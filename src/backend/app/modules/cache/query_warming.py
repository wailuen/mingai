"""
CACHE-006: Query embedding warming job.

Scheduled daily at 03:00 UTC. Pre-generates embeddings for the top-100
most-queried queries (past 30 days) per tenant, sourced from
profile_learning_events.query_text.

Rate-limited: 0.1s sleep between embedding calls (10/sec max).
Skips if embedding already in Redis cache.
Runs tenants sequentially.

IMPORTANT: Do NOT modify app/modules/chat/cache_warming.py (INFRA-014).
This job is separate and targets profile_learning_events, not messages.
"""
import asyncio
import time
from datetime import datetime, timezone

import structlog
from sqlalchemy import text

from app.core.session import async_session_factory
from app.modules.chat.embedding import EmbeddingService

logger = structlog.get_logger()

# Maximum number of top queries to warm per tenant per run
_MAX_QUERIES_PER_TENANT = 100

# Minimum interval between embedding calls (0.1s → 10/sec max)
_RATE_LIMIT_INTERVAL_SECS = 0.1

# Target run time: 03:00 UTC
_SCHEDULE_HOUR_UTC = 3
_SCHEDULE_MINUTE_UTC = 0


async def warm_query_embeddings_for_tenant(
    tenant_id: str,
    embedding_svc: EmbeddingService,
) -> dict:
    """
    Pre-warm embedding cache for the top-100 queries of a single tenant.

    Queries profile_learning_events for the most frequent queries in the
    past 30 days. For each query, checks Redis for an existing embedding
    cache entry and skips if present, otherwise calls EmbeddingService.embed().

    Args:
        tenant_id:      Tenant UUID string.
        embedding_svc:  Initialized EmbeddingService instance (shared across tenants).

    Returns:
        Dict with keys: warmed_count, skipped_count, error_count, duration_ms.
    """
    from app.core.redis_client import get_redis

    start = time.monotonic()
    warmed = 0
    skipped = 0
    errors = 0

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT query_text, COUNT(*) AS freq "
                    "FROM profile_learning_events "
                    "WHERE tenant_id = :tid "
                    "  AND created_at > NOW() - INTERVAL '30 days' "
                    "  AND query_text IS NOT NULL "
                    "GROUP BY query_text "
                    "ORDER BY freq DESC "
                    "LIMIT :limit"
                ),
                {"tid": tenant_id, "limit": _MAX_QUERIES_PER_TENANT},
            )
            rows = result.fetchall()
    except Exception as exc:
        logger.warning(
            "query_warming_db_fetch_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "warmed_count": 0,
            "skipped_count": 0,
            "error_count": 1,
            "duration_ms": duration_ms,
        }

    queries = [row[0] for row in rows if row[0]]
    if not queries:
        logger.info(
            "query_warming_tenant_no_queries",
            tenant_id=tenant_id,
        )
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "warmed_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "duration_ms": duration_ms,
        }

    redis = get_redis()

    for query in queries:
        call_start = time.monotonic()

        try:
            # Build the cache key the same way EmbeddingService does
            cache_key = EmbeddingService._build_cache_key(
                tenant_id, query, embedding_svc._model
            )
            # Skip if already cached — avoids redundant API calls
            already_cached = await redis.exists(cache_key)
            if already_cached:
                skipped += 1
            else:
                await embedding_svc.embed(query, tenant_id=tenant_id)
                warmed += 1
        except Exception as exc:
            errors += 1
            logger.warning(
                "query_warming_embed_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )

        # Rate-limit: 0.1s minimum between calls → max 10/sec
        elapsed = time.monotonic() - call_start
        sleep_secs = _RATE_LIMIT_INTERVAL_SECS - elapsed
        if sleep_secs > 0:
            await asyncio.sleep(sleep_secs)

    duration_ms = round((time.monotonic() - start) * 1000, 1)

    logger.info(
        "query_warming_tenant_complete",
        tenant_id=tenant_id,
        warmed_count=warmed,
        skipped_count=skipped,
        error_count=errors,
        duration_ms=duration_ms,
    )

    return {
        "warmed_count": warmed,
        "skipped_count": skipped,
        "error_count": errors,
        "duration_ms": duration_ms,
    }


async def run_query_warming_job() -> None:
    """
    Execute one full query warming run across all active tenants.

    Fetches all active tenant IDs and runs warm_query_embeddings_for_tenant()
    sequentially. Per-tenant errors are logged and never stop the run.
    Never raises — catches all exceptions to protect the caller.
    """
    job_start = time.monotonic()
    total_warmed = 0
    total_skipped = 0
    total_errors = 0
    tenant_count = 0

    try:
        embedding_svc = EmbeddingService()
    except ValueError as exc:
        logger.error(
            "query_warming_embedding_service_init_failed",
            error=str(exc),
            hint="EMBEDDING_MODEL or credentials not configured — warming skipped",
        )
        return

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT id FROM tenants WHERE status = 'active'")
            )
            tenant_rows = result.fetchall()
    except Exception as exc:
        logger.error(
            "query_warming_tenant_fetch_failed",
            error=str(exc),
        )
        return

    tenant_ids = [str(row[0]) for row in tenant_rows]
    tenant_count = len(tenant_ids)

    if tenant_count == 0:
        logger.info("query_warming_no_active_tenants")
        return

    for tenant_id in tenant_ids:
        try:
            stats = await warm_query_embeddings_for_tenant(tenant_id, embedding_svc)
            total_warmed += stats["warmed_count"]
            total_skipped += stats["skipped_count"]
            total_errors += stats["error_count"]
        except Exception as exc:
            total_errors += 1
            logger.error(
                "query_warming_tenant_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )

    job_elapsed_ms = round((time.monotonic() - job_start) * 1000, 1)

    logger.info(
        "query_warming_job_complete",
        tenant_count=tenant_count,
        total_warmed=total_warmed,
        total_skipped=total_skipped,
        total_errors=total_errors,
        duration_ms=job_elapsed_ms,
    )


def _seconds_until_next_run() -> float:
    """
    Calculate seconds until the next 03:00 UTC trigger.

    Returns at least 60s (minimum jitter guard) to avoid edge-case
    double-fires on startup if the clock is very close to 03:00.
    """
    now = datetime.now(timezone.utc)
    next_run = now.replace(
        hour=_SCHEDULE_HOUR_UTC,
        minute=_SCHEDULE_MINUTE_UTC,
        second=0,
        microsecond=0,
    )
    if next_run <= now:
        # Already past today's 03:00 — schedule for tomorrow
        # Use timedelta to handle month/year rollover correctly
        from datetime import timedelta

        next_run = now.replace(
            hour=_SCHEDULE_HOUR_UTC,
            minute=_SCHEDULE_MINUTE_UTC,
            second=0,
            microsecond=0,
        ) + timedelta(days=1)

    delta = (next_run - now).total_seconds()
    return max(delta, 60.0)


async def run_query_warming_scheduler() -> None:
    """
    Infinite asyncio loop that fires run_query_warming_job() daily at 03:00 UTC.

    Designed to be launched as an asyncio background task via asyncio.create_task()
    in app/main.py lifespan. Exits gracefully on CancelledError.
    """
    logger.info(
        "query_warming_scheduler_started",
        schedule="daily at 03:00 UTC",
    )

    while True:
        try:
            sleep_secs = _seconds_until_next_run()
            logger.debug(
                "query_warming_next_run_in",
                seconds=round(sleep_secs, 0),
            )
            await asyncio.sleep(sleep_secs)
            await run_query_warming_job()
        except asyncio.CancelledError:
            logger.info("query_warming_scheduler_cancelled")
            return
        except Exception as exc:
            # Never crash the scheduler loop — log and retry on next cycle
            logger.error(
                "query_warming_scheduler_loop_error",
                error=str(exc),
            )
