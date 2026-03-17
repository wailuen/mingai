"""
Vault client abstraction for HAR agent Ed25519 private key storage (DEF-007).

This module provides a `VaultClient` interface with two concrete implementations:

  1. `AzureVaultClient` — production implementation backed by Azure Key Vault.
     Activated when `AZURE_KEY_VAULT_URL` environment variable is set.
     Vault ref format: ``azure-kv://{vault_url}/secrets/{key_id}``

  2. `LocalDBVaultClient` — dev/test fallback. Encodes the secret inline in the
     vault_ref URI as ``local://{base64_encoded_secret}``.  Logs a warning on
     every call so developers notice they are NOT using a real vault.

Use `get_vault_client()` (the factory) rather than constructing instances directly.

--------------------------------------------------------------------------------
Migration note — moving `agent_cards.private_key_enc` to vault_ref
--------------------------------------------------------------------------------
When this module is adopted for existing agent cards the recommended migration is:

1. Add a new nullable column ``private_key_vault_ref TEXT`` to ``agent_cards``
   in a new Alembic migration (e.g. ``v030_agent_cards_vault_ref.py``).

2. Write a one-off data migration script that:
   a. Reads each row with a non-null ``private_key_enc`` value.
   b. Calls ``get_vault_client().store_secret(agent_id, plaintext)`` where
      ``plaintext`` is obtained by decrypting ``private_key_enc`` via
      ``app.modules.har.crypto.get_fernet().decrypt()``.
   c. Writes the returned vault_ref to ``private_key_vault_ref``.
   d. Nullifies ``private_key_enc`` after successful migration.

3. Update ``app.modules.har.crypto.sign_payload()`` to accept a vault_ref
   string, resolve it via ``get_vault_client().get_secret(vault_ref)``, and
   feed the plaintext into the existing Fernet decrypt / sign flow.

4. In a follow-up migration (after full rollout), drop the ``private_key_enc``
   column.

IMPORTANT: Steps 1-4 should be done as separate, individually-reviewed PRs
to keep rollback surface small.
--------------------------------------------------------------------------------

Security guarantees
-------------------
- Plaintext secret values are NEVER written to any log.
- Plaintext secret values are NEVER included in vault_ref URIs for the Azure
  implementation.
- ``LocalDBVaultClient`` is explicitly **not** secure for production — it is
  equivalent to storing the secret in the DB column directly (base64 is not
  encryption).  It must only be used in development and CI environments.
"""
from __future__ import annotations

import base64
import os
from abc import ABC, abstractmethod

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class VaultClient(ABC):
    """Abstract vault client interface for secret storage and retrieval."""

    @abstractmethod
    def store_secret(self, key_id: str, plaintext: str) -> str:
        """
        Persist ``plaintext`` under the given ``key_id`` and return a vault_ref
        URI that can be stored in the database instead of the raw secret.

        Args:
            key_id:    Logical identifier for the secret (e.g. agent UUID).
                       Must be non-empty and must not contain ``://``.
            plaintext: The secret value to persist. Never logged.

        Returns:
            A vault_ref URI string.  The exact scheme depends on the
            implementation (``azure-kv://...`` or ``local://...``).

        Raises:
            ValueError: If ``key_id`` is empty or malformed.
            RuntimeError: If the underlying vault call fails.
        """

    @abstractmethod
    def get_secret(self, vault_ref: str) -> str:
        """
        Resolve a vault_ref URI back to the original plaintext secret.

        Args:
            vault_ref: The URI returned by a previous ``store_secret()`` call.

        Returns:
            The original plaintext secret. Never logged by this method.

        Raises:
            ValueError: If ``vault_ref`` is empty or uses an unrecognised scheme.
            RuntimeError: If the underlying vault call fails.
        """


# ---------------------------------------------------------------------------
# Azure Key Vault implementation
# ---------------------------------------------------------------------------

_AZURE_SCHEME = "azure-kv://"
_LOCAL_SCHEME = "local://"


class AzureVaultClient(VaultClient):
    """
    Production vault client backed by Azure Key Vault.

    Requires:
    - ``AZURE_KEY_VAULT_URL`` environment variable (e.g.
      ``https://my-vault.vault.azure.net/``).
    - ``azure-keyvault-secrets`` and ``azure-identity`` packages installed.
    - An identity (DefaultAzureCredential) with Key Vault Secrets Officer role.

    Vault ref format: ``azure-kv://{vault_url}/secrets/{key_id}``
    """

    def __init__(self, vault_url: str) -> None:
        if not vault_url:
            raise ValueError("vault_url must be non-empty for AzureVaultClient")
        # Normalise: strip trailing slash
        self._vault_url = vault_url.rstrip("/")

    def _get_client(self):  # type: ignore[return]
        """
        Lazily import and construct the Azure SecretClient.

        Lazy import avoids a hard dependency on azure-keyvault-secrets in
        environments where it is not installed (dev / CI).

        Returns:
            azure.keyvault.secrets.SecretClient
        """
        try:
            from azure.identity import DefaultAzureCredential  # type: ignore[import]
            from azure.keyvault.secrets import SecretClient  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "azure-keyvault-secrets and azure-identity packages are required "
                "for AzureVaultClient. Install them with: "
                "pip install azure-keyvault-secrets azure-identity"
            ) from exc

        credential = DefaultAzureCredential()
        return SecretClient(vault_url=self._vault_url, credential=credential)

    def store_secret(self, key_id: str, plaintext: str) -> str:
        """Store a secret in Azure Key Vault and return a vault_ref URI."""
        if not key_id:
            raise ValueError("key_id must be non-empty")
        if "://" in key_id:
            raise ValueError("key_id must not contain '://'")

        client = self._get_client()
        # Azure Key Vault secret names may only contain alphanumeric and dashes.
        # Replace underscores with dashes to be safe.
        safe_name = key_id.replace("_", "-")
        # plaintext intentionally not logged
        client.set_secret(safe_name, plaintext)

        vault_ref = f"{_AZURE_SCHEME}{self._vault_url}/secrets/{safe_name}"
        logger.info(
            "vault_secret_stored",
            key_id=key_id,
            vault_ref=vault_ref,
            backend="azure_key_vault",
        )
        return vault_ref

    def get_secret(self, vault_ref: str) -> str:
        """Retrieve a secret from Azure Key Vault using a vault_ref URI."""
        if not vault_ref:
            raise ValueError("vault_ref must be non-empty")
        if not vault_ref.startswith(_AZURE_SCHEME):
            raise ValueError(
                f"vault_ref has unexpected scheme — expected '{_AZURE_SCHEME}', "
                f"got: {vault_ref[:20]!r}"
            )

        # Extract secret name from the URI tail: .../secrets/{name}
        try:
            secret_name = vault_ref.split("/secrets/", 1)[1]
        except IndexError:
            raise ValueError(
                f"vault_ref is malformed — cannot extract secret name: {vault_ref!r}"
            )

        if not secret_name:
            raise ValueError(f"vault_ref contains an empty secret name: {vault_ref!r}")

        client = self._get_client()
        secret_bundle = client.get_secret(secret_name)
        # plaintext intentionally not logged
        logger.info(
            "vault_secret_retrieved",
            secret_name=secret_name,
            backend="azure_key_vault",
        )
        return secret_bundle.value  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Local (DB-backed) fallback implementation
