"""
Application Insights Monitor

Provides custom metrics, dependency tracking, and request telemetry
for Azure ML pipeline observability.

Author: Gabriel Demetrios Lafis
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, Optional

from src.config.settings import AzureMLConfig
from src.utils.logger import get_logger

logger = get_logger("app_insights")


class AppInsightsMonitor:
    """
    Application Insights telemetry client for ML pipeline monitoring.

    Provides methods for tracking custom metrics, dependencies,
    requests, and exceptions with correlation support.

    Usage:
        monitor = AppInsightsMonitor("your-instrumentation-key")
        monitor.track_metric("model_accuracy", 0.95, {"model": "v3"})
        with monitor.track_dependency("AzureML", "training_job"):
            trainer.submit_job(...)
    """

    def __init__(
        self,
        instrumentation_key: Optional[str] = None,
        connection_string: Optional[str] = None,
        azure_config: Optional[AzureMLConfig] = None,
        enable_telemetry: bool = True,
    ):
        """
        Initialize Application Insights Monitor.

        Args:
            instrumentation_key: App Insights instrumentation key.
            connection_string: App Insights connection string (preferred).
            azure_config: Azure ML config (extracts key automatically).
            enable_telemetry: Whether to send telemetry (disable for tests).
        """
        self.enable_telemetry = enable_telemetry
        self._telemetry_client = None
        self._metrics_buffer: list[dict[str, Any]] = []

        key = instrumentation_key
        if azure_config and azure_config.application_insights_key:
            key = azure_config.application_insights_key

        if enable_telemetry and (key or connection_string):
            try:
                from opencensus.ext.azure.trace_exporter import AzureExporter
                from opencensus.ext.azure import metrics_exporter
                from opencensus.stats import stats as stats_module

                conn_str = connection_string or f"InstrumentationKey={key}"
                self._exporter = AzureExporter(connection_string=conn_str)
                self._metrics_exporter = metrics_exporter.new_metrics_exporter(
                    connection_string=conn_str
                )
                self._stats = stats_module.stats
                self._stats.view_manager.register_exporter(self._metrics_exporter)

                logger.info("Application Insights telemetry initialized.")
            except ImportError:
                logger.warning(
                    "opencensus-ext-azure not installed. "
                    "Telemetry will be buffered locally."
                )
                self.enable_telemetry = False
        else:
            logger.info("Telemetry disabled or no instrumentation key provided.")
            self.enable_telemetry = False

    def track_metric(
        self,
        name: str,
        value: float,
        properties: Optional[dict[str, str]] = None,
        namespace: str = "AzureMLPipeline",
    ) -> None:
        """
        Track a custom metric value.

        Args:
            name: Metric name (e.g., model_accuracy, training_duration).
            value: Metric value.
            properties: Additional dimensions/properties.
            namespace: Metric namespace for grouping.
        """
        metric_entry = {
            "name": name,
            "value": value,
            "namespace": namespace,
            "properties": properties or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._metrics_buffer.append(metric_entry)

        if self.enable_telemetry:
            try:
                from opencensus.stats import measure as measure_module
                from opencensus.stats import view as view_module
                from opencensus.stats import aggregation as aggregation_module
                from opencensus.tags import tag_key as tag_key_module
                from opencensus.tags import tag_map as tag_map_module
                from opencensus.tags import tag_value as tag_value_module

                measure = measure_module.MeasureFloat(
                    name=f"{namespace}/{name}",
                    description=f"Custom metric: {name}",
                    unit="1",
                )

                tag_keys = [
                    tag_key_module.TagKey(k) for k in (properties or {}).keys()
                ]

                view = view_module.View(
                    name=f"{namespace}/{name}",
                    description=f"Custom metric view: {name}",
                    columns=tag_keys,
                    measure=measure,
                    aggregation=aggregation_module.LastValueAggregation(),
                )

                self._stats.view_manager.register_view(view)

                tag_map = tag_map_module.TagMap()
                for k, v in (properties or {}).items():
                    tag_map.insert(
                        tag_key_module.TagKey(k),
                        tag_value_module.TagValue(str(v)),
                    )

                measurement_map = self._stats.stats_recorder.new_measurement_map()
                measurement_map.measure_float_put(measure, value)
                measurement_map.record(tag_map)

            except Exception as e:
                logger.debug("Failed to send metric to App Insights: %s", str(e))

        logger.info("Metric tracked: %s = %s (properties: %s)", name, value, properties)

    def track_training_metrics(
        self,
        model_name: str,
        model_version: str,
        metrics: dict[str, float],
        environment: str = "dev",
    ) -> None:
        """
        Track a batch of training metrics.

        Args:
            model_name: Model name.
            model_version: Model version.
            metrics: Dictionary of metric name-value pairs.
            environment: Deployment environment.
        """
        properties = {
            "model_name": model_name,
            "model_version": model_version,
            "environment": environment,
        }

        for metric_name, metric_value in metrics.items():
            self.track_metric(
                name=f"training/{metric_name}",
                value=metric_value,
                properties=properties,
                namespace="AzureMLTraining",
            )

        logger.info(
            "Training metrics batch tracked: model=%s:v%s, metrics=%d",
            model_name,
            model_version,
            len(metrics),
        )

    @contextmanager
    def track_dependency(
        self,
        dependency_type: str,
        name: str,
        data: Optional[str] = None,
        properties: Optional[dict[str, str]] = None,
    ) -> Generator[dict[str, Any], None, None]:
        """
        Track an external dependency call with duration measurement.

        Args:
            dependency_type: Type of dependency (AzureML, Storage, KeyVault).
            name: Dependency operation name.
            data: Additional data about the call.
            properties: Additional properties.

        Yields:
            Tracking context dictionary for adding details.
        """
        context: dict[str, Any] = {
            "dependency_type": dependency_type,
            "name": name,
            "data": data,
            "success": True,
            "start_time": time.time(),
        }

        try:
            yield context
        except Exception as e:
            context["success"] = False
            context["error"] = str(e)
            raise
        finally:
            duration = time.time() - context["start_time"]
            context["duration_ms"] = duration * 1000

            self.track_metric(
                name=f"dependency/{dependency_type}/{name}/duration_ms",
                value=context["duration_ms"],
                properties={
                    **(properties or {}),
                    "success": str(context["success"]),
                },
                namespace="AzureMLDependency",
            )

            log_fn = logger.info if context["success"] else logger.error
            log_fn(
                "Dependency tracked: %s/%s, duration=%.2fms, success=%s",
                dependency_type,
                name,
                context["duration_ms"],
                context["success"],
            )

    def track_request(
        self,
        name: str,
        url: str,
        success: bool,
        duration_ms: float,
        response_code: int = 200,
        properties: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Track an incoming request (e.g., scoring endpoint call).

        Args:
            name: Request name.
            url: Request URL.
            success: Whether the request succeeded.
            duration_ms: Request duration in milliseconds.
            response_code: HTTP response code.
            properties: Additional properties.
        """
        self.track_metric(
            name=f"request/{name}/duration_ms",
            value=duration_ms,
            properties={
                **(properties or {}),
                "url": url,
                "success": str(success),
                "response_code": str(response_code),
            },
            namespace="AzureMLRequest",
        )

        logger.info(
            "Request tracked: %s, duration=%.2fms, status=%d, success=%s",
            name,
            duration_ms,
            response_code,
            success,
        )

    def track_exception(
        self,
        exception: Exception,
        properties: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Track an exception occurrence.

        Args:
            exception: The exception to track.
            properties: Additional context properties.
        """
        self.track_metric(
            name="exceptions/count",
            value=1.0,
            properties={
                **(properties or {}),
                "exception_type": type(exception).__name__,
                "exception_message": str(exception),
            },
            namespace="AzureMLExceptions",
        )

        logger.error(
            "Exception tracked: %s - %s",
            type(exception).__name__,
            str(exception),
        )

    def track_deployment_event(
        self,
        event_type: str,
        model_name: str,
        model_version: str,
        environment: str,
        details: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Track a deployment lifecycle event.

        Args:
            event_type: Event type (deploy, promote, rollback, scale).
            model_name: Model name.
            model_version: Model version.
            environment: Target environment.
            details: Additional event details.
        """
        self.track_metric(
            name=f"deployment/{event_type}",
            value=1.0,
            properties={
                "model_name": model_name,
                "model_version": model_version,
                "environment": environment,
                **(details or {}),
            },
            namespace="AzureMLDeployment",
        )

        logger.info(
            "Deployment event: %s, model=%s:v%s, env=%s",
            event_type,
            model_name,
            model_version,
            environment,
        )

    def get_metrics_buffer(self) -> list[dict[str, Any]]:
        """
        Get the local metrics buffer (useful for testing).

        Returns:
            List of buffered metric entries.
        """
        return list(self._metrics_buffer)

    def flush(self) -> None:
        """Flush any pending telemetry data."""
        if self.enable_telemetry:
            try:
                self._metrics_exporter.export_metrics()
                logger.info("Telemetry flushed successfully.")
            except Exception as e:
                logger.warning("Failed to flush telemetry: %s", str(e))
