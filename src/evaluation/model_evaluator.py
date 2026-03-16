"""
Model Evaluator

Implements quality gates, metrics comparison, and evaluation artifact
management for ML model promotion decisions.

Author: Gabriel Demetrios Lafis
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from azure.ai.ml import MLClient
from azure.identity import DefaultAzureCredential

from src.config.settings import AzureMLConfig, Environment
from src.utils.logger import get_logger

logger = get_logger("model_evaluator")


@dataclass
class QualityGate:
    """
    Defines a quality gate threshold for model promotion.

    A quality gate specifies a metric, a minimum or maximum threshold,
    and whether the gate is mandatory for promotion.
    """

    metric_name: str
    threshold: float
    comparison: str = "gte"  # gte, lte, gt, lt, eq
    mandatory: bool = True
    description: str = ""

    def evaluate(self, actual_value: float) -> bool:
        """
        Evaluate whether the metric passes this gate.

        Args:
            actual_value: The actual metric value to evaluate.

        Returns:
            True if the gate passes, False otherwise.
        """
        comparisons = {
            "gte": actual_value >= self.threshold,
            "lte": actual_value <= self.threshold,
            "gt": actual_value > self.threshold,
            "lt": actual_value < self.threshold,
            "eq": abs(actual_value - self.threshold) < 1e-6,
        }
        return comparisons.get(self.comparison, False)


@dataclass
class EvaluationResult:
    """Container for model evaluation results."""

    model_name: str
    model_version: str
    metrics: dict[str, float] = field(default_factory=dict)
    gate_results: dict[str, bool] = field(default_factory=dict)
    passed_all_gates: bool = False
    champion_comparison: dict[str, Any] = field(default_factory=dict)
    artifacts_path: Optional[str] = None
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize evaluation result to dictionary."""
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "metrics": self.metrics,
            "gate_results": self.gate_results,
            "passed_all_gates": self.passed_all_gates,
            "champion_comparison": self.champion_comparison,
            "artifacts_path": self.artifacts_path,
            "timestamp": self.timestamp,
        }


