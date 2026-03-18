# 43. Hybrid Search Implementation — pgvector + tsvector RRF

> **Status**: Architecture Design
> **Date**: 2026-03-18
> **Purpose**: SQL patterns, service implementation, and tuning guide for replacing Azure AI Search hybrid search with pgvector + tsvector Reciprocal Rank Fusion.
> **Depends on**: `42-pgvector-schema-design.md`

---

## 1. Why Reciprocal Rank Fusion (RRF)

Azure AI Search uses RRF internally to fuse BM25 and vector ranked lists. We implement the same algorithm explicitly.

**RRF formula**:

```
score(d) = Σ  1 / (k + rank_i(d))
```

Where `k = 60` (standard; reduces dominance of top-ranked documents across lists).

**Why RRF over weighted average of scores**:

- BM25 scores and cosine similarity scores live on incompatible scales
- RRF works on ranks (ordinal positions), not raw scores — no calibration needed
- Documents appearing in both lists get a natural boost
- Documents exclusive to one list still surface if they ranked highly in that list

---

## 2. Hybrid Search SQL (RRF)

```sql
-- Set per-session for this query
SET hnsw.ef_search = 100;

WITH fts_ranked AS (
    -- Full-text search leg (BM25-approximate via ts_rank_cd)
    SELECT
        id,
        ROW_NUMBER() OVER (
            ORDER BY ts_rank_cd(fts_doc, query, 32) DESC
        ) AS fts_rank
    FROM
        search_chunks,
        websearch_to_tsquery('english', :query_text) AS query
    WHERE
        tenant_id  = :tenant_id
        AND index_id   = :index_id          -- scope to one KB or 'conversation' index
        AND fts_doc @@ query
        -- Optional for conversation docs:
        -- AND conversation_id = :conversation_id
        -- AND user_id = :user_id
    ORDER BY ts_rank_cd(fts_doc, query, 32) DESC
    LIMIT 200
),
vector_ranked AS (
    -- Vector search leg (HNSW cosine similarity)
    SELECT
        id,
        ROW_NUMBER() OVER (
            ORDER BY embedding <=> :query_embedding::halfvec(3072)
        ) AS vec_rank
    FROM search_chunks
    WHERE
        tenant_id  = :tenant_id
        AND index_id   = :index_id
        -- Optional conversation scope:
        -- AND conversation_id = :conversation_id
        -- AND user_id = :user_id
    ORDER BY embedding <=> :query_embedding::halfvec(3072)
    LIMIT 200
),
rrf AS (
    -- Fuse the two ranked lists
    SELECT
        COALESCE(f.id, v.id) AS id,
        COALESCE(1.0 / (60.0 + f.fts_rank), 0.0) +
        COALESCE(1.0 / (60.0 + v.vec_rank),  0.0) AS rrf_score
    FROM fts_ranked f
    FULL OUTER JOIN vector_ranked v ON f.id = v.id
)
SELECT
    sc.id,
    sc.chunk_key,
    sc.content,
    sc.title,
    sc.source_url,
    sc.file_name,
    sc.file_type,
    sc.chunk_type,
    sc.chunk_index,
    sc.page_number,
    sc.slide_number,
    sc.slide_title,
    sc.section_heading,
    sc.sheet_name,
    sc.is_image_description,
    rrf.rrf_score AS score
FROM rrf
JOIN search_chunks sc ON sc.id = rrf.id
ORDER BY rrf_score DESC
LIMIT :top_k;
```

**Parameters**:

- `:tenant_id` — UUID, always required
- `:index_id` — Logical index ID (e.g. `idx_sp_a3f2b1c4d5e6` or `{tenant_id}-{agent_id}`)
- `:query_text` — Raw user query string
- `:query_embedding` — float array cast to `halfvec(3072)`
- `:top_k` — 5 for KB search, 10 for conversation doc search

---

## 3. Vector-Only Search (Fallback When Query Has No Keywords)

```sql
SET hnsw.ef_search = 100;

SELECT
    id,
    chunk_key,
    content,
    title,
    source_url,
    file_name,
    file_type,
    chunk_type,
    chunk_index,
    page_number,
    slide_number,
    section_heading,
    1 - (embedding <=> :query_embedding::halfvec(3072)) AS score
FROM search_chunks
WHERE
    tenant_id = :tenant_id
    AND index_id  = :index_id
ORDER BY embedding <=> :query_embedding::halfvec(3072)
LIMIT :top_k;
```

