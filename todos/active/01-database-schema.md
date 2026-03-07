# Database, Schema, Migration & Redis Todo List

**Generated from**: Plans 01-10 in `workspaces/mingai/02-plans/`
**Stack**: FastAPI + PostgreSQL (RDS Aurora) + Redis + Alembic + Kailash DataFlow
**Convention**: All tables require `tenant_id` + RLS unless explicitly noted. All Redis keys prefixed `mingai:{tenant_id}:`.

---

## Plan 01+02: Core Multi-Tenant Migration

### TODO DB-001: Create `tenants` table via Alembic migration

**Effort**: 3h
**Depends on**: none
**Description**: Create the `tenants` table as the root tenant registry. This table holds tenant metadata, plan tier, lifecycle status, and is the FK target for `tenant_id` on all other tables. The status column implements a state machine: Draft > Active > Suspended > ScheduledDeletion > Deleted.
**Acceptance criteria**:

- [ ] Table created with columns: `id UUID PRIMARY KEY`, `name VARCHAR NOT NULL`, `plan VARCHAR NOT NULL CHECK (plan IN ('starter','professional','enterprise'))`, `status VARCHAR NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','suspended','scheduled_deletion','deleted'))`, `owner_id UUID`, `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()`, `migrated_from VARCHAR`
- [ ] RLS policy applied: `USING (id = current_setting('app.tenant_id')::UUID)` for tenant-scoped access; platform bypass policy for `scope = 'platform'`
- [ ] Default tenant row seeded: `id='default'`, `plan='enterprise'`, `status='active'`, `migrated_from='single_tenant'`
- [ ] Alembic migration file `002_create_tenant_tables.py` contains this table
      **Notes**: The `tenants` table has a special RLS policy where `tenant_id` IS the `id` column itself (self-referencing). Platform admin bypass policy required for cross-tenant operations.

---

### TODO DB-002: Create `tenant_configs` table via Alembic migration

**Effort**: 4h
**Depends on**: DB-001
**Description**: Create the per-tenant configuration table replacing the `@lru_cache` Settings singleton. Stores LLM provider config, BYOLLM credentials, rate limits, token budgets, and feature flags. This is the single source of truth for tenant runtime config, cached in Redis with 15-min TTL.
**Acceptance criteria**:

- [ ] Table created with columns: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `config_type VARCHAR NOT NULL DEFAULT 'llm_config'`, `provider VARCHAR NOT NULL DEFAULT 'azure_openai'`, `primary_model VARCHAR NOT NULL`, `intent_model VARCHAR NOT NULL`, `api_endpoint VARCHAR NOT NULL`, `api_key_ref VARCHAR NOT NULL`, `max_tokens_per_request INTEGER DEFAULT 4096`, `monthly_token_budget BIGINT DEFAULT 10000000`, `rate_limit_rpm INTEGER DEFAULT 60`, `byollm_enabled BOOLEAN DEFAULT FALSE`, `byollm_provider VARCHAR`, `byollm_key_ref VARCHAR`, `jwt_version VARCHAR(2) DEFAULT 'v2'`, `updated_at TIMESTAMPTZ DEFAULT now()`, `updated_by VARCHAR`, `UNIQUE (tenant_id, config_type)`
- [ ] RLS policy enabled with standard tenant isolation + platform bypass
- [ ] Default config row seeded from `.env` values with `tenant_id = 'default'`
- [ ] Memory policy fields included: `profile_learning_enabled BOOLEAN DEFAULT TRUE`, `working_memory_ttl_days INTEGER DEFAULT 7`, `max_memory_notes INTEGER DEFAULT 15`, `auto_extract_notes BOOLEAN DEFAULT TRUE`, `org_context_enabled BOOLEAN DEFAULT TRUE`, `profile_learning_trigger INTEGER DEFAULT 10`, `auth0_group_allowlist JSONB DEFAULT '[]'::jsonb`
      **Notes**: The `api_key_ref` is a secret manager URI (e.g., `secretsmanager://mingai/acme-corp/openai-key`), never the raw key. The `jwt_version` field supports dual-acceptance window during v1-to-v2 JWT migration (30 days).

---

### TODO DB-003: Add `tenant_id` column to all 19 existing tables

**Effort**: 6h
**Depends on**: DB-001
**Description**: Add `tenant_id UUID NOT NULL DEFAULT 'default'` column to every pre-existing table migrated from Cosmos DB. Each table gets a foreign key to `tenants(id)` and appropriate composite indexes. This is migration file `001_add_tenant_id_columns.py`.
**Acceptance criteria**:

- [ ] `tenant_id` column added to all 19 tables: `users`, `roles`, `user_roles`, `group_roles`, `indexes`, `conversations`, `messages`, `user_preferences`, `glossary_terms`, `user_profiles`, `profile_learning_events`, `consent_events`, `feedback`, `conversation_documents`, `document_chunks`, `usage_daily`, `events`, `question_categories`, `mcp_servers`, `notifications`
- [ ] Foreign key constraint `REFERENCES tenants(id)` on each `tenant_id` column
- [ ] Composite indexes added per table as specified in Plan 02 Section 1 (e.g., `(tenant_id, user_id, created_at DESC)` on conversations)
- [ ] `scope` column added to `roles` table: `VARCHAR DEFAULT 'tenant'`
- [ ] Migration is additive only (no data deletion, no column removal)
      **Notes**: The `DEFAULT 'default'` is removed after the 30-day validation period (separate cleanup migration). Table-specific indexes: `messages` gets BRIN on `created_at`; `glossary_terms` gets HNSW on embedding + GIN on `search_vector`; `user_profiles` gets `UNIQUE(tenant_id, user_id)`.

---

### TODO DB-004: Backfill `tenant_id = 'default'` on all existing rows

**Effort**: 2h
**Depends on**: DB-003
**Description**: Run batched UPDATE across all 19 tables to set `tenant_id = 'default'` for any rows where it is NULL. This is migration file `003_backfill_default_tenant.py`. Process 100 rows per batch with progress tracking.
**Acceptance criteria**:

- [ ] Each table updated in batches of 100 rows
- [ ] Progress logged per table: table name, total rows, migrated rows, duration
- [ ] Validation query after backfill: `COUNT(WHERE tenant_id = 'default') == COUNT(*)` per table
- [ ] Spot check: 10 random rows per table verify all fields preserved
      **Notes**: Expected to run in <1 hour for current data volumes. Must be run during a maintenance window. The default tenant record from DB-001 must exist before this runs.

---

### TODO DB-005: Enable Row-Level Security on all 22 tables

**Effort**: 4h
**Depends on**: DB-004
**Description**: Enable and force RLS on all 22 PostgreSQL tables (19 migrated + `tenants`, `tenant_configs`, `user_feedback`). Create two policies per table: `tenant_isolation` for tenant-scoped access and `platform_admin_bypass` for platform admin cross-tenant operations. This is migration file `004_add_rls_policies.py`.
**Acceptance criteria**:

- [ ] `ALTER TABLE {table} ENABLE ROW LEVEL SECURITY` and `ALTER TABLE {table} FORCE ROW LEVEL SECURITY` applied to all 22 tables
- [ ] `tenant_isolation` policy on each table: `USING (tenant_id = current_setting('app.tenant_id')::UUID) WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)`
- [ ] `platform_admin_bypass` policy on each table: `USING (current_setting('app.scope', true) = 'platform') WITH CHECK (current_setting('app.scope', true) = 'platform')`
- [ ] Integration test: query from tenant A cannot see tenant B rows
- [ ] Integration test: platform scope can see all rows
- [ ] `tenants` table uses special policy: `USING (id = current_setting('app.tenant_id')::UUID)` (self-referencing)
      **Notes**: RLS is applied using a non-superuser application role. The superuser role bypasses RLS by default. Application connections must use the restricted role. The dual-role strategy allows migration scripts to run as superuser while the app uses the RLS-enforced role.

---

### TODO DB-006: Create `user_feedback` table

**Effort**: 2h
**Depends on**: DB-001
**Description**: Create the user feedback table for thumbs up/down ratings on AI responses. Supports optional tags (inaccurate, incomplete, irrelevant, hallucinated) and free-text comments. Used by tenant admin satisfaction dashboard and platform admin health scoring.
**Acceptance criteria**:

