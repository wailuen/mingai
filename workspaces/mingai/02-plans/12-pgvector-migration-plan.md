# 12. pgvector Migration — Implementation Plan

> **Status**: Implementation Plan
> **Date**: 2026-03-18
> **Purpose**: Authoritative implementation plan for replacing Azure AI Search with pgvector. Incorporates all red team findings from `01-analysis/01-research/46-pgvector-redteam-findings.md`.
> **Depends on**: Research docs 40–46

---

## Architecture Decisions (Incorporating Red Team Fixes)

### DB Access Layer

`PgVectorSearchClient` MUST use `SQLAlchemy AsyncSession` with `text()` queries. No asyncpg pool exists. Use `async_session_factory` from `app.core.session`.

### RLS Pattern

New tables use `get_rls_policy_sql()` and `get_platform_bypass_policy_sql()` from `app.core.database` — the existing helpers that produce `app.current_tenant_id` policies. This is consistent with all 22 existing tables. Do NOT deviate from the helper pattern.

### Migration Numbers

- pgvector extension: **already installed** (v011 `semantic_cache`).
- New migrations: **v040** (search_index_registry), **v041** (search_chunks).
- All subsequent migrations after v041 continue from v042.

### CONCURRENTLY in Alembic

Use `CREATE INDEX` (non-concurrent) in Alembic migrations for the initial global HNSW index — tables are empty at migration time, so no blocking. Document that index rebuilds on live tables require autocommit context.

### Provisioning DDL

`_create_pgvector_index()` in worker.py uses a raw asyncpg connection with `isolation_level=AUTOCOMMIT` to run `CREATE INDEX CONCURRENTLY`. This avoids SQLAlchemy transaction wrapping. Engine DSN from `settings.DATABASE_URL`.

### Index Naming

`idx_sc_embedding_t_{short}` where `short = hashlib.sha256(tenant_id.encode()).hexdigest()[:20]`. Full name: `idx_sc_embedding_t_` (19 chars) + 20 chars = 39 chars — well within PostgreSQL's 63-char limit. No UUID truncation collision risk.

### `SET LOCAL` Split

`knn_search()` issues TWO `session.execute()` calls within the same session:

1. `await session.execute(text("SET LOCAL hnsw.ef_search = 100"))`
2. `await session.execute(text(HYBRID_SEARCH_CTE), params)`

### RRF Normalization

Normalize against theoretical maximum: `2/61 ≈ 0.0328` (rank-1 doc appearing in both FTS and vector lists). Never divide by observed max (would always map top to 1.0, inflating confidence).

### Upsert Count

Use `INSERT ... RETURNING id` with `session.scalars()` for accurate upsert counts, not `executemany()`.

### `upsert_chunks()` Signature Compatibility

`VectorSearchService.upsert_chunks()` accepts per-chunk kwargs matching indexing.py's call:

```python
async def upsert_chunks(self, *, tenant_id, integration_id, file_path, chunk_index, chunk_text, embedding) -> None
```

Internally builds a chunk dict and delegates to `PgVectorSearchClient.upsert_chunks(chunks=[...])`.

---

## Phase 0: Correct Architecture Docs

Update `43-hybrid-search-implementation.md` with corrections to:

- DB layer (AsyncSession not asyncpg)
- SET LOCAL split
- RETURNING id for upsert
- Index naming (SHA256)

---

## Phase 1: Alembic Migrations (v040, v041)

### v040_search_index_registry.py

```python
"""040 — search_index_registry table for pgvector index lifecycle tracking."""
from alembic import op
from app.core.database import get_rls_policy_sql, get_platform_bypass_policy_sql

revision = "040"
down_revision = "039"

def upgrade():
    op.execute("""
    CREATE TABLE search_index_registry (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        index_id        TEXT NOT NULL,
        source_type     TEXT NOT NULL,
        display_name    TEXT,
        embedding_model TEXT NOT NULL DEFAULT 'text-embedding-3-large',
        dimensions      INTEGER NOT NULL DEFAULT 3072,
        doc_count       INTEGER NOT NULL DEFAULT 0,
        chunk_count     INTEGER NOT NULL DEFAULT 0,
        storage_bytes   BIGINT NOT NULL DEFAULT 0,
        version         INTEGER NOT NULL DEFAULT 1,
        last_indexed_at TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(tenant_id, index_id)
    )
    """)
    op.execute("CREATE INDEX idx_sir_tenant ON search_index_registry(tenant_id)")
    op.execute("CREATE INDEX idx_sir_index_id ON search_index_registry(index_id)")

    # RLS via standard helpers (app.current_tenant_id pattern)
    for stmt in get_rls_policy_sql("search_index_registry").split(";"):
        stmt = stmt.strip()
        if stmt:
            op.execute(stmt + ";")
    op.execute(get_platform_bypass_policy_sql("search_index_registry"))
```

