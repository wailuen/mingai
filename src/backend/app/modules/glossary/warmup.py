"""
INFRA-026: Glossary cache warm-up on startup.

Pre-populates Redis cache with glossary terms for all active tenants.
This avoids cold-cache latency on the first user query after a restart.

Cache key format: mingai:{tenant_id}:glossary_terms
TTL: 3600 seconds (matches expander.py GLOSSARY_CACHE_TTL_SECONDS)
"""
import json
import time

import structlog
from sqlalchemy import text

from app.core.redis_client import get_redis
from app.core.session import async_session_factory

logger = structlog.get_logger()

# Must match expander.py constants
GLOSSARY_CACHE_TTL_SECONDS = 3600
MAX_TERMS_PER_TENANT = 20


async def warm_up_glossary_cache() -> None:
    """
    Warm up glossary term cache for all active tenants.

    For each active tenant:
    1. Check if Redis cache key already exists (skip if warm)
    2. If cold: query PostgreSQL for glossary terms
    3. Cache result as JSON in Redis with TTL

    Individual tenant failures are logged and skipped -- they never
    block startup or affect other tenants.
    """
    start = time.monotonic()
    warmed = 0
    skipped = 0
    already_cached = 0
    total_tenants = 0

    redis = get_redis()

    async with async_session_factory() as session:
        # Step 1: Get all active tenant IDs
        result = await session.execute(
            text("SELECT id FROM tenants WHERE status = 'active'")
        )
        tenant_rows = result.fetchall()
        total_tenants = len(tenant_rows)

        if total_tenants == 0:
            logger.info(
                "glossary_warmup_no_tenants",
                message="No active tenants found; nothing to warm up",
            )

        # Step 2: Warm each tenant's glossary cache
        for row in tenant_rows:
            tenant_id = row[0]
            cache_key = f"mingai:{tenant_id}:glossary_terms"

            try:
                # Check if already cached
                exists = await redis.exists(cache_key)
                if exists:
                    already_cached += 1
                    logger.debug(
                        "glossary_warmup_cache_hit",
                        tenant_id=tenant_id,
                    )
                    continue

                # Cache miss -- query PostgreSQL for this tenant's terms
                terms_result = await session.execute(
                    text(
                        "SELECT term, full_form, aliases "
                        "FROM glossary_terms "
                        "WHERE tenant_id = :tenant_id "
                        "ORDER BY term ASC"
                    ),
                    {"tenant_id": tenant_id},
                )
                rows = terms_result.fetchall()

                terms = []
                for term_row in rows[:MAX_TERMS_PER_TENANT]:
                    aliases_raw = term_row[2]
                    if isinstance(aliases_raw, str):
                        aliases = json.loads(aliases_raw)
                    elif isinstance(aliases_raw, list):
                        aliases = aliases_raw
                    else:
                        aliases = []

                    terms.append(
                        {
                            "term": term_row[0],
                            "full_form": term_row[1],
                            "aliases": aliases,
                        }
                    )

                # Cache in Redis (even empty lists -- prevents repeated DB hits)
                await redis.setex(
                    cache_key,
                    GLOSSARY_CACHE_TTL_SECONDS,
                    json.dumps(terms),
                )

                warmed += 1
                logger.info(
                    "glossary_warmup_tenant_cached",
                    tenant_id=tenant_id,
                    term_count=len(terms),
                )

            except Exception as exc:
                skipped += 1
                logger.warning(
                    "glossary_warmup_tenant_failed",
                    tenant_id=tenant_id,
                    error=str(exc),
                )

    elapsed_ms = round((time.monotonic() - start) * 1000, 1)

    logger.info(
        "glossary_warmup_complete",
        total_tenants=total_tenants,
        warmed=warmed,
        skipped=skipped,
        already_cached=already_cached,
        elapsed_ms=elapsed_ms,
    )
