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

import structlog
from sqlalchemy import text

from app.core.scheduler import DistributedJobLock, job_run_context, seconds_until_utc
from app.core.scheduler.tenant_throttle import run_tenants_throttled
from app.core.scheduler.timing import check_missed_job
from app.core.session import async_session_factory
from app.modules.chat.embedding import EmbeddingService

logger = structlog.get_logger()

# Maximum number of top queries to warm per tenant per run
_MAX_QUERIES_PER_TENANT = 100

# Minimum interval between embedding calls (0.1s → 10/sec max)
_RATE_LIMIT_INTERVAL_SECS = 0.1


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

    # SCHED-038: Run tenants concurrently, throttled by
    # SCHEDULER_MAX_CONCURRENT_TENANTS (default 5) to avoid saturating the
    # embedding API or the DB connection pool.
    results = await run_tenants_throttled(
        tenant_ids,
        coro_factory=lambda tid: warm_query_embeddings_for_tenant(tid, embedding_svc),
    )

    for tenant_id, result in zip(tenant_ids, results):
        if isinstance(result, Exception):
            total_errors += 1
            logger.error(
                "query_warming_tenant_failed",
                tenant_id=tenant_id,
                error=str(result),
            )
        else:
            total_warmed += result["warmed_count"]
            total_skipped += result["skipped_count"]
            total_errors += result["error_count"]

    job_elapsed_ms = round((time.monotonic() - job_start) * 1000, 1)

    logger.info(
        "query_warming_job_complete",
        tenant_count=tenant_count,
        total_warmed=total_warmed,
        total_skipped=total_skipped,
        total_errors=total_errors,
        duration_ms=job_elapsed_ms,
    )

    return total_warmed


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
            # SCHED-025: Missed-job recovery — runs immediately on the first
            # iteration if the 03:00 UTC slot passed today with no completed row.
            # On subsequent iterations check_missed_job returns False (row exists).
            async with async_session_factory() as _db:
                if await check_missed_job(
                    _db, "query_warming", scheduled_hour=3, scheduled_minute=0
                ):
                    async with DistributedJobLock("query_warming", ttl=3600) as _acquired:
                        if _acquired:
                            async with job_run_context("query_warming") as ctx:
                                _total_warmed = await run_query_warming_job()
                                ctx.records_processed = _total_warmed or 0
                            logger.info("query_warming_missed_job_recovered")

            sleep_secs = seconds_until_utc(3, 0)
            logger.debug(
                "query_warming_next_run_in",
                seconds=round(sleep_secs, 0),
            )
            await asyncio.sleep(sleep_secs)
            async with DistributedJobLock("query_warming", ttl=3600) as acquired:
                if not acquired:
                    logger.debug(
                        "query_warming_job_skipped",
                        reason="lock_held_by_another_pod",
                    )
                else:
                    async with job_run_context("query_warming") as ctx:
                        total_warmed = await run_query_warming_job()
                        ctx.records_processed = total_warmed or 0
        except asyncio.CancelledError:
            logger.info("query_warming_scheduler_cancelled")
            return
        except Exception as exc:
            # Never crash the scheduler loop — log and retry on next cycle
            logger.error(
                "query_warming_scheduler_loop_error",
                error=str(exc),
            )
