"""
Tenant LLM Configuration API (P2LLM-006 + TODO-33 B6 rewrite).

V1 endpoints (DEPRECATED — remove in Phase D once frontend is updated):
    GET    /admin/llm-config                   — returns current llm_config + byollm key presence
    PATCH  /admin/llm-config                   — DEPRECATED: removed in v2 (use select-profile)
    GET    /admin/llm-config/library-options   — DEPRECATED: delegates to available-profiles
    GET    /admin/llm-config/providers         — list enabled platform providers (PVDR-008)
    PATCH  /admin/llm-config/provider          — set tenant provider selection (PVDR-008)

V2 endpoints (TODO-33 B6):
    GET    /admin/llm-config                   — effective resolved profile (profile-aware)
    GET    /admin/llm-config/available-profiles — platform profiles visible to this tenant's plan
    POST   /admin/llm-config/select-profile    — select a platform profile (professional+ only)

V1 GET /admin/llm-config now includes _deprecated_model_source for frontend compat.
PATCH /admin/llm-config is REMOVED — replaced by POST /admin/llm-config/select-profile.
GET /admin/llm-config/library-options preserved as alias for available-profiles.

Config is stored in tenant_configs table under config_type='llm_config'.
Profile selection stored in tenants.llm_profile_id (set by select-profile endpoint).
Cache invalidation: Redis key mingai:{tenant_id}:llm_profile is DEL'd after profile changes.
"""
import json
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.middleware.plan_tier import require_plan_or_above
from app.core.redis_client import get_redis
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin-llm-config"])

_VALID_MODEL_SOURCES = frozenset({"library", "byollm"})

