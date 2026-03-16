"""
Endpoint Manager

Manages Azure ML managed online endpoints with blue-green deployment
strategies, traffic routing, and automated rollback.

Author: Gabriel Demetrios Lafis
"""

from __future__ import annotations

import time
from typing import Any, Optional

from azure.ai.ml import MLClient
from azure.ai.ml.entities import (
    ManagedOnlineEndpoint,
    ManagedOnlineDeployment,
    Model,
    Environment as AzureMLEnvironment,
    CodeConfiguration,
    ProbeSettings,
)
from azure.identity import DefaultAzureCredential

from src.config.settings import AzureMLConfig, DeploymentConfig
from src.utils.logger import get_logger

logger = get_logger("endpoint_manager")


class EndpointManager:
    """
    Manages Azure ML managed online endpoints lifecycle.

    Provides blue-green deployment, canary rollouts, traffic shifting,
    and automated rollback capabilities for production endpoints.

    Usage:
        config = AzureMLConfig.from_environment(Environment.PROD)
        deploy_config = DeploymentConfig.for_environment(Environment.PROD)
        manager = EndpointManager(config, deploy_config)
        manager.create_or_update_endpoint()
        manager.deploy_blue_green("my-model", "5")
    """

    def __init__(
        self,
        azure_config: AzureMLConfig,
        deployment_config: DeploymentConfig,
        credential: Optional[Any] = None,
    ):
        """
        Initialize Endpoint Manager.

        Args:
            azure_config: Azure ML workspace configuration.
            deployment_config: Deployment parameters.
            credential: Azure credential. Defaults to DefaultAzureCredential.
        """
        self.azure_config = azure_config
        self.deployment_config = deployment_config
        self.credential = credential or DefaultAzureCredential()
        self._client: Optional[MLClient] = None

        logger.info(
            "EndpointManager initialized: endpoint=%s, env=%s",
            deployment_config.endpoint_name,
            azure_config.environment.value,
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

    def create_or_update_endpoint(self) -> ManagedOnlineEndpoint:
        """
        Create or update the managed online endpoint.

        Returns:
            The endpoint resource.
        """
        config = self.deployment_config

        endpoint = ManagedOnlineEndpoint(
            name=config.endpoint_name,
            description=f"ML model endpoint ({self.azure_config.environment.value})",
            auth_mode="key",
            tags=config.tags,
        )

        result = self.client.online_endpoints.begin_create_or_update(endpoint).result()
        logger.info("Endpoint '%s' created/updated successfully.", config.endpoint_name)
        return result

    def create_deployment(
        self,
        model_name: str,
        model_version: str,
        deployment_name: Optional[str] = None,
        instance_count: Optional[int] = None,
        traffic_percent: int = 0,
    ) -> ManagedOnlineDeployment:
        """
        Create a new deployment under the endpoint.

        Args:
            model_name: Registered model name.
            model_version: Model version to deploy.
            deployment_name: Override deployment name.
            instance_count: Override instance count.
            traffic_percent: Initial traffic allocation.

        Returns:
            The deployment resource.
        """
        config = self.deployment_config
        deploy_name = deployment_name or config.deployment_name

        deployment = ManagedOnlineDeployment(
            name=deploy_name,
            endpoint_name=config.endpoint_name,
            model=f"azureml:{model_name}:{model_version}",
            environment=f"{config.environment_name}@latest",
            code_configuration=CodeConfiguration(
                code="./scoring",
                scoring_script=config.scoring_script,
            ),
            instance_type=config.instance_type,
            instance_count=instance_count or config.instance_count,
            liveness_probe=ProbeSettings(
                period=config.liveness_probe_period,
                initial_delay=30,
                timeout=10,
                failure_threshold=30,
            ),
            readiness_probe=ProbeSettings(
                period=config.readiness_probe_period,
                initial_delay=30,
                timeout=10,
                failure_threshold=30,
            ),
            request_settings={
                "request_timeout_ms": config.request_timeout_ms,
                "max_concurrent_requests_per_instance": config.max_concurrent_requests,
            },
            tags={
                **config.tags,
                "model_name": model_name,
                "model_version": model_version,
            },
        )

        result = self.client.online_deployments.begin_create_or_update(deployment).result()

        # Set initial traffic
        if traffic_percent > 0:
            self.update_traffic({deploy_name: traffic_percent})

        logger.info(
            "Deployment '%s' created: model=%s:v%s, instances=%d, traffic=%d%%",
            deploy_name,
            model_name,
            model_version,
            instance_count or config.instance_count,
            traffic_percent,
        )

        return result

    def deploy_blue_green(
        self,
        model_name: str,
        model_version: str,
        canary_percent: int = 10,
    ) -> dict[str, Any]:
        """
        Execute a blue-green deployment with canary traffic shifting.

        Creates a new 'green' deployment alongside the existing 'blue'
        deployment, allocates canary traffic, and provides methods
        for full promotion or rollback.

        Args:
            model_name: Registered model name.
            model_version: Model version to deploy.
            canary_percent: Initial canary traffic percentage.

        Returns:
            Deployment status with blue/green endpoint details.
        """
        config = self.deployment_config
        blue_name = f"{config.deployment_name}-blue"
        green_name = f"{config.deployment_name}-green"

        logger.info(
            "Starting blue-green deployment: model=%s:v%s, canary=%d%%",
            model_name,
            model_version,
            canary_percent,
        )

        # Determine current active deployment
        current_deployments = self._get_current_deployments()
        active_name = blue_name if green_name in [d.name for d in current_deployments] else green_name
        new_name = green_name if active_name == blue_name else blue_name

        # Create the new (green) deployment
        self.create_deployment(
            model_name=model_name,
            model_version=model_version,
            deployment_name=new_name,
            traffic_percent=canary_percent,
        )

        # Update traffic split
        traffic = {
            active_name: 100 - canary_percent,
            new_name: canary_percent,
        }

        # Only include existing deployments in traffic
        existing_names = {d.name for d in self._get_current_deployments()}
        traffic = {k: v for k, v in traffic.items() if k in existing_names}
        self.update_traffic(traffic)

        result = {
            "status": "canary_deployed",
            "blue_deployment": active_name,
            "green_deployment": new_name,
            "traffic_split": traffic,
            "model": f"{model_name}:v{model_version}",
        }

        logger.info("Blue-green deployment canary active: %s", result)
        return result

    def promote_green(self, green_name: str, blue_name: str) -> dict[str, Any]:
        """
        Promote green deployment to receive 100% traffic and remove blue.

        Args:
            green_name: Name of the green (new) deployment.
            blue_name: Name of the blue (old) deployment.

        Returns:
            Promotion result status.
        """
        logger.info("Promoting green deployment '%s' to 100%% traffic.", green_name)

        self.update_traffic({green_name: 100})

        # Wait before removing old deployment
        time.sleep(30)

        try:
            self.client.online_deployments.begin_delete(
                name=blue_name,
                endpoint_name=self.deployment_config.endpoint_name,
            ).result()
            logger.info("Old blue deployment '%s' removed.", blue_name)
        except Exception as e:
            logger.warning("Could not remove old deployment '%s': %s", blue_name, str(e))

        return {
            "status": "promoted",
            "active_deployment": green_name,
            "removed_deployment": blue_name,
        }

    def rollback(self, green_name: str, blue_name: str) -> dict[str, Any]:
        """
        Rollback: route all traffic back to blue and remove green.

        Args:
            green_name: Name of the green (new) deployment to remove.
            blue_name: Name of the blue (old) deployment to restore.

        Returns:
            Rollback result status.
        """
        logger.info("Rolling back: restoring traffic to '%s'.", blue_name)

        self.update_traffic({blue_name: 100})

        try:
            self.client.online_deployments.begin_delete(
                name=green_name,
                endpoint_name=self.deployment_config.endpoint_name,
            ).result()
            logger.info("Green deployment '%s' removed.", green_name)
        except Exception as e:
            logger.warning("Could not remove green deployment '%s': %s", green_name, str(e))

        return {
            "status": "rolled_back",
            "active_deployment": blue_name,
            "removed_deployment": green_name,
        }

    def update_traffic(self, traffic_map: dict[str, int]) -> None:
        """
        Update traffic allocation across deployments.

        Args:
            traffic_map: Mapping of deployment name to traffic percentage.
        """
        endpoint = self.client.online_endpoints.get(self.deployment_config.endpoint_name)
        endpoint.traffic = traffic_map

        self.client.online_endpoints.begin_create_or_update(endpoint).result()
        logger.info("Traffic updated: %s", traffic_map)

    def get_endpoint_status(self) -> dict[str, Any]:
        """
        Get comprehensive endpoint and deployment status.

        Returns:
            Status dictionary with endpoint health and deployment details.
        """
        try:
            endpoint = self.client.online_endpoints.get(self.deployment_config.endpoint_name)
            deployments = self._get_current_deployments()

            return {
                "endpoint_name": endpoint.name,
                "provisioning_state": endpoint.provisioning_state,
                "scoring_uri": endpoint.scoring_uri,
                "traffic": endpoint.traffic,
                "deployments": [
                    {
                        "name": d.name,
                        "provisioning_state": d.provisioning_state,
                        "instance_type": d.instance_type,
                        "instance_count": d.instance_count,
                        "model": d.model,
                    }
                    for d in deployments
                ],
            }
        except Exception as e:
            logger.error("Failed to get endpoint status: %s", str(e))
            return {"error": str(e)}

    def _get_current_deployments(self) -> list[ManagedOnlineDeployment]:
        """Get all current deployments for the endpoint."""
        return list(
            self.client.online_deployments.list(
                endpoint_name=self.deployment_config.endpoint_name
            )
        )

    def delete_endpoint(self) -> None:
        """Delete the managed online endpoint and all deployments."""
        endpoint_name = self.deployment_config.endpoint_name
        logger.warning("Deleting endpoint '%s' and all deployments.", endpoint_name)

        self.client.online_endpoints.begin_delete(name=endpoint_name).result()
        logger.info("Endpoint '%s' deleted.", endpoint_name)