class ModelEvaluator:
    """
    Evaluates trained models against quality gates and champion models.

    Provides comprehensive model evaluation including:
    - Quality gate enforcement with configurable thresholds
    - Champion/challenger comparison for model promotion
    - Evaluation artifact persistence for audit trails
    - Environment-specific quality requirements

    Usage:
        evaluator = ModelEvaluator(config)
        evaluator.add_quality_gate(QualityGate("accuracy", 0.85, "gte"))
        result = evaluator.evaluate_model("my-model", "3", metrics)
    """

    DEFAULT_GATES: dict[Environment, list[QualityGate]] = {
        Environment.DEV: [
            QualityGate("accuracy", 0.70, "gte", mandatory=True, description="Minimum accuracy for dev"),
            QualityGate("loss", 1.0, "lte", mandatory=False, description="Maximum loss for dev"),
        ],
        Environment.STAGING: [
            QualityGate("accuracy", 0.80, "gte", mandatory=True, description="Minimum accuracy for staging"),
            QualityGate("f1_score", 0.75, "gte", mandatory=True, description="Minimum F1 for staging"),
            QualityGate("loss", 0.5, "lte", mandatory=True, description="Maximum loss for staging"),
        ],
        Environment.PROD: [
            QualityGate("accuracy", 0.85, "gte", mandatory=True, description="Minimum accuracy for prod"),
            QualityGate("f1_score", 0.80, "gte", mandatory=True, description="Minimum F1 for prod"),
            QualityGate("precision", 0.80, "gte", mandatory=True, description="Minimum precision for prod"),
            QualityGate("recall", 0.75, "gte", mandatory=True, description="Minimum recall for prod"),
            QualityGate("loss", 0.3, "lte", mandatory=True, description="Maximum loss for prod"),
        ],
    }

    def __init__(
        self,
        azure_config: AzureMLConfig,
        credential: Optional[Any] = None,
        quality_gates: Optional[list[QualityGate]] = None,
    ):
        """
        Initialize Model Evaluator.

        Args:
            azure_config: Azure ML workspace configuration.
            credential: Azure credential. Defaults to DefaultAzureCredential.
            quality_gates: Custom quality gates. Uses environment defaults if None.
        """
        self.azure_config = azure_config
        self.credential = credential or DefaultAzureCredential()
        self._client: Optional[MLClient] = None

        if quality_gates is not None:
            self.quality_gates = quality_gates
        else:
            self.quality_gates = list(
                self.DEFAULT_GATES.get(azure_config.environment, [])
            )

        logger.info(
            "ModelEvaluator initialized: env=%s, gates=%d",
            azure_config.environment.value,
            len(self.quality_gates),
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
        return self._client

    def add_quality_gate(self, gate: QualityGate) -> None:
        """
        Add a quality gate to the evaluator.

        Args:
            gate: QualityGate to add.
        """
        self.quality_gates.append(gate)
        logger.info("Quality gate added: %s %s %s", gate.metric_name, gate.comparison, gate.threshold)

    def evaluate_model(
        self,
        model_name: str,
        model_version: str,
        metrics: dict[str, float],
        champion_metrics: Optional[dict[str, float]] = None,
    ) -> EvaluationResult:
        """
        Evaluate a model against quality gates and optionally compare
        with the champion model.

        Args:
            model_name: Name of the model to evaluate.
            model_version: Version of the model.
            metrics: Dictionary of metric name-value pairs.
            champion_metrics: Champion model metrics for comparison.

        Returns:
            EvaluationResult with gate outcomes and comparison data.
        """
        from datetime import datetime, timezone

        logger.info("Evaluating model: %s (v%s)", model_name, model_version)

        result = EvaluationResult(
            model_name=model_name,
            model_version=model_version,
            metrics=metrics,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Evaluate quality gates
        all_mandatory_passed = True
        for gate in self.quality_gates:
            if gate.metric_name in metrics:
                passed = gate.evaluate(metrics[gate.metric_name])
                result.gate_results[gate.metric_name] = passed

                if not passed and gate.mandatory:
                    all_mandatory_passed = False
                    logger.warning(
                        "GATE FAILED [mandatory]: %s = %.4f (threshold: %s %.4f)",
                        gate.metric_name,
                        metrics[gate.metric_name],
                        gate.comparison,
                        gate.threshold,
                    )
                elif not passed:
                    logger.warning(
                        "GATE FAILED [optional]: %s = %.4f (threshold: %s %.4f)",
                        gate.metric_name,
                        metrics[gate.metric_name],
                        gate.comparison,
                        gate.threshold,
                    )
                else:
                    logger.info(
                        "GATE PASSED: %s = %.4f (threshold: %s %.4f)",
                        gate.metric_name,
                        metrics[gate.metric_name],
                        gate.comparison,
                        gate.threshold,
                    )
            elif gate.mandatory:
                result.gate_results[gate.metric_name] = False
                all_mandatory_passed = False
                logger.error("GATE FAILED: metric '%s' not found in results.", gate.metric_name)

        result.passed_all_gates = all_mandatory_passed

        # Champion comparison
        if champion_metrics:
            result.champion_comparison = self._compare_with_champion(
                metrics, champion_metrics
            )

        logger.info(
            "Evaluation complete: model=%s, passed=%s, gates=%d/%d",
            model_name,
            result.passed_all_gates,
            sum(result.gate_results.values()),
            len(result.gate_results),
        )

        return result

    def _compare_with_champion(
        self,
        challenger_metrics: dict[str, float],
        champion_metrics: dict[str, float],
    ) -> dict[str, Any]:
        """
        Compare challenger model metrics against the current champion.

        Args:
            challenger_metrics: Challenger model metrics.
            champion_metrics: Champion model metrics.

        Returns:
            Comparison results with improvement indicators.
        """
        comparison = {
            "challenger_better": False,
            "improvements": {},
            "regressions": {},
        }

        improvement_count = 0
        regression_count = 0

        for metric, challenger_val in challenger_metrics.items():
            if metric in champion_metrics:
                champion_val = champion_metrics[metric]
                diff = challenger_val - champion_val
                pct_change = (diff / champion_val * 100) if champion_val != 0 else 0

                entry = {
                    "champion": champion_val,
                    "challenger": challenger_val,
                    "difference": diff,
                    "percentage_change": round(pct_change, 2),
                }

                if metric.lower() in ("loss", "error", "mse", "mae", "rmse"):
                    if diff < 0:
                        comparison["improvements"][metric] = entry
                        improvement_count += 1
                    elif diff > 0:
                        comparison["regressions"][metric] = entry
                        regression_count += 1
                else:
                    if diff > 0:
                        comparison["improvements"][metric] = entry
                        improvement_count += 1
                    elif diff < 0:
                        comparison["regressions"][metric] = entry
                        regression_count += 1

        comparison["challenger_better"] = improvement_count > regression_count

        logger.info(
            "Champion comparison: improvements=%d, regressions=%d, challenger_better=%s",
            improvement_count,
            regression_count,
            comparison["challenger_better"],
        )

        return comparison

    def save_evaluation_artifacts(
        self,
        result: EvaluationResult,
        output_dir: str = "evaluation_artifacts",
    ) -> str:
        """
        Save evaluation results and artifacts to disk.

        Args:
            result: Evaluation result to persist.
            output_dir: Output directory for artifacts.

        Returns:
            Path to the saved artifacts directory.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save evaluation report
        report_path = output_path / f"{result.model_name}_v{result.model_version}_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, default=str)

        # Save gate summary
        gate_summary_path = output_path / f"{result.model_name}_v{result.model_version}_gates.json"
        gate_summary = {
            "passed_all_gates": result.passed_all_gates,
            "gate_results": result.gate_results,
            "quality_gates": [
                {
                    "metric": g.metric_name,
                    "threshold": g.threshold,
                    "comparison": g.comparison,
                    "mandatory": g.mandatory,
                }
                for g in self.quality_gates
            ],
        }
        with open(gate_summary_path, "w", encoding="utf-8") as f:
            json.dump(gate_summary, f, indent=2)

        result.artifacts_path = str(output_path)
        logger.info("Evaluation artifacts saved to: %s", output_path)

        return str(output_path)

    def get_champion_model_metrics(
        self,
        model_name: str,
    ) -> Optional[dict[str, float]]:
        """
        Retrieve metrics for the current champion model (latest production version).

        Args:
            model_name: Registered model name.

        Returns:
            Champion model metrics, or None if no champion exists.
        """
        try:
            latest_model = self.client.models.get(name=model_name, label="latest")
            if latest_model.tags and "metrics" in latest_model.tags:
                return json.loads(latest_model.tags["metrics"])
            logger.info("No metrics found in champion model tags for '%s'.", model_name)
            return None
        except Exception as e:
            logger.warning("Could not retrieve champion model '%s': %s", model_name, str(e))
            return None
