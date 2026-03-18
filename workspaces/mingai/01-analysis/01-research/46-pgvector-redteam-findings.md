# 46. pgvector Migration — Red Team Findings

> **Status**: Red Team Critique
> **Date**: 2026-03-18
> **Purpose**: Adversarial review of documents 40–45. All gaps must be resolved before implementation begins.
> **Depends on**: `40-pgvector-migration-overview.md` through `45-pgvector-competitive-analysis.md`

---

## Executive Summary

The research documents (40–45) represent a well-structured migration plan with strong strategic reasoning. However, red team analysis uncovered **5 critical, 11 high, 8 medium, and 6 low** issues. The five critical issues describe fundamental architectural mismatches that would produce a completely non-functional system if implemented as documented.

**The five critical issues must be resolved before any code is written.**

---

## CRITICAL — Would cause complete feature failure or security breach

### C-1. RLS Config Variable Name Mismatch

**Document**: `42-pgvector-schema-design.md`

**Problem**: The proposed RLS policies use `current_setting('app.current_tenant_id', true)::uuid`. But the existing session layer (`session.py`) injects `app.tenant_id` (not `app.current_tenant_id`) via `set_config('app.tenant_id', :tid, true)`. These are different PostgreSQL config variables. With `current_setting(..., true)`, a missing variable returns NULL, and `NULL::uuid = tenant_id` never matches — every `search_chunks` query under RLS returns zero rows.

**Fix**: Use `current_setting('app.tenant_id', true)::uuid` to match the existing session injection pattern. Verify with `SELECT current_setting('app.tenant_id', true)` inside a request context.

---

### C-2. asyncpg Pool vs SQLAlchemy AsyncSession — Wrong DB Access Layer

**Document**: `43-hybrid-search-implementation.md`

**Problem**: `PgVectorSearchClient` is designed around `asyncpg.Pool` with `self._pool.acquire()` and `conn.fetch()`. The codebase has no asyncpg pool. The backend uses SQLAlchemy `AsyncSession` with `create_async_engine()`. The factory reference `from app.core.database import get_pool` does not exist.

If implemented as documented, `get_search_client()` instantiation would fail immediately with `ImportError`.

**Fix**: Rewrite `PgVectorSearchClient` to use `SQLAlchemy AsyncSession` with `session.execute(text(...))` — the same pattern used across the entire codebase. This also correctly inherits the RLS context set by `get_db_with_rls()`.

---

### C-3. Multi-Statement String Fails with asyncpg

**Document**: `43-hybrid-search-implementation.md`

**Problem**: `_HYBRID_SEARCH_SQL` begins with `SET LOCAL hnsw.ef_search = 100;` followed by the CTE as a single string. asyncpg does not support multi-statement queries via the extended query protocol. Sending both statements as one string to `conn.fetch()` raises `PostgresSyntaxError`. The same applies to SQLAlchemy `session.execute(text(...))`.

**Fix**: Split into two separate execute calls within the same transaction/session:

```python
await session.execute(text("SET LOCAL hnsw.ef_search = 100"))
result = await session.execute(text(HYBRID_SEARCH_CTE), params)
```

Both must be in the same session so `SET LOCAL` is transaction-scoped to the query.

---

### C-4. CREATE INDEX CONCURRENTLY Cannot Run Inside a Transaction

**Document**: `42-pgvector-schema-design.md`, `43-hybrid-search-implementation.md`

**Problem**: PostgreSQL prohibits `CREATE INDEX CONCURRENTLY` inside a transaction block. Two issues:

1. **Alembic migrations**: Alembic runs inside a transaction by default. The `CREATE INDEX CONCURRENTLY` statements in `v016_search_chunks.py` will fail with `CREATE INDEX CONCURRENTLY cannot run inside a transaction block`.

2. **Runtime provisioning**: If `_create_pgvector_index()` is called within a SQLAlchemy session context (which wraps a transaction), `CREATE INDEX CONCURRENTLY` will also fail.

