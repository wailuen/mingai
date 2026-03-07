"""
Platform cache analytics endpoints (API-106 to API-109).

Endpoints:
- GET  /platform/analytics/cache           — Overall cache hit/miss stats (API-106)
- GET  /platform/analytics/cache/by-index  — Per-index cache stats (API-107)
- GET  /platform/analytics/cache/savings   — Cost savings estimate (API-108)
- PATCH /platform/cache-ttl/{index_name}   — Update per-index TTL (API-109)

If the cache_analytics_events table does not exist yet the analytics endpoints
return a zeroed-out structure (graceful degradation) rather than a 500 error.
TTL overrides are stored in Redis under mingai:platform:cache_ttl:{index_name}.
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.redis_client import build_redis_key, get_redis
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/platform", tags=["platform-cache"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Cost model: approximate cost saved per cache hit (avoids one LLM call)
# Derived from median token cost across configured models — read from env in production.
_COST_PER_HIT_USD = 0.0004  # ~$0.0004 per avoided LLM call (conservative estimate)

# Approximate average latency reduction per cache hit (ms)
_AVG_LATENCY_REDUCTION_MS = 1200.0

# Platform tenant ID for Redis keys (no user data — platform-scoped)
_PLATFORM_REDIS_TENANT = "platform"

# Allowlist for valid period values
_VALID_PERIODS = {"7d", "30d"}

# Allowlist for index_name characters (alphanumeric + hyphen + underscore)
import re as _re

_VALID_INDEX_NAME_RE = _re.compile(r"^[A-Za-z0-9_-]{1,100}$")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UpdateCacheTTLRequest(BaseModel):
    ttl_hours: int = Field(..., ge=1, le=168, description="TTL in hours (1–168)")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _table_exists(table_name: str, db: AsyncSession) -> bool:
    """Check if a table exists in the public schema. Returns False on any error."""
    from sqlalchemy.exc import InterfaceError as SAInterfaceError

    try:
        result = await db.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = 'public' AND table_name = :table_name"
                ")"
            ),
            {"table_name": table_name},
        )
        return bool(result.scalar())
    except (ProgrammingError, SAInterfaceError, Exception) as exc:
        logger.warning(
            "table_exists_check_failed",
            table_name=table_name,
            error=str(exc),
        )
        return False


async def _fetch_cache_stats(period: str, db: AsyncSession) -> dict:
    """
    Query cache_analytics_events for overall hit/miss stats.

    Returns zeros if the table does not exist (graceful degradation).
    """
    if not await _table_exists("cache_analytics_events", db):
        logger.info("cache_analytics_events_table_missing_returning_zeros")
        return {"hit_rate": 0.0, "hits": 0, "misses": 0}

    # Use a hardcoded interval fragment — asyncpg cannot bind a string to
    # a bare INTERVAL literal, and the period value comes from a validated
    # allowlist so direct interpolation of the fragment is safe.
    interval_sql = "INTERVAL '7 days'" if period == "7d" else "INTERVAL '30 days'"
    try:
        result = await db.execute(
            text(
                "SELECT "
                "  COUNT(*) FILTER (WHERE event_type = 'hit') AS hits, "
                "  COUNT(*) FILTER (WHERE event_type = 'miss') AS misses "
                "FROM cache_analytics_events "
                f"WHERE created_at >= NOW() - {interval_sql}"
            )
        )
        row = result.one()
    except ProgrammingError:
        logger.warning("cache_analytics_query_failed_returning_zeros")
        return {"hit_rate": 0.0, "hits": 0, "misses": 0}

    hits = row.hits or 0
    misses = row.misses or 0
    total = hits + misses
    hit_rate = round(hits / total, 4) if total > 0 else 0.0
    return {"hit_rate": hit_rate, "hits": hits, "misses": misses}


async def _fetch_cache_stats_by_type(period: str, db: AsyncSession) -> list:
    """
    Query cache_analytics_events grouped by cache_type.

    Returns empty list if the table does not exist.
    """
    if not await _table_exists("cache_analytics_events", db):
        return []

    # Use a hardcoded interval fragment — period value is allowlist-validated.
    interval_sql = "INTERVAL '7 days'" if period == "7d" else "INTERVAL '30 days'"
    try:
        rows_result = await db.execute(
            text(
                "SELECT "
                "  cache_type, "
                "  COUNT(*) FILTER (WHERE event_type = 'hit') AS hits, "
                "  COUNT(*) FILTER (WHERE event_type = 'miss') AS misses "
                "FROM cache_analytics_events "
                f"WHERE created_at >= NOW() - {interval_sql} "
                "GROUP BY cache_type "
                "ORDER BY hits DESC"
            )
        )
    except ProgrammingError:
        logger.warning("cache_analytics_by_type_query_failed")
        return []

    items = []
    for row in rows_result.mappings():
        hits = row["hits"] or 0
        misses = row["misses"] or 0
        total = hits + misses
        hit_rate = round(hits / total, 4) if total > 0 else 0.0
        items.append(
            {
                "cache_type": row["cache_type"],
                "hit_rate": hit_rate,
                "hits": hits,
                "misses": misses,
            }
        )
    return items


async def _fetch_cache_stats_by_index(db: AsyncSession) -> list:
    """
    Query cache_analytics_events grouped by index_name.

    Returns empty list if the table does not exist or has no index_name column.
    """
    if not await _table_exists("cache_analytics_events", db):
        return []

    try:
        rows_result = await db.execute(
            text(
                "SELECT "
                "  index_name, "
                "  COUNT(*) FILTER (WHERE event_type = 'hit') AS hits, "
                "  COUNT(*) FILTER (WHERE event_type = 'miss') AS misses "
                "FROM cache_analytics_events "
                "WHERE index_name IS NOT NULL "
                "GROUP BY index_name "
                "ORDER BY hits DESC"
            )
        )
    except ProgrammingError:
        logger.warning("cache_analytics_by_index_query_failed")
        return []

    items = []
    redis = get_redis()
    for row in rows_result.mappings():
        hits = row["hits"] or 0
        misses = row["misses"] or 0
        total = hits + misses
        hit_rate = round(hits / total, 4) if total > 0 else 0.0

        index_name = row["index_name"]
        # Look up TTL override from Redis
        ttl_key = build_redis_key(_PLATFORM_REDIS_TENANT, "cache_ttl", index_name)
        ttl_raw = await redis.get(ttl_key)
        ttl_hours = int(ttl_raw) if ttl_raw is not None else 24  # default 24h

        items.append(
            {
                "index_name": index_name,
                "hit_rate": hit_rate,
                "hits": hits,
                "ttl_hours": ttl_hours,
            }
        )
    return items


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/analytics/cache")
async def get_cache_analytics(
    period: str = Query("30d", description="Period: 7d or 30d"),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-106: Overall cache analytics.

    Returns hit/miss counts, hit rate, and estimated cost saved for the period.
    Returns zeros if cache_analytics_events table is not yet populated.
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period '{period}'. Allowed: {sorted(_VALID_PERIODS)}",
        )

    overall = await _fetch_cache_stats(period=period, db=session)
    by_type = await _fetch_cache_stats_by_type(period=period, db=session)

    estimated_cost_saved = round(overall["hits"] * _COST_PER_HIT_USD, 4)

    logger.info(
        "cache_analytics_requested",
        user_id=current_user.id,
        period=period,
        hits=overall["hits"],
        misses=overall["misses"],
    )

    return {
        "period": period,
        "overall": {
            "hit_rate": overall["hit_rate"],
            "hits": overall["hits"],
            "misses": overall["misses"],
            "estimated_cost_saved_usd": estimated_cost_saved,
        },
        "by_type": by_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/analytics/cache/by-index")
async def get_cache_analytics_by_index(
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-107: Per-index cache analytics.

    Returns hit rates and TTL settings for each index.
    Returns empty list if cache_analytics_events is not yet populated.
    """
    indexes = await _fetch_cache_stats_by_index(db=session)

    logger.info(
        "cache_analytics_by_index_requested",
        user_id=current_user.id,
        index_count=len(indexes),
    )

    return {"indexes": indexes}


