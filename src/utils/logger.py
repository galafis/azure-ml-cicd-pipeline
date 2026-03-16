"""
Centralized Logging Configuration

Provides structured logging with support for Azure Application Insights,
console output, and file-based logging with rotation.

Author: Gabriel Demetrios Lafis
"""

import logging
import logging.handlers
import sys
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter for production observability."""

    def __init__(self, service_name: str = "azure-ml-pipeline"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id

        if hasattr(record, "environment"):
            log_entry["environment"] = record.environment

        return json.dumps(log_entry, default=str)


class ConsoleFormatter(logging.Formatter):
    """Color-coded console formatter for local development."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"{color}[{timestamp}] {record.levelname:8s}{self.RESET} "
            f"{record.module}.{record.funcName}:{record.lineno} - "
            f"{record.getMessage()}"
        )


class PipelineLogger:
    """
    Centralized logger with multi-handler support.

    Supports structured JSON logging for production, color-coded console
    output for development, and rotating file handlers for persistence.

    Usage:
        logger = PipelineLogger.get_logger("training", environment="dev")
        logger.info("Training job submitted", extra={"correlation_id": "abc-123"})
    """

    _loggers: dict[str, logging.Logger] = {}

    @classmethod
    def get_logger(
        cls,
        name: str,
        level: int = logging.INFO,
        environment: str = "dev",
        log_dir: Optional[str] = None,
        enable_file_logging: bool = True,
    ) -> logging.Logger:
        """
        Get or create a configured logger instance.

        Args:
            name: Logger name (typically module or component name).
            level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            environment: Deployment environment (dev, staging, prod).
            log_dir: Directory for log files. Defaults to ./logs.
            enable_file_logging: Whether to write logs to files.

        Returns:
            Configured logging.Logger instance.
        """
        if name in cls._loggers:
            return cls._loggers[name]

        logger = logging.getLogger(f"azure_ml_pipeline.{name}")
        logger.setLevel(level)
        logger.propagate = False

        if logger.handlers:
            logger.handlers.clear()

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        if environment == "dev":
            console_handler.setFormatter(ConsoleFormatter())
        else:
            console_handler.setFormatter(StructuredFormatter())
        console_handler.setLevel(level)
        logger.addHandler(console_handler)

        # File handler with rotation
        if enable_file_logging:
            log_path = Path(log_dir or "logs")
            log_path.mkdir(parents=True, exist_ok=True)

            file_handler = logging.handlers.RotatingFileHandler(
                log_path / f"{name}.log",
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(StructuredFormatter())
            file_handler.setLevel(level)
            logger.addHandler(file_handler)

        cls._loggers[name] = logger
        return logger

    @classmethod
    def reset(cls) -> None:
        """Reset all cached loggers. Useful for testing."""
        for logger in cls._loggers.values():
            logger.handlers.clear()
        cls._loggers.clear()


def get_logger(name: str, **kwargs) -> logging.Logger:
    """Convenience function for obtaining a pipeline logger."""
    return PipelineLogger.get_logger(name, **kwargs)
