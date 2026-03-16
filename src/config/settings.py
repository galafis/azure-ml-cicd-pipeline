"""
Configuration Settings

Pydantic-based configuration classes for Azure ML pipeline settings
with multi-environment support (dev, staging, prod).

Author: Gabriel Demetrios Lafis
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field


class Environment(str, Enum):
    """Deployment environment enumeration."""
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


@dataclass(frozen=True)
class AzureMLConfig:
    """
    Azure ML workspace configuration.

    Holds connection details for Azure ML workspace, subscription,
    and resource group scoped by deployment environment.
    """

    subscription_id: str
    resource_group: str
    workspace_name: str
    tenant_id: str
    environment: Environment = Environment.DEV
    region: str = "eastus2"
    registry_name: Optional[str] = None
    application_insights_key: Optional[str] = None

    @classmethod
    def from_environment(cls, env: Environment | str = Environment.DEV) -> AzureMLConfig:
        """
        Load configuration from environment variables.

        Args:
            env: Target environment (dev, staging, prod).

        Returns:
            AzureMLConfig populated from environment variables.

        Raises:
            ValueError: If required environment variables are missing.
        """
        if isinstance(env, str):
            env = Environment(env)

        prefix = f"AZURE_ML_{env.value.upper()}_"
        fallback_prefix = "AZURE_ML_"

        def get_var(name: str, required: bool = True) -> Optional[str]:
            value = os.getenv(f"{prefix}{name}") or os.getenv(f"{fallback_prefix}{name}")
            if required and not value:
                raise ValueError(
                    f"Required environment variable {prefix}{name} or "
                    f"{fallback_prefix}{name} is not set."
                )
            return value

        return cls(
            subscription_id=get_var("SUBSCRIPTION_ID"),
            resource_group=get_var("RESOURCE_GROUP"),
            workspace_name=get_var("WORKSPACE_NAME"),
            tenant_id=get_var("TENANT_ID"),
            environment=env,
            region=get_var("REGION", required=False) or "eastus2",
            registry_name=get_var("REGISTRY_NAME", required=False),
            application_insights_key=get_var("APP_INSIGHTS_KEY", required=False),
        )


@dataclass
class TrainingConfig:
    """
    Training job configuration.

    Defines compute targets, experiment parameters, and HyperDrive
    settings for Azure ML training jobs.
    """

    experiment_name: str = "ml-training-experiment"
    compute_target: str = "cpu-cluster"
    vm_size: str = "Standard_DS3_v2"
    min_nodes: int = 0
    max_nodes: int = 4
    environment_name: str = "ml-training-env"
    max_epochs: int = 100
    batch_size: int = 32
    learning_rate: float = 0.001
    early_stopping_patience: int = 10
    enable_hyperdrive: bool = False
    hyperdrive_max_total_runs: int = 20
    hyperdrive_max_concurrent_runs: int = 4
    hyperdrive_primary_metric: str = "accuracy"
    hyperdrive_goal: str = "maximize"
    tags: dict[str, str] = field(default_factory=dict)
    timeout_minutes: int = 120

    @classmethod
    def for_environment(cls, env: Environment) -> TrainingConfig:
        """
        Get environment-specific training configuration.

        Args:
            env: Target environment.

        Returns:
            TrainingConfig tuned for the specified environment.
        """
        env_configs = {
            Environment.DEV: cls(
                compute_target="dev-cpu-cluster",
                vm_size="Standard_DS2_v2",
                max_nodes=2,
                max_epochs=10,
                timeout_minutes=30,
                tags={"environment": "dev"},
            ),
            Environment.STAGING: cls(
                compute_target="staging-cpu-cluster",
                vm_size="Standard_DS3_v2",
                max_nodes=4,
                max_epochs=50,
                timeout_minutes=60,
                tags={"environment": "staging"},
            ),
            Environment.PROD: cls(
                compute_target="prod-gpu-cluster",
                vm_size="Standard_NC6s_v3",
                max_nodes=8,
                max_epochs=100,
                enable_hyperdrive=True,
                timeout_minutes=180,
                tags={"environment": "prod"},
            ),
        }
        return env_configs.get(env, cls())


@dataclass
class DeploymentConfig:
    """
    Deployment configuration for managed online endpoints.

    Defines endpoint settings, scaling parameters, and traffic
    routing rules for blue-green deployment strategies.
    """

    endpoint_name: str = "ml-model-endpoint"
    deployment_name: str = "ml-model-deployment"
    instance_type: str = "Standard_DS2_v2"
    instance_count: int = 1
    min_instances: int = 1
    max_instances: int = 5
    scale_type: str = "default"
    request_timeout_ms: int = 60000
    max_concurrent_requests: int = 100
    liveness_probe_period: int = 10
    readiness_probe_period: int = 10
    traffic_percentile: int = 0
    blue_green_enabled: bool = True
    rollback_on_failure: bool = True
    scoring_script: str = "score.py"
    environment_name: str = "ml-inference-env"
    tags: dict[str, str] = field(default_factory=dict)

    @classmethod
    def for_environment(cls, env: Environment) -> DeploymentConfig:
        """
        Get environment-specific deployment configuration.

        Args:
            env: Target environment.

        Returns:
            DeploymentConfig tuned for the specified environment.
        """
        env_configs = {
            Environment.DEV: cls(
                endpoint_name="ml-endpoint-dev",
                instance_type="Standard_DS1_v2",
                instance_count=1,
                max_instances=2,
                traffic_percentile=100,
                blue_green_enabled=False,
                tags={"environment": "dev"},
            ),
            Environment.STAGING: cls(
                endpoint_name="ml-endpoint-staging",
                instance_type="Standard_DS2_v2",
                instance_count=2,
                max_instances=4,
                traffic_percentile=100,
                blue_green_enabled=True,
                tags={"environment": "staging"},
            ),
            Environment.PROD: cls(
                endpoint_name="ml-endpoint-prod",
                instance_type="Standard_DS3_v2",
                instance_count=3,
                max_instances=10,
                traffic_percentile=0,
                blue_green_enabled=True,
                rollback_on_failure=True,
                tags={"environment": "prod"},
            ),
        }
        return env_configs.get(env, cls())


@dataclass(frozen=True)
class PipelineSettings:
    """
    Aggregate pipeline settings combining all configuration sections.

    Provides a single entry point for accessing all pipeline-related
    configuration from a unified environment context.
    """

    azure_ml: AzureMLConfig
    training: TrainingConfig
    deployment: DeploymentConfig
    environment: Environment

    @classmethod
    def load(cls, env: Environment | str = Environment.DEV) -> PipelineSettings:
        """
        Load complete pipeline settings for a given environment.

        Args:
            env: Target environment (dev, staging, prod).

        Returns:
            Fully initialized PipelineSettings.
        """
        if isinstance(env, str):
            env = Environment(env)

        return cls(
            azure_ml=AzureMLConfig.from_environment(env),
            training=TrainingConfig.for_environment(env),
            deployment=DeploymentConfig.for_environment(env),
            environment=env,
        )
