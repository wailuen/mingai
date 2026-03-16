"""
PA-015: Cost Alert Thresholds API.

Endpoints:
- POST  /platform/tenants/{tenant_id}/cost-alerts  — Set per-tenant thresholds
- GET   /platform/tenants/{tenant_id}/cost-alerts  — Get per-tenant config (falls back to global)
- PATCH /platform/cost-alerts/defaults             — Set global default thresholds
- GET   /platform/cost-alerts/defaults             — Get global default config

All endpoints require platform_admin scope.
Thresholds are stored in cost_alert_configs (v019 migration).
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.session import get_async_session
from app.modules.tenants.routes import write_audit_log_db

logger = structlog.get_logger()

router = APIRouter(prefix="/platform", tags=["platform"])

# ---------------------------------------------------------------------------
# RLS context helper
# ---------------------------------------------------------------------------

_SET_PLATFORM_SCOPE = "SET LOCAL app.current_scope = 'platform'"
_SET_PLATFORM_ROLE = "SET LOCAL app.user_role = 'platform_admin'"


async def _set_platform_context(db: AsyncSession) -> None:
    """Set both RLS settings required for platform-scoped table access."""
    await db.execute(text(_SET_PLATFORM_SCOPE))
    await db.execute(text(_SET_PLATFORM_ROLE))


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CostAlertConfigRequest(BaseModel):
    """Body for setting cost alert thresholds."""

    daily_spend_threshold_usd: Optional[float] = Field(
        None,
        ge=0.0,
        description="Alert when daily spend exceeds this amount (USD). NULL = disabled.",
    )
    margin_floor_pct: Optional[float] = Field(
        None,
        ge=-100.0,
        le=100.0,
        description="Alert when gross margin drops below this percentage. NULL = disabled.",
    )


class CostAlertConfigResponse(BaseModel):
    """Cost alert config returned from GET endpoints."""

    id: Optional[str]
    tenant_id: Optional[str]
    daily_spend_threshold_usd: Optional[float]
    margin_floor_pct: Optional[float]
    is_global_default: bool
    created_at: Optional[str]
    updated_at: Optional[str]


# ---------------------------------------------------------------------------
# DB helpers (mockable in unit tests)
# ---------------------------------------------------------------------------


async def upsert_cost_alert_config_db(
    tenant_id: Optional[str],
    daily_spend_threshold_usd: Optional[float],
    margin_floor_pct: Optional[float],
    db: AsyncSession,
) -> dict:
    """
    Upsert a cost_alert_configs row for the given tenant_id (or NULL for global).

    ON CONFLICT on (tenant_id) updates the threshold fields and updated_at.
    Returns the upserted row as a dict.
    """
    config_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO cost_alert_configs
                (id, tenant_id, daily_spend_threshold_usd, margin_floor_pct)
            VALUES
                (:id, :tenant_id, :daily_spend, :margin_floor)
            ON CONFLICT (tenant_id) DO UPDATE SET
                daily_spend_threshold_usd = EXCLUDED.daily_spend_threshold_usd,
                margin_floor_pct          = EXCLUDED.margin_floor_pct,
                updated_at                = NOW()
            """
        ),
        {
            "id": config_id,
            "tenant_id": tenant_id,
            "daily_spend": daily_spend_threshold_usd,
            "margin_floor": margin_floor_pct,
        },
    )
    # NOTE: no commit here — caller commits after also writing the audit log,
    # ensuring upsert + audit log are atomic in one transaction.

    # Re-fetch to get actual stored values (handles NULL tenant_id uniqueness)
    result = await db.execute(
        text(
            "SELECT id, tenant_id, daily_spend_threshold_usd, margin_floor_pct, "
            "created_at, updated_at "
            "FROM cost_alert_configs "
            "WHERE tenant_id IS NOT DISTINCT FROM :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return {
            "id": config_id,
            "tenant_id": tenant_id,
            "daily_spend_threshold_usd": daily_spend_threshold_usd,
            "margin_floor_pct": margin_floor_pct,
            "created_at": None,
            "updated_at": None,
        }
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]) if row[1] is not None else None,
        "daily_spend_threshold_usd": float(row[2]) if row[2] is not None else None,
        "margin_floor_pct": float(row[3]) if row[3] is not None else None,
        "created_at": str(row[4]),
        "updated_at": str(row[5]),
    }


