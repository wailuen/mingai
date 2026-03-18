# 42. pgvector Schema Design

> **Status**: Architecture Design
> **Date**: 2026-03-18
> **Purpose**: Full SQL schema to replace all three Azure AI Search index types with pgvector tables.
> **Depends on**: `41-azure-search-touchpoints.md`

---

## 1. Design Principles

1. **Single table for all content** — `search_chunks` holds conversation docs, SharePoint KB, Google Drive KB, and future sources. Source type is a discriminator column.
2. **Per-tenant partial HNSW indexes** — Created at tenant provisioning, dropped at deprovisioning. Provides strong isolation without schema-per-tenant complexity.
3. **halfvec(3072)** — Use `halfvec` type (16-bit float) instead of `vector(3072)` (32-bit). This fits within pgvector's HNSW indexable limit (4,000 dims for halfvec), halves memory footprint, and matches text-embedding-3-large's output.
4. **Generated tsvector column** — `fts_doc` is computed from `title + content` automatically on insert/update, driving full-text search.
5. **RLS extends existing pattern** — The v002 RLS pattern is extended to cover `search_chunks` and `search_index_registry`.

---

## 2. Migration 1: Enable pgvector Extension

```sql
-- alembic/versions/v0XX_enable_pgvector.py

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("SET max_parallel_maintenance_workers = 4")  -- session-level for index builds

def downgrade():
    # Cannot drop extension if tables exist with vector columns
    op.execute("DROP EXTENSION IF EXISTS vector CASCADE")
```

---

## 3. Migration 2: search_index_registry Table

Logical index registry — replaces the concept of "named indexes" in Azure AI Search.

```sql
-- alembic/versions/v0XX_search_index_registry.py

CREATE TABLE search_index_registry (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    index_id        TEXT NOT NULL,          -- e.g. "idx_sp_a3f2b1c4d5e6", "{tenant_id}-{agent_id}"
    source_type     TEXT NOT NULL,          -- 'sharepoint' | 'google_drive' | 'conversation' | 'agent_kb'
    display_name    TEXT,                   -- Human-readable name shown in admin UI
    embedding_model TEXT NOT NULL DEFAULT 'text-embedding-3-large',
    dimensions      INTEGER NOT NULL DEFAULT 3072,
    doc_count       INTEGER NOT NULL DEFAULT 0,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    storage_bytes   BIGINT NOT NULL DEFAULT 0,
    version         INTEGER NOT NULL DEFAULT 1,   -- Incremented on every index update (cache invalidation)
    last_indexed_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(tenant_id, index_id)
);

-- RLS: tenants see only their own index registry entries
ALTER TABLE search_index_registry ENABLE ROW LEVEL SECURITY;
CREATE POLICY search_index_registry_tenant_isolation ON search_index_registry
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE INDEX idx_sir_tenant ON search_index_registry(tenant_id);
CREATE INDEX idx_sir_index_id ON search_index_registry(index_id);
```

---

## 4. Migration 3: search_chunks Table

Main content store. Replaces all three Azure AI Search index types.