# Slot names available for provider selection display
_AVAILABLE_SLOTS = ["primary", "chat", "doc_embedding", "kb_embedding", "intent"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class BYOLLMStatus(BaseModel):
    """BYOLLM status embedded in LLMConfigResponse — never contains the key."""

    provider: Optional[str] = None
    key_present: bool = False


class SlotInfo(BaseModel):
    """Resolved info for a single model slot."""

    library_entry_id: Optional[str] = None
    model_name: Optional[str] = None
    display_name: Optional[str] = None
    provider: Optional[str] = None
    test_passed_at: Optional[str] = None
    is_available_on_plan: bool = True

    model_config = {"protected_namespaces": ()}


class SlotsPayload(BaseModel):
    """All four model slots — always present, values may be null."""

    chat: SlotInfo = Field(default_factory=SlotInfo)
    intent: SlotInfo = Field(default_factory=SlotInfo)
    vision: SlotInfo = Field(default_factory=SlotInfo)
    agent: SlotInfo = Field(default_factory=SlotInfo)

    model_config = {"protected_namespaces": ()}


class LLMConfigResponse(BaseModel):
    """Current tenant LLM configuration (v1 compat + v2 profile fields)."""

    # V1 compat fields (DEPRECATED: remove in Phase D)
    model_source: str  # "library" | "byollm" | "profile"
    llm_library_id: Optional[str] = None
    byollm: BYOLLMStatus

    # V2 profile fields
    profile_id: Optional[str] = None
    profile_name: Optional[str] = None
    description: Optional[str] = None
    plan_tier: str = "starter"
    is_byollm: bool = False
    slots: SlotsPayload = Field(default_factory=SlotsPayload)
    available_profiles_count: int = 0

    model_config = {"protected_namespaces": ()}


class EffectiveProfileResponse(BaseModel):
    """V2 response shape for resolved LLM profile."""

    profile_id: Optional[str] = None
    profile_name: Optional[str] = None
    is_byollm: bool = False
    slots: dict = Field(default_factory=dict)

    model_config = {"protected_namespaces": ()}


class SelectProfileRequest(BaseModel):
    """Body for POST /admin/llm-config/select-profile."""

    profile_id: str = Field(..., description="UUID of a platform LLM profile")

    model_config = {"protected_namespaces": ()}


class AvailableProfileItem(BaseModel):
    """A platform profile available for this tenant's plan tier."""

    id: str
    name: str
    description: Optional[str] = None
    plan_tiers: list[str]
    slot_summary: dict = Field(default_factory=dict)
    is_platform_default: bool = False
    estimated_cost_per_1k_queries: Optional[float] = None

    model_config = {"protected_namespaces": ()}


class LibraryOption(BaseModel):
    """A Published llm_library entry available for tenant assignment (PA-003/PA-004)."""

    id: str
    provider: str
    model_name: str
    display_name: str
    plan_tier: str
    is_recommended: bool
    pricing_per_1k_tokens_in: Optional[float] = None
    pricing_per_1k_tokens_out: Optional[float] = None

    model_config = {"protected_namespaces": ()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_llm_config_raw(tenant_id: str, db: AsyncSession) -> dict:
    """Read llm_config and byollm_key_ref from tenant_configs."""
    result = await db.execute(
        text(
            "SELECT config_type, config_data FROM tenant_configs "
            "WHERE tenant_id = :tid AND config_type IN ('llm_config', 'byollm_key_ref')"
        ),
        {"tid": tenant_id},
    )
    rows = result.fetchall()
    data: dict = {}
    for row in rows:
        config_type = row[0]
        config_data = row[1]
        if isinstance(config_data, str):
            config_data = json.loads(config_data)
        data[config_type] = config_data
    return data


async def _invalidate_config_cache(tenant_id: str) -> None:
    """DEL tenant LLM config Redis keys after mutation.

    Key format matches TenantConfigService._redis_key():
    mingai:{tenant_id}:config:{key}

    Also invalidates the ProfileResolver cache key:
    mingai:{tenant_id}:llm_profile

    Both keys are deleted because byollm mutations change byollm_key_ref
    and llm_config mutations change model_source — both affect routing.
    """
    try:
        # Clear in-process LRU first so the next resolve() hits DB, not stale LRU
        from app.core.llm.profile_resolver import ProfileResolver
        await ProfileResolver().invalidate(tenant_id)

        redis = get_redis()
        llm_key = f"mingai:{tenant_id}:config:llm_config"
        byollm_key = f"mingai:{tenant_id}:config:byollm_key_ref"
        profile_key = f"mingai:{tenant_id}:llm_profile"
        await redis.delete(llm_key, byollm_key, profile_key)
        logger.debug("llm_config_cache_invalidated", tenant_id=tenant_id)
    except Exception as exc:
        # Non-blocking — cache miss is acceptable
        logger.warning(
            "llm_config_cache_invalidate_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )


_NULL_SLOT = {
    "library_entry_id": None,
    "model_name": None,
    "display_name": None,
    "provider": None,
    "test_passed_at": None,
    "is_available_on_plan": True,
}

_SLOT_NAMES = ("chat", "intent", "vision", "agent")


def _empty_slots() -> dict:
    return {s: dict(_NULL_SLOT) for s in _SLOT_NAMES}


async def _resolve_effective_profile(tenant_id: str, plan: str, db: AsyncSession) -> dict:
    """Resolve the effective LLM profile for the tenant.

    Returns a dict with profile_id, profile_name, description, is_byollm, slots.
    Slots always contains all four keys (chat/intent/vision/agent) with null-safe values.
    Falls back to legacy llm_config if profile resolution returns nothing.
    """
    try:
        from app.core.llm.profile_resolver import ProfileResolver
        resolver = ProfileResolver()
        resolved = await resolver.resolve(tenant_id, plan=plan, db=db)
        if resolved:
            slots = _empty_slots()
            for slot_name in _SLOT_NAMES:
                slot = resolved.get_slot(slot_name)
                if slot and slot.library_id:
                    lib_result = await db.execute(
                        text(
                            "SELECT id, provider, model_name, display_name "
                            "FROM llm_library WHERE id = :id"
                        ),
                        {"id": slot.library_id},
                    )
                    lib_row = lib_result.fetchone()
                    if lib_row:
                        slots[slot_name] = {
                            "library_entry_id": str(lib_row[0]),
                            "model_name": lib_row[2],
                            "display_name": lib_row[3],
                            "provider": lib_row[1],
                            "test_passed_at": None,
                            "is_available_on_plan": True,
                        }
            return {
                "profile_id": resolved.profile_id,
                "profile_name": resolved.profile_name,
                "description": resolved.description if hasattr(resolved, "description") else None,
                "is_byollm": resolved.owner_tenant_id is not None,
                "slots": slots,
            }
    except Exception as exc:
        logger.warning(
            "effective_profile_resolution_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )

    # Fallback: legacy llm_config
    raw = await _get_llm_config_raw(tenant_id, db)
    llm_cfg = raw.get("llm_config", {})
    return {
        "profile_id": None,
        "profile_name": "No profile assigned",
        "description": None,
        "is_byollm": llm_cfg.get("model_source") == "byollm",
        "slots": _empty_slots(),
    }


# ---------------------------------------------------------------------------
# V2 Route handlers (TODO-33 B6)
# ---------------------------------------------------------------------------


@router.get("/llm-config/available-profiles", response_model=list[AvailableProfileItem])
async def list_available_profiles(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """List platform LLM profiles available for this tenant's plan tier (TODO-33 B6).

    Returns profiles where plan_tiers is empty (all plans) or contains the tenant's plan.
    Excludes deprecated profiles.
    """
    plan = getattr(current_user, "plan", "starter") or "starter"

    result = await db.execute(
        text(
            "SELECT id, name, description, plan_tiers, is_platform_default, "
            "chat_library_id, intent_library_id, vision_library_id, agent_library_id "
            "FROM llm_profiles "
            "WHERE owner_tenant_id IS NULL "
            "AND status = 'active' "
            "AND (plan_tiers = '{}' OR :plan = ANY(plan_tiers)) "
            "ORDER BY is_platform_default DESC, name ASC"
        ),
        {"plan": plan},
    )
    rows = result.fetchall()

    items = []
    for row in rows:
        slot_summary: dict = {}
        for i, slot_name in enumerate(("chat", "intent", "vision", "agent"), start=5):
            if row[i]:
                slot_summary[slot_name] = "assigned"
        items.append(
            AvailableProfileItem(
                id=str(row[0]),
                name=row[1],
                description=row[2],
                plan_tiers=list(row[3]) if row[3] else [],
                is_platform_default=bool(row[4]),
                slot_summary=slot_summary,
            )
        )
    return items


@router.post("/llm-config/select-profile", response_model=EffectiveProfileResponse)
async def select_profile(
    request: SelectProfileRequest,
    current_user: CurrentUser = Depends(require_plan_or_above("professional")),
    db: AsyncSession = Depends(get_async_session),
):
    """Select a platform LLM profile for this tenant (professional+ only) (TODO-33 B6).

    Starter tenants receive 403 before any DB access (enforced by require_plan_or_above).
    Invalidates the profile resolver cache for this tenant.
    """
    tenant_id = current_user.tenant_id
    plan = getattr(current_user, "plan", "professional") or "professional"

    # Verify the profile exists, is active, and is eligible for this tenant's plan
    profile_result = await db.execute(
        text(
            "SELECT id, name, status, plan_tiers, owner_tenant_id "
            "FROM llm_profiles "
            "WHERE id = :pid "
            "AND owner_tenant_id IS NULL "
            "AND status = 'active' "
            "AND (plan_tiers = '{}' OR :plan = ANY(plan_tiers))"
        ),
        {"pid": request.profile_id, "plan": plan},
    )
    profile_row = profile_result.fetchone()
    if profile_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found or not available for your plan",
        )

    # Update tenant's llm_profile_id
    update_result = await db.execute(
        text("UPDATE tenants SET llm_profile_id = :pid WHERE id = :tid"),
        {"pid": request.profile_id, "tid": tenant_id},
    )
    if (update_result.rowcount or 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    await db.commit()
    await _invalidate_config_cache(tenant_id)

    logger.info(
        "tenant_profile_selected",
        tenant_id=tenant_id,
        profile_id=request.profile_id,
        actor_id=current_user.id,
    )

    # Return the effective resolved profile
    effective = await _resolve_effective_profile(tenant_id, plan, db)
    return EffectiveProfileResponse(
        profile_id=effective["profile_id"],
        profile_name=effective["profile_name"],
        is_byollm=effective["is_byollm"],
        slots=effective["slots"],
    )


# ---------------------------------------------------------------------------
# V1/V2 combined GET /admin/llm-config
# ---------------------------------------------------------------------------


@router.get("/llm-config/library-options", response_model=list[LibraryOption])
async def list_llm_library_options(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    DEPRECATED: use GET /admin/llm-config/available-profiles instead.
    # DEPRECATED: remove in Phase D
    Preserved for frontend compat during Phase C transition.
    """
    result = await db.execute(
        text(
            "SELECT id, provider, model_name, display_name, plan_tier, "
            "is_recommended, pricing_per_1k_tokens_in, pricing_per_1k_tokens_out "
            "FROM llm_library "
            "WHERE status = 'published' "
            "ORDER BY is_recommended DESC, display_name ASC"
        )
    )
    rows = result.fetchall()
    return [
        LibraryOption(
            id=str(row[0]),
            provider=row[1],
            model_name=row[2],
            display_name=row[3],
            plan_tier=row[4],
            is_recommended=row[5],
            pricing_per_1k_tokens_in=float(row[6]) if row[6] is not None else None,
            pricing_per_1k_tokens_out=float(row[7]) if row[7] is not None else None,
        )
        for row in rows
    ]


@router.get("/llm-config", response_model=LLMConfigResponse)
async def get_llm_config(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Get current LLM config for this tenant.

    V2 (TODO-33 B6): Returns effective resolved profile data in addition to
    legacy model_source fields for backward compatibility.
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": current_user.tenant_id},
    )
    plan = getattr(current_user, "plan", "starter") or "starter"

    raw = await _get_llm_config_raw(current_user.tenant_id, db)
    llm_cfg = raw.get("llm_config", {})
    byollm_cfg = raw.get("byollm_key_ref", {})

    effective = await _resolve_effective_profile(current_user.tenant_id, plan, db)

    # Count available platform profiles for this tenant's plan (for upgrade nudge)
    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM llm_profiles "
            "WHERE owner_tenant_id IS NULL AND status = 'active' "
            "AND (plan_tiers = '{}' OR :plan = ANY(plan_tiers))"
        ),
        {"plan": plan},
    )
    available_count = count_result.scalar() or 0

    # Build SlotsPayload with all four slot keys always present
    slots_dict = effective["slots"]
    slots_payload = SlotsPayload(
        chat=SlotInfo(**slots_dict.get("chat", _NULL_SLOT)),
        intent=SlotInfo(**slots_dict.get("intent", _NULL_SLOT)),
        vision=SlotInfo(**slots_dict.get("vision", _NULL_SLOT)),
        agent=SlotInfo(**slots_dict.get("agent", _NULL_SLOT)),
    )

    return LLMConfigResponse(
        # V1 compat fields
        model_source=llm_cfg.get("model_source", "library"),
        llm_library_id=llm_cfg.get("llm_library_id"),
        byollm=BYOLLMStatus(
            provider=byollm_cfg.get("provider") if byollm_cfg else None,
            key_present=bool(byollm_cfg.get("encrypted_key_ref")) if byollm_cfg else False,
        ),
        # V2 profile fields
        profile_id=effective["profile_id"],
        profile_name=effective["profile_name"],
        description=effective.get("description"),
        plan_tier=plan,
        is_byollm=effective["is_byollm"],
        slots=slots_payload,
        available_profiles_count=int(available_count),
    )


# NOTE: PATCH /admin/llm-config is REMOVED in v2.
# # DEPRECATED: remove in Phase D
# Use POST /admin/llm-config/select-profile instead.


# ---------------------------------------------------------------------------
# PVDR-008: Tenant Provider Selection API (preserved from v1)
# ---------------------------------------------------------------------------


class ProviderOptionResponse(BaseModel):
    """An enabled platform provider available for tenant selection."""

    id: str
    provider_type: str
    display_name: str
    description: Optional[str] = None
    is_default: bool
    provider_status: str
    slots_available: list[str]

    model_config = {"protected_namespaces": ()}


class ProviderSelectionResponse(BaseModel):
    """Tenant's current provider selection."""

    provider_id: Optional[str] = None
    using_default: bool

    model_config = {"protected_namespaces": ()}


class UpdateProviderSelectionRequest(BaseModel):
    """PATCH /admin/llm-config/provider — set or clear provider selection."""

    provider_id: Optional[str] = Field(
        None,
        description="UUID of an enabled platform provider, or null to use default",
    )

    model_config = {"protected_namespaces": ()}


@router.get("/llm-config/providers", response_model=list[ProviderOptionResponse])
async def list_available_providers(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    PVDR-008: List enabled platform providers available for tenant selection.

    Returns enabled providers with slots_available derived from the models dict.
    No credentials are returned.
    """
    # Elevate to platform scope to read llm_providers (cross-tenant table).
    # Reset in finally to guarantee tenant scope is restored on the pooled connection.
    await db.execute(text("SELECT set_config('app.scope', 'platform', true)"))
    try:
        result = await db.execute(
            text(
                "SELECT id, provider_type, display_name, description, "
                "is_default, provider_status, models "
                "FROM llm_providers WHERE is_enabled = true "
                "ORDER BY is_default DESC, display_name ASC"
            )
        )
        rows = result.fetchall()
    finally:
        await db.execute(text("SELECT set_config('app.scope', 'tenant', true)"))

    import json as _json

    _AVAILABLE_SLOTS_PVDR = ["primary", "chat", "doc_embedding", "kb_embedding", "intent"]

    options = []
    for row in rows:
        models_raw = row[6]
        if isinstance(models_raw, str):
            models_dict = _json.loads(models_raw) if models_raw else {}
        elif isinstance(models_raw, dict):
            models_dict = models_raw
        else:
            models_dict = {}

        slots_available = [s for s in _AVAILABLE_SLOTS_PVDR if models_dict.get(s)]

        options.append(
            ProviderOptionResponse(
                id=str(row[0]),
                provider_type=row[1],
                display_name=row[2],
                description=row[3],
                is_default=row[4],
                provider_status=row[5],
                slots_available=slots_available,
            )
        )

    return options


@router.patch("/llm-config/provider", response_model=ProviderSelectionResponse)
async def update_provider_selection(
    request: UpdateProviderSelectionRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    PVDR-008: Set or clear tenant LLM provider selection.

    - provider_id: UUID of enabled provider → upsert selection
    - provider_id: null → delete selection (use platform default)
    - unknown provider_id → 404
    - disabled provider_id → 422
    """
    tenant_id = current_user.tenant_id

    if request.provider_id is not None:
        # Validate provider exists and is enabled.
        # Use try/finally to guarantee scope is reset to 'tenant' even if a
        # 404/422 exception escapes — without this, the pooled connection
        # would retain 'platform' scope for the next request.
        await db.execute(text("SELECT set_config('app.scope', 'platform', true)"))
        try:
            check_result = await db.execute(
                text("SELECT is_enabled FROM llm_providers WHERE id = :id"),
                {"id": request.provider_id},
            )
            provider_row_check = check_result.fetchone()
            if provider_row_check is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Provider not found",
                )
            if not provider_row_check[0]:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Provider is disabled and cannot be selected",
                )
        finally:
            # Reset RLS to tenant scope regardless of outcome.
            await db.execute(text("SELECT set_config('app.scope', 'tenant', true)"))
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        config_data = {"provider_id": request.provider_id}
        await db.execute(
            text(
                "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
                "VALUES (:id, :tid, 'llm_provider_selection', CAST(:data AS jsonb)) "
                "ON CONFLICT (tenant_id, config_type) DO UPDATE "
                "SET config_data = CAST(:data AS jsonb)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": tenant_id,
                "data": json.dumps(config_data),
            },
        )
        await db.commit()
        await _invalidate_config_cache(tenant_id)

        logger.info(
            "tenant_provider_selection_updated",
            tenant_id=tenant_id,
            provider_id=request.provider_id,
        )

        return ProviderSelectionResponse(
            provider_id=request.provider_id,
            using_default=False,
        )

    else:
        # Remove selection — use platform default
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        await db.execute(
            text(
                "DELETE FROM tenant_configs "
                "WHERE tenant_id = :tid AND config_type = 'llm_provider_selection'"
            ),
            {"tid": tenant_id},
        )
        await db.commit()
        await _invalidate_config_cache(tenant_id)

        logger.info(
            "tenant_provider_selection_cleared",
            tenant_id=tenant_id,
        )

        return ProviderSelectionResponse(
            provider_id=None,
            using_default=True,
        )
