"""
Platform LLM Profile API (TODO-32).

Endpoints (require platform_admin scope):
    GET    /platform/llm-profiles                     — list platform profiles
    POST   /platform/llm-profiles                     — create platform profile
    GET    /platform/llm-profiles/default             — get platform default
    GET    /platform/llm-profiles/available-models/{slot} — library entries by slot
    GET    /platform/llm-profiles/{id}                — get single profile
    PATCH  /platform/llm-profiles/{id}                — update platform profile
    DELETE /platform/llm-profiles/{id}                — deprecate profile
    POST   /platform/llm-profiles/{id}/deprecate      — deprecate profile (alias)
    POST   /platform/llm-profiles/{id}/set-default    — set as platform default
    PUT    /platform/llm-profiles/{id}/slots           — assign all slots atomically
    PATCH  /platform/llm-profiles/{id}/slots/{slot}   — assign single slot
    DELETE /platform/llm-profiles/{id}/slots/{slot}   — unassign a slot
    POST   /platform/llm-profiles/{id}/test           — test all assigned slots
    GET    /platform/llm-profiles/{id}/tenants        — tenants using this profile

Security invariants:
    api_key_encrypted, api_key_hash NEVER appear in any response body.
    Only api_key_last4 (if present on the library entry) is returned.

All write operations emit audit log entries via LLMProfileService._audit().
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.llm.profile_resolver import ProfileResolver
from app.core.session import get_async_session
from app.modules.llm_profiles.service import (
    LLMProfileConflictError,
    LLMProfileNotFoundError,
    LLMProfileService,
    LLMProfileValidationError,
    VALID_PLAN_TIERS,
    VALID_SLOTS,
)

# Valid slot names for path parameter validation
_VALID_SLOT_NAMES = frozenset({"chat", "intent", "vision", "agent"})

logger = structlog.get_logger()

router = APIRouter(prefix="/platform/llm-profiles", tags=["platform-llm-profiles"])

_service = LLMProfileService()
_resolver = ProfileResolver()

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SlotAssignment(BaseModel):
    library_id: Optional[str] = None
    library_entry_id: Optional[str] = None  # frontend alias for library_id
    params: dict[str, Any] = Field(default_factory=dict)
    traffic_split: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"protected_namespaces": ()}

    @property
    def resolved_library_id(self) -> Optional[str]:
        return self.library_id or self.library_entry_id


class CreatePlatformProfileRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    plan_tiers: list[str] = Field(default_factory=list)
    is_platform_default: bool = False
    # Slot assignments
    chat: Optional[SlotAssignment] = None
    intent: Optional[SlotAssignment] = None
    vision: Optional[SlotAssignment] = None
    agent: Optional[SlotAssignment] = None

    model_config = {"protected_namespaces": ()}


class UpdatePlatformProfileRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    plan_tiers: Optional[list[str]] = None
    is_platform_default: Optional[bool] = None
    status: Optional[str] = Field(None, pattern="^(active|deprecated)$")
    chat: Optional[SlotAssignment] = None
    intent: Optional[SlotAssignment] = None
    vision: Optional[SlotAssignment] = None
    agent: Optional[SlotAssignment] = None

    model_config = {"protected_namespaces": ()}


class SlotInfo(BaseModel):
    library_entry_id: str
    model_name: str
    provider: str
    health_status: str = "unknown"
    test_passed_at: Optional[str] = None

    model_config = {"protected_namespaces": ()}


class LLMProfileResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: str
    chat_library_id: Optional[str] = None
    intent_library_id: Optional[str] = None
    vision_library_id: Optional[str] = None
    agent_library_id: Optional[str] = None
    chat_params: dict[str, Any] = Field(default_factory=dict)
    intent_params: dict[str, Any] = Field(default_factory=dict)
    vision_params: dict[str, Any] = Field(default_factory=dict)
    agent_params: dict[str, Any] = Field(default_factory=dict)
    chat_traffic_split: list[dict[str, Any]] = Field(default_factory=list)
    intent_traffic_split: list[dict[str, Any]] = Field(default_factory=list)
    vision_traffic_split: list[dict[str, Any]] = Field(default_factory=list)
    agent_traffic_split: list[dict[str, Any]] = Field(default_factory=list)
    is_platform_default: bool
    plan_tiers: list[str]
    owner_tenant_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Enriched fields for list view
    slots: dict[str, Optional[SlotInfo]] = Field(default_factory=dict)
    tenants_count: int = 0

    model_config = {"protected_namespaces": ()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request_to_slot_data(request: CreatePlatformProfileRequest | UpdatePlatformProfileRequest) -> dict:
    """Flatten slot sub-objects into the flat dict format expected by the service."""
    data: dict = {}
    for slot_name in ("chat", "intent", "vision", "agent"):
        slot_obj: Optional[SlotAssignment] = getattr(request, slot_name, None)
        if slot_obj is None:
            continue
        if slot_obj.resolved_library_id is not None:
            data[f"{slot_name}_library_id"] = slot_obj.resolved_library_id
        if slot_obj.params:
            data[f"{slot_name}_params"] = slot_obj.params
        if slot_obj.traffic_split:
            data[f"{slot_name}_traffic_split"] = slot_obj.traffic_split
    return data


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[LLMProfileResponse])
async def list_platform_profiles(
    plan: Optional[str] = Query(None, description="Filter by plan tier eligibility"),
    include_deprecated: bool = Query(False),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """List all platform-owned LLM profiles."""
    if plan and plan not in VALID_PLAN_TIERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"plan must be one of {sorted(VALID_PLAN_TIERS)}",
        )

    profiles = await _service.list_platform_profiles(
        plan_filter=plan,
        include_deprecated=include_deprecated,
        db=db,
    )
    return [LLMProfileResponse(**p) for p in profiles]


@router.get("/default", response_model=Optional[LLMProfileResponse])
async def get_platform_default_profile(
    plan: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Get the platform default LLM profile (or null if none set)."""
    profile = await _service.get_platform_default(plan=plan, db=db)
    if profile is None:
        return None
    return LLMProfileResponse(**profile)