**Fix for Alembic**: Use `op.execute()` with the migration in non-transactional mode:

```python
def upgrade():
    op.execute("COMMIT")  # exit Alembic's implicit transaction
    op.execute("CREATE INDEX CONCURRENTLY ...")
```

Or configure the migration environment with `transaction_per_migration = False`.

**Fix for provisioning**: Use a raw `asyncpg` connection with `isolation_level=AUTOCOMMIT`, separate from the SQLAlchemy session pool:

```python
async with asyncpg.connect(dsn, isolation_level='read_committed') as conn:
    await conn.execute("CREATE INDEX CONCURRENTLY ...")
```

Alternatively, use non-concurrent DDL (`CREATE INDEX` without `CONCURRENTLY`) for the per-tenant partial index — it is created on a near-empty table slice, so blocking is negligible.

---

### C-5. `executemany()` Returns None — Count Is Always Wrong

**Document**: `43-hybrid-search-implementation.md`

**Problem**: `PgVectorSearchClient.upsert_chunks()` uses `conn.executemany()` and returns `len(chunks)` as the upsert count. asyncpg `executemany()` returns `None`, not row counts. The method always reports all chunks as upserted regardless of whether `content_hash IS DISTINCT FROM` caused rows to be skipped. This causes `search_index_registry.chunk_count` to diverge from reality.

Additionally, `executemany()` runs all rows in a single implicit transaction — one constraint violation on any row aborts the entire batch.

**Fix**: Use `RETURNING id` with `session.execute()` to count actual upserted rows, or use `unnest()` bulk insert with explicit row counting. For batch insert, use `INSERT ... SELECT unnest($1::text[]), unnest($2::halfvec[]) ...` with `RETURNING id`.

---

## HIGH — Would cause incorrect behavior or test failures

### H-1. `VectorSearchService.search()` Never Passes `query_text`

Hybrid search requires `query_text` in the search call. `VectorSearchService.search()` currently only accepts and passes `query_vector`. The orchestrator does not pass `query_text` to the search method. Without this, the FTS leg is never activated — every search degrades to vector-only silently.

**Fix**: Add `query_text: str | None = None` to `VectorSearchService.search()`. Pass user message text from the orchestrator.

### H-2. `upsert_chunks()` Signature Mismatch with `indexing.py`

`indexing.py` calls `vector_service.upsert_chunks(tenant_id=..., integration_id=..., file_path=..., chunk_index=..., chunk_text=..., embedding=...)` per chunk. `PgVectorSearchClient.upsert_chunks()` takes `chunks: list[dict]`. These are incompatible.

**Fix**: `VectorSearchService.upsert_chunks()` must accept the per-chunk kwargs from `indexing.py` and internally translate/batch before delegating to the client. Refactoring `indexing.py` to batch is also acceptable but touches more code.

### H-3. Non-English Text Silently Breaks FTS

`websearch_to_tsquery('english', ...)` and `to_tsvector('english', ...)` produce empty results for non-Latin scripts. Chinese, Japanese, Korean, and Arabic queries will silently degrade to vector-only with no indication.

**Fix**: Use `'simple'` configuration as a baseline, or make the tsvector config tenant-configurable via `search_index_registry`. Document this as a known limitation at minimum.

### H-4. Embedding Dimension Not Validated at Startup

The schema assumes `halfvec(3072)` (text-embedding-3-large). If `.env` sets `EMBEDDING_MODEL=text-embedding-3-small` (1536 dims), inserts will fail with dimension mismatch errors at runtime. The existing Azure AI Search schema used 1536 dims — if there is any code path using 3-small, the schema must match.

**Fix**: Add a startup validation that reads the configured embedding model's output dimension and verifies it matches the `search_chunks.embedding` column's dimension.

### H-5. `fts_ranked` CTE Missing ORDER BY Before LIMIT

The `LIMIT 200` in `fts_ranked` without an `ORDER BY` on the outer query means PostgreSQL can return any 200 matching rows, not the top 200 by relevance. `ROW_NUMBER()` then ranks an arbitrary subset. RRF ordering is incorrect.