### v041_search_chunks.py

```python
"""041 — search_chunks table: unified pgvector content store."""
# NON-TRANSACTIONAL for HNSW index: use op.execute("COMMIT") before CREATE INDEX
from alembic import op
from app.core.database import get_rls_policy_sql, get_platform_bypass_policy_sql

revision = "041"
down_revision = "040"

def upgrade():
    # 1. Table
    op.execute("""CREATE TABLE search_chunks ( ... )""")  # full DDL from doc 42

    # 2. updated_at trigger
    op.execute("""
    CREATE FUNCTION search_chunks_set_updated_at() RETURNS TRIGGER AS $$
    BEGIN NEW.updated_at = now(); RETURN NEW; END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    CREATE TRIGGER search_chunks_updated_at
    BEFORE UPDATE ON search_chunks
    FOR EACH ROW EXECUTE FUNCTION search_chunks_set_updated_at();
    """)

    # 3. RLS
    for stmt in get_rls_policy_sql("search_chunks").split(";"):
        stmt = stmt.strip()
        if stmt:
            op.execute(stmt + ";")
    op.execute(get_platform_bypass_policy_sql("search_chunks"))

    # 4. Non-vector indexes (transactional OK)
    op.execute("CREATE INDEX idx_sc_fts ON search_chunks USING GIN(fts_doc)")
    op.execute("CREATE INDEX idx_sc_conversation ON search_chunks(tenant_id, conversation_id, user_id) WHERE source_type = 'conversation'")
    op.execute("CREATE INDEX idx_sc_integration ON search_chunks(tenant_id, integration_id) WHERE integration_id IS NOT NULL")
    op.execute("CREATE INDEX idx_sc_index_id ON search_chunks(tenant_id, index_id)")
    op.execute("CREATE INDEX idx_sc_content_hash ON search_chunks(tenant_id, content_hash) WHERE content_hash IS NOT NULL")

    # 5. Global HNSW (non-transactional) — empty table, no lock risk
    op.execute("COMMIT")  # exit Alembic transaction
    op.execute("CREATE INDEX idx_sc_embedding_global ON search_chunks USING hnsw(embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 128)")
```

---

## Phase 2: Provisioning (worker.py)

Replace `_create_azure_search_index` / `_delete_azure_search_index` with:

```python
async def _create_pgvector_index(tenant_id: str) -> None:
    """Create per-tenant partial HNSW index. Uses autocommit for CONCURRENTLY."""
    import asyncpg
    import hashlib
    from app.core.config import settings

    short = hashlib.sha256(tenant_id.encode()).hexdigest()[:20]
    index_name = f"idx_sc_embedding_t_{short}"

    async with await asyncpg.connect(settings.DATABASE_URL) as conn:
        await conn.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name}
            ON search_chunks USING hnsw(embedding halfvec_cosine_ops)
            WITH (m = 16, ef_construction = 128)
            WHERE tenant_id = '{tenant_id}'::uuid
            """
        )
    # Register in search_index_registry
    async with get_db_session() as session:
        await session.execute(text("""
            INSERT INTO search_index_registry
            (tenant_id, index_id, source_type, display_name)
            VALUES (:tenant_id, :index_id, 'tenant', 'Tenant Search Index')
            ON CONFLICT (tenant_id, index_id) DO NOTHING
        """), {"tenant_id": tenant_id, "index_id": f"tenant_{tenant_id}"})
        await session.commit()


async def _delete_pgvector_index(tenant_id: str) -> None:
    """Drop per-tenant partial HNSW index and clean all search data."""
    import asyncpg
    import hashlib
    from app.core.config import settings

    short = hashlib.sha256(tenant_id.encode()).hexdigest()[:20]
    index_name = f"idx_sc_embedding_t_{short}"

    async with await asyncpg.connect(settings.DATABASE_URL) as conn:
        await conn.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")

    async with get_db_session() as session:
        await session.execute(
            text("DELETE FROM search_chunks WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await session.execute(
            text("DELETE FROM search_index_registry WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await session.commit()
```

Update `_step_create_search_index()` to call `_create_pgvector_index(tenant_id)` for ALL providers (local, aws, gcp — not just azure). Remove `"azure"` special case.

---

## Phase 3: PgVectorSearchClient (vector_search.py)

### Class structure

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_RRF_K = 60
_RRF_MAX_SCORE = 2 / (_RRF_K + 1)  # theoretical max when rank-1 in both lists

