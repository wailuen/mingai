# 40. pgvector Migration Overview — Replacing Azure AI Search

> **Status**: Architecture Decision
> **Date**: 2026-03-18
> **Decision**: Replace Azure AI Search with pgvector on Aurora PostgreSQL
> **Driver**: AWS-first deployment, data sovereignty, zero third-party dependency
> **Depends on**: `05-cloud-agnostic-deployment.md`, `20-document-upload-architecture.md`, `19-sharepoint-sync-architecture.md`, `33-agent-library-studio-architecture.md`

---

## 1. Decision Summary

Azure AI Search is removed from the mingai stack. All vector and hybrid search is handled by **pgvector** running on the existing Aurora PostgreSQL instance.

This is not a tactical cost cut — it is a strategic positioning decision that expands the total addressable market by making mingai deployable in regulated and sovereign-cloud environments where external AI data processors are prohibited.

---

## 2. What Azure AI Search Was Doing

Three distinct search workloads were served by Azure AI Search:

| Workload                          | Index Name Pattern                       | Purpose                                            |
| --------------------------------- | ---------------------------------------- | -------------------------------------------------- |
| Conversation document upload      | `mingai-conversation-documents` (shared) | Per-user, per-conversation RAG from uploaded files |
| SharePoint / Google Drive KB sync | `mingai-sp-{idx_sp_hash}` (per-source)   | Tenant-scoped enterprise knowledge base            |
| Agent KB (tenant provisioning)    | `mingai-{tenant_id}` (per-tenant)        | Per-agent vector index, Phase 2 only               |

All three used:

- `text-embedding-3-large` vectors, 3072 dimensions
- Hybrid BM25 + vector search
- Per-tenant or per-user query-time filtering

---

## 3. Why pgvector

### Technical Fit

- Aurora PostgreSQL is already in the stack (v002 RLS already in use across 21 tables)
- pgvector 0.8.0 ships on Aurora PostgreSQL 15+ with `halfvec` type (supports 3072 dims)
- HNSW index type handles incremental inserts from sync pipelines without degradation
- RLS + partial HNSW indexes per tenant provide strong isolation at 10-50 tenant scale

### Strategic Fit

- **Single data processor**: Customer documents never leave PostgreSQL. The data path shrinks from PostgreSQL + Azure AI Search to PostgreSQL only.
- **Any-cloud deployment**: Removes the last Azure-specific service from the hot path. mingai can now deploy on AWS, GCP, any Kubernetes + PostgreSQL environment, including air-gapped installations.
- **Regulated market access**: Financial services, healthcare, government, and legal verticals that prohibit external AI data processors become directly addressable.
- **Cost**: pgvector storage is 2-3 orders of magnitude cheaper than Azure AI Search at current scale.

### What Is Sacrificed

- **Corpus-aware BM25**: ts_rank_cd is not true BM25 (no global IDF). Mitigation: post-retrieval reranking or pg_bm25 extension if quality gaps emerge.
- **Managed auto-scaling**: Azure AI Search scales partitions automatically. pgvector requires Aurora instance sizing decisions. Manageable at current scale.
- **Azure skillsets**: No equivalent in pgvector — handled in application layer (already is).

---

## 4. Three-Table Design

The replacement uses three PostgreSQL tables in place of all Azure AI Search indexes:

```
search_chunks          — All indexed content (all sources, all tenants)
search_index_registry  — Logical index metadata (maps index_id to tenant, source type)
```

The `search_chunks` table replaces every Azure AI Search index. Tenant isolation is enforced via:

1. Row-Level Security (existing pattern)
2. `WHERE tenant_id = $1` in all queries
3. Per-tenant partial HNSW indexes (created at tenant provisioning)

See `42-pgvector-schema-design.md` for full schema.

---

## 5. Hybrid Search Replacement

Azure AI Search hybrid mode = BM25 + vector, scored by internal Reciprocal Rank Fusion.

Replacement = PostgreSQL `tsvector` (GIN index) + pgvector HNSW, fused by **explicit RRF SQL**.

See `43-hybrid-search-implementation.md` for the SQL pattern.

---

## 6. Code Change Surface

| File                                | Change Required                                                                       |
| ----------------------------------- | ------------------------------------------------------------------------------------- |
| `app/modules/chat/vector_search.py` | Implement `PgVectorSearchClient` replacing `LocalSearchClient` stub                   |
| `app/modules/tenants/worker.py`     | Replace `_create_azure_search_index` / `_delete_azure_search_index` with pgvector DDL |
| `app/modules/documents/indexing.py` | Implement `upsert_chunks()` against `search_chunks` table                             |
| `app/core/config.py`                | Remove azure*search*\* settings; no new settings needed (uses existing DB)            |
| `alembic/versions/`                 | New migration: CREATE EXTENSION vector, search_chunks, search_index_registry          |
| `tests/`                            | Update unit + integration tests; remove Azure Search mocks                            |

See `41-azure-search-touchpoints.md` for full change inventory.

---

## 7. Migration Strategy

**Phase 1**: Schema + infrastructure (pgvector tables, HNSW indexes, RLS policies)
**Phase 2**: Indexing pipeline (implement upsert_chunks, connect sync workers)
**Phase 3**: Query path (implement PgVectorSearchClient, wire into VectorSearchService)
**Phase 4**: Remove Azure AI Search code paths and env vars

No parallel-run required — Azure AI Search search path is not in production use (`LocalSearchClient` returns empty results today). The replacement is net-new functionality.

See `44-migration-strategy.md` for full plan.

---

## 8. Document Index

| File                                  | Contents                                     |
| ------------------------------------- | -------------------------------------------- |
| `40-pgvector-migration-overview.md`   | This document — decision, rationale, map     |
| `41-azure-search-touchpoints.md`      | Every code file that needs to change         |
| `42-pgvector-schema-design.md`        | Full SQL schema design                       |
| `43-hybrid-search-implementation.md`  | Hybrid search SQL, tuning, cache integration |
| `44-migration-strategy.md`            | Phase-by-phase plan, risks, rollback         |
| `45-pgvector-competitive-analysis.md` | Competitive landscape, value props, USPs     |

---

**Document Version**: 1.0
**Last Updated**: 2026-03-18
