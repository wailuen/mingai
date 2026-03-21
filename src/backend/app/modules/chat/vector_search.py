"""
VectorSearchService (AI-055) — pgvector-backed hybrid search.

Replaces Azure AI Search with pgvector + tsvector for hybrid RRF search.
All search and indexing operations use SQLAlchemy AsyncSession (no asyncpg pool needed).

Architecture:
  - PgVectorSearchClient: low-level DB queries (RRF hybrid, upsert, delete)
  - VectorSearchService: per-request adapter (index naming, signature compat)
  - RetrievalConfidenceCalculator: pure score calculation, unchanged

Hybrid search: Reciprocal Rank Fusion (RRF) of FTS (tsvector 'simple') + HNSW (halfvec cosine)
Vector format: halfvec(1536) — text-embedding-3-small compatible
RLS: Enforced by session layer (app.current_tenant_id), same as all other tables
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

import structlog
from sqlalchemy import text

from app.core.session import async_session_factory

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# RRF constants
# ---------------------------------------------------------------------------
_RRF_K = 60
# Theoretical maximum RRF score: rank-1 document appearing in both FTS and vector lists
_RRF_MAX_SCORE = 2.0 / (_RRF_K + 1)  # ≈ 0.0328

# ---------------------------------------------------------------------------
# SQL constants — module-level for performance, no runtime string formatting
# ---------------------------------------------------------------------------

# Hybrid search: RRF fusion of tsvector FTS + HNSW vector search
# fts_ranked ORDER BY before LIMIT ensures top-200 by relevance (not arbitrary 200)
# Scores normalized against theoretical max so RetrievalConfidenceCalculator works correctly
_HYBRID_SEARCH_SQL = """
WITH
fts_ranked AS (
    SELECT
        sc.id,
        ROW_NUMBER() OVER (ORDER BY ts_rank_cd(sc.fts_doc, query.q, 32) DESC) AS fts_rank
    FROM search_chunks sc,
         websearch_to_tsquery('simple', :query_text) AS query(q)
    WHERE sc.tenant_id = CAST(:tenant_id AS uuid)
      AND sc.index_id  = :index_id
      AND (CAST(:conv_id AS uuid) IS NULL OR sc.conversation_id = CAST(:conv_id AS uuid))
      AND (CAST(:user_id AS uuid) IS NULL OR sc.user_id = CAST(:user_id AS uuid))
      AND sc.fts_doc @@ query.q
    ORDER BY ts_rank_cd(sc.fts_doc, query.q, 32) DESC
    LIMIT 200
),
vec_ranked AS (
    SELECT
        sc.id,
        ROW_NUMBER() OVER (ORDER BY sc.embedding <=> CAST(:vec AS halfvec)) AS vec_rank
    FROM search_chunks sc
    WHERE sc.tenant_id = CAST(:tenant_id AS uuid)
      AND sc.index_id  = :index_id
      AND (CAST(:conv_id AS uuid) IS NULL OR sc.conversation_id = CAST(:conv_id AS uuid))
      AND (CAST(:user_id AS uuid) IS NULL OR sc.user_id = CAST(:user_id AS uuid))
    ORDER BY sc.embedding <=> CAST(:vec AS halfvec)
    LIMIT 200
),
rrf AS (
    SELECT
        COALESCE(f.id, v.id) AS id,
        COALESCE(1.0 / (:k + f.fts_rank), 0.0)
      + COALESCE(1.0 / (:k + v.vec_rank), 0.0) AS rrf_score
    FROM fts_ranked f
    FULL OUTER JOIN vec_ranked v ON f.id = v.id
)
SELECT
    sc.id,
    sc.title,
    sc.content,
    sc.source_url,
    sc.chunk_key,
    r.rrf_score / :rrf_max AS score
FROM rrf r
JOIN search_chunks sc ON sc.id = r.id
ORDER BY r.rrf_score DESC
LIMIT :top_k
"""

# Vector-only fallback for short / empty query_text
_VECTOR_ONLY_SQL = """
SELECT
    sc.id,
    sc.title,
    sc.content,
    sc.source_url,
    sc.chunk_key,
    (1.0 - (sc.embedding <=> CAST(:vec AS halfvec))) AS score