- [ ] Table created with exact schema: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `conversation_id UUID NOT NULL REFERENCES conversations(id)`, `message_id UUID NOT NULL REFERENCES messages(id)`, `user_id UUID NOT NULL REFERENCES users(id)`, `rating SMALLINT NOT NULL CHECK (rating IN (1, -1))`, `tags TEXT[]`, `comment TEXT`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- [ ] RLS enabled with standard tenant isolation + platform bypass
- [ ] Index: `idx_user_feedback_message ON (tenant_id, message_id)`
- [ ] Index: `idx_user_feedback_user ON (tenant_id, user_id, created_at DESC)`
      **Notes**: `rating = 1` is thumbs up, `rating = -1` is thumbs down. Tags are optional and from a fixed set. This table feeds the platform admin health score (satisfaction component = 35% weight).

---

### TODO DB-007: Create `platform_members` table and seed platform roles

**Effort**: 3h
**Depends on**: DB-003
**Description**: Create the `platform_members` table for platform-scoped users (no `tenant_id` column) and seed 4 platform roles into the `roles` table with `scope = 'platform'`. Migration file `005_platform_rbac.py`. Add 5 new system functions for platform operations.
**Acceptance criteria**:

- [ ] `platform_members` table created: `id UUID PRIMARY KEY`, `user_id UUID NOT NULL REFERENCES users(id)`, `role_id UUID NOT NULL REFERENCES roles(id)`, `created_at TIMESTAMPTZ DEFAULT now()`, `created_by UUID`
- [ ] No `tenant_id` column on `platform_members` (platform-scoped table)
- [ ] No RLS on `platform_members` (access controlled by middleware checking `scope = 'platform'` in JWT)
- [ ] 4 platform roles seeded: `platform_admin`, `platform_operator`, `platform_support`, `platform_security` with `scope = 'platform'`
- [ ] 5 new platform functions added: `manage_tenants`, `manage_providers`, `manage_billing`, `view_cross_tenant`, `manage_platform_users`
- [ ] Existing 7 system roles untouched; `scope = 'tenant'` backfilled on all existing role rows
      **Notes**: Platform roles are additive, not a replacement. They cannot grant tenant-scoped permissions. Platform admin inherits all `manage_*` + `view_cross_tenant` functions. Platform support inherits `view_cross_tenant` only.

---

### TODO DB-008: Create `token_blocklist` table for JWT migration

**Effort**: 1h
**Depends on**: DB-001
**Description**: Create a table to track revoked JWT tokens during the v1-to-v2 migration window. Tokens added here are rejected by the auth middleware even if not yet expired. Entries are cleaned up after the 30-day dual-acceptance window closes.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `token_jti VARCHAR NOT NULL UNIQUE`, `revoked_at TIMESTAMPTZ DEFAULT now()`, `expires_at TIMESTAMPTZ NOT NULL`, `reason VARCHAR`
- [ ] Index on `token_jti` for fast lookup
- [ ] No tenant_id (tokens are cross-tenant by nature)
- [ ] pg_cron job or application-level cleanup: delete rows where `expires_at < now()` (run daily)
      **Notes**: This is a temporary migration table. After the 30-day JWT v1 acceptance window closes and all v1 tokens expire, this table can be dropped or repurposed for general token revocation.

---

### TODO DB-009: Partition `messages` table by month

**Effort**: 3h
**Depends on**: DB-003
**Description**: Convert the `messages` table to use PostgreSQL range partitioning on `created_at` by month. This is critical for query performance at scale since messages is the highest-volume table. Add BRIN index on `created_at` and denormalize `tenant_id` for RLS enforcement.
**Acceptance criteria**:

- [ ] `messages` table converted to partitioned table with `PARTITION BY RANGE (created_at)`
- [ ] Initial partitions created for current month + 3 months forward
- [ ] BRIN index on `created_at` within each partition
- [ ] `tenant_id` column present (denormalized from conversations) for direct RLS enforcement
- [ ] pg_cron job to auto-create new monthly partitions 3 months ahead
- [ ] Existing data migrated to correct partition
      **Notes**: Partitioning by month + tenant_id filtering via RLS provides efficient range scans for conversation history retrieval. BRIN index is more space-efficient than B-tree for append-only timestamp data.

---

### TODO DB-010: Partition `events` table by month

**Effort**: 2h
**Depends on**: DB-003
**Description**: Convert the unified `events` table (replacing deprecated `audit_logs` and `usage_events`) to monthly range partitioning on `timestamp`. This table stores all platform events and grows fastest after messages.
**Acceptance criteria**:

- [ ] `events` table partitioned by `RANGE (timestamp)` monthly
- [ ] BRIN index on `timestamp`
- [ ] pg_cron job for partition creation (3 months ahead) and cleanup (per retention policy)
- [ ] Historical data from `audit_logs` and `usage_events` merged into `events` before partitioning
      **Notes**: The `events` table absorbs data from the deprecated `audit_logs` and `usage_events` Cosmos DB containers. After migration and validation, the legacy containers are dropped.

---

### TODO DB-011: Partition `profile_learning_events` table by month

**Effort**: 1h
**Depends on**: DB-003
**Description**: Apply monthly range partitioning on the `profile_learning_events` audit trail table. This table has 30-day retention, so pg_cron drops old partitions automatically.
**Acceptance criteria**:

- [ ] Table partitioned by `RANGE (created_at)` monthly
- [ ] BRIN index on `created_at`
- [ ] pg_cron job drops partitions older than 30 days
- [ ] New partitions auto-created 3 months ahead
      **Notes**: 30-day retention means only 1-2 active partitions at any time. pg_cron partition drop is cleaner than DELETE WHERE for bulk expiry.

---

### TODO DB-012: Redis key namespace migration

**Effort**: 4h
**Depends on**: DB-001
**Description**: Migrate all existing Redis keys from `mingai:{key}` pattern to `mingai:{tenant_id}:{key}` pattern. Deploy a backward-compatible reader that checks new pattern first, falls back to old. Run a SCAN + RENAME migration script. Remove fallback after 24 hours.
**Acceptance criteria**:

- [ ] New code reads from `mingai:{tenant_id}:{key}` first, then falls back to `mingai:{key}`
- [ ] Migration script uses `SCAN` (not `KEYS`) to enumerate and `RENAME` to move keys
- [ ] All existing keys moved to `mingai:default:{key}` (default tenant)
- [ ] Platform-scoped keys remain at `mingai:platform:{key}` (no tenant prefix): `tenant_list`, `provider_status`, `feature_flags`
- [ ] Fallback logic removed after 24-hour validation window
- [ ] Integration test: old and new key patterns both resolve during migration window
      **Notes**: NEVER use `KEYS *` in production. Use `SCAN` with cursor iteration. The migration script should be idempotent (safe to re-run).

---

### TODO DB-013: Redis key structure for LLM config cache

**Effort**: 1h
**Depends on**: DB-002, DB-012
**Description**: Implement the Redis caching layer for tenant LLM config. On read: check Redis first, fall back to PostgreSQL. On write: update PostgreSQL, delete Redis key. Publish invalidation event for multi-instance deployments.
**Acceptance criteria**:

- [ ] Key pattern: `mingai:{tenant_id}:llm_config` with JSON-serialized value
- [ ] TTL: 900 seconds (15 minutes)
- [ ] On config update: `DEL mingai:{tenant_id}:llm_config` + publish to `mingai:config_invalidation` pub/sub channel
- [ ] Multi-instance support: all FastAPI instances subscribe to invalidation channel
- [ ] Cache miss rate <5% after warm-up (measured via metrics)
      **Notes**: The pub/sub invalidation is a belt-and-suspenders approach alongside the 15-min TTL. Even if pub/sub fails, eventual consistency is guaranteed by TTL expiry.

---

## Plan 02: LLM Library & Usage Tracking

### TODO DB-014: Create `llm_library` table for platform LLM catalog

