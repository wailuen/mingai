# 44. Migration Strategy — Azure AI Search → pgvector

> **Status**: Architecture Design
> **Date**: 2026-03-18
> **Purpose**: Phase-by-phase migration plan, risks, rollback procedures, and test strategy.
> **Depends on**: `41-azure-search-touchpoints.md`, `42-pgvector-schema-design.md`, `43-hybrid-search-implementation.md`

---

## 1. Migration Preconditions

### Why No Parallel-Run Is Needed

The Azure AI Search code paths are **not in production use**:

- `LocalSearchClient.knn_search()` returns `[]` (empty) for all queries today
- `VectorSearchService.upsert_chunks()` is called in `indexing.py` but is **not implemented** — the call is effectively a no-op
- `_create_azure_search_index()` runs on tenant provisioning when `CLOUD_PROVIDER=azure`, but current deployments use `CLOUD_PROVIDER=local`

This means the migration is **net-new functionality**, not a replacement of live production behavior. There is no risk of data loss from the transition.

### Pre-Migration Checklist

- [ ] Aurora PostgreSQL version is 15+ (pgvector 0.8.0 / `halfvec` support)
- [ ] `CREATE EXTENSION vector` can be run on the target DB (Aurora supports it natively)
- [ ] `CLOUD_PROVIDER=local` or `CLOUD_PROVIDER=aws` confirmed in `.env`
- [ ] `maintenance_work_mem` can be set to ≥ 1GB for index builds
- [ ] Existing test suite passes at baseline (run before any changes)

---

## 2. Phase Plan

### Phase 1: Schema Migration (Foundation)

**Goal**: Add pgvector extension and tables. No application behavior changes.

**Steps**:

1. Write and run `v014_enable_pgvector.py`: `CREATE EXTENSION IF NOT EXISTS vector`
2. Write and run `v015_search_index_registry.py`: registry table + RLS policy
3. Write and run `v016_search_chunks.py`: main table + GIN index + global HNSW

**Time estimate**: HNSW global index on empty table = seconds. GIN index = seconds.

**Validation**:

```sql
SELECT extversion FROM pg_extension WHERE extname = 'vector';
-- Expected: 0.8.0 or higher
SELECT COUNT(*) FROM search_chunks;  -- 0 (empty is correct)
SELECT COUNT(*) FROM search_index_registry;  -- 0 (empty is correct)
```

**Rollback**:

```sql
DROP TABLE IF EXISTS search_chunks CASCADE;
DROP TABLE IF EXISTS search_index_registry CASCADE;
DROP EXTENSION IF EXISTS vector;
```

---

### Phase 2: Provisioning Integration (Tenant Index Lifecycle)

**Goal**: Replace `_create_azure_search_index` / `_delete_azure_search_index` in `worker.py` with pgvector DDL helpers.

**Steps**:

1. Implement `_create_pgvector_index(tenant_id, db_pool)` in `worker.py`
2. Implement `_delete_pgvector_index(tenant_id, db_pool)` in `worker.py`
3. Update `_step_create_search_index()` to call pgvector helper
4. Update `_rollback_create_search_index()` to call pgvector cleanup
5. Remove `AZURE_SEARCH_ENDPOINT` and `AZURE_SEARCH_ADMIN_KEY` env var reads
6. Remove the `urllib.request` HTTP calls

**Validation**:

- Provision a test tenant → verify partial HNSW index created:
  ```sql
  SELECT indexname FROM pg_indexes
  WHERE tablename = 'search_chunks'
  AND indexname LIKE 'idx_sc_embedding_t_%';
  ```
- Deprovision test tenant → verify index dropped and rows cleaned up

**Rollback**: Revert `worker.py` to previous version (git revert). No schema changes needed.

---

### Phase 3: Indexing Pipeline (Write Path)

**Goal**: Implement `upsert_chunks()` so document sync actually populates `search_chunks`.

**Steps**:

1. Implement `PgVectorSearchClient.upsert_chunks()` in `vector_search.py`
2. Implement `PgVectorSearchClient.delete_by_index()` and `delete_by_source_file()`
3. Add `VectorSearchService.upsert_chunks()` method that delegates to client
4. Add `VectorSearchService.delete_chunks()` method
5. Update `get_search_client()` factory to return `PgVectorSearchClient` for `local`/`aws`

**Validation**:

- Trigger a SharePoint sync for a test tenant
- Verify rows appear in `search_chunks`:
  ```sql
  SELECT COUNT(*), source_type, index_id
  FROM search_chunks
  WHERE tenant_id = :test_tenant_id
  GROUP BY source_type, index_id;
  ```
- Verify embeddings stored: `SELECT length(embedding::text) FROM search_chunks LIMIT 1;`
- Verify tsvector populated: `SELECT fts_doc IS NOT NULL FROM search_chunks LIMIT 5;`

**Rollback**: Revert `vector_search.py` changes. `search_chunks` rows can be left (idempotent on next sync).

---

### Phase 4: Query Path (Read Path)

**Goal**: Implement `PgVectorSearchClient.knn_search()` so chat actually retrieves from pgvector.

**Steps**:

1. Implement hybrid search SQL in `PgVectorSearchClient.knn_search()`
2. Wire `db_pool` into `get_search_client()` factory
3. Add RRF score normalization before `RetrievalConfidenceCalculator`
4. Update `VectorSearchService.search()` to pass `query_text` (currently only passes vector)
5. Set `hnsw.ef_search = 100` per-query via `SET LOCAL`

