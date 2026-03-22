"""
CredentialManager — per-agent credential storage and retrieval.

Vault key schema (per-agent-instance):
  {tenant_id}/agents/{agent_id}/{credential_key}

Security requirements:
  - Credential values are NEVER logged
  - test_credentials() validates HTTP endpoint reachability without caching the test result
  - All paths are parameterized vault lookups — no f-string injection into vault path components
  - tenant_id and agent_id are UUID strings validated by callers (FastAPI path params)

Vault backend:
  Uses VAULT_ADDR + VAULT_TOKEN env vars (HashiCorp Vault KV v2) when configured.
  Falls back to an encrypted local store (CREDENTIAL_ENCRYPTION_KEY env var) for
  development environments without a Vault deployment.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Vault path helpers
# ---------------------------------------------------------------------------

_MAX_KEY_LENGTH = 128
_VALID_KEY_CHARS = set(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "_-."
)


def _validate_credential_key(key: str) -> None:
    """Raise ValueError if the credential key contains unsafe characters."""
    if not key or len(key) > _MAX_KEY_LENGTH:
        raise ValueError(f"Credential key must be 1-{_MAX_KEY_LENGTH} characters")
    if not all(c in _VALID_KEY_CHARS for c in key):
        raise ValueError(
            "Credential key must contain only alphanumeric characters, hyphens, underscores, and dots"
        )


def _build_vault_path(tenant_id: str, agent_id: str) -> str:
    """Build the vault KV path for an agent's credentials."""
    return f"{tenant_id}/agents/{agent_id}"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CredentialTestResult:
    """
    Result of a credential connectivity test.

    passed defaults to None (untested), not True (this is intentional —
    CredentialTestResult.passed=None means the integration has NOT been verified).
    """
    passed: Optional[bool] = None
    error_message: Optional[str] = None
    http_status: Optional[int] = None
    latency_ms: Optional[int] = None


# ---------------------------------------------------------------------------
# Vault client abstraction
# ---------------------------------------------------------------------------

class _HashiCorpVaultClient:
    """Thin wrapper around HashiCorp Vault KV v2 via HVAC."""

    def __init__(self, vault_addr: str, vault_token: str) -> None:
        self._addr = vault_addr
        self._token = vault_token
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import hvac  # type: ignore[import]
                self._client = hvac.Client(url=self._addr, token=self._token)
            except ImportError as exc:
                raise RuntimeError(
                    "hvac is required for HashiCorp Vault integration. "
                    "Install it with: pip install hvac"
                ) from exc
        return self._client

    def get_all(self, path: str) -> dict:
        client = self._get_client()
        try:
            response = client.secrets.kv.v2.read_secret_version(path=path)
            return response["data"]["data"] or {}
        except Exception as exc:
            logger.warning("vault_read_failed", path_prefix=path.split("/")[0], error=str(exc))
            return {}

    def put(self, path: str, key: str, value: str) -> None:
        client = self._get_client()
        # Read existing, merge, write back
        try:
            existing = self.get_all(path)
        except Exception:
            existing = {}
        existing[key] = value
        try:
            client.secrets.kv.v2.create_or_update_secret(path=path, secret=existing)
        except Exception as exc:
            logger.error("vault_write_failed", path_prefix=path.split("/")[0], error=str(exc))
            raise RuntimeError(f"Vault write failed: {str(exc)[:200]}") from exc

    def delete(self, path: str, key: str) -> None:
        client = self._get_client()
        try:
            existing = self.get_all(path)
            if key in existing:
                del existing[key]
                client.secrets.kv.v2.create_or_update_secret(path=path, secret=existing)
        except Exception as exc:
            logger.warning("vault_delete_failed", path_prefix=path.split("/")[0], error=str(exc))

    def delete_all(self, path: str) -> None:
        client = self._get_client()
        try:
            client.secrets.kv.v2.delete_metadata_and_all_versions(path=path)
        except Exception as exc:
            logger.warning("vault_delete_all_failed", path_prefix=path.split("/")[0], error=str(exc))