**Effort**: 3h
**Depends on**: DB-001
**Description**: Create the platform-managed LLM model catalog table. Platform admin adds/removes providers and models, sets which are available per plan tier, and marks recommended models. This is the single source of truth for which LLMs tenants can select.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY`, `provider VARCHAR NOT NULL`, `model_name VARCHAR NOT NULL`, `display_name VARCHAR NOT NULL`, `description TEXT`, `tier_availability VARCHAR[] NOT NULL` (array of 'starter', 'professional', 'enterprise'), `recommended BOOLEAN DEFAULT FALSE`, `status VARCHAR DEFAULT 'active' CHECK (status IN ('active','deprecated'))`, `cost_per_1k_input_tokens DECIMAL(10,6)`, `cost_per_1k_output_tokens DECIMAL(10,6)`, `max_tokens INTEGER`, `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()`
- [ ] No `tenant_id` (platform-scoped table)
- [ ] No RLS (access controlled by platform role middleware)
- [ ] `UNIQUE(provider, model_name)`
- [ ] Seeded with Azure OpenAI and OpenAI Direct entries
      **Notes**: Cost rates stored here, not hardcoded in env. When a model is deprecated, existing tenant assignments continue to work but new tenants cannot select it.

---

### TODO DB-015: Create `usage_events` table for token tracking

**Effort**: 3h
**Depends on**: DB-001
**Description**: Create the token usage tracking table that records every LLM call with tenant attribution. Used for cost analytics, billing, and budget enforcement. Each row represents a single LLM API call.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `user_id UUID NOT NULL`, `conversation_id UUID`, `provider VARCHAR NOT NULL`, `model VARCHAR NOT NULL`, `tokens_in INTEGER NOT NULL`, `tokens_out INTEGER NOT NULL`, `model_source VARCHAR NOT NULL CHECK (model_source IN ('library','byollm'))`, `cost_usd DECIMAL(10,6)`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- [ ] RLS enabled with standard tenant isolation + platform bypass
- [ ] Index: `(tenant_id, created_at DESC)` for tenant cost queries
- [ ] Index: `(tenant_id, model, created_at)` for model-specific usage
- [ ] Partitioned by month on `created_at` for scalability
      **Notes**: `model_source = 'byollm'` means the tenant provided their own API key; billing is skipped but observability tracking continues. Cost is calculated at insert time: `tokens_in * cost_per_1k_input / 1000 + tokens_out * cost_per_1k_output / 1000`.

---

## Plan 03: Caching

### TODO DB-016: Enable pgvector extension on PostgreSQL

**Effort**: 1h
**Depends on**: none
**Description**: Enable the `pgvector` PostgreSQL extension required for semantic cache and glossary embedding search. Must be done before any table using `vector` type is created. Confirm availability on the target RDS Aurora instance.
**Acceptance criteria**:

- [ ] Alembic migration runs `CREATE EXTENSION IF NOT EXISTS vector`
- [ ] Verified on target RDS Aurora PostgreSQL (pgvector is available on Aurora PostgreSQL 15.4+)
- [ ] Fallback plan documented: if pgvector unavailable, use Redis VSS as alternative
      **Notes**: pgvector must be enabled before DB-017, DB-030, and any table using the `vector` type. Check with AWS team pre-deployment.

---

### TODO DB-017: Create `semantic_cache` table with HNSW index

**Effort**: 4h
**Depends on**: DB-016, DB-001
**Description**: Create the pgvector-based semantic response cache table. Stores query embeddings alongside cached LLM responses, enabling similarity-based cache lookup. Partitioned by `tenant_id` for data isolation and query performance.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `query_text TEXT NOT NULL`, `query_embedding vector(3072) NOT NULL`, `response_json TEXT NOT NULL`, `indexes_used UUID[]`, `intent_category VARCHAR`, `version_tags JSONB`, `similarity_threshold DECIMAL(4,3) DEFAULT 0.950`, `expires_at TIMESTAMPTZ NOT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- [ ] HNSW index: `CREATE INDEX idx_semantic_cache_embedding ON semantic_cache USING hnsw (query_embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)`
- [ ] Partitioned by `tenant_id` (list partitioning)
- [ ] RLS enabled with standard tenant isolation
- [ ] Cleanup job deletes expired entries (`expires_at < NOW()`) hourly
- [ ] Cleanup job deletes stale entries (version tags outdated) hourly
      **Notes**: HNSW parameters: `m=16` gives good recall/speed tradeoff, `ef_construction=64` for build quality. Partition by tenant_id ensures each tenant's cache is physically isolated. The `indexes_used` array tracks which knowledge base indexes were used to generate the cached response, enabling targeted invalidation.

---

### TODO DB-018: Create `index_versions` table for cache invalidation

**Effort**: 1h
**Depends on**: DB-001
**Description**: Create a version counter table for each search index. Incremented on every document sync/update event. Semantic cache lookups compare stored version tags against current versions to detect stale entries.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `index_id UUID NOT NULL`, `version BIGINT NOT NULL DEFAULT 1`, `updated_at TIMESTAMPTZ DEFAULT now()`, `UNIQUE(tenant_id, index_id)`
- [ ] RLS enabled
- [ ] `INCR` operation: `UPDATE index_versions SET version = version + 1, updated_at = now() WHERE tenant_id = $1 AND index_id = $2`
      **Notes**: The version counter is the authoritative source for cache invalidation. When a document sync completes, the corresponding index version is incremented, and any semantic cache entries referencing that index with an older version are considered stale.

---

### TODO DB-019: Redis caching layer — foundation caches (Phase C1)

**Effort**: 6h
**Depends on**: DB-012
**Description**: Implement all Phase C1 Redis cache key structures: user context cache, conversation history cache, glossary cache, and index metadata cache. Build the `CacheService` abstraction with key validation, metrics, and pub/sub invalidation.
**Acceptance criteria**:

- [ ] `CacheService` class implemented with `build_key()`, `get()`, `set()`, `delete()`, `publish_invalidation()`
- [ ] Key validation: tenant_id must match UUID pattern; cache_type must be in allowed set; key components alphanumeric only
- [ ] User context cache: `mingai:{tenant_id}:ctx:{user_id}` — TTL 600s — invalidated on role change
- [ ] Conversation cache: `mingai:{tenant_id}:conv:{conversation_id}` — last 10 messages — TTL 1800s — write-through on new message
- [ ] Glossary cache: `mingai:{tenant_id}:glossary:{tenant_id}` — all active terms — TTL 3600s — invalidated on glossary update
- [ ] Index metadata cache: `mingai:{tenant_id}:idx:{index_id}` — TTL 600s — invalidated on index update
- [ ] Invalidation pub/sub channel: `mingai:invalidation:{tenant_id}`
- [ ] Metrics instrumented: cache.hit / cache.miss counters with cache_type tag
      **Notes**: The `@cached(ttl, cache_type)` decorator pattern simplifies application of caching to service methods. All cache types are registered in `VALID_CACHE_TYPES` frozenset.

---

### TODO DB-020: Redis caching layer — pipeline caches (Phase C2)

**Effort**: 4h
**Depends on**: DB-019
**Description**: Implement intent detection, query embedding, and search result Redis caches. These eliminate redundant LLM calls and embedding API calls on repeated or similar queries.
**Acceptance criteria**:

- [ ] Intent cache: `mingai:{tenant_id}:intent:{sha256(normalized_query)}` — TTL 86400s (24h) — query normalized to lowercase, stripped, no punctuation
- [ ] Embedding cache: `mingai:{tenant_id}:emb:{model_id}:{sha256(query)}` — float16 compressed binary — TTL 604800s (7 days) — model_id in key for upgrade safety
- [ ] Search result cache: `mingai:{tenant_id}:search:{index_id}:{emb_hash_prefix_16}:{params_hash_8}` — TTL per-index config (default 3600s) — validated against `index_versions` counter
- [ ] Index version counter: `mingai:{tenant_id}:version:{index_id}` — `INCR` on document update — used to validate search cache entries
      **Notes**: Embedding compression from float32 to float16 gives 50% memory savings with negligible precision loss for similarity search. The `model_id` in the embedding cache key ensures a model upgrade doesn't serve stale embeddings.

---

## Plan 04: Issue Reporting

### TODO DB-021: Create `issue_reports` table