**Fix**: Add `ORDER BY ts_rank_cd(fts_doc, query, 32) DESC` before `LIMIT 200` in the `fts_ranked` CTE.

### H-6. `FORCE ROW LEVEL SECURITY` Missing

Schema uses `ENABLE ROW LEVEL SECURITY` but not `FORCE ROW LEVEL SECURITY`. Without `FORCE`, the table owner (the application DB user) bypasses RLS entirely, disabling tenant isolation.

**Fix**: Add `ALTER TABLE search_chunks FORCE ROW LEVEL SECURITY;` and `ALTER TABLE search_index_registry FORCE ROW LEVEL SECURITY;`.

### H-7. `WITH CHECK` Clause Missing from RLS Policies

RLS policies only have `USING (...)` for reads. Without `WITH CHECK (...)`, INSERT/UPDATE operations can write data with any `tenant_id`, bypassing isolation on writes.

**Fix**: Add `WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)` to both policies, matching the existing pattern.

### H-8. RRF Normalization Produces Inflated Confidence

Normalizing the top score to exactly `1.0` means `RetrievalConfidenceCalculator` always returns ≥ 0.5 when any results exist (since `top_score * 0.5 = 0.5`). Poor search results will report high confidence.

**Fix**: Normalize against a theoretical maximum RRF score (e.g., `2/61 = 0.0328` for dual-appearing rank-1 document) rather than the observed maximum. This preserves absolute score meaning.

### H-9. `search_index_registry` Counts Never Updated

`doc_count`, `chunk_count`, `storage_bytes` columns have `DEFAULT 0` but no trigger or UPDATE path. They remain 0 forever.

**Fix**: Update registry counts after each batch upsert in `VectorSearchService.upsert_chunks()`. Use a single UPDATE with a subquery counting current rows for that `index_id`.

### H-10. Index Name Collision Risk (Tenant Short ID Truncation)

`tenant_short_id = re.sub(r"[^a-z0-9]", "_", str(tenant_id).lower())[:16]` — the first 16 chars of a UUID (after hyphens replaced with underscores) are `xxxxxxxx_xxxx_xx`. At scale, this could collide between tenants sharing UUID prefixes.

