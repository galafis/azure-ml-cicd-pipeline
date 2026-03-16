"""
Unit Tests - Security (Key Vault & Network Configuration)

Author: Gabriel Demetrios Lafis
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, PropertyMock

from src.security.key_vault import KeyVaultManager
from src.security.network import NetworkConfig, NSGRule, VNetConfig
from src.config.settings import AzureMLConfig, Environment


class TestKeyVaultManager:
    """Tests for KeyVaultManager class."""

    @pytest.fixture
    def kv_manager(self, mock_credential):
        manager = KeyVaultManager(
            vault_url="https://kv-test.vault.azure.net/",
            credential=mock_credential,
            cache_ttl_seconds=60,
        )
        manager._client = MagicMock()
        return manager

    def test_initialization(self, mock_credential):
        """Test Key Vault manager initializes correctly."""
        manager = KeyVaultManager(
            vault_url="https://kv-test.vault.azure.net/",
            credential=mock_credential,
        )
        assert manager.vault_url == "https://kv-test.vault.azure.net/"

    def test_from_config(self, azure_config):
        """Test creation from Azure ML config."""
        manager = KeyVaultManager.from_config(azure_config)
        assert "vault.azure.net" in manager.vault_url

    def test_get_secret(self, kv_manager):
        """Test secret retrieval."""
        mock_secret = MagicMock()
        mock_secret.value = "super-secret-value"
        kv_manager._client.get_secret.return_value = mock_secret

        value = kv_manager.get_secret("test-secret")
        assert value == "super-secret-value"

    def test_get_secret_caching(self, kv_manager):
        """Test that secrets are cached."""
        mock_secret = MagicMock()
        mock_secret.value = "cached-value"
        kv_manager._client.get_secret.return_value = mock_secret

        # First call hits Key Vault
        value1 = kv_manager.get_secret("test-secret")
        # Second call should use cache
        value2 = kv_manager.get_secret("test-secret")

        assert value1 == value2
        kv_manager._client.get_secret.assert_called_once()

    def test_get_secret_no_cache(self, kv_manager):
        """Test secret retrieval without cache."""
        mock_secret = MagicMock()
        mock_secret.value = "no-cache-value"
        kv_manager._client.get_secret.return_value = mock_secret

        kv_manager.get_secret("test-secret", use_cache=False)
        kv_manager.get_secret("test-secret", use_cache=False)

        assert kv_manager._client.get_secret.call_count == 2

    def test_set_secret(self, kv_manager):
        """Test secret creation/update."""
        mock_secret = MagicMock()
        mock_secret.properties.version = "v1"
        kv_manager._client.set_secret.return_value = mock_secret

        result = kv_manager.set_secret("new-secret", "new-value")
        kv_manager._client.set_secret.assert_called_once()

    def test_set_secret_invalidates_cache(self, kv_manager):
        """Test that setting a secret clears the cache for that key."""
        # Pre-populate cache
        kv_manager._cache["test-secret:latest"] = ("old-value", datetime.now(timezone.utc))

        mock_secret = MagicMock()
        mock_secret.properties.version = "v2"
        kv_manager._client.set_secret.return_value = mock_secret

        kv_manager.set_secret("test-secret", "new-value")
        assert "test-secret:latest" not in kv_manager._cache

    def test_rotate_secret(self, kv_manager):
        """Test secret rotation with expiration."""
        mock_secret = MagicMock()
        mock_secret.properties.version = "v2"
        kv_manager._client.set_secret.return_value = mock_secret

        result = kv_manager.rotate_secret("rotate-me", "new-value", rotation_period_days=30)
        kv_manager._client.set_secret.assert_called_once()

    def test_clear_cache(self, kv_manager):
        """Test cache clearing."""
        kv_manager._cache["key1:latest"] = ("val", datetime.now(timezone.utc))
        kv_manager._cache["key2:latest"] = ("val", datetime.now(timezone.utc))

        kv_manager.clear_cache()
        assert len(kv_manager._cache) == 0

    def test_get_secret_raises_on_empty_value(self, kv_manager):
        """Test that a secret with no value raises ValueError."""
        mock_secret = MagicMock()
        mock_secret.value = None
        kv_manager._client.get_secret.return_value = mock_secret

        with pytest.raises(ValueError, match="has no value"):
            kv_manager.get_secret("empty-secret", use_cache=False)


class TestNetworkConfig:
    """Tests for NetworkConfig class."""

    def test_dev_vnet_config(self, azure_config):
        """Test VNet configuration for dev environment."""
        network = NetworkConfig(azure_config)
        vnet = network.get_vnet_config()

        assert "dev" in vnet.vnet_name
        assert vnet.address_prefix.startswith("10.0.")
        assert "ml-training" in vnet.subnets

    def test_prod_vnet_config(self, prod_config):
        """Test VNet configuration for prod environment."""
        network = NetworkConfig(prod_config)
        vnet = network.get_vnet_config()

        assert "prod" in vnet.vnet_name
        assert vnet.address_prefix.startswith("10.2.")
        assert "ml-management" in vnet.subnets

    def test_nsg_rules_base(self, azure_config):
        """Test base NSG rules are generated."""
        network = NetworkConfig(azure_config)
        rules = network.get_nsg_rules()

        assert len(rules) >= 7
        rule_names = [r.name for r in rules]
        assert "AllowAzureMLInbound" in rule_names
        assert "AllowStorageOutbound" in rule_names

    def test_prod_nsg_deny_rule(self, prod_config):
        """Test prod environment has deny-all outbound rule."""
        network = NetworkConfig(prod_config)
        rules = network.get_nsg_rules()

        deny_rules = [r for r in rules if "Deny" in r.name]
        assert len(deny_rules) >= 1

    def test_private_endpoints(self, azure_config):
        """Test private endpoint configurations."""
        network = NetworkConfig(azure_config)
        endpoints = network.get_private_endpoints()

        assert len(endpoints) >= 4
        endpoint_names = [pe.name for pe in endpoints]
        assert any("storage" in name for name in endpoint_names)
        assert any("keyvault" in name for name in endpoint_names)

    def test_prod_private_endpoints_include_appinsights(self, prod_config):
        """Test prod environment includes App Insights private endpoint."""
        network = NetworkConfig(prod_config)
        endpoints = network.get_private_endpoints()

        endpoint_names = [pe.name for pe in endpoints]
        assert any("appinsights" in name for name in endpoint_names)

    def test_network_summary(self, azure_config):
        """Test network summary generation."""
        network = NetworkConfig(azure_config)
        summary = network.get_network_summary()

        assert summary["environment"] == "dev"
        assert "vnet" in summary
        assert "nsg_rules_count" in summary
        assert "private_endpoints" in summary
