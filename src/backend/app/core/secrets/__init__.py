"""Vault client abstraction for secrets management (DEF-007)."""
from .vault_client import (
    AzureVaultClient,
    LocalDBVaultClient,
    VaultClient,
    get_vault_client,
)

__all__ = [
    "VaultClient",
    "AzureVaultClient",
    "LocalDBVaultClient",
    "get_vault_client",
]