# ---------------------------------------------------------------------------


class LocalDBVaultClient(VaultClient):
    """
    Development/test fallback vault client.

    Encodes the secret inline in the vault_ref as ``local://{base64(plaintext)}``.
    This provides NO real security isolation — it is functionally equivalent to
    storing the raw secret in the database column.

    A WARNING is logged on every call so that the developer is aware they are
    not using a real vault.  This implementation MUST NOT be used in production.
    """

    def store_secret(self, key_id: str, plaintext: str) -> str:
        """Encode the secret inline and return a local:// vault_ref URI."""
        if not key_id:
            raise ValueError("key_id must be non-empty")
        if "://" in key_id:
            raise ValueError("key_id must not contain '://'")

        logger.warning(
            "local_vault_client_in_use",
            message=(
                "LocalDBVaultClient is storing a secret inline in the vault_ref. "
                "This provides NO production-grade security isolation. "
                "Set AZURE_KEY_VAULT_URL to enable Azure Key Vault."
            ),
            key_id=key_id,
        )
        # plaintext intentionally not logged
        encoded = base64.urlsafe_b64encode(plaintext.encode("utf-8")).decode("ascii")
        vault_ref = f"{_LOCAL_SCHEME}{encoded}"
        return vault_ref

    def get_secret(self, vault_ref: str) -> str:
        """Decode an inline local:// vault_ref back to the original plaintext."""
        if not vault_ref:
            raise ValueError("vault_ref must be non-empty")
        if not vault_ref.startswith(_LOCAL_SCHEME):
            raise ValueError(
                f"vault_ref has unexpected scheme — expected '{_LOCAL_SCHEME}', "
                f"got: {vault_ref[:20]!r}"
            )

        logger.warning(
            "local_vault_client_in_use",
            message=(
                "LocalDBVaultClient is resolving an inline secret from vault_ref. "
                "This provides NO production-grade security isolation. "
                "Set AZURE_KEY_VAULT_URL to enable Azure Key Vault."
            ),
        )

        encoded = vault_ref[len(_LOCAL_SCHEME) :]
        if not encoded:
            raise ValueError("vault_ref contains an empty encoded payload")

        try:
            # Add padding if stripped
            padding = (4 - len(encoded) % 4) % 4
            plaintext = base64.urlsafe_b64decode(encoded + "=" * padding).decode(
                "utf-8"
            )
        except Exception as exc:
            raise ValueError(
                f"vault_ref payload could not be base64-decoded: {exc}"
            ) from exc

        # plaintext intentionally not logged
        return plaintext


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_vault_client() -> VaultClient:
    """
    Return the appropriate VaultClient based on environment configuration.

    - If ``AZURE_KEY_VAULT_URL`` is set (non-empty): returns ``AzureVaultClient``.
      Falls back to ``LocalDBVaultClient`` if azure-keyvault-secrets is not
      installed (logs an error and warns).
    - Otherwise: returns ``LocalDBVaultClient`` with a startup warning.

    This function reads the environment variable at call time — it is NOT
    cached, so tests can patch ``os.environ`` without worrying about
    ``lru_cache`` staleness.
    """
    vault_url = os.environ.get("AZURE_KEY_VAULT_URL", "").strip()

    if vault_url:
        # Validate the azure SDK is available before committing to the Azure client
        try:
            import azure.keyvault.secrets  # noqa: F401  # type: ignore[import]
            import azure.identity  # noqa: F401  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "AZURE_KEY_VAULT_URL is set but azure-keyvault-secrets / "
                "azure-identity packages are not installed. "
                "Install: pip install azure-keyvault-secrets azure-identity"
            ) from exc

        logger.info(
            "vault_client_initialized",
            backend="azure_key_vault",
            vault_url=vault_url,
        )
        return AzureVaultClient(vault_url)

    logger.warning(
        "vault_client_initialized",
        backend="local_db",
        message=(
            "AZURE_KEY_VAULT_URL is not set. Using LocalDBVaultClient — "
            "NOT suitable for production. Set AZURE_KEY_VAULT_URL to use Azure Key Vault."
        ),
    )
    return LocalDBVaultClient()
