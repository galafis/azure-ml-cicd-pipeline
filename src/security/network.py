"""
Network Configuration

Manages Azure network security configuration for ML workspaces
including VNet integration, private endpoints, and NSG rules.

Author: Gabriel Demetrios Lafis
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.config.settings import AzureMLConfig, Environment
from src.utils.logger import get_logger

logger = get_logger("network_config")


@dataclass
class NSGRule:
    """Network Security Group rule definition."""

    name: str
    priority: int
    direction: str  # Inbound, Outbound
    access: str  # Allow, Deny
    protocol: str  # Tcp, Udp, *
    source_address_prefix: str
    destination_address_prefix: str
    source_port_range: str = "*"
    destination_port_range: str = "*"
    description: str = ""


@dataclass
class PrivateEndpointConfig:
    """Private endpoint configuration."""

    name: str
    resource_type: str  # Microsoft.MachineLearningServices/workspaces, etc.
    subresource_names: list[str] = field(default_factory=list)
    private_dns_zone_name: Optional[str] = None
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class VNetConfig:
    """Virtual Network configuration."""

    vnet_name: str
    address_prefix: str
    subnets: dict[str, str] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)


class NetworkConfig:
    """
    Manages network security configuration for Azure ML environments.

    Provides VNet integration, private endpoint management, and NSG
    rule definitions for securing ML workspace communication.

    Usage:
        config = AzureMLConfig.from_environment(Environment.PROD)
        network = NetworkConfig(config)
        vnet = network.get_vnet_config()
        nsg_rules = network.get_nsg_rules()
        endpoints = network.get_private_endpoints()
    """

    def __init__(self, azure_config: AzureMLConfig):
        """
        Initialize Network Configuration.

        Args:
            azure_config: Azure ML workspace configuration.
        """
        self.azure_config = azure_config
        self.env = azure_config.environment

        logger.info(
            "NetworkConfig initialized: env=%s, region=%s",
            self.env.value,
            azure_config.region,
        )

    def get_vnet_config(self) -> VNetConfig:
        """
        Get Virtual Network configuration for the environment.

        Returns:
            VNetConfig with environment-appropriate network settings.
        """
        env_name = self.env.value
        rg = self.azure_config.resource_group

        vnet_configs = {
            Environment.DEV: VNetConfig(
                vnet_name=f"vnet-ml-{env_name}-{rg}",
                address_prefix="10.0.0.0/16",
                subnets={
                    "ml-training": "10.0.1.0/24",
                    "ml-inference": "10.0.2.0/24",
                    "ml-data": "10.0.3.0/24",
                },
                tags={"environment": env_name},
            ),
            Environment.STAGING: VNetConfig(
                vnet_name=f"vnet-ml-{env_name}-{rg}",
                address_prefix="10.1.0.0/16",
                subnets={
                    "ml-training": "10.1.1.0/24",
                    "ml-inference": "10.1.2.0/24",
                    "ml-data": "10.1.3.0/24",
                    "ml-monitoring": "10.1.4.0/24",
                },
                tags={"environment": env_name},
            ),
            Environment.PROD: VNetConfig(
                vnet_name=f"vnet-ml-{env_name}-{rg}",
                address_prefix="10.2.0.0/16",
                subnets={
                    "ml-training": "10.2.1.0/24",
                    "ml-inference": "10.2.2.0/24",
                    "ml-data": "10.2.3.0/24",
                    "ml-monitoring": "10.2.4.0/24",
                    "ml-management": "10.2.5.0/24",
                },
                tags={"environment": env_name},
            ),
        }

        config = vnet_configs.get(self.env, vnet_configs[Environment.DEV])
        logger.info("VNet config: %s (%s)", config.vnet_name, config.address_prefix)
        return config

    def get_nsg_rules(self) -> list[NSGRule]:
        """
        Get NSG rules for the environment.

        Returns:
            List of NSGRule definitions.
        """
        base_rules = [
            NSGRule(
                name="AllowAzureMLInbound",
                priority=100,
                direction="Inbound",
                access="Allow",
                protocol="Tcp",
                source_address_prefix="AzureMachineLearning",
                destination_address_prefix="*",
                destination_port_range="44224",
                description="Allow Azure ML control plane",
            ),
            NSGRule(
                name="AllowBatchNodeManagement",
                priority=110,
                direction="Inbound",
                access="Allow",
                protocol="Tcp",
                source_address_prefix="BatchNodeManagement",
                destination_address_prefix="*",
                destination_port_range="29876-29877",
                description="Allow Batch node management",
            ),
            NSGRule(
                name="AllowAzureActiveDirectoryOutbound",
                priority=100,
                direction="Outbound",
                access="Allow",
                protocol="Tcp",
                source_address_prefix="*",
                destination_address_prefix="AzureActiveDirectory",
                destination_port_range="443",
                description="Allow AAD authentication",
            ),
            NSGRule(
                name="AllowAzureMLOutbound",
                priority=110,
                direction="Outbound",
                access="Allow",
                protocol="Tcp",
                source_address_prefix="*",
                destination_address_prefix="AzureMachineLearning",
                destination_port_range="443",
                description="Allow Azure ML API access",
            ),
            NSGRule(
                name="AllowStorageOutbound",
                priority=120,
                direction="Outbound",
                access="Allow",
                protocol="Tcp",
                source_address_prefix="*",
                destination_address_prefix="Storage",
                destination_port_range="443",
                description="Allow Azure Storage access",
            ),
            NSGRule(
                name="AllowKeyVaultOutbound",
                priority=130,
                direction="Outbound",
                access="Allow",
                protocol="Tcp",
                source_address_prefix="*",
                destination_address_prefix="AzureKeyVault",
                destination_port_range="443",
                description="Allow Key Vault access",
            ),
            NSGRule(
                name="AllowContainerRegistryOutbound",
                priority=140,
                direction="Outbound",
                access="Allow",
                protocol="Tcp",
                source_address_prefix="*",
                destination_address_prefix="AzureContainerRegistry",
                destination_port_range="443",
                description="Allow ACR access",
            ),
        ]

        # Add stricter rules for production
        if self.env == Environment.PROD:
            base_rules.append(
                NSGRule(
                    name="DenyAllOtherOutbound",
                    priority=4000,
                    direction="Outbound",
                    access="Deny",
                    protocol="*",
                    source_address_prefix="*",
                    destination_address_prefix="Internet",
                    description="Deny all other internet outbound in prod",
                )
            )

        logger.info("NSG rules generated: %d rules for %s", len(base_rules), self.env.value)
        return base_rules

    def get_private_endpoints(self) -> list[PrivateEndpointConfig]:
        """
        Get private endpoint configurations for the environment.

        Returns:
            List of PrivateEndpointConfig definitions.
        """
        env_name = self.env.value
        rg = self.azure_config.resource_group

        endpoints = [
            PrivateEndpointConfig(
                name=f"pe-ml-workspace-{env_name}",
                resource_type="Microsoft.MachineLearningServices/workspaces",
                subresource_names=["amlworkspace"],
                private_dns_zone_name="privatelink.api.azureml.ms",
                tags={"environment": env_name},
            ),
            PrivateEndpointConfig(
                name=f"pe-storage-{env_name}",
                resource_type="Microsoft.Storage/storageAccounts",
                subresource_names=["blob", "file"],
                private_dns_zone_name="privatelink.blob.core.windows.net",
                tags={"environment": env_name},
            ),
            PrivateEndpointConfig(
                name=f"pe-keyvault-{env_name}",
                resource_type="Microsoft.KeyVault/vaults",
                subresource_names=["vault"],
                private_dns_zone_name="privatelink.vaultcore.azure.net",
                tags={"environment": env_name},
            ),
            PrivateEndpointConfig(
                name=f"pe-acr-{env_name}",
                resource_type="Microsoft.ContainerRegistry/registries",
                subresource_names=["registry"],
                private_dns_zone_name="privatelink.azurecr.io",
                tags={"environment": env_name},
            ),
        ]

        # Add Application Insights private endpoint for staging/prod
        if self.env in (Environment.STAGING, Environment.PROD):
            endpoints.append(
                PrivateEndpointConfig(
                    name=f"pe-appinsights-{env_name}",
                    resource_type="Microsoft.Insights/components",
                    subresource_names=["azuremonitor"],
                    private_dns_zone_name="privatelink.monitor.azure.com",
                    tags={"environment": env_name},
                )
            )

        logger.info("Private endpoints configured: %d for %s", len(endpoints), env_name)
        return endpoints

    def get_network_summary(self) -> dict[str, Any]:
        """
        Get a complete network configuration summary.

        Returns:
            Dictionary with VNet, NSG, and private endpoint details.
        """
        vnet = self.get_vnet_config()
        nsg_rules = self.get_nsg_rules()
        private_endpoints = self.get_private_endpoints()

        return {
            "environment": self.env.value,
            "vnet": {
                "name": vnet.vnet_name,
                "address_prefix": vnet.address_prefix,
                "subnets": vnet.subnets,
            },
            "nsg_rules_count": len(nsg_rules),
            "nsg_rules": [
                {"name": r.name, "direction": r.direction, "access": r.access}
                for r in nsg_rules
            ],
            "private_endpoints": [
                {"name": pe.name, "resource_type": pe.resource_type}
                for pe in private_endpoints
            ],
        }