@router.get("/{profile_id}", response_model=LLMProfileResponse)
async def get_platform_profile(
    profile_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a single platform LLM profile by ID."""
    try:
        profile = await _service.get_profile(profile_id, db=db)
    except LLMProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    # Restrict to platform profiles only in this endpoint
    if profile.get("owner_tenant_id") is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return LLMProfileResponse(**profile)


@router.post("", response_model=LLMProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_platform_profile(
    request: CreatePlatformProfileRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new platform LLM profile."""
    slot_data = _request_to_slot_data(request)
    try:
        profile = await _service.create_platform_profile(
            name=request.name,
            description=request.description,
            plan_tiers=request.plan_tiers,
            slot_data=slot_data,
            is_platform_default=request.is_platform_default,
            actor_id=current_user.id,
            db=db,
        )
    except LLMProfileConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except LLMProfileValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    await db.commit()
    if request.is_platform_default:
        await _resolver.invalidate_all()
    return LLMProfileResponse(**profile)


@router.patch("/{profile_id}", response_model=LLMProfileResponse)
async def update_platform_profile(
    profile_id: str,
    request: UpdatePlatformProfileRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Update a platform LLM profile (sparse update — only provided fields change)."""
    updates: dict = {}
    if request.name is not None:
        updates["name"] = request.name
    if request.description is not None:
        updates["description"] = request.description
    if request.plan_tiers is not None:
        updates["plan_tiers"] = request.plan_tiers
    if request.is_platform_default is not None:
        updates["is_platform_default"] = request.is_platform_default
    if request.status is not None:
        updates["status"] = request.status
    updates.update(_request_to_slot_data(request))

    try:
        profile = await _service.update_platform_profile(
            profile_id,
            updates=updates,
            actor_id=current_user.id,
            db=db,
        )
    except LLMProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    except LLMProfileValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    await db.commit()
    # Platform profile changes can affect any tenant using this profile (or the default)
    await _resolver.invalidate_all()
    return LLMProfileResponse(**profile)


@router.post("/{profile_id}/deprecate", response_model=LLMProfileResponse)
async def deprecate_platform_profile(
    profile_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Mark a platform profile as deprecated."""
    try:
        profile = await _service.deprecate_platform_profile(
            profile_id,
            actor_id=current_user.id,
            db=db,
        )
    except LLMProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    except LLMProfileValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    await db.commit()
    await _resolver.invalidate_all()
    return LLMProfileResponse(**profile)


@router.delete("/{profile_id}", response_model=LLMProfileResponse)
async def delete_platform_profile(
    profile_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Semantically delete (deprecate) a platform profile.

    Returns 409 when tenants are currently assigned to this profile.
    """
    # Check if any tenants are using this profile before deprecating
    tenant_count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM tenants WHERE llm_profile_id = :pid"
        ),
        {"pid": profile_id},
    )
    count_row = tenant_count_result.fetchone()
    tenant_count = count_row[0] if count_row else 0

    if tenant_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "profile_in_use",
                "tenant_count": tenant_count,
                "message": f"Remove this profile from {tenant_count} tenant(s) before deprecating",
            },
        )

    try:
        profile = await _service.deprecate_platform_profile(
            profile_id,
            actor_id=current_user.id,
            db=db,
        )
    except LLMProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    except LLMProfileValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    await db.commit()
    await _resolver.invalidate_all()
    return LLMProfileResponse(**profile)


@router.post("/{profile_id}/set-default", response_model=dict)
async def set_platform_default(
    profile_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Atomically set this profile as the platform default.

    Clears is_platform_default on any existing default, then sets it on this profile.
    Returns {"previous_default_id": ..., "new_default_id": ...}.
    """
    # Verify the profile exists and is a platform profile
    profile_result = await db.execute(
        text(
            "SELECT id, status, owner_tenant_id FROM llm_profiles "
            "WHERE id = :id AND owner_tenant_id IS NULL"
        ),
        {"id": profile_id},
    )
    profile_row = profile_result.fetchone()
    if profile_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    if profile_row[1] == "deprecated":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot set a deprecated profile as default",
        )

    # Get current default (if any)
    prev_result = await db.execute(
        text(
            "SELECT id FROM llm_profiles "
            "WHERE owner_tenant_id IS NULL AND is_platform_default = true"
        )
    )
    prev_row = prev_result.fetchone()
    previous_default_id = str(prev_row[0]) if prev_row else None

    # Atomic swap: clear all defaults, then set this one
    await db.execute(
        text(
            "UPDATE llm_profiles SET is_platform_default = false, updated_at = NOW() "
            "WHERE owner_tenant_id IS NULL AND is_platform_default = true"
        )
    )
    await db.execute(
        text(
            "UPDATE llm_profiles SET is_platform_default = true, updated_at = NOW() "
            "WHERE id = :id"
        ),
        {"id": profile_id},
    )

    from app.modules.llm_profiles.service import _audit
    await _audit(
        actor_id=current_user.id,
        tenant_id=None,
        entity_type="llm_profile",
        entity_id=profile_id,
        action="set_default",
        diff={
            "before": {"default_id": previous_default_id},
            "after": {"default_id": profile_id},
        },
        db=db,
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another default profile was set concurrently. Please retry.",
        )
    # Default change affects all tenants — invalidate entire profile cache
    await _resolver.invalidate_all()

    logger.info(
        "llm_profile_default_set",
        profile_id=profile_id,
        previous_default_id=previous_default_id,
        actor_id=current_user.id,
    )

    return {
        "previous_default_id": previous_default_id,
        "new_default_id": profile_id,
    }


@router.put("/{profile_id}/slots", response_model=LLMProfileResponse)
async def assign_all_slots(
    profile_id: str,
    request: CreatePlatformProfileRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Atomically assign all 4 slots in one request.

    Chat and intent are required. Vision and agent are optional.
    Replaces ALL existing slot assignments.
    """
    if request.chat is None or request.intent is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="chat and intent slots are required",
        )

    slot_data = _request_to_slot_data(request)

    try:
        profile = await _service.update_platform_profile(
            profile_id,
            updates=slot_data,
            actor_id=current_user.id,
            db=db,
        )
    except LLMProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    except LLMProfileValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    await db.commit()
    await _resolver.invalidate_all()
    return LLMProfileResponse(**profile)


@router.patch("/{profile_id}/slots/{slot}", response_model=LLMProfileResponse)
async def assign_single_slot(
    profile_id: str,
    slot: str,
    request: SlotAssignment,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Assign a single slot by name."""
    if slot not in _VALID_SLOT_NAMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"slot must be one of {sorted(_VALID_SLOT_NAMES)}",
        )

    updates: dict = {}
    resolved_lib_id = request.resolved_library_id
    if resolved_lib_id is not None:
        updates[f"{slot}_library_id"] = resolved_lib_id
    if request.params:
        updates[f"{slot}_params"] = request.params
    if request.traffic_split:
        updates[f"{slot}_traffic_split"] = request.traffic_split

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No slot fields provided",
        )

    try:
        profile = await _service.update_platform_profile(
            profile_id,
            updates=updates,
            actor_id=current_user.id,
            db=db,
        )
    except LLMProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    except LLMProfileValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    await db.commit()
    await _resolver.invalidate_all()
    return LLMProfileResponse(**profile)


@router.delete("/{profile_id}/slots/{slot}", response_model=LLMProfileResponse)
async def unassign_slot(
    profile_id: str,
    slot: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Unassign a slot (set library_id to NULL and params to {}).

    Blocked for chat and intent slots on active profiles — those are required.
    """
    if slot not in _VALID_SLOT_NAMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"slot must be one of {sorted(_VALID_SLOT_NAMES)}",
        )

    if slot in ("chat", "intent"):
        # Check profile status — required slots cannot be unassigned from active profiles
        profile_check = await db.execute(
            text("SELECT status FROM llm_profiles WHERE id = :id AND owner_tenant_id IS NULL"),
            {"id": profile_id},
        )
        row = profile_check.fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
        if row[0] == "active":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Cannot unassign the '{slot}' slot from an active profile — it is required",
            )

    updates = {
        f"{slot}_library_id": None,
        f"{slot}_params": {},
        f"{slot}_traffic_split": [],
    }

    try:
        profile = await _service.update_platform_profile(
            profile_id,
            updates=updates,
            actor_id=current_user.id,
            db=db,
        )
    except LLMProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    except LLMProfileValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    await db.commit()
    await _resolver.invalidate_all()
    return LLMProfileResponse(**profile)


# ---------------------------------------------------------------------------
# Slot test endpoint
# ---------------------------------------------------------------------------


class SlotTestResult(BaseModel):
    """Result of testing a single slot."""
    slot: str
    success: bool
    latency_ms: Optional[int] = None
    model_name: Optional[str] = None
    token_count: Optional[int] = None
    error_message: Optional[str] = None

    model_config = {"protected_namespaces": ()}


async def _test_slot(slot_name: str, library_id: str) -> SlotTestResult:
    """Send a minimal test prompt to a single slot's library entry.

    Returns SlotTestResult with success/failure and timing.
    Results are never stored.
    """
    import time as _time

    _TEST_PROMPT = "Respond with 'ok' and nothing else."
    _TIMEOUT_SECONDS = 10

    start = _time.monotonic()
    try:
        from app.core.session import async_session_factory
        from app.core.llm.provider_service import ProviderService
        from sqlalchemy import text as _text

        async with async_session_factory() as db_session:
            entry_result = await db_session.execute(
                _text(
                    "SELECT provider, model_name, endpoint_url, api_key_encrypted, api_version "
                    "FROM llm_library WHERE id = :id AND status = 'published'"
                ),
                {"id": library_id},
            )
            entry_row = entry_result.fetchone()

        if entry_row is None:
            return SlotTestResult(
                slot=slot_name,
                success=False,
                error_message="Library entry not found or not published",
            )

        provider, model_name, endpoint_url, api_key_encrypted, api_version = entry_row

        if not api_key_encrypted:
            return SlotTestResult(
                slot=slot_name,
                success=False,
                error_message="No API key configured for this library entry",
            )

        svc = ProviderService()
        decrypted_key: Optional[str] = None
        try:
            decrypted_key = svc.decrypt_api_key(api_key_encrypted)
            # Build a minimal adapter and send test prompt
            # (provider-specific call omitted to keep this general — use a shared test helper)
            adapter = svc.build_adapter(
                provider=provider,
                model_name=model_name,
                endpoint_url=endpoint_url,
                api_key=decrypted_key,
                api_version=api_version,
            )
            response = await asyncio.wait_for(
                adapter.complete([{"role": "user", "content": _TEST_PROMPT}], model=model_name),
                timeout=_TIMEOUT_SECONDS,
            )
            elapsed_ms = int((_time.monotonic() - start) * 1000)
            return SlotTestResult(
                slot=slot_name,
                success=True,
                latency_ms=elapsed_ms,
                model_name=model_name,
                token_count=response.get("usage", {}).get("total_tokens"),
            )
        finally:
            if decrypted_key is not None:
                decrypted_key = ""

    except asyncio.TimeoutError:
        elapsed_ms = int((_time.monotonic() - start) * 1000)
        return SlotTestResult(
            slot=slot_name,
            success=False,
            latency_ms=elapsed_ms,
            error_message="Connection timed out — check the endpoint URL",
        )
    except Exception as exc:
        elapsed_ms = int((_time.monotonic() - start) * 1000)
        err_str = str(exc).lower()
        if "auth" in err_str or "key" in err_str or "401" in err_str or "403" in err_str:
            msg = "Authentication failed — check your API key"
        elif "timeout" in err_str:
            msg = "Connection timed out — check the endpoint URL"
        else:
            msg = "Connection failed"
        return SlotTestResult(
            slot=slot_name,
            success=False,
            latency_ms=elapsed_ms,
            error_message=msg,
        )


@router.post("/{profile_id}/test", response_model=dict)
async def test_platform_profile(
    profile_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Test all assigned slots in parallel (max 10s per slot).

    Returns per-slot results. Results are not stored.
    """
    try:
        profile = await _service.get_profile(profile_id, db=db)
    except LLMProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    if profile.get("owner_tenant_id") is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    # Collect assigned slots
    tasks = {}
    for slot_name in ("chat", "intent", "vision", "agent"):
        library_id = profile.get(f"{slot_name}_library_id")
        if library_id:
            tasks[slot_name] = asyncio.create_task(_test_slot(slot_name, library_id))

    if not tasks:
        return {"results": {}, "message": "No slots assigned — nothing to test"}

    await asyncio.gather(*tasks.values(), return_exceptions=True)

    results = {}
    for slot_name, task in tasks.items():
        try:
            result = task.result()
            results[slot_name] = result.model_dump()
        except Exception as exc:
            results[slot_name] = {
                "slot": slot_name,
                "success": False,
                "error_message": str(exc),
            }

    return {"results": results}


@router.get("/{profile_id}/history", response_model=list[dict])
async def get_profile_history(
    profile_id: str,
    limit: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Return the last N audit log entries for a platform profile, newest first.

    Each entry includes: id, action, actor_id, created_at, diff.
    The diff.before field (when present) captures the slot state before the
    change — used by the rollback endpoint to restore prior state.
    """
    # Verify the profile exists and is a platform profile
    profile_check = await db.execute(
        text(
            "SELECT id FROM llm_profiles "
            "WHERE id = :id AND owner_tenant_id IS NULL"
        ),
        {"id": profile_id},
    )
    if profile_check.fetchone() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    result = await db.execute(
        text(
            "SELECT id, action, actor_id, logged_at, diff "
            "FROM llm_profile_audit_log "
            "WHERE entity_id = :pid AND entity_type = 'llm_profile' "
            "ORDER BY logged_at DESC "
            "LIMIT :lim"
        ),
        {"pid": profile_id, "lim": limit},
    )
    rows = result.fetchall()

    import json as _json

    entries = []
    for row in rows:
        raw_diff = row[4]
        if isinstance(raw_diff, str):
            parsed_diff = _json.loads(raw_diff)
        else:
            parsed_diff = raw_diff or {}
        entries.append(
            {
                "id": str(row[0]),
                "action": row[1],
                "actor_id": str(row[2]) if row[2] else None,
                "created_at": row[3].isoformat() if row[3] else None,
                "diff": parsed_diff,
            }
        )
    return entries


@router.post("/{profile_id}/rollback/{history_id}", response_model=LLMProfileResponse)
async def rollback_profile_to_version(
    profile_id: str,
    history_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Restore a profile's slot assignments to the state captured in a history entry.

    Fetches the audit log entry identified by history_id, extracts diff.before,
    and applies those slot assignments back to the profile. A new audit log entry
    with action="rollback" is written to preserve the audit trail.

    Returns the updated profile.
    """
    import json as _json

    # Verify the profile exists and is a platform profile
    profile_check = await db.execute(
        text(
            "SELECT id FROM llm_profiles "
            "WHERE id = :id AND owner_tenant_id IS NULL"
        ),
        {"id": profile_id},
    )
    if profile_check.fetchone() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    # Fetch the history entry; verify it belongs to this profile
    history_result = await db.execute(
        text(
            "SELECT id, action, diff FROM llm_profile_audit_log "
            "WHERE id = :hid AND entity_id = :pid AND entity_type = 'llm_profile'"
        ),
        {"hid": history_id, "pid": profile_id},
    )
    history_row = history_result.fetchone()
    if history_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="History entry not found for this profile",
        )

    raw_diff = history_row[2]
    if isinstance(raw_diff, str):
        entry_diff = _json.loads(raw_diff)
    else:
        entry_diff = raw_diff or {}

    before_state: dict = entry_diff.get("before") or {}

    # Extract only slot-related fields from the before state
    _SLOT_COLS = frozenset({
        "chat_library_id", "intent_library_id", "vision_library_id", "agent_library_id",
        "chat_params", "intent_params", "vision_params", "agent_params",
        "chat_traffic_split", "intent_traffic_split", "vision_traffic_split", "agent_traffic_split",
    })
    slot_updates = {k: v for k, v in before_state.items() if k in _SLOT_COLS}

    if not slot_updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="History entry has no slot state to restore (diff.before is empty or contains no slot fields)",
        )

    try:
        profile = await _service.update_platform_profile(
            profile_id,
            updates=slot_updates,
            actor_id=current_user.id,
            db=db,
        )
    except LLMProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    except LLMProfileValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    # Write a rollback audit entry to preserve the audit trail
    from app.modules.llm_profiles.service import _audit as _audit_fn
    current_result = await db.execute(
        text(
            "SELECT chat_library_id, intent_library_id, vision_library_id, agent_library_id "
            "FROM llm_profiles WHERE id = :id"
        ),
        {"id": profile_id},
    )
    current_row = current_result.fetchone()
    after_slots = {
        "chat_library_id": str(current_row[0]) if current_row and current_row[0] else None,
        "intent_library_id": str(current_row[1]) if current_row and current_row[1] else None,
        "vision_library_id": str(current_row[2]) if current_row and current_row[2] else None,
        "agent_library_id": str(current_row[3]) if current_row and current_row[3] else None,
    } if current_row else {}

    await _audit_fn(
        actor_id=current_user.id,
        tenant_id=None,
        entity_type="llm_profile",
        entity_id=profile_id,
        action="rollback",
        diff={
            "rolled_back_from_history_id": history_id,
            "before": slot_updates,
            "after": after_slots,
        },
        db=db,
    )

    await db.commit()
    await _resolver.invalidate_all()

    logger.info(
        "llm_profile_rolled_back",
        profile_id=profile_id,
        history_id=history_id,
        actor_id=current_user.id,
    )

    return LLMProfileResponse(**profile)


@router.get("/{profile_id}/tenants", response_model=list[dict])
async def list_tenants_using_profile(
    profile_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """List tenants currently assigned to this platform profile (paginated)."""
    try:
        profile = await _service.get_profile(profile_id, db=db)
    except LLMProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    if profile.get("owner_tenant_id") is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    result = await db.execute(
        text(
            "SELECT t.id, t.name, t.plan, t.updated_at "
            "FROM tenants t "
            "WHERE t.llm_profile_id = :pid "
            "ORDER BY t.name ASC "
            "LIMIT :lim OFFSET :off"
        ),
        {"pid": profile_id, "lim": limit, "off": offset},
    )
    rows = result.fetchall()
    return [
        {
            "tenant_id": str(row[0]),
            "name": row[1],
            "plan_tier": row[2],
            "selected_at": row[3].isoformat() if row[3] else None,
        }
        for row in rows
    ]


@router.get("/available-models/{slot}", response_model=list[dict])
async def list_available_models_for_slot(
    slot: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Return llm_library entries eligible for a given slot.

    Filters by capabilities.eligible_slots containing the requested slot.
    api_key fields are NEVER returned.
    """
    if slot not in _VALID_SLOT_NAMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"slot must be one of {sorted(_VALID_SLOT_NAMES)}",
        )

    import json as _json

    result = await db.execute(
        text(
            "SELECT id, display_name, provider, model_name, health_status, "
            "health_checked_at, last_test_passed_at, status "
            "FROM llm_library "
            "WHERE status = 'published' "
            "AND ("
            "  capabilities IS NULL "
            "  OR capabilities->'eligible_slots' IS NULL "
            "  OR capabilities->'eligible_slots' @> :slot_json::jsonb"
            ") "
            "ORDER BY "
            "  CASE WHEN health_status = 'healthy' THEN 0 ELSE 1 END ASC, "
            "  display_name ASC"
        ),
        {"slot_json": _json.dumps([slot])},
    )
    rows = result.fetchall()
    return [
        {
            "library_entry_id": str(row[0]),
            "display_name": row[1] or row[3],
            "provider": row[2],
            "model_name": row[3],
            "health_status": row[4] or "unknown",
            "health_checked_at": row[5].isoformat() if row[5] else None,
            "test_passed_at": row[6].isoformat() if row[6] else None,
            "is_deprecated": row[7] == "deprecated",
        }
        for row in rows
    ]
