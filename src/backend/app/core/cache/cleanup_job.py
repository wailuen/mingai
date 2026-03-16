"""
Semantic cache cleanup job (CACHE-014).

Runs hourly via asyncio background task (started in app/main.py lifespan).
Deletes expired entries from semantic_cache where expires_at < NOW().

Uses a platform-scope session (no tenant RLS) so it can clean across all
tenants in a single query — this is an internal maintenance task not a
user-facing operation.

Error handling: all exceptions are caught and logged — the job never
crashes the application.
"""
import asyncio

import structlog

logger = structlog.get_logger()

# Interval between cleanup runs (seconds)
_CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour


async def run_semantic_cache_cleanup_loop() -> None:
    """
    Infinite loop that runs the cleanup task every hour.

    Designed to be launched as an asyncio background task in main.py.
    Exits gracefully on CancelledError (shutdown signal).
    """
    logger.info(
        "semantic_cache_cleanup_started", interval_seconds=_CLEANUP_INTERVAL_SECONDS
    )
    while True:
        try:
            await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
            await _run_cleanup()
        except asyncio.CancelledError:
            logger.info("semantic_cache_cleanup_cancelled")
            return
        except Exception as exc:
            # Never crash the loop — log and continue
            logger.error(
                "semantic_cache_cleanup_loop_error",
                error=str(exc),
            )


async def _run_cleanup() -> None:
    """
    Execute one cleanup pass: delete all rows with expires_at < NOW().

    Logs per-tenant deletion counts for observability.
    """
    from app.core.session import async_session_factory
    from sqlalchemy import text

    try:
        async with async_session_factory() as session:
            # Count per-tenant before deleting (for logging)
            count_result = await session.execute(
                text(
                    "SELECT tenant_id, COUNT(*) AS cnt "
                    "FROM semantic_cache "
                    "WHERE expires_at < NOW() "
                    "GROUP BY tenant_id"
                )
            )
            per_tenant = {str(row[0]): row[1] for row in count_result.fetchall()}

            # Delete expired entries
            delete_result = await session.execute(
                text("DELETE FROM semantic_cache WHERE expires_at < NOW()")
            )
            deleted = delete_result.rowcount or 0
            await session.commit()

        if deleted > 0:
            logger.info(
                "semantic_cache_cleanup_completed",
                total_deleted=deleted,
                per_tenant=per_tenant,
            )
        else:
            logger.debug("semantic_cache_cleanup_no_expired_entries")

    except Exception as exc:
        logger.warning(
            "semantic_cache_cleanup_error",
            error=str(exc),
        )
