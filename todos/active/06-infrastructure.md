# 06 — Infrastructure, Deployment, Migrations, Background Jobs & DevOps

**Date**: 2026-03-07
**Status**: Active
**Scope**: All infrastructure tasks extracted from Plans 02-09 plus general DevOps
**Depends on**: `04-codegen-instructions/00-README.md`, `02-plans/02-technical-migration-plan.md`

---

## Plan 02 — Database Migration (Alembic)

### INFRA-001: Alembic migration — add tenant_id to 19 existing tables ✅ COMPLETED

**Effort**: 8h
**Depends on**: none
**Description**: Create Alembic migration `001_add_tenant_id_columns.py` that adds a `tenant_id UUID NOT NULL DEFAULT 'default'` column to all 19 migrated tables: `users`, `roles`, `user_roles`, `group_roles`, `indexes`, `conversations`, `messages`, `user_preferences`, `glossary_terms`, `user_profiles`, `profile_learning_events`, `consent_events`, `feedback`, `conversation_documents`, `document_chunks`, `usage_daily`, `events`, `question_categories`, `mcp_servers`, `notifications`. Add composite indexes per migration plan Section 1 (e.g. `(tenant_id, user_id, created_at DESC)` on conversations, BRIN on messages.created_at, GIN on glossary_terms.search_vector).
**Acceptance criteria**:

- [ ] Migration runs cleanly on empty PostgreSQL 16 database
- [ ] Migration runs cleanly on database with existing single-tenant data
- [ ] All 19 tables have `tenant_id` column after migration
- [ ] Column-level indexes created per migration plan table spec
- [ ] Migration is reversible via `alembic downgrade`
      **Notes**: Use `pgvector/pgvector:pg16` Docker image for local dev. Batch backfill in migration 003.

### INFRA-002: Alembic migration — create tenants, tenant_configs, user_feedback tables ✅ COMPLETED

**Effort**: 4h
**Depends on**: INFRA-001
**Description**: Create Alembic migration `002_create_tenant_tables.py` with three new tables. `tenants` table: id UUID PK, name, plan (starter/professional/enterprise), status (Draft/Active/Suspended/ScheduledDeletion/Deleted), created_at, owner_id, migrated_from. `tenant_configs` table: exact schema from migration plan Section 3 including api_key_ref (secrets manager URI), byollm fields, rate_limit_rpm, monthly_token_budget, UNIQUE(tenant_id, config_type). `user_feedback` table: exact schema from migration plan Section 1 with rating CHECK(1,-1), tags TEXT[], comment TEXT, indexes on (tenant_id, message_id) and (tenant_id, user_id, created_at DESC).
**Acceptance criteria**:

- [ ] All three tables created with exact column types from plan
- [ ] Foreign key constraints active (tenant_configs.tenant_id -> tenants.id, user_feedback FKs)
- [ ] `user_feedback.rating` CHECK constraint enforced
- [ ] Migration reversible
      **Notes**: `tenant_configs.api_key_ref` stores a secrets manager URI (e.g. `secretsmanager://mingai/acme-corp/openai-key`), never a raw key.

### INFRA-003: Alembic migration — backfill default tenant ✅ COMPLETED

**Effort**: 3h
**Depends on**: INFRA-002
**Description**: Create Alembic migration `003_backfill_default_tenant.py`. INSERT a default tenant row into `tenants` (id='default', name='Default Tenant (Migrated)', plan='enterprise', status='active'). UPDATE all 19 tables in batches of 100 rows: `SET tenant_id = 'default'::UUID WHERE tenant_id IS NULL`. Log batch progress (table name, batch number, rows updated).
**Acceptance criteria**:

- [ ] Default tenant record exists in `tenants` table after migration
- [ ] All rows in all 19 tables have `tenant_id = 'default'`
- [ ] Zero NULL tenant_id values remain
- [ ] Migration handles empty tables gracefully
- [ ] Batch size of 100 rows per UPDATE
      **Notes**: Run validation query after: `SELECT table_name, COUNT(*) FROM information_schema... WHERE tenant_id IS NULL` returns zero rows.

### INFRA-004: Alembic migration — enable RLS policies on all 22 tables ✅ COMPLETED

**Effort**: 6h
**Depends on**: INFRA-003
**Description**: Create Alembic migration `004_add_rls_policies.py`. For all 22 PostgreSQL tables (19 migrated + tenants + tenant_configs + user_feedback): `ALTER TABLE ... ENABLE ROW LEVEL SECURITY; FORCE ROW LEVEL SECURITY;`. Create `tenant_isolation` policy: `USING (tenant_id = current_setting('app.tenant_id')::UUID) WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)`. Create `platform_admin_bypass` policy: `USING (current_setting('app.scope', true) = 'platform') WITH CHECK (current_setting('app.scope', true) = 'platform')`.
**Acceptance criteria**:

- [ ] RLS enabled and forced on all 22 tables
- [ ] `tenant_isolation` policy on every table
- [ ] `platform_admin_bypass` policy on every table
- [ ] Queries without `SET app.tenant_id` return zero rows (non-superuser)
- [ ] Queries with `SET app.scope = 'platform'` bypass tenant filter
- [ ] Cross-tenant isolation integration test passes: tenant A data invisible to tenant B
      **Notes**: The application database user must NOT be a superuser (superusers bypass RLS). Create a dedicated `mingai_app` role.

### INFRA-005: Alembic migration — platform RBAC (scope column + platform roles) ✅ COMPLETED

**Effort**: 4h
**Depends on**: INFRA-004
**Description**: Create Alembic migration `005_platform_rbac.py`. Add `scope VARCHAR DEFAULT 'tenant'` column to `roles` table; backfill all existing rows with `scope = 'tenant'`. Create `platform_members` table (no tenant_id — platform-scoped). Seed 4 platform roles: `platform_admin`, `platform_operator`, `platform_support`, `platform_security` per `24-platform-rbac-specification.md`. Add 5 new platform system functions: `manage_tenants`, `manage_providers`, `manage_billing`, `view_cross_tenant`, `manage_platform_users`.
**Acceptance criteria**:

- [ ] `roles.scope` column exists with default 'tenant'
- [ ] Existing roles have `scope = 'tenant'`
- [ ] 4 platform roles seeded
- [ ] 5 platform system functions registered
- [ ] `platform_members` table created (no RLS — platform scope)
      **Notes**: Tenant roles cannot grant platform access. Permission resolution: check JWT scope first, then check role-level permissions.

### INFRA-006: Alembic migration — pgvector extension + semantic_cache table

**Effort**: 4h
**Depends on**: INFRA-001
**Description**: Create Alembic migration for pgvector setup. Execute `CREATE EXTENSION IF NOT EXISTS vector;`. Create `semantic_cache` table: id UUID PK, tenant_id UUID FK, query_text TEXT, query_embedding vector(3072), response_cacheable JSONB, indexes_used TEXT[], intent_category VARCHAR, version_tags JSONB, similarity_score FLOAT, expires_at TIMESTAMPTZ, created_at TIMESTAMPTZ. Partition by tenant_id. Create HNSW index on query_embedding: `CREATE INDEX idx_semantic_cache_embedding ON semantic_cache USING hnsw (query_embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)`.
**Acceptance criteria**:

- [ ] `vector` extension enabled
- [ ] `semantic_cache` table created with vector(3072) column
- [ ] HNSW index created and functional
- [ ] Nearest-neighbor query returns correct results on test data
- [ ] Table partitioned by tenant_id
- [ ] RLS policy applied
      **Notes**: Verify pgvector extension is available on target RDS/Aurora instance before deployment. Fallback: Redis VSS if pgvector unavailable (see caching plan risk register).

### INFRA-007: Alembic migration — all secondary indexes

**Effort**: 3h
**Depends on**: INFRA-006
**Description**: Create Alembic migration for all secondary indexes not covered in INFRA-001. Includes: `idx_memory_notes_user` on (tenant_id, user_id), `idx_profile_learning_events_user` on (tenant_id, user_id, created_at DESC), `idx_glossary_terms_embedding` HNSW on glossary_terms.embedding, `idx_agent_cards_tenant` on (tenant_id, status), `idx_agent_cards_industries` GIN on agent_cards.industries, `idx_events_tenant_timestamp` BRIN on events(tenant_id, timestamp), `idx_notifications_user` on (tenant_id, user_id, status, created_at DESC), `idx_consent_events_user` on (tenant_id, user_id, timestamp DESC).
**Acceptance criteria**:

- [ ] All indexes created
- [ ] EXPLAIN ANALYZE confirms index usage on representative queries
- [ ] No duplicate indexes
      **Notes**: Some indexes may already be created in INFRA-001 table-level specs. Deduplicate before running.

### INFRA-008: JWT v1 to v2 dual-acceptance middleware ✅ COMPLETED

**Effort**: 6h
**Depends on**: INFRA-005
**Description**: Implement JWT middleware in `app/core/jwt.py` that accepts both v1 tokens (no tenant_id, no scope, no plan, no token_version) and v2 tokens (with all four fields). v1 tokens treated as: `tenant_id='default'`, `scope='tenant'`, `plan='professional'`, `token_version=1`. Log v1 token usage with user_id for monitoring. After 30 days, reject v1 tokens with 401 + message "Please log in again". Configurable sunset date via `JWT_V1_SUNSET_DATE` env var.
**Acceptance criteria**:

- [ ] v2 tokens accepted and parsed correctly
- [ ] v1 tokens accepted during dual-acceptance window with correct defaults
- [ ] v1 tokens rejected after sunset date
- [ ] v1 token usage logged (count per user)
- [ ] Sunset date configurable via env var
- [ ] Unit tests for both token types
- [ ] Integration test: v1 token sets `app.tenant_id = 'default'` on DB connection
      **Notes**: See migration plan Section 2 for exact token structures.

### INFRA-009: Redis key namespace migration ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 5h
**Depends on**: INFRA-008
**Description**: Implement Redis key namespace migration from `mingai:{key}` to `mingai:{tenant_id}:{key}`. Deploy dual-read code: try new pattern first, fall back to old pattern. Create migration script using SCAN + RENAME to move existing keys to new namespace (all existing keys get `tenant_id = 'default'`). After 24 hours, remove fallback logic. Platform-scoped keys use `mingai:platform:{key}` pattern (no tenant_id). Clean up remaining old-pattern keys.
**Acceptance criteria**:

- [ ] New code reads new pattern first, falls back to old pattern
- [ ] Migration script renames all existing keys to new namespace
- [ ] Platform-scoped keys (`mingai:platform:tenant_list`, `mingai:platform:provider_status`, `mingai:platform:feature_flags`) use correct pattern
- [ ] No data loss during migration (verified by key count before/after)
- [ ] Fallback logic removable after 24h
      **Notes**: Use Redis SCAN (not KEYS) to avoid blocking. Rate-limit RENAME operations to avoid Redis CPU spikes.

### INFRA-010: LLM config migration from @lru_cache to tenant_configs table ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 5h
**Depends on**: INFRA-002, INFRA-009
**Description**: Replace the existing `@lru_cache` Settings pattern with a tenant-aware config reader. Read path: check Redis `mingai:{tenant_id}:llm_config` (15-min TTL) -> PostgreSQL `tenant_configs` table -> fall back to env vars. Write path: admin update writes to PostgreSQL, DELETEs Redis key, publishes invalidation event to `mingai:config_invalidation` pub/sub channel. Seed default config row from current `.env` values with `tenant_id = 'default'`.
**Acceptance criteria**:

- [ ] Config reader returns identical values to old `@lru_cache` Settings for default tenant
- [ ] Redis cache hit serves config in <1ms
- [ ] Redis cache miss falls through to PostgreSQL
- [ ] Admin config update invalidates Redis cache immediately
- [ ] Pub/sub invalidation broadcast reaches all FastAPI instances
- [ ] `.env` fallback works when both Redis and PostgreSQL are unavailable
- [ ] `@lru_cache` Settings removed from codebase
      **Notes**: Multi-instance invalidation requires all FastAPI instances to subscribe to `mingai:config_invalidation` channel on startup.

---

## Plan 03 — Caching Infrastructure

### INFRA-011: CacheService implementation (app/core/cache.py) ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 6h
**Depends on**: INFRA-009
**Description**: Implement `CacheService` class per Plan 03 Phase C1 spec. Includes: `build_cache_key(tenant_id, cache_type, *parts)` with UUID validation for tenant_id, whitelist validation for cache_type (auth, ctx, conv, intent, emb, search, idx, glossary, llm, mcp, rate, version), and regex validation for key parts. Wrap `aioredis` with metrics instrumentation (cache.hit, cache.miss counters with key_prefix tag). Implement get/set/delete/publish_invalidation methods. All operations must be async.
**Acceptance criteria**:

- [x] `build_cache_key` rejects invalid tenant_id (non-UUID)
- [x] `build_cache_key` rejects invalid cache_type
- [x] `build_cache_key` rejects injection attempts in key parts
- [x] get/set/delete work with real Redis (integration test)
- [x] Metrics increment on every hit/miss
- [x] Invalidation event published to correct channel
- [x] Cross-tenant key isolation verified (security test)
      **Notes**: Implemented in `app/core/cache.py`. Includes get/set/delete/get_many/set_many/invalidate_pattern methods.

### INFRA-012: @cached(ttl, cache_type) decorator ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 3h
**Depends on**: INFRA-011
**Description**: Implement `@cached(ttl, cache_type)` decorator that wraps any async function with cache lookup before execution and cache write after execution. The decorator must extract `tenant_id` from the first argument or keyword argument. Cache key built from function name + serialized arguments. TTL and cache_type specified at decoration time. Support explicit invalidation via `func.invalidate(tenant_id, *args)`.
**Acceptance criteria**:

- [x] Decorated function returns cached value on hit
- [x] Decorated function executes and caches on miss
- [x] TTL respected (value expires after TTL seconds)
- [x] `func.invalidate()` removes cached value
- [x] Tenant_id correctly extracted from function arguments
- [x] Works with async functions only (raises on sync)
      **Notes**: Implemented in `app/core/cache.py` as async decorator with graceful degradation — cache failures do not propagate to callers.

### INFRA-013: Cache invalidation pub/sub via Redis Pub/Sub ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 4h
**Depends on**: INFRA-011
**Description**: Implement invalidation event subscriber that listens on `mingai:invalidation:{tenant_id}` channels. On receiving an invalidation event, delete the specified cache keys from local Redis. Support event types: `role_change` (invalidate user context cache), `glossary_update` (invalidate glossary cache), `index_update` (invalidate index metadata + search result caches), `config_update` (invalidate LLM config cache), `document_sync` (increment version counter, invalidate search + semantic caches). Each FastAPI instance subscribes on startup and unsubscribes on shutdown.
**Acceptance criteria**:

- [x] Subscriber starts on FastAPI startup
- [x] Subscriber cleans up on FastAPI shutdown
- [x] Each event type correctly invalidates the right cache keys
- [x] Version counter incremented on document_sync events
- [x] Integration test: publish event on one instance, verify cache cleared on another
      **Notes**: Implemented via `publish_invalidation`/`subscribe_invalidation` in `app/core/cache.py`. Pattern subscription `mingai:invalidation:*` used.

### INFRA-014: Cache warming background job

**Effort**: 6h
**Depends on**: INFRA-012
**Description**: Implement scheduled background job that runs daily at 3 AM (tenant-local timezone). Per active tenant: query usage_daily/events table for top-100 queries from past 30 days. Pre-generate embeddings for each query (via embedding service). Pre-warm intent cache for top queries. Rate-limit warming to avoid impacting peak traffic (max 10 queries/second per tenant). Skip tenants with no activity in past 7 days.
**Acceptance criteria**:

- [ ] Job runs on schedule (cron-like trigger)
- [ ] Respects tenant-local timezone for 3 AM scheduling
- [ ] Top-100 queries correctly identified per tenant
- [ ] Embeddings cached in Redis after warming
- [ ] Intent results cached after warming
- [ ] Rate-limited to 10 queries/second per tenant
- [ ] Inactive tenants skipped
- [ ] Job completion logged with per-tenant stats
      **Notes**: Use APScheduler or Celery Beat for scheduling. Tenant timezone stored in `tenants` table or `tenant_configs`.

### INFRA-015: Semantic cache cleanup job

**Effort**: 3h
**Depends on**: INFRA-006
**Description**: Implement background job that runs hourly. Deletes expired entries from `semantic_cache` table where `expires_at < NOW()`. Deletes stale entries where version tags are outdated (compare version_tags JSONB against current version counters in Redis `mingai:{tenant_id}:version:{index_id}`). Log entries deleted per run.
**Acceptance criteria**:

- [ ] Job runs hourly
- [ ] Expired entries (by timestamp) deleted
- [ ] Stale entries (by version tag) deleted
- [ ] Deletion count logged
- [ ] Job handles empty table gracefully
- [ ] Job does not lock table during deletion (use batched DELETE with LIMIT)
      **Notes**: Use `DELETE ... WHERE id IN (SELECT id FROM semantic_cache WHERE expires_at < NOW() LIMIT 1000)` pattern to avoid long-running transactions.

### INFRA-016: Confirm pgvector availability on cloud PostgreSQL

**Effort**: 2h
**Depends on**: none
**Description**: Verify that pgvector extension is available on all target cloud PostgreSQL services: AWS Aurora PostgreSQL, Azure Database for PostgreSQL, GCP Cloud SQL for PostgreSQL. Document the minimum PostgreSQL version required (16+). Document the process to enable the extension on each cloud provider. If any provider does not support pgvector, document the Redis VSS fallback path.
**Acceptance criteria**:

- [ ] AWS Aurora PostgreSQL pgvector availability confirmed with version
- [ ] Azure Database for PostgreSQL pgvector availability confirmed with version
- [ ] GCP Cloud SQL pgvector availability confirmed with version
- [ ] Enable process documented per provider
- [ ] Fallback path documented if unavailable
      **Notes**: AWS Aurora supports pgvector on PostgreSQL 15.4+. Azure supports on Flexible Server 15+. GCP supports on Cloud SQL 15+.

---

## Plan 04 — Issue Reporting Infrastructure

