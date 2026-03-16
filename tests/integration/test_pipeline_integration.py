"""
Integration Tests - End-to-End Pipeline Flow

Tests the complete pipeline integration from configuration loading
through training, evaluation, and deployment promotion.

Requires Azure credentials and workspace connectivity.

Author: Gabriel Demetrios Lafis
"""

import os
import pytest
from unittest.mock import MagicMock, patch

from src.config.settings import (
    AzureMLConfig,
    TrainingConfig,
    DeploymentConfig,
    PipelineSettings,
    Environment,
)
from src.evaluation.model_evaluator import ModelEvaluator, QualityGate
from src.deployment.environment_promoter import EnvironmentPromoter
from src.monitoring.app_insights import AppInsightsMonitor


class TestPipelineSettingsIntegration:
    """Test full pipeline settings loading."""

    def test_load_dev_settings(self):
        """Test loading dev environment settings."""
        settings = PipelineSettings.load(Environment.DEV)

        assert settings.environment == Environment.DEV
        assert settings.azure_ml.environment == Environment.DEV
        assert settings.training.compute_target == "dev-cpu-cluster"
        assert settings.deployment.blue_green_enabled is False

    def test_load_staging_settings(self):
        """Test loading staging environment settings."""
        settings = PipelineSettings.load(Environment.STAGING)

        assert settings.environment == Environment.STAGING
        assert settings.training.max_epochs == 50
        assert settings.deployment.blue_green_enabled is True

    def test_load_prod_settings(self):
        """Test loading prod environment settings."""
        settings = PipelineSettings.load(Environment.PROD)

        assert settings.environment == Environment.PROD
        assert settings.training.enable_hyperdrive is True
        assert settings.deployment.rollback_on_failure is True

    def test_load_settings_from_string(self):
        """Test loading settings with string environment name."""
        settings = PipelineSettings.load("dev")
        assert settings.environment == Environment.DEV


class TestEndToEndEvaluationFlow:
    """Test the evaluation and promotion flow end-to-end."""

    @pytest.fixture
    def dev_evaluator(self, azure_config, mock_credential, mock_ml_client):
        evaluator = ModelEvaluator(azure_config, mock_credential)
        evaluator._client = mock_ml_client
        return evaluator

    @pytest.fixture
    def prod_evaluator(self, prod_config, mock_credential, mock_ml_client):
        evaluator = ModelEvaluator(prod_config, mock_credential)
        evaluator._client = mock_ml_client
        return evaluator

    def test_evaluation_quality_gate_escalation(
        self, dev_evaluator, prod_evaluator, sample_metrics
    ):
        """Test that prod has stricter gates than dev."""
        dev_result = dev_evaluator.evaluate_model("model", "1", sample_metrics)
        prod_result = prod_evaluator.evaluate_model("model", "1", sample_metrics)

        # Both should pass with good metrics
        assert dev_result.passed_all_gates is True
        assert prod_result.passed_all_gates is True

        # Prod should evaluate more gates
        assert len(prod_result.gate_results) >= len(dev_result.gate_results)

    def test_failing_model_blocks_promotion(
        self, poor_metrics, staging_config, prod_config, mock_credential, mock_ml_client, tmp_path
    ):
        """Test that a failing model is blocked from promotion."""
        promoter = EnvironmentPromoter(
            source_config=staging_config,
            target_config=prod_config,
            credential=mock_credential,
            audit_dir=str(tmp_path / "audit"),
        )
        promoter._source_client = mock_ml_client
        promoter._target_client = mock_ml_client

        record = promoter.promote_model(
            model_name="bad-model",
            model_version="1",
            metrics=poor_metrics,
            approved=True,
            integration_tests_passed=True,
        )

        assert record.promoted is False

    def test_full_promotion_pipeline(
        self,
        sample_metrics,
        champion_metrics,
        staging_config,
        prod_config,
        mock_credential,
        mock_ml_client,
        tmp_path,
    ):
        """Test full promotion pipeline from staging to prod."""
        promoter = EnvironmentPromoter(
            source_config=staging_config,
            target_config=prod_config,
            credential=mock_credential,
            audit_dir=str(tmp_path / "audit"),
        )
        promoter._source_client = mock_ml_client
        promoter._target_client = mock_ml_client

        record = promoter.promote_model(
            model_name="good-model",
            model_version="3",
            metrics=sample_metrics,
            champion_metrics=champion_metrics,
            approved=True,
            integration_tests_passed=True,
        )

        assert record.promoted is True
        assert record.source_environment == Environment.STAGING
        assert record.target_environment == Environment.PROD

        # Verify audit trail
        history = promoter.get_promotion_history("good-model")
        assert len(history) == 1
        assert history[0]["promoted"] is True


class TestMonitoringIntegration:
    """Test monitoring telemetry integration."""

    def test_track_training_metrics(self, sample_metrics):
        """Test tracking training metrics."""
        monitor = AppInsightsMonitor(enable_telemetry=False)
        monitor.track_training_metrics("test-model", "1", sample_metrics, "dev")

        buffer = monitor.get_metrics_buffer()
        assert len(buffer) == len(sample_metrics)

    def test_track_dependency(self):
        """Test dependency tracking context manager."""
        monitor = AppInsightsMonitor(enable_telemetry=False)

        with monitor.track_dependency("AzureML", "submit_job") as ctx:
            pass  # Simulate dependency call

        assert ctx["success"] is True
        assert "duration_ms" in ctx

    def test_track_exception(self):
        """Test exception tracking."""
        monitor = AppInsightsMonitor(enable_telemetry=False)
        monitor.track_exception(ValueError("test error"), {"context": "unit_test"})

        buffer = monitor.get_metrics_buffer()
        exception_entries = [e for e in buffer if "exceptions" in e["name"]]
        assert len(exception_entries) == 1

    def test_track_deployment_event(self):
        """Test deployment event tracking."""
        monitor = AppInsightsMonitor(enable_telemetry=False)
        monitor.track_deployment_event(
            event_type="deploy",
            model_name="test-model",
            model_version="1",
            environment="staging",
        )

        buffer = monitor.get_metrics_buffer()
        assert any("deployment" in e["name"] for e in buffer)