**Effort**: 3h
**Depends on**: DB-001
**Description**: Create the issue reports table for user-submitted bug reports, feature requests, and UX issues. Stores all context captured from the reporter widget including session data, screenshot URL, and AI triage results.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `user_id UUID NOT NULL REFERENCES users(id)`, `conversation_id UUID REFERENCES conversations(id)`, `agent_id UUID`, `title VARCHAR(200) NOT NULL`, `description TEXT NOT NULL CHECK (length(description) <= 10000)`, `type VARCHAR NOT NULL CHECK (type IN ('bug','performance','ux','feature'))`, `severity_hint VARCHAR CHECK (severity_hint IN ('high','medium','low','suggestion'))`, `screenshot_blob_url TEXT`, `screenshot_annotations JSONB`, `session_context JSONB NOT NULL`, `status VARCHAR NOT NULL DEFAULT 'received' CHECK (status IN ('received','triaging','triaged','in_review','escalated','in_progress','resolved','closed','wont_fix'))`, `priority VARCHAR CHECK (priority IN ('P0','P1','P2','P3','P4'))`, `category VARCHAR`, `root_cause_hypothesis TEXT`, `github_issue_url TEXT`, `github_issue_number INTEGER`, `sla_target TIMESTAMPTZ`, `parent_issue_id UUID REFERENCES issue_reports(id)`, `duplicate_confidence DECIMAL(4,3)`, `resolved_at TIMESTAMPTZ`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()`
- [ ] RLS enabled with standard tenant isolation + platform bypass
- [ ] Index: `(tenant_id, user_id, created_at DESC)` for My Reports listing
- [ ] Index: `(tenant_id, status, priority)` for queue views
- [ ] Index: `(tenant_id, parent_issue_id)` for duplicate grouping
      **Notes**: Feature requests (`type = 'feature'`) are routed to a separate product backlog channel, not the bug triage queue. The triage agent skips severity classification for feature requests. `parent_issue_id` links duplicate reports to the original.

---

### TODO DB-022: Create `issue_events` table

**Effort**: 2h
**Depends on**: DB-021
**Description**: Create the issue event audit trail table that records every state transition, comment, and action on an issue report. Provides the timeline view in the report detail page and full auditability of issue lifecycle.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `issue_id UUID NOT NULL REFERENCES issue_reports(id) ON DELETE CASCADE`, `event_type VARCHAR NOT NULL` (values: 'created', 'triaged', 'severity_set', 'status_changed', 'github_created', 'assigned', 'commented', 'escalated', 'resolved', 'closed', 'reopened', 'duplicate_linked', 'info_requested'), `actor_id UUID`, `actor_type VARCHAR CHECK (actor_type IN ('user','admin','system','triage_agent'))`, `payload JSONB`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- [ ] RLS enabled with standard tenant isolation + platform bypass
- [ ] Index: `(issue_id, created_at)` for timeline queries
- [ ] Immutable: no UPDATE or DELETE allowed (audit trail)
      **Notes**: The `payload` JSONB contains event-specific data: for `severity_set` it has `{from: null, to: "P2", reason: "..."}`, for `status_changed` it has `{from: "triaging", to: "triaged"}`. Actor type distinguishes human actions from AI triage agent actions.

---

### TODO DB-023: Create `issue_embeddings` table for duplicate detection

**Effort**: 2h
**Depends on**: DB-016, DB-021
**Description**: Create a pgvector table for issue description embeddings, enabling semantic duplicate detection by the triage agent. Each issue report gets an embedding generated from its title + description.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `issue_id UUID NOT NULL REFERENCES issue_reports(id) ON DELETE CASCADE`, `embedding vector(3072) NOT NULL`, `created_at TIMESTAMPTZ DEFAULT now()`, `UNIQUE(issue_id)`
- [ ] HNSW index: `CREATE INDEX idx_issue_embeddings ON issue_embeddings USING hnsw (embedding vector_cosine_ops)`
- [ ] RLS enabled
- [ ] Duplicate detection threshold: 0.88 cosine similarity (configurable)
      **Notes**: The triage agent queries this table to find semantically similar issues before creating a new GitHub issue. If similarity >= 0.88, the new report is linked as a duplicate to the existing issue. Category is used as a query predicate filter for efficiency.

---

### TODO DB-024: Redis Stream for issue report async processing

**Effort**: 2h
**Depends on**: DB-012
**Description**: Set up the Redis Stream `issue_reports:incoming` that decouples issue intake from AI triage processing. The intake API enqueues; the triage agent consumes. Supports horizontal scaling via consumer groups.
**Acceptance criteria**:

- [ ] Stream key: `mingai:issue_reports:incoming` (platform-scoped, not tenant-prefixed — the stream serves all tenants)
- [ ] Consumer group: `triage_workers` created on stream
- [ ] Message format: `{report_id, tenant_id, created_at}` (minimal; full data fetched from PostgreSQL by consumer)
- [ ] Consumer uses `XREADGROUP` with `BLOCK` for efficient polling
- [ ] Unacknowledged messages re-claimed after 5 minutes (dead letter handling)
- [ ] Rate limiting: 10 reports/user/day, 50 reports/tenant/day (checked at intake API before enqueue)
      **Notes**: The stream is platform-scoped because the triage agent is a shared worker. The `tenant_id` in the message payload allows the worker to set the correct RLS context when processing. Consumer group enables multiple triage workers for horizontal scaling.

---

## Plan 05: Platform Admin Console

### TODO DB-025: Create `llm_profiles` table

**Effort**: 3h
**Depends on**: DB-014
**Description**: Create the LLM profile configuration table. Platform admin defines named profiles (e.g., "Cost Optimized", "High Quality") with 6 deployment slot configurations. Profiles have a lifecycle: Draft > Published > Deprecated. Tenant admins select from published profiles.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `name VARCHAR NOT NULL UNIQUE`, `description TEXT`, `slot_configs JSONB NOT NULL` (6 slots: primary_chat, intent, embedding, extraction, synthesis, guardrail), `status VARCHAR NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','deprecated'))`, `best_practices TEXT`, `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()`, `created_by UUID`
- [ ] No `tenant_id` (platform-scoped)
- [ ] No RLS (access controlled by platform admin middleware)
- [ ] Index on `status` for listing published profiles
      **Notes**: Each `slot_configs` entry contains `{provider, model, max_tokens, temperature, ...}` for that slot. Deprecated profiles retain existing tenant assignments but cannot be newly selected. Profile change propagates to tenant RAG pipeline within 60 seconds (via Redis cache invalidation on `tenant_configs`).

---

### TODO DB-026: Create `tenant_health_scores` table

**Effort**: 2h
**Depends on**: DB-001
**Description**: Create the table that stores daily computed health scores per tenant. Calculated by a nightly batch job from 4 weighted components: usage trend (30%), feature breadth (20%), satisfaction rate (35%), error rate (15%).
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `score_date DATE NOT NULL`, `overall_score DECIMAL(5,2) NOT NULL`, `usage_trend_score DECIMAL(5,2)`, `feature_breadth_score DECIMAL(5,2)`, `satisfaction_score DECIMAL(5,2)`, `error_rate_score DECIMAL(5,2)`, `at_risk BOOLEAN DEFAULT FALSE`, `at_risk_reason TEXT`, `created_at TIMESTAMPTZ DEFAULT now()`, `UNIQUE(tenant_id, score_date)`
- [ ] No RLS (platform-scoped analytics; accessed by platform admin only)
- [ ] Index: `(tenant_id, score_date DESC)` for trend queries
- [ ] Index: `(at_risk, score_date DESC)` for at-risk tenant listing
      **Notes**: `at_risk = TRUE` when: score declining 3+ consecutive weeks, OR overall_score < 40, OR satisfaction_score < 50 for 2+ consecutive weeks. The nightly job runs at 02:00 UTC. Not populated until 15+ active tenants exist (Phase B gate).

---

### TODO DB-027: Create `tool_catalog` table