### INFRA-017: Redis Stream setup for issue reports

**Effort**: 2h
**Depends on**: INFRA-009
**Description**: Create Redis Stream key `issue_reports:incoming` with a consumer group `issue_triage_workers`. Configure stream max length to 10,000 entries (trim oldest). Document the message schema: `{report_id, tenant_id, type, severity_hint, timestamp}`. Implement stream producer in the issue intake endpoint (`POST /api/v1/issue-reports`) that XADDs to the stream after persisting to PostgreSQL.
**Acceptance criteria**:

- [ ] Redis Stream `issue_reports:incoming` created
- [ ] Consumer group `issue_triage_workers` created
- [ ] Stream max length enforced at 10,000
- [ ] Intake endpoint successfully writes to stream
- [ ] Message schema validated before XADD
      **Notes**: Stream consumer (INFRA-018) reads from this stream.

### INFRA-018: Issue triage background worker (Redis Stream consumer)

**Effort**: 8h
**Depends on**: INFRA-017
**Description**: Implement async background worker that reads from `issue_reports:incoming` Redis Stream using XREADGROUP. On each message: load full issue report from PostgreSQL, invoke IssueTriageAgent (Kaizen agent) for severity classification and duplicate detection, update issue report status in PostgreSQL, create GitHub issue via GitHub API if classification warrants it. Handle consumer failures with XCLAIM for abandoned messages (visibility timeout: 5 minutes). Acknowledge messages after successful processing.
**Acceptance criteria**:

- [ ] Worker reads from stream using consumer group
- [ ] IssueTriageAgent invoked for each report
- [ ] Issue report status updated after triage
- [ ] GitHub issue created for non-duplicate bug reports
- [ ] Abandoned messages reclaimed after 5-minute timeout
- [ ] Messages ACKed after successful processing
- [ ] Worker handles IssueTriageAgent failures gracefully (retry with backoff)
- [ ] Feature request type routed to product backlog channel, not bug triage
      **Notes**: Feature requests (`type=feature`) skip severity classification and route to product backlog.

### INFRA-019: Screenshot blur service ✅ COMPLETED

**Effort**: 6h
**Depends on**: none
**Description**: Implement server-side blur pipeline for issue report screenshots. When a screenshot is uploaded, the RAG response area must be blurred BEFORE storage (per red team finding R4.1 CRITICAL). Pipeline: receive pre-signed URL upload notification -> download from object storage -> apply Gaussian blur to detected response area (use region annotation from frontend if provided, otherwise blur bottom 60% of image) -> overwrite original with blurred version -> confirm blur applied. Never store unblurred screenshots.
**Acceptance criteria**:

- [ ] Unblurred screenshot never persisted in object storage
- [ ] Blur applied to annotated region (if annotations provided)
- [ ] Blur applied to bottom 60% default region (if no annotations)
- [ ] Blurred image overwrites original at same object storage path
- [ ] Processing completes within 5 seconds of upload
- [ ] Handles PNG and JPEG formats
- [ ] Integration test with real object storage (S3/Blob/GCS based on CLOUD_PROVIDER)
      **Notes**: Use Pillow (PIL) for image processing. This is a CRITICAL security requirement from red team review.

---

## Plan 05 — Platform Admin Infrastructure

### INFRA-020: Tenant provisioning async worker

**Effort**: 12h
**Depends on**: INFRA-004, INFRA-009
**Description**: Implement tenant provisioning as a Kailash SDK workflow (AsyncLocalRuntime). Steps executed in order with rollback on any failure: (1) Create tenant record in PostgreSQL, (2) Seed 7 default system roles for tenant, (3) Apply RLS policy context for tenant, (4) Create search index (OpenSearch/Azure AI Search/Vertex per CLOUD_PROVIDER), (5) Create object storage bucket with tenant-scoped prefix, (6) Initialize Redis key namespace, (7) Create Stripe customer record, (8) Send invite email to tenant admin. Full compensating transactions: if step N fails, undo steps 1 through N-1. SLA: complete within 10 minutes. Log every step with timing.
**Acceptance criteria**:

- [ ] All 8 provisioning steps execute successfully for happy path
- [ ] Failure at any step triggers rollback of all completed steps
- [ ] Rollback verified: no orphaned resources after failure
- [ ] Provisioning completes in < 10 minutes
- [ ] Each step logged with duration
- [ ] Cloud-agnostic: works with AWS, Azure, GCP, self-hosted CLOUD_PROVIDER values
- [ ] Integration test with real PostgreSQL + Redis (mock external services in Tier 1 only)
      **Notes**: Use Kailash `WorkflowBuilder` + `AsyncLocalRuntime`. See `04-codegen-instructions/01-backend-instructions.md` Step 5 for skeleton.

### INFRA-021: Health score background job

**Effort**: 6h
**Depends on**: INFRA-002
**Description**: Implement daily background job that recalculates health scores for all active tenants. Composite score from 4 inputs: usage trend 30-day window (30% weight), feature breadth - distinct features used in last 30 days (20%), AI satisfaction rate - thumbs up/down ratio (35%), error rate - 5xx as % of total queries (15%). Store computed score in PostgreSQL (tenant health score table or tenants table column). Flag tenants with 3+ consecutive weeks of declining score as "at-risk". Support on-demand recalculation via API trigger.
**Acceptance criteria**:

- [ ] Job runs nightly for all active tenants
- [ ] All 4 score components calculated correctly
- [ ] Composite score stored in PostgreSQL
- [ ] At-risk flag set for 3+ weeks of decline
- [ ] On-demand API endpoint triggers immediate recalculation
- [ ] Job handles tenants with no data gracefully (score = null, not zero)
- [ ] Execution time logged per tenant and total
      **Notes**: Health score formula from Plan 05 Sprint B2. Score range 0-100.

### INFRA-022: LLM cost constants configuration

**Effort**: 3h
**Depends on**: INFRA-010
**Description**: Implement LLM cost constants as configurable values in `tenant_configs` or a dedicated `llm_cost_rates` table. Each model deployment has a cost-per-1K-tokens rate. Values loaded from env config on startup, overridable per tenant. Implement alert mechanism: when actual cost deviates > 20% from expected (based on token volume x rate), fire an alert event. Never hardcode cost values in application code.
**Acceptance criteria**:

- [ ] Cost rates stored in database, not hardcoded
- [ ] Rates loadable from env config on first boot
- [ ] Per-tenant rate override supported
- [ ] Alert fires when cost deviation > 20%
- [ ] Alert delivered via notification system (log + admin notification)
- [ ] Cost calculation: tokens x rate = dollar cost
      **Notes**: From Plan 05: "LLM cost constants in env config, NOT hardcoded; alerts when deviation > 20%."

---

## Plan 06 — Tenant Admin Infrastructure

### INFRA-023: Secrets manager integration (Azure Key Vault / AWS Secrets Manager / GCP Secret Manager)

**Effort**: 8h
**Depends on**: none
**Description**: Implement cloud-agnostic secrets manager abstraction for storing and retrieving tenant credentials (SharePoint client secrets, OAuth tokens, API keys). Interface: `get_secret(uri)`, `set_secret(uri, value)`, `delete_secret(uri)`. URI format: `secretsmanager://mingai/{tenant_id}/{secret_name}`. Implementations: Azure Key Vault (azure CLOUD_PROVIDER), AWS Secrets Manager (aws), GCP Secret Manager (gcp), local .env fallback (self-hosted). Secrets never stored in PostgreSQL or Redis.
**Acceptance criteria**:

- [ ] Abstract interface defined with get/set/delete
- [ ] Azure Key Vault implementation working
- [ ] AWS Secrets Manager implementation working
- [ ] GCP Secret Manager implementation working
- [ ] Self-hosted fallback (env vars or encrypted file)
- [ ] URI parsing correctly routes to provider
- [ ] Integration test per provider (can use emulator/localstack for AWS/GCP)
- [ ] Secrets never logged or returned in API responses
      **Notes**: `tenant_configs.api_key_ref` stores these URIs. This is the backbone for all credential storage.

### INFRA-024: Credential health check daily job

**Effort**: 4h
**Depends on**: INFRA-023
**Description**: Implement daily background job that checks credential health for all active tenants. For each tenant: check SharePoint client secret expiry date (alert 30 days before), check OAuth token refresh viability (attempt silent refresh), check API key validity (test API call). On finding expiring or invalid credentials: create notification for tenant admin, log credential health event. Do not block tenant operations on credential warnings (only on actual failures).
**Acceptance criteria**:

- [ ] Job runs daily for all active tenants
- [ ] SharePoint client secret expiry detected 30 days before
- [ ] OAuth token refresh tested
- [ ] API key validity verified via test call
- [ ] Notification created for tenant admin on credential issues
- [ ] Job does not fail-fast: continues checking other tenants on individual failures
- [ ] Health check results logged per tenant
      **Notes**: From Plan 06 Sprint B3: "Credential expiry monitoring: 30-day warning for SharePoint client secret, OAuth token refresh alerts."

### INFRA-025: Document sync background worker

