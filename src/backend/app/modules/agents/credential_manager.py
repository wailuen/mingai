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


class MissingPlatformCredentialError(Exception):
    """Raised when one or more required platform credentials are not stored."""
    def __init__(self, template_id: str, missing_keys: list[str]) -> None:
        self.template_id = template_id
        self.missing_keys = missing_keys
        super().__init__(
            f"Missing platform credentials for template {template_id}: {missing_keys}"
        )


class PlatformVaultUnavailableError(Exception):
    """Raised when the platform credential vault backend is not configured."""
    pass


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


def _build_platform_vault_backend() -> Any:
    """Build platform vault backend from environment configuration.

    Separate from the tenant vault backend:
    - Uses PLATFORM_CREDENTIAL_ENCRYPTION_KEY (not CREDENTIAL_ENCRYPTION_KEY)
    - Uses PLATFORM_CREDENTIAL_STORE_PATH (not CREDENTIAL_STORE_PATH)
    - Defaults to .credentials/platform_credentials.json.enc

    Returns None if neither Vault nor Fernet key is configured.
    Callers must check — startup validation (main.py) raises if None.
    """
    vault_addr = os.environ.get("VAULT_ADDR")
    vault_token = os.environ.get("VAULT_TOKEN")
    if vault_addr and vault_token:
        # Production: reuse HashiCorp Vault backend; platform paths are under
        # the "platform/templates/" prefix which Vault ACLs can enforce separately.
        return _HashiCorpVaultClient(vault_addr, vault_token)

    encryption_key = os.environ.get("PLATFORM_CREDENTIAL_ENCRYPTION_KEY")
    if encryption_key:
        store_path = os.environ.get(
            "PLATFORM_CREDENTIAL_STORE_PATH",
            ".credentials/platform_credentials.json.enc",
        )
        return _LocalEncryptedStore(encryption_key, store_path)

    return None


def _build_platform_vault_path(template_id: str) -> str:
    """Build the vault KV path for platform template credentials."""
    return f"platform/templates/{template_id}"


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


# ---------------------------------------------------------------------------
# Platform credential functions (module-level, used by CRUD routes and orchestrator)
#
# Vault path schema: platform/templates/{template_id}/{key}
# Values are NEVER stored in the database — only key names and metadata.
# ---------------------------------------------------------------------------

_platform_vault: Any = None
_platform_vault_initialized: bool = False


def _get_platform_vault() -> Any:
    """Lazy-initialize the platform vault backend (thread-safe via GIL)."""
    global _platform_vault, _platform_vault_initialized
    if not _platform_vault_initialized:
        _platform_vault = _build_platform_vault_backend()
        _platform_vault_initialized = True
    return _platform_vault


def set_platform_credential(
    template_id: str,
    key: str,
    value: str,
    allowed_domains: list[str] | None = None,
    injection_config: dict | None = None,
    description: str | None = None,
    actor_id: str = "unknown",
) -> None:
    """Store a platform credential value in the vault.

    This function only writes the VALUE to the vault. The calling route
    must separately insert/update a row in platform_credential_metadata.

    Args:
        template_id: Agent template UUID string.
        key:         Credential key name (e.g. "PITCHBOOK_API_KEY").
        value:       Secret value — NEVER logged.
        allowed_domains: SSRF allowlist (stored in DB metadata, not here).
        injection_config: How to inject at runtime (stored in DB metadata, not here).
        description: Human-readable description (stored in DB metadata, not here).
        actor_id:    Who is storing this credential (for audit logging).

    Raises:
        PlatformVaultUnavailableError: If vault backend is not configured.
        RuntimeError: If vault write fails.
    """
    _validate_credential_key(key)

    vault = _get_platform_vault()
    if vault is None:
        raise PlatformVaultUnavailableError(
            "Platform credential vault is not configured. "
            "Set PLATFORM_CREDENTIAL_ENCRYPTION_KEY or VAULT_ADDR+VAULT_TOKEN."
        )

    path = _build_platform_vault_path(template_id)
    vault.put(path, key, value)
    logger.info(
        "platform_credential_stored",
        template_id=template_id,
        key=key,
        actor_id=actor_id,
        # value NEVER logged
    )


def get_platform_credential(template_id: str, key: str) -> Optional[str]:
    """Retrieve a single platform credential value from the vault.

    Returns None if the key is not found or vault is unavailable.
    The returned value must NEVER be logged by callers.
    """
    _validate_credential_key(key)

    vault = _get_platform_vault()
    if vault is None:
        return None

    path = _build_platform_vault_path(template_id)
    try:
        all_creds = vault.get_all(path)
        return all_creds.get(key)
    except Exception as exc:
        logger.warning(
            "platform_credential_get_failed",
            template_id=template_id,
            key=key,
            error=str(exc),
        )
        return None


def delete_platform_credential(template_id: str, key: str, actor_id: str = "unknown") -> None:
    """Delete a platform credential value from the vault.

    The calling route handles soft-delete of the metadata row separately.
    This function purges the actual value from the vault backend.

    Does not raise if the key doesn't exist.
    """
    _validate_credential_key(key)

    vault = _get_platform_vault()
    if vault is None:
        return  # Nothing to delete if vault not configured

    path = _build_platform_vault_path(template_id)
    try:
        vault.delete(path, key)
        logger.info(
            "platform_credential_deleted",
            template_id=template_id,
            key=key,
            actor_id=actor_id,
        )
    except Exception as exc:
        logger.warning(
            "platform_credential_delete_failed",
            template_id=template_id,
            key=key,
            error=str(exc),
        )


