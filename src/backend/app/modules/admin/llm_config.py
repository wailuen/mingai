"""
Tenant LLM Configuration API (P2LLM-006).

Endpoints (require tenant_admin):
    GET  /admin/llm-config   — returns current llm_config + byollm key presence
    PATCH /admin/llm-config  — set model_source (library/byollm) + llm_library_id

Config is stored in tenant_configs table under config_type='llm_config'.
After PATCH: Redis key mingai:{tenant_id}:config is DEL'd to bust cache.
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
    """DEL the tenant config Redis key after mutation.

    Key format matches TenantConfigService._redis_key():
    mingai:{tenant_id}:config:{key}
    """
    try:
        redis = get_redis()
        # Use raw key — not through CacheService type system (spec requirement).
        # Key must match TenantConfigService._redis_key(tenant_id, "llm_config").
        cache_key = f"mingai:{tenant_id}:config:llm_config"
        await redis.delete(cache_key)
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
