# Technical Migration Plan: Single-Tenant to Multi-Tenant

## Overview

This document provides the concrete migration steps for converting mingai from a single-tenant application to a multi-tenant SaaS platform. Each section covers a specific migration domain with exact data changes, scripts, and rollback procedures.

---

## Section 1: tenant_id Injection

### PostgreSQL Table Migration

Every row in every table must receive a `tenant_id` column. Existing data is backfilled as `tenant_id = 'default'`. Row-Level Security (RLS) policies enforce tenant isolation at the database level.

| Table                     | Source (Cosmos DB Container) | Migration Strategy                                                                       | Notes                                                                                   |
| ------------------------- | ---------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `users`                   | `users`                      | Add `tenant_id` column (NOT NULL); backfill existing rows; add RLS policy                | User uniqueness scoped to tenant (same email can exist in different tenants)            |
| `roles`                   | `roles`                      | Add `tenant_id` column (NOT NULL); backfill; platform roles use `tenant_id = 'platform'` | Seed 7 default system roles per tenant on provisioning; `admin` and `default` protected |
| `user_roles`              | `user_roles`                 | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | FK to users + roles; UNIQUE(tenant_id, user_id, role_id)                                |
| `group_roles`             | `group_roles`                | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | FK to roles; UNIQUE(tenant_id, group_id, role_id)                                       |
| `indexes`                 | `indexes`                    | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | Maps to search indexes (Azure AI Search, OpenSearch, etc.); UNIQUE(tenant_id, name)     |
| `conversations`           | `conversations`              | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | Conversations are tenant-scoped; composite index (tenant_id, user_id, created_at DESC)  |
| `messages`                | `messages`                   | Add `tenant_id` column (NOT NULL); backfill; add RLS policy; partition by month          | FK to conversations; BRIN on created_at; tenant_id denormalized for RLS enforcement     |
| `user_preferences`        | `user_preferences`           | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | UNIQUE(tenant_id, user_id); stores per-user UI and notification settings                |
| `glossary_terms`          | `glossary_terms`             | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | HNSW on embedding; GIN on search_vector; scoped by (tenant_id, scope, category)         |
| `user_profiles`           | `user_profiles`              | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | UNIQUE(tenant_id, user_id); adaptive learning profile per user                          |
| `profile_learning_events` | `profile_learning_events`    | Add `tenant_id` column (NOT NULL); backfill; add RLS policy; partition by month          | 30-day retention; BRIN on created_at; pg_cron cleanup of expired partitions             |
| `consent_events`          | `consent_events`             | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | Index on (tenant_id, user_id, timestamp DESC); immutable audit trail                    |
| `feedback`                | `feedback`                   | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | Index on (tenant_id, message_id) and (tenant_id, status, created_at)                    |
| `conversation_documents`  | `conversation_documents`     | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | FK to conversations; personal document uploads scoped per tenant                        |
| `document_chunks`         | `document_chunks`            | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | FK to conversation_documents; HNSW on embedding for vector search                       |
| `usage_daily`             | `usage_daily`                | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | Pre-aggregated daily stats per tenant; index on (tenant_id, date, service)              |
| `events`                  | `events`                     | Add `tenant_id` column (NOT NULL); backfill; add RLS policy; partition by month          | Unified event store (replaces deprecated audit_logs + usage_events); BRIN on timestamp  |
| `question_categories`     | `question_categories`        | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | Seed default categories from platform template; index on (tenant_id, date)              |
| `mcp_servers`             | `mcp_servers`                | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | UNIQUE(tenant_id, name); MCP server configuration per tenant                            |
| `notifications`           | `notifications`              | Add `tenant_id` column (NOT NULL); backfill; add RLS policy                              | 30-day retention via pg_cron; index on (tenant_id, user_id, status, created_at DESC)    |

**Not migrated to PostgreSQL:**

| Cosmos DB Container         | Disposition                                                        |
| --------------------------- | ------------------------------------------------------------------ |
| `group_membership_cache`    | Maps to Redis (pure TTL cache, not a PostgreSQL table)             |
| `audit_logs` (deprecated)   | Historical data merged into `events` table, then container dropped |
| `usage_events` (deprecated) | Historical data merged into `events` table, then container dropped |