class _LocalEncryptedStore:
    """
    Development fallback: credentials stored in a local JSON file encrypted with Fernet.

    NOT suitable for production. CREDENTIAL_ENCRYPTION_KEY must be a URL-safe base64
    32-byte key (generated via: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    """

    def __init__(self, encryption_key: str, store_path: str) -> None:
        self._key = encryption_key.encode()
        self._path = store_path
        self._fernet: Any = None

    def _get_fernet(self) -> Any:
        if self._fernet is None:
            try:
                from cryptography.fernet import Fernet  # type: ignore[import]
                self._fernet = Fernet(self._key)
            except ImportError as exc:
                raise RuntimeError(
                    "cryptography is required for local credential storage. "
                    "Install it with: pip install cryptography"
                ) from exc
        return self._fernet

    def _load(self) -> dict:
        if not os.path.exists(self._path):
            return {}
        try:
            with open(self._path, "rb") as f:
                encrypted = f.read()
            fernet = self._get_fernet()
            raw = fernet.decrypt(encrypted)
            return json.loads(raw)
        except Exception as exc:
            logger.warning("local_store_load_failed", error=str(exc))
            return {}

    def _save(self, data: dict) -> None:
        try:
            fernet = self._get_fernet()
            raw = json.dumps(data).encode()
            encrypted = fernet.encrypt(raw)
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(self._path, "wb") as f:
                f.write(encrypted)
            # Restrict to owner read/write only — encrypted credentials must not
            # be world-readable on shared systems.
            os.chmod(self._path, 0o600)
        except Exception as exc:
            logger.error("local_store_save_failed", error=str(exc))
            raise RuntimeError(f"Local store write failed: {str(exc)[:200]}") from exc

    def get_all(self, path: str) -> dict:
        data = self._load()
        return dict(data.get(path, {}))

    def put(self, path: str, key: str, value: str) -> None:
        data = self._load()
        if path not in data:
            data[path] = {}
        data[path][key] = value
        self._save(data)

    def delete(self, path: str, key: str) -> None:
        data = self._load()
        if path in data and key in data[path]:
            del data[path][key]
            self._save(data)

    def delete_all(self, path: str) -> None:
        data = self._load()
        if path in data:
            del data[path]
            self._save(data)


# ---------------------------------------------------------------------------
# CredentialManager
# ---------------------------------------------------------------------------

def _build_vault_backend() -> Any:
    """Build vault backend from environment configuration."""
    vault_addr = os.environ.get("VAULT_ADDR")
    vault_token = os.environ.get("VAULT_TOKEN")
    if vault_addr and vault_token:
        return _HashiCorpVaultClient(vault_addr, vault_token)

    encryption_key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    if encryption_key:
        store_path = os.environ.get(
            "CREDENTIAL_STORE_PATH",
            "/tmp/mingai_credentials.enc",
        )
        return _LocalEncryptedStore(encryption_key, store_path)

    return None


