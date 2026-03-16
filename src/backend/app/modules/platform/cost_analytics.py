"""
Platform Cost Analytics API (P2LLM-012).

Endpoints (require platform admin):
    GET /platform/tenants/{id}/cost-usage
        ?period=7d|30d|90d  OR  ?from=date&to=date
        Returns: total tokens_in/out/cost + by-(provider,model) breakdown + daily

    GET /platform/cost-analytics/summary
        Cross-tenant cost aggregates sorted by cost_usd DESC

All queries use direct SQL against usage_events. Platform admin bypasses RLS
via app.user_role = 'platform_admin' setting.
"""
import re
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(tags=["platform-cost-analytics"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_PERIODS = frozenset({"7d", "30d", "90d"})

# ISO date pattern YYYY-MM-DD
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_period(
    period: Optional[str],
    from_date: Optional[str],
    to_date: Optional[str],
) -> tuple[datetime, datetime]:
    """
    Resolve query time window to (start_dt, end_dt) UTC datetimes.

    Priority: explicit from/to > period shorthand > default 30d.
    """
    now = datetime.now(timezone.utc)

    if from_date or to_date:
        if not from_date or not to_date:
            raise HTTPException(
                status_code=422,
                detail="Both 'from' and 'to' must be provided together.",
            )
        if not _DATE_RE.match(from_date) or not _DATE_RE.match(to_date):
            raise HTTPException(
                status_code=422,
                detail="'from' and 'to' must be ISO dates (YYYY-MM-DD).",
            )
        try:
            start_dt = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
            end_dt = datetime.fromisoformat(to_date).replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid date: {exc}") from exc
        if start_dt > end_dt:
            raise HTTPException(status_code=422, detail="'from' must be before 'to'.")
        return start_dt, end_dt

    days = 30
    if period:
        if period not in _VALID_PERIODS:
            raise HTTPException(
                status_code=422,
                detail=f"period must be one of {sorted(_VALID_PERIODS)}",
            )
        days = int(period.rstrip("d"))

    start_dt = now - timedelta(days=days)
    return start_dt, now


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/platform/tenants/{tenant_id}/cost-usage")
async def get_tenant_cost_usage(
    tenant_id: str,
    period: Optional[str] = Query(None, description="7d | 30d | 90d"),
    from_date: Optional[str] = Query(None, alias="from", description="YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, alias="to", description="YYYY-MM-DD"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Tenant cost and usage breakdown for a given time period (P2LLM-012).

    Returns:
        - totals: {tokens_in, tokens_out, cost_usd}
        - by_model: list of {provider, model, tokens_in, tokens_out, cost_usd}
        - daily: list of {date, tokens_in, tokens_out, cost_usd}
    """
    try:
        _uuid.UUID(tenant_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="tenant_id must be a valid UUID")
    start_dt, end_dt = _parse_period(period, from_date, to_date)

    # Set platform admin role for RLS bypass
    await db.execute(text("SELECT set_config('app.user_role', 'platform_admin', true)"))
    # cost_summary_daily RLS requires platform scope as well
    await db.execute(text("SELECT set_config('app.current_scope', 'platform', true)"))

    # Totals
    totals_result = await db.execute(
        text(
            "SELECT "
            "  COALESCE(SUM(tokens_in), 0) AS tokens_in, "
            "  COALESCE(SUM(tokens_out), 0) AS tokens_out, "
            "  SUM(cost_usd) AS cost_usd "
            "FROM usage_events "
            "WHERE tenant_id = :tid "
            "  AND created_at >= :start_dt "
            "  AND created_at <= :end_dt"
        ),
        {"tid": tenant_id, "start_dt": start_dt, "end_dt": end_dt},
    )
    totals_row = totals_result.fetchone()
    totals = {
        "tokens_in": int(totals_row[0]) if totals_row else 0,
        "tokens_out": int(totals_row[1]) if totals_row else 0,
        "cost_usd": float(totals_row[2])
        if totals_row and totals_row[2] is not None
        else None,
    }

    # By model breakdown
    model_result = await db.execute(
        text(
            "SELECT provider, model, "
            "  COALESCE(SUM(tokens_in), 0) AS tokens_in, "
            "  COALESCE(SUM(tokens_out), 0) AS tokens_out, "
            "  SUM(cost_usd) AS cost_usd "
            "FROM usage_events "
            "WHERE tenant_id = :tid "
            "  AND created_at >= :start_dt "
            "  AND created_at <= :end_dt "
            "GROUP BY provider, model "
            "ORDER BY SUM(cost_usd) DESC NULLS LAST"
        ),
        {"tid": tenant_id, "start_dt": start_dt, "end_dt": end_dt},
    )
    by_model = [
        {
            "provider": r[0],
            "model": r[1],
            "tokens_in": int(r[2]),
            "tokens_out": int(r[3]),
            "cost_usd": float(r[4]) if r[4] is not None else None,
        }
        for r in model_result.fetchall()
    ]

    # Daily breakdown
    daily_result = await db.execute(
        text(
            "SELECT DATE(created_at) AS day, "
            "  COALESCE(SUM(tokens_in), 0) AS tokens_in, "
            "  COALESCE(SUM(tokens_out), 0) AS tokens_out, "
            "  SUM(cost_usd) AS cost_usd "
            "FROM usage_events "
            "WHERE tenant_id = :tid "
            "  AND created_at >= :start_dt "
            "  AND created_at <= :end_dt "
            "GROUP BY DATE(created_at) "
            "ORDER BY DATE(created_at) ASC"
        ),
        {"tid": tenant_id, "start_dt": start_dt, "end_dt": end_dt},
    )
    daily = [
        {
            "date": str(r[0]),
            "tokens_in": int(r[1]),
            "tokens_out": int(r[2]),
            "cost_usd": float(r[3]) if r[3] is not None else None,
        }
        for r in daily_result.fetchall()
    ]

    # Gross margin + Azure cost estimation flags — fetch from cost_summary_daily.
    # The row is written by the nightly job and may not exist for very new tenants
    # or when the job has not yet run; in that case all fields default to None/True.
    margin_result = await db.execute(
        text(
            "SELECT gross_margin_pct, infra_is_estimated, MAX(infra_last_updated_at) "
            "FROM cost_summary_daily "
            "WHERE tenant_id = :tid "
            "GROUP BY gross_margin_pct, infra_is_estimated "
            "ORDER BY MAX(infra_last_updated_at) DESC NULLS LAST "
            "LIMIT 1"
        ),
        {"tid": tenant_id},
    )
    margin_row = margin_result.fetchone()
    gross_margin_pct: float | None = (
        float(margin_row[0]) if margin_row and margin_row[0] is not None else None
    )
    # infra_is_estimated defaults to True when no row exists (no Azure data available).
    infra_is_estimated: bool = (
        bool(margin_row[1]) if margin_row and margin_row[1] is not None else True
    )
    infra_last_updated_at: str | None = (
        margin_row[2].isoformat() if margin_row and margin_row[2] is not None else None
    )
    totals["gross_margin_pct"] = gross_margin_pct
    totals["infra_is_estimated"] = infra_is_estimated
    totals["infra_last_updated_at"] = infra_last_updated_at

    return {
        "tenant_id": tenant_id,
        "period": {
            "from": start_dt.isoformat(),
            "to": end_dt.isoformat(),
        },
        "totals": totals,
        "by_model": by_model,
        "daily": daily,
    }


@router.get("/platform/cost-analytics/summary")
async def get_cost_analytics_summary(
    period: Optional[str] = Query("30d", description="7d | 30d | 90d"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Cross-tenant cost aggregates, sorted by cost DESC.

    Returns a list of tenants with their total cost for the period.
    """
    start_dt, end_dt = _parse_period(period, None, None)

    # Set platform admin role for RLS bypass
    await db.execute(text("SELECT set_config('app.user_role', 'platform_admin', true)"))

    result = await db.execute(
        text(
            "SELECT ue.tenant_id, t.name AS tenant_name, "
            "  COALESCE(SUM(ue.tokens_in), 0) AS tokens_in, "
            "  COALESCE(SUM(ue.tokens_out), 0) AS tokens_out, "
            "  SUM(ue.cost_usd) AS cost_usd, "
            "  COUNT(*) AS call_count "
            "FROM usage_events ue "
            "LEFT JOIN tenants t ON t.id = ue.tenant_id "
            "WHERE ue.created_at >= :start_dt "
            "  AND ue.created_at <= :end_dt "
            "GROUP BY ue.tenant_id, t.name "
            "ORDER BY SUM(ue.cost_usd) DESC NULLS LAST"
        ),
        {"start_dt": start_dt, "end_dt": end_dt},
    )
    rows = result.fetchall()

    tenants = [
        {
            "tenant_id": str(r[0]),
            "tenant_name": r[1] or "Unknown",
            "tokens_in": int(r[2]),
            "tokens_out": int(r[3]),
            "cost_usd": float(r[4]) if r[4] is not None else None,
            "call_count": int(r[5]),
        }
        for r in rows
    ]

    return {
        "period": {
            "from": start_dt.isoformat(),
            "to": end_dt.isoformat(),
        },
        "tenants": tenants,
        "total_cost_usd": sum(t["cost_usd"] or 0 for t in tenants),
        "total_calls": sum(t["call_count"] for t in tenants),
    }