_HYBRID_SEARCH_CTE = """
WITH
fts_query AS (SELECT websearch_to_tsquery('simple', :query_text) AS q),
fts_ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (ORDER BY ts_rank_cd(fts_doc, q.q, 32) DESC) AS fts_rank
    FROM search_chunks, fts_query AS q
    WHERE tenant_id = :tenant_id::uuid
      AND index_id = :index_id
      AND (:conv_id::uuid IS NULL OR conversation_id = :conv_id::uuid)
      AND (:user_id::uuid IS NULL OR user_id = :user_id::uuid)
      AND fts_doc @@ q.q
    ORDER BY ts_rank_cd(fts_doc, q.q, 32) DESC
    LIMIT 200
),
vec_ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (ORDER BY embedding <=> :vec::halfvec) AS vec_rank
    FROM search_chunks
    WHERE tenant_id = :tenant_id::uuid
      AND index_id = :index_id
      AND (:conv_id::uuid IS NULL OR conversation_id = :conv_id::uuid)
      AND (:user_id::uuid IS NULL OR user_id = :user_id::uuid)
    ORDER BY embedding <=> :vec::halfvec
    LIMIT 200
),
rrf AS (
    SELECT COALESCE(f.id, v.id) AS id,
           COALESCE(1.0 / (:k + f.fts_rank), 0)
         + COALESCE(1.0 / (:k + v.vec_rank), 0) AS rrf_score
    FROM fts_ranked f
    FULL OUTER JOIN vec_ranked v ON f.id = v.id
)
SELECT sc.id, sc.title, sc.content, sc.source_url, sc.chunk_key,
       r.rrf_score / :rrf_max AS score
FROM rrf r
JOIN search_chunks sc ON sc.id = r.id
ORDER BY r.rrf_score DESC
LIMIT :top_k
"""

_VECTOR_ONLY_CTE = """
SELECT id, title, content, source_url, chunk_key,
       (1 - (embedding <=> :vec::halfvec)) / 1.0 AS score
FROM search_chunks
WHERE tenant_id = :tenant_id::uuid
  AND index_id = :index_id
  AND (:conv_id::uuid IS NULL OR conversation_id = :conv_id::uuid)
  AND (:user_id::uuid IS NULL OR user_id = :user_id::uuid)
ORDER BY embedding <=> :vec::halfvec
LIMIT :top_k
"""

_UPSERT_SQL = """
INSERT INTO search_chunks
  (chunk_key, tenant_id, index_id, source_type, user_id, conversation_id,
   integration_id, content, title, source_url, file_name, file_type,
   chunk_type, chunk_index, source_file_id, content_hash, etag,
   source_modified_at, file_size_bytes, embedding)
VALUES
  (:chunk_key, :tenant_id, :index_id, :source_type, :user_id, :conversation_id,
   :integration_id, :content, :title, :source_url, :file_name, :file_type,
   :chunk_type, :chunk_index, :source_file_id, :content_hash, :etag,
   :source_modified_at, :file_size_bytes, :embedding::halfvec)
ON CONFLICT (tenant_id, index_id, chunk_key) DO UPDATE SET
  content = EXCLUDED.content,
  title = EXCLUDED.title,
  embedding = EXCLUDED.embedding,
  content_hash = EXCLUDED.content_hash,
  etag = EXCLUDED.etag,
  source_modified_at = EXCLUDED.source_modified_at,
  source_url = EXCLUDED.source_url,
  file_name = EXCLUDED.file_name,
  file_type = EXCLUDED.file_type,
  chunk_type = EXCLUDED.chunk_type,
  file_size_bytes = EXCLUDED.file_size_bytes,
  updated_at = now()
WHERE search_chunks.content_hash IS DISTINCT FROM EXCLUDED.content_hash
RETURNING id
"""
```

### knn_search() flow

```python
async def knn_search(self, *, index_id, vector, top_k, query_text, tenant_id,
                     conversation_id=None, user_id=None) -> list[dict]:
    async with async_session_factory() as session:
        await session.execute(text("SET LOCAL hnsw.ef_search = 100"))
        use_hybrid = query_text and len(query_text.strip()) >= 2
        sql = _HYBRID_SEARCH_CTE if use_hybrid else _VECTOR_ONLY_CTE
        params = {
            "tenant_id": tenant_id, "index_id": index_id,
            "vec": str(vector),  # pgvector literal format
            "top_k": top_k, "k": _RRF_K, "rrf_max": _RRF_MAX_SCORE,
            "conv_id": conversation_id, "user_id": user_id,
            "query_text": query_text or "",
        }
        rows = (await session.execute(text(sql), params)).mappings().all()
        return [dict(r) for r in rows]
```

### upsert_chunks() flow

```python
async def upsert_chunks(self, chunks: list[dict]) -> int:
    async with async_session_factory() as session:
        result = await session.execute(text(_UPSERT_SQL), chunks)
        inserted_ids = result.scalars().all()
        await session.commit()
        return len(inserted_ids)