**Effort**: 3h
**Depends on**: DB-001
**Description**: Create the platform MCP tool catalog table. Stores registered tools with safety classification (Read-Only / Write / Destructive), health status, and tenant opt-in tracking. Safety classification is immutable (can only escalate, never downgrade).
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `name VARCHAR NOT NULL UNIQUE`, `provider VARCHAR NOT NULL`, `mcp_endpoint TEXT NOT NULL`, `auth_type VARCHAR NOT NULL CHECK (auth_type IN ('api_key','oauth2','mtls','none'))`, `capabilities JSONB`, `safety_classification VARCHAR NOT NULL CHECK (safety_classification IN ('read_only','write','destructive'))`, `health_status VARCHAR DEFAULT 'unknown' CHECK (health_status IN ('healthy','degraded','unavailable','unknown'))`, `health_last_checked TIMESTAMPTZ`, `consecutive_failures INTEGER DEFAULT 0`, `version VARCHAR`, `status VARCHAR DEFAULT 'active' CHECK (status IN ('active','deprecated','discontinued'))`, `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()`, `created_by UUID`
- [ ] No `tenant_id` (platform-scoped)
- [ ] No RLS (platform admin access only; tenant catalog browser uses filtered read API)
- [ ] CHECK constraint: safety_classification changes must only go Read-Only > Write > Destructive (enforced at application level; DB stores current value)
      **Notes**: Health monitoring pings every 5 minutes. Degraded after 3 consecutive failures. Unavailable after 10. State transitions trigger platform admin alerts. Agents receive fallback instructions when a tool is degraded/unavailable.

---

## Plan 06: Tenant Admin Console

### TODO DB-028: Create `agents` table

**Effort**: 3h
**Depends on**: DB-001
**Description**: Create the workspace agents table. Stores both library-adopted agents (from templates) and custom Agent Studio agents. Each agent has a system prompt, guardrails config, associated KBs, and access control settings.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `name VARCHAR(100) NOT NULL`, `description TEXT`, `system_prompt TEXT NOT NULL`, `guardrails JSONB` (blocked_topics, required_elements, confidence_threshold, max_length), `kb_ids UUID[]`, `tool_ids UUID[]`, `status VARCHAR NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','archived'))`, `template_id UUID REFERENCES agent_templates(id)`, `template_version INTEGER`, `variables JSONB`, `access_mode VARCHAR DEFAULT 'workspace' CHECK (access_mode IN ('workspace','role','user','agent_only'))`, `avatar_url TEXT`, `category VARCHAR`, `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()`, `created_by UUID`
- [ ] RLS enabled with standard tenant isolation
- [ ] Index: `(tenant_id, status)` for listing active agents
- [ ] `UNIQUE(tenant_id, name)` to prevent duplicate agent names within a workspace
      **Notes**: `template_id` is NULL for Agent Studio custom agents. For library agents, `template_id` + `template_version` track which template version was adopted. `variables` stores the tenant-filled variable values for library agents. `kb_ids` is an array of knowledge base IDs this agent can access.

---

### TODO DB-029: Create `agent_templates` table

**Effort**: 3h
**Depends on**: DB-001
**Description**: Create the platform-managed agent template library table. Templates have versioned system prompts, variable definitions, guardrail configs, and performance tracking. Includes 4 seed templates shipped in the codebase that are available without platform admin action.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `name VARCHAR(100) NOT NULL UNIQUE`, `description TEXT`, `system_prompt TEXT NOT NULL`, `variables JSONB NOT NULL DEFAULT '[]'::jsonb` (array of `{name, type, description, required, example}`), `guardrails JSONB`, `confidence_threshold DECIMAL(3,2) DEFAULT 0.70`, `category VARCHAR`, `tier_requirement VARCHAR DEFAULT 'starter' CHECK (tier_requirement IN ('starter','professional','enterprise'))`, `status VARCHAR NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','deprecated','seed'))`, `version INTEGER NOT NULL DEFAULT 1`, `changelog TEXT`, `satisfaction_score DECIMAL(4,2)`, `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()`, `created_by UUID`
- [ ] No `tenant_id` (platform-scoped templates)
- [ ] No RLS (access controlled by API; tenant admins see only `status IN ('published','seed')`)
- [ ] 4 seed templates inserted: `tmpl_seed_hr_policy`, `tmpl_seed_it_helpdesk`, `tmpl_seed_procurement`, `tmpl_seed_onboarding` with `status = 'seed'`
      **Notes**: Seed templates are tagged `status: seed` and automatically visible to tenant admins without platform admin action. Published versions are immutable in their system prompt; a new version must be created for changes. Variables use `{{variable}}` syntax in the system prompt.

---

### TODO DB-030: Add embedding column and HNSW index to `glossary_terms` table

**Effort**: 2h
**Depends on**: DB-016, DB-003
**Description**: Add a vector embedding column to the existing `glossary_terms` table for relevance-ranked glossary injection. At query time, the top 20 most relevant terms are selected by cosine similarity to the query embedding (not keyword match).
**Acceptance criteria**:

- [ ] Column added: `embedding vector(3072)` to `glossary_terms`
- [ ] HNSW index: `CREATE INDEX idx_glossary_embedding ON glossary_terms USING hnsw (embedding vector_cosine_ops)`
- [ ] GIN index on `search_vector` column (full-text search fallback)
- [ ] Columns present: `term VARCHAR NOT NULL`, `full_form VARCHAR`, `definition VARCHAR(200) NOT NULL`, `context_tags TEXT[]`, `scope VARCHAR`, `active BOOLEAN DEFAULT TRUE`, `version INTEGER DEFAULT 1`, `created_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ`
- [ ] Character limit enforced at DB level: `CHECK (length(definition) <= 200)`
- [ ] `UNIQUE(tenant_id, term, scope)` constraint
      **Notes**: Canonical injection limits: max 20 terms per query, max 200 chars per definition, 800-token hard cap for glossary block. Storage tier limits (100/1K/Unlimited) are separate from the per-query injection limit of 20.

---

## Plan 07: Hosted Agent Registry (HAR)

### TODO DB-031: Create `agent_cards` table for HAR registry

**Effort**: 3h
**Depends on**: DB-001
**Description**: Create the Hosted Agent Registry agent card table. Stores agent metadata, A2A endpoint, health status, and trust score. Published by tenant admins to make their workspace agents discoverable in the global registry.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `agent_id UUID NOT NULL` (FK to workspace `agents` table), `name VARCHAR NOT NULL`, `description TEXT`, `transaction_types TEXT[] NOT NULL`, `industries TEXT[]`, `languages TEXT[] DEFAULT '{en}'`, `a2a_endpoint TEXT NOT NULL`, `health_check_url TEXT NOT NULL`, `status VARCHAR NOT NULL DEFAULT 'pending_kyb' CHECK (status IN ('pending_kyb','active','suspended','unavailable'))`, `trust_score INTEGER DEFAULT 20 CHECK (trust_score BETWEEN 0 AND 100)`, `public_key TEXT` (Ed25519 public key), `kyb_level INTEGER DEFAULT 0`, `transaction_count BIGINT DEFAULT 0`, `discovery_count BIGINT DEFAULT 0`, `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()`
- [ ] RLS enabled with standard tenant isolation for write operations
- [ ] Platform bypass for read operations (registry is globally searchable)
- [ ] Index: `(status)` for active agent listing
- [ ] Index: `(transaction_types)` GIN for array containment queries
- [ ] Index: `(industries)` GIN for array containment queries
- [ ] `UNIQUE(tenant_id, agent_id)` to prevent double-publishing
      **Notes**: The `public_key` stores the Ed25519 public key. In Phase 1, HAR generates and holds the keypair. In Phase 2, agents can bring their own keys (BYOK). Health monitor pings `health_check_url` every 5 minutes; marks `unavailable` after 3 consecutive failures.

---

### TODO DB-032: Create `har_transaction_events` table with signature chaining

