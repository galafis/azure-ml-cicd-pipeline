"""
Shared Test Fixtures

Provides common fixtures and mocks for Azure ML pipeline testing.

Author: Gabriel Demetrios Lafis
"""

import os
import pytest
from unittest.mock import MagicMock, patch

from src.config.settings import (
    AzureMLConfig,
    TrainingConfig,
    DeploymentConfig,
    Environment,
)


# =============================================================================
# Environment Configuration Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def set_test_env_vars(monkeypatch):
    """Set required environment variables for all tests."""
    env_vars = {
        "AZURE_ML_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
        "AZURE_ML_RESOURCE_GROUP": "rg-ml-test",
        "AZURE_ML_WORKSPACE_NAME": "mlw-test",
        "AZURE_ML_TENANT_ID": "00000000-0000-0000-0000-000000000001",
        "AZURE_ML_REGION": "eastus2",
        "AZURE_ML_REGISTRY_NAME": "acr-test",
        "AZURE_ML_APP_INSIGHTS_KEY": "test-key-00000000",
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def azure_config() -> AzureMLConfig:
    """Create a test Azure ML configuration."""
    return AzureMLConfig(
        subscription_id="00000000-0000-0000-0000-000000000000",
        resource_group="rg-ml-test",
        workspace_name="mlw-test",
        tenant_id="00000000-0000-0000-0000-000000000001",
        environment=Environment.DEV,
        region="eastus2",
    )


@pytest.fixture
def staging_config() -> AzureMLConfig:
    """Create a staging Azure ML configuration."""
    return AzureMLConfig(
        subscription_id="00000000-0000-0000-0000-000000000000",
        resource_group="rg-ml-staging",
        workspace_name="mlw-staging",
        tenant_id="00000000-0000-0000-0000-000000000001",
        environment=Environment.STAGING,
        region="eastus2",
    )


@pytest.fixture
def prod_config() -> AzureMLConfig:
    """Create a production Azure ML configuration."""
    return AzureMLConfig(
        subscription_id="00000000-0000-0000-0000-000000000000",
        resource_group="rg-ml-prod",
        workspace_name="mlw-prod",
        tenant_id="00000000-0000-0000-0000-000000000001",
        environment=Environment.PROD,
        region="eastus2",
    )


@pytest.fixture
def training_config() -> TrainingConfig:
    """Create a test training configuration."""
    return TrainingConfig.for_environment(Environment.DEV)


@pytest.fixture
def deployment_config() -> DeploymentConfig:
    """Create a test deployment configuration."""
    return DeploymentConfig.for_environment(Environment.DEV)


# =============================================================================
# Mock Azure Clients
# =============================================================================


@pytest.fixture
def mock_credential():
    """Create a mock Azure credential."""
    return MagicMock()


@pytest.fixture
def mock_ml_client():
    """Create a mock Azure ML client."""
    client = MagicMock()

    # Mock jobs
    client.jobs.create_or_update.return_value = MagicMock(
        name="test-job-001",
        status="Completed",
        display_name="test-run",
    )
    client.jobs.get.return_value = MagicMock(
        name="test-job-001",
        status="Completed",
        display_name="test-run",
        properties={"metrics": {"accuracy": 0.9}},
    )

    # Mock models
    client.models.create_or_update.return_value = MagicMock(
        name="test-model",
        version="1",
    )
    client.models.get.return_value = MagicMock(
        name="test-model",
        version="1",
        tags={"metrics": '{"accuracy": 0.85}'},
    )

    # Mock compute
    client.compute.get.return_value = MagicMock(name="test-cluster")
    client.compute.begin_create_or_update.return_value = MagicMock(
        result=MagicMock(return_value=MagicMock(name="test-cluster"))
    )

    # Mock endpoints
    client.online_endpoints.get.return_value = MagicMock(
        name="test-endpoint",
        provisioning_state="Succeeded",
        scoring_uri="https://test-endpoint.eastus2.inference.ml.azure.com/score",
        traffic={"default": 100},
    )
    client.online_endpoints.begin_create_or_update.return_value = MagicMock(
        result=MagicMock(return_value=MagicMock(name="test-endpoint"))
    )

    # Mock deployments
    client.online_deployments.list.return_value = []
    client.online_deployments.begin_create_or_update.return_value = MagicMock(
        result=MagicMock(return_value=MagicMock(name="test-deployment"))
    )

    # Mock environments
    client.environments.create_or_update.return_value = MagicMock(
        name="test-env",
        version="1",
    )

    # Mock data
    client.data.create_or_update.return_value = MagicMock(
        name="test-data",
        version="1",
        type="uri_folder",
        path="/test/path",
    )
    client.data.get.return_value = MagicMock(
        name="test-data",
        version="1",
        type="uri_folder",
        path="/test/path",
    )
    client.data.list.return_value = [
        MagicMock(name="test-data", version="1"),
        MagicMock(name="test-data", version="2"),
    ]

    return client


# =============================================================================
# Sample Data Fixtures
# =============================================================================


@pytest.fixture
def sample_metrics() -> dict:
    """Sample model evaluation metrics."""
    return {
        "accuracy": 0.92,
        "f1_score": 0.89,
        "precision": 0.90,
        "recall": 0.88,
        "loss": 0.18,
    }


@pytest.fixture
def poor_metrics() -> dict:
    """Sample metrics that fail quality gates."""
    return {
        "accuracy": 0.55,
        "f1_score": 0.50,
        "precision": 0.52,
        "recall": 0.48,
        "loss": 1.5,
    }


@pytest.fixture
def champion_metrics() -> dict:
    """Sample champion model metrics for comparison."""
    return {
        "accuracy": 0.88,
        "f1_score": 0.85,
        "precision": 0.87,
        "recall": 0.83,
        "loss": 0.25,
    }