### New Tables (no Cosmos DB source)

| Table            | Purpose                                                                  |
| ---------------- | ------------------------------------------------------------------------ |
| `tenants`        | Tenant metadata: name, plan, status, created_at, owner_id                |
| `tenant_configs` | Per-tenant configuration: LLM provider, model, feature flags, MCP access |
| `user_feedback`  | Thumb up/down ratings on AI responses with optional tags and comments    |

**`user_feedback` schema:**

```sql
CREATE TABLE user_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  message_id UUID NOT NULL REFERENCES messages(id),
  user_id UUID NOT NULL REFERENCES users(id),
  rating SMALLINT NOT NULL CHECK (rating IN (1, -1)),  -- 1 = thumbs up, -1 = thumbs down
  tags TEXT[],                                          -- optional: 'inaccurate', 'incomplete', 'irrelevant', 'hallucinated'
  comment TEXT,                                         -- optional free-text
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS policy (same pattern as all tenant-scoped tables)
ALTER TABLE user_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_feedback FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON user_feedback
  USING (tenant_id = current_setting('app.tenant_id')::UUID);

-- Indexes
CREATE INDEX idx_user_feedback_message ON user_feedback (tenant_id, message_id);
CREATE INDEX idx_user_feedback_user ON user_feedback (tenant_id, user_id, created_at DESC);
```

### Connection Abstraction

Database connectivity is driven by a single `DATABASE_URL` environment variable, supporting any PostgreSQL-compatible endpoint:

| Cloud | Service                       | DATABASE_URL Example                                                    |
| ----- | ----------------------------- | ----------------------------------------------------------------------- |
| AWS   | RDS Aurora PostgreSQL         | `postgresql://user:pass@cluster.region.rds.amazonaws.com:5432/mingai`   |
| Azure | Azure Database for PostgreSQL | `postgresql://user:pass@server.postgres.database.azure.com:5432/mingai` |
| GCP   | Cloud SQL for PostgreSQL      | `postgresql://user:pass@/mingai?host=/cloudsql/project:region:instance` |
| Local | Docker PostgreSQL             | `postgresql://user:pass@localhost:5432/mingai`                          |

### Migration Tool: Alembic

All schema changes managed via Alembic migration scripts:

```
alembic/
  versions/
    001_add_tenant_id_columns.py
    002_backfill_default_tenant.py
    003_add_rls_policies.py
    004_create_tenant_tables.py
```

### Data Migration: Cosmos DB to PostgreSQL

```
1. Export Cosmos DB containers as JSON (per container, paginated)
2. Transform JSON documents to relational rows:
   - Flatten nested fields
   - Map Cosmos DB id -> PostgreSQL UUID primary key
   - Add tenant_id = 'default' to all rows
3. INSERT into PostgreSQL via Alembic migration scripts (100 rows/batch)
4. Validate: COUNT(*) per table matches source container document count
5. Validate: COUNT(WHERE tenant_id = 'default') == COUNT(*) per table
6. Log: table name, total rows, migrated rows, duration
```

Estimated duration: <1 hour for current data volumes. Run during maintenance window.

### Row-Level Security (RLS) Setup

PostgreSQL RLS enforces tenant isolation at the database engine level — no application-layer bypass is possible.

```sql
-- Set tenant context on each connection/transaction
SET app.tenant_id = 'acme-corp';

-- Enable RLS on each table
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

-- Create RLS policy (same pattern for all tenant-scoped tables)
CREATE POLICY tenant_isolation ON users
  USING (tenant_id = current_setting('app.tenant_id'))
  WITH CHECK (tenant_id = current_setting('app.tenant_id'));

-- Platform admin bypass (for cross-tenant operations)
CREATE POLICY platform_admin_bypass ON users
  USING (current_setting('app.scope', true) = 'platform')
  WITH CHECK (current_setting('app.scope', true) = 'platform');
```

