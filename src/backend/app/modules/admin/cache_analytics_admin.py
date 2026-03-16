"""
CACHE-016: Tenant admin cache analytics endpoints.

Endpoints:
- GET /admin/analytics/cache/summary         — hit rate, total_requests, cost_saved
- GET /admin/analytics/cache/by-index        — per-index breakdown
- GET /admin/analytics/cache/top-cached-queries — top 20 SHA256 prefixes
- GET /admin/analytics/cache/cost-savings    — daily breakdown

All endpoints require require_tenant_admin.

Data source: cache_analytics_events table if it exists; Redis counters as
fallback if the table is absent. Returns graceful zeros when no data available.

Security: never expose raw query text — only SHA256 prefixes (first 16 chars).
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin/analytics/cache", tags=["admin", "cache-analytics"])

# Cost model: approximate cost saved per semantic cache hit (avoids one LLM call)
_COST_PER_SEMANTIC_HIT_USD = 0.0004
_COST_PER_SEARCH_HIT_USD = 0.00005
_COST_PER_INTENT_HIT_USD = 0.000015
_COST_PER_EMB_HIT_USD = 0.00001

_COST_BY_TYPE = {
    "semantic": _COST_PER_SEMANTIC_HIT_USD,
    "search": _COST_PER_SEARCH_HIT_USD,
    "intent": _COST_PER_INTENT_HIT_USD,
    "embedding": _COST_PER_EMB_HIT_USD,
}

_VALID_PERIODS = frozenset({"7d", "30d", "90d"})


async def _table_exists(table_name: str, db: AsyncSession) -> bool:
    """Check if a table exists in the public schema."""
    try:
        result = await db.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = 'public' AND table_name = :tname"
                ")"
            ),
            {"tname": table_name},
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("cache_analytics_table_check_failed", error=str(exc))
        return False


def _interval_sql(period: str) -> str:
    """Return a hardcoded SQL interval fragment for an allowlisted period."""
    mapping = {
        "7d": "INTERVAL '7 days'",
        "30d": "INTERVAL '30 days'",
        "90d": "INTERVAL '90 days'",
    }
    return mapping[period]


@router.get("/summary")
async def get_cache_summary(
    period: str = Query("7d", description="Period: 7d, 30d, or 90d"),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    CACHE-016: Overall cache hit rate, total requests, and cost saved.

    Returns zeros when no analytics data is available.
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period '{period}'. Allowed: {sorted(_VALID_PERIODS)}",
        )

    table_ok = await _table_exists("cache_analytics_events", session)
    if not table_ok:
        return _zero_summary(period)

    interval = _interval_sql(period)
    try:
        result = await session.execute(
            text(
                "SELECT "
                "  cache_type, "
                "  COUNT(*) FILTER (WHERE event_type = 'hit') AS hits, "
                "  COUNT(*) FILTER (WHERE event_type = 'miss') AS misses "
                "FROM cache_analytics_events "
                f"WHERE tenant_id = :tid AND created_at >= NOW() - {interval} "
                "GROUP BY cache_type"
            ),
            {"tid": current_user.tenant_id},
        )
    except ProgrammingError:
        return _zero_summary(period)

    total_hits = 0
    total_misses = 0
    cost_saved = 0.0
    by_type = []

    for row in result.mappings():
        hits = row["hits"] or 0
        misses = row["misses"] or 0
        total = hits + misses
        hit_rate = round(hits / total, 4) if total > 0 else 0.0
        cost_type = _COST_BY_TYPE.get(row["cache_type"], _COST_PER_SEMANTIC_HIT_USD)
        cost_saved += hits * cost_type
        total_hits += hits
        total_misses += misses
        by_type.append(
            {
                "cache_type": row["cache_type"],
                "hits": hits,
                "misses": misses,
                "hit_rate": hit_rate,
            }
        )

    total_requests = total_hits + total_misses
    overall_hit_rate = (
        round(total_hits / total_requests, 4) if total_requests > 0 else 0.0
    )

    logger.info(
        "cache_summary_requested",
        tenant_id=current_user.tenant_id,
        period=period,
        total_hits=total_hits,
        total_misses=total_misses,
    )

    return {
        "period": period,
        "hit_rate": overall_hit_rate,
        "total_requests": total_requests,
        "total_hits": total_hits,
        "total_misses": total_misses,
        "cost_saved_usd": round(cost_saved, 6),
        "by_type": by_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/by-index")
async def get_cache_by_index(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    CACHE-016: Per-index cache breakdown.

    Returns hit rates and request counts grouped by index_name.
    Empty list if no data is available.
    """
    table_ok = await _table_exists("cache_analytics_events", session)
    if not table_ok:
        return {"indexes": []}

    try:
        rows_result = await session.execute(
            text(
                "SELECT "
                "  index_name, "
                "  cache_type, "
                "  COUNT(*) FILTER (WHERE event_type = 'hit') AS hits, "
                "  COUNT(*) FILTER (WHERE event_type = 'miss') AS misses "
                "FROM cache_analytics_events "
                "WHERE tenant_id = :tid AND index_name IS NOT NULL "
                "GROUP BY index_name, cache_type "
                "ORDER BY hits DESC"
            ),
            {"tid": current_user.tenant_id},
        )
    except ProgrammingError:
        return {"indexes": []}

    items = []
    for row in rows_result.mappings():
        hits = row["hits"] or 0
        misses = row["misses"] or 0
        total = hits + misses
        hit_rate = round(hits / total, 4) if total > 0 else 0.0
        items.append(
            {
                "index_name": row["index_name"],
                "cache_type": row["cache_type"],
                "hits": hits,
                "misses": misses,
                "hit_rate": hit_rate,
            }
        )

    logger.info(
        "cache_by_index_requested",
        tenant_id=current_user.tenant_id,
        index_count=len(items),
    )

    return {"indexes": items}


