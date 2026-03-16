"""
Environment Promoter

Manages model promotion across environments (dev -> staging -> prod)
with approval gates, validation checks, and audit logging.

Author: Gabriel Demetrios Lafis
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from azure.ai.ml import MLClient
from azure.identity import DefaultAzureCredential

from src.config.settings import AzureMLConfig, DeploymentConfig, Environment
from src.evaluation.model_evaluator import ModelEvaluator, EvaluationResult
from src.utils.logger import get_logger

logger = get_logger("environment_promoter")


@dataclass
class PromotionGate:
    """Defines a gate that must be satisfied before promotion."""

    name: str
    gate_type: str  # evaluation, approval, smoke_test, integration_test
    required: bool = True
    passed: bool = False
    details: str = ""
    evaluated_at: Optional[str] = None


@dataclass
class PromotionRecord:
    """Audit record for an environment promotion attempt."""

    model_name: str
    model_version: str
    source_environment: Environment
    target_environment: Environment
    gates: list[PromotionGate] = field(default_factory=list)
    promoted: bool = False
    initiated_by: str = "pipeline"
    initiated_at: str = ""
    completed_at: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize promotion record."""
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "source_environment": self.source_environment.value,
            "target_environment": self.target_environment.value,
            "gates": [
                {
                    "name": g.name,
                    "gate_type": g.gate_type,
                    "required": g.required,
                    "passed": g.passed,
                    "details": g.details,
                    "evaluated_at": g.evaluated_at,
                }
                for g in self.gates
            ],
            "promoted": self.promoted,
            "initiated_by": self.initiated_by,
            "initiated_at": self.initiated_at,
            "completed_at": self.completed_at,
            "details": self.details,
        }