**Effort**: 10h
**Depends on**: INFRA-023
**Description**: Implement per-source document sync background worker. Triggered by: (1) scheduled cron per sync_schedule config, (2) manual "Sync Now" button via API. Per sync run: authenticate with source using credentials from secrets manager, enumerate documents (delta since last sync), download new/modified documents, chunk and embed, upsert into search index, update sync status in PostgreSQL. Retry logic: exponential backoff (1s, 2s, 4s, 8s, 16s) with max 5 retries per document. Failure logging: per-file error with system-generated diagnosis. Sync frequency: plan-tier limited (Starter: daily, Professional: every 6h, Enterprise: hourly).
**Acceptance criteria**:

- [ ] Scheduled sync runs per configured frequency
- [ ] Manual sync trigger works via API
- [ ] Delta sync: only new/modified documents processed
- [ ] Retry with exponential backoff on transient failures
- [ ] Per-file error logged with diagnosis
- [ ] Sync status updated in PostgreSQL (last_sync_time, indexed_count, failed_count)
- [ ] Plan-tier frequency limits enforced
- [ ] Version counter incremented after sync (triggers cache invalidation via INFRA-013)
      **Notes**: Supports SharePoint (Phase A) and Google Drive (Phase B). Abstracted behind a DocumentSource interface.

### INFRA-026: Glossary cache warm-up on startup ✅ COMPLETED

**Completed**: 2026-03-07
**Completion note**: Implemented in `src/backend/app/modules/glossary/warmup.py`. Called from the FastAPI startup handler in `app/main.py`.
**Effort**: 2h
**Depends on**: INFRA-011
**Description**: On FastAPI application startup, pre-load active glossary terms for all active tenants into Redis cache. Key: `mingai:{tenant_id}:glossary:active`, TTL: 3600s. Query PostgreSQL for all active terms per tenant, serialize to JSON, SET in Redis. If Redis already has cached values (TTL not expired), skip. Log per-tenant term count and total warm-up duration.
**Acceptance criteria**:

- [ ] Glossary terms loaded into Redis on startup
- [ ] Skip tenants whose cache is still warm (TTL not expired)
- [ ] 3600s TTL set on each cache entry
- [ ] Startup warm-up logged with timing
- [ ] Works with zero tenants (no error)
- [ ] Works with tenants that have zero glossary terms
      **Notes**: From Plan 06: "Glossary cache warm-up on startup: pre-load active terms per tenant."

---

## Plan 07 — HAR (Hosted Agent Registry) Infrastructure

### INFRA-027: Ed25519 key management for registered agents

**Effort**: 6h
**Depends on**: INFRA-023
**Description**: Implement Ed25519 keypair generation for each registered agent. On agent registration: generate keypair using `cryptography` library, store private key in secrets manager (via INFRA-023 abstraction) at URI `secretsmanager://mingai/{tenant_id}/agent-keys/{agent_id}`, store public key in `agent_cards` table (public_key column). Implement signing function: given agent_id + message, retrieve private key from secrets manager, sign SHA-256(header||payload) with Ed25519. Implement verification function: given public key + signature + message, verify signature.
**Acceptance criteria**:

- [ ] Keypair generated on agent registration
- [ ] Private key stored in secrets manager (never in PostgreSQL)
- [ ] Public key stored in agent_cards table
- [ ] Sign function produces valid Ed25519 signature
- [ ] Verify function correctly validates/rejects signatures
- [ ] Signature chaining: each signature covers previous event hash + current event data
- [ ] Key rotation support: new keypair generation + old key archival
      **Notes**: Phase 1: HAR signs on agent's behalf. Phase 2 (BYOK): agents can bring their own keys.

### INFRA-028: Agent health monitor background job

**Effort**: 4h
**Depends on**: none
**Description**: Implement background job that pings `health_check_url` for every registered agent with status `active` every 5 minutes. HTTP GET with 10-second timeout. Track consecutive failures. After 3 consecutive failures: set agent status to `UNAVAILABLE`, create notification for agent owner (tenant admin). On next successful check after UNAVAILABLE: restore to `active`, create recovery notification. Log all health check results.
**Acceptance criteria**:

- [ ] Job runs every 5 minutes
- [ ] All active agents' health_check_url pinged
- [ ] 10-second timeout per check
- [ ] 3 consecutive failures -> UNAVAILABLE status
- [ ] Recovery detection: UNAVAILABLE -> active on success
- [ ] Notifications created for status transitions
- [ ] Health check history stored for last 24 hours (for diagnostics)
- [ ] Job handles unreachable URLs gracefully (timeout, DNS failure, etc.)
      **Notes**: From Plan 07: "Background job pings health_check_url every 5 minutes; marks agent UNAVAILABLE if 3 consecutive failures."

### INFRA-029: A2A message broker routing (HAR as signing proxy)

**Effort**: 10h
**Depends on**: INFRA-027
**Description**: Implement HAR as a message broker for Phase 1 A2A transactions. Buyer's system calls HAR API with transaction request. HAR: (1) validates both agents are registered and active, (2) signs outbound message using sender's Ed25519 key, (3) routes message to recipient's a2a_endpoint via HTTPS POST, (4) records transaction event in `har_transaction_events` table with signature chaining, (5) returns response to sender. Implement JSON Schema validation per message_type (RFQ, QUOTE, PO, ACK, etc.). Implement nonce tracking to prevent replay attacks.
**Acceptance criteria**:

- [ ] Message routing from sender to recipient via HAR
- [ ] Ed25519 signature applied to every outbound message
- [ ] Transaction event recorded with signature chain
- [ ] JSON Schema validation per message_type
- [ ] Nonce tracking prevents replay attacks
- [ ] Both agents must be registered and active (reject if not)
- [ ] HTTPS-only for recipient endpoints
- [ ] Transaction state machine transitions enforced (DRAFT->OPEN->NEGOTIATING->etc.)
      **Notes**: Phase 1 simplification: HAR holds all private keys and signs on behalf of agents.

### INFRA-030: Human approval email notification + timeout job

**Effort**: 6h
**Depends on**: INFRA-029
**Description**: Implement human approval gate for HAR transactions. When a transaction exceeds the tenant's approval threshold (default $5,000): pause transaction, send approval email to tenant admin with secure approval link (signed URL, single-use), start 48-hour timeout. Approval link: `GET /api/v1/registry/transactions/{txn_id}/approve?token={signed_token}`. Implement timeout job: check every hour for pending approvals past 48h, auto-reject expired approvals, notify both parties. Threshold configurable per tenant and per transaction type.
**Acceptance criteria**:

- [ ] Transactions above threshold pause for approval
- [ ] Approval email sent with secure, single-use link
- [ ] Approval link works (approve/reject)
- [ ] 48-hour timeout auto-rejects expired approvals
- [ ] Both parties notified on approval/rejection/timeout
- [ ] Threshold configurable per tenant (default $5,000)
- [ ] Threshold configurable per transaction type
- [ ] Signed URL prevents tampering
      **Notes**: From Plan 07: "Human approval gates: default ON for Tier 2+; default threshold $5,000."

### INFRA-031: Phase 2 blockchain infrastructure documentation

**Effort**: 2h
**Depends on**: none
**Description**: Document what is needed for Phase 2 blockchain integration without building it. Cover: Hyperledger Fabric 3-node network on Kubernetes (1 orderer, 2 peers), chaincode requirements (TransactionContract, AgentRegistryContract in Go), Fabric channel-per-transaction-pair data isolation, migration path from Phase 1 signed audit log, Polygon CDK checkpoint layer (every 100 Fabric blocks -> Polygon checkpoint), estimated infrastructure cost, and team skills required.
**Acceptance criteria**:

- [ ] Hyperledger Fabric deployment requirements documented
- [ ] Chaincode interface specifications documented
- [ ] Migration path from Phase 1 audit log documented
- [ ] Polygon CDK checkpoint architecture documented
- [ ] Infrastructure cost estimate provided
- [ ] Required team skills listed
- [ ] Gate criteria documented: 100+ transactions from Phase 1
      **Notes**: Explicitly do NOT build this in Phase 0-1. Documentation only. Build decision gated on 100+ real transactions.

---

## Plan 08 — Profile & Memory Infrastructure

### INFRA-032: Redis hot counter write-back to PostgreSQL ✅ COMPLETED

**Completed**: 2026-03-07
**Completion note**: Implemented in `src/backend/app/modules/profile/learning.py`. Counter seeds from DB on first INCR (cache miss), checkpoints to DB every LEARN_TRIGGER_THRESHOLD queries.
**Effort**: 4h
**Depends on**: INFRA-011
**Description**: Implement Redis-based hot counter for profile learning query counts. Key: `mingai:{tenant_id}:profile_learning:query_count:{user_id}`. On each query: INCR counter in Redis. When counter reaches 10: trigger async background learning job, reset counter, checkpoint value to PostgreSQL `user_profiles.query_count`. On Redis cache miss (counter key not found): read last checkpoint from PostgreSQL, seed Redis counter. Handle race conditions: use Redis WATCH/MULTI or Lua script for atomic check-and-reset.
**Acceptance criteria**:

- [ ] Counter incremented in Redis on each query
- [ ] Learning job triggered at count = 10
- [ ] Counter reset after triggering
- [ ] Value checkpointed to PostgreSQL on trigger
- [ ] Redis cache miss seeds from PostgreSQL
- [ ] Atomic check-and-reset (no double-trigger)
- [ ] Counter survives Redis restart (via PostgreSQL checkpoint)
      **Notes**: From Plan 08 Sprint 2: "query_count write-back: Redis hot counter -> PostgreSQL checkpoint on every 10th query."

### INFRA-033: Async profile learning job ✅ COMPLETED

**Completed**: 2026-03-07 — Evidence: fully implemented in `app/modules/profile/learning.py` with LLM pipeline, extraction prompt, attribute merging, and learning event logging.
**Effort**: 6h
**Depends on**: INFRA-032
**Description**: Implement async background job triggered from `on_query_completed` hook when query counter reaches 10. Job steps: (1) fetch last 10 conversations for user from PostgreSQL, (2) send ONLY user queries (not AI responses) to extraction LLM (intent model slot from tenant config), (3) extract profile attributes (technical_level, communication_style, interests, expertise_areas, common_tasks), (4) merge extracted attributes into existing `user_profiles` record, (5) extract up to 5 memory notes from conversations, (6) log profile_learning_event for audit trail. Enforce limits: interests max 20, expertise_areas max 10, common_tasks max 15, memory_notes per extraction max 5.
**Acceptance criteria**:

- [ ] Job triggered when counter = 10
- [ ] Only user queries sent to extraction LLM (not AI responses — data residency requirement)
- [ ] Profile attributes extracted and merged
- [ ] Memory notes extracted (max 5 per run)
- [ ] All limits enforced (interests 20, expertise 10, tasks 15)
- [ ] Learning event logged in profile_learning_events table
- [ ] Job uses tenant's configured intent model (not hardcoded)
- [ ] Job handles LLM failures gracefully (retry once, then skip)
      **Notes**: CRITICAL: only user queries sent to extraction LLM per red team finding on data residency.

### INFRA-034: In-process LRU cache for user profiles (L1) ✅ COMPLETED

**Completed**: 2026-03-07 — Evidence: `_profile_l1_cache = LRUCache(maxsize=1000)` implemented in `app/modules/profile/learning.py`.
**Effort**: 2h
**Depends on**: none
**Description**: Implement process-local LRU cache for user profiles as L1 cache layer. Max 1000 entries per process. TTL: 300 seconds. Read path: L1 (in-process) -> L2 (Redis) -> L3 (PostgreSQL). On profile update: invalidate L1 entry (local only; other processes invalidate on TTL expiry or pub/sub in Phase 2). Use `functools.lru_cache` with TTL wrapper or `cachetools.TTLCache`.
**Acceptance criteria**:

- [ ] L1 cache serves profile in <0.1ms
- [ ] Max 1000 entries enforced
- [ ] 300-second TTL enforced
- [ ] Cache miss falls through to Redis (L2) then PostgreSQL (L3)
- [ ] Profile update invalidates local L1 entry
- [ ] Memory usage bounded (1000 entries max)
      **Notes**: Phase 1 is single-process L1 only. Phase 2 adds Redis L2 with pub/sub invalidation across instances.

### INFRA-035: Auth0 group claim sync on login

**Effort**: 4h
**Depends on**: INFRA-008
**Description**: Implement Auth0 group claim synchronization triggered on each JWT decode during login. On login: extract group claims from JWT (Auth0 `groups` or custom namespace), check against tenant's group-to-role mapping table, create/update team memberships in PostgreSQL. If user's groups changed since last login: update role assignments, invalidate user context cache in Redis. Check group names against allowlist (tenant-configured). Log group sync events.
**Acceptance criteria**:

- [ ] Group claims extracted from JWT on login
- [ ] Group-to-role mapping applied
- [ ] Team memberships created/updated
- [ ] Changed groups trigger role update + cache invalidation
- [ ] Allowlist filtering applied (only mapped groups processed)
- [ ] Sync event logged
- [ ] Handles missing group claims gracefully (no groups = no change)
      **Notes**: From Plan 08: "Auth0 group claim sync: triggered on each login JWT decode, check allowlist, create/update team memberships."

### INFRA-036: Org context Redis cache ✅ COMPLETED

**Completed**: 2026-03-07 — Evidence: full implementation in `app/modules/memory/org_context.py` with 24h TTL, login-triggered caching, and provider-normalized schema.
**Effort**: 3h
**Depends on**: INFRA-011
**Description**: Implement Redis cache for org context data per user. Key: `mingai:{tenant_id}:org_context:{user_id}`. TTL: 24 hours (86400s). On login: fetch org context from SSO provider (Azure AD, Okta, SAML), normalize to `OrgContextData` schema, cache in Redis. On subsequent queries within 24h: read from Redis cache. Invalidate on new login (fresh data from SSO). Org context is injected into system prompt as Layer 2 (budget: 100 tokens).
**Acceptance criteria**:

- [ ] Org context cached on login
- [ ] 24-hour TTL enforced
- [ ] Cache hit serves org context in <1ms
- [ ] New login invalidates and refreshes cache
- [ ] Normalized schema regardless of SSO provider
- [ ] Token budget of 100 tokens enforced at injection time
      **Notes**: Actual org context usage is ~70 tokens per MEMORY.md analysis. Budget of 100 provides headroom.

---

## Plan 09 — Glossary Infrastructure

### INFRA-037: Glossary pretranslation rollout flag ✅ COMPLETED

**Completed**: 2026-03-07
**Completion note**: Implemented in `src/backend/app/core/glossary_config.py`. Per-tenant boolean stored in the `tenant_configs` table.
**Effort**: 1h
**Depends on**: INFRA-002
**Description**: Add `glossary_pretranslation_enabled` boolean flag to `tenant_configs` table (default: false). When enabled, the chat preprocessing pipeline uses GlossaryExpander for inline query expansion instead of Layer 6 system prompt injection. When disabled, legacy Layer 6 behavior is preserved. Flag is per-tenant, toggled by platform admin.
**Acceptance criteria**:

- [ ] Flag stored in tenant_configs
- [ ] Default value is false
- [ ] Chat pipeline checks flag before choosing expansion vs injection path
- [ ] Platform admin can toggle via API
- [ ] Flag change takes effect within 60 seconds (via config cache TTL)
      **Notes**: Enables gradual rollout per tenant. Validate with pilot tenants before global enable.

### INFRA-038: Glossary Redis cache with invalidation ✅ COMPLETED

**Completed**: 2026-03-07 — Evidence: `_invalidate_glossary_cache` in `app/modules/glossary/routes.py` and Redis cache in `_get_terms` in `expander.py` with 3600s TTL and pub/sub invalidation on CRUD.
**Effort**: 2h
**Depends on**: INFRA-011, INFRA-013
**Description**: Implement glossary terms Redis cache per tenant. Key: `mingai:{tenant_id}:glossary:active`. TTL: 3600s. On any glossary CRUD operation (add/edit/delete term, bulk import): publish `glossary_update` invalidation event via INFRA-013 pub/sub. All instances receive event and delete cached glossary for that tenant. Next query triggers fresh load from PostgreSQL.
**Acceptance criteria**:

- [ ] Glossary terms cached with 3600s TTL
- [ ] CRUD operations trigger invalidation event
- [ ] All FastAPI instances receive invalidation
- [ ] Fresh load from PostgreSQL after invalidation
- [ ] Bulk import triggers single invalidation (not per-term)
      **Notes**: Warm-up handled by INFRA-026. This covers runtime invalidation.

---

## General DevOps

### INFRA-039: Docker Compose for local development ✅ COMPLETED

**Effort**: 4h
**Depends on**: none
**Description**: Create `docker-compose.yml` at repository root for local development. Services: (1) `postgres` using `pgvector/pgvector:pg16` image with POSTGRES_DB=mingai, POSTGRES_USER=mingai, port 5432, named volume for data persistence, health check via `pg_isready`. (2) `redis` using `redis:7-alpine` with port 6379, health check via `redis-cli ping`, `--maxmemory 256mb --maxmemory-policy allkeys-lru`. (3) `backend` using backend Dockerfile, depends_on postgres+redis healthy, port 8022, mounts `src/backend` for hot reload, loads `.env`. (4) `frontend` using frontend Dockerfile, port 3022, mounts `src/web` for hot reload. All backend services on internal `backend` network; only frontend and backend exposed externally.
**Acceptance criteria**:

- [ ] `docker compose up` starts all 4 services
- [ ] PostgreSQL healthy with pgvector extension available
- [ ] Redis healthy with memory limit
- [ ] Backend connects to PostgreSQL and Redis
- [ ] Frontend connects to backend API
- [ ] Hot reload works for both backend and frontend
- [ ] Network isolation: postgres and redis not exposed externally
- [ ] Named volumes persist data across restarts
- [ ] Health checks configured for postgres and redis
      **Notes**: Backend network should be internal (no external access to postgres/redis).

### INFRA-040: Dockerfile for backend (FastAPI) ✅ COMPLETED