**Fix**: Use `hashlib.sha256(tenant_id.encode()).hexdigest()[:20]` or the full UUID without hyphens (32 chars, total index name 51 chars — within PostgreSQL's 63-char limit).

### H-11. `index_id` Not a Real Foreign Key

`search_chunks.index_id` is a logical reference — no `REFERENCES` constraint. Deleting from `search_index_registry` does not cascade to `search_chunks`. Orphaned chunks accumulate.

**Fix**: Either add `REFERENCES search_index_registry(index_id) ON DELETE CASCADE` (requires adding `(tenant_id, index_id)` as unique key first), or document explicit cleanup responsibility and add it to `_delete_pgvector_index()`.

---

## MEDIUM — Suboptimal behavior or maintenance burden

### M-1. Short Query Threshold Too Aggressive (3 chars)

Queries like "AI", "HR", "UK", "ML" (2 chars) are common enterprise terms that skip FTS at the `len >= 3` threshold.

**Fix**: Lower to `len >= 2`, or check whether `websearch_to_tsquery` produces any lexemes.

### M-2. No Platform Admin RLS Bypass Policy

Platform admins need to query `search_chunks` for monitoring/debugging. Without a bypass policy, all PA queries return empty.

**Fix**: Add platform admin bypass policy matching the existing pattern in `database.py`.

### M-3. Test Strategy Contradicts No-Mocking Rule

Doc 44 proposes "patch `asyncpg.execute` to raise `asyncpg.PostgresError`" for rollback testing. This is a mock, violating the no-mocking policy.

**Fix**: Use a real failure scenario: attempt to create a HNSW index on a non-existent table column, or use an invalid DDL statement that raises a real `PostgresError`.

### M-4. `updated_at` Not Auto-Updated on UPDATE

`DEFAULT now()` only applies on INSERT. Updates leave `updated_at` stale without a trigger.

**Fix**: Create a `set_updated_at()` trigger function and attach to `search_chunks`. Match the pattern used by other tables in the schema.

### M-5. `upsert_chunks` Doesn't Update All Mutable Metadata

The ON CONFLICT UPDATE SET does not include `source_url`, `file_name`, `file_type`, `chunk_type`, `file_size_bytes`. Renaming a file leaves stale metadata.

**Fix**: Include all mutable metadata fields in the ON CONFLICT UPDATE SET clause.

### M-6. No Search Quality Observability

No structured logging for RRF scores, FTS vs. vector-only query distribution, or low-confidence query sampling.

**Fix**: Add structured logging in `knn_search()`: log `query_text` (hashed), result count, top score, and whether hybrid or vector-only path was taken.

### M-7. `xlsx` in Schema But Not in Indexing Pipeline

`search_chunks.file_type` documents 'xlsx' support and has `sheet_name`/`row_range` columns, but `DocumentIndexingPipeline.SUPPORTED_EXTENSIONS` does not include `.xlsx`.

**Fix**: Either add xlsx indexing support (openpyxl) or remove xlsx from schema documentation.

### M-8. Registry Counts With Concurrent Syncs

Multiple concurrent sync jobs for the same tenant/index would produce race conditions on `search_index_registry.chunk_count` updates.

**Fix**: Use `UPDATE search_index_registry SET chunk_count = (SELECT COUNT(*) FROM search_chunks WHERE tenant_id = $1 AND index_id = $2)` instead of increment arithmetic.

---

## LOW — Improvements but not blocking

### L-1. USP 1 Overstates Uniqueness

"Only enterprise AI assistant that runs entirely within a single PostgreSQL database" is contestable. PrivateGPT and Supabase-based tools also use PostgreSQL + pgvector.

**Fix**: Qualify: "Only multi-tenant enterprise AI assistant platform with native RBAC that runs entirely within the customer's own PostgreSQL instance."

### L-2. "~40% of global enterprise software spend" Is Unsourced

**Fix**: Source it (Gartner/IDC) or soften to "a substantial and systematically underserved share."

### L-3. "No Cross-Tenant Knowledge Sharing" Mislabeled as Weakness

For regulated-industry target customers, strict isolation is a selling point, not a weakness.

**Fix**: Reframe: "Strict data isolation is architecturally enforced — a regulatory advantage that limits cross-tenant learning effects."

### L-4. `ts_rank_cd` Normalization Flag 32 Misdescribed

Flag 32 is score compression (`rank / (rank + 1)`), not a BM25 approximation. Flag 1 (length normalization) is more BM25-like.

**Fix**: Use flag `1 | 32 = 33` for length-normalized compressed scores, or clarify that ts_rank_cd approximates TF-IDF, not BM25.

### L-5. `CREATE INDEX CONCURRENTLY` in Migration Requires Non-Transactional Context

Documented under C-4. Mark in migration comments that rebuild must use `autocommit=True`.

### L-6. `get_search_client()` Drops `"azure"` Without Deprecating in Config

`CLOUD_PROVIDER=azure` passes config validation but will fail at client creation after the migration.

**Fix**: Either remove `"azure"` from the config validator or alias it to the pgvector client with a deprecation warning.

---

## Resolution Priority Before Implementation

| Priority                         | Issues                       |
| -------------------------------- | ---------------------------- |
| Must fix first (blocks all code) | C-1, C-2, C-3, C-4, C-5      |
| Fix before write path            | H-1, H-2, H-6, H-7           |
| Fix before read path             | H-5, H-8                     |
| Fix before testing               | H-9, H-10, H-11, M-3, M-4    |
| Fix before launch                | H-3, H-4, M-1, M-2, M-5, M-6 |
| Post-launch / backlog            | L-1 through L-6              |

---

**Document Version**: 1.0
**Last Updated**: 2026-03-18
