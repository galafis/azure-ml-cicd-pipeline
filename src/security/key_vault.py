"""
Key Vault Manager

Manages Azure Key Vault operations including secret retrieval,
managed identity authentication, and credential rotation.

Author: Gabriel Demetrios Lafis
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient, KeyVaultSecret

from src.config.settings import AzureMLConfig
from src.utils.logger import get_logger

logger = get_logger("key_vault")


class KeyVaultManager:
    """
    Manages Azure Key Vault secret operations.

    Provides secure secret retrieval, caching, and credential
    rotation support with managed identity authentication.

    Usage:
        kv_manager = KeyVaultManager("https://my-vault.vault.azure.net/")
        secret = kv_manager.get_secret("db-connection-string")
    """

    def __init__(
        self,
        vault_url: str,
        credential: Optional[Any] = None,
        use_managed_identity: bool = False,
        managed_identity_client_id: Optional[str] = None,
        cache_ttl_seconds: int = 300,
    ):
        """
        Initialize Key Vault Manager.

        Args:
            vault_url: Key Vault URL (https://<name>.vault.azure.net/).
            credential: Azure credential. Auto-selected if None.
            use_managed_identity: Use Managed Identity for authentication.
            managed_identity_client_id: Client ID for user-assigned MI.
            cache_ttl_seconds: Secret cache TTL in seconds.
        """
        self.vault_url = vault_url
        self.cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[str, datetime]] = {}

        if credential:
            self.credential = credential
        elif use_managed_identity:
            if managed_identity_client_id:
                self.credential = ManagedIdentityCredential(
                    client_id=managed_identity_client_id
                )
            else:
                self.credential = ManagedIdentityCredential()
            logger.info("Using Managed Identity for Key Vault authentication.")
        else:
            self.credential = DefaultAzureCredential()

        self._client: Optional[SecretClient] = None
        logger.info("KeyVaultManager initialized: vault=%s", vault_url)

    @property
    def client(self) -> SecretClient:
        """Lazy-initialized Key Vault secret client."""
        if self._client is None:
            self._client = SecretClient(
                vault_url=self.vault_url,
                credential=self.credential,
            )
        return self._client

    @classmethod
    def from_config(
        cls,
        azure_config: AzureMLConfig,
        **kwargs,
    ) -> KeyVaultManager:
        """
        Create KeyVaultManager from Azure ML configuration.

        Args:
            azure_config: Azure ML workspace configuration.
            **kwargs: Additional constructor arguments.

        Returns:
            Configured KeyVaultManager instance.
        """
        env = azure_config.environment.value
        vault_name = f"kv-ml-{env}-{azure_config.resource_group[:10]}"
        vault_url = f"https://{vault_name}.vault.azure.net/"

        return cls(vault_url=vault_url, **kwargs)

    def get_secret(
        self,
        name: str,
        version: Optional[str] = None,
        use_cache: bool = True,
    ) -> str:
        """
        Retrieve a secret value from Key Vault.

        Args:
            name: Secret name.
            version: Specific secret version. Defaults to latest.
            use_cache: Whether to use the local cache.

        Returns:
            Secret value string.

        Raises:
            ValueError: If the secret is not found or has no value.
        """
        cache_key = f"{name}:{version or 'latest'}"

        if use_cache and cache_key in self._cache:
            value, cached_at = self._cache[cache_key]
            if datetime.now(timezone.utc) - cached_at < timedelta(seconds=self.cache_ttl):
                logger.debug("Secret '%s' retrieved from cache.", name)
                return value

        try:
            secret = self.client.get_secret(name, version=version)
            if secret.value is None:
                raise ValueError(f"Secret '{name}' exists but has no value.")

            if use_cache:
                self._cache[cache_key] = (secret.value, datetime.now(timezone.utc))

            logger.info("Secret '%s' retrieved from Key Vault.", name)
            return secret.value

        except Exception as e:
            logger.error("Failed to retrieve secret '%s': %s", name, str(e))
            raise

    def set_secret(
        self,
        name: str,
        value: str,
        content_type: Optional[str] = None,
        tags: Optional[dict[str, str]] = None,
        expires_on: Optional[datetime] = None,
    ) -> KeyVaultSecret:
        """
        Set or update a secret in Key Vault.

        Args:
            name: Secret name.
            value: Secret value.
            content_type: MIME content type.
            tags: Metadata tags.
            expires_on: Expiration datetime.

        Returns:
            The created/updated secret.
        """
        secret = self.client.set_secret(
            name,
            value,
            content_type=content_type,
            tags=tags,
            expires_on=expires_on,
        )

        # Invalidate cache
        for key in list(self._cache.keys()):
            if key.startswith(f"{name}:"):
                del self._cache[key]

        logger.info("Secret '%s' set in Key Vault (version: %s).", name, secret.properties.version)
        return secret

    def rotate_secret(
        self,
        name: str,
        new_value: str,
        rotation_period_days: int = 90,
    ) -> KeyVaultSecret:
        """
        Rotate a secret with a new value and set expiration.

        Args:
            name: Secret name to rotate.
            new_value: New secret value.
            rotation_period_days: Days until next rotation.

        Returns:
            The rotated secret.
        """
        expires_on = datetime.now(timezone.utc) + timedelta(days=rotation_period_days)

        secret = self.set_secret(
            name=name,
            value=new_value,
            tags={
                "rotated_at": datetime.now(timezone.utc).isoformat(),
                "rotation_period_days": str(rotation_period_days),
            },
            expires_on=expires_on,
        )

        logger.info(
            "Secret '%s' rotated. Next rotation: %s",
            name,
            expires_on.isoformat(),
        )
        return secret

    def list_secrets(self) -> list[dict[str, Any]]:
        """
        List all secrets in the Key Vault (metadata only, no values).

        Returns:
            List of secret metadata dictionaries.
        """
        secrets = []
        for secret_properties in self.client.list_properties_of_secrets():
            secrets.append({
                "name": secret_properties.name,
                "enabled": secret_properties.enabled,
                "created_on": secret_properties.created_on.isoformat() if secret_properties.created_on else None,
                "updated_on": secret_properties.updated_on.isoformat() if secret_properties.updated_on else None,
                "expires_on": secret_properties.expires_on.isoformat() if secret_properties.expires_on else None,
                "content_type": secret_properties.content_type,
                "tags": secret_properties.tags,
            })

        logger.info("Listed %d secrets from Key Vault.", len(secrets))
        return secrets

    def check_expiring_secrets(self, days_threshold: int = 30) -> list[dict[str, Any]]:
        """
        Check for secrets expiring within the given threshold.

        Args:
            days_threshold: Number of days to look ahead.

        Returns:
            List of secrets approaching expiration.
        """
        threshold_date = datetime.now(timezone.utc) + timedelta(days=days_threshold)
        expiring = []

        for secret_properties in self.client.list_properties_of_secrets():
            if (
                secret_properties.expires_on
                and secret_properties.expires_on <= threshold_date
                and secret_properties.enabled
            ):
                expiring.append({
                    "name": secret_properties.name,
                    "expires_on": secret_properties.expires_on.isoformat(),
                    "days_until_expiry": (
                        secret_properties.expires_on - datetime.now(timezone.utc)
                    ).days,
                })

        if expiring:
            logger.warning(
                "%d secrets expiring within %d days: %s",
                len(expiring),
                days_threshold,
                ", ".join(s["name"] for s in expiring),
            )

        return expiring

    def clear_cache(self) -> None:
        """Clear the local secret cache."""
        self._cache.clear()
        logger.info("Secret cache cleared.")
