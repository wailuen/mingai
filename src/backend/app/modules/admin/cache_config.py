"""
CACHE-013: Admin semantic cache configuration endpoints.

Endpoints:
- GET  /admin/cache/semantic-config  — Return threshold and ttl_seconds
- PATCH /admin/cache/semantic-config — Update threshold and/or ttl_seconds

Configuration is stored in tenant_configs table under the key
'semantic_cache_config' via TenantConfigService.

Constraints:
- threshold: float in [0.85, 0.99] (too low causes garbage hits; too high
  disables cache effectively)
- ttl_seconds: int in [3600, 604800] (1h to 7 days)

Auth: require_tenant_admin
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.dependencies import CurrentUser, require_tenant_admin

logger = structlog.get_logger()

router = APIRouter(prefix="/admin/cache", tags=["admin", "cache"])

# Defaults when not configured
_DEFAULT_THRESHOLD = 0.92
_DEFAULT_TTL_SECONDS = 86400  # 24h


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SemanticCacheConfig(BaseModel):
    """Semantic cache configuration response."""

    threshold: float
    ttl_seconds: int


class PatchSemanticCacheConfigRequest(BaseModel):
    """PATCH /admin/cache/semantic-config request body."""

    threshold: Optional[float] = Field(
        None,
        ge=0.85,
        le=0.99,
        description="Cosine similarity threshold for cache hit (0.85–0.99)",
    )
    ttl_seconds: Optional[int] = Field(
        None,
        ge=3600,
        le=604800,
        description="Cache TTL in seconds (3600–604800)",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/semantic-config", response_model=SemanticCacheConfig)
async def get_semantic_cache_config(
    current_user: CurrentUser = Depends(require_tenant_admin),
):
    """
    CACHE-013: Return the tenant's semantic cache configuration.

    Returns defaults if no config has been set via PATCH.
    """
    from app.core.tenant_config_service import TenantConfigService

    svc = TenantConfigService()
    config = await svc.get(current_user.tenant_id, "semantic_cache_config") or {}

    threshold = float(config.get("threshold", _DEFAULT_THRESHOLD))
    ttl_seconds = int(config.get("ttl_seconds", _DEFAULT_TTL_SECONDS))

    logger.info(
        "semantic_cache_config_read",
        tenant_id=current_user.tenant_id,
        threshold=threshold,
        ttl_seconds=ttl_seconds,
    )

    return SemanticCacheConfig(threshold=threshold, ttl_seconds=ttl_seconds)


@router.patch("/semantic-config", response_model=SemanticCacheConfig)
async def patch_semantic_cache_config(
    body: PatchSemanticCacheConfigRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
):
    """
    CACHE-013: Update the tenant's semantic cache configuration.

    Only fields present in the request body are updated; others retain
    their current values. Both fields are optional in a PATCH.
    """
    from app.core.tenant_config_service import TenantConfigService

    if body.threshold is None and body.ttl_seconds is None:
        raise HTTPException(
            status_code=422,
            detail="At least one of 'threshold' or 'ttl_seconds' must be provided.",
        )

    svc = TenantConfigService()
    existing = await svc.get(current_user.tenant_id, "semantic_cache_config") or {}

    new_threshold = (
        body.threshold
        if body.threshold is not None
        else float(existing.get("threshold", _DEFAULT_THRESHOLD))
    )
    new_ttl = (
        body.ttl_seconds
        if body.ttl_seconds is not None
        else int(existing.get("ttl_seconds", _DEFAULT_TTL_SECONDS))
    )

    # Additional bounds check (Pydantic ge/le already handles this, but belt-and-suspenders)
    if not (0.85 <= new_threshold <= 0.99):
        raise HTTPException(
            status_code=422,
            detail="threshold must be between 0.85 and 0.99 inclusive.",
        )
    if not (3600 <= new_ttl <= 604800):
        raise HTTPException(
            status_code=422,
            detail="ttl_seconds must be between 3600 and 604800 inclusive.",
        )

    updated_config = {"threshold": new_threshold, "ttl_seconds": new_ttl}
    await svc.set(current_user.tenant_id, "semantic_cache_config", updated_config)

    logger.info(
        "semantic_cache_config_updated",
        tenant_id=current_user.tenant_id,
        threshold=new_threshold,
        ttl_seconds=new_ttl,
    )

    return SemanticCacheConfig(threshold=new_threshold, ttl_seconds=new_ttl)