**Effort**: 3h
**Depends on**: none
**Description**: Create multi-stage Dockerfile at `src/backend/Dockerfile`. Stage 1 (builder): Python 3.12-slim base, install dependencies from pyproject.toml, copy source. Stage 2 (runtime): Python 3.12-slim base, copy only installed packages and app code from builder, non-root user `mingai` (UID 1000), EXPOSE 8022, health check endpoint `/health`, CMD uvicorn with appropriate settings. Optimize layer caching: copy pyproject.toml and install deps before copying source code.
**Acceptance criteria**:

- [ ] Multi-stage build (builder + runtime)
- [ ] Final image size < 500MB
- [ ] Runs as non-root user
- [ ] Health check configured in Dockerfile
- [ ] Layer caching optimized (deps before source)
- [ ] `.dockerignore` excludes tests, docs, .env, **pycache**, .git
- [ ] Image builds successfully
- [ ] Container starts and responds to /health
      **Notes**: Use `--no-cache-dir` for pip to reduce image size.

### INFRA-041: Dockerfile for frontend (Next.js) ✅ COMPLETED

**Effort**: 3h
**Depends on**: none
**Description**: Create multi-stage Dockerfile at `src/web/Dockerfile`. Stage 1 (deps): node:20-alpine, install dependencies from package.json/lock. Stage 2 (builder): copy source, run `next build` with standalone output. Stage 3 (runtime): node:20-alpine, copy standalone build output, non-root user, EXPOSE 3022, health check, CMD `node server.js`. Optimize with Next.js standalone output mode for minimal runtime.
**Acceptance criteria**:

- [ ] Multi-stage build (deps + builder + runtime)
- [ ] Final image size < 300MB
- [ ] Runs as non-root user
- [ ] Health check configured
- [ ] Standalone output mode enabled
- [ ] `.dockerignore` excludes node_modules, .next, .env, .git
- [ ] Image builds successfully
- [ ] Container starts and serves pages
      **Notes**: Use Next.js `output: 'standalone'` in next.config.js.

### INFRA-042: Environment variable configuration (.env.example) ✅ COMPLETED

**Effort**: 2h
**Depends on**: none
**Description**: Create `.env.example` at `src/backend/.env.example` with ALL required environment variables documented. Group by category: Database (DATABASE_URL), Redis (REDIS_URL), Cloud (CLOUD_PROVIDER), LLM (PRIMARY_MODEL, INTENT_MODEL, EMBEDDING_MODEL — blank, never hardcoded), Auth (JWT_SECRET_KEY — generate with `openssl rand -hex 32`, AUTH0_DOMAIN, AUTH0_CLIENT_ID), Feature flags (MULTI_TENANT_ENABLED, JWT_V1_SUNSET_DATE), Object Storage (S3_BUCKET/AZURE_CONTAINER/GCS_BUCKET based on provider), Search (OPENSEARCH_URL/AZURE_SEARCH_URL/VERTEX_URL), Secrets Manager (AZURE_KEY_VAULT_URL/AWS_REGION), Email (SENDGRID_API_KEY). Include comments explaining each variable's purpose.
**Acceptance criteria**:

- [ ] All required variables listed
- [ ] No real secret values (all blank or placeholder)
- [ ] Each variable has a comment explaining purpose
- [ ] Grouped by category
- [ ] `openssl rand -hex 32` instruction for secret generation
- [ ] `.env` in `.gitignore`
- [ ] Frontend `.env.example` at `src/web/.env.example` with NEXT_PUBLIC_API_URL
      **Notes**: CRITICAL: `.env` must be in `.gitignore`. Never commit real secrets.

### INFRA-043: Health check endpoints (/health and /ready) ✅ COMPLETED

**Effort**: 3h
**Depends on**: none
**Description**: Implement health check endpoints for backend FastAPI service. `GET /health` (liveness): returns 200 if process is alive, does not check dependencies (fast, for container restart decisions). `GET /ready` (readiness): returns 200 only if PostgreSQL connection is healthy AND Redis connection is healthy; returns 503 with details if any dependency is down. Include version, uptime, and dependency status in response body. Both endpoints bypass auth middleware.
**Acceptance criteria**:

- [ ] `/health` returns 200 when process is alive
- [ ] `/health` does not check external dependencies
- [ ] `/ready` checks PostgreSQL connectivity
- [ ] `/ready` checks Redis connectivity
- [ ] `/ready` returns 503 with failure details when dependency is down
- [ ] Both endpoints bypass authentication
- [ ] Response includes version and uptime
- [ ] Response time < 100ms for /health, < 500ms for /ready
      **Notes**: Kubernetes uses liveness for restart decisions and readiness for traffic routing.

### INFRA-044: Structured logging (JSON format) ✅ COMPLETED

**Effort**: 4h
**Depends on**: none
**Description**: Implement structured JSON logging across the entire backend. Every log entry must include: `timestamp` (ISO-8601), `level`, `message`, `tenant_id` (from request context), `user_id` (from JWT), `request_id` (generated per request via middleware), `module`, `function`. Use `structlog` or `python-json-logger`. Configure log level via `LOG_LEVEL` env var (default: INFO). Ensure no PII (passwords, tokens, full email) appears in logs. Sensitive fields redacted automatically.
**Acceptance criteria**:

- [ ] All log output is valid JSON
- [ ] Every entry includes timestamp, level, message, tenant_id, user_id, request_id
- [ ] Request ID generated per request and propagated through all handlers
- [ ] Log level configurable via env var
- [ ] No secrets or PII in logs (automated redaction)
- [ ] Structured logging works in both sync and async contexts
- [ ] Exception tracebacks included as structured field (not raw text)
      **Notes**: Use middleware to inject tenant_id, user_id, request_id into logging context.

### INFRA-045: Metrics instrumentation

**Effort**: 4h
**Depends on**: INFRA-011
**Description**: Implement application metrics using Prometheus client library or StatsD. Required metrics: `cache_hit_total` / `cache_miss_total` (by cache_type), `profile_learning_triggered_total`, `issue_triage_classified_total` (by severity), `query_latency_seconds` (histogram by pipeline stage), `active_connections` (PostgreSQL, Redis), `token_usage_total` (by model, tenant), `health_check_success_total` / `health_check_failure_total` (HAR agents). Expose metrics at `GET /metrics` (Prometheus format).
**Acceptance criteria**:

- [ ] All required metrics emitted
- [ ] `/metrics` endpoint returns Prometheus format
- [ ] Metrics include tenant_id label where applicable
- [ ] Cache hit/miss rates visible
- [ ] Query latency histogram by pipeline stage
- [ ] Token usage tracked per model per tenant
- [ ] Metrics endpoint bypasses authentication
      **Notes**: These metrics feed into the cache analytics dashboard (Plan 03 Phase C4) and platform admin cost monitoring (Plan 05 Phase B3).

### INFRA-046: CI pipeline configuration ✅ COMPLETED

**Effort**: 4h
**Depends on**: INFRA-040, INFRA-041
**Description**: Create GitHub Actions CI pipeline (`.github/workflows/ci.yml`). Jobs: (1) `lint`: ruff (Python) + eslint (TypeScript), (2) `typecheck`: mypy (Python) + tsc (TypeScript), (3) `test-unit`: pytest unit tests (Tier 1, mocking allowed), (4) `test-integration`: pytest integration tests (Tier 2, real PostgreSQL + Redis via service containers, NO MOCKING), (5) `build`: Docker build for backend and frontend. All jobs must pass before merge to main. Coverage gate: 80% minimum (100% for auth and security modules).
**Acceptance criteria**:

- [ ] Pipeline triggers on PR to main
- [ ] Lint job catches style violations
- [ ] Type check job catches type errors
- [ ] Unit tests run with coverage report
- [ ] Integration tests run with real PostgreSQL + Redis (GitHub Actions service containers)
- [ ] Docker build succeeds
- [ ] Coverage gate enforced (80% general, 100% auth/security)
- [ ] Pipeline completes in < 10 minutes
      **Notes**: Integration tests use `pgvector/pgvector:pg16` and `redis:7-alpine` as service containers.

### INFRA-047: Background job framework decision and setup

**Effort**: 6h
**Depends on**: INFRA-039
**Description**: Evaluate and implement the background job framework. Decision: Celery with Redis broker vs FastAPI BackgroundTasks with APScheduler. Document trade-offs: Celery provides better reliability (task persistence, retry, monitoring) but adds operational complexity; FastAPI BackgroundTasks are simpler but lack persistence. Implement the chosen framework with: task registration, scheduled jobs (cron-like), retry with exponential backoff, dead letter handling, task status tracking. Register all background jobs from this todo file (INFRA-014, 015, 018, 021, 024, 025, 028, 030, 032, 033).
**Acceptance criteria**:

- [ ] Framework decision documented with rationale
- [ ] Task registration mechanism working
- [ ] Scheduled job support (cron syntax)
- [ ] Retry with configurable exponential backoff
- [ ] Dead letter handling for permanently failed tasks
- [ ] Task status queryable (pending, running, completed, failed)
- [ ] All background jobs from this todo registered
- [ ] Health check for job worker process
- [ ] Worker included in Docker Compose (INFRA-039)
      **Notes**: Recommendation: Celery for production (reliability + monitoring via Flower), FastAPI BackgroundTasks for development simplicity. Can start with BackgroundTasks and migrate to Celery before GA.

