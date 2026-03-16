"""
Data Handler

Manages Azure ML Data Assets with versioning, tabular dataset
operations, and data lineage tracking.

Author: Gabriel Demetrios Lafis
"""

from __future__ import annotations

from typing import Any, Optional

from azure.ai.ml import MLClient, Input
from azure.ai.ml.entities import Data
from azure.ai.ml.constants import AssetTypes
from azure.identity import DefaultAzureCredential

from src.config.settings import AzureMLConfig
from src.utils.logger import get_logger

logger = get_logger("data_handler")


class DataHandler:
    """
    Manages Azure ML Data Assets and dataset operations.

    Handles data registration, versioning, retrieval, and
    validation for training pipeline consumption.

    Usage:
        config = AzureMLConfig.from_environment(Environment.DEV)
        handler = DataHandler(config)
        asset = handler.register_data_asset("training-data", "./data/train.csv")
    """

    def __init__(
        self,
        azure_config: AzureMLConfig,
        credential: Optional[Any] = None,
    ):
        """
        Initialize Data Handler.

        Args:
            azure_config: Azure ML workspace configuration.
            credential: Azure credential. Defaults to DefaultAzureCredential.
        """
        self.azure_config = azure_config
        self.credential = credential or DefaultAzureCredential()
        self._client: Optional[MLClient] = None

        logger.info("DataHandler initialized for workspace=%s", azure_config.workspace_name)

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

    def register_data_asset(
        self,
        name: str,
        path: str,
        asset_type: str = AssetTypes.URI_FOLDER,
        description: Optional[str] = None,
        version: Optional[str] = None,
        tags: Optional[dict[str, str]] = None,
    ) -> Data:
        """
        Register a new data asset or create a new version.

        Args:
            name: Data asset name.
            path: Local or remote path to the data.
            asset_type: Asset type (URI_FOLDER, URI_FILE, MLTABLE).
            description: Asset description.
            version: Explicit version string. Auto-incremented if None.
            tags: Metadata tags for lineage tracking.

        Returns:
            Registered Data asset.
        """
        data_asset = Data(
            name=name,
            path=path,
            type=asset_type,
            description=description or f"Data asset: {name}",
            version=version,
            tags=tags or {"environment": self.azure_config.environment.value},
        )

        registered = self.client.data.create_or_update(data_asset)
        logger.info(
            "Data asset registered: name=%s, version=%s, type=%s",
            registered.name,
            registered.version,
            asset_type,
        )
        return registered

    def register_tabular_dataset(
        self,
        name: str,
        path: str,
        description: Optional[str] = None,
        version: Optional[str] = None,
    ) -> Data:
        """
        Register a tabular dataset (MLTable format).

        Args:
            name: Dataset name.
            path: Path to the MLTable definition folder.
            description: Dataset description.
            version: Explicit version string.

        Returns:
            Registered MLTable Data asset.
        """
        return self.register_data_asset(
            name=name,
            path=path,
            asset_type=AssetTypes.MLTABLE,
            description=description or f"Tabular dataset: {name}",
            version=version,
        )

    def get_data_asset(
        self,
        name: str,
        version: Optional[str] = None,
    ) -> Data:
        """
        Retrieve a registered data asset.

        Args:
            name: Data asset name.
            version: Specific version. Defaults to latest.

        Returns:
            Data asset object.
        """
        if version:
            asset = self.client.data.get(name=name, version=version)
        else:
            asset = self.client.data.get(name=name, label="latest")

        logger.info(
            "Data asset retrieved: name=%s, version=%s",
            asset.name,
            asset.version,
        )
        return asset

    def list_data_assets(
        self,
        name: Optional[str] = None,
    ) -> list[Data]:
        """
        List registered data assets.

        Args:
            name: Filter by asset name. Lists all if None.

        Returns:
            List of Data asset objects.
        """
        if name:
            assets = list(self.client.data.list(name=name))
        else:
            assets = list(self.client.data.list())

        logger.info("Listed %d data assets (filter=%s)", len(assets), name)
        return assets

    def get_input_reference(
        self,
        name: str,
        version: Optional[str] = None,
        input_type: str = "uri_folder",
    ) -> Input:
        """
        Get a data input reference for use in training jobs.

        Args:
            name: Data asset name.
            version: Specific version. Defaults to latest.
            input_type: Input type (uri_folder, uri_file, mltable).

        Returns:
            Input reference for pipeline consumption.
        """
        asset = self.get_data_asset(name, version)

        return Input(
            type=input_type,
            path=f"azureml:{asset.name}:{asset.version}",
        )

    def validate_data_asset(self, name: str, version: Optional[str] = None) -> dict[str, Any]:
        """
        Validate a data asset exists and is accessible.

        Args:
            name: Data asset name.
            version: Specific version to validate.

        Returns:
            Validation result with asset metadata.
        """
        try:
            asset = self.get_data_asset(name, version)
            result = {
                "valid": True,
                "name": asset.name,
                "version": asset.version,
                "type": asset.type,
                "path": asset.path,
            }
            logger.info("Data asset validation passed: %s (v%s)", name, asset.version)
            return result
        except Exception as e:
            result = {
                "valid": False,
                "name": name,
                "version": version,
                "error": str(e),
            }
            logger.error("Data asset validation failed: %s - %s", name, str(e))
            return result

    def create_data_version(
        self,
        name: str,
        path: str,
        parent_version: Optional[str] = None,
        tags: Optional[dict[str, str]] = None,
    ) -> Data:
        """
        Create a new version of an existing data asset with lineage.

        Args:
            name: Existing data asset name.
            path: Path to the new data version.
            parent_version: Previous version for lineage tracking.
            tags: Additional metadata tags.

        Returns:
            Newly registered Data asset version.
        """
        lineage_tags = tags or {}
        if parent_version:
            lineage_tags["parent_version"] = parent_version

        return self.register_data_asset(
            name=name,
            path=path,
            tags=lineage_tags,
        )