Applied to all 22 PostgreSQL tables (19 migrated + 3 new): `users`, `roles`, `user_roles`, `group_roles`, `indexes`, `conversations`, `messages`, `user_preferences`, `glossary_terms`, `user_profiles`, `profile_learning_events`, `consent_events`, `feedback`, `conversation_documents`, `document_chunks`, `usage_daily`, `events`, `question_categories`, `mcp_servers`, `notifications`, `tenants`, `tenant_configs`, `user_feedback`.

> Note: `group_membership_cache` maps to Redis (not PostgreSQL). `audit_logs` and `usage_events` are deprecated containers to be dropped after historical data is merged into `events`. Full mapping in `12-database-architecture-analysis.md` Section 2.

### Redis Key Pattern Changes

**Current pattern:**

```
mingai:session:{session_id}
mingai:cache:{cache_key}
mingai:rate_limit:{user_id}
mingai:search_cache:{query_hash}
mingai:llm_config
```

**New pattern:**

```
mingai:{tenant_id}:session:{session_id}
mingai:{tenant_id}:cache:{cache_key}
mingai:{tenant_id}:rate_limit:{user_id}
mingai:{tenant_id}:search_cache:{query_hash}
mingai:{tenant_id}:llm_config
```

**Migration steps:**

1. Deploy new code that reads from new pattern first, falls back to old pattern
2. Run key migration script: SCAN + RENAME for each key
3. After 24 hours, remove fallback logic
4. Clean up any remaining old-pattern keys

**Platform-scoped keys (no tenant_id):**

```
mingai:platform:tenant_list
mingai:platform:provider_status
mingai:platform:feature_flags
```

### Azure AI Search Index Strategy

**Decision: Separate indexes per tenant.**

**Justification:**

- Tenant data isolation is guaranteed at the infrastructure level (not query-filter level)
- Index deletion on tenant deprovisioning is clean (drop index, not filter-delete)
- Per-tenant index tuning (analyzers, scoring profiles) is possible
- Simpler security model — no risk of cross-tenant search leakage

**Naming convention:** `{index_name}-{tenant_id}`

Examples:

```
documents-default
documents-acme-corp
documents-globex
```

**Provisioning:** Tenant creation workflow creates search indexes. Deprovisioning archives then deletes.

**Limits:** Azure AI Search supports up to 200 indexes per service (S1 tier). For >200 tenants, provision additional search services or upgrade tier.

---

## Section 2: JWT Migration

### Current Token Structure

```json
{
  "sub": "user_id_123",
  "roles": ["analyst", "admin"],
  "exp": 1735689600,
  "iat": 1735603200,
  "iss": "mingai"
}
```

### Target Token Structure

```json
{
  "sub": "user_id_123",
  "tenant_id": "acme-corp",
  "scope": "tenant",
  "plan": "professional",
  "roles": ["analyst", "admin"],
  "exp": 1735689600,
  "iat": 1735603200,
  "iss": "mingai",
  "token_version": 2
}
```

### New Fields

| Field           | Type    | Values                                        | Purpose                                                       |
| --------------- | ------- | --------------------------------------------- | ------------------------------------------------------------- |
| `tenant_id`     | string  | UUID or slug                                  | Identifies the tenant for all data scoping                    |
| `scope`         | string  | `"tenant"` or `"platform"`                    | Platform scope grants cross-tenant access for platform admins |
| `plan`          | string  | `"starter"`, `"professional"`, `"enterprise"` | Determines feature access and rate limits                     |
| `token_version` | integer | `2`                                           | Enables dual-token acceptance during migration                |

### Backward Compatibility Window (30 Days)

**Week 1-2: Deploy v2 token generation + dual acceptance**

- New logins receive v2 tokens (with tenant_id, scope, plan)
- Auth middleware accepts both v1 and v2 tokens
- v1 tokens treated as: `tenant_id: "default"`, `scope: "tenant"`, `plan: "professional"`

**Week 3-4: Monitor and nudge**

- Log v1 token usage (count, user_ids)
- Display "please re-login" banner for users still on v1 tokens
- Force token refresh on next API call for v1 tokens (transparently issues v2)