FROM search_chunks sc
WHERE sc.tenant_id = CAST(:tenant_id AS uuid)
  AND sc.index_id  = :index_id
  AND (CAST(:conv_id AS uuid) IS NULL OR sc.conversation_id = CAST(:conv_id AS uuid))
  AND (CAST(:user_id AS uuid) IS NULL OR sc.user_id = CAST(:user_id AS uuid))
ORDER BY sc.embedding <=> CAST(:vec AS halfvec)
LIMIT :top_k
"""

# Upsert with idempotency — only updates when content has changed
# RETURNING id gives accurate count of actual upserted/updated rows
_UPSERT_SQL = """
INSERT INTO search_chunks (
    chunk_key, tenant_id, index_id, source_type,
    user_id, conversation_id, integration_id,
    content, title, source_url, file_name, file_type,
    chunk_type, chunk_index,
    source_file_id, content_hash, etag, source_modified_at, file_size_bytes,
    embedding
) VALUES (
    :chunk_key, CAST(:tenant_id AS uuid), :index_id, :source_type,
    CAST(:user_id AS uuid), CAST(:conversation_id AS uuid), CAST(:integration_id AS uuid),
    :content, :title, :source_url, :file_name, :file_type,
    :chunk_type, :chunk_index,
    :source_file_id, :content_hash, :etag, :source_modified_at, :file_size_bytes,
    CAST(:embedding AS halfvec)
)
ON CONFLICT (tenant_id, index_id, chunk_key) DO UPDATE SET
    content             = EXCLUDED.content,
    title               = EXCLUDED.title,
    embedding           = EXCLUDED.embedding,
    content_hash        = EXCLUDED.content_hash,
    etag                = EXCLUDED.etag,
    source_modified_at  = EXCLUDED.source_modified_at,
    source_url          = EXCLUDED.source_url,
    file_name           = EXCLUDED.file_name,
    file_type           = EXCLUDED.file_type,
    chunk_type          = EXCLUDED.chunk_type,
    file_size_bytes     = EXCLUDED.file_size_bytes,
    updated_at          = now()
WHERE search_chunks.content_hash IS DISTINCT FROM EXCLUDED.content_hash
RETURNING id
"""

_DELETE_BY_INDEX_SQL = """
DELETE FROM search_chunks
WHERE tenant_id = CAST(:tenant_id AS uuid) AND index_id = :index_id
"""

_DELETE_BY_SOURCE_SQL = """
DELETE FROM search_chunks
WHERE tenant_id = CAST(:tenant_id AS uuid)
  AND index_id  = :index_id
  AND source_file_id = :source_file_id
"""

_UPDATE_REGISTRY_COUNTS_SQL = """
UPDATE search_index_registry SET
    chunk_count     = (
        SELECT COUNT(*)
        FROM search_chunks
        WHERE tenant_id = CAST(:tenant_id AS uuid) AND index_id = :index_id
    ),
    doc_count       = (
        SELECT COUNT(DISTINCT source_file_id)
        FROM search_chunks
        WHERE tenant_id = CAST(:tenant_id AS uuid) AND index_id = :index_id
    ),
    last_indexed_at = now(),
    updated_at      = now()
WHERE tenant_id = CAST(:tenant_id AS uuid) AND index_id = :index_id
"""

_UPSERT_REGISTRY_SQL = """
INSERT INTO search_index_registry
    (tenant_id, index_id, source_type, display_name)
VALUES
    (CAST(:tenant_id AS uuid), :index_id, :source_type, :display_name)
ON CONFLICT (tenant_id, index_id) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """A single search result from vector search."""

    title: str
    content: str
    score: float
    source_url: str | None
    document_id: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "title": self.title,
            "content": self.content,
            "score": self.score,
            "source_url": self.source_url,
            "document_id": self.document_id,
        }


# ---------------------------------------------------------------------------
# pgvector search client
# ---------------------------------------------------------------------------


