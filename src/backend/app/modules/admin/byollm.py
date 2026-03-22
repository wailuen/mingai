"""
BYOLLM (Bring Your Own LLM) API — v2 (TODO-33 B7).

Enterprise-only. Allows tenants to manage their own LLM library entries and profiles.
API keys are encrypted at rest using Fernet (same pattern as HAR keypairs).

Endpoints (require tenant_admin + enterprise plan):

Library entry management:
    GET    /admin/byollm/library-entries               — list tenant's library entries
    POST   /admin/byollm/library-entries               — create library entry (SSRF validated)
    PATCH  /admin/byollm/library-entries/{id}          — update entry metadata
    PATCH  /admin/byollm/library-entries/{id}/rotate-key — rotate API key
    POST   /admin/byollm/library-entries/{id}/test     — test connectivity
    DELETE /admin/byollm/library-entries/{id}          — soft delete (status=disabled)

Profile management:
    GET    /admin/byollm/profiles                          — list tenant's BYOLLM profiles
    POST   /admin/byollm/profiles                          — create BYOLLM profile
    PATCH  /admin/byollm/profiles/{id}/slots/{slot}        — assign slot
    POST   /admin/byollm/profiles/{id}/activate            — activate (requires slots+tests)
    DELETE /admin/byollm/profiles/{id}                     — soft delete (status=deprecated)

Security invariants:
    - api_key_encrypted NEVER appears in any response body
    - api_key_last4 is the only key-related field returned
    - Ownership checks before every mutation
    - SSRF validation on every endpoint URL save and test
    - Cross-tenant isolation: returns 404 not 403 on access to another tenant's entry
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.middleware.plan_tier import require_plan_or_above
from app.core.session import get_async_session
from app.modules.admin.llm_config import _invalidate_config_cache

logger = structlog.get_logger()

router = APIRouter(prefix="/admin/byollm", tags=["admin-byollm"])

# Enterprise-only dependency
_require_enterprise = require_plan_or_above("enterprise")

_VALID_PROVIDERS = frozenset({
    "openai_direct", "azure_openai", "aws_bedrock", "google_vertex", "anthropic_direct"
})

_VALID_SLOTS = frozenset({"chat", "intent", "vision", "agent"})

# Maps slot name to llm_profiles column name — used for safe f-string column interpolation
_SLOT_COL: dict[str, str] = {
    "chat": "chat_library_id",
    "intent": "intent_library_id",
    "vision": "vision_library_id",
    "agent": "agent_library_id",
}

_TEST_PROMPT = "Respond with 'ok' and nothing else."
_TEST_TIMEOUT_SECONDS = 10


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LibraryEntryCapabilities(BaseModel):
    eligible_slots: list[str] = Field(default_factory=list)
    supports_vision: bool = False
    supports_function_calling: bool = False
    context_window: Optional[int] = None

    model_config = {"protected_namespaces": ()}


class CreateLibraryEntryRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    provider: str = Field(..., description=f"One of: {sorted(_VALID_PROVIDERS)}")
    endpoint_url: Optional[str] = Field(None, min_length=1, max_length=2048)
    api_version: Optional[str] = Field(None, max_length=50)
    model_name: str = Field(..., min_length=1, max_length=255)
    api_key: str = Field(..., min_length=8, description="Encrypted at rest — never stored plain")
    capabilities: LibraryEntryCapabilities = Field(default_factory=LibraryEntryCapabilities)
    display_name: Optional[str] = Field(None, max_length=255)
    slot: Optional[str] = Field(None, description="Slot to assign: chat, intent, vision, or agent")

    model_config = {"protected_namespaces": ()}


class UpdateLibraryEntryRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    endpoint_url: Optional[str] = Field(None, min_length=1, max_length=2048)
    api_version: Optional[str] = Field(None, max_length=50)
    model_name: Optional[str] = Field(None, min_length=1, max_length=255)
    capabilities: Optional[LibraryEntryCapabilities] = None
    display_name: Optional[str] = Field(None, max_length=255)

    model_config = {"protected_namespaces": ()}


class RotateKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=8, description="New API key — encrypted at rest")

    model_config = {"protected_namespaces": ()}


class LibraryEntryResponse(BaseModel):
    id: str
    name: str
    provider: str
    endpoint_url: Optional[str] = None
    api_version: Optional[str] = None
    model_name: str
    api_key_last4: Optional[str] = None
    status: str
    test_passed_at: Optional[str] = None
    capabilities: dict = Field(default_factory=dict)
    display_name: Optional[str] = None
    owner_tenant_id: str
    slot: Optional[str] = None  # which profile slot this entry is assigned to
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"protected_namespaces": ()}


class TestEntryResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    latency_ms: Optional[int] = None

    model_config = {"protected_namespaces": ()}


# Frontend uses short provider names; map to backend internal names
_FRONTEND_PROVIDER_MAP: dict[str, str] = {
    "azure_openai": "azure_openai",
    "openai": "openai_direct",
    "anthropic": "anthropic_direct",
    "google": "google_vertex",
    "aws": "aws_bedrock",
    "bedrock": "aws_bedrock",
}


class TestConnectionRequest(BaseModel):
    """Inline connection test — API key supplied directly (no DB entry required)."""
    provider: str = Field(..., description="One of: azure_openai, openai, anthropic, google")
    endpoint_url: Optional[str] = Field(None, max_length=2048)
    api_key: str = Field(..., min_length=8)
    api_version: Optional[str] = Field(None, max_length=50)
    model_name: str = Field(..., min_length=1, max_length=255)

    model_config = {"protected_namespaces": ()}


class TestConnectionResult(BaseModel):
    passed: bool
    latency_ms: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    model_config = {"protected_namespaces": ()}


class CreateProfileRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)

    model_config = {"protected_namespaces": ()}


class AssignSlotRequest(BaseModel):
    library_id: str = Field(..., description="UUID of a tenant-owned library entry")

    model_config = {"protected_namespaces": ()}


class BYOLLMProfileResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: str
    chat_library_id: Optional[str] = None
    intent_library_id: Optional[str] = None
    vision_library_id: Optional[str] = None
    agent_library_id: Optional[str] = None
    owner_tenant_id: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"protected_namespaces": ()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encrypt_api_key(api_key: str) -> tuple[str, str]:
    """Encrypt API key and return (encrypted_token, last4)."""
    from app.modules.har.crypto import get_fernet
    fernet = get_fernet()
    encrypted = fernet.encrypt(api_key.encode("utf-8")).decode("ascii")
    last4 = api_key[-4:] if len(api_key) >= 8 else "****"
    return encrypted, last4


def _row_to_entry_response(row) -> LibraryEntryResponse:
    """Convert DB row to LibraryEntryResponse — api_key_encrypted is NEVER included."""
    (
        entry_id, name, provider, endpoint_url, api_version, model_name,
        api_key_last4, entry_status, test_passed_at, capabilities_raw,
        display_name, owner_tenant_id, created_at, updated_at,
    ) = row

    caps: dict = {}
    if capabilities_raw:
        if isinstance(capabilities_raw, str):
            caps = json.loads(capabilities_raw)
        elif isinstance(capabilities_raw, dict):
            caps = capabilities_raw

    return LibraryEntryResponse(
        id=str(entry_id),
        name=name,
        provider=provider,
        endpoint_url=endpoint_url,
        api_version=api_version,
        model_name=model_name,
        api_key_last4=api_key_last4,
        status=entry_status,
        test_passed_at=test_passed_at.isoformat() if test_passed_at else None,
        capabilities=caps,
        display_name=display_name,
        owner_tenant_id=str(owner_tenant_id),
        created_at=created_at.isoformat() if created_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
    )


_ENTRY_SELECT = (
    "SELECT id, display_name AS name, provider, endpoint_url, api_version, model_name, "
    "api_key_last4, status, last_test_passed_at AS test_passed_at, capabilities, display_name, "
    "owner_tenant_id, created_at, updated_at "
    "FROM llm_library"
)


def _row_to_profile_response(row) -> BYOLLMProfileResponse:
    (
        pid, name, description, prof_status, chat_lib, intent_lib, vision_lib, agent_lib,
        owner_tid, created_at, updated_at,
    ) = row
    return BYOLLMProfileResponse(
        id=str(pid),
        name=name,
        description=description,
        status=prof_status,
        chat_library_id=str(chat_lib) if chat_lib else None,
        intent_library_id=str(intent_lib) if intent_lib else None,
        vision_library_id=str(vision_lib) if vision_lib else None,
        agent_library_id=str(agent_lib) if agent_lib else None,
        owner_tenant_id=str(owner_tid),
        created_at=created_at.isoformat() if created_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
    )


_PROFILE_SELECT = (
    "SELECT id, name, description, status, "
    "chat_library_id, intent_library_id, vision_library_id, agent_library_id, "
    "owner_tenant_id, created_at, updated_at "
    "FROM llm_profiles"
)


async def _fetch_owned_entry(
    entry_id: str, tenant_id: str, db: AsyncSession
) -> Any:
    """Fetch a library entry owned by this tenant. Returns row or raises 404."""
    result = await db.execute(
        text(f"{_ENTRY_SELECT} WHERE id = :id AND owner_tenant_id = :tid"),
        {"id": entry_id, "tid": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library entry not found",
        )
    return row


async def _fetch_owned_profile(
    profile_id: str, tenant_id: str, db: AsyncSession
) -> Any:
    """Fetch a BYOLLM profile owned by this tenant. Returns row or raises 404."""
    result = await db.execute(
        text(f"{_PROFILE_SELECT} WHERE id = :id AND owner_tenant_id = :tid"),
        {"id": profile_id, "tid": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    return row


# ---------------------------------------------------------------------------
# Inline Test Connection (no DB entry required)
# ---------------------------------------------------------------------------


@router.post("/test-connection", response_model=TestConnectionResult)
async def test_connection_inline(
    request: TestConnectionRequest,
    current_user: CurrentUser = Depends(_require_enterprise),
):
    """Test a provider connection before creating a library entry.

    API key is used in-memory only — never stored or logged.
    SSRF validation runs on endpoint_url before any network call.
    """
    backend_provider = _FRONTEND_PROVIDER_MAP.get(request.provider)
    if backend_provider is None:
        return TestConnectionResult(
            passed=False,
            error_code="invalid_provider",
            error_message=f"Unknown provider '{request.provider}'",
        )

    if request.endpoint_url:
        from app.core.security.url_validator import SSRFValidationError, validate_llm_endpoint
        try:
            validate_llm_endpoint(request.endpoint_url)
        except SSRFValidationError as exc:
            return TestConnectionResult(
                passed=False,
                error_code="ssrf_blocked",
                error_message=str(exc),
            )

    import time as _time
    start = _time.monotonic()
    api_key = request.api_key

    try:
        from app.core.llm.provider_service import ProviderService
        svc = ProviderService()
        adapter = svc.build_adapter(
            provider=backend_provider,
            model_name=request.model_name,
            endpoint_url=request.endpoint_url,
            api_key=api_key,
            api_version=request.api_version,
        )
        await asyncio.wait_for(
            adapter.complete([{"role": "user", "content": _TEST_PROMPT}]),
            timeout=_TEST_TIMEOUT_SECONDS,
        )
        latency_ms = int((_time.monotonic() - start) * 1000)
        return TestConnectionResult(passed=True, latency_ms=latency_ms)

    except asyncio.TimeoutError:
        latency_ms = int((_time.monotonic() - start) * 1000)
        return TestConnectionResult(
            passed=False,
            latency_ms=latency_ms,
            error_code="timeout",
            error_message="Connection timed out — check the endpoint URL",
        )

    except Exception as exc:
        latency_ms = int((_time.monotonic() - start) * 1000)
        err_str = str(exc).lower()
        if "auth" in err_str or "key" in err_str or "401" in err_str or "403" in err_str:
            return TestConnectionResult(
                passed=False,
                latency_ms=latency_ms,
                error_code="auth_failed",
                error_message="Authentication failed — check your API key",
            )
        elif "not found" in err_str or "404" in err_str:
            return TestConnectionResult(
                passed=False,
                latency_ms=latency_ms,
                error_code="model_not_found",
                error_message="Model or deployment not found — check the deployment name",
            )
        elif "ssrf" in err_str or "permitted" in err_str:
            return TestConnectionResult(
                passed=False,
                latency_ms=latency_ms,
                error_code="endpoint_not_permitted",
                error_message="Endpoint address is not permitted",
            )
        else:
            logger.warning(
                "byollm_test_connection_failed",
                tenant_id=current_user.tenant_id,
                provider=request.provider,
                error=str(exc)[:200],
            )
            return TestConnectionResult(
                passed=False,
                latency_ms=latency_ms,
                error_code="connection_failed",
                error_message="Connection failed — check your configuration",
            )

    finally:
        api_key = ""  # Clear key from memory


# ---------------------------------------------------------------------------
# Library Entry Routes
# ---------------------------------------------------------------------------


@router.get("/library-entries", response_model=list[LibraryEntryResponse])
async def list_library_entries(
    current_user: CurrentUser = Depends(_require_enterprise),
    db: AsyncSession = Depends(get_async_session),
):
    """List all library entries owned by this tenant, including their slot assignment.

    api_key_encrypted is NEVER returned — only api_key_last4.
    The `slot` field reflects which slot the entry is assigned to in the tenant's
    active BYOLLM profile (chat/intent/vision/agent), or null if unassigned.
    """
    result = await db.execute(
        text(
            "SELECT l.id, l.display_name AS name, l.provider, l.endpoint_url, l.api_version, "
            "l.model_name, l.api_key_last4, l.status, l.last_test_passed_at AS test_passed_at, "
            "l.capabilities, l.display_name, l.owner_tenant_id, l.created_at, l.updated_at, "
            "CASE "
            "  WHEN p.chat_library_id   = l.id THEN 'chat' "
            "  WHEN p.intent_library_id = l.id THEN 'intent' "
            "  WHEN p.vision_library_id = l.id THEN 'vision' "
            "  WHEN p.agent_library_id  = l.id THEN 'agent' "
            "  ELSE NULL "
            "END AS slot "
            "FROM llm_library l "
            "LEFT JOIN LATERAL ("
            "  SELECT chat_library_id, intent_library_id, vision_library_id, agent_library_id "
            "  FROM llm_profiles "
            "  WHERE owner_tenant_id = l.owner_tenant_id AND status = 'active' "
            "  ORDER BY created_at DESC LIMIT 1"
            ") p ON true "
            "WHERE l.owner_tenant_id = :tid AND l.status != 'disabled' "
            "ORDER BY l.created_at DESC"
        ),
        {"tid": current_user.tenant_id},
    )
    rows = result.fetchall()
    responses = []
    for row in rows:
        entry = _row_to_entry_response(row[:14])
        entry.slot = row[14]
        responses.append(entry)
    return responses


@router.post(
    "/library-entries",
    response_model=LibraryEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_library_entry(
    request: CreateLibraryEntryRequest,
    current_user: CurrentUser = Depends(_require_enterprise),
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new BYOLLM library entry.

    Validates SSRF on endpoint_url before any DB write.
    Encrypts api_key — plaintext is never stored.
    """
    # Accept both frontend short names and internal names
    backend_provider = _FRONTEND_PROVIDER_MAP.get(request.provider, request.provider)
    if backend_provider not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"provider must be one of {sorted(_VALID_PROVIDERS | set(_FRONTEND_PROVIDER_MAP.keys()))}",
        )

    if request.slot and request.slot not in _VALID_SLOTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"slot must be one of {sorted(_VALID_SLOTS)}",
        )

    # SSRF validation — must run before any DB write (skip for providers without endpoint_url)
    if request.endpoint_url:
        from app.core.security.url_validator import SSRFValidationError, validate_llm_endpoint
        try:
            validate_llm_endpoint(request.endpoint_url)
        except SSRFValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from None

    encrypted_key, last4 = _encrypt_api_key(request.api_key)
    entry_id = str(uuid.uuid4())

    caps_json = json.dumps(request.capabilities.model_dump())

    await db.execute(
        text(
            "INSERT INTO llm_library "
            "(id, provider, model_name, endpoint_url, api_version, "
            "api_key_encrypted, api_key_last4, status, capabilities, display_name, "
            "plan_tier, owner_tenant_id, is_byollm, created_at, updated_at) "
            "VALUES "
            "(:id, :provider, :model_name, :endpoint_url, :api_version, "
            ":api_key_encrypted, :api_key_last4, 'draft', CAST(:caps AS jsonb), :display_name, "
            "'enterprise', :tid, true, NOW(), NOW())"
        ),
        {
            "id": entry_id,
            "provider": backend_provider,
            "model_name": request.model_name,
            "endpoint_url": request.endpoint_url,
            "api_version": request.api_version,
            "api_key_encrypted": encrypted_key.encode("utf-8"),
            "api_key_last4": last4,
            "caps": caps_json,
            "display_name": request.display_name or request.model_name,
            "tid": current_user.tenant_id,
        },
    )

    # If a slot was specified, assign the entry to the tenant's BYOLLM profile.
    # Create the profile if it doesn't exist yet.
    if request.slot:
        slot_col = _SLOT_COL[request.slot]

        # Upsert BYOLLM profile for this tenant
        profile_result = await db.execute(
            text(
                "SELECT id FROM llm_profiles "
                "WHERE owner_tenant_id = :tid AND status != 'deprecated' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"tid": current_user.tenant_id},
        )
        profile_row = profile_result.fetchone()

        if profile_row:
            profile_id = str(profile_row[0])
            await db.execute(
                text(
                    f"UPDATE llm_profiles SET {slot_col} = :eid, updated_at = NOW() "
                    "WHERE id = :pid AND owner_tenant_id = :tid"
                ),
                {"eid": entry_id, "pid": profile_id, "tid": current_user.tenant_id},
            )
        else:
            profile_id = str(uuid.uuid4())
            await db.execute(
                text(
                    f"INSERT INTO llm_profiles "
                    f"(id, name, description, status, {slot_col}, owner_tenant_id, "
                    "is_platform_default, plan_tiers, created_at, updated_at) "
                    f"VALUES (:pid, 'My Custom Profile', NULL, 'active', :eid, :tid, "
                    "false, '{}', NOW(), NOW())"
                ),
                {"pid": profile_id, "eid": entry_id, "tid": current_user.tenant_id},
            )

    await db.commit()

    # Invalidate profile cache when a slot assignment was made
    if request.slot:
        await _invalidate_config_cache(current_user.tenant_id)

    logger.info(
        "byollm_library_entry_created",
        entry_id=entry_id,
        tenant_id=current_user.tenant_id,
        provider=request.provider,
    )

    row = await _fetch_owned_entry(entry_id, current_user.tenant_id, db)
    entry = _row_to_entry_response(row)
    entry.slot = request.slot
    return entry


@router.get("/library-entries/{entry_id}", response_model=LibraryEntryResponse)
async def get_library_entry(
    entry_id: str,
    current_user: CurrentUser = Depends(_require_enterprise),
    db: AsyncSession = Depends(get_async_session),
):
    """Fetch a single library entry owned by this tenant. Returns 404 for cross-tenant access."""
    row = await _fetch_owned_entry(entry_id, current_user.tenant_id, db)
    return _row_to_entry_response(row)


@router.patch("/library-entries/{entry_id}", response_model=LibraryEntryResponse)
async def update_library_entry(
    entry_id: str,
    request: UpdateLibraryEntryRequest,
    current_user: CurrentUser = Depends(_require_enterprise),
    db: AsyncSession = Depends(get_async_session),
):
    """Update library entry metadata. Does NOT allow api_key change (use rotate-key)."""
    # Verify ownership
    await _fetch_owned_entry(entry_id, current_user.tenant_id, db)

    # SSRF validation if endpoint_url is provided
    if request.endpoint_url is not None:
        from app.core.security.url_validator import SSRFValidationError, validate_llm_endpoint
        try:
            validate_llm_endpoint(request.endpoint_url)
        except SSRFValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from None

    _UPDATABLE_COLS = frozenset({"name", "endpoint_url", "api_version", "model_name", "display_name"})
    set_clauses: list[str] = []
    params: dict = {"id": entry_id, "tid": current_user.tenant_id}

    for col in _UPDATABLE_COLS:
        val = getattr(request, col, None)
        if val is not None:
            set_clauses.append(f"{col} = :{col}")
            params[col] = val

    if request.capabilities is not None:
        set_clauses.append("capabilities = CAST(:capabilities AS jsonb)")
        params["capabilities"] = json.dumps(request.capabilities.model_dump())

    if not set_clauses:
        row = await _fetch_owned_entry(entry_id, current_user.tenant_id, db)
        return _row_to_entry_response(row)

    set_clauses.append("updated_at = NOW()")
    sql = (
        f"UPDATE llm_library SET {', '.join(set_clauses)} "
        "WHERE id = :id AND owner_tenant_id = :tid"
    )
    result = await db.execute(text(sql), params)
    if (result.rowcount or 0) == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library entry not found")

    await db.commit()

    logger.info(
        "byollm_library_entry_updated",
        entry_id=entry_id,
        tenant_id=current_user.tenant_id,
    )

    row = await _fetch_owned_entry(entry_id, current_user.tenant_id, db)
    return _row_to_entry_response(row)


@router.patch("/library-entries/{entry_id}/rotate-key", response_model=LibraryEntryResponse)
async def rotate_library_entry_key(
    entry_id: str,
    request: RotateKeyRequest,
    current_user: CurrentUser = Depends(_require_enterprise),
    db: AsyncSession = Depends(get_async_session),
):
    """Rotate the API key for a library entry.

    Re-encrypts the new key, updates api_key_last4, resets test_passed_at to NULL.
    Key change invalidates previous test result — entry reverts to 'draft' status.
    """
    await _fetch_owned_entry(entry_id, current_user.tenant_id, db)

    encrypted_key, last4 = _encrypt_api_key(request.api_key)

    result = await db.execute(
        text(
            "UPDATE llm_library "
            "SET api_key_encrypted = :encrypted, api_key_last4 = :last4, "
            "test_passed_at = NULL, status = 'draft', updated_at = NOW() "
            "WHERE id = :id AND owner_tenant_id = :tid"
        ),
        {
            "encrypted": encrypted_key.encode("utf-8"),
            "last4": last4,
            "id": entry_id,
            "tid": current_user.tenant_id,
        },
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library entry not found")

    await db.commit()

    logger.info(
        "byollm_library_entry_key_rotated",
        entry_id=entry_id,
        tenant_id=current_user.tenant_id,
    )

    row = await _fetch_owned_entry(entry_id, current_user.tenant_id, db)
    return _row_to_entry_response(row)


@router.post("/library-entries/{entry_id}/test", response_model=TestEntryResponse)
async def test_library_entry(
    entry_id: str,
    current_user: CurrentUser = Depends(_require_enterprise),
    db: AsyncSession = Depends(get_async_session),
):
    """Test connectivity for a library entry.

    On success: sets test_passed_at = NOW(), status = 'published'.
    On failure: sets test_passed_at = NULL, status = 'draft'.
    Response body contents are NEVER stored or returned.
    """
    # Verify ownership — returns row with api_key_encrypted in position [6]
    existing_row = await _fetch_owned_entry(entry_id, current_user.tenant_id, db)

    # Row columns: id[0], name[1], provider[2], endpoint_url[3], api_version[4],
    #              model_name[5], api_key_last4[6], status[7], test_passed_at[8],
    #              capabilities[9], display_name[10], owner_tenant_id[11], ...
    # NOTE: _ENTRY_SELECT does NOT include api_key_encrypted — it was intentionally excluded
    # to prevent accidental exposure. We need a separate query for the encrypted key.
    key_result = await db.execute(
        text("SELECT api_key_encrypted FROM llm_library WHERE id = :id AND owner_tenant_id = :tid"),
        {"id": entry_id, "tid": current_user.tenant_id},
    )
    key_row = key_result.fetchone()
    api_key_encrypted = key_row[0] if key_row else None

    provider = existing_row[2]
    endpoint_url = existing_row[3]
    api_version = existing_row[4]
    model_name = existing_row[5]

    if not api_key_encrypted:
        return TestEntryResponse(
            success=False,
            error="No API key configured — add a key before testing",
        )

    # SSRF re-validation before test
    from app.core.security.url_validator import SSRFValidationError, validate_llm_endpoint
    try:
        validate_llm_endpoint(endpoint_url)
    except SSRFValidationError:
        await db.execute(
            text(
                "UPDATE llm_library SET last_test_passed_at = NULL, status = 'draft', updated_at = NOW() "
                "WHERE id = :id AND owner_tenant_id = :tid"
            ),
            {"id": entry_id, "tid": current_user.tenant_id},
        )
        await db.commit()
        return TestEntryResponse(
            success=False,
            error="Endpoint address is not permitted",
        )

    import time as _time
    start = _time.monotonic()
    success = False
    error_msg: Optional[str] = None
    latency_ms: Optional[int] = None

    decrypted_key: Optional[str] = None
    try:
        from app.core.llm.provider_service import ProviderService
        svc = ProviderService()
        decrypted_key = svc.decrypt_api_key(api_key_encrypted)

        adapter = svc.build_adapter(
            provider=provider,
            model_name=model_name,
            endpoint_url=endpoint_url,
            api_key=decrypted_key,
            api_version=api_version,
        )
        await asyncio.wait_for(
            adapter.complete([{"role": "user", "content": _TEST_PROMPT}]),
            timeout=_TEST_TIMEOUT_SECONDS,
        )
        latency_ms = int((_time.monotonic() - start) * 1000)
        success = True

    except asyncio.TimeoutError:
        latency_ms = int((_time.monotonic() - start) * 1000)
        error_msg = "Connection timed out — check the endpoint URL"

    except Exception as exc:
        latency_ms = int((_time.monotonic() - start) * 1000)
        err_str = str(exc).lower()
        if "auth" in err_str or "key" in err_str or "401" in err_str or "403" in err_str:
            error_msg = "Authentication failed — check your API key"
        elif "timeout" in err_str:
            error_msg = "Connection timed out — check the endpoint URL"
        elif "ssrf" in err_str or "permitted" in err_str:
            error_msg = "Endpoint address is not permitted"
        else:
            error_msg = "Connection failed"

    finally:
        if decrypted_key is not None:
            decrypted_key = ""

    # Update test result in DB
    if success:
        await db.execute(
            text(
                "UPDATE llm_library SET last_test_passed_at = NOW(), status = 'published', "
                "updated_at = NOW() WHERE id = :id AND owner_tenant_id = :tid"
            ),
            {"id": entry_id, "tid": current_user.tenant_id},
        )
    else:
        await db.execute(
            text(
                "UPDATE llm_library SET last_test_passed_at = NULL, status = 'draft', "
                "updated_at = NOW() WHERE id = :id AND owner_tenant_id = :tid"
            ),
            {"id": entry_id, "tid": current_user.tenant_id},
        )
    await db.commit()

    logger.info(
        "byollm_library_entry_tested",
        entry_id=entry_id,
        tenant_id=current_user.tenant_id,
        success=success,
        latency_ms=latency_ms,
    )

    return TestEntryResponse(success=success, error=error_msg, latency_ms=latency_ms)


@router.delete("/library-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_library_entry(
    entry_id: str,
    current_user: CurrentUser = Depends(_require_enterprise),
    db: AsyncSession = Depends(get_async_session),
):
    """Soft delete a library entry (status = 'disabled').

    Blocked if the entry is assigned to any BYOLLM profile slot (returns 409).
    """
    await _fetch_owned_entry(entry_id, current_user.tenant_id, db)

    # Check if assigned to any BYOLLM profile slot
    slot_check = await db.execute(
        text(
            "SELECT COUNT(*) FROM llm_profiles "
            "WHERE owner_tenant_id = :tid "
            "AND (chat_library_id = :id OR intent_library_id = :id "
            "     OR vision_library_id = :id OR agent_library_id = :id)"
        ),
        {"tid": current_user.tenant_id, "id": entry_id},
    )
    slot_count_row = slot_check.fetchone()
    if slot_count_row and slot_count_row[0] > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete entry — it is assigned to one or more BYOLLM profile slots",
        )

    result = await db.execute(
        text(
            "UPDATE llm_library SET status = 'disabled', updated_at = NOW() "
            "WHERE id = :id AND owner_tenant_id = :tid"
        ),
        {"id": entry_id, "tid": current_user.tenant_id},
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library entry not found")

    await db.commit()

    logger.info(
        "byollm_library_entry_disabled",
        entry_id=entry_id,
        tenant_id=current_user.tenant_id,
    )


# ---------------------------------------------------------------------------
# Profile Management Routes
# ---------------------------------------------------------------------------


@router.get("/profiles", response_model=list[BYOLLMProfileResponse])
async def list_byollm_profiles(
    current_user: CurrentUser = Depends(_require_enterprise),
    db: AsyncSession = Depends(get_async_session),
):
    """List BYOLLM profiles owned by this tenant."""
    result = await db.execute(
        text(
            f"{_PROFILE_SELECT} "
            "WHERE owner_tenant_id = :tid AND status != 'disabled' "
            "ORDER BY name ASC"
        ),
        {"tid": current_user.tenant_id},
    )
    return [_row_to_profile_response(row) for row in result.fetchall()]


@router.post(
    "/profiles",
    response_model=BYOLLMProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_byollm_profile(
    request: CreateProfileRequest,
    current_user: CurrentUser = Depends(_require_enterprise),
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new BYOLLM profile shell (no slots assigned yet)."""
    from app.modules.llm_profiles.service import (
        LLMProfileConflictError,
        LLMProfileService,
        LLMProfileValidationError,
    )
    svc = LLMProfileService()
    try:
        profile = await svc.create_byollm_profile(
            tenant_id=current_user.tenant_id,
            name=request.name,
            description=request.description,
            slot_data={},
            actor_id=current_user.id,
            db=db,
        )
    except LLMProfileConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except LLMProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None

    await db.commit()

    row = await _fetch_owned_profile(profile["id"], current_user.tenant_id, db)
    return _row_to_profile_response(row)


@router.patch("/profiles/{profile_id}/slots/{slot}", response_model=BYOLLMProfileResponse)
async def assign_byollm_slot(
    profile_id: str,
    slot: str,
    request: AssignSlotRequest,
    current_user: CurrentUser = Depends(_require_enterprise),
    db: AsyncSession = Depends(get_async_session),
):
    """Assign a library entry to a slot on a BYOLLM profile.

    Validates that the library_id belongs to this tenant and is not disabled.
    """
    if slot not in _VALID_SLOTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"slot must be one of {sorted(_VALID_SLOTS)}",
        )

    # Verify profile ownership
    await _fetch_owned_profile(profile_id, current_user.tenant_id, db)

    # Verify library entry ownership and status
    entry_check = await db.execute(
        text(
            "SELECT id, status FROM llm_library "
            "WHERE id = :lid AND owner_tenant_id = :tid"
        ),
        {"lid": request.library_id, "tid": current_user.tenant_id},
    )
    entry_row = entry_check.fetchone()
    if entry_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library entry not found",
        )
    if entry_row[1] == "disabled":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot assign a disabled library entry to a slot",
        )

    slot_col = _SLOT_COL[slot]
    result = await db.execute(
        text(
            f"UPDATE llm_profiles SET {slot_col} = :lid, updated_at = NOW() "
            "WHERE id = :pid AND owner_tenant_id = :tid"
        ),
        {"lid": request.library_id, "pid": profile_id, "tid": current_user.tenant_id},
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    await db.commit()
    await _invalidate_config_cache(current_user.tenant_id)

    logger.info(
        "byollm_profile_slot_assigned",
        profile_id=profile_id,
        slot=slot,
        library_id=request.library_id,
        tenant_id=current_user.tenant_id,
    )

    row = await _fetch_owned_profile(profile_id, current_user.tenant_id, db)
    return _row_to_profile_response(row)


@router.post("/profiles/{profile_id}/activate", response_model=BYOLLMProfileResponse)
async def activate_byollm_profile(
    profile_id: str,
    current_user: CurrentUser = Depends(_require_enterprise),
    db: AsyncSession = Depends(get_async_session),
):
    """Activate a BYOLLM profile.

    Requires chat and intent slots to be assigned and tested (status='published').
    Returns 422 with clear message if requirements not met.
    """
    profile_row = await _fetch_owned_profile(profile_id, current_user.tenant_id, db)
    chat_lib_id = profile_row[4]
    intent_lib_id = profile_row[5]

    if not chat_lib_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot activate — the 'chat' slot is not assigned",
        )
    if not intent_lib_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot activate — the 'intent' slot is not assigned",
        )

    # Verify required slots have been tested (status='published' AND last_test_passed_at IS NOT NULL)
    for slot_name, lib_id in (("chat", chat_lib_id), ("intent", intent_lib_id)):
        test_check = await db.execute(
            text(
                "SELECT status, last_test_passed_at FROM llm_library "
                "WHERE id = :id AND owner_tenant_id = :tid"
            ),
            {"id": lib_id, "tid": current_user.tenant_id},
        )
        test_row = test_check.fetchone()
        if test_row is None or test_row[0] != "published":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Cannot activate — the '{slot_name}' library entry has not been published. "
                    "Publish the entry before activating."
                ),
            )
        if test_row[1] is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Cannot activate — the '{slot_name}' library entry has not been tested. "
                    "Run POST /admin/byollm/library-entries/{id}/test first."
                ),
            )

    # Mark profile as active
    await db.execute(
        text(
            "UPDATE llm_profiles SET status = 'active', updated_at = NOW() "
            "WHERE id = :pid AND owner_tenant_id = :tid"
        ),
        {"pid": profile_id, "tid": current_user.tenant_id},
    )

    # Set this profile as the tenant's effective profile
    await db.execute(
        text("UPDATE tenants SET llm_profile_id = :pid WHERE id = :tid"),
        {"pid": profile_id, "tid": current_user.tenant_id},
    )

    await db.commit()
    await _invalidate_config_cache(current_user.tenant_id)

    logger.info(
        "byollm_profile_activated",
        profile_id=profile_id,
        tenant_id=current_user.tenant_id,
    )

    row = await _fetch_owned_profile(profile_id, current_user.tenant_id, db)
    return _row_to_profile_response(row)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_byollm_profile(
    profile_id: str,
    current_user: CurrentUser = Depends(_require_enterprise),
    db: AsyncSession = Depends(get_async_session),
):
    """Soft delete a BYOLLM profile (status = 'deprecated').

    Blocked if this profile is currently active for the tenant.
    Tenant must switch away first via POST /admin/llm-config/select-profile.
    """
    await _fetch_owned_profile(profile_id, current_user.tenant_id, db)

    # Check if currently active for this tenant
    active_check = await db.execute(
        text("SELECT llm_profile_id FROM tenants WHERE id = :tid"),
        {"tid": current_user.tenant_id},
    )
    active_row = active_check.fetchone()
    if active_row and active_row[0] is not None and str(active_row[0]) == profile_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot delete the currently active profile — "
                "select a different profile first via POST /admin/llm-config/select-profile"
            ),
        )

    result = await db.execute(
        text(
            "UPDATE llm_profiles SET status = 'deprecated', updated_at = NOW() "
            "WHERE id = :id AND owner_tenant_id = :tid"
        ),
        {"id": profile_id, "tid": current_user.tenant_id},
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    await db.commit()

    logger.info(
        "byollm_profile_deprecated",
        profile_id=profile_id,
        tenant_id=current_user.tenant_id,
    )