**Week 5 (day 31): v1 rejection**

- Auth middleware rejects v1 tokens with 401 + message "Please log in again"
- Remove v1 acceptance code

### Migration Script

```
1. Query all active sessions from Redis
2. For each session:
   a. Decode existing JWT
   b. Look up user's tenant_id (from users container)
   c. Look up tenant's plan (from tenants container)
   d. Issue new v2 token with same exp
   e. Update session in Redis
3. Log: total sessions, migrated, failed
```

This script is optional — the dual-acceptance window handles most cases. The script accelerates migration for long-lived sessions.

---

## Section 3: LLM Config Migration

### Current Architecture

```python
from functools import lru_cache
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_DEPLOYMENT: str = "gpt-5.2-chat"
    AZURE_OPENAI_INTENT_MODEL: str = "gpt-5-mini"
    # ... single set of values for entire application

    class Config:
        env_file = ".env"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

**Problems:**

- Single configuration for all users
- `@lru_cache` means config changes require restart
- No per-tenant model selection
- No BYOLLM support

### Target Architecture

**PostgreSQL `tenant_configs` table:**

```sql
CREATE TABLE tenant_configs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
  config_type VARCHAR NOT NULL DEFAULT 'llm_config',
  provider VARCHAR NOT NULL DEFAULT 'azure_openai',
  primary_model VARCHAR NOT NULL,
  intent_model VARCHAR NOT NULL,
  api_endpoint VARCHAR NOT NULL,
  api_key_ref VARCHAR NOT NULL,          -- e.g. 'secretsmanager://mingai/acme-corp/openai-key'
  max_tokens_per_request INTEGER DEFAULT 4096,
  monthly_token_budget BIGINT DEFAULT 10000000,
  rate_limit_rpm INTEGER DEFAULT 60,
  byollm_enabled BOOLEAN DEFAULT FALSE,
  byollm_provider VARCHAR,
  byollm_key_ref VARCHAR,
  updated_at TIMESTAMPTZ DEFAULT now(),
  updated_by VARCHAR,
  UNIQUE (tenant_id, config_type)
);

-- RLS policy
ALTER TABLE tenant_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_configs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tenant_configs
  USING (tenant_id = current_setting('app.tenant_id'));