Use when `query_text` is empty, very short (< 3 chars), or a stop-word-only query.

---

## 4. PgVectorSearchClient Implementation

```python
# src/backend/app/modules/chat/vector_search.py

import asyncpg
from typing import Optional
import structlog

logger = structlog.get_logger()

_HYBRID_SEARCH_SQL = """
SET LOCAL hnsw.ef_search = 100;

WITH fts_ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (ORDER BY ts_rank_cd(fts_doc, query, 32) DESC) AS fts_rank
    FROM search_chunks,
         websearch_to_tsquery('english', $3) AS query
    WHERE tenant_id = $1 AND index_id = $2 AND fts_doc @@ query
    LIMIT 200
),
vector_ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (ORDER BY embedding <=> $4::halfvec(3072)) AS vec_rank
    FROM search_chunks
    WHERE tenant_id = $1 AND index_id = $2
    ORDER BY embedding <=> $4::halfvec(3072)
    LIMIT 200
),
rrf AS (
    SELECT COALESCE(f.id, v.id) AS id,
           COALESCE(1.0 / (60.0 + f.fts_rank), 0.0) +
           COALESCE(1.0 / (60.0 + v.vec_rank),  0.0) AS rrf_score
    FROM fts_ranked f
    FULL OUTER JOIN vector_ranked v ON f.id = v.id
)
SELECT sc.id, sc.chunk_key, sc.content, sc.title, sc.source_url,
       sc.file_name, sc.file_type, sc.chunk_type, sc.chunk_index,
       sc.page_number, sc.slide_number, sc.slide_title,
       sc.section_heading, sc.sheet_name, sc.is_image_description,
       rrf.rrf_score AS score
FROM rrf
JOIN search_chunks sc ON sc.id = rrf.id
ORDER BY rrf_score DESC
LIMIT $5;
"""

_VECTOR_ONLY_SQL = """
SET LOCAL hnsw.ef_search = 100;

SELECT id, chunk_key, content, title, source_url,
       file_name, file_type, chunk_type, chunk_index,
       page_number, slide_number, slide_title,
       section_heading, sheet_name, is_image_description,
       1 - (embedding <=> $3::halfvec(3072)) AS score
FROM search_chunks
WHERE tenant_id = $1 AND index_id = $2
ORDER BY embedding <=> $3::halfvec(3072)
LIMIT $4;
"""

_UPSERT_SQL = """
INSERT INTO search_chunks (
    chunk_key, tenant_id, index_id, source_type,
    user_id, conversation_id, integration_id,
    content, title, source_url, file_name, file_type,
    chunk_type, chunk_index,
    page_number, slide_number, slide_title,
    sheet_name, row_range, section_heading,
    image_type, is_image_description,
    source_file_id, content_hash, etag,
    source_modified_at, file_size_bytes,
    embedding,
    indexed_at, updated_at
)
VALUES (
    $1,  $2,  $3,  $4,
    $5,  $6,  $7,
    $8,  $9,  $10, $11, $12,
    $13, $14,
    $15, $16, $17,
    $18, $19, $20,
    $21, $22,
    $23, $24, $25,
    $26, $27,
    $28::halfvec(3072),
    now(), now()
)
ON CONFLICT (tenant_id, index_id, chunk_key) DO UPDATE SET
    content             = EXCLUDED.content,
    title               = EXCLUDED.title,
    embedding           = EXCLUDED.embedding,
    content_hash        = EXCLUDED.content_hash,
    etag                = EXCLUDED.etag,
    source_modified_at  = EXCLUDED.source_modified_at,
    indexed_at          = now(),
    updated_at          = now()
WHERE search_chunks.content_hash IS DISTINCT FROM EXCLUDED.content_hash;
"""

_DELETE_BY_INDEX_SQL = """
DELETE FROM search_chunks
WHERE tenant_id = $1 AND index_id = $2;
"""

_DELETE_BY_SOURCE_FILE_SQL = """
DELETE FROM search_chunks
WHERE tenant_id = $1 AND index_id = $2 AND source_file_id = $3;
"""


class PgVectorSearchClient:
    """
    pgvector-backed search client.
    Implements hybrid search via tsvector (GIN) + HNSW (halfvec) with RRF fusion.
    Replaces LocalSearchClient (which returned empty results).
    """

    def __init__(self, db_pool):
        """
        Args:
            db_pool: asyncpg connection pool (the existing app pool).
        """
        self._pool = db_pool

    async def knn_search(
        self,
        *,
        index: str,              # Format: "{tenant_id}-{agent_id}" or "idx_sp_{hash}"
        vector: list[float],
        top_k: int = 10,
        query_text: Optional[str] = None,
        tenant_id: str,
        # Optional conversation scope (for conversation docs)
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Hybrid search using RRF over tsvector + HNSW.
        Falls back to vector-only if query_text is empty/short.
        """
        # Normalise embedding to list for asyncpg
        embedding_str = "[" + ",".join(str(x) for x in vector) + "]"

        use_hybrid = bool(query_text and len(query_text.strip()) >= 3)

        if use_hybrid:
            sql = _HYBRID_SEARCH_SQL
            params = (tenant_id, index, query_text.strip(), embedding_str, top_k)
        else:
            sql = _VECTOR_ONLY_SQL
            params = (tenant_id, index, embedding_str, top_k)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [dict(row) for row in rows]

    async def upsert_chunks(self, chunks: list[dict]) -> int:
        """
        Batch upsert chunks into search_chunks.
        Only updates rows where content_hash differs (no-op on unchanged content).
        Returns number of rows affected.
        """
        async with self._pool.acquire() as conn:
            result = await conn.executemany(_UPSERT_SQL, [
                (
                    c["chunk_key"],      c["tenant_id"],     c["index_id"],
                    c["source_type"],    c.get("user_id"),   c.get("conversation_id"),
                    c.get("integration_id"),
                    c["content"],        c.get("title"),     c.get("source_url"),
                    c.get("file_name"),  c.get("file_type"),
                    c.get("chunk_type", "text"), c.get("chunk_index", 0),
                    c.get("page_number"), c.get("slide_number"), c.get("slide_title"),
                    c.get("sheet_name"), c.get("row_range"), c.get("section_heading"),
                    c.get("image_type"), c.get("is_image_description", False),
                    c.get("source_file_id"), c.get("content_hash"), c.get("etag"),
                    c.get("source_modified_at"), c.get("file_size_bytes"),
                    "[" + ",".join(str(x) for x in c["embedding"]) + "]",
                )
                for c in chunks
            ])
        return len(chunks)

    async def delete_by_index(self, tenant_id: str, index_id: str) -> None:
        """Delete all chunks for a logical index (used when KB source is removed)."""
        async with self._pool.acquire() as conn:
            await conn.execute(_DELETE_BY_INDEX_SQL, tenant_id, index_id)

    async def delete_by_source_file(
        self, tenant_id: str, index_id: str, source_file_id: str
    ) -> None:
        """Delete chunks for a specific source file (used during incremental sync)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                _DELETE_BY_SOURCE_FILE_SQL, tenant_id, index_id, source_file_id
            )
```

