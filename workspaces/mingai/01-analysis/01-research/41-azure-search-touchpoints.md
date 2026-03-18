# 41. Azure AI Search — Complete Codebase Touchpoint Inventory

> **Status**: Reference Document
> **Date**: 2026-03-18
> **Purpose**: Exhaustive inventory of every Azure AI Search touchpoint in the mingai backend. This is the change surface for the pgvector migration.

---

## 1. Environment & Configuration

### Missing from Config Template

`AZURE_SEARCH_ENDPOINT` and `AZURE_SEARCH_ADMIN_KEY` are read directly from `os.environ.get()` in `worker.py` — they are **not** in:

- `src/backend/.env.example`
- `src/backend/app/core/config.py` (Settings class)

**Action**: Remove these env vars entirely. No replacement needed — pgvector uses the existing `DATABASE_URL`.

### Missing Package Dependency

`azure-search-documents` SDK is **not** in `pyproject.toml`. The worker uses raw `urllib.request` calls. No SDK removal needed — just remove the raw HTTP calls.

---

## 2. Core Abstraction Layer

### `src/backend/app/modules/chat/vector_search.py`

**Classes**:

- `SearchResult` (lines 15-33) — dataclass: `title, content, score, source_url, document_id`. **Keep as-is**.
- `LocalSearchClient` (lines 36-67) — stub that returns `[]`. **Replace with `PgVectorSearchClient`**.
- `VectorSearchService` (lines 93-199) — cloud-agnostic service. **Add `upsert_chunks()` and `delete_chunks()` methods**.
- `RetrievalConfidenceCalculator` (lines 169-199) — pure calculation, no search dependency. **Keep as-is**.

**Key facts**:

- Index name format used: `{tenant_id}-{agent_id}` (line 138)
- `LocalSearchClient.knn_search()` signature: `(index, vector, top_k)` — this is the interface `PgVectorSearchClient` must satisfy
- `upsert_chunks()` is called from `indexing.py` line 82-93 but **not yet defined** on `VectorSearchService`

**Changes required**:

1. Implement `PgVectorSearchClient` class with real pgvector queries
2. Implement `VectorSearchService.upsert_chunks()`
3. Implement `VectorSearchService.delete_chunks()`
4. Update `get_search_client()` factory: `provider == "local"` → returns `PgVectorSearchClient`

---

## 3. Tenant Provisioning & Index Lifecycle

### `src/backend/app/modules/tenants/worker.py`

**Functions to replace**:

| Function                                | Lines   | Current Behavior                                      | Replacement                                                               |
| --------------------------------------- | ------- | ----------------------------------------------------- | ------------------------------------------------------------------------- |
| `_create_azure_search_index(tenant_id)` | 558-614 | POST to Azure AI Search REST API to create HNSW index | `CREATE INDEX CONCURRENTLY` on `search_chunks` with partial WHERE clause  |
| `_delete_azure_search_index(tenant_id)` | 616-644 | DELETE to Azure AI Search REST API                    | `DROP INDEX IF EXISTS` + `DELETE FROM search_chunks WHERE tenant_id = $1` |
| `_step_create_search_index()`           | 234-264 | State machine step calling above                      | Update to call pgvector DDL                                               |
| `_rollback_create_search_index()`       | 266-275 | Calls delete function                                 | Update to call pgvector cleanup                                           |

**Current Azure AI Search schema** (lines 578-596):

```python
{
  "fields": [
    {"name": "id", "type": "Edm.String", "key": True},
    {"name": "tenant_id", "type": "Edm.String", "filterable": True},
    {"name": "content", "type": "Edm.String", "searchable": True},
    {"name": "embedding", "type": "Collection(Edm.Single)", "dimensions": 1536}
  ]
}
```

Note: Schema uses 1536 dims but embeddings in pipeline are 3072-dim. **pgvector will use `halfvec(3072)`**.

**Environment variables to remove**:

- `os.environ.get("AZURE_SEARCH_ENDPOINT", "")` (lines 567, 620)
- `os.environ.get("AZURE_SEARCH_ADMIN_KEY", "")` (lines 568, 621)

**HTTP API calls to remove**:

- `urllib.request.Request(f"{endpoint}/indexes?api-version=2023-11-01", ...)` (lines 600-608)
- `urllib.request.Request(f"{endpoint}/indexes/{index_name}?api-version=2023-11-01", ...)` (lines 630-633)
- `urllib.request.urlopen(req, timeout=30)` (lines 609, 636)

---

## 4. Document Indexing Pipeline

### `src/backend/app/modules/documents/indexing.py`

**Class**: `DocumentIndexingPipeline`

**Key methods**:

- `process_file()` (lines 37-140) — main entry point, orchestrates chunking + embedding
- `_chunk_text()` (lines 204-227) — 512-token chunks, 50-token overlap

**Vector service call** (lines 82-93):

