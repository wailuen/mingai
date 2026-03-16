"""
SemanticCacheService (CACHE-008).

Provides pgvector-based semantic similarity caching for LLM responses.
Near-duplicate queries are served from cache without an LLM call.

Table: semantic_cache (see alembic v011 + v012)
Columns: id, tenant_id, query_embedding VECTOR(1536), query_text,
         response_text, agent_id, similarity_threshold, hit_count,
         created_at, expires_at, version_tag

Lookup: cosine distance via pgvector <=> operator.
Store:  non-blocking asyncio.create_task() — never slows the response path.
Invalidation: version_tag compared against get_index_version(tenant_id, "global").
"""
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class CacheLookupResult:
    """Result of a successful semantic cache lookup."""

    response: "CacheableResponse"  # type: ignore[name-defined]  # noqa: F821
    similarity: float
    age_seconds: int


# ---------------------------------------------------------------------------
# SemanticCacheService
# ---------------------------------------------------------------------------


class SemanticCacheService:
    """
    Pgvector-based semantic similarity cache.

    Usage::

        svc = SemanticCacheService()

        # Lookup
        result = await svc.lookup(tenant_id, embedding, threshold=0.92)
        if result:
            return result.response  # cache hit

        # Store (non-blocking)
        await svc.store(tenant_id, query_text, embedding, response, ttl_seconds=86400)

        # Invalidate on document update
        await svc.invalidate_tenant(tenant_id)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def lookup(
        self,
        tenant_id: str,
        query_embedding: list[float],
        threshold: float = 0.92,
    ) -> CacheLookupResult | None:
        """
        Search for a semantically similar cached response.

        Uses pgvector cosine distance (<=>). The distance threshold is
        derived as: dist_threshold = 1 - threshold (cosine distance is
        1 minus cosine similarity).

        Also checks version_tag against the current global index version —
        stale entries (version mismatch) are treated as misses.

        Args:
            tenant_id:       Tenant UUID.
            query_embedding: Float32 embedding vector for the query.
            threshold:       Minimum cosine similarity (0.0–1.0). Default 0.92.

        Returns:
            CacheLookupResult on hit, None on miss or error.
        """
        from app.modules.chat.response_models import CacheableResponse, Source
        from app.core.cache_utils import get_index_version
        from app.core.session import async_session_factory
        from sqlalchemy import text

        try:
            current_version = await get_index_version(tenant_id, "global")
        except Exception as exc:
            logger.warning(
                "semantic_cache_version_fetch_error",
                tenant_id=tenant_id,
                error=str(exc),
            )
            current_version = 0

        dist_threshold = 1.0 - threshold
        # Build the embedding vector literal for pgvector: '[1,2,3,...]'
        emb_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

        try:
            async with async_session_factory() as session:
                # Set RLS context for this tenant
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant_id},
                )

                result = await session.execute(
                    text(
                        "SELECT id, response_text, created_at, version_tag, "
                        "    (query_embedding <=> CAST(:emb AS vector)) AS distance "
                        "FROM semantic_cache "
                        "WHERE tenant_id = :tid "
                        "  AND expires_at > NOW() "
                        "  AND (query_embedding <=> CAST(:emb AS vector)) <= :dist_threshold "
                        "ORDER BY query_embedding <=> CAST(:emb AS vector) "
                        "LIMIT 1"
                    ),
                    {
                        "tid": tenant_id,
                        "emb": emb_literal,
                        "dist_threshold": dist_threshold,
                    },
                )
                row = result.mappings().first()
        except Exception as exc:
            logger.warning(
                "semantic_cache_lookup_error",
                tenant_id=tenant_id,
                error=str(exc),
            )
            return None

        if row is None:
            return None

        stored_version = row.get("version_tag", 0)
        if stored_version != current_version:
            logger.debug(
                "semantic_cache_version_stale",
                tenant_id=tenant_id,
                stored_version=stored_version,
                current_version=current_version,
            )
            return None

        distance = float(row["distance"])
        similarity = max(0.0, 1.0 - distance)

        try:
            response_data = json.loads(row["response_text"])
            sources = [Source(**s) for s in response_data.get("sources", [])]
            cacheable = CacheableResponse(
                sources=sources,
                raw_answer=response_data.get("raw_answer", ""),
                confidence=float(response_data.get("confidence", 0.0)),
                model=response_data.get("model", ""),
                latency_ms=int(response_data.get("latency_ms", 0)),
            )
        except Exception as exc:
            logger.warning(
                "semantic_cache_deserialize_error",
                tenant_id=tenant_id,
                error=str(exc),
            )
            return None

        # Calculate entry age
        created_at = row["created_at"]
        if isinstance(created_at, datetime):
            age_seconds = int(
                (
                    datetime.now(timezone.utc) - created_at.replace(tzinfo=timezone.utc)
                    if created_at.tzinfo is None
                    else datetime.now(timezone.utc) - created_at
                ).total_seconds()
            )
        else:
            age_seconds = 0

        # Increment hit_count non-blocking
        entry_id = str(row["id"])
        asyncio.create_task(self._increment_hit_count(entry_id, tenant_id))

        logger.info(
            "semantic_cache_hit",
            tenant_id=tenant_id,
            similarity=round(similarity, 4),
            age_seconds=age_seconds,
        )

        return CacheLookupResult(
            response=cacheable,
            similarity=similarity,
            age_seconds=age_seconds,
        )

    async def store(
        self,
        tenant_id: str,
        query_text: str,
        query_embedding: list[float],
        response: "CacheableResponse",  # type: ignore[name-defined]  # noqa: F821
        ttl_seconds: int = 86400,
    ) -> None:
        """
        Non-blocking upsert of a response to the semantic cache.

        Fires and forgets via asyncio.create_task() so it never slows
        the response path.

        Args:
            tenant_id:       Tenant UUID.
            query_text:      Original query text (for auditing/analytics).
            query_embedding: Float32 embedding vector.
            response:        CacheableResponse to store.
            ttl_seconds:     Cache entry TTL in seconds (default 86400 = 24h).
        """
        asyncio.create_task(
            self._store_impl(
                tenant_id, query_text, query_embedding, response, ttl_seconds
            )
        )

    async def invalidate_tenant(self, tenant_id: str) -> None:
        """
        Invalidate all semantic cache entries for a tenant by version increment.

        Incrementing the global index version causes all stored entries with
        the old version to be treated as misses on next lookup — no DELETE scan
        required.

        Fire-and-forget — errors are logged but not raised.
        """
        asyncio.create_task(self._invalidate_tenant_impl(tenant_id))

    # ------------------------------------------------------------------
    # Internal implementations
    # ------------------------------------------------------------------

    async def _store_impl(
        self,
        tenant_id: str,
        query_text: str,
        query_embedding: list[float],
        response: "CacheableResponse",  # type: ignore[name-defined]  # noqa: F821
        ttl_seconds: int,
    ) -> None:
        """Background task: write response to semantic_cache table."""
        from app.core.cache_utils import get_index_version
        from app.core.session import async_session_factory
        from sqlalchemy import text
        import uuid

        try:
            current_version = await get_index_version(tenant_id, "global")
        except Exception as exc:
            logger.warning(
                "semantic_cache_store_version_error",
                tenant_id=tenant_id,
                error=str(exc),
            )
            current_version = 0

        response_json = response.model_dump_json()
        emb_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"
        entry_id = str(uuid.uuid4())

        try:
            async with async_session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant_id},
                )
                await session.execute(
                    text(
                        "INSERT INTO semantic_cache "
                        "(id, tenant_id, query_embedding, query_text, response_text, "
                        " similarity_threshold, hit_count, created_at, expires_at, version_tag) "
                        "VALUES (:id, :tid, CAST(:emb AS vector), :query_text, :response_text, "
                        " :threshold, 0, NOW(), "
                        " NOW() + (:ttl_seconds * INTERVAL '1 second'), :version_tag)"
                    ),
                    {
                        "id": entry_id,
                        "tid": tenant_id,
                        "emb": emb_literal,
                        "query_text": query_text,
                        "response_text": response_json,
                        "threshold": 0.92,
                        "ttl_seconds": ttl_seconds,
                        "version_tag": current_version,
                    },
                )
                await session.commit()
            logger.debug(
                "semantic_cache_stored",
                tenant_id=tenant_id,
                entry_id=entry_id,
                version_tag=current_version,
            )
        except Exception as exc:
            logger.warning(
                "semantic_cache_store_error",
                tenant_id=tenant_id,
                error=str(exc),
            )

    async def _increment_hit_count(self, entry_id: str, tenant_id: str) -> None:
        """Background task: increment hit_count for a cache entry."""
        from app.core.session import async_session_factory
        from sqlalchemy import text

        try:
            async with async_session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant_id},
                )
                await session.execute(
                    text(
                        "UPDATE semantic_cache SET hit_count = hit_count + 1 "
                        "WHERE id = :id"
                    ),
                    {"id": entry_id},
                )
                await session.commit()
        except Exception as exc:
            logger.warning(
                "semantic_cache_hit_count_error",
                entry_id=entry_id,
                error=str(exc),
            )

    async def _invalidate_tenant_impl(self, tenant_id: str) -> None:
        """Background task: increment global version to invalidate all entries."""
        from app.core.cache_utils import increment_index_version

        try:
            new_version = await increment_index_version(tenant_id, "global")
            logger.info(
                "semantic_cache_tenant_invalidated",
                tenant_id=tenant_id,
                new_version=new_version,
            )
        except Exception as exc:
            logger.warning(
                "semantic_cache_invalidate_error",
                tenant_id=tenant_id,
                error=str(exc),
            )
