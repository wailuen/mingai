"""
INFRA-014: Cache warming background job.

Runs daily (triggered by the startup scheduler or an external cron). For each
active tenant that has had query activity in the past 7 days:
  1. Identify the top-100 user queries from the past 30 days.
  2. Pre-generate embeddings for each query so they are cached in Redis.
  3. Rate-limit embedding calls to 10 queries/second per tenant to avoid
     competing with peak traffic.
  4. Skip tenants with no activity in the past 7 days.
  5. Log per-tenant stats and total duration.

Embedding caching is handled inside EmbeddingService.embed() — this job
simply pre-calls it so the cache is warm before users arrive.

Intent cache warming is deferred to Phase 2 when the intent detection
pipeline (Stage 2 of the RAG pipeline) is fully implemented.
"""
import asyncio
import time

import structlog
from sqlalchemy import text

from app.core.session import async_session_factory
from app.modules.chat.embedding import EmbeddingService

logger = structlog.get_logger()

# Maximum number of top queries to warm per tenant
MAX_QUERIES_PER_TENANT = 100

# Minimum rate: 10 queries/second per tenant (0.1 second between calls)
_MIN_INTERVAL_SECS = 1.0 / 10.0


async def warm_embedding_cache() -> None:
    """
    Warm the embedding cache for all active tenants with recent query activity.

    Queries the messages table for top-100 most frequent user queries in the
    past 30 days per tenant. Skips tenants with zero queries in the past 7
    days (inactive). Calls EmbeddingService.embed() for each query which
    populates the Redis embedding cache automatically.

    Rate-limited to 10 embed calls/second per tenant. Never raises — per-tenant
    failures are logged and skipped so one broken tenant cannot block others.
    """
    start = time.monotonic()
    total_tenants = 0
    warmed_tenants = 0
    skipped_inactive = 0
    total_queries_warmed = 0
    embedding_errors = 0

    try:
        embedding_svc = EmbeddingService()
    except ValueError as exc:
        logger.error(
            "cache_warming_embedding_service_init_failed",
            error=str(exc),
            message="Cache warming skipped — EMBEDDING_MODEL or credentials not configured",
        )
        return

    async with async_session_factory() as session:
        # Step 1: get active tenants
        tenant_result = await session.execute(
            text("SELECT id FROM tenants WHERE status = 'active'")
        )
        tenant_rows = tenant_result.fetchall()
        total_tenants = len(tenant_rows)

        if total_tenants == 0:
            logger.info(
                "cache_warming_no_active_tenants",
                message="No active tenants; nothing to warm",
            )
            return

        for row in tenant_rows:
            tenant_id = row[0]
            tenant_start = time.monotonic()

            try:
                # Step 2: check recent activity (past 7 days)
                activity_result = await session.execute(
                    text(
                        "SELECT COUNT(*) FROM messages "
                        "WHERE tenant_id = :tenant_id "
                        "  AND role = 'user' "
                        "  AND created_at >= NOW() - INTERVAL '7 days'"
                    ),
                    {"tenant_id": tenant_id},
                )
                recent_count = activity_result.scalar() or 0

                if recent_count == 0:
                    skipped_inactive += 1
                    logger.info(
                        "cache_warming_tenant_skipped_inactive",
                        tenant_id=tenant_id,
                    )
                    continue

                # Step 3: fetch top-100 queries from past 30 days by frequency
                queries_result = await session.execute(
                    text(
                        "SELECT content "
                        "FROM messages "
                        "WHERE tenant_id = :tenant_id "
                        "  AND role = 'user' "
                        "  AND created_at >= NOW() - INTERVAL '30 days' "
                        "  AND content IS NOT NULL "
                        "  AND LENGTH(TRIM(content)) > 0 "
                        "GROUP BY content "
                        "ORDER BY COUNT(*) DESC "
                        "LIMIT :limit"
                    ),
                    {"tenant_id": tenant_id, "limit": MAX_QUERIES_PER_TENANT},
                )
                query_rows = queries_result.fetchall()

                queries = [r[0] for r in query_rows if r[0]]
                if not queries:
                    logger.info(
                        "cache_warming_tenant_no_queries",
                        tenant_id=tenant_id,
                    )
                    continue

                # Step 4: embed each query (rate-limited to 10/sec)
                warmed = 0
                errors = 0
                for i, query_text in enumerate(queries):
                    call_start = time.monotonic()

                    try:
                        await embedding_svc.embed(query_text, tenant_id=tenant_id)
                        warmed += 1
                    except Exception as embed_exc:
                        errors += 1
                        logger.warning(
                            "cache_warming_embed_failed",
                            tenant_id=tenant_id,
                            query_index=i,
                            error=str(embed_exc),
                        )

                    # Rate-limiting: ensure at least _MIN_INTERVAL_SECS between calls
                    elapsed = time.monotonic() - call_start
                    sleep_secs = _MIN_INTERVAL_SECS - elapsed
                    if sleep_secs > 0:
                        await asyncio.sleep(sleep_secs)

                tenant_elapsed_ms = round((time.monotonic() - tenant_start) * 1000, 1)
                total_queries_warmed += warmed
                embedding_errors += errors
                warmed_tenants += 1

                logger.info(
                    "cache_warming_tenant_complete",
                    tenant_id=tenant_id,
                    queries_warmed=warmed,
                    embed_errors=errors,
                    elapsed_ms=tenant_elapsed_ms,
                )

            except Exception as exc:
                logger.error(
                    "cache_warming_tenant_failed",
                    tenant_id=tenant_id,
                    error=str(exc),
                )

    total_elapsed_ms = round((time.monotonic() - start) * 1000, 1)

    logger.info(
        "cache_warming_complete",
        total_tenants=total_tenants,
        warmed_tenants=warmed_tenants,
        skipped_inactive=skipped_inactive,
        total_queries_warmed=total_queries_warmed,
        embedding_errors=embedding_errors,
        elapsed_ms=total_elapsed_ms,
    )