---

## 5. Factory Update in `get_search_client()`

```python
def get_search_client(cloud_provider: str | None = None, db_pool=None):
    """
    Get the appropriate search client based on CLOUD_PROVIDER.
    For 'local' and 'aws': uses PgVectorSearchClient.
    """
    provider = cloud_provider or os.environ.get("CLOUD_PROVIDER", "local")

    if provider in ("local", "aws", "gcp", "self-hosted"):
        if db_pool is None:
            from app.core.database import get_pool
            db_pool = get_pool()
        return PgVectorSearchClient(db_pool)

    raise ValueError(
        f"Unknown CLOUD_PROVIDER: '{provider}'. "
        f"Must be one of: local, aws, gcp, self-hosted."
    )
```

---

## 6. Tenant Provisioning: DDL Helpers

```python
# src/backend/app/modules/tenants/worker.py  (replace _create_azure_search_index)

import re
import asyncpg

async def _create_pgvector_index(tenant_id: str, db_pool) -> None:
    """
    Create a partial HNSW index on search_chunks scoped to this tenant.
    Called during tenant provisioning.
    """
    safe_id = re.sub(r"[^a-z0-9]", "_", tenant_id.lower())[:16]
    index_name = f"idx_sc_embedding_t_{safe_id}"

    async with db_pool.acquire() as conn:
        await conn.execute(f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name}
            ON search_chunks
            USING hnsw(embedding halfvec_cosine_ops)
            WITH (m = 16, ef_construction = 128)
            WHERE tenant_id = '{tenant_id}'::uuid
        """)

        # Register in index registry
        await conn.execute("""
            INSERT INTO search_index_registry
                (tenant_id, index_id, source_type, embedding_model, dimensions)
            VALUES ($1, $2, 'tenant_default', 'text-embedding-3-large', 3072)
            ON CONFLICT (tenant_id, index_id) DO NOTHING
        """, tenant_id, f"tenant-{tenant_id}")


async def _delete_pgvector_index(tenant_id: str, db_pool) -> None:
    """
    Drop the partial HNSW index and delete all chunks for this tenant.
    Called during tenant deprovisioning or rollback.
    """
    safe_id = re.sub(r"[^a-z0-9]", "_", tenant_id.lower())[:16]
    index_name = f"idx_sc_embedding_t_{safe_id}"

    async with db_pool.acquire() as conn:
        try:
            await conn.execute(
                f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}"
            )
            await conn.execute(
                "DELETE FROM search_chunks WHERE tenant_id = $1::uuid",
                tenant_id
            )
            await conn.execute(
                "DELETE FROM search_index_registry WHERE tenant_id = $1::uuid",
                tenant_id
            )
        except Exception as exc:
            logger.warning(
                "pgvector_index_delete_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )
```

