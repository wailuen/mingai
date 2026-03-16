"""
CACHE-015: Cache metrics collection helper.

Provides emit_cache_event() — a fire-and-forget function that inserts a row
into cache_analytics_events for each cache hit or miss.

Called from the chat orchestrator after semantic cache lookup.

Cost model (approximate, conservative estimates):
  semantic  — $0.0004 per avoided LLM call
  search    — $0.00005 per avoided vector search API call
  intent    — $0.000015 per avoided intent classification
  embedding — $0.00001 per avoided embedding API call

Never raises — all errors are logged. The event emission path must never
slow or block the chat response pipeline.
"""
import asyncio
import hashlib

import structlog

logger = structlog.get_logger()

# Cost model per cache type (USD per hit)
_COST_PER_HIT: dict[str, float] = {
    "semantic": 0.0004,
    "search": 0.00005,
    "intent": 0.000015,
    "embedding": 0.00001,
}

_VALID_CACHE_EVENT_TYPES = frozenset({"semantic", "search", "intent", "embedding"})


def emit_cache_event(
    tenant_id: str,
    cache_type: str,
    hit: bool,
    query: str | None = None,
    index_name: str | None = None,
) -> None:
    """
    Fire-and-forget: insert one cache analytics event row.

    Must be called from an async context. Uses asyncio.create_task() so it
    never blocks the caller.

    Args:
        tenant_id:   Tenant UUID.
        cache_type:  One of 'semantic', 'search', 'intent', 'embedding'.
        hit:         True for cache hit, False for miss.
        query:       Optional raw query string — hashed before storage (never
                     raw text stored in the DB).
        index_name:  Optional index identifier (for search tier).
    """
    if cache_type not in _VALID_CACHE_EVENT_TYPES:
        # Silently skip unknown types — do not error in analytics path
        return

    asyncio.create_task(
        _insert_event(
            tenant_id=tenant_id,
            cache_type=cache_type,
            hit=hit,
            query=query,
            index_name=index_name,
        )
    )


async def _insert_event(
    tenant_id: str,
    cache_type: str,
    hit: bool,
    query: str | None,
    index_name: str | None,
) -> None:
    """Background task: insert one cache_analytics_events row."""
    from app.core.session import async_session_factory
    from sqlalchemy import text

    event_type = "hit" if hit else "miss"
    cost_saved = _COST_PER_HIT.get(cache_type, 0.0) if hit else None

    # Hash the query — we store first 16 chars of SHA256 (not raw text)
    query_hash: str | None = None
    if query:
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]

    try:
        async with async_session_factory() as session:
            # Set RLS context — analytics events are tenant-scoped
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": tenant_id},
            )
            await session.execute(
                text(
                    "INSERT INTO cache_analytics_events "
                    "(tenant_id, cache_type, event_type, index_name, query_hash, cost_saved_usd) "
                    "VALUES (:tid, :cache_type, :event_type, :index_name, :query_hash, :cost_saved)"
                ),
                {
                    "tid": tenant_id,
                    "cache_type": cache_type,
                    "event_type": event_type,
                    "index_name": index_name,
                    "query_hash": query_hash,
                    "cost_saved": cost_saved,
                },
            )
            await session.commit()
    except Exception as exc:
        # Graceful degradation — analytics must never crash the app
        logger.warning(
            "cache_metrics_emit_failed",
            tenant_id=tenant_id,
            cache_type=cache_type,
            event_type=event_type,
            error=str(exc),
        )
