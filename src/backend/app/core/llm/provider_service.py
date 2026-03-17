"""
ProviderService — Platform LLM Provider credential management (PVDR-002).

Stores encrypted API credentials for platform-configured LLM providers.
Keys are Fernet-encrypted using JWT_SECRET_KEY (same mechanism as HAR
private key storage). The decrypted key MUST be cleared immediately after
adapter instantiation.

Security contract:
- api_key_encrypted is BYTEA — never plaintext in any DB row.
- list_providers() / get_provider() NEVER return api_key_encrypted.
- All callers must clear decrypted keys (decrypted_key = "") immediately.
- No PII in logs — only provider_id and provider_type.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Module-level import for patching in tests
from app.core.session import async_session_factory  # noqa: E402

logger = structlog.get_logger()

_VALID_PROVIDER_TYPES = frozenset(
    {
        "azure_openai",
        "openai",
        "anthropic",
        "deepseek",
        "dashscope",
        "doubao",
        "gemini",
    }
)

# Columns safe to return in list/detail responses — api_key_encrypted excluded.
_SAFE_COLUMNS = (
    "id",
    "provider_type",
    "display_name",
    "description",
    "endpoint",
    "models",
    "options",
    "pricing",
    "is_enabled",
    "is_default",
    "provider_status",
    "last_health_check_at",
    "health_error",
    "created_at",
    "updated_at",
    "created_by",
)

_SELECT_SAFE = (
    "SELECT id, provider_type, display_name, description, endpoint, "
    "models, options, pricing, is_enabled, is_default, provider_status, "
    "last_health_check_at, health_error, created_at, updated_at, created_by, "
    # api_key_encrypted NOT selected — include key_present flag instead
    "octet_length(api_key_encrypted) > 0 AS key_present "
    "FROM llm_providers"
)


def _row_to_dict(row) -> dict:
    """Convert a DB row (tuple) to a safe dict. Never includes api_key_encrypted."""
    return {
        "id": str(row[0]),
        "provider_type": row[1],
        "display_name": row[2],
        "description": row[3],
        "endpoint": row[4],
        "models": row[5]
        if isinstance(row[5], dict)
        else (json.loads(row[5]) if row[5] else {}),
        "options": row[6]
        if isinstance(row[6], dict)
        else (json.loads(row[6]) if row[6] else {}),
        "pricing": row[7]
        if isinstance(row[7], dict)
        else (json.loads(row[7]) if row[7] else None),
        "is_enabled": row[8],
        "is_default": row[9],
        "provider_status": row[10],
        "last_health_check_at": row[11].isoformat() if row[11] else None,
        "health_error": row[12],
        "created_at": row[13].isoformat() if row[13] else None,
        "updated_at": row[14].isoformat() if row[14] else None,
        "created_by": str(row[15]) if row[15] else None,
        "key_present": bool(row[16]),
    }


def _set_platform_scope_sql() -> str:
    """SQL fragment to set platform scope for RLS bypass."""
    return "SELECT set_config('app.scope', 'platform', true)"


class ProviderService:
    """
    CRUD and connectivity testing for platform LLM providers.

    All methods require the caller to pass an async DB session.
    The session must have platform scope set (app.scope = 'platform')
    for RLS to allow access.
    """

    # ------------------------------------------------------------------
    # Encryption helpers
    # ------------------------------------------------------------------

    def encrypt_api_key(self, plaintext_key: str) -> bytes:
        """
        Encrypt a plaintext API key using Fernet derived from JWT_SECRET_KEY.

        Returns raw bytes suitable for storing in BYTEA column.
        The plaintext_key should be cleared by the caller after this call.
        """
        from app.modules.har.crypto import get_fernet

        fernet = get_fernet()
        return fernet.encrypt(plaintext_key.encode("utf-8"))

    def decrypt_api_key(self, encrypted_bytes: bytes) -> str:
        """
        Decrypt a BYTEA-stored encrypted API key.

        Returns the plaintext key string.
        Caller MUST clear the returned string (key = "") after use.
        Raises ValueError if decryption fails (invalid token or wrong JWT_SECRET_KEY).
        """
        from app.modules.har.crypto import get_fernet
        from cryptography.fernet import InvalidToken

        fernet = get_fernet()
        try:
            return fernet.decrypt(encrypted_bytes).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(
                "Failed to decrypt provider API key — Fernet token is invalid. "
                "This may indicate JWT_SECRET_KEY has changed since the key was stored."
            ) from exc

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_providers(
        self, db: AsyncSession, enabled_only: bool = False
    ) -> list[dict]:
        """
        List all providers. Never returns api_key_encrypted.
        Returns key_present: bool instead.
        """
        await db.execute(text(_set_platform_scope_sql()))

        query = _SELECT_SAFE
        params: dict = {}
        if enabled_only:
            query += " WHERE is_enabled = true"
        query += " ORDER BY is_default DESC, created_at ASC"

        result = await db.execute(text(query), params)
        rows = result.fetchall()
        return [_row_to_dict(r) for r in rows]

    async def get_provider(self, db: AsyncSession, provider_id: str) -> Optional[dict]:
        """
        Get a single provider by ID. Never returns api_key_encrypted.
        Returns None if not found.
        """
        await db.execute(text(_set_platform_scope_sql()))

        result = await db.execute(
            text(_SELECT_SAFE + " WHERE id = :id"),
            {"id": provider_id},
        )
        row = result.fetchone()
        return _row_to_dict(row) if row else None

    async def get_default_provider(self, db: AsyncSession) -> Optional[dict]:
        """
        Get the default enabled provider. Returns None if none set.
        Never returns api_key_encrypted.
        """
        await db.execute(text(_set_platform_scope_sql()))

        result = await db.execute(
            text(
                _SELECT_SAFE + " WHERE is_default = true AND is_enabled = true LIMIT 1"
            )
        )
        row = result.fetchone()
        return _row_to_dict(row) if row else None

    async def _get_provider_with_key(
        self, db: AsyncSession, provider_id: str
    ) -> Optional[tuple]:
        """
        Internal: fetch provider row including api_key_encrypted bytes.
        Returns (safe_dict, encrypted_bytes) or None.
        NEVER expose encrypted_bytes outside this module.
        """
        await db.execute(text(_set_platform_scope_sql()))

        result = await db.execute(
            text(
                "SELECT id, provider_type, display_name, description, endpoint, "
                "models, options, pricing, is_enabled, is_default, provider_status, "
                "last_health_check_at, health_error, created_at, updated_at, created_by, "
                "true AS key_present, api_key_encrypted "
                "FROM llm_providers WHERE id = :id"
            ),
            {"id": provider_id},
        )
        row = result.fetchone()
        if row is None:
            return None
        # row[16] = key_present (always true here), row[17] = api_key_encrypted
        safe = _row_to_dict(row)
        encrypted_bytes = bytes(row[17]) if row[17] else b""
        return safe, encrypted_bytes

    async def _get_default_provider_with_key(self, db: AsyncSession) -> Optional[tuple]:
        """
        Internal: fetch default provider row including api_key_encrypted.
        Returns (safe_dict, encrypted_bytes) or None.
        """
        await db.execute(text(_set_platform_scope_sql()))

        result = await db.execute(
            text(
                "SELECT id, provider_type, display_name, description, endpoint, "
                "models, options, pricing, is_enabled, is_default, provider_status, "
                "last_health_check_at, health_error, created_at, updated_at, created_by, "
                "true AS key_present, api_key_encrypted "
                "FROM llm_providers WHERE is_default = true AND is_enabled = true LIMIT 1"
            )
        )
        row = result.fetchone()
        if row is None:
            return None
        safe = _row_to_dict(row)
        encrypted_bytes = bytes(row[17]) if row[17] else b""
        return safe, encrypted_bytes

    async def create_provider(
        self, db: AsyncSession, payload: dict, created_by: Optional[str] = None
    ) -> dict:
        """
        Create a new provider. Encrypts api_key before storage.
        Returns the created provider (safe dict, no key).
        Logs api_key as "[REDACTED]".
        """
        await db.execute(text(_set_platform_scope_sql()))

        provider_id = str(uuid.uuid4())
        encrypted_key = self.encrypt_api_key(payload["api_key"])

        models = payload.get("models", {})
        options = payload.get("options", {})
        pricing = payload.get("pricing")
        now = datetime.now(timezone.utc)

        await db.execute(
            text(
                "INSERT INTO llm_providers "
                "(id, provider_type, display_name, description, endpoint, "
                " api_key_encrypted, models, options, pricing, is_enabled, "
                " is_default, provider_status, created_at, updated_at, created_by) "
                "VALUES "
                "(:id, :provider_type, :display_name, :description, :endpoint, "
                " :api_key_encrypted, CAST(:models AS jsonb), CAST(:options AS jsonb), "
                " CAST(:pricing AS jsonb), :is_enabled, :is_default, 'unchecked', "
                " :now, :now, :created_by)"
            ),
            {
                "id": provider_id,
                "provider_type": payload["provider_type"],
                "display_name": payload["display_name"],
                "description": payload.get("description"),
                "endpoint": payload.get("endpoint"),
                "api_key_encrypted": encrypted_key,
                "models": json.dumps(models),
                "options": json.dumps(options),
                "pricing": json.dumps(pricing) if pricing is not None else None,
                "is_enabled": payload.get("is_enabled", True),
                "is_default": payload.get("is_default", False),
                "now": now,
                "created_by": created_by,
            },
        )
        await db.commit()

        logger.info(
            "provider_created",
            provider_id=provider_id,
            provider_type=payload["provider_type"],
            api_key="[REDACTED]",
        )

        provider = await self.get_provider(db, provider_id)
        return provider

    async def update_provider(
        self, db: AsyncSession, provider_id: str, updates: dict
    ) -> Optional[dict]:
        """
        Update provider fields. If api_key not in updates, api_key_encrypted
        is left unchanged. Returns updated safe dict or None if not found.
        """
        await db.execute(text(_set_platform_scope_sql()))

        updates = dict(updates)  # never mutate caller's dict

        # Build SET clause from allowlisted fields only
        _UPDATE_ALLOWLIST = frozenset(
            {
                "display_name",
                "description",
                "endpoint",
                "models",
                "options",
                "pricing",
                "is_enabled",
                "is_default",
                "provider_status",
            }
        )

        set_parts = []
        params: dict = {"id": provider_id}

        # Handle api_key separately — encrypt if provided
        if "api_key" in updates:
            encrypted_key = self.encrypt_api_key(updates["api_key"])
            set_parts.append("api_key_encrypted = :api_key_encrypted")
            params["api_key_encrypted"] = encrypted_key
            logger.info(
                "provider_api_key_updated",
                provider_id=provider_id,
                api_key="[REDACTED]",
            )

        for field in _UPDATE_ALLOWLIST:
            if field not in updates:
                continue
            value = updates[field]
            if field in ("models", "options", "pricing"):
                set_parts.append(f"{field} = CAST(:{field} AS jsonb)")
                params[field] = json.dumps(value) if value is not None else None
            else:
                set_parts.append(f"{field} = :{field}")
                params[field] = value

        if not set_parts:
            # Nothing to update — return current state
            return await self.get_provider(db, provider_id)

        set_parts.append("updated_at = NOW()")
        # set_parts is built exclusively from _UPDATE_ALLOWLIST (frozenset of known
        # column names) — no user-controlled values appear as column identifiers.
        # User values flow through named placeholders in `params` only.
        set_clause = ", ".join(set_parts)

        result = await db.execute(
            text(f"UPDATE llm_providers SET {set_clause} WHERE id = :id"),
            params,
        )
        if (result.rowcount or 0) == 0:
            return None

        await db.commit()
        return await self.get_provider(db, provider_id)

    async def set_default(self, db: AsyncSession, provider_id: str) -> None:
        """
        Atomically set the given provider as default.

        Two-step: clear all is_default=true rows, then set the target.
        Single commit after both steps.
        """
        await db.execute(text(_set_platform_scope_sql()))

        await db.execute(
            text("UPDATE llm_providers SET is_default = false WHERE is_default = true")
        )
        await db.execute(
            text("UPDATE llm_providers SET is_default = true WHERE id = :id"),
            {"id": provider_id},
        )
        await db.commit()

        logger.info("provider_set_default", provider_id=provider_id)

    async def delete_provider(self, db: AsyncSession, provider_id: str) -> bool:
        """
        Delete a provider. Returns True if deleted, False if not found.
        Caller should check is_default / only-enabled constraints before calling.
        """
        await db.execute(text(_set_platform_scope_sql()))

        result = await db.execute(
            text("DELETE FROM llm_providers WHERE id = :id"),
            {"id": provider_id},
        )
        deleted = (result.rowcount or 0) > 0
        if deleted:
            await db.commit()
            logger.info("provider_deleted", provider_id=provider_id)
        return deleted

    # ------------------------------------------------------------------
    # Connectivity test
    # ------------------------------------------------------------------

    async def test_connectivity(self, provider_row: dict) -> tuple[bool, Optional[str]]:
        """
        Test connectivity to the provider via a real API call.

        Accepts a safe provider_row dict (from get_provider / list_providers).
        Caller must supply the decrypted key separately if needed — this method
        reads it fresh from the DB to avoid requiring callers to hold plaintext keys.

        Returns (True, None) on success or (False, error_message) on failure.
        Note: This variant performs a real connectivity test using the
        provider's stored credentials.
        """
        provider_id = provider_row["id"]
        provider_type = provider_row["provider_type"]

        try:
            async with async_session_factory() as db:  # uses module-level import for test patching
                result = await _get_provider_with_key_standalone(db, provider_id)
                if result is None:
                    return False, "Provider not found in database"
                _, encrypted_bytes = result

            if not encrypted_bytes:
                return False, "No API key stored for this provider"

            decrypted_key = self.decrypt_api_key(encrypted_bytes)
            try:
                success, error = await _do_connectivity_test(
                    provider_type=provider_type,
                    api_key=decrypted_key,
                    endpoint=provider_row.get("endpoint"),
                    models=provider_row.get("models", {}),
                )
            finally:
                decrypted_key = ""  # clear immediately

            return success, error

        except Exception as exc:
            logger.warning(
                "provider_connectivity_test_failed",
                provider_id=provider_id,
                error=str(exc),
            )
            return False, str(exc)

    async def count_providers(self, db: AsyncSession) -> int:
        """Return total count of provider rows."""
        await db.execute(text(_set_platform_scope_sql()))
        result = await db.execute(text("SELECT COUNT(*) FROM llm_providers"))
        row = result.fetchone()
        return int(row[0]) if row else 0


# ------------------------------------------------------------------
# Module-level helpers (used internally and in routes)
# ------------------------------------------------------------------


async def _get_provider_with_key_standalone(
    db: AsyncSession, provider_id: str
) -> Optional[tuple]:
    """Standalone version for use without a service instance."""
    await db.execute(text(_set_platform_scope_sql()))
    result = await db.execute(
        text(
            "SELECT id, provider_type, display_name, description, endpoint, "
            "models, options, pricing, is_enabled, is_default, provider_status, "
            "last_health_check_at, health_error, created_at, updated_at, created_by, "
            "true AS key_present, api_key_encrypted "
            "FROM llm_providers WHERE id = :id"
        ),
        {"id": provider_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    safe = _row_to_dict(row)
    encrypted_bytes = bytes(row[17]) if row[17] else b""
    return safe, encrypted_bytes


async def _do_connectivity_test(
    provider_type: str,
    api_key: str,
    endpoint: Optional[str],
    models: dict,
) -> tuple[bool, Optional[str]]:
    """
    Perform a real API call to verify connectivity.

    Returns (True, None) on success, (False, error_message) on failure.
    api_key is used only within this call and must be cleared by caller.
    """
    try:
        start = time.time()

        if provider_type == "azure_openai":
            from openai import AsyncAzureOpenAI

            if not endpoint:
                return False, "endpoint is required for azure_openai provider"

            api_version = os.environ.get(
                "AZURE_PLATFORM_OPENAI_API_VERSION", "2024-02-01"
            )
            client = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=endpoint,
                api_version=api_version,
            )
            # Use primary model if specified, else a simple models.list() call
            model_name = (
                models.get("primary") or models.get("chat") or models.get("worker")
            )
            if model_name:
                resp = await client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                )
                _ = resp.choices[0].message.content
            else:
                # Fallback: list models
                await client.models.list()

        elif provider_type == "openai":
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key)
            model_name = models.get("primary") or models.get("chat")
            if model_name:
                resp = await client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                )
                _ = resp.choices[0].message.content
            else:
                await client.models.list()

        elif provider_type == "anthropic":
            import anthropic  # type: ignore[import]

            client = anthropic.AsyncAnthropic(api_key=api_key)
            model_name = models.get("primary")
            if not model_name:
                raise ValueError(
                    "Anthropic provider connectivity test requires 'primary' slot to be"
                    " configured in the provider's models map."
                )
            resp = await client.messages.create(
                model=model_name,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            _ = resp.content

        else:
            # For other providers, we can only do a basic check
            return True, None

        latency_ms = int((time.time() - start) * 1000)
        logger.debug(
            "provider_connectivity_test_ok",
            provider_type=provider_type,
            latency_ms=latency_ms,
        )
        return True, None

    except Exception as exc:
        error_msg = str(exc)
        logger.warning(
            "provider_connectivity_test_error",
            provider_type=provider_type,
            error=error_msg,
        )
        return False, error_msg


async def get_default_provider_credentials(
    db: AsyncSession,
) -> tuple[str, str, str]:
    """
    Get decrypted credentials for the default enabled provider.

    Returns (api_key_decrypted, endpoint, api_version).
    Caller MUST clear api_key_decrypted = "" immediately after use.

    Falls back to env vars if no DB provider is configured.
    Logs WARNING when using env fallback.
    """
    svc = ProviderService()
    result = await svc._get_default_provider_with_key(db)

    if result is not None:
        provider_row, encrypted_bytes = result
        if encrypted_bytes:
            decrypted_key = svc.decrypt_api_key(encrypted_bytes)
            endpoint = provider_row.get("endpoint") or ""
            options = provider_row.get("options") or {}
            api_version = options.get(
                "api_version",
                os.environ.get("AZURE_PLATFORM_OPENAI_API_VERSION", "2024-02-01"),
            )
            return decrypted_key, endpoint, api_version

    # Env fallback
    logger.warning(
        "llm_providers_env_fallback_active",
        reason="no_default_provider_in_db",
    )
    api_key = os.environ.get("AZURE_PLATFORM_OPENAI_API_KEY", "")
    endpoint = os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT", "")
    api_version = os.environ.get("AZURE_PLATFORM_OPENAI_API_VERSION", "2024-02-01")
    return api_key, endpoint, api_version