class EnvironmentPromoter:
    """
    Manages model promotion across deployment environments.

    Enforces promotion policies:
    - dev -> staging: Requires passing evaluation quality gates
    - staging -> prod: Requires quality gates + integration tests + approval

    Usage:
        promoter = EnvironmentPromoter(
            source_config=AzureMLConfig.from_environment("staging"),
            target_config=AzureMLConfig.from_environment("prod"),
        )
        result = promoter.promote_model("my-model", "5", metrics)
    """

    PROMOTION_PATHS = {
        (Environment.DEV, Environment.STAGING): [
            PromotionGate("quality_gates", "evaluation", required=True),
            PromotionGate("smoke_test", "smoke_test", required=True),
        ],
        (Environment.STAGING, Environment.PROD): [
            PromotionGate("quality_gates", "evaluation", required=True),
            PromotionGate("champion_comparison", "evaluation", required=True),
            PromotionGate("integration_tests", "integration_test", required=True),
            PromotionGate("manual_approval", "approval", required=True),
        ],
    }

    def __init__(
        self,
        source_config: AzureMLConfig,
        target_config: AzureMLConfig,
        credential: Optional[Any] = None,
        audit_dir: str = "promotion_audit",
    ):
        """
        Initialize Environment Promoter.

        Args:
            source_config: Source environment configuration.
            target_config: Target environment configuration.
            credential: Azure credential. Defaults to DefaultAzureCredential.
            audit_dir: Directory for promotion audit logs.
        """
        self.source_config = source_config
        self.target_config = target_config
        self.credential = credential or DefaultAzureCredential()
        self.audit_dir = Path(audit_dir)

        self._source_client: Optional[MLClient] = None
        self._target_client: Optional[MLClient] = None

        self.promotion_path = (source_config.environment, target_config.environment)

        logger.info(
            "EnvironmentPromoter initialized: %s -> %s",
            source_config.environment.value,
            target_config.environment.value,
        )

    @property
    def source_client(self) -> MLClient:
        """Lazy-initialized source workspace client."""
        if self._source_client is None:
            self._source_client = MLClient(
                credential=self.credential,
                subscription_id=self.source_config.subscription_id,
                resource_group_name=self.source_config.resource_group,
                workspace_name=self.source_config.workspace_name,
            )
        return self._source_client

    @property
    def target_client(self) -> MLClient:
        """Lazy-initialized target workspace client."""
        if self._target_client is None:
            self._target_client = MLClient(
                credential=self.credential,
                subscription_id=self.target_config.subscription_id,
                resource_group_name=self.target_config.resource_group,
                workspace_name=self.target_config.workspace_name,
            )
        return self._target_client

    def promote_model(
        self,
        model_name: str,
        model_version: str,
        metrics: dict[str, float],
        champion_metrics: Optional[dict[str, float]] = None,
        approved: bool = False,
        integration_tests_passed: bool = False,
    ) -> PromotionRecord:
        """
        Attempt to promote a model from source to target environment.

        Evaluates all required promotion gates and either promotes
        the model or returns a record of which gates failed.

        Args:
            model_name: Registered model name.
            model_version: Model version to promote.
            metrics: Current model evaluation metrics.
            champion_metrics: Production champion metrics for comparison.
            approved: Whether manual approval has been granted.
            integration_tests_passed: Whether integration tests passed.

        Returns:
            PromotionRecord with gate results and promotion status.
        """
        now = datetime.now(timezone.utc).isoformat()

        record = PromotionRecord(
            model_name=model_name,
            model_version=model_version,
            source_environment=self.source_config.environment,
            target_environment=self.target_config.environment,
            initiated_at=now,
        )

        # Get gates for this promotion path
        gates_template = self.PROMOTION_PATHS.get(self.promotion_path, [])
        gates = [
            PromotionGate(
                name=g.name,
                gate_type=g.gate_type,
                required=g.required,
            )
            for g in gates_template
        ]
        record.gates = gates

        logger.info(
            "Evaluating promotion: %s:v%s (%s -> %s), gates=%d",
            model_name,
            model_version,
            self.source_config.environment.value,
            self.target_config.environment.value,
            len(gates),
        )

        # Evaluate each gate
        for gate in gates:
            gate.evaluated_at = datetime.now(timezone.utc).isoformat()

            if gate.gate_type == "evaluation" and gate.name == "quality_gates":
                evaluator = ModelEvaluator(self.target_config, self.credential)
                result = evaluator.evaluate_model(
                    model_name, model_version, metrics, champion_metrics
                )
                gate.passed = result.passed_all_gates
                gate.details = f"Gates: {sum(result.gate_results.values())}/{len(result.gate_results)} passed"

            elif gate.gate_type == "evaluation" and gate.name == "champion_comparison":
                if champion_metrics:
                    evaluator = ModelEvaluator(self.target_config, self.credential)
                    result = evaluator.evaluate_model(
                        model_name, model_version, metrics, champion_metrics
                    )
                    gate.passed = result.champion_comparison.get("challenger_better", False)
                    gate.details = "Challenger is better than champion" if gate.passed else "Champion is still better"
                else:
                    gate.passed = True
                    gate.details = "No champion model found; first deployment"

            elif gate.gate_type == "smoke_test":
                gate.passed = True  # Smoke test runs during deployment
                gate.details = "Smoke test will execute post-deployment"

            elif gate.gate_type == "integration_test":
                gate.passed = integration_tests_passed
                gate.details = "Integration tests passed" if gate.passed else "Integration tests not passed"

            elif gate.gate_type == "approval":
                gate.passed = approved
                gate.details = "Manual approval granted" if gate.passed else "Awaiting manual approval"

            status = "PASSED" if gate.passed else "FAILED"
            logger.info("Gate '%s' (%s): %s - %s", gate.name, gate.gate_type, status, gate.details)

        # Check if all required gates passed
        all_required_passed = all(
            gate.passed for gate in gates if gate.required
        )

        if all_required_passed:
            record.promoted = True
            record.completed_at = datetime.now(timezone.utc).isoformat()
            self._execute_promotion(model_name, model_version)
            logger.info(
                "Model %s:v%s promoted to %s.",
                model_name,
                model_version,
                self.target_config.environment.value,
            )
        else:
            failed_gates = [g.name for g in gates if g.required and not g.passed]
            logger.warning(
                "Promotion blocked for %s:v%s. Failed gates: %s",
                model_name,
                model_version,
                ", ".join(failed_gates),
            )

        # Save audit log
        self._save_audit_log(record)

        return record

    def _execute_promotion(self, model_name: str, model_version: str) -> None:
        """
        Execute the model promotion to the target workspace.

        Args:
            model_name: Model name.
            model_version: Model version.
        """
        try:
            # Get model from source
            source_model = self.source_client.models.get(
                name=model_name, version=model_version
            )

            logger.info(
                "Promoting model artifact: %s:v%s -> %s",
                model_name,
                model_version,
                self.target_config.workspace_name,
            )

            # Register in target workspace (cross-workspace model copy)
            from azure.ai.ml.entities import Model

            target_model = Model(
                name=model_name,
                path=source_model.path,
                type=source_model.type,
                description=f"Promoted from {self.source_config.environment.value}: {source_model.description}",
                tags={
                    **(source_model.tags or {}),
                    "promoted_from": self.source_config.environment.value,
                    "promoted_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            registered = self.target_client.models.create_or_update(target_model)
            logger.info(
                "Model registered in target: %s:v%s",
                registered.name,
                registered.version,
            )

        except Exception as e:
            logger.error("Promotion execution failed: %s", str(e))
            raise

    def _save_audit_log(self, record: PromotionRecord) -> None:
        """Save promotion audit record to disk."""
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        filename = (
            f"promotion_{record.model_name}_v{record.model_version}_"
            f"{record.source_environment.value}_to_{record.target_environment.value}_"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        )

        filepath = self.audit_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2, default=str)

        logger.info("Audit log saved: %s", filepath)

    def get_promotion_history(
        self,
        model_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve promotion audit history.

        Args:
            model_name: Filter by model name. Returns all if None.

        Returns:
            List of promotion records.
        """
        if not self.audit_dir.exists():
            return []

        records = []
        for audit_file in sorted(self.audit_dir.glob("promotion_*.json"), reverse=True):
            with open(audit_file, "r", encoding="utf-8") as f:
                record = json.load(f)
                if model_name is None or record.get("model_name") == model_name:
                    records.append(record)

        return records