---

## 7. Cache Integration

The existing `SearchCacheService` in `app/core/cache_search.py` is fully compatible — no changes needed.

Cache key: `mingai:{tenant_id}:search:{index_id}:{emb_hash16}:{params_hash8}`

Cache invalidation on document sync (already implemented in sharepoint.py / google_drive sync_worker.py):

```python
asyncio.create_task(increment_index_version(tenant_id, integration_id))
```

The version counter mismatch causes cache misses on next query — forcing a fresh pgvector query. This mechanism is backend-agnostic.

---

## 8. Performance Tuning Guide

### `hnsw.ef_search`

| Workload                        | Recommended value | Notes                       |
| ------------------------------- | ----------------- | --------------------------- |
| Fast / high-throughput          | 40 (default)      | Lower recall (~90%), faster |
| Standard RAG                    | 100               | Good balance (recall ~97%)  |
| High-recall (legal, compliance) | 200               | Best recall, 2x slower      |

Set per-query with `SET LOCAL hnsw.ef_search = 100` inside a transaction.

### Embedding Comparison Operator

Use `<=>` for cosine distance (returns 0-2, lower = more similar).

`1 - (embedding <=> query_embedding)` = cosine similarity (0-1).

For vector-only score reporting to match existing confidence calculator: return `1 - distance`.

### FTS Normalization Flag

`ts_rank_cd(fts_doc, query, 32)` — normalization flag `32` divides rank by `rank + 1`, producing a score in `[0, 1)`. This is the most BM25-like normalization available in PostgreSQL.

Flag `1` (divide by log document length) can also be combined: `32 | 1 = 33`.

### Query Parallelism

Multiple KB indexes are searched in parallel at the application layer (existing pipeline already uses `asyncio.gather`). Each `knn_search()` call is independent.

---

## 9. Score Normalization for Confidence Calculator

The existing `RetrievalConfidenceCalculator` expects scores in `[0, 1]`.

RRF scores are in `(0, 1/60]` — not normalized. Map them before passing to the calculator:

```python
def normalize_rrf_scores(results: list[dict]) -> list[dict]:
    """Normalize RRF scores to [0, 1] range for confidence calculation."""
    if not results:
        return results
    max_score = max(r["score"] for r in results)
    if max_score == 0:
        return results
    return [{**r, "score": r["score"] / max_score} for r in results]
```

Apply before constructing `SearchResult` objects.

---

**Document Version**: 1.0
**Last Updated**: 2026-03-18