**Effort**: 4h
**Depends on**: DB-031
**Description**: Create the tamper-evident audit log for HAR A2A transactions. Each event's Ed25519 signature covers the previous event's hash plus current event data, creating a cryptographic chain that detects any alteration of historical records.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `txn_id VARCHAR NOT NULL`, `event_type VARCHAR NOT NULL` (RFQ_SENT, QUOTE_RECEIVED, PO_PLACED, PO_ACKNOWLEDGED, DELIVERY_CONFIRMED, APPROVED, REJECTED, ABANDONED, DISPUTED, RESOLVED), `from_agent_id VARCHAR NOT NULL`, `to_agent_id VARCHAR NOT NULL`, `payload_hash VARCHAR NOT NULL` (SHA-256 of payload), `payload_encrypted TEXT`, `platform_signature VARCHAR NOT NULL` (Ed25519 signature), `prev_event_hash VARCHAR` (NULL for first event in chain), `block_height INTEGER` (NULL in Phase 1; populated in Phase 2 blockchain), `timestamp TIMESTAMPTZ NOT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- [ ] Index: `(txn_id, timestamp)` for transaction timeline
- [ ] Index: `(from_agent_id, timestamp)` for per-agent history
- [ ] Index: `(to_agent_id, timestamp)` for per-agent history
- [ ] Immutable: no UPDATE or DELETE allowed (append-only audit)
- [ ] Signature verification function: given an event, verify signature against platform public key + prev_event_hash chain
      **Notes**: Signature chaining: `signature = Ed25519_sign(SHA256(prev_event_hash || event_type || payload_hash || timestamp))`. If any event is altered, all subsequent signatures become invalid. This provides tamper-evidence without blockchain in Phase 1. `block_height` is populated only in Phase 2 when Hyperledger Fabric is deployed.

---

### TODO DB-033: Create `har_fee_records` table

**Effort**: 1h
**Depends on**: DB-032
**Description**: Create the fee tracking table for HAR transaction fees. In Phase 1, fees are tracked (accrued) but not collected. Fee collection and invoicing begin in Phase 2 when financial transactions are enabled.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `txn_id VARCHAR NOT NULL`, `fee_type VARCHAR NOT NULL CHECK (fee_type IN ('TIER_1','TIER_2','TIER_3'))`, `amount_usd DECIMAL(10,4) NOT NULL`, `status VARCHAR NOT NULL DEFAULT 'accrued' CHECK (status IN ('accrued','invoiced','paid'))`, `tenant_id UUID REFERENCES tenants(id)`, `created_at TIMESTAMPTZ DEFAULT now()`
- [ ] RLS enabled with tenant isolation for tenant-visible fee records
- [ ] Index: `(txn_id)` for per-transaction fee lookup
- [ ] Index: `(tenant_id, status, created_at)` for billing queries
      **Notes**: Phase 1 fee rates: TIER_1 (information exchange) = free, TIER_2 (commitment) = flat fee TBD, TIER_3 (financial) = basis points on transaction value. All fees start as `accrued`. Reconciliation CSV export aggregates fees per tenant per period.

---

## Plan 08: Profile & Memory

### TODO DB-034: Create `user_profiles` table

**Effort**: 4h
**Depends on**: DB-001
**Description**: Create the adaptive user profile learning table. Stores LLM-extracted attributes updated every N queries (default 10). Contains technical level, communication style, interests, expertise areas, and common tasks learned from conversation history.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `user_id UUID NOT NULL REFERENCES users(id)`, `technical_level VARCHAR(20)`, `communication_style VARCHAR(20)`, `interests JSONB DEFAULT '[]'::jsonb` (max 20 items), `expertise_areas JSONB DEFAULT '[]'::jsonb` (max 10 items), `common_tasks JSONB DEFAULT '[]'::jsonb` (max 15 items), `profile_learning_enabled BOOLEAN DEFAULT TRUE`, `org_context_enabled BOOLEAN DEFAULT TRUE`, `share_manager_info BOOLEAN DEFAULT TRUE`, `query_count INTEGER DEFAULT 0`, `last_learned_at TIMESTAMPTZ`, `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()`
- [ ] `UNIQUE(tenant_id, user_id)` constraint
- [ ] RLS enabled with standard tenant isolation
- [ ] Index: `(tenant_id, user_id)` for fast lookup
      **Notes**: `query_count` is a durable checkpoint — the hot counter lives in Redis at `{tenant_id}:profile_learning:query_count:{user_id}` (TTL 30 days). On Redis cache miss, the counter seeds from this PostgreSQL value. Every 10th query writes back to PostgreSQL and triggers profile learning extraction.

---

### TODO DB-035: Create `memory_notes` table

**Effort**: 2h
**Depends on**: DB-001
**Description**: Create the user memory notes table for persistent facts the AI should remember. Notes come from two sources: user-directed ("remember that...") and auto-extracted during profile learning. Max 15 notes per user; oldest pruned when limit exceeded.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `user_id UUID NOT NULL REFERENCES users(id)`, `agent_id UUID REFERENCES agents(id) ON DELETE SET NULL` (NULL = global, non-NULL = agent-specific in Phase 2), `content TEXT NOT NULL CHECK (length(content) <= 200)`, `source VARCHAR(20) NOT NULL CHECK (source IN ('user','auto','team_admin'))`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- [ ] RLS enabled with standard tenant isolation
- [ ] Index: `idx_memory_notes_user ON (tenant_id, user_id, created_at DESC)` for listing notes newest-first
- [ ] 200-character content limit enforced at DB level (was documented but not enforced in aihub2)
      **Notes**: Top 5 notes (newest first) are injected into the prompt. The `agent_id` column is nullable in Phase 1 (all notes are global). Phase 2 enables agent-scoped memory by filtering on `agent_id`. The `source = 'user'` notes come from "remember that..." intent; `source = 'auto'` from profile learning extraction.

---

### TODO DB-036: Create `profile_learning_events` table

**Effort**: 2h
**Depends on**: DB-034
**Description**: Create the audit trail table for profile learning extraction events. Records when the LLM analyzed conversations, what attributes were extracted, and how many conversations were analyzed. 30-day retention via partition cleanup.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `user_id UUID NOT NULL REFERENCES users(id)`, `agent_id UUID`, `extracted_attributes JSONB NOT NULL`, `conversations_analyzed INTEGER NOT NULL`, `model_used VARCHAR`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- [ ] RLS enabled
- [ ] Partitioned by month on `created_at` (see DB-011)
- [ ] 30-day retention via pg_cron partition drop
      **Notes**: `extracted_attributes` contains the diff: `{technical_level: "intermediate", new_interests: ["kubernetes"], new_tasks: ["deploy microservices"]}`. This audit trail enables debugging of profile quality issues and GDPR data subject access requests.

---

### TODO DB-037: Redis keys for profile and memory services

**Effort**: 3h
**Depends on**: DB-012
**Description**: Implement all Redis key structures for the profile learning, working memory, org context, and memory services. These are the hot-path caches that avoid PostgreSQL reads on every chat turn.
**Acceptance criteria**:

- [ ] Profile query counter: `mingai:{tenant_id}:profile_learning:query_count:{user_id}` — INTEGER — TTL 30 days — writes back to PostgreSQL every 10th query
- [ ] Profile L2 cache: `mingai:{tenant_id}:profile_learning:profile:{user_id}` — JSON — TTL 1 hour — invalidated on profile update
- [ ] Working memory: `mingai:{tenant_id}:working_memory:{user_id}:{agent_id}` — JSON (topics[], recent_queries[]) — TTL 7 days (configurable via tenant_settings) — max 5 topics, max 3 recent queries (100-char truncation)
- [ ] Org context: `mingai:{tenant_id}:org_context:{user_id}` — JSON — TTL 24 hours — populated from SSO provider on login
- [ ] Active team session: `mingai:{tenant_id}:session:{user_id}:active_team` — STRING (team_id) — TTL session duration
      **Notes**: Working memory TTL defaults to 7 days but is configurable per tenant (1-30 days) via `tenant_settings.working_memory_ttl_days`. The `agent_id` in the working memory key enables agent-scoped memory from Day 1, even though Phase 1 uses a single default agent context.

---

### TODO DB-038: Create `consent_events` table (if not exists in migration)

**Effort**: 1h
**Depends on**: DB-003
**Description**: Ensure the `consent_events` table exists for GDPR compliance tracking. Records every privacy consent/opt-out event. This table may already exist in the Cosmos DB migration; verify and add `tenant_id` if needed.
**Acceptance criteria**:

- [ ] Table exists with: `id UUID PRIMARY KEY`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `user_id UUID NOT NULL`, `consent_type VARCHAR NOT NULL`, `consented BOOLEAN NOT NULL`, `timestamp TIMESTAMPTZ NOT NULL DEFAULT now()`, `source VARCHAR` (ui, api, admin)
- [ ] RLS enabled
- [ ] Index: `(tenant_id, user_id, timestamp DESC)` for latest consent lookup
- [ ] Immutable (append-only)
      **Notes**: For EU tenants, profile learning requires opt-in consent (not opt-out). The `PrivacyDisclosureDialog` in the frontend triggers a consent event write. GDPR `clear_profile_data()` must check and record consent withdrawal in this table.

---

## Plan 09: Glossary Pre-Translation

### TODO DB-039: Add `glossary_pretranslation_enabled` rollout flag

**Effort**: 0.5h
**Depends on**: DB-002
**Description**: Add a per-tenant feature flag to `tenant_configs` to control gradual rollout of the glossary pre-translation (inline expansion) feature. When disabled, the legacy Layer 6 system prompt injection is used.
**Acceptance criteria**:

- [ ] Column added to `tenant_configs`: `glossary_pretranslation_enabled BOOLEAN DEFAULT FALSE`
- [ ] Alembic migration for the column addition
- [ ] Default is FALSE (legacy behavior); switched to TRUE per tenant during rollout
      **Notes**: This is a temporary rollout flag. Once all tenants are migrated and validated, it can be removed and the legacy Layer 6 code path deleted.

---

## Plan 10: Teams & Collaboration

### TODO DB-040: Create `tenant_teams` table

**Effort**: 2h
**Depends on**: DB-001
**Description**: Create the native teams table for organizing users into groups within a tenant. Teams can be manually created by tenant admin or auto-synced from Auth0 JWT group claims. Used for team working memory and access control scoping.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `name VARCHAR(100) NOT NULL`, `description TEXT`, `source VARCHAR NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','auth0_sync'))`, `auth0_group_name VARCHAR`, `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()`, `created_by UUID`
- [ ] `UNIQUE(tenant_id, name)` constraint
- [ ] RLS enabled with standard tenant isolation
- [ ] Index: `(tenant_id)` for listing teams
      **Notes**: `source = 'auth0_sync'` means the team was auto-created from a JWT group claim. Auth0 sync only creates teams for groups matching the tenant's allowlist (`tenant_configs.auth0_group_allowlist`). Empty allowlist = no auto-sync.