**Validation**:

- End-to-end chat test: Upload document → ask question → verify sources appear in response
- Unit test: `PgVectorSearchClient.knn_search()` with known chunks → verify ordering
- Integration test: Hybrid vs vector-only — confirm hybrid returns better results for keyword-heavy queries

---

### Phase 5: Cleanup

**Goal**: Remove all Azure AI Search dead code.

**Steps**:

1. Remove `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_ADMIN_KEY` from `.env.example`
2. Remove `LocalSearchClient` class (replaced by `PgVectorSearchClient`)
3. Remove `CLOUD_PROVIDER=azure` branch from `_step_create_search_index()`
4. Update `test_provisioning_rollback.py`: replace Azure Search env var mocks with pgvector DDL failure simulation
5. Update `test_vector_search.py`: replace `AsyncMock` with real DB fixtures

---

## 3. Test Strategy

### Unit Tests (Tier 1)

**File**: `tests/unit/test_vector_search.py`

New tests to add:

- `test_pgvector_client_upsert_chunks`: Insert chunks, verify in DB
- `test_pgvector_client_knn_search_hybrid`: Insert known chunks, query, verify RRF ordering
- `test_pgvector_client_knn_search_vector_only`: Short query → falls back to vector-only
- `test_pgvector_client_delete_by_source`: Verify deletion scoped to `source_file_id`
- `test_rrf_score_normalization`: Scores map to [0, 1]

**Per gold standards: NO MOCKING in Tier 2/3.** Unit tests use a real in-process test DB with pgvector extension.

### Integration Tests (Tier 2)

New test file: `tests/integration/test_pgvector_search.py`

- `test_tenant_provisioning_creates_hnsw_index`: Full provisioning run → partial index exists
- `test_tenant_deprovisioning_drops_index`: Deprovision → index gone, rows deleted
- `test_hybrid_search_returns_relevant_chunks`: Insert 10 chunks, search, verify top result
- `test_conversation_doc_isolation`: Two users, same tenant → can only see own docs
- `test_kb_isolation_across_tenants`: Two tenants, same content → neither sees other's results
- `test_cache_invalidation_on_sync`: Sync → cache miss on next query

Update: `tests/integration/test_provisioning_rollback.py`

- Replace Azure Search env var patches with pgvector DDL failure simulation (patch `asyncpg.execute` to raise `asyncpg.PostgresError`)

---

## 4. Risk Register

| Risk                                                   | Likelihood | Impact | Mitigation                                                                                                                                                            |
| ------------------------------------------------------ | ---------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `halfvec` not available on Aurora version              | Low        | High   | Verify `pg_extension` and Aurora version before migration; use `vector(1536)` as fallback (requires truncating embeddings at generation time)                         |
| HNSW index build causes table lock                     | Low        | Medium | Use `CREATE INDEX CONCURRENTLY` — non-blocking. Monitor for long-running vacuums that could delay CONCURRENTLY                                                        |
| Partial index not used by query planner                | Low        | Medium | Verify with `EXPLAIN (ANALYZE)` — if planner chooses global index, add `WHERE tenant_id = $1` hint; partial indexes are reliably chosen when the WHERE clause matches |
| FTS quality gap vs Azure AI Search BM25                | Medium     | Low    | ts_rank_cd with normalization=32 covers most enterprise query patterns; add post-retrieval reranking if quality feedback signals degradation                          |
| RRF score normalization breaks confidence calc         | Low        | Low    | Unit tested; normalization is a pure function with no side effects                                                                                                    |
| `upsert_chunks` contention during high-throughput sync | Low        | Medium | Use batch inserts (100 chunks per executemany); ON CONFLICT condition (`content_hash IS DISTINCT FROM`) prevents unnecessary write amplification                      |
| Per-tenant HNSW index provisioning time                | Low        | Low    | On empty table, CREATE INDEX CONCURRENTLY takes < 1 second. At 50K chunks, < 30 seconds. Non-blocking.                                                                |

---

## 5. Rollback Plan

Since Azure AI Search is not currently in the production query path (all searches return empty today), any rollback is:

1. Revert the application code changes (git revert)
2. Leave `search_chunks` table in place (no data loss, just unused)
3. If needed, drop tables: `DROP TABLE search_chunks CASCADE; DROP TABLE search_index_registry CASCADE;`

There is no "revert to Azure AI Search" because Azure AI Search was never serving production queries.

---

## 6. Definition of Done

- [ ] `CREATE EXTENSION vector` verified on target Aurora instance
- [ ] Migrations v014, v015, v016 run successfully
- [ ] Tenant provisioning creates partial HNSW index
- [ ] Tenant deprovisioning drops index and cleans rows
- [ ] SharePoint sync populates `search_chunks` rows with `halfvec(3072)` embeddings
- [ ] Chat query retrieves relevant chunks via hybrid search
- [ ] Per-tenant isolation verified (cross-tenant rows not returned)
- [ ] Per-user isolation for conversation docs verified
- [ ] All unit tests pass (no mocks for search client)
- [ ] All integration tests pass against real DB
- [ ] `LocalSearchClient` removed
- [ ] Azure Search env vars removed from `.env.example`
- [ ] AZURE_SEARCH env var reads removed from `worker.py`

---

**Document Version**: 1.0
**Last Updated**: 2026-03-18