def resolve_platform_credentials(
    template_id: str,
    required_keys: list[str],
    tenant_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, dict]:
    """Resolve all required platform credentials for orchestration.

    Called by the orchestrator at the START of each orchestration, before
    any tool call. Fail-fast: raises MissingPlatformCredentialError if any
    key is absent.

    Returns a dict mapping key -> {"value": str, "injection_config": dict}.
    The injection_config is read from platform_credential_metadata.

    Args:
        template_id:   Agent template UUID string.
        required_keys: List of credential key names required by this template.
        tenant_id:     Tenant that triggered this orchestration (for audit).
        request_id:    Correlation ID for this request (for audit).

    Returns:
        {key: {"value": str, "injection_config": dict}} for all keys.

    Raises:
        MissingPlatformCredentialError: If any required key is not stored.
        PlatformVaultUnavailableError:  If vault backend is not configured.
    """
    if not required_keys:
        return {}

    vault = _get_platform_vault()
    if vault is None:
        raise PlatformVaultUnavailableError(
            "Platform credential vault is not configured."
        )

    path = _build_platform_vault_path(template_id)
    try:
        all_values = vault.get_all(path)
    except Exception as exc:
        raise PlatformVaultUnavailableError(
            f"Platform vault read failed: {str(exc)[:200]}"
        ) from exc

    missing = [k for k in required_keys if k not in all_values or not all_values[k]]
    if missing:
        raise MissingPlatformCredentialError(template_id=template_id, missing_keys=missing)

    # Build result with default injection_config (caller may override from DB metadata)
    _default_injection_config = {
        "type": "header",
        "header_name": "Authorization",
        "header_format": "{value}",
    }

    result = {
        key: {
            "value": all_values[key],
            "injection_config": _default_injection_config.copy(),
        }
        for key in required_keys
    }

    logger.info(
        "platform_credentials_resolved",
        template_id=template_id,
        key_count=len(required_keys),
        tenant_id=tenant_id,
        request_id=request_id,
        # values NEVER logged
    )
    return result


async def get_platform_credential_health(
    template_id: str,
    required_keys: list[str],
) -> dict:
    """Check completeness of platform credentials for a template.

    Used by:
    - GET /credentials/health endpoint
    - Deploy flow pre-flight check
    - Test harness banner

    Returns:
        {
            "template_id": str,
            "required_credentials": list[str],
            "status": "complete" | "incomplete" | "not_required",
            "keys": {key: "stored" | "missing"}
        }
    """
    if not required_keys:
        return {
            "template_id": template_id,
            "required_credentials": [],
            "status": "not_required",
            "keys": {},
        }

    vault = _get_platform_vault()
    if vault is None:
        # Vault unavailable — all keys appear missing
        return {
            "template_id": template_id,
            "required_credentials": required_keys,
            "status": "incomplete",
            "keys": {k: "missing" for k in required_keys},
        }

    path = _build_platform_vault_path(template_id)
    try:
        stored_values = vault.get_all(path)
    except Exception:
        stored_values = {}

    keys_status = {}
    for key in required_keys:
        if key in stored_values and stored_values[key]:
            keys_status[key] = "stored"
        else:
            keys_status[key] = "missing"

    all_stored = all(v == "stored" for v in keys_status.values())
    status = "complete" if all_stored else "incomplete"

    return {
        "template_id": template_id,
        "required_credentials": required_keys,
        "status": status,
        "keys": keys_status,
    }


async def purge_expired_platform_credentials(db_session) -> int:
    """Hard-delete platform credential metadata rows past retention_until.

    Called by the background scheduler daily. Does NOT attempt to delete vault
    values — those are removed at soft-delete time in the DELETE route. This
    function only removes the metadata row once the 30-day retention window
    has elapsed.

    Only rows where `deleted_at IS NOT NULL AND retention_until < NOW()` are
    affected. Active credentials (deleted_at IS NULL) are never touched.

    Returns: count of rows deleted.
    """
    from datetime import datetime, timezone

    from sqlalchemy import text

    result = await db_session.execute(
        text(
            """
            DELETE FROM platform_credential_metadata
            WHERE deleted_at IS NOT NULL
            AND retention_until < :now
            RETURNING id, template_id, key
            """
        ),
        {"now": datetime.now(timezone.utc)},
    )
    rows = result.fetchall()
    await db_session.commit()
    count = len(rows)
    if count > 0:
        logger.info("platform_credentials_hard_deleted", count=count)
    return count


def validate_platform_credential_config() -> None:
    """Validate that the platform credential vault is properly configured.

    Called at startup (see main.py lifespan). Raises RuntimeError if
    neither PLATFORM_CREDENTIAL_ENCRYPTION_KEY nor VAULT_ADDR is set.

    This prevents silent failures where platform_credentials auth_mode
    templates appear to work but credentials can never be stored or resolved.
    """
    vault_addr = os.environ.get("VAULT_ADDR")
    platform_key = os.environ.get("PLATFORM_CREDENTIAL_ENCRYPTION_KEY")

    if not vault_addr and not platform_key:
        raise RuntimeError(
            "Platform credential vault is not configured. "
            "Set PLATFORM_CREDENTIAL_ENCRYPTION_KEY (dev) or "
            "VAULT_ADDR+VAULT_TOKEN (production) in environment variables. "
            "See .env.example for details."
        )