```python
embedding = await embedding_service.embed(chunk, tenant_id=tenant_id)
await vector_service.upsert_chunks(
    tenant_id=tenant_id,
    integration_id=integration_id,
    file_path=file_path,
    chunk_index=i,
    chunk_text=chunk,
    embedding=embedding,
)
```

**Status**: `upsert_chunks()` is called but **not defined** in `VectorSearchService`. This is the primary unimplemented method that the pgvector migration must implement.

**Changes required**:

1. `VectorSearchService.upsert_chunks()` must INSERT into `search_chunks` table
2. Must handle upsert (ON CONFLICT DO UPDATE) for sync re-runs
3. Must update `search_index_registry.doc_count` after batch

---

## 5. SharePoint Sync

### `src/backend/app/modules/documents/sharepoint.py`

**No direct Azure AI Search calls**. Delegates to `DocumentIndexingPipeline`.

**Cache invalidation** (lines 465-483):

```python
asyncio.create_task(increment_index_version(tenant_id, integration_id))
sem_cache = SemanticCacheService()
await sem_cache.invalidate_tenant(tenant_id)
```

This pattern is **compatible with pgvector** — no changes needed. Redis version counter invalidates search result cache regardless of backend.

---

## 6. Google Drive Sync

### `src/backend/app/modules/documents/google_drive/sync_worker.py`

**No direct Azure AI Search calls**. Same delegation pattern as SharePoint.

**Cache invalidation** (lines 765-777): Same pattern as SharePoint. **No changes needed**.

---

## 7. Search Result Cache

### `src/backend/app/core/cache_search.py`

**Class**: `SearchCacheService`

**Redis key pattern** (line 212):

```
mingai:{tenant_id}:search:{index_id}:{emb_hash16}:{params_hash8}
```

**Version-based invalidation**: Each index has a version counter. Stale on version mismatch.

**Status**: Fully compatible with pgvector. The cache sits in front of the search call — it doesn't care whether the backend is Azure AI Search or pgvector. **No changes needed**.

---

## 8. Configuration

### `src/backend/app/core/config.py`

**Status**: Azure Search settings (`azure_search_endpoint`, `azure_search_admin_key`, `azure_search_api_version`) are **not** in the Settings class. They are read via raw `os.environ.get()` in worker.py.

**Action**: Remove the `os.environ.get()` calls in worker.py. Nothing to change in config.py.

---

## 9. Database Migrations

### `src/backend/alembic/versions/`

**Current state**: No existing migration references Azure AI Search. The Azure AI Search index lifecycle is application-driven (REST API calls at runtime), not schema-driven.

**New migrations needed**:

1. `v0XX_pgvector_extension.py` — `CREATE EXTENSION IF NOT EXISTS vector`
2. `v0XX_search_chunks.py` — `CREATE TABLE search_chunks (...)`, GIN index, HNSW index
3. `v0XX_search_index_registry.py` — `CREATE TABLE search_index_registry (...)`

See `42-pgvector-schema-design.md` for full DDL.

---

## 10. Test Files

### `src/backend/tests/unit/test_vector_search.py`

**Lines 1-270**. Uses `AsyncMock` for search client. Tests:

- `SearchResult` dataclass
- `VectorSearchService.search()` — verifies index name format `{tenant_id}-{agent_id}`
- `RetrievalConfidenceCalculator`

**Changes required**:

1. Replace `AsyncMock` with actual test DB calls (pgvector runs in test DB — no mocking needed)
2. Add tests for `upsert_chunks()`, `delete_chunks()`
3. Add tests for hybrid search (vector + FTS results)

### `src/backend/tests/integration/test_provisioning_rollback.py`

**Lines 335-345**. Tests Azure Search provisioning failure:

```python
"AZURE_SEARCH_ENDPOINT": "",
"AZURE_SEARCH_ADMIN_KEY": "",
```

**Changes required**: Replace with pgvector provisioning rollback test (DDL failure → rollback partial index creation).

---

## 11. Change Summary

| File                                              | Type of Change                                                                                  | Priority |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------- | -------- |
| `app/modules/chat/vector_search.py`               | Implement `PgVectorSearchClient`, add `upsert_chunks()`, `delete_chunks()`                      | P0       |
| `app/modules/tenants/worker.py`                   | Replace Azure REST calls with pgvector DDL                                                      | P0       |
| `app/modules/documents/indexing.py`               | No changes to pipeline; `upsert_chunks()` implementation in vector_search.py satisfies the call | P0       |
| `alembic/versions/`                               | 2 new migrations (extension + tables)                                                           | P0       |
| `tests/unit/test_vector_search.py`                | Update mocks → real DB, add new tests                                                           | P1       |
| `tests/integration/test_provisioning_rollback.py` | Update Azure Search test → pgvector                                                             | P1       |
| `.env.example`                                    | Remove AZURE*SEARCH*\* vars                                                                     | P2       |

---

**Document Version**: 1.0
**Last Updated**: 2026-03-18