```sql
-- alembic/versions/v0XX_search_chunks.py

CREATE TABLE search_chunks (
    -- Identity
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_key       TEXT NOT NULL,          -- Stable idempotency key: "{source_id}_{file_id}_{chunk_index}"
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    index_id        TEXT NOT NULL,          -- FK to search_index_registry.index_id (logical)
    source_type     TEXT NOT NULL,          -- 'sharepoint' | 'google_drive' | 'conversation' | 'agent_kb'

    -- Ownership (for conversation docs: user-level; for KB: tenant-level)
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    conversation_id UUID,                   -- Only for source_type = 'conversation'
    integration_id  UUID,                   -- Only for SP/GDrive: FK to integrations.id

    -- Content
    content         TEXT NOT NULL,
    title           TEXT,
    source_url      TEXT,
    file_name       TEXT,
    file_type       TEXT,                   -- 'pdf' | 'docx' | 'xlsx' | 'pptx' | 'txt' | 'md' | 'image'
    chunk_type      TEXT NOT NULL DEFAULT 'text',  -- 'text' | 'table' | 'slide' | 'section' | 'image'
    chunk_index     INTEGER NOT NULL DEFAULT 0,

    -- Type-specific metadata (nullable — populated by source type)
    page_number     INTEGER,
    slide_number    INTEGER,
    slide_title     TEXT,
    sheet_name      TEXT,
    row_range       TEXT,
    section_heading TEXT,
    image_type      TEXT,                   -- 'embedded' | 'standalone'
    is_image_description BOOLEAN DEFAULT FALSE,

    -- Source metadata
    source_file_id  TEXT,                   -- e.g. SharePoint item ID, GDrive file ID
    content_hash    TEXT,                   -- sha256 of content for dedup detection
    etag            TEXT,                   -- Source system etag for change detection
    source_modified_at TIMESTAMPTZ,
    file_size_bytes BIGINT,

    -- Search vectors
    embedding       halfvec(3072),          -- halfvec: 16-bit float, fits HNSW index at 3072 dims
    fts_doc         tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                        setweight(to_tsvector('english', coalesce(content, '')), 'D')
                    ) STORED,

    -- Timestamps
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Idempotency: same chunk_key + index_id must not duplicate
    UNIQUE(tenant_id, index_id, chunk_key)
);

-- RLS: tenant isolation
ALTER TABLE search_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY search_chunks_tenant_isolation ON search_chunks
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ── Indexes ──────────────────────────────────────────────────────────────────

-- Full-text search (GIN — mandatory for @@ operator performance)
CREATE INDEX CONCURRENTLY idx_sc_fts
    ON search_chunks USING GIN(fts_doc);

-- Conversation document lookup (filters by conversation + user for per-user isolation)
CREATE INDEX CONCURRENTLY idx_sc_conversation
    ON search_chunks(tenant_id, conversation_id, user_id)
    WHERE source_type = 'conversation';

-- Integration/KB lookup
CREATE INDEX CONCURRENTLY idx_sc_integration
    ON search_chunks(tenant_id, integration_id)
    WHERE integration_id IS NOT NULL;

-- Index ID lookup (for KB searches across an entire source)
CREATE INDEX CONCURRENTLY idx_sc_index_id
    ON search_chunks(tenant_id, index_id);

-- Content hash for dedup detection during sync
CREATE INDEX CONCURRENTLY idx_sc_content_hash
    ON search_chunks(tenant_id, content_hash)
    WHERE content_hash IS NOT NULL;

-- ── GLOBAL HNSW vector index (fallback while per-tenant partial indexes are being built) ──
-- Note: Per-tenant partial HNSW indexes are created at tenant provisioning time.
-- This global index serves queries during the provisioning window.
CREATE INDEX CONCURRENTLY idx_sc_embedding_global
    ON search_chunks USING hnsw(embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 128);
```

---

## 5. Per-Tenant Partial HNSW Index (Created at Provisioning)

For each tenant, a dedicated partial HNSW index scoped to `tenant_id`:

```sql
-- Generated at provisioning time (tenant_id known):
CREATE INDEX CONCURRENTLY idx_sc_embedding_t_{tenant_short_id}
    ON search_chunks USING hnsw(embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 128)
    WHERE tenant_id = '{tenant_id}'::uuid;

-- Dropped at deprovisioning:
DROP INDEX CONCURRENTLY IF EXISTS idx_sc_embedding_t_{tenant_short_id};
DELETE FROM search_chunks WHERE tenant_id = '{tenant_id}'::uuid;
DELETE FROM search_index_registry WHERE tenant_id = '{tenant_id}'::uuid;
```

`tenant_short_id` = `re.sub(r"[^a-z0-9]", "_", str(tenant_id).lower())[:16]` (safe for index names).

**Why partial HNSW per tenant?**

- The query planner will use the partial index for any query with `WHERE tenant_id = $1`
- ANN search scans only that tenant's vectors — no post-filtering needed
- At 10-50 tenants: 50 HNSW indexes, each covering 2K-50K docs → fast, clean isolation
- Drop/create is non-blocking (`CONCURRENTLY`) so provisioning and deprovisioning don't lock the table

---

## 6. Field Mapping: Azure AI Search → pgvector

### Conversation Documents

