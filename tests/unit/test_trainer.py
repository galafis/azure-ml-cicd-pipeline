"""
Unit Tests - Azure ML Trainer

Author: Gabriel Demetrios Lafis
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from src.training.azure_trainer import AzureMLTrainer
from src.config.settings import AzureMLConfig, TrainingConfig, Environment


class TestAzureMLTrainer:
    """Tests for AzureMLTrainer class."""

    @pytest.fixture
    def trainer(self, azure_config, training_config, mock_credential, mock_ml_client):
        """Create a trainer with mocked dependencies."""
        trainer = AzureMLTrainer(azure_config, training_config, mock_credential)
        trainer._client = mock_ml_client
        return trainer

    def test_initialization(self, azure_config, training_config, mock_credential):
        """Test trainer initializes correctly."""
        trainer = AzureMLTrainer(azure_config, training_config, mock_credential)
        assert trainer.azure_config == azure_config
        assert trainer.training_config == training_config
        assert trainer._client is None

    def test_ensure_compute_cluster_exists(self, trainer, mock_ml_client):
        """Test compute cluster detection when it already exists."""
        mock_ml_client.compute.get.return_value = MagicMock(name="dev-cpu-cluster")
        result = trainer.ensure_compute_cluster()
        assert result is not None
        mock_ml_client.compute.get.assert_called_once()

    def test_ensure_compute_cluster_creates_new(self, trainer, mock_ml_client):
        """Test compute cluster creation when it does not exist."""
        mock_ml_client.compute.get.side_effect = Exception("Not found")
        mock_operation = MagicMock()
        mock_operation.result.return_value = MagicMock(name="dev-cpu-cluster")
        mock_ml_client.compute.begin_create_or_update.return_value = mock_operation

        result = trainer.ensure_compute_cluster()
        mock_ml_client.compute.begin_create_or_update.assert_called_once()

    def test_submit_training_job(self, trainer, mock_ml_client):
        """Test training job submission."""
        job = trainer.submit_training_job(
            training_script="./train.py",
            data_input="azureml:training-data:1",
            experiment_name="test-experiment",
        )
        assert job is not None
        mock_ml_client.jobs.create_or_update.assert_called_once()

    def test_submit_training_job_with_additional_args(self, trainer, mock_ml_client):
        """Test training job submission with extra arguments."""
        job = trainer.submit_training_job(
            training_script="./train.py",
            data_input="azureml:training-data:1",
            additional_args={"optimizer": "adam", "dropout": 0.3},
        )
        assert job is not None
        mock_ml_client.jobs.create_or_update.assert_called_once()

    def test_register_model(self, trainer, mock_ml_client):
        """Test model registration from a completed job."""
        model = trainer.register_model(
            job_name="test-job-001",
            model_name="test-model",
            description="Test model",
        )
        assert model is not None
        mock_ml_client.models.create_or_update.assert_called_once()

    def test_get_job_metrics(self, trainer, mock_ml_client):
        """Test retrieval of job metrics."""
        metrics = trainer.get_job_metrics("test-job-001")
        assert isinstance(metrics, dict)
        mock_ml_client.jobs.get.assert_called_once_with("test-job-001")

    def test_create_environment(self, trainer, mock_ml_client):
        """Test training environment creation."""
        env = trainer.create_environment(docker_image="mcr.microsoft.com/azureml/base:latest")
        assert env is not None
        mock_ml_client.environments.create_or_update.assert_called_once()

    def test_training_config_per_environment(self):
        """Test that training configs differ by environment."""
        dev_config = TrainingConfig.for_environment(Environment.DEV)
        prod_config = TrainingConfig.for_environment(Environment.PROD)

        assert dev_config.max_nodes < prod_config.max_nodes
        assert dev_config.max_epochs < prod_config.max_epochs
        assert prod_config.enable_hyperdrive is True
        assert dev_config.enable_hyperdrive is False