---

### TODO DB-041: Create `team_memberships` table

**Effort**: 2h
**Depends on**: DB-040
**Description**: Create the team membership junction table with composite primary key. Tracks which users belong to which teams, when they were added, by whom, and whether the membership was manual or synced from Auth0.
**Acceptance criteria**:

- [ ] Table created: `team_id UUID NOT NULL REFERENCES tenant_teams(id) ON DELETE CASCADE`, `user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `role VARCHAR DEFAULT 'member' CHECK (role IN ('member','team_admin'))`, `source VARCHAR NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','auth0_sync'))`, `added_at TIMESTAMPTZ DEFAULT now()`, `added_by UUID`, `PRIMARY KEY (team_id, user_id)`
- [ ] RLS enabled with standard tenant isolation
- [ ] Index: `(user_id, tenant_id)` for finding a user's teams
- [ ] Auth0 sync rule: `auth0_sync` records can be removed by login sync; `manual` records are never auto-removed
      **Notes**: On each SSO login, the Auth0 group sync evaluates current group claims vs existing `auth0_sync` memberships. Groups the user is no longer in get their `auth0_sync` memberships removed. Manual memberships are untouched.

---

### TODO DB-042: Create `membership_audit_log` table

**Effort**: 1h
**Depends on**: DB-041
**Description**: Create the audit log for team membership changes. Records every add/remove action with actor, source, and timestamp. Visible in Tenant Admin > Teams > {team} > Audit Log.
**Acceptance criteria**:

- [ ] Table created: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `team_id UUID NOT NULL REFERENCES tenant_teams(id)`, `user_id UUID NOT NULL`, `action VARCHAR NOT NULL CHECK (action IN ('add','remove'))`, `actor_id UUID`, `source VARCHAR NOT NULL CHECK (source IN ('manual','auth0_sync','admin_bulk'))`, `timestamp TIMESTAMPTZ NOT NULL DEFAULT now()`
- [ ] RLS enabled with standard tenant isolation
- [ ] Index: `(team_id, timestamp DESC)` for team audit history
- [ ] Immutable (append-only, no UPDATE or DELETE)
      **Notes**: Actor is NULL for auth0_sync actions (system-initiated). For manual actions, actor_id is the tenant admin who performed the operation.

---

### TODO DB-043: Redis key for team working memory

**Effort**: 2h
**Depends on**: DB-012, DB-040
**Description**: Implement the Redis key structure for team working memory. Stores shared topics and anonymous query history that is injected as Layer 4b in the system prompt (150 token budget).
**Acceptance criteria**:

- [ ] Key: `mingai:{tenant_id}:team_memory:{team_id}` — JSON `{topics: [], recent_queries: []}` — TTL 7 days (configurable)
- [ ] Max 10 topics (union-merged with dedup from individual queries)
- [ ] Max 5 recent queries with anonymous attribution: `{query: "...", source: "a team member", timestamp: "..."}` (no user ID or display name)
- [ ] Team admin can clear team memory bucket
- [ ] User membership verified before reading team memory (security check)
      **Notes**: Anonymous attribution is intentional: team memory is an AI context tool, not an audit trail. The "a team member" label prevents social dynamics from affecting query behavior. If a user is removed from a team, they lose access to that team's working memory immediately.

---

## Cross-Plan: Phase 5 (Cloud Agnostic)

### TODO DB-044: Create `dag_runs`, `dag_nodes`, `dag_synthesis` tables

**Effort**: 4h
**Depends on**: DB-001
**Description**: Create the DAG execution history tables for the agentic RAG pipeline debug/replay UI. Stores full execution graph, per-node artifacts, and synthesis input/output for each multi-agent query. Per-plan retention policy: Starter 7 days, Professional 30 days, Enterprise 90 days.
**Acceptance criteria**:

- [ ] `dag_runs` table: `id UUID PRIMARY KEY`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `conversation_id UUID REFERENCES conversations(id)`, `query TEXT NOT NULL`, `intent VARCHAR`, `agent_count INTEGER`, `status VARCHAR NOT NULL CHECK (status IN ('running','completed','partial_failure','failed'))`, `total_latency_ms INTEGER`, `created_at TIMESTAMPTZ DEFAULT now()`
- [ ] `dag_nodes` table: `id UUID PRIMARY KEY`, `dag_run_id UUID REFERENCES dag_runs(id) ON DELETE CASCADE`, `agent_name VARCHAR NOT NULL`, `criticality VARCHAR CHECK (criticality IN ('CRITICAL','SUPPLEMENTARY'))`, `status VARCHAR NOT NULL`, `input_payload JSONB`, `output_payload JSONB`, `error_message TEXT`, `latency_ms INTEGER`, `tokens_used INTEGER`, `created_at TIMESTAMPTZ`
- [ ] `dag_synthesis` table: `id UUID PRIMARY KEY`, `dag_run_id UUID REFERENCES dag_runs(id) ON DELETE CASCADE`, `synthesis_input JSONB NOT NULL`, `synthesis_output TEXT NOT NULL`, `tokens_used INTEGER`, `model VARCHAR`, `created_at TIMESTAMPTZ`
- [ ] RLS enabled on all three tables
- [ ] Retention cleanup job: delete rows older than plan-tier limit (7/30/90 days)
      **Notes**: These tables enable the tenant admin DAG replay panel: artifact inspection, synthesis input/output view, re-run capability. The `dag_nodes.output_payload` can be large (agent artifacts); consider TOAST compression.

---

## Cross-Plan: Phase 6 (GA)

### TODO DB-045: Create billing tables (`invoices`, `line_items`, `payments`)

**Effort**: 4h
**Depends on**: DB-001, DB-015
**Description**: Create the billing infrastructure tables for usage-based pricing via Stripe integration. Invoices aggregate line items from usage events; payments track Stripe payment intents.
**Acceptance criteria**:

- [ ] `invoices` table: `id UUID PRIMARY KEY`, `tenant_id UUID NOT NULL REFERENCES tenants(id)`, `stripe_invoice_id VARCHAR`, `period_start DATE NOT NULL`, `period_end DATE NOT NULL`, `total_usd DECIMAL(10,2)`, `status VARCHAR CHECK (status IN ('draft','pending','paid','overdue','void'))`, `created_at TIMESTAMPTZ DEFAULT now()`
- [ ] `line_items` table: `id UUID PRIMARY KEY`, `invoice_id UUID REFERENCES invoices(id)`, `description VARCHAR NOT NULL`, `quantity DECIMAL(10,4)`, `unit_price DECIMAL(10,6)`, `total_usd DECIMAL(10,2)`, `category VARCHAR CHECK (category IN ('llm_tokens','api_calls','storage','a2a_transactions'))`, `created_at TIMESTAMPTZ`
- [ ] `payments` table: `id UUID PRIMARY KEY`, `invoice_id UUID REFERENCES invoices(id)`, `stripe_payment_intent_id VARCHAR`, `amount_usd DECIMAL(10,2)`, `status VARCHAR`, `paid_at TIMESTAMPTZ`, `created_at TIMESTAMPTZ`
- [ ] RLS enabled on all three tables (tenant sees own invoices; platform sees all)
      **Notes**: Billing accuracy target: within 0.1% of actual usage. Reconcile automated billing against manual calculation for first 30 days after launch. Phase 6 deliverable.

---

## Summary: Migration File Order

The Alembic migration files should be created and run in this order:

| Migration File                    | Description                                          | Todos                  |
| --------------------------------- | ---------------------------------------------------- | ---------------------- |
| `001_add_tenant_id_columns.py`    | Add tenant_id to 19 existing tables + scope to roles | DB-003                 |
| `002_create_tenant_tables.py`     | Create tenants, tenant_configs, user_feedback        | DB-001, DB-002, DB-006 |
| `003_backfill_default_tenant.py`  | Seed default tenant, backfill tenant_id              | DB-004                 |
| `004_add_rls_policies.py`         | Enable RLS on all 22 tables                          | DB-005                 |
| `005_platform_rbac.py`            | Platform members table, platform roles, scope column | DB-007                 |
| `006_token_blocklist.py`          | JWT token revocation during migration                | DB-008                 |
| `007_partition_messages.py`       | Monthly partitioning on messages                     | DB-009                 |
| `008_partition_events.py`         | Monthly partitioning on events                       | DB-010                 |
| `009_profile_memory_tables.py`    | user_profiles, memory_notes, profile_learning_events | DB-034, DB-035, DB-036 |
| `010_teams_tables.py`             | tenant_teams, team_memberships, membership_audit_log | DB-040, DB-041, DB-042 |
| `011_enable_pgvector.py`          | CREATE EXTENSION vector                              | DB-016                 |
| `012_semantic_cache.py`           | semantic_cache + index_versions tables               | DB-017, DB-018         |
| `013_issue_reporting.py`          | issue_reports, issue_events, issue_embeddings        | DB-021, DB-022, DB-023 |
| `014_llm_library.py`              | llm_library, llm_profiles, usage_events              | DB-014, DB-025, DB-015 |
| `015_har_tables.py`               | agent_cards, har_transaction_events, har_fee_records | DB-031, DB-032, DB-033 |
| `016_agents_templates.py`         | agents, agent_templates (with seeds)                 | DB-028, DB-029         |
| `017_glossary_embedding.py`       | Add embedding column + HNSW to glossary_terms        | DB-030                 |
| `018_tenant_health.py`            | tenant_health_scores                                 | DB-026                 |
| `019_tool_catalog.py`             | tool_catalog                                         | DB-027                 |
| `020_consent_events.py`           | consent_events (verify/create)                       | DB-038                 |
| `021_glossary_flag.py`            | glossary_pretranslation_enabled on tenant_configs    | DB-039                 |
| `022_dag_tables.py`               | dag_runs, dag_nodes, dag_synthesis                   | DB-044                 |
| `023_billing_tables.py`           | invoices, line_items, payments                       | DB-045                 |
| `024_partition_profile_events.py` | Monthly partitioning on profile_learning_events      | DB-011                 |

---

## Summary: All Redis Key Structures

| Key Pattern                                                     | Type             | TTL                   | Todo   | Plan  |
| --------------------------------------------------------------- | ---------------- | --------------------- | ------ | ----- |
| `mingai:{tenant_id}:llm_config`                                 | JSON             | 900s (15min)          | DB-013 | 02    |
| `mingai:{tenant_id}:ctx:{user_id}`                              | JSON             | 600s                  | DB-019 | 03-C1 |
| `mingai:{tenant_id}:conv:{conversation_id}`                     | JSON             | 1800s                 | DB-019 | 03-C1 |
| `mingai:{tenant_id}:glossary:{tenant_id}`                       | JSON             | 3600s                 | DB-019 | 03-C1 |
| `mingai:{tenant_id}:idx:{index_id}`                             | JSON             | 600s                  | DB-019 | 03-C1 |
| `mingai:{tenant_id}:intent:{sha256(query)}`                     | JSON             | 86400s                | DB-020 | 03-C2 |
| `mingai:{tenant_id}:emb:{model_id}:{sha256(query)}`             | Binary (float16) | 604800s (7d)          | DB-020 | 03-C2 |
| `mingai:{tenant_id}:search:{index_id}:{emb_hash}:{params_hash}` | JSON             | configurable          | DB-020 | 03-C2 |
| `mingai:{tenant_id}:version:{index_id}`                         | INTEGER          | none                  | DB-020 | 03-C2 |
| `mingai:{tenant_id}:profile_learning:query_count:{user_id}`     | INTEGER          | 30 days               | DB-037 | 08    |
| `mingai:{tenant_id}:profile_learning:profile:{user_id}`         | JSON             | 3600s (1h)            | DB-037 | 08    |
| `mingai:{tenant_id}:working_memory:{user_id}:{agent_id}`        | JSON             | 7 days (configurable) | DB-037 | 08    |
| `mingai:{tenant_id}:org_context:{user_id}`                      | JSON             | 86400s (24h)          | DB-037 | 08    |
| `mingai:{tenant_id}:session:{user_id}:active_team`              | STRING           | session               | DB-037 | 08    |
| `mingai:{tenant_id}:team_memory:{team_id}`                      | JSON             | 7 days (configurable) | DB-043 | 10    |
| `mingai:issue_reports:incoming`                                 | Stream           | none                  | DB-024 | 04    |
| `mingai:invalidation:{tenant_id}`                               | Pub/Sub          | none                  | DB-019 | 03-C1 |
| `mingai:config_invalidation`                                    | Pub/Sub          | none                  | DB-013 | 02    |
| `mingai:platform:tenant_list`                                   | JSON             | configurable          | DB-012 | 01    |
| `mingai:platform:provider_status`                               | JSON             | configurable          | DB-012 | 01    |
| `mingai:platform:feature_flags`                                 | JSON             | configurable          | DB-012 | 01    |

---

## Dependency Graph (Critical Path)

```
DB-001 (tenants) ──┬── DB-002 (tenant_configs)
                   ├── DB-003 (add tenant_id) ── DB-004 (backfill) ── DB-005 (RLS)
                   ├── DB-006 (user_feedback)
                   ├── DB-007 (platform RBAC)
                   ├── DB-014 (llm_library) ── DB-025 (llm_profiles)
                   ├── DB-015 (usage_events)
                   ├── DB-021 (issue_reports) ── DB-022 (issue_events)
                   ├── DB-028 (agents)
                   ├── DB-029 (agent_templates)
                   ├── DB-031 (agent_cards) ── DB-032 (har_txn_events) ── DB-033 (har_fees)
                   ├── DB-034 (user_profiles) ── DB-036 (learning_events)
                   ├── DB-035 (memory_notes)
                   ├── DB-040 (tenant_teams) ── DB-041 (memberships) ── DB-042 (membership_audit)
                   ├── DB-026 (health_scores)
                   ├── DB-027 (tool_catalog)
                   ├── DB-044 (dag_tables)
                   └── DB-045 (billing)

DB-016 (pgvector) ──┬── DB-017 (semantic_cache)
                    ├── DB-023 (issue_embeddings)
                    └── DB-030 (glossary_embedding)

DB-012 (Redis migration) ──┬── DB-013 (llm_config cache)
                           ├── DB-019 (foundation caches)
                           ├── DB-020 (pipeline caches)
                           ├── DB-024 (issue stream)
                           ├── DB-037 (profile/memory keys)
                           └── DB-043 (team memory)
```

**Total effort estimate**: ~120 hours (~3 person-weeks at full-time database focus)