async def get_cost_alert_config_db(
    tenant_id: Optional[str],
    db: AsyncSession,
) -> Optional[dict]:
    """
    Fetch the cost_alert_configs row for the given tenant_id.

    tenant_id=None fetches the global default (WHERE tenant_id IS NULL).
    Returns None if no row found.
    """
    result = await db.execute(
        text(
            "SELECT id, tenant_id, daily_spend_threshold_usd, margin_floor_pct, "
            "created_at, updated_at "
            "FROM cost_alert_configs "
            "WHERE tenant_id IS NOT DISTINCT FROM :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]) if row[1] is not None else None,
        "daily_spend_threshold_usd": float(row[2]) if row[2] is not None else None,
        "margin_floor_pct": float(row[3]) if row[3] is not None else None,
        "created_at": str(row[4]),
        "updated_at": str(row[5]),
    }


async def get_tenant_exists_db(tenant_id: str, db: AsyncSession) -> bool:
    """Return True if tenant with given id exists (active status not required)."""
    result = await db.execute(
        text("SELECT 1 FROM tenants WHERE id = :tid LIMIT 1"),
        {"tid": tenant_id},
    )
    return result.fetchone() is not None


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("/tenants/{tenant_id}/cost-alerts", status_code=status.HTTP_200_OK)
async def set_tenant_cost_alerts(
    tenant_id: str = Path(
        ..., description="Tenant UUID", pattern=r"^[0-9a-fA-F-]{36}$"
    ),
    body: CostAlertConfigRequest = ...,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> CostAlertConfigResponse:
    """
    Set (upsert) cost alert thresholds for a specific tenant.

    Requires platform_admin scope.
    """
    await _set_platform_context(db)

    # Verify tenant exists
    exists = await get_tenant_exists_db(tenant_id, db)
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found.",
        )

    row = await upsert_cost_alert_config_db(
        tenant_id=tenant_id,
        daily_spend_threshold_usd=body.daily_spend_threshold_usd,
        margin_floor_pct=body.margin_floor_pct,
        db=db,
    )

    await write_audit_log_db(
        tenant_id=tenant_id,
        actor_user_id=current_user.id,
        action="set_cost_alert_config",
        resource_type="cost_alert_config",
        resource_id=tenant_id,
        details={
            "daily_spend_threshold_usd": body.daily_spend_threshold_usd,
            "margin_floor_pct": body.margin_floor_pct,
        },
        db=db,
    )
    await db.commit()

    logger.info(
        "cost_alert_config_set",
        actor_user_id=current_user.id,
        tenant_id=tenant_id,
        daily_spend_threshold_usd=body.daily_spend_threshold_usd,
        margin_floor_pct=body.margin_floor_pct,
    )

    return CostAlertConfigResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        daily_spend_threshold_usd=row["daily_spend_threshold_usd"],
        margin_floor_pct=row["margin_floor_pct"],
        is_global_default=False,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/tenants/{tenant_id}/cost-alerts", status_code=status.HTTP_200_OK)
async def get_tenant_cost_alerts(
    tenant_id: str = Path(
        ..., description="Tenant UUID", pattern=r"^[0-9a-fA-F-]{36}$"
    ),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> CostAlertConfigResponse:
    """
    Get cost alert config for a specific tenant.

    Falls back to the global default if no per-tenant config is set.
    Returns 404 if neither per-tenant nor global default config exists.
    Requires platform_admin scope.
    """
    await _set_platform_context(db)

    # Verify tenant exists
    exists = await get_tenant_exists_db(tenant_id, db)
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found.",
        )

    # Try per-tenant config first
    row = await get_cost_alert_config_db(tenant_id, db)
    if row is not None:
        return CostAlertConfigResponse(
            id=row["id"],
            tenant_id=row["tenant_id"],
            daily_spend_threshold_usd=row["daily_spend_threshold_usd"],
            margin_floor_pct=row["margin_floor_pct"],
            is_global_default=False,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # Fall back to global default
    global_row = await get_cost_alert_config_db(None, db)
    if global_row is not None:
        return CostAlertConfigResponse(
            id=global_row["id"],
            tenant_id=None,
            daily_spend_threshold_usd=global_row["daily_spend_threshold_usd"],
            margin_floor_pct=global_row["margin_floor_pct"],
            is_global_default=True,
            created_at=global_row["created_at"],
            updated_at=global_row["updated_at"],
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No cost alert configuration found for this tenant or globally.",
    )


@router.patch("/cost-alerts/defaults", status_code=status.HTTP_200_OK)
async def set_global_cost_alert_defaults(
    body: CostAlertConfigRequest = ...,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> CostAlertConfigResponse:
    """
    Set (upsert) global default cost alert thresholds.

    The global default applies to tenants that have no per-tenant config.
    Requires platform_admin scope.
    """
    await _set_platform_context(db)

    row = await upsert_cost_alert_config_db(
        tenant_id=None,
        daily_spend_threshold_usd=body.daily_spend_threshold_usd,
        margin_floor_pct=body.margin_floor_pct,
        db=db,
    )

    # Use the platform sentinel tenant_id for audit log (global config has no tenant)
    platform_tid = "00000000-0000-0000-0000-000000000000"
    await write_audit_log_db(
        tenant_id=platform_tid,
        actor_user_id=current_user.id,
        action="set_global_cost_alert_defaults",
        resource_type="cost_alert_config",
        resource_id=platform_tid,
        details={
            "daily_spend_threshold_usd": body.daily_spend_threshold_usd,
            "margin_floor_pct": body.margin_floor_pct,
        },
        db=db,
    )
    await db.commit()

    logger.info(
        "global_cost_alert_defaults_set",
        actor_user_id=current_user.id,
        daily_spend_threshold_usd=body.daily_spend_threshold_usd,
        margin_floor_pct=body.margin_floor_pct,
    )

    return CostAlertConfigResponse(
        id=row["id"],
        tenant_id=None,
        daily_spend_threshold_usd=row["daily_spend_threshold_usd"],
        margin_floor_pct=row["margin_floor_pct"],
        is_global_default=True,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/cost-alerts/defaults", status_code=status.HTTP_200_OK)
async def get_global_cost_alert_defaults(
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> CostAlertConfigResponse:
    """
    Get the global default cost alert thresholds.

    Returns 404 if no global default has been configured yet.
    Requires platform_admin scope.
    """
    await _set_platform_context(db)

    row = await get_cost_alert_config_db(None, db)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No global cost alert default configured.",
        )

    return CostAlertConfigResponse(
        id=row["id"],
        tenant_id=None,
        daily_spend_threshold_usd=row["daily_spend_threshold_usd"],
        margin_floor_pct=row["margin_floor_pct"],
        is_global_default=True,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
