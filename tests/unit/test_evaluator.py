"""
Unit Tests - Model Evaluator

Author: Gabriel Demetrios Lafis
"""

import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock

from src.evaluation.model_evaluator import (
    ModelEvaluator,
    QualityGate,
    EvaluationResult,
)
from src.config.settings import AzureMLConfig, Environment


class TestQualityGate:
    """Tests for QualityGate class."""

    def test_gte_comparison_pass(self):
        gate = QualityGate("accuracy", 0.80, "gte")
        assert gate.evaluate(0.85) is True

    def test_gte_comparison_fail(self):
        gate = QualityGate("accuracy", 0.80, "gte")
        assert gate.evaluate(0.75) is False

    def test_lte_comparison_pass(self):
        gate = QualityGate("loss", 0.5, "lte")
        assert gate.evaluate(0.3) is True

    def test_lte_comparison_fail(self):
        gate = QualityGate("loss", 0.5, "lte")
        assert gate.evaluate(0.8) is False

    def test_gt_comparison(self):
        gate = QualityGate("metric", 0.80, "gt")
        assert gate.evaluate(0.81) is True
        assert gate.evaluate(0.80) is False

    def test_lt_comparison(self):
        gate = QualityGate("metric", 0.80, "lt")
        assert gate.evaluate(0.79) is True
        assert gate.evaluate(0.80) is False

    def test_eq_comparison(self):
        gate = QualityGate("metric", 1.0, "eq")
        assert gate.evaluate(1.0) is True
        assert gate.evaluate(1.1) is False


class TestModelEvaluator:
    """Tests for ModelEvaluator class."""

    @pytest.fixture
    def evaluator(self, azure_config, mock_credential, mock_ml_client):
        evaluator = ModelEvaluator(azure_config, mock_credential)
        evaluator._client = mock_ml_client
        return evaluator

    @pytest.fixture
    def prod_evaluator(self, prod_config, mock_credential, mock_ml_client):
        evaluator = ModelEvaluator(prod_config, mock_credential)
        evaluator._client = mock_ml_client
        return evaluator

    def test_initialization_dev(self, evaluator):
        """Test evaluator initializes with dev quality gates."""
        assert len(evaluator.quality_gates) > 0
        gate_names = [g.metric_name for g in evaluator.quality_gates]
        assert "accuracy" in gate_names

    def test_initialization_prod(self, prod_evaluator):
        """Test evaluator initializes with stricter prod quality gates."""
        assert len(prod_evaluator.quality_gates) >= 4
        gate_names = [g.metric_name for g in prod_evaluator.quality_gates]
        assert "accuracy" in gate_names
        assert "f1_score" in gate_names
        assert "precision" in gate_names

    def test_add_quality_gate(self, evaluator):
        """Test adding a custom quality gate."""
        initial_count = len(evaluator.quality_gates)
        evaluator.add_quality_gate(QualityGate("custom_metric", 0.90, "gte"))
        assert len(evaluator.quality_gates) == initial_count + 1

    def test_evaluate_model_passes(self, evaluator, sample_metrics):
        """Test model evaluation that passes all gates."""
        result = evaluator.evaluate_model("my-model", "1", sample_metrics)
        assert result.passed_all_gates is True
        assert result.model_name == "my-model"
        assert result.model_version == "1"

    def test_evaluate_model_fails(self, evaluator, poor_metrics):
        """Test model evaluation that fails quality gates."""
        result = evaluator.evaluate_model("my-model", "1", poor_metrics)
        assert result.passed_all_gates is False

    def test_evaluate_model_prod_strict(self, prod_evaluator, sample_metrics):
        """Test prod evaluation with stricter thresholds."""
        result = prod_evaluator.evaluate_model("my-model", "1", sample_metrics)
        assert result.passed_all_gates is True

    def test_evaluate_with_champion_comparison(self, evaluator, sample_metrics, champion_metrics):
        """Test evaluation with champion model comparison."""
        result = evaluator.evaluate_model(
            "my-model", "1", sample_metrics, champion_metrics
        )
        assert "challenger_better" in result.champion_comparison
        assert result.champion_comparison["challenger_better"] is True

    def test_champion_comparison_regression(self, evaluator, poor_metrics, champion_metrics):
        """Test evaluation where challenger is worse than champion."""
        result = evaluator.evaluate_model(
            "my-model", "1", poor_metrics, champion_metrics
        )
        assert result.champion_comparison.get("challenger_better") is False

    def test_save_evaluation_artifacts(self, evaluator, sample_metrics, tmp_path):
        """Test saving evaluation artifacts to disk."""
        result = evaluator.evaluate_model("my-model", "1", sample_metrics)
        output_dir = str(tmp_path / "artifacts")
        path = evaluator.save_evaluation_artifacts(result, output_dir)

        assert Path(path).exists()
        report_files = list(Path(path).glob("*.json"))
        assert len(report_files) >= 2

        # Validate report content
        report_file = next(f for f in report_files if "report" in f.name)
        with open(report_file) as f:
            report = json.load(f)
        assert report["model_name"] == "my-model"
        assert "metrics" in report

    def test_evaluation_result_serialization(self):
        """Test EvaluationResult to_dict serialization."""
        result = EvaluationResult(
            model_name="test",
            model_version="1",
            metrics={"accuracy": 0.9},
            gate_results={"accuracy": True},
            passed_all_gates=True,
        )
        data = result.to_dict()
        assert data["model_name"] == "test"
        assert data["metrics"]["accuracy"] == 0.9
        assert data["passed_all_gates"] is True

    def test_missing_mandatory_metric(self, evaluator):
        """Test evaluation fails when a mandatory metric is missing."""
        incomplete_metrics = {"loss": 0.2}  # Missing accuracy
        result = evaluator.evaluate_model("my-model", "1", incomplete_metrics)
        assert result.passed_all_gates is False