### INFRA-048: Tenant middleware (app/core/tenant_middleware.py)

**Effort**: 5h
**Depends on**: INFRA-008
**Description**: Implement FastAPI middleware that runs on every request. If `MULTI_TENANT_ENABLED=false`: inject `tenant_id='default'` into request.state, do not set RLS context (backward compatible). If `MULTI_TENANT_ENABLED=true`: extract `tenant_id` from JWT, validate tenant exists and is active (check Redis cache first, PostgreSQL fallback), execute `SET app.tenant_id = '{tenant_id}'` and `SET app.scope = '{scope}'` on the database connection, inject into request.state for downstream use. Return 401 if tenant not found or suspended.
**Acceptance criteria**:

- [ ] Middleware runs on every request (except /health, /ready, /metrics)
- [ ] MULTI_TENANT_ENABLED=false mode injects default tenant
- [ ] MULTI_TENANT_ENABLED=true mode extracts from JWT
- [ ] Tenant existence/status validated
- [ ] RLS context set on database connection
- [ ] 401 returned for missing/suspended tenant
- [ ] Tenant info available in request.state
- [ ] Performance: < 5ms overhead per request
      **Notes**: See migration plan Section 6 for strangler fig pattern. This is the core multi-tenancy enforcement point.

### INFRA-049: Database connection pool with RLS context

**Effort**: 4h
**Depends on**: INFRA-048
**Description**: Configure SQLAlchemy async connection pool with per-request RLS context injection. On connection checkout from pool: execute `SET app.tenant_id` and `SET app.scope` using values from request context. On connection return to pool: reset session variables. Pool configuration: min_size=5, max_size=20 (configurable via env), max_overflow=10, pool_recycle=3600s. Create a dedicated `mingai_app` database role (non-superuser) that RLS policies apply to.
**Acceptance criteria**:

- [ ] Connection pool configured with async SQLAlchemy
- [ ] RLS context set on every connection checkout
- [ ] RLS context cleared on connection return
- [ ] Pool size configurable via env vars
- [ ] Non-superuser database role used (RLS enforced)
- [ ] Connection health checked on checkout
- [ ] Pool metrics exposed (active, idle, overflow)
      **Notes**: CRITICAL: application must use non-superuser role. Superuser bypasses RLS entirely.

### INFRA-050: MULTI_TENANT_ENABLED feature flag

**Effort**: 2h
**Depends on**: none
**Description**: Implement the `MULTI_TENANT_ENABLED` feature flag from `.env`. When false: all code paths use `tenant_id='default'`, RLS context not set, JWT v1 accepted without tenant claims. When true: full multi-tenant enforcement. Flag readable at startup and checkable at runtime without restart. Used by tenant middleware (INFRA-048), JWT handler (INFRA-008), and database connection (INFRA-049).
**Acceptance criteria**:

- [ ] Flag read from .env on startup
- [ ] Flag checkable at runtime
- [ ] false mode: single-tenant behavior preserved exactly
- [ ] true mode: full multi-tenant enforcement
- [ ] All dependent components (middleware, JWT, DB) respect the flag
- [ ] Integration test: same API calls work in both modes
      **Notes**: See migration plan Section 6 for deployment sequence (Week 1 false, Week 2 staging true, Week 4 production true).

---

## Dependency Graph Summary

```
INFRA-001 (tenant_id columns)
  -> INFRA-002 (new tables)
    -> INFRA-003 (backfill)
      -> INFRA-004 (RLS policies)
        -> INFRA-005 (platform RBAC)
          -> INFRA-008 (JWT v2)
            -> INFRA-009 (Redis namespace)
              -> INFRA-010 (LLM config migration)
              -> INFRA-011 (CacheService)
                -> INFRA-012 (@cached decorator)
                -> INFRA-013 (pub/sub invalidation)
                  -> INFRA-038 (glossary cache)
                -> INFRA-014 (cache warming job)
                -> INFRA-015 (semantic cache cleanup)
                -> INFRA-026 (glossary warm-up)
                -> INFRA-032 (hot counter)
                  -> INFRA-033 (profile learning job)
              -> INFRA-017 (Redis Stream)
                -> INFRA-018 (triage worker)
            -> INFRA-048 (tenant middleware)
              -> INFRA-049 (DB pool + RLS)
            -> INFRA-035 (Auth0 group sync)
        -> INFRA-020 (provisioning worker)
  -> INFRA-006 (pgvector + semantic_cache)
    -> INFRA-015 (semantic cache cleanup)

Independent (no infra dependencies):
  INFRA-016 (pgvector verification)
  INFRA-019 (screenshot blur)
  INFRA-023 (secrets manager)
    -> INFRA-024 (credential health check)
    -> INFRA-025 (document sync worker)
    -> INFRA-027 (Ed25519 keys)
      -> INFRA-029 (A2A broker)
        -> INFRA-030 (human approval)
  INFRA-028 (agent health monitor)
  INFRA-031 (Phase 2 blockchain docs)
  INFRA-034 (L1 LRU cache)
  INFRA-036 (org context cache) [depends on INFRA-011]
  INFRA-037 (glossary rollout flag) [depends on INFRA-002]
  INFRA-039 (Docker Compose)
  INFRA-040 (backend Dockerfile)
  INFRA-041 (frontend Dockerfile)
  INFRA-042 (.env.example)
  INFRA-043 (health checks)
  INFRA-044 (structured logging)
  INFRA-045 (metrics)
  INFRA-046 (CI pipeline)
  INFRA-047 (background job framework)
  INFRA-050 (feature flag)
```

---

## Effort Summary

| Category                         | Tasks          | Total Effort |
| -------------------------------- | -------------- | ------------ |
| Plan 02 — Database Migration     | INFRA-001..010 | 48h          |
| Plan 03 — Caching Infrastructure | INFRA-011..016 | 24h          |
| Plan 04 — Issue Reporting        | INFRA-017..019 | 16h          |
| Plan 05 — Platform Admin         | INFRA-020..022 | 21h          |
| Plan 06 — Tenant Admin           | INFRA-023..026 | 24h          |
| Plan 07 — HAR                    | INFRA-027..031 | 28h          |
| Plan 08 — Profile & Memory       | INFRA-032..036 | 19h          |
| Plan 09 — Glossary               | INFRA-037..038 | 3h           |
| General DevOps                   | INFRA-039..050 | 44h          |
| Gap Remediation                  | INFRA-051..067 | 82h          |
| **Total**                        | **67 tasks**   | **309h**     |

Estimated calendar time at 1 engineer: ~39 working days (~8 weeks).
Recommended: 2 engineers in parallel, targeting ~4.5 weeks for critical path (database migration -> caching -> tenant middleware -> security middleware).

---

## Gap Remediation (from 07-gap-analysis.md)

### INFRA-051: CORS middleware configuration

**Effort**: 3h
**Depends on**: none
**Description**: FastAPI CORS middleware configuration. Frontend runs on port 3022, backend on 8022 — cross-origin requests blocked by every modern browser without explicit CORS headers. Day-one showstopper. Allowed origins read from `ALLOWED_ORIGINS` env var (comma-separated). SSE uses GET via EventSource so must not require preflight for that path.
**Acceptance criteria**:

- [ ] FastAPI `CORSMiddleware` added with origins from `ALLOWED_ORIGINS` env var
- [ ] Allowed methods: GET, POST, PATCH, PUT, DELETE, OPTIONS
- [ ] Allowed headers: Authorization, Content-Type, X-Request-ID, X-Confirm-Delete
- [ ] Credentials allowed (cookies for httpOnly JWT)
- [ ] SSE endpoint (GET /api/v1/chat/stream) works via EventSource without preflight
- [ ] Wildcard `*` NOT allowed in production (explicit origins only)
- [ ] Dev mode: `http://localhost:3022` allowed
      **Notes**: GAP-001. CRITICAL. Without this, no frontend request reaches the backend.

### INFRA-052: HTTP security headers middleware

**Effort**: 4h
**Depends on**: none
**Description**: Security headers middleware for both backend (FastAPI) and frontend (Next.js `next.config.js` headers). Required headers: Content-Security-Policy, Strict-Transport-Security, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy. Enterprise customers will flag missing headers in security assessments.
**Acceptance criteria**:

- [ ] `Content-Security-Policy`: allows SSE connections, Recharts inline styles, Google Fonts
- [ ] `Strict-Transport-Security`: max-age=31536000; includeSubDomains
- [ ] `X-Frame-Options`: DENY
- [ ] `X-Content-Type-Options`: nosniff
- [ ] `Referrer-Policy`: strict-origin-when-cross-origin
- [ ] `Permissions-Policy`: camera=(), microphone=(), geolocation=()
- [ ] Backend: FastAPI middleware adds headers to all responses
- [ ] Frontend: `next.config.js` `headers()` function for static responses
      **Notes**: GAP-002. HIGH. Enterprise security assessment blocker.

### INFRA-053: Rate limiting middleware