```

**Redis cache layer:**

```
Key:    mingai:{tenant_id}:llm_config
Value:  JSON-serialized tenant_config document
TTL:    900 seconds (15 minutes)
```

**Read path:**

1. Check Redis cache: `mingai:{tenant_id}:llm_config`
2. Cache hit -> return cached config
3. Cache miss -> read from PostgreSQL `tenant_configs` table
4. Write to Redis with 15-min TTL
5. Return config

**Write path (admin update):**

1. Write updated config to PostgreSQL `tenant_configs` table
2. Invalidate Redis cache: `DEL mingai:{tenant_id}:llm_config`
3. Next read will populate cache from PostgreSQL
4. Log config change for audit trail

**Cache invalidation on admin update:**

- Explicit: Admin config save triggers `DEL` on Redis key
- Implicit: 15-min TTL ensures eventual consistency even if explicit invalidation fails
- Broadcast: If running multiple FastAPI instances, publish invalidation event to Redis pub/sub channel `mingai:config_invalidation`

### Migration Steps

1. Create `tenant_configs` table via Alembic migration
2. Seed default config row from current `.env` values with `tenant_id = 'default'`
3. Deploy new config reader (Redis -> PostgreSQL -> fallback to env)
4. Verify new reader returns identical values to `@lru_cache` Settings
5. Remove `@lru_cache` Settings usage from codebase
6. Platform admin UI can now manage per-tenant LLM config

---

## Section 4: RBAC Extension

### Current Role Model

Source: `app/modules/roles/schemas.py` (SystemFunction Literal), `scripts/init_system_roles.py` (role definitions)

**7 System Roles:**
| Role ID | Role Name | System Permissions |
| ---------------- | -------------------- | --------------------------- |
| `default` | Default | (none — kb_permissions set by admins) |
| `role_admin` | Role Administrator | role:manage |
| `index_admin` | Index Administrator | index:manage |
| `user_admin` | User Administrator | user:manage |
| `analytics_viewer` | Analytics Viewer | analytics:view |
| `audit_viewer` | Audit Viewer | audit:view |
| `admin` | Administrator | ALL 9 system permissions |

Protected (cannot delete): `admin`, `default`

**9 System Functions** (source: `SystemFunction = Literal[...]` in schemas.py):
`role:manage`, `user:manage`, `index:manage`, `analytics:view`, `audit:view`, `integration:manage`, `glossary:manage`, `feedback:view`, `sync:manage`

Note: 4 functions (`integration:manage`, `glossary:manage`, `feedback:view`, `sync:manage`) have no dedicated role — accessible only via `admin` role or custom roles.

**Permissions Model**: Additive — `kb_permissions` (list of accessible KB IDs) + `system_permissions` (list of system functions); union across all assigned roles.

### Extended Role Model

**New Platform Roles:**

| Role            | Scope    | Capabilities                                                                                            |
| --------------- | -------- | ------------------------------------------------------------------------------------------------------- |
| PlatformAdmin   | Platform | Full cross-tenant access: tenant CRUD, provider management, billing, user management across all tenants |
| PlatformSupport | Platform | Read-only cross-tenant access: view tenant configs, user lists, usage data, logs. Cannot modify.        |

**New System Functions:**

| Function              | Scope    | Description                             |
| --------------------- | -------- | --------------------------------------- |
| manage_tenants        | Platform | Create, update, deactivate tenants      |
| manage_providers      | Platform | Configure LLM providers, MCP servers    |
| manage_billing        | Platform | View and adjust billing, invoices       |
| view_cross_tenant     | Platform | Read data across tenant boundaries      |
| manage_platform_users | Platform | Create and manage platform-scoped users |

### ADR: Additive vs. Replacement Model

**Decision: Additive model.**

**Rationale:**

- Existing 7 system roles and 9 functions remain unchanged within tenant scope
- Platform roles are a new layer on top, not a replacement
- Tenant roles cannot grant platform access (isolation preserved)
- Platform roles grant cross-tenant read access but do not override tenant-level RBAC within a tenant
- Simpler migration: no changes to existing permission checks

**Permission Resolution:**

```
1. Extract scope from JWT (tenant | platform)
2. If scope == "tenant":
   - Check tenant-scoped roles and functions
   - Deny any cross-tenant or platform operations
3. If scope == "platform":
   - Check platform-scoped roles and functions
   - For tenant-specific operations: platform roles grant READ access
   - For tenant WRITE operations: require explicit platform function (manage_tenants)
```

**Permission Inheritance:**

- PlatformAdmin inherits: `view_cross_tenant` + all `manage_*` platform functions
- PlatformSupport inherits: `view_cross_tenant` only
- Neither inherits tenant-scoped roles — they operate at a different level

### Migration Steps

1. Add `scope` column to `roles` table via Alembic migration: existing roles get `scope = 'tenant'`
2. Create platform roles: PlatformAdmin, PlatformSupport with `scope = 'platform'`
3. Create platform functions as `system_permissions` entries in the `roles` table
4. Update permission middleware to check scope before role resolution
5. Designate initial PlatformAdmin users (current system owners)
6. Verify existing tenant RBAC unchanged (regression tests)

---

## Section 5: Data Migration Strategy

### Approach

All existing single-tenant data becomes the "default" tenant. This is a non-destructive, additive migration.

### Step-by-Step

**Step 1: Run Alembic migrations to add tenant_id columns**

```
alembic upgrade head
  - Adds tenant_id column (VARCHAR, NOT NULL, DEFAULT 'default') to all 19 migrated tables
  - Creates new tables: tenants, tenant_configs, user_feedback
  - Creates indexes on tenant_id columns
  - Enables RLS on all 22 PostgreSQL tables
```

**Step 2: Backfill tenant_id**

```
For each table:
  1. UPDATE rows in batches (100 rows/batch):
     UPDATE {table} SET tenant_id = 'default' WHERE tenant_id IS NULL
  2. Track: batch_number, rows_updated, errors
  3. After all batches: validate counts match
