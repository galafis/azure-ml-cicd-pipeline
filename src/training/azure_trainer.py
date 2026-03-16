"""
Azure ML Trainer

Submits training jobs to Azure ML compute clusters with experiment
tracking, HyperDrive hyperparameter optimization, and distributed
training support.

Author: Gabriel Demetrios Lafis
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from azure.ai.ml import MLClient, command, Input
from azure.ai.ml.entities import (
    AmlCompute,
    Environment as AzureMLEnvironment,
    Model,
)
from azure.ai.ml.sweep import (
    Choice,
    Uniform,
    BanditPolicy,
    SweepJob,
)
from azure.identity import DefaultAzureCredential

from src.config.settings import AzureMLConfig, TrainingConfig, Environment
from src.utils.logger import get_logger

logger = get_logger("azure_trainer")


class AzureMLTrainer:
    """
    Manages training job lifecycle on Azure ML compute clusters.

    Provides methods for submitting single training jobs, HyperDrive
    sweeps, experiment tracking, and model registration.

    Usage:
        config = AzureMLConfig.from_environment(Environment.DEV)
        training_config = TrainingConfig.for_environment(Environment.DEV)
        trainer = AzureMLTrainer(config, training_config)
        job = trainer.submit_training_job("./train.py", "training-data:1")
    """

    def __init__(
        self,
        azure_config: AzureMLConfig,
        training_config: TrainingConfig,
        credential: Optional[Any] = None,
    ):
        """
        Initialize Azure ML Trainer.

        Args:
            azure_config: Azure ML workspace configuration.
            training_config: Training job parameters.
            credential: Azure credential. Defaults to DefaultAzureCredential.
        """
        self.azure_config = azure_config
        self.training_config = training_config
        self.credential = credential or DefaultAzureCredential()
        self._client: Optional[MLClient] = None

        logger.info(
            "AzureMLTrainer initialized for workspace=%s, env=%s",
            azure_config.workspace_name,
            azure_config.environment.value,
        )

    @property
    def client(self) -> MLClient:
        """Lazy-initialized Azure ML client."""
        if self._client is None:
            self._client = MLClient(
                credential=self.credential,
                subscription_id=self.azure_config.subscription_id,
                resource_group_name=self.azure_config.resource_group,
                workspace_name=self.azure_config.workspace_name,
            )
            logger.info("MLClient connected to workspace: %s", self.azure_config.workspace_name)
        return self._client

    def ensure_compute_cluster(self) -> AmlCompute:
        """
        Ensure the compute cluster exists, creating it if necessary.

        Returns:
            The compute cluster resource.
        """
        compute_name = self.training_config.compute_target
        try:
            compute = self.client.compute.get(compute_name)
            logger.info("Compute cluster '%s' already exists.", compute_name)
            return compute
        except Exception:
            logger.info("Creating compute cluster '%s'...", compute_name)

        compute = AmlCompute(
            name=compute_name,
            type="amlcompute",
            size=self.training_config.vm_size,
            min_instances=self.training_config.min_nodes,
            max_instances=self.training_config.max_nodes,
            idle_time_before_scale_down=120,
            tier="Dedicated",
            tags=self.training_config.tags,
        )

        operation = self.client.compute.begin_create_or_update(compute)
        result = operation.result()
        logger.info("Compute cluster '%s' created successfully.", compute_name)
        return result

    def create_environment(
        self,
        conda_file: Optional[str] = None,
        docker_image: Optional[str] = None,
    ) -> AzureMLEnvironment:
        """
        Create or retrieve a training environment.

        Args:
            conda_file: Path to conda environment YAML.
            docker_image: Base Docker image for the environment.

        Returns:
            Azure ML Environment resource.
        """
        env_name = self.training_config.environment_name

        if docker_image:
            environment = AzureMLEnvironment(
                name=env_name,
                image=docker_image,
                conda_file=conda_file,
                tags=self.training_config.tags,
            )
        else:
            environment = AzureMLEnvironment(
                name=env_name,
                image="mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu20.04:latest",
                conda_file=conda_file or "environment.yml",
                tags=self.training_config.tags,
            )

        environment = self.client.environments.create_or_update(environment)
        logger.info("Environment '%s' registered (version: %s).", env_name, environment.version)
        return environment

    def submit_training_job(
        self,
        training_script: str,
        data_input: str,
        experiment_name: Optional[str] = None,
        display_name: Optional[str] = None,
        additional_args: Optional[dict[str, Any]] = None,
    ) -> Any:
        """
        Submit a training job to the Azure ML compute cluster.

        Args:
            training_script: Path to the training script.
            data_input: Data asset URI or registered dataset reference.
            experiment_name: Override experiment name.
            display_name: Display name for the job run.
            additional_args: Extra command-line arguments for the script.

        Returns:
            The submitted job object with tracking information.
        """
        experiment = experiment_name or self.training_config.experiment_name
        config = self.training_config

        cmd_args = (
            f"--data-path ${{{{inputs.training_data}}}} "
            f"--epochs {config.max_epochs} "
            f"--batch-size {config.batch_size} "
            f"--learning-rate {config.learning_rate} "
            f"--early-stopping-patience {config.early_stopping_patience}"
        )

        if additional_args:
            for key, value in additional_args.items():
                cmd_args += f" --{key} {value}"

        job = command(
            code=str(Path(training_script).parent),
            command=f"python {Path(training_script).name} {cmd_args}",
            inputs={"training_data": Input(type="uri_folder", path=data_input)},
            environment=f"{config.environment_name}@latest",
            compute=config.compute_target,
            experiment_name=experiment,
            display_name=display_name or f"{experiment}-run",
            tags={**config.tags, "script": training_script},
            timeout=config.timeout_minutes * 60,
        )

        submitted_job = self.client.jobs.create_or_update(job)
        logger.info(
            "Training job submitted: name=%s, experiment=%s, compute=%s",
            submitted_job.name,
            experiment,
            config.compute_target,
        )
        return submitted_job

    def submit_hyperdrive_sweep(
        self,
        training_script: str,
        data_input: str,
        search_space: Optional[dict[str, Any]] = None,
        experiment_name: Optional[str] = None,
    ) -> SweepJob:
        """
        Submit a HyperDrive hyperparameter sweep job.

        Args:
            training_script: Path to the training script.
            data_input: Data asset URI or registered dataset reference.
            search_space: Custom hyperparameter search space.
            experiment_name: Override experiment name.

        Returns:
            The submitted sweep job with tracking information.
        """
        config = self.training_config
        experiment = experiment_name or f"{config.experiment_name}-sweep"

        base_job = command(
            code=str(Path(training_script).parent),
            command=(
                f"python {Path(training_script).name} "
                "--data-path ${{inputs.training_data}} "
                "--learning-rate ${{search_space.learning_rate}} "
                "--batch-size ${{search_space.batch_size}} "
                "--epochs ${{search_space.epochs}}"
            ),
            inputs={"training_data": Input(type="uri_folder", path=data_input)},
            environment=f"{config.environment_name}@latest",
            compute=config.compute_target,
            tags=config.tags,
        )

        default_search_space = search_space or {
            "learning_rate": Uniform(min_value=0.0001, max_value=0.01),
            "batch_size": Choice(values=[16, 32, 64, 128]),
            "epochs": Choice(values=[25, 50, 100]),
        }

        sweep_job = base_job.sweep(
            sampling_algorithm="bayesian",
            primary_metric=config.hyperdrive_primary_metric,
            goal=config.hyperdrive_goal,
            search_space=default_search_space,
            early_termination=BanditPolicy(
                slack_factor=0.15,
                evaluation_interval=2,
                delay_evaluation=5,
            ),
            max_total_trials=config.hyperdrive_max_total_runs,
            max_concurrent_trials=config.hyperdrive_max_concurrent_runs,
        )

        sweep_job.experiment_name = experiment
        sweep_job.display_name = f"{experiment}-sweep"

        submitted_sweep = self.client.jobs.create_or_update(sweep_job)
        logger.info(
            "HyperDrive sweep submitted: name=%s, max_trials=%d, metric=%s",
            submitted_sweep.name,
            config.hyperdrive_max_total_runs,
            config.hyperdrive_primary_metric,
        )
        return submitted_sweep

    def register_model(
        self,
        job_name: str,
        model_name: str,
        model_path: str = "outputs/model",
        description: Optional[str] = None,
        tags: Optional[dict[str, str]] = None,
    ) -> Model:
        """
        Register a trained model from a completed job.

        Args:
            job_name: Name of the completed training job.
            model_name: Name for the registered model.
            model_path: Path within job outputs to the model artifact.
            description: Model description.
            tags: Additional metadata tags.

        Returns:
            Registered Model resource.
        """
        model = Model(
            path=f"azureml://jobs/{job_name}/outputs/artifacts/{model_path}",
            name=model_name,
            description=description or f"Model trained by job {job_name}",
            type="mlflow_model",
            tags={**self.training_config.tags, **(tags or {})},
        )

        registered = self.client.models.create_or_update(model)
        logger.info(
            "Model registered: name=%s, version=%s",
            registered.name,
            registered.version,
        )
        return registered

    def get_job_metrics(self, job_name: str) -> dict[str, Any]:
        """
        Retrieve metrics from a completed training job.

        Args:
            job_name: Name of the training job.

        Returns:
            Dictionary of metric name-value pairs.
        """
        job = self.client.jobs.get(job_name)
        logger.info("Retrieved job '%s' (status: %s)", job_name, job.status)

        if hasattr(job, "properties") and "metrics" in job.properties:
            return job.properties["metrics"]

        return {"status": job.status, "display_name": job.display_name}

    def wait_for_completion(self, job_name: str, timeout: int = 7200) -> str:
        """
        Wait for a job to complete.

        Args:
            job_name: Name of the job to monitor.
            timeout: Maximum wait time in seconds.

        Returns:
            Final job status string.
        """
        import time

        start_time = time.time()

        while time.time() - start_time < timeout:
            job = self.client.jobs.get(job_name)
            status = job.status

            if status in ("Completed", "Failed", "Canceled"):
                logger.info("Job '%s' finished with status: %s", job_name, status)
                return status

            logger.info("Job '%s' status: %s (elapsed: %.0fs)", job_name, status, time.time() - start_time)
            time.sleep(30)

        logger.warning("Job '%s' timed out after %ds", job_name, timeout)
        return "Timeout"