**Effort**: 6h
**Depends on**: INFRA-011
**Description**: Redis-based sliding window rate limiting middleware. Reads `rate_limit_rpm` from tenant config and enforces per-user and per-tenant request limits. Returns 429 with `Retry-After` header when exceeded. The `rate_limit_rpm` field already exists in tenant_configs but nothing reads it at runtime.
**Acceptance criteria**:

- [ ] Sliding window algorithm using Redis sorted sets
- [ ] Per-user limit: configurable (default 60 rpm)
- [ ] Per-tenant limit: reads `rate_limit_rpm` from tenant config
- [ ] Returns 429 with `Retry-After` header (seconds until window resets)
- [ ] Error response matches standard format: `{error: "rate_limited", message, request_id}`
- [ ] Chat endpoint has separate, lower limit (default 20 rpm per user)
- [ ] Health check and public endpoints exempt
- [ ] Rate limit headers on all responses: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
      **Notes**: GAP-006. HIGH. Multiple endpoints reference rate limits but nothing enforces them.

### INFRA-055: LLM circuit breaker

**Effort**: 6h
**Depends on**: none
**Description**: Circuit breaker pattern for all LLM calls (chat, intent detection, profile learning, issue triage, glossary expansion). States: closed (normal), open (all calls fail-fast), half-open (probe with single request). Per-tenant, per-LLM-slot tracking. Opens at 50% failure rate in 60-second window.
**Acceptance criteria**:

- [ ] Three states: closed, open, half-open
- [ ] Opens at 50% failure rate in 60-second sliding window (minimum 5 calls)
- [ ] Open state: fail-fast for 30 seconds, then transition to half-open
- [ ] Half-open: allow 1 probe request; success -> closed, failure -> open
- [ ] Per-tenant, per-LLM-slot (chat_model, intent_model, extraction_model)
- [ ] Circuit state exposed in `/api/v1/health` response and Prometheus metrics
- [ ] Open circuit emits alert event (feeds INFRA-058 alerting)
- [ ] Graceful degradation: chat returns "Service temporarily unavailable" SSE event when open
      **Notes**: GAP-016. HIGH. 5+ LLM call sites fail simultaneously without this.

### INFRA-056: Database backup and restore strategy

**Effort**: 6h
**Depends on**: none
**Description**: Database backup, point-in-time recovery (PITR), and restore testing strategy. 44 tables including financial data, compliance records, and user data require documented backup procedures. Pre-migration backup checkpoint integrated into Alembic runner.
**Acceptance criteria**:

- [ ] Automated backups: 35-day retention (cloud-managed: Aurora/Azure/Cloud SQL)
- [ ] Point-in-time recovery (PITR) enabled with 5-minute granularity
- [ ] Pre-migration backup: Alembic runner triggers manual snapshot before any migration
- [ ] Monthly restore testing: automated script restores latest backup to test environment
- [ ] Restore test validates: row counts match, RLS policies intact, application connects successfully
- [ ] Backup status included in platform admin health dashboard
- [ ] Documented recovery time objective (RTO): <1 hour for PITR, <4 hours for full restore
- [ ] Recovery point objective (RPO): <5 minutes
      **Notes**: GAP-028. CRITICAL. Zero backup strategy for 44 tables including financial and compliance data.

### INFRA-057: Redis persistence and data criticality policy

**Effort**: 4h
**Depends on**: INFRA-011
**Description**: Separate Redis instances for cache (ephemeral, acceptable data loss) and durable data (working memory with 7-day TTL, no PostgreSQL backup). Current INFRA-039 sets `allkeys-lru` which evicts ANY key under memory pressure, including working memory data.
**Acceptance criteria**:

- [ ] Two Redis instances in Docker Compose: `redis-cache` (ephemeral) and `redis-durable` (persistent)
- [ ] Cache instance: `allkeys-lru`, no persistence, for embedding/search/semantic caches
- [ ] Durable instance: `noeviction` + AOF (appendonly yes, appendfsync everysec)
- [ ] Durable instance holds: working memory, session keys, rate limit counters, circuit breaker state
- [ ] Application code uses correct instance per data type
- [ ] Documentation: acceptable data loss scenarios per data type
- [ ] Memory alerting: warn at 80% on durable instance
      **Notes**: GAP-029. HIGH. Working memory has no PostgreSQL backup and 7-day TTL — eviction means permanent data loss.

### INFRA-058: Alerting rules and notification channels

**Effort**: 8h
**Depends on**: INFRA-045
**Description**: Alerting rules for all critical infrastructure metrics. INFRA-045 collects metrics but without alerts, failures go unnoticed. Defines thresholds, notification channels (PagerDuty/Slack/email), and escalation policy.
**Acceptance criteria**:

- [ ] Critical alerts (page immediately): DB pool >80%, Redis memory >80%, LLM error rate >10%, P99 latency >10s
- [ ] Warning alerts (Slack): cache hit rate <50% sustained 15min, disk usage >70%, DB slow queries >5/min
- [ ] Info alerts (email digest): token budget approaching limit, backup age >24h
- [ ] Notification channels: PagerDuty for critical, Slack for warning, email for info
- [ ] Alert deduplication: same alert not fired more than once per 15-minute window
- [ ] Alert suppression during maintenance windows
- [ ] Alert configuration stored in env/config (not hardcoded thresholds)
- [ ] Alert history queryable via platform admin API
      **Notes**: GAP-030. CRITICAL. Metrics without alerts are useless for operations.

### INFRA-059: Operational runbook

**Effort**: 8h
**Depends on**: INFRA-056, INFRA-058
**Description**: Documented procedures for common operational scenarios. On-call engineers need step-by-step instructions for failures.
**Acceptance criteria**:

- [ ] Runbook: service restart procedures (backend, frontend, Redis, PostgreSQL)
- [ ] Runbook: stuck Redis Streams consumer recovery
- [ ] Runbook: Alembic migration rollback procedure
- [ ] Runbook: secret rotation (JWT, DB password, Redis, Auth0, LLM keys)
- [ ] Runbook: LLM provider outage fallback procedure
- [ ] Runbook: RLS bypass investigation (suspected data leak)
- [ ] Runbook: tenant data export (GDPR request)
- [ ] Runbook: tenant data deletion (GDPR request)
- [ ] Each runbook includes: symptoms, diagnosis steps, resolution steps, verification
- [ ] Stored in `docs/runbooks/` directory, linked from platform admin UI
      **Notes**: GAP-031. HIGH. Zero operational documentation for production support.

### INFRA-061: Auth0 Management API token manager

**Effort**: 4h
**Depends on**: INFRA-023
**Description**: Singleton service that obtains, caches, and refreshes Auth0 Management API tokens. Tokens expire after 24h and are rate-limited to 2 req/sec. Used by org context sync, user management, and group sync.
**Acceptance criteria**:

- [ ] Client credentials grant to obtain Management API token
- [ ] Token cached in Redis with 23h TTL (1h safety margin before expiry)
- [ ] Auto-refresh on expiry (background refresh, no request blocking)
- [ ] Retry with exponential backoff on 429 rate limit
- [ ] Singleton pattern: shared across all Management API consumers
- [ ] Auth0 domain and client credentials from env (never hardcoded)
- [ ] Health check: token validity verified, reported in `/api/v1/health`
      **Notes**: GAP-040. HIGH. Multiple services need Management API access but none manage the token lifecycle.

### INFRA-066: Platform admin bootstrap CLI

**Effort**: 4h
**Depends on**: INFRA-005
**Description**: CLI command to create the first platform admin user. Solves the chicken-and-egg problem: platform admin portal requires a platform admin user, but no mechanism exists to create the first one. Must have no web attack surface.
**Acceptance criteria**:

- [ ] `python manage.py create-platform-admin --email admin@company.com`
- [ ] Creates user in Auth0 with platform_admin role
- [ ] Creates user record in PostgreSQL with scope=platform
- [ ] Idempotent: running twice with same email does not error or create duplicate
- [ ] Alternative: `BOOTSTRAP_ADMIN_EMAIL` env var checked on first startup
- [ ] Refuses to run if a platform admin already exists (safety check)
- [ ] No web endpoint exposed (CLI only — zero attack surface)
- [ ] Logs bootstrap action to audit trail
      **Notes**: GAP-049. HIGH. Without this, no one can access the platform admin portal after deployment.

### INFRA-067: Secret rotation procedures

**Effort**: 6h
**Depends on**: INFRA-023
**Description**: Zero-downtime secret rotation procedures for all critical secrets: JWT signing key, database password, Redis password, Auth0 client secret, SendGrid API key, LLM API keys.
**Acceptance criteria**:

- [ ] JWT: JWKS endpoint with key rotation (dual-key acceptance window during rotation)
- [ ] Database: Aurora online password rotation via AWS Secrets Manager (or equivalent per cloud)
- [ ] Redis: coordinated password update (update config, restart connections, update clients)
- [ ] Auth0 client secret: rotate via Management API, update env, restart
- [ ] LLM API keys: update in tenant_configs + invalidate config cache
- [ ] SendGrid: rotate key, update env, verify delivery
- [ ] Each rotation documented with pre/during/post steps
- [ ] Rotation verification: health check confirms new credentials work before old ones expire
      **Notes**: GAP-050. HIGH. No documented procedure for rotating any secret without downtime.