```

**Step 3: Create tenant record**

```sql
INSERT INTO tenants (id, name, plan, status, created_at, migrated_from, owner_id)
VALUES (
  'default',
  'Default Tenant (Migrated)',
  'enterprise',
  'active',
  '2026-03-04T00:00:00Z',
  'single_tenant',
  '<current_system_owner_id>'
);
```

**Step 4: Enable RLS policies**

```
alembic upgrade (RLS migration):
  - ALTER TABLE {table} ENABLE ROW LEVEL SECURITY
  - ALTER TABLE {table} FORCE ROW LEVEL SECURITY
  - CREATE POLICY tenant_isolation ON {table}
      USING (tenant_id = current_setting('app.tenant_id'))
      WITH CHECK (tenant_id = current_setting('app.tenant_id'))
```

**Step 5: Validation queries**

```
For each table:
  - COUNT(*) matches expected row count
  - COUNT(WHERE tenant_id = 'default') == COUNT(*)
  - Spot check: 10 random rows, verify all fields preserved
  - Query test: existing application queries return same results with SET app.tenant_id = 'default'
```

**Step 6: Switch application to use RLS-aware connections**

```
  - Application sets app.tenant_id on each database connection/transaction
  - Deploy and verify application works with RLS active
  - Verify tenant isolation: queries from tenant A cannot see tenant B data
```

**Step 7: Cleanup (after 30-day validation period)**

```
  - Remove DEFAULT 'default' from tenant_id columns (new rows must explicitly set tenant_id)
  - Archive Cosmos DB export files to object storage
  - Drop any legacy compatibility views
```

### Rollback Procedure

If migration fails or introduces issues within 30 days:

1. Disable RLS policies: `ALTER TABLE {table} DISABLE ROW LEVEL SECURITY`
2. Revert application code to not set `app.tenant_id` on connections
3. Deploy rollback
4. tenant_id columns remain (additive, harmless) but are ignored by application
5. Investigate failure cause
6. Re-attempt migration after fix

**Data loss risk: ZERO** — the migration is purely additive (new columns, new policies). Disabling RLS restores original query behavior. No data is deleted or moved.

---

## Section 6: Zero-Downtime Approach

### Feature Flag

**Environment variable:** `MULTI_TENANT_ENABLED`

```
MULTI_TENANT_ENABLED=false   # Single-tenant mode (current behavior)
MULTI_TENANT_ENABLED=true    # Multi-tenant mode (new behavior)
```

Stored in `.env` and overridable per deployment environment.

### Strangler Fig Pattern

The migration follows the strangler fig pattern — new multi-tenant code wraps existing single-tenant code, gradually replacing it.

**Tenant Middleware (FastAPI):**

```
For every incoming request:
  1. If MULTI_TENANT_ENABLED == false:
     - Pass request through unchanged (existing behavior)
     - Inject tenant_id = "default" into request context (for forward compatibility)

  2. If MULTI_TENANT_ENABLED == true:
     - Extract tenant_id from JWT
     - Validate tenant exists and is active
     - Inject tenant_id into request context
     - All downstream queries scoped to tenant_id
```

**Deployment Sequence:**

```
Week 1: Deploy with MULTI_TENANT_ENABLED=false
  - New code is live but feature-flagged off
  - All requests go through middleware but get tenant_id="default"
  - Verify zero behavior change (regression tests)

Week 2: Canary — enable for internal testing
  - MULTI_TENANT_ENABLED=true for staging environment
  - Create test tenant, run full E2E suite against it
  - Verify tenant isolation

Week 3: Canary — enable for 10% of production users
  - Use header-based routing: X-Feature-MultiTenant: true
  - Monitor error rates, latency, data integrity
  - If issues: disable header routing (instant rollback)

Week 4: Full rollout
  - MULTI_TENANT_ENABLED=true for all traffic
  - Remove canary routing logic
  - Monitor for 48 hours
  - If issues: flip flag to false (instant rollback)
