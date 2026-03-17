"""
Tenant LLM Configuration API (P2LLM-006).

Endpoints (require tenant_admin):
    GET  /admin/llm-config                 — returns current llm_config + byollm key presence
    PATCH /admin/llm-config                — set model_source (library/byollm) + llm_library_id
    GET  /admin/llm-config/library-options — list Published llm_library entries available for
                                             assignment (excludes Deprecated) (PA-003/PA-004)

Config is stored in tenant_configs table under config_type='llm_config'.
After PATCH: Redis key mingai:{tenant_id}:config is DEL'd to bust cache (PA-003).
SLA: 60s propagation — DEL forces cache miss → re-read from PostgreSQL on next call.
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


class LLMConfigResponse(BaseModel):
    """Current tenant LLM configuration."""

    model_source: str  # "library" | "byollm"
    llm_library_id: Optional[str] = None
    byollm: BYOLLMStatus

    model_config = {"protected_namespaces": ()}


class UpdateLLMConfigRequest(BaseModel):
    model_source: str = Field(..., description="One of: library, byollm")
    llm_library_id: Optional[str] = Field(
        None,
        description="Required when model_source=library. UUID of a Published llm_library entry.",
    )

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

    Both keys are deleted because byollm mutations change byollm_key_ref
    and llm_config mutations change model_source — both affect routing.
    """
    try:
        redis = get_redis()
        llm_key = f"mingai:{tenant_id}:config:llm_config"
        byollm_key = f"mingai:{tenant_id}:config:byollm_key_ref"
        await redis.delete(llm_key, byollm_key)
        logger.debug("llm_config_cache_invalidated", tenant_id=tenant_id)
    except Exception as exc:
        # Non-blocking — cache miss is acceptable
        logger.warning(
            "llm_config_cache_invalidate_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/llm-config/library-options", response_model=list[LibraryOption])
async def list_llm_library_options(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    List Published llm_library entries available for tenant assignment (PA-003/PA-004).

    Excludes Deprecated entries — WHERE status = 'Published'.
    Ordered by is_recommended DESC then display_name ASC.
    """
    result = await db.execute(
        text(
            "SELECT id, provider, model_name, display_name, plan_tier, "
            "is_recommended, pricing_per_1k_tokens_in, pricing_per_1k_tokens_out "
            "FROM llm_library "
            "WHERE status = 'Published' "
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
    """Get current LLM config for this tenant (P2LLM-006)."""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": current_user.tenant_id},
    )

    raw = await _get_llm_config_raw(current_user.tenant_id, db)

    llm_cfg = raw.get("llm_config", {})
    byollm_cfg = raw.get("byollm_key_ref", {})

    return LLMConfigResponse(
        model_source=llm_cfg.get("model_source", "library"),
        llm_library_id=llm_cfg.get("llm_library_id"),
        byollm=BYOLLMStatus(
            provider=byollm_cfg.get("provider") if byollm_cfg else None,
            key_present=bool(byollm_cfg.get("encrypted_key_ref"))
            if byollm_cfg
            else False,
        ),
    )


@router.patch("/llm-config", response_model=LLMConfigResponse)
async def update_llm_config(
    request: UpdateLLMConfigRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Update LLM model source (P2LLM-006)."""
    if request.model_source not in _VALID_MODEL_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"model_source must be one of {sorted(_VALID_MODEL_SOURCES)}",
        )

    if request.model_source == "byollm":
        if current_user.plan != "enterprise":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="BYOLLM requires an enterprise plan.",
            )

    if request.model_source == "library":
        if not request.llm_library_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="llm_library_id is required when model_source=library",
            )
        # Validate the referenced entry is Published
        lib_result = await db.execute(
            text("SELECT status FROM llm_library WHERE id = :id"),
            {"id": request.llm_library_id},
        )
        lib_row = lib_result.fetchone()
        if lib_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="llm_library entry not found",
            )
        if lib_row[0] != "Published":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"llm_library entry is not Published (status: {lib_row[0]})",
            )

    config_data = {
        "model_source": request.model_source,
        "llm_library_id": request.llm_library_id,
    }

    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tid, 'llm_config', CAST(:data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) DO UPDATE SET config_data = CAST(:data AS jsonb)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": current_user.tenant_id,
            "data": json.dumps(config_data),
        },
    )
    await db.commit()

    await _invalidate_config_cache(current_user.tenant_id)

    logger.info(
        "llm_config_updated",
        tenant_id=current_user.tenant_id,
        model_source=request.model_source,
    )

    # Return current config
    raw = await _get_llm_config_raw(current_user.tenant_id, db)
    llm_cfg = raw.get("llm_config", {})
    byollm_cfg = raw.get("byollm_key_ref", {})

    return LLMConfigResponse(
        model_source=llm_cfg.get("model_source", "library"),
        llm_library_id=llm_cfg.get("llm_library_id"),
        byollm=BYOLLMStatus(
            provider=byollm_cfg.get("provider") if byollm_cfg else None,
            key_present=bool(byollm_cfg.get("encrypted_key_ref"))
            if byollm_cfg
            else False,
        ),
    )


# ---------------------------------------------------------------------------
# PVDR-008: Tenant Provider Selection API
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
    await db.execute(text("SELECT set_config('app.scope', 'platform', true)"))

    result = await db.execute(
        text(
            "SELECT id, provider_type, display_name, description, "
            "is_default, provider_status, models "
            "FROM llm_providers WHERE is_enabled = true "
            "ORDER BY is_default DESC, display_name ASC"
        )
    )
    rows = result.fetchall()

    import json as _json

    _AVAILABLE_SLOTS = ["primary", "chat", "doc_embedding", "kb_embedding", "intent"]

    options = []
    for row in rows:
        models_raw = row[6]
        if isinstance(models_raw, str):
            models_dict = _json.loads(models_raw) if models_raw else {}
        elif isinstance(models_raw, dict):
            models_dict = models_raw
        else:
            models_dict = {}

        slots_available = [s for s in _AVAILABLE_SLOTS if models_dict.get(s)]

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
        # Validate provider exists and is enabled
        await db.execute(text("SELECT set_config('app.scope', 'platform', true)"))
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

        # Reset RLS to tenant scope for tenant_configs write.
        # Both app.scope and app.tenant_id must be correct before the INSERT.
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