class PgVectorSearchClient:
    """
    Low-level pgvector search client using SQLAlchemy AsyncSession.

    All operations use the existing async_session_factory — no separate
    asyncpg pool needed. RLS context is injected at the session layer
    by get_db_with_rls() for request-scoped sessions; background tasks
    that use async_session_factory directly must set RLS context explicitly.

    Hybrid search uses Reciprocal Rank Fusion (RRF) of:
      1. tsvector FTS  — websearch_to_tsquery('simple', ...) for non-Latin safety
      2. HNSW cosine   — halfvec(1536) embeddings via <=> operator
    """

    @staticmethod
    def _vec_to_str(vector: list[float]) -> str:
        """Convert embedding list to pgvector literal string '[x,y,z,...]'."""
        return "[" + ",".join(str(v) for v in vector) + "]"

    async def knn_search(
        self,
        *,
        index_id: str,
        vector: list[float],
        top_k: int = 10,
        query_text: str | None = None,
        tenant_id: str,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        """
        Hybrid RRF search (FTS + vector) or vector-only fallback.

        Uses hybrid search when query_text has >= 2 characters.
        Falls back to vector-only for empty/short queries.
        hnsw.ef_search=100 is SET LOCAL before the search query to improve recall.
        """
        use_hybrid = bool(query_text and len(query_text.strip()) >= 2)
        sql = _HYBRID_SEARCH_SQL if use_hybrid else _VECTOR_ONLY_SQL
        vec_str = self._vec_to_str(vector)
        top_k = max(1, min(top_k, 100))  # Guard against unbounded result sets

        params: dict = {
            "tenant_id": tenant_id,
            "index_id": index_id,
            "vec": vec_str,
            "top_k": top_k,
            "conv_id": conversation_id,
            "user_id": user_id,
        }
        if use_hybrid:
            params["query_text"] = query_text
            params["k"] = float(_RRF_K)
            params["rrf_max"] = _RRF_MAX_SCORE

        async with async_session_factory() as session:
            # SET LOCAL: scoped to current transaction — must be before the search query
            await session.execute(text("SET LOCAL hnsw.ef_search = 100"))
            result = await session.execute(text(sql), params)
            rows = result.mappings().all()

        results = [dict(r) for r in rows]

        logger.info(
            "pgvector_knn_search",
            tenant_id=tenant_id,
            index_id=index_id,
            result_count=len(results),
            search_mode="hybrid" if use_hybrid else "vector_only",
            top_k=top_k,
        )
        return results

    async def upsert_chunks(self, chunks: list[dict]) -> int:
        """
        Bulk-upsert chunks into search_chunks.

        Returns the count of rows actually inserted or updated (WHERE content_hash
        IS DISTINCT FROM ensures unchanged content is not re-written). Updates the
        search_index_registry counts after upsert.
        """
        if not chunks:
            return 0

        # Serialize embeddings to pgvector string format for each chunk
        serialized = []
        for chunk in chunks:
            c = dict(chunk)
            if isinstance(c.get("embedding"), list):
                c["embedding"] = self._vec_to_str(c["embedding"])
            # Ensure nullable UUID fields are None (not empty string)
            for field in ("user_id", "conversation_id", "integration_id"):
                if c.get(field) == "":
                    c[field] = None
            serialized.append(c)

        inserted_ids: list = []
        async with async_session_factory() as session:
            for chunk_params in serialized:
                result = await session.execute(text(_UPSERT_SQL), chunk_params)
                ids = result.scalars().all()
                inserted_ids.extend(ids)

            # Update registry counts — ensures doc_count and chunk_count stay fresh
            if serialized:
                sample = serialized[0]
                # Ensure registry row exists before updating counts
                await session.execute(
                    text(_UPSERT_REGISTRY_SQL),
                    {
                        "tenant_id": sample["tenant_id"],
                        "index_id": sample["index_id"],
                        "source_type": sample.get("source_type", "unknown"),
                        "display_name": sample.get("index_id", ""),
                    },
                )
                await session.execute(
                    text(_UPDATE_REGISTRY_COUNTS_SQL),
                    {
                        "tenant_id": sample["tenant_id"],
                        "index_id": sample["index_id"],
                    },
                )

            await session.commit()

        logger.info(
            "pgvector_chunks_upserted",
            upserted_count=len(inserted_ids),
            total_chunks=len(chunks),
        )
        return len(inserted_ids)

    async def delete_by_index(self, tenant_id: str, index_id: str) -> int:
        """Delete all chunks for a given tenant+index. Returns deleted row count."""
        async with async_session_factory() as session:
            result = await session.execute(
                text(_DELETE_BY_INDEX_SQL),
                {"tenant_id": tenant_id, "index_id": index_id},
            )
            await session.execute(
                text(
                    "UPDATE search_index_registry SET chunk_count=0, doc_count=0, updated_at=now() "
                    "WHERE tenant_id=CAST(:tenant_id AS uuid) AND index_id=:index_id"
                ),
                {"tenant_id": tenant_id, "index_id": index_id},
            )
            await session.commit()
        return result.rowcount or 0

    async def delete_by_source_file(
        self, tenant_id: str, index_id: str, source_file_id: str
    ) -> int:
        """Delete chunks for a specific source file. Updates registry counts after."""
        async with async_session_factory() as session:
            result = await session.execute(
                text(_DELETE_BY_SOURCE_SQL),
                {
                    "tenant_id": tenant_id,
                    "index_id": index_id,
                    "source_file_id": source_file_id,
                },
            )
            await session.execute(
                text(_UPDATE_REGISTRY_COUNTS_SQL),
                {"tenant_id": tenant_id, "index_id": index_id},
            )
            await session.commit()
        return result.rowcount or 0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_search_client(cloud_provider: str | None = None) -> PgVectorSearchClient:
    """
    Get the pgvector search client.

    All cloud providers (local, aws, gcp) use pgvector. The 'azure' value
    is accepted for backwards compatibility but logs a deprecation warning —
    remove AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_ADMIN_KEY from .env.
    """
    provider = cloud_provider or os.environ.get("CLOUD_PROVIDER", "local")

    # Warn only if old Azure AI Search env vars are still set — CLOUD_PROVIDER=azure is
    # valid (used for Azure OpenAI etc.) and now routes to pgvector like all providers.
    if os.environ.get("AZURE_SEARCH_ENDPOINT") or os.environ.get(
        "AZURE_SEARCH_ADMIN_KEY"
    ):
        logger.warning(
            "search_provider_azure_search_vars_stale",
            message=(
                "AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_ADMIN_KEY are set but no longer used. "
                "pgvector is the search backend for all CLOUD_PROVIDER values. "
                "Remove these vars from .env."
            ),
        )

    # All providers use pgvector — no per-provider branching needed
    return PgVectorSearchClient()


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------


class VectorSearchService:
    """
    Cloud-agnostic vector search service.

    Wraps PgVectorSearchClient with the per-request interface used by the
    orchestrator and indexing pipeline. Index naming: {tenant_id}-{agent_id}.
    """

    def __init__(self, cloud_provider: str | None = None) -> None:
        self._client = get_search_client(cloud_provider)

    async def _search_single_index(
        self,
        index_id: str,
        query_vector: list[float],
        top_k: int,
        tenant_id: str = "",
        query_text: str | None = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> list[SearchResult]:
        """
        Search a single named vector index.
        Raises on network/DB error — caller (fan-out gather) must handle exceptions.
        """
        raw_results = await self._client.knn_search(
            index_id=index_id,
            vector=query_vector,
            top_k=top_k,
            query_text=query_text,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        return [
            SearchResult(
                title=r.get("title") or "",
                content=r.get("content") or "",
                score=float(r.get("score") or 0.0),
                source_url=r.get("source_url"),
                document_id=r.get("chunk_key") or r.get("id") or "",
            )
            for r in raw_results
        ]

    async def search(
        self,
        query_vector: list[float],
        tenant_id: str,
        agent_id: str,
        top_k: int = 10,
        query_text: str | None = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
        kb_ids: list[str] | None = None,
    ) -> list[SearchResult]:
        """
        Search vector indexes.

        If kb_ids is non-empty, fan-out to each KB index in addition to the agent's
        own index via asyncio.gather.

        Index naming:
        - Agent's own index: f"{tenant_id}-{agent_id}"
        - KB binding index: kb_id directly (the integration's index_id)

        kb_ids entries must be pre-validated at the route handler layer.
        Exceptions from individual indexes are logged and skipped (resilient fan-out).

        Args:
            query_vector: Embedding of the query.
            tenant_id: Tenant identifier — index is tenant-scoped.
            agent_id: Agent identifier — index is per-agent.
            top_k: Maximum number of results.
            query_text: Raw user query text for FTS leg (optional).
            conversation_id: Scope to conversation docs (optional).
            user_id: Scope to user's docs (optional).
            kb_ids: Additional KB index IDs to search (optional).
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for vector search.")
        if not agent_id:
            raise ValueError("agent_id is required for vector search.")

        agent_index = f"{tenant_id}-{agent_id}"
        indexes_to_search: list[str] = [agent_index]

        # Fan out to each KB binding
        if kb_ids:
            for kb_id in kb_ids:
                if kb_id not in indexes_to_search:
                    indexes_to_search.append(kb_id)

        if len(indexes_to_search) == 1:
            # Fast path: single index, no gather overhead
            results = await self._search_single_index(
                index_id=indexes_to_search[0],
                query_vector=query_vector,
                top_k=top_k,
                tenant_id=tenant_id,
                query_text=query_text,
                conversation_id=conversation_id,
                user_id=user_id,
            )
        else:
            # Fan-out path: parallel search across multiple indexes
            import asyncio

            search_tasks = [
                self._search_single_index(
                    index_id=idx,
                    query_vector=query_vector,
                    top_k=top_k,
                    tenant_id=tenant_id,
                    query_text=query_text,
                    conversation_id=conversation_id,
                    user_id=user_id,
                )
                for idx in indexes_to_search
            ]
            all_results = await asyncio.gather(*search_tasks, return_exceptions=True)

            results = []
            for i, result in enumerate(all_results):
                if isinstance(result, Exception):
                    logger.warning(
                        "kb_search_index_failed",
                        index_id=indexes_to_search[i],
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        error=str(result),
                    )
                else:
                    results.extend(result)

            # Re-rank merged results by score, return top_k
            results.sort(key=lambda r: r.score, reverse=True)
            results = results[:top_k]

        logger.info(
            "vector_search_completed",
            tenant_id=tenant_id,
            agent_id=agent_id,
            indexes_searched=len(indexes_to_search),
            result_count=len(results),
            search_mode="hybrid" if query_text else "vector_only",
            top_score=results[0].score if results else 0.0,
        )
        return results

    async def upsert_chunks(
        self,
        *,
        tenant_id: str,
        integration_id: str,
        file_path: str,
        chunk_index: int,
        chunk_text: str,
        embedding: list[float],
        source_type: str = "sharepoint",
    ) -> None:
        """
        Adapter matching the indexing.py call signature.

        Builds the full chunk dict and delegates to PgVectorSearchClient.
        Called per-chunk by DocumentIndexingPipeline — errors are logged by the caller.
        """
        file_name = os.path.basename(file_path)
        ext = os.path.splitext(file_name)[1].lower().lstrip(".") or "txt"
        index_id = f"{tenant_id}-{integration_id}"
        chunk_key = f"{integration_id}_{file_name}_{chunk_index}"

        chunk = {
            "chunk_key": chunk_key,
            "tenant_id": tenant_id,
            "index_id": index_id,
            "source_type": source_type,
            "user_id": None,
            "conversation_id": None,
            "integration_id": integration_id,
            "content": chunk_text,
            "title": file_name,
            "source_url": None,
            "file_name": file_name,
            "file_type": ext,
            "chunk_type": "text",
            "chunk_index": chunk_index,
            "source_file_id": file_name,
            "content_hash": hashlib.sha256(chunk_text.encode()).hexdigest(),
            "etag": None,
            "source_modified_at": None,
            "file_size_bytes": None,
            "embedding": embedding,
        }
        await self._client.upsert_chunks(chunks=[chunk])

    async def delete_chunks(
        self,
        *,
        tenant_id: str,
        index_id: str,
        source_file_id: str | None = None,
    ) -> int:
        """Delete chunks by index or by specific source file."""
        if source_file_id:
            return await self._client.delete_by_source_file(
                tenant_id=tenant_id,
                index_id=index_id,
                source_file_id=source_file_id,
            )
        return await self._client.delete_by_index(
            tenant_id=tenant_id,
            index_id=index_id,
        )

    async def upsert_conversation_chunks(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        user_id: str,
        file_name: str,
        chunks: list[dict],  # list of {"text": str, "embedding": list[float]}
    ) -> int:
        """
        Upsert conversation-scoped document chunks.

        Uses index_id = f"conv-{tenant_id}-{conversation_id}" (distinct from
        integration indexes which use f"{tenant_id}-{integration_id}").
        Calls upsert_chunks() once with all chunks (not per-chunk).
        """
        safe_filename = os.path.basename(file_name)[:255]
        ext = os.path.splitext(safe_filename)[1].lower().lstrip(".") or "txt"
        index_id = f"conv-{tenant_id}-{conversation_id}"
        source_file_id = f"conv_{conversation_id}_{safe_filename}"

        chunk_list = []
        for i, c in enumerate(chunks):
            chunk_text = c["text"]
            # hash filename component to avoid special chars in chunk_key
            name_hash = hashlib.sha256(safe_filename.encode()).hexdigest()[:12]
            chunk_key = f"conv_{conversation_id}_{name_hash}_{i}"
            chunk_list.append(
                {
                    "chunk_key": chunk_key,
                    "tenant_id": tenant_id,
                    "index_id": index_id,
                    "source_type": "conversation",
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "integration_id": None,
                    "content": chunk_text,
                    "title": safe_filename,
                    "source_url": None,
                    "file_name": safe_filename,
                    "file_type": ext,
                    "chunk_type": "text",
                    "chunk_index": i,
                    "source_file_id": source_file_id,
                    "content_hash": hashlib.sha256(chunk_text.encode()).hexdigest(),
                    "etag": None,
                    "source_modified_at": None,
                    "file_size_bytes": None,
                    "embedding": c["embedding"],
                }
            )

        return await self._client.upsert_chunks(chunks=chunk_list)

    async def search_conversation_index(
        self,
        *,
        query_vector: list[float],
        tenant_id: str,
        conversation_id: str,
        top_k: int = 5,
        query_text: str | None = None,
        user_id: str | None = None,
    ) -> list[SearchResult]:
        """
        Search the conversation-scoped document index.

        Uses index_id = f"conv-{tenant_id}-{conversation_id}".
        Returns SearchResult objects (same type as search()).
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for conversation search.")
        if not conversation_id:
            raise ValueError("conversation_id is required for conversation search.")

        index_id = f"conv-{tenant_id}-{conversation_id}"

        raw_results = await self._client.knn_search(
            index_id=index_id,
            vector=query_vector,
            top_k=top_k,
            query_text=query_text,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )

        results = [
            SearchResult(
                title=r.get("title") or "",
                content=r.get("content") or "",
                score=float(r.get("score") or 0.0),
                source_url=r.get("source_url"),
                document_id=r.get("chunk_key") or r.get("id") or "",
            )
            for r in raw_results
        ]

        logger.info(
            "conversation_search_completed",
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            index_id=index_id,
            result_count=len(results),
        )
        return results


# ---------------------------------------------------------------------------
# Confidence calculator (unchanged)
# ---------------------------------------------------------------------------


class RetrievalConfidenceCalculator:
    """
    Calculates a confidence score for search results.

    Input scores must be in [0, 1] — PgVectorSearchClient normalizes RRF scores
    against the theoretical maximum so this calculator works correctly without
    always returning inflated values.
    """

    def calculate(self, results: list[SearchResult]) -> float:
        """
        Calculate retrieval confidence from search results.

        Returns float in [0.0, 1.0].
        0.0 = no results or very poor matches.
        1.0 = multiple high-confidence matches.
        """
        if not results:
            return 0.0

        scores = [r.score for r in results]

        top_score = max(scores)
        avg_score = sum(scores) / len(scores)
        count_factor = min(len(scores) / 5.0, 1.0)  # Max out at 5 results

        confidence = (top_score * 0.5) + (avg_score * 0.3) + (count_factor * 0.2)

        return max(0.0, min(1.0, confidence))