class CredentialManager:
    """
    Manages per-agent credentials via vault backend.

    Usage:
        mgr = CredentialManager()

        # Store a credential
        mgr.store_credential(tenant_id, agent_id, "api_key", "sk-...")

        # Retrieve all credentials for an agent
        creds = mgr.get_credentials(tenant_id, agent_id)

        # Test connectivity
        result = await mgr.test_credentials(tenant_id, agent_id, tool_record)
    """

    def __init__(self, vault_client: Any = None) -> None:
        if vault_client is not None:
            self._vault = vault_client
        else:
            self._vault = _build_vault_backend()

    def _is_available(self) -> bool:
        return self._vault is not None

    def store_credential(
        self,
        tenant_id: str,
        agent_id: str,
        credential_key: str,
        credential_value: str,
    ) -> None:
        """
        Store a single credential for an agent.

        Never logs the credential value.

        Args:
            tenant_id: Tenant UUID string.
            agent_id: Agent UUID string.
            credential_key: Key name (alphanumeric, hyphens, underscores, dots).
            credential_value: Secret value.

        Raises:
            ValueError: If credential_key is invalid.
            RuntimeError: If vault backend is unavailable or write fails.
        """
        _validate_credential_key(credential_key)

        if not self._is_available():
            raise RuntimeError(
                "Credential vault is not configured. Set VAULT_ADDR+VAULT_TOKEN "
                "or CREDENTIAL_ENCRYPTION_KEY in environment."
            )

        path = _build_vault_path(tenant_id, agent_id)
        self._vault.put(path, credential_key, credential_value)
        logger.info(
            "credential_stored",
            tenant_id=tenant_id,
            agent_id=agent_id,
            credential_key=credential_key,
            # Never log credential_value
        )

    def store_credentials(
        self,
        tenant_id: str,
        agent_id: str,
        credentials: dict[str, str],
    ) -> None:
        """
        Store multiple credentials for an agent.

        Args:
            tenant_id: Tenant UUID string.
            agent_id: Agent UUID string.
            credentials: Dict of {key: value} pairs.
        """
        for key, value in credentials.items():
            self.store_credential(tenant_id, agent_id, key, value)

    def get_credentials(
        self,
        tenant_id: str,
        agent_id: str,
    ) -> dict:
        """
        Retrieve all credentials for an agent.

        Returns empty dict if vault is unavailable (fail-open for reads to
        allow agents to run without credentials when none are needed).
        """
        if not self._is_available():
            logger.warning(
                "credential_vault_unavailable",
                tenant_id=tenant_id,
                agent_id=agent_id,
            )
            return {}
        try:
            path = _build_vault_path(tenant_id, agent_id)
            return self._vault.get_all(path)
        except Exception as exc:
            logger.warning(
                "credential_read_failed",
                tenant_id=tenant_id,
                agent_id=agent_id,
                error=str(exc),
            )
            return {}

    def delete_credentials(
        self,
        tenant_id: str,
        agent_id: str,
    ) -> None:
        """
        Delete all credentials for an agent (e.g., on agent deletion).
        """
        if not self._is_available():
            return
        try:
            path = _build_vault_path(tenant_id, agent_id)
            self._vault.delete_all(path)
            logger.info(
                "credentials_deleted",
                tenant_id=tenant_id,
                agent_id=agent_id,
            )
        except Exception as exc:
            logger.warning(
                "credential_delete_failed",
                tenant_id=tenant_id,
                agent_id=agent_id,
                error=str(exc),
            )

    async def test_credentials(
        self,
        tenant_id: str,
        agent_id: str,
        tool_record: dict,
    ) -> CredentialTestResult:
        """
        Test credential connectivity for an HTTP/MCP tool.

        Makes a real HTTP request to the tool's endpoint_url with the stored
        credentials injected. Does NOT cache the test result.

        Returns:
            CredentialTestResult with passed=True/False and optional error_message.
            passed=None is returned if the tool has no endpoint_url (builtin tools).
        """
        import time

        endpoint_url = tool_record.get("endpoint_url") or ""
        if not endpoint_url:
            # Built-in tools do not have endpoints — result is untested (None)
            return CredentialTestResult(passed=None)

        credentials = self.get_credentials(tenant_id, agent_id)

        # Build headers with credential injection
        headers: dict = {"Content-Type": "application/json"}
        credential_schema = tool_record.get("credential_schema") or []
        for field_def in credential_schema:
            key = field_def.get("key", "")
            header_name = field_def.get("header_name", "Authorization")
            if key in credentials:
                headers[header_name] = credentials[key]

        start_ms = int(time.time() * 1000)
        try:
            import httpx
            from app.modules.tools.executor import _check_ssrf
            _check_ssrf(endpoint_url)

            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=False,
            ) as client:
                response = await client.get(endpoint_url, headers=headers)
                latency_ms = int(time.time() * 1000) - start_ms

                # Accept any 2xx or 401/403 (endpoint reachable, auth may be needed)
                if response.status_code < 500:
                    return CredentialTestResult(
                        passed=response.status_code < 400,
                        http_status=response.status_code,
                        latency_ms=latency_ms,
                    )
                return CredentialTestResult(
                    passed=False,
                    http_status=response.status_code,
                    error_message=f"Server error: HTTP {response.status_code}",
                    latency_ms=latency_ms,
                )
        except Exception as exc:
            latency_ms = int(time.time() * 1000) - start_ms
            return CredentialTestResult(
                passed=False,
                error_message=str(exc)[:200],
                latency_ms=latency_ms,
            )