```

---

## Phase 4: VectorSearchService Adapter Methods

```python
class VectorSearchService:
    async def search(self, query_vector, tenant_id, agent_id, top_k=10,
                     query_text=None, conversation_id=None, user_id=None):
        index_id = f"{tenant_id}-{agent_id}"
        raw = await self._client.knn_search(
            index_id=index_id, vector=query_vector, top_k=top_k,
            query_text=query_text, tenant_id=tenant_id,
            conversation_id=conversation_id, user_id=user_id,
        )
        return [SearchResult(title=r["title"], content=r["content"],
                             score=r["score"], source_url=r.get("source_url"),
                             document_id=r["chunk_key"]) for r in raw]

    async def upsert_chunks(self, *, tenant_id, integration_id, file_path,
                            chunk_index, chunk_text, embedding) -> None:
        """Adapter: per-chunk kwargs → batch dict for PgVectorSearchClient."""
        import os, hashlib
        file_name = os.path.basename(file_path)
        ext = os.path.splitext(file_name)[1].lower().lstrip(".")
        index_id = f"{tenant_id}-{integration_id}"
        chunk_key = f"{integration_id}_{file_name}_{chunk_index}"
        chunk = {
            "chunk_key": chunk_key,
            "tenant_id": tenant_id,
            "index_id": index_id,
            "source_type": "sharepoint",  # or inferred from integration
            "user_id": None,
            "conversation_id": None,
            "integration_id": integration_id,
            "content": chunk_text,
            "title": file_name,
            "source_url": None,
            "file_name": file_name,
            "file_type": ext or "txt",
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

    async def delete_chunks(self, *, tenant_id: str, index_id: str) -> None:
        await self._client.delete_by_index(tenant_id=tenant_id, index_id=index_id)
```

---

## Phase 5: Orchestrator — Wire query_text

In the chat orchestrator, when calling `vector_service.search()`, pass `query_text=user_message_text`. Locate the `VectorSearchService.search()` call in `orchestrator.py` and add `query_text=` from the user's raw message.

---

## Phase 6: Cleanup

- Remove `LocalSearchClient` class from `vector_search.py`
- Remove `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_ADMIN_KEY` from `.env.example`
- Update `get_search_client()` factory: remove `"azure"` branch or alias to `PgVectorSearchClient`
- Remove `_create_azure_search_index` and `_delete_azure_search_index` from `worker.py`
- Add `"azure"` deprecation alias that logs a warning and falls through to PgVectorSearchClient

---

## Phase 7: Tests

### Unit tests (`tests/unit/test_vector_search.py`)

Replace AsyncMock with real pgvector test DB calls. New test cases:

- `test_upsert_and_search_returns_results` — insert 3 chunks, search, verify non-empty
- `test_hybrid_search_uses_fts` — verify FTS path activates for ≥ 2 char queries
- `test_vector_only_for_empty_query` — verify fallback for empty query_text
- `test_rrf_score_normalization` — verify scores ∈ [0, 1]
- `test_delete_by_index` — insert then delete, verify empty
- `test_upsert_idempotent` — same chunk_key twice, verify single row

### Integration tests (`tests/integration/test_pgvector_search.py`) — NEW FILE

- `test_tenant_provisioning_creates_partial_hnsw_index`
- `test_tenant_deprovisioning_drops_index_and_cleans_rows`
- `test_hybrid_search_cross_tenant_isolation` — tenant A cannot see tenant B chunks
- `test_per_user_conversation_isolation` — user A cannot see user B conversation docs
- `test_registry_counts_updated_after_upsert`
- `test_cache_invalidation_on_sync` (version counter increments)

### Update (`tests/integration/test_provisioning_rollback.py`)

Replace Azure env var patches with real DDL failure: `CREATE INDEX ON nonexistent_table_xyz` to trigger a real `ProgrammingError`. No mocking.

---

## File Change Surface

| File                                                          | Change Type                                                           |
| ------------------------------------------------------------- | --------------------------------------------------------------------- |
| `src/backend/alembic/versions/v040_search_index_registry.py`  | NEW                                                                   |
| `src/backend/alembic/versions/v041_search_chunks.py`          | NEW                                                                   |
| `src/backend/app/modules/chat/vector_search.py`               | REPLACE LocalSearchClient → PgVectorSearchClient, add adapter methods |
| `src/backend/app/modules/tenants/worker.py`                   | Replace Azure helpers with pgvector DDL                               |
| `src/backend/tests/unit/test_vector_search.py`                | REWRITE (no AsyncMock)                                                |
| `src/backend/tests/integration/test_pgvector_search.py`       | NEW                                                                   |
| `src/backend/tests/integration/test_provisioning_rollback.py` | UPDATE                                                                |
| `src/backend/.env.example`                                    | Remove AZURE*SEARCH*\* vars                                           |

**Total files changed**: 8 (3 new, 5 modified)

---

**Document Version**: 1.0
**Last Updated**: 2026-03-18