| Azure AI Search Field               | pgvector Column               | Notes                                        |
| ----------------------------------- | ----------------------------- | -------------------------------------------- |
| `id` (`{doc_id}_{chunk_idx}`)       | `chunk_key`                   | Stable idempotency key                       |
| `document_id`                       | derived from `chunk_key`      | Split on last `_`                            |
| `conversation_id`                   | `conversation_id`             | Direct mapping                               |
| `user_id`                           | `user_id`                     | Direct mapping                               |
| `chunk_index`                       | `chunk_index`                 | Direct mapping                               |
| `file_type`                         | `file_type`                   | Direct mapping                               |
| `chunk_type`                        | `chunk_type`                  | Direct mapping                               |
| `content`                           | `content`                     | Direct mapping                               |
| `content_vector` (3072-dim float32) | `embedding` (halfvec(3072))   | Float32 → float16, acceptable precision loss |
| `document_name`                     | `file_name`                   | Renamed                                      |
| `uploaded_at`                       | `created_at`                  | Mapped to base column                        |
| `sheet_name`, `row_range`           | `sheet_name`, `row_range`     | Direct mapping                               |
| `slide_number`, `slide_title`       | `slide_number`, `slide_title` | Direct mapping                               |
| `section_heading`                   | `section_heading`             | Direct mapping                               |
| `page_number`                       | `page_number`                 | Direct mapping                               |
| `image_type`, `location`            | `image_type`                  | `location` dropped (not used in retrieval)   |

**Isolation**: `WHERE tenant_id = $1 AND conversation_id = $2 AND user_id = $3`

### SharePoint / Google Drive KB

| Azure AI Search Field                                          | pgvector Column      | Notes                  |
| -------------------------------------------------------------- | -------------------- | ---------------------- |
| `id` (`{index_id}_{file_id}_{chunk_idx}`)                      | `chunk_key`          | Stable idempotency key |
| `content`                                                      | `content`            | Direct mapping         |
| `content_vector`                                               | `embedding`          | halfvec(3072)          |
| `title`                                                        | `title`              | Direct mapping         |
| `source_file`                                                  | `file_name`          | Renamed                |
| `source_url`                                                   | `source_url`         | Direct mapping         |
| `file_type`                                                    | `file_type`          | Direct mapping         |
| `page_number`, `slide_number`, `sheet_name`, `section_heading` | Direct mapping       | Same columns           |
| `etag`                                                         | `etag`               | Direct mapping         |
| `content_hash`                                                 | `content_hash`       | Direct mapping         |
| `chunk_type`, `image_type`, `is_image_description`             | Direct mapping       | Same columns           |
| `last_modified`                                                | `source_modified_at` | Renamed                |
| `file_size`                                                    | `file_size_bytes`    | Renamed                |

**Isolation**: `WHERE tenant_id = $1 AND index_id = $2`

---

## 7. Alembic Migration Order

```
v001_initial_schema.py         (existing — 22 tables)
...
v013_cache_analytics_events.py (existing)
v014_enable_pgvector.py        (NEW) — CREATE EXTENSION vector
v015_search_index_registry.py  (NEW) — registry table + RLS
v016_search_chunks.py          (NEW) — main table + GIN + global HNSW
```

Per-tenant partial HNSW indexes are created at runtime (tenant provisioning) — NOT in migrations.

---

## 8. Performance Configuration

```sql
-- Set on each search query session (or Aurora parameter group)
SET hnsw.ef_search = 100;        -- Default 40; higher = better recall, slower

-- Set during index builds (provisioning time)
SET maintenance_work_mem = '4GB';
SET max_parallel_maintenance_workers = 4;
```

**Aurora Parameter Group** recommendations:

- `shared_buffers`: 25% of instance RAM (Aurora manages this automatically)
- `effective_cache_size`: 75% of instance RAM
- Ensure `vector` extension is in `shared_preload_libraries` if Aurora version requires it (most don't)

---

## 9. Index Size Estimates

For 50 enterprise tenants, avg 10,000 docs/tenant, avg 5 chunks/doc = 2.5M chunks:

| Component                  | Size                                |
| -------------------------- | ----------------------------------- |
| content (avg 500 chars)    | ~1.2 GB                             |
| embedding halfvec(3072)    | 2.5M × 3072 × 2 bytes = ~14.6 GB    |
| HNSW global index          | ~14.6 GB (same as embedding column) |
| 50 per-tenant partial HNSW | ~14.6 GB total (shared with global) |
| tsvector (GIN)             | ~0.3 GB                             |
| metadata columns           | ~1 GB                               |
| **Total**                  | **~32 GB**                          |

Fits comfortably on Aurora `r7g.2xlarge` (64 GB RAM). At 10M chunks, step up to `r7g.4xlarge`.

---

**Document Version**: 1.0
**Last Updated**: 2026-03-18