```

### Database Coexistence

During the migration window, both old and new code paths must work:

- **Reads**: New code sets `app.tenant_id` on the connection and RLS filters automatically. Old code does not set `app.tenant_id`, so RLS is bypassed (FORCE RLS only applies to non-superuser roles; migration uses a dual-role strategy).
- **Writes**: New code writes with `tenant_id`. Old code writes with `tenant_id = 'default'` via column DEFAULT. Backfill script catches any rows missing `tenant_id` (run hourly during migration window).

---

## Section 7: Rollback Plan

### Rollback Triggers

Initiate rollback if any of the following occur within 48 hours of cutover:

- Cross-tenant data leakage detected (any tenant sees another tenant's data)
- Error rate exceeds 5% (compared to pre-migration baseline)
- P95 latency exceeds 2x pre-migration baseline
- Authentication failures exceed 1% of login attempts
- Data integrity check fails (row counts don't match)

### Rollback Procedure

**Step 1: Feature flag off (immediate, <1 minute)**

```
Set MULTI_TENANT_ENABLED=false in production environment
All requests revert to single-tenant behavior instantly
No restart required if using hot-reloading config
```

**Step 2: JWT service rollback (if JWT migration was active)**

```
Revert auth service to issue v1 tokens
Enable v1-only acceptance in auth middleware
Active v2 sessions will expire naturally (or force-expire via Redis flush)
```

**Step 3: Database rollback (if data migration was active)**

```
Disable RLS policies: ALTER TABLE {table} DISABLE ROW LEVEL SECURITY
Revert application code to not set app.tenant_id on connections
Deploy reverted code — tenant_id columns remain but are ignored
Run alembic downgrade if needed to revert schema changes
```

**Step 4: Redis cleanup**

```
Flush tenant-namespaced keys: DEL mingai:*:* (but preserve mingai:{key} pattern)
Or more safely: let keys expire naturally (TTL-based)
```

**Step 5: Search index rollback**

```
Revert code to use original index names (without tenant suffix)
Per-tenant indexes can remain — they're unused but harmless
Clean up per-tenant indexes after confirming rollback is stable
```

### Data Loss Risk Assessment

| Scenario                                | Data Loss Risk | Explanation                                                                                                                    |
| --------------------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Rollback before any new tenants created | ZERO           | All data is in "default" tenant, RLS disabled restores original behavior                                                       |
| Rollback after new tenants created      | LOW            | New tenant data remains in PostgreSQL tables. Default tenant data preserved. New tenant data requires manual export if needed. |
| Rollback after JWT migration            | ZERO           | v1 tokens still work during dual-acceptance window. Force re-login worst case.                                                 |
| Rollback after LLM config migration     | ZERO           | Falling back to `.env` Settings singleton. PostgreSQL tenant_configs table unused but preserved.                               |
| Rollback after RBAC extension           | ZERO           | New roles/permissions are additive. Removing them has no effect on existing roles.                                             |

### Post-Rollback Checklist

- [ ] Feature flag confirmed off in all environments
- [ ] Error rate returned to pre-migration baseline
- [ ] Latency returned to pre-migration baseline
- [ ] Authentication working for all users
- [ ] Data integrity spot-check passed (10 random rows per table)
- [ ] Incident report drafted with root cause
- [ ] Fix planned before next migration attempt

---

## Appendix: Migration Timeline

| Week | Action                                 | Reversible                | Risk   |
| ---- | -------------------------------------- | ------------------------- | ------ |
| 1    | Run Alembic migrations, start backfill | Yes (alembic downgrade)   | Low    |
| 2    | Deploy with feature flag OFF           | Yes (standard rollback)   | Low    |
| 3    | Enable canary (10% traffic)            | Yes (disable canary)      | Medium |
| 4    | Full rollout, monitor 48h              | Yes (feature flag OFF)    | Medium |
| 5    | Begin JWT migration (dual acceptance)  | Yes (revert auth service) | Medium |
| 6    | Clean up v1 token support              | Partial (force re-login)  | Low    |
| 7+   | Continue Phase 2 (LLM Marketplace)     | N/A (new feature)         | Low    |