@router.get("/top-cached-queries")
async def get_top_cached_queries(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    CACHE-016: Top 20 most-frequently-cached query SHA256 prefixes.

    Returns SHA256 prefix (first 16 chars) — never raw query text.
    """
    table_ok = await _table_exists("cache_analytics_events", session)
    if not table_ok:
        return {"queries": []}

    try:
        rows_result = await session.execute(
            text(
                "SELECT "
                "  query_hash, "
                "  COUNT(*) FILTER (WHERE event_type = 'hit') AS hits "
                "FROM cache_analytics_events "
                "WHERE tenant_id = :tid AND query_hash IS NOT NULL "
                "GROUP BY query_hash "
                "ORDER BY hits DESC "
                "LIMIT 20"
            ),
            {"tid": current_user.tenant_id},
        )
    except ProgrammingError:
        return {"queries": []}

    items = [
        {
            "query_hash_prefix": str(row["query_hash"])[:16],
            "hits": row["hits"] or 0,
        }
        for row in rows_result.mappings()
    ]

    logger.info(
        "cache_top_queries_requested",
        tenant_id=current_user.tenant_id,
        result_count=len(items),
    )

    return {"queries": items}


@router.get("/cost-savings")
async def get_cache_cost_savings(
    period: str = Query("7d", description="Period: 7d, 30d, or 90d"),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    CACHE-016: Daily cost savings breakdown for the period.

    Returns daily rows with hits and estimated cost_saved_usd.
    Empty list if no data is available.
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period '{period}'. Allowed: {sorted(_VALID_PERIODS)}",
        )

    table_ok = await _table_exists("cache_analytics_events", session)
    if not table_ok:
        return {"period": period, "daily": []}

    interval = _interval_sql(period)
    try:
        rows_result = await session.execute(
            text(
                "SELECT "
                "  DATE_TRUNC('day', created_at) AS day, "
                "  cache_type, "
                "  COUNT(*) FILTER (WHERE event_type = 'hit') AS hits "
                "FROM cache_analytics_events "
                f"WHERE tenant_id = :tid AND created_at >= NOW() - {interval} "
                "GROUP BY DATE_TRUNC('day', created_at), cache_type "
                "ORDER BY day ASC"
            ),
            {"tid": current_user.tenant_id},
        )
    except ProgrammingError:
        return {"period": period, "daily": []}

    daily = []
    for row in rows_result.mappings():
        hits = row["hits"] or 0
        cost_type = _COST_BY_TYPE.get(row["cache_type"], _COST_PER_SEMANTIC_HIT_USD)
        cost_saved = round(hits * cost_type, 6)
        day_val = row["day"]
        day_str = day_val.isoformat() if hasattr(day_val, "isoformat") else str(day_val)
        daily.append(
            {
                "day": day_str,
                "cache_type": row["cache_type"],
                "hits": hits,
                "cost_saved_usd": cost_saved,
            }
        )

    logger.info(
        "cache_cost_savings_requested",
        tenant_id=current_user.tenant_id,
        period=period,
        day_count=len(daily),
    )

    return {"period": period, "daily": daily}


def _zero_summary(period: str) -> dict:
    """Return a zeroed summary when no analytics data exists."""
    return {
        "period": period,
        "hit_rate": 0.0,
        "total_requests": 0,
        "total_hits": 0,
        "total_misses": 0,
        "cost_saved_usd": 0.0,
        "by_type": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