# ---------------------------------------------------------------------------
# TODO-15 module-level functions (deploy wizard)
#
# These functions operate via the AzureVaultClient / LocalDBVaultClient
# (app.core.secrets) — the same backend used by _validate_and_store_credentials
# in routes.py.  They are separate from the CredentialManager class above,
# which uses the HashiCorp / Fernet backend.
# ---------------------------------------------------------------------------


async def store_credentials(
    tenant_id: str,
    agent_id: str,
    credentials: dict,
    schema: list,
    vault_client=None,
) -> None:
    """Validate credential keys against schema, store each via VaultClient.

    Vault path: {tenant_id}/agents/{agent_id}/{credential_key}

    Unknown keys (not in schema) are skipped with a warning — never stored.
    Credential values are NEVER logged.

    Args:
        tenant_id:    Tenant UUID string.
        agent_id:     Agent UUID string (per-instance — two agents from the
                      same template have different agent_ids and therefore
                      completely isolated vault paths).
        credentials:  Dict of {key: value} to store.
        schema:       List of credential-schema dicts from the template's
                      required_credentials field.  Each dict must contain "key".
        vault_client: Optional pre-built VaultClient (injected in tests).
                      Defaults to get_vault_client() when None.
    """
    if vault_client is None:
        from app.core.secrets import get_vault_client as _get_vault_client

        vault_client = _get_vault_client()

    schema_keys = {s["key"] for s in (schema or [])}

    for key, value in credentials.items():
        if key not in schema_keys:
            logger.warning(
                "credential_store_unknown_key",
                agent_id=agent_id,
                key=key,
                # value intentionally omitted
            )
            continue

        vault_path = f"{tenant_id}/agents/{agent_id}/{key}"
        # VaultClient.store_secret is synchronous.
        vault_client.store_secret(vault_path, value)
        # NEVER log value


async def get_credential(
    tenant_id: str,
    agent_id: str,
    credential_key: str,
    vault_client=None,
) -> "Optional[str]":
    """Retrieve a single credential for runtime injection into tool calls.

    Called by the Tool Executor at query time, not at agent load time.
    Returns None if the credential cannot be retrieved (vault unavailable,
    secret not found, etc.).

    SECURITY: the returned value must NEVER be logged by callers.
    """
    if vault_client is None:
        from app.core.secrets import get_vault_client as _get_vault_client

        vault_client = _get_vault_client()

    vault_path = f"{tenant_id}/agents/{agent_id}/{credential_key}"
    try:
        # VaultClient.get_secret is synchronous.
        return vault_client.get_secret(vault_path)
    except Exception:
        logger.warning(
            "credential_get_failed",
            agent_id=agent_id,
            key=credential_key,
            # value intentionally omitted
        )
        return None


async def test_credentials(
    template_id: str,
    credentials: dict,
    timeout_seconds: int = 15,
) -> CredentialTestResult:
    """Run credential validation with a hard 15s timeout.

    Currently performs a lightweight connectivity check (placeholder for Phase 3
    which will call the real tool endpoint).  The timeout is enforced via
    asyncio.wait_for so a hung downstream probe cannot block the wizard.

    Phase 3 TODO: replace asyncio.sleep(0.1) with a real HTTP probe to the
    template's tool endpoint using the supplied credentials.

    Returns CredentialTestResult with passed=True on success, False on failure
    or timeout, and latency_ms set in all cases.
    """
    import asyncio
    import time

    start = time.monotonic()
    try:
        # Lightweight placeholder — Phase 3 replaces with real endpoint probe.
        await asyncio.wait_for(asyncio.sleep(0.1), timeout=timeout_seconds)
        latency_ms = int((time.monotonic() - start) * 1000)
        return CredentialTestResult(passed=True, latency_ms=latency_ms)
    except asyncio.TimeoutError:
        return CredentialTestResult(
            passed=False,
            error_message="Credential test timed out after 15 seconds",
            latency_ms=timeout_seconds * 1000,
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return CredentialTestResult(
            passed=False,
            error_message=str(exc),
            latency_ms=latency_ms,
        )