@router.get("/analytics/cache/savings")
async def get_cache_savings(
    period: str = Query("30d", description="Period: 7d or 30d"),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-108: Cache cost savings estimate.

    Returns estimated cost savings, tokens served from cache, and
    average latency reduction for the period.
    Returns zeros if no data is available.
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period '{period}'. Allowed: {sorted(_VALID_PERIODS)}",
        )

    overall = await _fetch_cache_stats(period=period, db=session)
    hits = overall["hits"]

    # Approximate tokens served from cache: 800 tokens per hit (median response)
    tokens_served = hits * 800
    estimated_cost_saved = round(hits * _COST_PER_HIT_USD, 4)
    avg_latency_reduction = _AVG_LATENCY_REDUCTION_MS if hits > 0 else 0.0

    logger.info(
        "cache_savings_requested",
        user_id=current_user.id,
        period=period,
        estimated_cost_saved_usd=estimated_cost_saved,
    )

    return {
        "period": period,
        "estimated_cost_saved_usd": estimated_cost_saved,
        "tokens_served_from_cache": tokens_served,
        "avg_latency_reduction_ms": avg_latency_reduction,
    }


@router.patch("/cache-ttl/{index_name}")
async def update_cache_ttl(
    index_name: str,
    body: UpdateCacheTTLRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """
    API-109: Update the cache TTL for a specific index.

    TTL is stored in Redis under mingai:platform:cache_ttl:{index_name}.
    Allowed range: 1–168 hours.
    """
    if not _VALID_INDEX_NAME_RE.match(index_name):
        raise HTTPException(
            status_code=422,
            detail=(
                "index_name must be 1–100 characters and contain only "
                "alphanumeric characters, hyphens, or underscores."
            ),
        )

    redis = get_redis()
    ttl_key = build_redis_key(_PLATFORM_REDIS_TENANT, "cache_ttl", index_name)

    # Store TTL value — no expiry on the key itself (TTL config is permanent until changed)
    await redis.set(ttl_key, str(body.ttl_hours))

    logger.info(
        "cache_ttl_updated",
        user_id=current_user.id,
        index_name=index_name,
        ttl_hours=body.ttl_hours,
    )

    return {
        "index_name": index_name,
        "ttl_hours": body.ttl_hours,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
