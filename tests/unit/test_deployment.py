"""
Unit Tests - Endpoint Manager & Environment Promoter

Author: Gabriel Demetrios Lafis
"""

import pytest
from unittest.mock import MagicMock, patch

from src.deployment.endpoint_manager import EndpointManager
from src.deployment.environment_promoter import EnvironmentPromoter, PromotionRecord
from src.config.settings import AzureMLConfig, DeploymentConfig, Environment


class TestEndpointManager:
    """Tests for EndpointManager class."""

    @pytest.fixture
    def manager(self, azure_config, deployment_config, mock_credential, mock_ml_client):
        manager = EndpointManager(azure_config, deployment_config, mock_credential)
        manager._client = mock_ml_client
        return manager

    def test_initialization(self, azure_config, deployment_config, mock_credential):
        """Test endpoint manager initializes correctly."""
        manager = EndpointManager(azure_config, deployment_config, mock_credential)
        assert manager.deployment_config == deployment_config
        assert manager._client is None

    def test_create_or_update_endpoint(self, manager, mock_ml_client):
        """Test endpoint creation."""
        result = manager.create_or_update_endpoint()
        mock_ml_client.online_endpoints.begin_create_or_update.assert_called_once()

    def test_create_deployment(self, manager, mock_ml_client):
        """Test deployment creation."""
        result = manager.create_deployment(
            model_name="test-model",
            model_version="1",
            traffic_percent=100,
        )
        mock_ml_client.online_deployments.begin_create_or_update.assert_called_once()

    def test_get_endpoint_status(self, manager, mock_ml_client):
        """Test endpoint status retrieval."""
        status = manager.get_endpoint_status()
        assert "endpoint_name" in status
        assert status["endpoint_name"] == "test-endpoint"

    def test_update_traffic(self, manager, mock_ml_client):
        """Test traffic update."""
        manager.update_traffic({"blue": 80, "green": 20})
        mock_ml_client.online_endpoints.begin_create_or_update.assert_called()

    def test_deployment_config_per_environment(self):
        """Test that deployment configs differ by environment."""
        dev_config = DeploymentConfig.for_environment(Environment.DEV)
        prod_config = DeploymentConfig.for_environment(Environment.PROD)

        assert dev_config.instance_count < prod_config.instance_count
        assert dev_config.max_instances < prod_config.max_instances
        assert prod_config.blue_green_enabled is True
        assert dev_config.blue_green_enabled is False

    def test_delete_endpoint(self, manager, mock_ml_client):
        """Test endpoint deletion."""
        mock_ml_client.online_endpoints.begin_delete.return_value = MagicMock(
            result=MagicMock(return_value=None)
        )
        manager.delete_endpoint()
        mock_ml_client.online_endpoints.begin_delete.assert_called_once()


class TestEnvironmentPromoter:
    """Tests for EnvironmentPromoter class."""

    @pytest.fixture
    def promoter(self, staging_config, prod_config, mock_credential, mock_ml_client):
        promoter = EnvironmentPromoter(
            source_config=staging_config,
            target_config=prod_config,
            credential=mock_credential,
            audit_dir="test_audit",
        )
        promoter._source_client = mock_ml_client
        promoter._target_client = mock_ml_client
        return promoter

    def test_initialization(self, staging_config, prod_config, mock_credential):
        """Test promoter initializes with correct promotion path."""
        promoter = EnvironmentPromoter(
            source_config=staging_config,
            target_config=prod_config,
            credential=mock_credential,
        )
        assert promoter.promotion_path == (Environment.STAGING, Environment.PROD)

    def test_promote_model_all_gates_pass(
        self, promoter, sample_metrics, champion_metrics, tmp_path
    ):
        """Test successful model promotion when all gates pass."""
        promoter.audit_dir = tmp_path / "audit"

        record = promoter.promote_model(
            model_name="test-model",
            model_version="1",
            metrics=sample_metrics,
            champion_metrics=champion_metrics,
            approved=True,
            integration_tests_passed=True,
        )

        assert record.promoted is True
        assert record.model_name == "test-model"

    def test_promote_model_missing_approval(
        self, promoter, sample_metrics, champion_metrics, tmp_path
    ):
        """Test promotion blocked when manual approval is missing."""
        promoter.audit_dir = tmp_path / "audit"

        record = promoter.promote_model(
            model_name="test-model",
            model_version="1",
            metrics=sample_metrics,
            champion_metrics=champion_metrics,
            approved=False,
            integration_tests_passed=True,
        )

        assert record.promoted is False
        failed_gates = [g.name for g in record.gates if not g.passed]
        assert "manual_approval" in failed_gates

    def test_promote_model_failed_integration_tests(
        self, promoter, sample_metrics, tmp_path
    ):
        """Test promotion blocked when integration tests fail."""
        promoter.audit_dir = tmp_path / "audit"

        record = promoter.promote_model(
            model_name="test-model",
            model_version="1",
            metrics=sample_metrics,
            approved=True,
            integration_tests_passed=False,
        )

        assert record.promoted is False

    def test_audit_log_saved(
        self, promoter, sample_metrics, champion_metrics, tmp_path
    ):
        """Test that audit log is persisted."""
        promoter.audit_dir = tmp_path / "audit"

        promoter.promote_model(
            model_name="test-model",
            model_version="1",
            metrics=sample_metrics,
            champion_metrics=champion_metrics,
            approved=True,
            integration_tests_passed=True,
        )

        audit_files = list((tmp_path / "audit").glob("promotion_*.json"))
        assert len(audit_files) == 1

    def test_promotion_record_serialization(self):
        """Test PromotionRecord to_dict serialization."""
        record = PromotionRecord(
            model_name="test",
            model_version="1",
            source_environment=Environment.STAGING,
            target_environment=Environment.PROD,
            promoted=True,
        )
        data = record.to_dict()
        assert data["model_name"] == "test"
        assert data["source_environment"] == "staging"
        assert data["target_environment"] == "prod"
