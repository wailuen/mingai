"""
CACHE-005: Per-index cache TTL configuration API.

Endpoints:
- GET  /admin/indexes/{index_id}/cache-config  — returns current TTL
- PATCH /admin/indexes/{index_id}/cache-config  — sets TTL with plan tier enforcement

Valid TTL values: {0, 900, 1800, 3600, 14400, 28800, 86400} seconds.
Plan tier limits:
- starter/professional: max 3600s
- enterprise: max 86400s

Storage: TenantConfigService.set(tenant_id, f"index_cache_ttl.{index_id}", ttl_seconds).
GET returns: {"index_id": ..., "ttl_seconds": 3600} — default 3600 if not configured.

Validation:
- ttl_seconds must be in the allowed set
- Plan tier check: if plan in (starter, professional) and ttl_seconds > 3600 → 403
- index_id sanitization: must match ^[a-zA-Z0-9_-]{1,100}$ to prevent injection in key
"""
import re

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from app.core.dependencies import CurrentUser, require_tenant_admin

logger = structlog.get_logger()

router = APIRouter(
    prefix="/admin/indexes",
    tags=["admin", "cache"],
)

# Allowed TTL values (seconds)
_VALID_TTL_VALUES: frozenset[int] = frozenset({0, 900, 1800, 3600, 14400, 28800, 86400})

# Maximum TTL per plan tier (seconds)
_PLAN_TTL_LIMITS: dict[str, int] = {
    "starter": 3600,
    "professional": 3600,
    "enterprise": 86400,
}

# Default TTL when not configured
_DEFAULT_INDEX_CACHE_TTL = 3600

# Allowed index_id pattern — prevents colon injection into Redis key
_INDEX_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class IndexCacheConfig(BaseModel):
    """Per-index cache TTL configuration response."""

    index_id: str
    ttl_seconds: int


class PatchIndexCacheConfigRequest(BaseModel):
    """PATCH /admin/indexes/{index_id}/cache-config request body."""

    ttl_seconds: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{index_id}/cache-config", response_model=IndexCacheConfig)
async def get_index_cache_config(
    index_id: str = Path(
        ...,
        description="Index identifier. Alphanumeric, hyphens, and underscores only.",
    ),
    current_user: CurrentUser = Depends(require_tenant_admin),
) -> IndexCacheConfig:
    """
    CACHE-005: Return the per-index cache TTL for the authenticated tenant.

    Returns default of 3600s if no TTL has been configured for this index.
    """
    if not _INDEX_ID_RE.match(index_id):
        raise HTTPException(
            status_code=422,
            detail=(
                "index_id must contain only alphanumeric characters, hyphens, "
                "or underscores and be 1–100 characters long."
            ),
        )

    from app.core.tenant_config_service import TenantConfigService

    svc = TenantConfigService()
    # Key uses a dot separator — TenantConfigService validates no colons in key
    config_key = f"index_cache_ttl.{index_id}"
    stored = await svc.get(current_user.tenant_id, config_key)
    ttl_seconds = int(stored) if stored is not None else _DEFAULT_INDEX_CACHE_TTL

    logger.info(
        "index_cache_config_read",
        tenant_id=current_user.tenant_id,
        index_id=index_id,
        ttl_seconds=ttl_seconds,
    )

    return IndexCacheConfig(index_id=index_id, ttl_seconds=ttl_seconds)


@router.patch("/{index_id}/cache-config", response_model=IndexCacheConfig)
async def patch_index_cache_config(
    body: PatchIndexCacheConfigRequest,
    index_id: str = Path(
        ...,
        description="Index identifier. Alphanumeric, hyphens, and underscores only.",
    ),
    current_user: CurrentUser = Depends(require_tenant_admin),
) -> IndexCacheConfig:
    """
    CACHE-005: Set the per-index cache TTL for the authenticated tenant.

    Enforces:
    - ttl_seconds must be one of the allowed values
    - starter/professional plans: ttl_seconds ≤ 3600
    - enterprise plans: ttl_seconds ≤ 86400
    """
    if not _INDEX_ID_RE.match(index_id):
        raise HTTPException(
            status_code=422,
            detail=(
                "index_id must contain only alphanumeric characters, hyphens, "
                "or underscores and be 1–100 characters long."
            ),
        )

    if body.ttl_seconds not in _VALID_TTL_VALUES:
        raise HTTPException(
            status_code=422,
            detail=(f"ttl_seconds must be one of {sorted(_VALID_TTL_VALUES)}."),
        )

    # Plan tier enforcement
    plan = current_user.plan or "professional"
    if plan not in _PLAN_TTL_LIMITS:
        logger.warning(
            "index_cache_config_unknown_plan",
            plan=plan,
            tenant_id=current_user.tenant_id,
            fallback_max=3600,
        )
    plan_max = _PLAN_TTL_LIMITS.get(plan, 3600)
    if body.ttl_seconds > plan_max:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Your plan does not allow a TTL greater than {plan_max}s. "
                "Upgrade to enterprise for higher TTL values."
            ),
        )

    from app.core.tenant_config_service import TenantConfigService

    svc = TenantConfigService()
    config_key = f"index_cache_ttl.{index_id}"
    await svc.set(current_user.tenant_id, config_key, body.ttl_seconds)

    logger.info(
        "index_cache_config_updated",
        tenant_id=current_user.tenant_id,
        index_id=index_id,
        ttl_seconds=body.ttl_seconds,
        plan=plan,
    )

    return IndexCacheConfig(index_id=index_id, ttl_seconds=body.ttl_seconds)
