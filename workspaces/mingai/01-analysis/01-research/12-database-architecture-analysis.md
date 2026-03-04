# Database Architecture Analysis: Pure PostgreSQL for Multi-Tenant mingai

**Date**: March 4, 2026
**Author**: db-writer
**Status**: Final Decision
**Verdict**: **Pure PostgreSQL -- single database system, no Cosmos DB**

---

## 1. Executive Decision

**mingai will use PostgreSQL as its sole database system.** No hybrid architecture. No Cosmos DB retention. Every Cosmos DB container migrates to a PostgreSQL table.

### Rationale

**One isolation system covers all tables.** PostgreSQL Row-Level Security (RLS) enforces tenant isolation at the database engine level across every table. A hybrid approach would require RLS for PostgreSQL tables and application-layer `TenantScopedRepository` filtering for Cosmos DB containers -- two isolation mechanisms to build, test, audit, and maintain. One missed `tenant_id` filter in the Cosmos DB layer equals a data breach. With pure PostgreSQL, there is exactly one isolation boundary, and it is enforced by the database itself, not application code.

**Cross-database transaction atomicity is eliminated.** In a hybrid architecture, creating a conversation (PostgreSQL) and inserting its first message (Cosmos DB) are two separate transactions. If the message write fails, the conversation exists without a message -- an orphaned record. With pure PostgreSQL, this is a single transaction with automatic rollback on failure.

**Cloud-agnostic deployment.** The same PostgreSQL code runs on:

- AWS Aurora PostgreSQL
- Azure Database for PostgreSQL Flexible Server
- GCP Cloud SQL for PostgreSQL
- AliCloud PolarDB for PostgreSQL
- Self-hosted PostgreSQL 16

Only the connection string changes. Cosmos DB locks mingai to Azure. The previous analysis noted that "Azure also offers PostgreSQL Flexible Server as a first-class service" -- this means there is no Azure ecosystem penalty for choosing PostgreSQL.

**Cosmos DB advantages are premature optimization.** The previous analysis identified three Cosmos DB strengths:

1. **Global multi-region active-active writes** -- mingai is currently single-region. Global distribution is a Phase 5+ concern.
2. **Serverless RU auto-scaling** -- relevant for dev/staging, but production uses provisioned throughput anyway.
3. **Append-only partition-scoped writes for messages** -- PostgreSQL handles this with table partitioning and BRIN indexes at equivalent performance for mingai's current scale (< 100M messages).

**Operational simplicity.** One backup strategy (pg_dump / pg_basebackup / cloud snapshots). One migration tool (Alembic). One monitoring setup (pg_stat_statements, pgBadger). One connection pool (PgBouncer). One set of credentials to rotate. One disaster recovery runbook.

---

## 2. Container to Table Migration Map

### 2.1 Complete Inventory

Source: `app/core/database.py:94-118`, `scripts/provision_cosmosdb.py:61-187`

The aihub2 system uses 23 Cosmos DB containers (2 deprecated). Every container maps to a PostgreSQL table.

| #   | Cosmos DB Container       | Partition Key      | PostgreSQL Table          | Primary Key | Foreign Keys                                | Partition Strategy | Key Indexes                                                           |
| --- | ------------------------- | ------------------ | ------------------------- | ----------- | ------------------------------------------- | ------------------ | --------------------------------------------------------------------- |
| 1   | `users`                   | `/id`              | `users`                   | `id UUID`   | `tenants(id)`                               | None               | UNIQUE(tenant_id, email), idx on azure_oid                            |
| 2   | `roles`                   | `/id`              | `roles`                   | `id UUID`   | `tenants(id)`                               | None               | UNIQUE(tenant_id, name)                                               |
| 3   | `user_roles`              | `/user_id`         | `user_roles`              | `id UUID`   | `users(id)`, `roles(id)`, `tenants(id)`     | None               | UNIQUE(tenant_id, user_id, role_id)                                   |
| 4   | `group_roles`             | `/group_id`        | `group_roles`             | `id UUID`   | `roles(id)`, `tenants(id)`                  | None               | UNIQUE(tenant_id, group_id, role_id)                                  |
| 5   | `group_membership_cache`  | `/group_id`        | Redis (not a table)       | N/A         | N/A                                         | N/A                | N/A -- pure cache with TTL, belongs in Redis                          |
| 6   | `indexes`                 | `/id`              | `indexes`                 | `id UUID`   | `tenants(id)`                               | None               | UNIQUE(tenant_id, name), idx on azure_index_name                      |
| 7   | `conversations`           | `/user_id`         | `conversations`           | `id UUID`   | `users(id)`, `tenants(id)`                  | None               | (tenant_id, user_id, created_at DESC)                                 |
| 8   | `messages`                | `/conversation_id` | `messages`                | `id UUID`   | `conversations(id)`, `tenants(id)`          | **Range by month** | BRIN on created_at, (conversation_id, created_at)                     |
| 9   | `user_preferences`        | `/user_id`         | `user_preferences`        | `id UUID`   | `users(id)`, `tenants(id)`                  | None               | UNIQUE(tenant_id, user_id)                                            |
| 10  | `glossary_terms`          | `/scope`           | `glossary_terms`          | `id UUID`   | `tenants(id)`                               | None               | HNSW on embedding, GIN on search_vector, (tenant_id, scope, category) |
| 11  | `user_profiles`           | `/user_id`         | `user_profiles`           | `id UUID`   | `users(id)`, `tenants(id)`                  | None               | UNIQUE(tenant_id, user_id)                                            |
| 12  | `profile_learning_events` | `/user_id`         | `profile_learning_events` | `id UUID`   | `users(id)`, `tenants(id)`                  | **Range by month** | BRIN on created_at, (tenant_id, user_id, created_at DESC)             |
| 13  | `consent_events`          | `/user_id`         | `consent_events`          | `id UUID`   | `users(id)`, `tenants(id)`                  | None               | (tenant_id, user_id, timestamp DESC)                                  |
| 14  | `feedback`                | `/user_id`         | `feedback`                | `id UUID`   | `users(id)`, `tenants(id)`                  | None               | (tenant_id, message_id), (tenant_id, status, created_at)              |
| 15  | `conversation_documents`  | `/conversation_id` | `conversation_documents`  | `id UUID`   | `conversations(id)`, `tenants(id)`          | None               | (tenant_id, conversation_id)                                          |
| 16  | `document_chunks`         | `/conversation_id` | `document_chunks`         | `id UUID`   | `conversation_documents(id)`, `tenants(id)` | None               | HNSW on embedding, (tenant_id, conversation_id)                       |
| 17  | `audit_logs`              | `/user_id`         | **DROP** (deprecated)     | N/A         | N/A                                         | N/A                | Migrate historical data into `events`, then drop                      |
| 18  | `usage_events`            | `/partition_key`   | **DROP** (deprecated)     | N/A         | N/A                                         | N/A                | Already deprecated, data merged into `events`                         |
| 19  | `usage_daily`             | `/date`            | `usage_daily`             | `id UUID`   | `tenants(id)`                               | None               | (tenant_id, date, service)                                            |
| 20  | `events`                  | `/partition_key`   | `events`                  | `id UUID`   | `tenants(id)`                               | **Range by month** | BRIN on timestamp, composite indexes below                            |
| 21  | `question_categories`     | `/date`            | `question_categories`     | `id UUID`   | `tenants(id)`                               | None               | (tenant_id, date)                                                     |
| 22  | `mcp_servers`             | `/id`              | `mcp_servers`             | `id UUID`   | `tenants(id)`                               | None               | UNIQUE(tenant_id, name)                                               |
| 23  | `notifications`           | `/user_id`         | `notifications`           | `id UUID`   | `users(id)`, `tenants(id)`                  | None               | (tenant_id, user_id, status, created_at DESC)                         |

### 2.2 Migration Tally

| Destination    | Count  | Tables                                                                                                                                                                                                                                                                                     |
| -------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **PostgreSQL** | **19** | users, roles, user_roles, group_roles, indexes, conversations, messages, user_preferences, glossary_terms, user_profiles, profile_learning_events, consent_events, feedback, conversation_documents, document_chunks, usage_daily, events, question_categories, mcp_servers, notifications |
| **Redis**      | **1**  | group_membership_cache (pure TTL cache)                                                                                                                                                                                                                                                    |
| **Dropped**    | **2**  | audit_logs (deprecated), usage_events (deprecated)                                                                                                                                                                                                                                         |

Note: `notifications` has a 30-day retention policy. In the previous hybrid analysis, this was kept in Cosmos DB for per-item TTL. PostgreSQL handles this with a scheduled `pg_cron` job: `DELETE FROM notifications WHERE created_at < NOW() - INTERVAL '30 days'`. Similarly, `profile_learning_events` (30-day TTL) and `events` (configurable TTL) use the same pattern. This is simpler than managing per-document TTL in a separate database system.

### 2.3 The Four Previously-Cosmos Containers: Design Rationale

The previous analysis kept four containers in Cosmos DB: `messages`, `events`/`usage_events`, `profile_learning_events`, and `notifications`. Here is why each works in PostgreSQL:

**messages**: The previous analysis scored this 5/5 for NoSQL fit ("append-only, conversation-scoped, high write volume, variable metadata"). PostgreSQL handles each of these:

- Append-only: `INSERT` into a partitioned table is O(1), same as Cosmos DB
- Conversation-scoped reads: composite index `(conversation_id, created_at)` provides partition-equivalent read performance
- High write volume: monthly range partitioning distributes I/O; BRIN index on `created_at` is 100x smaller than B-tree for time-ordered data
- Variable metadata: JSONB column stores sources, confidence breakdown, token counts -- indexed with GIN when needed

**events**: 11 composite indexes in Cosmos DB (from `app/modules/events/query_service.py`) signal over-indexing to work around limited query flexibility. PostgreSQL replaces all 11 with 4-5 well-chosen B-tree indexes plus BRIN on timestamp. Monthly partitioning handles time-bounded queries (the common `user_id:YYYY-MM` partition pattern maps directly to range partitions).

**profile_learning_events**: Write-heavy time-series with 30-day TTL. Monthly partitioning + `pg_cron` drop of expired partitions is simpler and more efficient than per-document TTL. Dropping an entire partition is instant (metadata-only operation) vs scanning and deleting individual documents.

**notifications**: Low-volume transient data. A standard table with a composite index `(tenant_id, user_id, status)` and a `pg_cron` cleanup job handles this trivially. The previous NoSQL fit score of 4 was based on "per-item TTL" -- a feature PostgreSQL does not need because batch deletion of expired rows is more efficient than per-item TTL tracking.

---

## 3. PostgreSQL RLS Tenant Isolation

### 3.1 Core RLS Design

Every table with tenant data gets the same RLS policy pattern:

```sql
-- Step 1: Enable RLS on the table
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

-- Step 2: Force RLS even for table owners (prevents superuser bypass in application code)
ALTER TABLE conversations FORCE ROW LEVEL SECURITY;

-- Step 3: Create the isolation policy
CREATE POLICY tenant_isolation ON conversations
    USING (tenant_id = current_setting('app.tenant_id')::UUID);

-- Step 4: Create a write policy (prevents inserting rows for other tenants)
CREATE POLICY tenant_isolation_insert ON conversations
    FOR INSERT
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);
```

The `app.tenant_id` session variable is set once per database connection, from the JWT tenant claim:

```sql
-- Set at connection time via middleware (before any queries)
SET app.tenant_id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';
```

After this SET, every `SELECT`, `UPDATE`, `DELETE` on every RLS-enabled table automatically filters by `tenant_id`. There is no way for application code to read or modify another tenant's data, even with raw SQL.

### 3.2 FastAPI Middleware Pattern

```python
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

async def set_tenant_context(request: Request, session: AsyncSession):
    """Set PostgreSQL session variable from JWT tenant claim.

    Called at the start of every request, before any database queries.
    The RLS policy on every table uses current_setting('app.tenant_id')
    to filter rows, so this single SET protects all tables.
    """
    tenant_id = request.state.tenant_id  # Extracted from JWT by auth middleware
    await session.execute(
        text("SET app.tenant_id = :tenant_id"),
        {"tenant_id": str(tenant_id)}
    )
```

This middleware integrates with the existing FastAPI dependency injection:

```python
from fastapi import Depends

async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        await set_tenant_context(request, session)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### 3.3 Platform Admin Bypass

For cross-tenant operations (platform admin dashboard, tenant provisioning, analytics aggregation), a separate database role bypasses RLS:

```sql
-- Create a platform admin role that bypasses RLS
CREATE ROLE platform_admin NOLOGIN;
GRANT ALL ON ALL TABLES IN SCHEMA public TO platform_admin;
-- platform_admin does NOT have FORCE ROW LEVEL SECURITY,
-- so RLS does not apply to this role

-- Application database user (used by FastAPI)
CREATE ROLE app_user LOGIN PASSWORD 'from-env-var';
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
-- app_user HAS FORCE ROW LEVEL SECURITY, so RLS always applies

-- For admin operations, SET ROLE within the session:
SET ROLE platform_admin;
-- Now queries bypass RLS (cross-tenant access)
-- After admin operation:
RESET ROLE;
-- Back to app_user with RLS enforced
```

The FastAPI admin middleware uses this pattern:

```python
async def admin_bypass_context(session: AsyncSession):
    """Temporarily bypass RLS for platform admin operations.

    Only called from admin endpoints that require cross-tenant access.
    The calling endpoint must verify platform_admin permission first.
    """
    await session.execute(text("SET ROLE platform_admin"))
    try:
        yield session
    finally:
        await session.execute(text("RESET ROLE"))
```

### 3.4 RLS Policy Applied to All 19 Tables

Every tenant-scoped table gets identical RLS policies. The `tenants` table itself does NOT get RLS (it is only accessed by platform admin operations). The `role_index_permissions` join table inherits tenant scoping through its FK to `roles`.

Tables with RLS:
`users`, `roles`, `user_roles`, `group_roles`, `indexes`, `conversations`, `messages`, `user_preferences`, `glossary_terms`, `user_profiles`, `profile_learning_events`, `consent_events`, `feedback`, `conversation_documents`, `document_chunks`, `usage_daily`, `events`, `question_categories`, `mcp_servers`, `notifications`

All 20 tables use the same policy:

```sql
CREATE POLICY tenant_isolation ON <table_name>
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON <table_name>
    FOR INSERT
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);
```

---

## 4. Schema Design for High-Volume Tables

### 4.1 Messages Table (Partitioned)

Source container: `messages` (partition key `/conversation_id`), previously scored 5/5 NoSQL fit.

```sql
-- Enable pgcrypto for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Monthly range-partitioned messages table
CREATE TABLE messages (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    conversation_id UUID NOT NULL,
    user_id UUID NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    content_length INT GENERATED ALWAYS AS (length(content)) STORED,

    -- Source citations (variable per message, formerly flexible Cosmos DB document fields)
    sources JSONB DEFAULT '[]',
    -- Example: [{"title": "Employee Handbook", "score": 0.87, "url": "...", "chunk_id": "chunk-123"}]

    -- Confidence scoring
    confidence NUMERIC(4,3),
    confidence_breakdown JSONB DEFAULT '{}',
    -- Example: {"source_agreement": 0.9, "vector_similarity": 0.85, "coverage": 0.75}

    -- Token tracking
    tokens_input INT DEFAULT 0,
    tokens_output INT DEFAULT 0,
    cost_usd NUMERIC(10,6) DEFAULT 0,

    -- Response metadata
    response_time_ms INT,
    intent TEXT,
    intent_score NUMERIC(4,3),
    indexes_searched TEXT[] DEFAULT '{}',
    used_internet_search BOOLEAN DEFAULT FALSE,

    -- Feedback (denormalized for read performance; canonical in feedback table)
    feedback_rating SMALLINT,
    feedback_type TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    edited_at TIMESTAMPTZ,

    -- Composite PK includes partition key for partition pruning
    PRIMARY KEY (id, created_at),

    -- FK to conversations (not enforced across partitions; validated at application layer)
    CONSTRAINT fk_messages_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
) PARTITION BY RANGE (created_at);

-- Enable RLS
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON messages
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON messages
    FOR INSERT
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- BRIN index on created_at: ideal for append-only time-ordered data
-- ~100x smaller than B-tree, nearly as fast for range scans
CREATE INDEX idx_messages_created_brin ON messages USING BRIN (created_at)
    WITH (pages_per_range = 32);

-- B-tree for conversation timeline queries (the primary read pattern)
CREATE INDEX idx_messages_conversation ON messages (conversation_id, created_at);

-- B-tree for per-user message lookup (analytics)
CREATE INDEX idx_messages_user ON messages (tenant_id, user_id, created_at DESC);

-- Monthly partitions managed by pg_partman
-- Install pg_partman extension:
CREATE EXTENSION IF NOT EXISTS pg_partman;

SELECT partman.create_parent(
    p_parent_table := 'public.messages',
    p_control := 'created_at',
    p_type := 'range',
    p_interval := '1 month',
    p_premake := 3,           -- Pre-create 3 months ahead
    p_start_partition := '2026-01-01'
);

-- pg_partman maintenance (run via pg_cron every hour):
-- SELECT partman.run_maintenance('public.messages');
```

**BRIN vs B-tree decision**: Messages are inserted in time order (append-only). BRIN indexes exploit this physical ordering to achieve ~100x smaller index size. A B-tree on `created_at` for 100M messages would be ~2GB; BRIN is ~20MB. For range scans (`WHERE created_at BETWEEN ...`), BRIN performance is within 10% of B-tree. The conversation-scoped index `(conversation_id, created_at)` remains B-tree because conversation IDs are not physically ordered.

**JSONB vs typed columns decision**: Fields like `sources`, `confidence_breakdown` are JSONB because their internal structure varies per message (different numbers of sources, different confidence metrics). Fields like `role`, `content`, `confidence`, `tokens_input` are typed columns because they have fixed schema and benefit from type checking, constraints, and columnar statistics.

### 4.2 Events Table (Partitioned)

Source container: `events` (partition key `/partition_key` = `user_id:YYYY-MM`).

```sql
CREATE TABLE events (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    email TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Event classification
    event_type TEXT NOT NULL CHECK (event_type IN (
        'query', 'response', 'error', 'login', 'logout',
        'role_assigned', 'role_revoked', 'export', 'sync',
        'feedback', 'mcp_call', 'admin_action'
    )),
    action TEXT NOT NULL,      -- detailed action name: chat_query, user_create, etc.
    result TEXT NOT NULL CHECK (result IN ('success', 'failure', 'partial')),

    -- Context references
    session_id UUID,
    conversation_id UUID,
    message_id UUID,

    -- Client context
    ip_address INET,
    user_agent TEXT,

    -- Event-specific details (flexible schema per event_type)
    details JSONB DEFAULT '{}',
    -- Example for query event:
    -- {"query_text": "...", "intent": "policy_question", "indexes_searched": ["hr"],
    --  "results_count": 5, "response_time_ms": 2847, "tokens_used": 401, "cost_usd": 0.01}

    -- Error context (populated when result = 'failure')
    error JSONB,

    -- Metadata
    tags TEXT[] DEFAULT '{}',
    country TEXT,
    region TEXT,

    -- Partition key for range partitioning
    PRIMARY KEY (id, timestamp),
    CONSTRAINT fk_events_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
) PARTITION BY RANGE (timestamp);

-- RLS
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON events
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON events
    FOR INSERT
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- BRIN on timestamp (primary ordering dimension)
CREATE INDEX idx_events_timestamp_brin ON events USING BRIN (timestamp)
    WITH (pages_per_range = 32);

-- Replace the 11 Cosmos DB composite indexes with 5 targeted indexes:

-- 1. User timeline (replaces Cosmos composite: user_id ASC, timestamp DESC)
CREATE INDEX idx_events_user_timeline ON events (tenant_id, user_id, timestamp DESC);

-- 2. Event type aggregation (replaces Cosmos composite: event_type ASC, timestamp DESC)
CREATE INDEX idx_events_type ON events (tenant_id, event_type, timestamp DESC);

-- 3. Action audit (replaces Cosmos composite: action ASC, timestamp DESC)
CREATE INDEX idx_events_action ON events (tenant_id, action, timestamp DESC);

-- 4. Conversation drill-down (replaces Cosmos composite: conversation_id ASC, timestamp ASC)
CREATE INDEX idx_events_conversation ON events (conversation_id, timestamp);

-- 5. Session replay (replaces Cosmos composite: session_id ASC, timestamp ASC)
CREATE INDEX idx_events_session ON events (session_id, timestamp);

-- Note: the Cosmos DB indexes for email lookup, cost aggregation, MCP analytics,
-- error tracking, and tag filtering are handled by the above indexes + the JSONB
-- details column. PostgreSQL's query planner can combine indexes efficiently;
-- Cosmos DB requires explicit composite indexes for every query pattern.

-- Monthly partitions via pg_partman
SELECT partman.create_parent(
    p_parent_table := 'public.events',
    p_control := 'timestamp',
    p_type := 'range',
    p_interval := '1 month',
    p_premake := 3,
    p_start_partition := '2026-01-01'
);

-- Auto-pruning: drop partitions older than retention period
-- Configured via pg_partman retention:
UPDATE partman.part_config
SET retention = '90 days',
    retention_keep_table = false,
    retention_keep_index = false
WHERE parent_table = 'public.events';
```

### 4.3 Profile Learning Events (Partitioned)

```sql
CREATE TABLE profile_learning_events (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Learning data (flexible per event type)
    data JSONB NOT NULL DEFAULT '{}',
    -- Examples:
    -- {"topic": "finance", "engagement_score": 0.85, "query": "401k matching"}
    -- {"preferred_length": "detailed", "used_citations": true}

    PRIMARY KEY (id, timestamp),
    CONSTRAINT fk_ple_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
) PARTITION BY RANGE (timestamp);

-- RLS
ALTER TABLE profile_learning_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE profile_learning_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON profile_learning_events
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON profile_learning_events
    FOR INSERT
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- BRIN for time ordering
CREATE INDEX idx_ple_timestamp_brin ON profile_learning_events USING BRIN (timestamp)
    WITH (pages_per_range = 32);

-- User timeline lookup
CREATE INDEX idx_ple_user ON profile_learning_events (tenant_id, user_id, timestamp DESC);

-- Monthly partitions with 30-day retention (auto-drop via pg_partman)
SELECT partman.create_parent(
    p_parent_table := 'public.profile_learning_events',
    p_control := 'timestamp',
    p_type := 'range',
    p_interval := '1 month',
    p_premake := 2,
    p_start_partition := '2026-01-01'
);

UPDATE partman.part_config
SET retention = '30 days',
    retention_keep_table = false
WHERE parent_table = 'public.profile_learning_events';
```

### 4.4 Notifications Table

```sql
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL,
    type TEXT NOT NULL CHECK (type IN (
        'query_complete', 'sync_done', 'error', 'mention',
        'role_change', 'system', 'warning'
    )),
    title TEXT NOT NULL,
    body TEXT,
    action_url TEXT,
    action_label TEXT,
    priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    status TEXT NOT NULL DEFAULT 'unread' CHECK (status IN ('unread', 'read', 'dismissed')),

    -- Delivery tracking
    delivery_channels JSONB DEFAULT '{"in_app": true, "email": false, "web_push": false}',

    -- Metadata (source, related entity IDs, etc.)
    metadata JSONB DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '30 days')
);

-- RLS
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON notifications
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON notifications
    FOR INSERT
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- Primary query: user's unread notifications
CREATE INDEX idx_notifications_user_status ON notifications
    (tenant_id, user_id, status, created_at DESC);

-- Cleanup: scheduled via pg_cron (runs daily at 03:00 UTC)
-- SELECT cron.schedule('cleanup-notifications', '0 3 * * *',
--     $$DELETE FROM notifications WHERE expires_at < NOW()$$);
```

---

## 5. pgvector Integration

### 5.1 Problem: Python-Side Cosine Similarity

Source: `app/modules/glossary/service.py:97-163`

The current glossary service loads ALL embeddings from Cosmos DB into Python memory, then uses numpy to compute cosine similarity:

```python
# Current implementation (from service.py:126-163):
# 1. Load all glossary terms from Cosmos DB (potentially thousands)
# 2. Extract embeddings into numpy array
# 3. Compute cosine similarity against query embedding
# 4. Sort and return top-k
#
# Problems:
# - Memory: 1000 terms x 3072 dims x 4 bytes = 12MB per request
# - Latency: numpy computation on every query
# - Scale: does not work beyond ~10K terms
# - No RLS: filtering by tenant is application code
```

### 5.2 pgvector Solution

```sql
-- Install pgvector (version 0.7.0+ for HNSW support)
CREATE EXTENSION IF NOT EXISTS vector;

-- Glossary terms table with vector column
CREATE TABLE glossary_terms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    term TEXT NOT NULL,
    definition TEXT NOT NULL,
    description TEXT,
    scope TEXT NOT NULL DEFAULT 'enterprise',
    scope_id TEXT,                               -- index ID for index-scoped terms
    category TEXT,
    synonyms TEXT[] DEFAULT '{}',
    embedding vector(3072),                      -- text-embedding-3-large output dimension
    usage_count INT DEFAULT 0,
    usage_contexts TEXT[] DEFAULT '{}',
    related_terms TEXT[] DEFAULT '{}',
    confidence NUMERIC(4,3) DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID,
    last_used TIMESTAMPTZ,

    -- Auto-generated full-text search vector
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(term, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(definition, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(description, '')), 'C')
    ) STORED
);

-- RLS
ALTER TABLE glossary_terms ENABLE ROW LEVEL SECURITY;
ALTER TABLE glossary_terms FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON glossary_terms
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON glossary_terms
    FOR INSERT
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- HNSW index for approximate nearest neighbor search
-- HNSW provides better recall than IVFFlat and does not require training
CREATE INDEX idx_glossary_embedding ON glossary_terms
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- GIN index for full-text search
CREATE INDEX idx_glossary_search ON glossary_terms USING GIN (search_vector);

-- Lookup indexes
CREATE INDEX idx_glossary_scope ON glossary_terms (tenant_id, scope, category);
CREATE UNIQUE INDEX idx_glossary_term_scope ON glossary_terms (tenant_id, term, scope, scope_id)
    WHERE scope_id IS NOT NULL;
```

### 5.3 Query Pattern: Semantic Search

```sql
-- Replace 50+ lines of Python numpy code with one SQL query.
-- RLS automatically filters to current tenant.
-- HNSW index provides ~95% recall at sub-millisecond latency.

SELECT
    id,
    term,
    definition,
    category,
    1 - (embedding <=> $1::vector) AS similarity_score
FROM glossary_terms
WHERE scope IN ('enterprise', 'index')
  AND (scope_id IS NULL OR scope_id = ANY($2::text[]))
ORDER BY embedding <=> $1::vector
LIMIT $3;

-- $1 = query embedding (3072-dim vector from text-embedding-3-large)
-- $2 = array of index IDs the user has access to
-- $3 = top-k (typically 5)
```

### 5.4 Document Chunks with pgvector

```sql
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    document_id UUID NOT NULL REFERENCES conversation_documents(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(3072),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON document_chunks
    USING (tenant_id = current_setting('app.tenant_id')::UUID);

CREATE INDEX idx_chunks_embedding ON document_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_chunks_document ON document_chunks (tenant_id, conversation_id, document_id);
```

---

## 6. Cloud Deployment Matrix

### 6.1 Provider Mapping

| Component       | AWS (Phase 1)                | Azure                         | GCP                      | Self-hosted               |
| --------------- | ---------------------------- | ----------------------------- | ------------------------ | ------------------------- |
| PostgreSQL      | Aurora PostgreSQL 16         | Azure DB for PostgreSQL Flex  | Cloud SQL for PostgreSQL | PostgreSQL 16 + Patroni   |
| pgvector        | Aurora pgvector (built-in)   | pgvector extension (built-in) | Cloud SQL pgvector       | pgvector 0.7.0+           |
| pg_partman      | Aurora pg_partman (built-in) | Azure pg_partman (supported)  | Cloud SQL pg_partman     | pg_partman 5.0+           |
| Object Storage  | S3                           | Azure Blob Storage            | GCS                      | MinIO                     |
| Search (RAG)    | OpenSearch Service           | Azure AI Search               | Vertex AI Search         | OpenSearch 2.x            |
| Cache           | ElastiCache for Redis        | Azure Cache for Redis         | Memorystore for Redis    | Redis 7.x OSS             |
| LLM             | Bedrock + Azure OpenAI       | Azure OpenAI                  | Vertex AI                | Self-hosted (vLLM/Ollama) |
| Auth            | Cognito + OIDC               | Azure AD / Entra ID           | Cloud Identity           | Keycloak                  |
| Connection Pool | RDS Proxy                    | PgBouncer on Flex Server      | Cloud SQL Auth Proxy     | PgBouncer 1.22+           |
| Cron/Scheduler  | EventBridge + Lambda         | Azure Functions Timer         | Cloud Scheduler          | pg_cron extension         |

### 6.2 Cloud Selection Pattern

Cloud provider is selected via environment variable:

```
CLOUD_PROVIDER=aws|azure|gcp|self-hosted
```

This variable controls which provider implementation module is loaded for:

- Object storage (S3 vs Blob vs GCS)
- Search service (OpenSearch vs Azure AI Search vs Vertex AI Search)
- LLM provider routing (Bedrock vs Azure OpenAI vs Vertex AI)
- Auth provider (Cognito vs Entra ID vs Cloud Identity)

The PostgreSQL connection is provider-agnostic -- only `DATABASE_URL` changes:

```
# AWS Aurora
DATABASE_URL=postgresql+asyncpg://user:pass@aurora-cluster.us-east-1.rds.amazonaws.com:5432/mingai

# Azure Flexible Server
DATABASE_URL=postgresql+asyncpg://user:pass@mingai-db.postgres.database.azure.com:5432/mingai

# GCP Cloud SQL
DATABASE_URL=postgresql+asyncpg://user:pass@/mingai?host=/cloudsql/project:region:instance

# Self-hosted
DATABASE_URL=postgresql+asyncpg://user:pass@db.internal:5432/mingai
```

### 6.3 Phase Timeline

- **Phase 1 (weeks 1-8)**: AWS Aurora PostgreSQL. Full schema, RLS, pgvector, pg_partman.
- **Phase 2-4**: Feature development on AWS infrastructure.
- **Phase 5**: Azure and GCP deployment support. Only provider-specific modules (object storage, search, LLM routing) need adaptation. PostgreSQL layer is identical.

### 6.4 PostgreSQL Extension Requirements

| Extension    | Version  | Purpose                                   | Availability                       |
| ------------ | -------- | ----------------------------------------- | ---------------------------------- |
| `pgvector`   | >= 0.7.0 | Vector similarity search (HNSW, IVFFlat)  | Aurora, Azure Flex, Cloud SQL, OSS |
| `pg_partman` | >= 5.0   | Automated table partitioning management   | Aurora, Azure Flex, Cloud SQL, OSS |
| `pg_cron`    | >= 1.6   | Scheduled jobs (TTL cleanup, maintenance) | Aurora, Azure Flex, OSS            |
| `pgcrypto`   | >= 1.3   | `gen_random_uuid()` function              | All (built into core)              |
| `pg_trgm`    | >= 1.6   | Trigram similarity for fuzzy text search  | All (built into contrib)           |

---

## 7. Migration Strategy: Cosmos DB to PostgreSQL

### 7.1 Overall Approach

The migration follows a container-by-container strategy with zero downtime. Each container is migrated independently, validated, and then the application is switched to PostgreSQL for that entity.

**Migration order** (based on dependency chain and risk):

1. **Foundation tables** (no FKs to other app tables): `tenants`
2. **Core identity** (referenced by everything): `users`, `roles`
3. **RBAC**: `user_roles`, `group_roles`, `role_index_permissions`
4. **Content configuration**: `indexes`, `mcp_servers`
5. **User data**: `user_preferences`, `user_profiles`, `glossary_terms`
6. **Conversations + messages**: `conversations`, `messages`, `conversation_documents`, `document_chunks`
7. **Analytics + audit**: `events`, `usage_daily`, `question_categories`, `consent_events`
8. **Transient data**: `feedback`, `notifications`, `profile_learning_events`

### 7.2 Per-Container Migration Pattern

For each Cosmos DB container:

**Step 1: Export from Cosmos DB**

```bash
# Use Azure Cosmos DB data migration tool (dt) or custom script
# Export to NDJSON (newline-delimited JSON)
az cosmosdb sql container export \
    --account-name mingai-cosmos \
    --database-name mingai-db \
    --name users \
    --output-path /exports/users.ndjson
```

Alternatively, use the Cosmos DB change feed to stream documents:

```python
import os
from dotenv import load_dotenv
load_dotenv()

from azure.cosmos import CosmosClient

client = CosmosClient(
    os.environ.get("COSMOS_ENDPOINT"),
    os.environ.get("COSMOS_KEY")
)
db = client.get_database_client(os.environ.get("COSMOS_DATABASE"))
container = db.get_container_client("users")

# Stream all documents
documents = list(container.read_all_items())
```

**Step 2: Transform**

Transform Cosmos DB documents to PostgreSQL rows. Key transformations:

| Cosmos DB Pattern          | PostgreSQL Transformation                                |
| -------------------------- | -------------------------------------------------------- |
| `id` (string)              | `id` (UUID) -- parse or generate                         |
| `/partition_key` field     | Drop -- partition is structural, not a data field        |
| `_ts`, `_etag`, `_rid`     | Drop -- Cosmos DB system fields                          |
| `_self`, `_attachments`    | Drop -- Cosmos DB internal references                    |
| Nested JSON objects        | JSONB column or extracted typed columns                  |
| `ARRAY_CONTAINS` arrays    | Join table (`role_index_permissions`) or `TEXT[]` column |
| Missing `tenant_id`        | Assign default tenant UUID                               |
| `created_at` (ISO string)  | `TIMESTAMPTZ` -- parse ISO 8601                          |
| Per-item TTL (`ttl` field) | `expires_at TIMESTAMPTZ` or pg_partman retention         |

**Step 3: Import into PostgreSQL**

```python
import os
from dotenv import load_dotenv
load_dotenv()

import asyncpg
import json

async def import_users(export_path: str):
    conn = await asyncpg.connect(os.environ.get("DATABASE_URL"))

    with open(export_path, 'r') as f:
        for line in f:
            doc = json.loads(line)
            await conn.execute('''
                INSERT INTO users (id, tenant_id, email, full_name, azure_oid,
                    is_active, department, job_title, last_login, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (id) DO NOTHING
            ''',
                doc['id'],
                DEFAULT_TENANT_ID,  # from environment
                doc['email'],
                doc.get('full_name', ''),
                doc.get('azure_oid'),
                doc.get('is_active', True),
                doc.get('department'),
                doc.get('job_title'),
                doc.get('last_login'),
                doc.get('created_at'),
                doc.get('updated_at'),
            )

    await conn.close()
```

**Step 4: Validate**

```python
async def validate_migration(container_name: str):
    # Count check
    cosmos_count = len(list(container.read_all_items()))
    pg_count = await conn.fetchval(f"SELECT COUNT(*) FROM {container_name}")
    assert cosmos_count == pg_count, f"Count mismatch: Cosmos={cosmos_count}, PG={pg_count}"

    # Spot check: compare 100 random documents
    cosmos_docs = list(container.query_items(
        "SELECT * FROM c OFFSET 0 LIMIT 100", enable_cross_partition_query=True
    ))
    for doc in cosmos_docs:
        pg_row = await conn.fetchrow(
            f"SELECT * FROM {container_name} WHERE id = $1", doc['id']
        )
        assert pg_row is not None, f"Missing document: {doc['id']}"

    # FK integrity check
    fk_violations = await conn.fetch("""
        SELECT conname, conrelid::regclass
        FROM pg_constraint
        WHERE contype = 'f'
          AND NOT convalidated
    """)
    assert len(fk_violations) == 0, f"FK violations: {fk_violations}"
```

### 7.3 Special Migration Cases

**`roles` container -- ARRAY_CONTAINS to join table:**

The `index_permissions` array in each role document becomes rows in `role_index_permissions`:

```python
for role_doc in cosmos_roles:
    # Insert the role itself
    await conn.execute("INSERT INTO roles (...) VALUES (...)", ...)

    # Extract index_permissions array and create join table rows
    index_ids = role_doc.get('permissions', {}).get('index_ids', [])
    for index_id in index_ids:
        await conn.execute('''
            INSERT INTO role_index_permissions (role_id, index_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
        ''', role_doc['id'], index_id)
```

**`events` container -- composite partition_key decomposition:**

The Cosmos DB partition key `user_id:YYYY-MM` is decomposed:

```python
for event_doc in cosmos_events:
    # Parse composite partition key
    pk = event_doc.get('partition_key', '')
    parts = pk.split(':')
    user_id = parts[0] if parts else event_doc.get('user_id')
    # The YYYY-MM part is implicit from the timestamp

    await conn.execute("INSERT INTO events (...) VALUES (...)", ...)
    # Partitioning by timestamp (monthly range) replaces the manual partition_key
```

**`messages` container -- high volume, batch import:**

For large message volumes (millions of rows), use PostgreSQL `COPY` for bulk import:

```bash
# Convert NDJSON to CSV
cat messages.ndjson | jq -r '[.id, .tenant_id, .conversation_id, ...] | @csv' > messages.csv

# Bulk import via COPY (100x faster than INSERT)
psql $DATABASE_URL -c "\COPY messages FROM 'messages.csv' WITH (FORMAT csv, HEADER false)"
```

### 7.4 Dual-Write Transition Period

For zero-downtime migration of high-traffic containers (`messages`, `events`):

1. **Deploy dual-write**: Application writes to both Cosmos DB and PostgreSQL
2. **Backfill**: Import all historical data from Cosmos DB to PostgreSQL
3. **Validate**: Run comparison queries to verify data consistency
4. **Switch reads**: Application reads from PostgreSQL
5. **Remove Cosmos DB writes**: Application writes only to PostgreSQL
6. **Decommission**: Remove Cosmos DB container after retention period

### 7.5 Alembic Migration Management

All schema changes are managed via Alembic migrations:

```python
# alembic/versions/001_initial_schema.py
def upgrade():
    # Create tenants table (no RLS -- platform-level)
    op.create_table('tenants',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('slug', sa.Text(), unique=True, nullable=False),
        sa.Column('tier', sa.Text(), server_default='standard'),
        sa.Column('settings', sa.JSON(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # Create users table with RLS
    op.create_table('users', ...)
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON users
            USING (tenant_id = current_setting('app.tenant_id')::UUID)
    """)
    # ... repeat for all tables

def downgrade():
    op.drop_table('users')
    op.drop_table('tenants')
```

---

## 8. What Changed from Previous Analysis

### 8.1 Decision Change

**Previous recommendation** (version 1.0): Hybrid architecture -- 15 tables in PostgreSQL, 4 containers in Cosmos DB (messages, events, profile_learning_events, notifications).

**New decision** (version 2.0): Pure PostgreSQL. All 19 data tables in PostgreSQL, 1 cache layer in Redis, 2 deprecated containers dropped.

### 8.2 Why the Change

The hybrid recommendation was technically sound for a single-system optimization perspective. However, it optimized for the wrong axis:

1. **Dual isolation systems are a liability, not a feature.** RLS for 15 PostgreSQL tables + application-layer filtering for 4 Cosmos DB containers = two isolation mechanisms that must both be correct. In practice, the Cosmos DB side would be the weaker link (no database-enforced isolation), creating an asymmetric security posture.

2. **Cross-database transactions create orphaned data.** Creating a conversation (PostgreSQL) and its first message (Cosmos DB) requires coordinating two systems. PostgreSQL transactions eliminate this class of bug entirely.

3. **Operational overhead of two database systems.** Two backup strategies, two monitoring setups, two connection management approaches, two sets of credentials, two failure modes. For a startup-stage product, this complexity is unjustified.

4. **The NoSQL advantages do not apply at mingai's current scale.** Cosmos DB's strengths (global distribution, auto-scaling RU, partition-scoped writes) matter at >100M writes/day or multi-region deployments. mingai is single-region with <1M writes/day. PostgreSQL with monthly partitioning and BRIN indexes handles this load without breaking a sweat.

5. **Cloud lock-in eliminated.** Cosmos DB is Azure-only. PostgreSQL runs identically on AWS Aurora, Azure Flexible Server, GCP Cloud SQL, and self-hosted. This is critical for enterprise customers who may require specific cloud providers.

### 8.3 Impact on Phase 1 Timeline

**Timeline remains 8 weeks** as estimated in the hybrid analysis. The work breakdown shifts:

| Hybrid Plan Task                            | Pure PostgreSQL Task                         | Effort Change |
| ------------------------------------------- | -------------------------------------------- | ------------- |
| PostgreSQL schema (15 tables)               | PostgreSQL schema (19 tables + partitioning) | +1 week       |
| Cosmos DB tenant_id backfill (4 containers) | Eliminated                                   | -1 week       |
| Dual-system connection management           | Single connection pool (PgBouncer)           | -0.5 weeks    |
| Dual-system monitoring setup                | Single monitoring setup (pg_stat_statements) | -0.5 weeks    |
| Integration testing (two systems)           | Integration testing (one system)             | -1 week       |
| pg_partman + BRIN for messages/events       | Same                                         | +1 week       |
| pg_cron for TTL cleanup                     | New task                                     | +0.5 weeks    |
| Alembic migrations (19 tables)              | Same scope as hybrid, slightly more tables   | +0.5 weeks    |

**Net change**: approximately neutral. The additional schema work for 4 more tables is offset by eliminating dual-system complexity.

### 8.4 Risk Assessment

| Risk                                      | Mitigation                                                                 |
| ----------------------------------------- | -------------------------------------------------------------------------- |
| Messages table write performance at scale | Monthly partitioning + BRIN index; benchmark before launch                 |
| Events table query flexibility            | 5 targeted indexes replace 11 Cosmos DB composites; EXPLAIN ANALYZE        |
| pgvector accuracy vs dedicated vector DB  | HNSW with ef_construction=64 provides 95%+ recall; sufficient for glossary |
| pg_partman auto-maintenance reliability   | pg_cron scheduled maintenance + monitoring alerts on partition creation    |
| Partition pruning for time-range queries  | PostgreSQL 16 has improved partition pruning; test with EXPLAIN            |

---

## Appendix A: Complete PostgreSQL Schema (Core Tables)

```sql
-- ============================================================
-- Extensions
-- ============================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;         -- pgvector 0.7.0+
CREATE EXTENSION IF NOT EXISTS pg_partman;     -- automated partitioning
CREATE EXTENSION IF NOT EXISTS pg_trgm;        -- trigram similarity search
-- pg_cron is loaded via shared_preload_libraries in postgresql.conf

-- ============================================================
-- Tenants (no RLS -- platform-level table)
-- ============================================================
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    tier TEXT NOT NULL DEFAULT 'standard' CHECK (tier IN ('free', 'standard', 'enterprise')),
    settings JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Users
-- ============================================================
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    email TEXT NOT NULL,
    full_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    azure_oid TEXT,
    auth_provider TEXT DEFAULT 'azure_ad',
    is_active BOOLEAN DEFAULT TRUE,
    is_admin BOOLEAN DEFAULT FALSE,
    department TEXT,
    job_title TEXT,
    manager_email TEXT,
    office_location TEXT,
    phone TEXT,
    profile_picture_url TEXT,
    last_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID,
    updated_by UUID,
    UNIQUE(tenant_id, email)
);
CREATE INDEX idx_users_azure_oid ON users (azure_oid) WHERE azure_oid IS NOT NULL;
CREATE INDEX idx_users_tenant ON users (tenant_id, is_active);
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON users
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON users
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- Roles
-- ============================================================
CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    display_name TEXT,
    description TEXT,
    is_system_role BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    permissions JSONB DEFAULT '{}',
    -- permissions stores system_functions and data_access rules:
    -- {"system_functions": ["chat:query", "conversation:read"],
    --  "data_access": {"conversations": "own_only", "analytics": "none"}}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID,
    UNIQUE(tenant_id, name)
);
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE roles FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON roles
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON roles
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- User-Role Assignments (M:N join table)
-- ============================================================
CREATE TABLE user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    assignment_type TEXT NOT NULL DEFAULT 'direct' CHECK (assignment_type IN ('direct', 'group')),
    source_group_id TEXT,          -- Azure AD group ID if assignment_type = 'group'
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    assigned_by UUID REFERENCES users(id),
    expires_at TIMESTAMPTZ,        -- optional time-limited roles
    UNIQUE(tenant_id, user_id, role_id)
);
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_roles FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON user_roles
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON user_roles
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- Group-Role Assignments (Azure AD group to role mapping)
-- ============================================================
CREATE TABLE group_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    group_id TEXT NOT NULL,        -- Azure AD group object ID
    group_name TEXT,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    is_active BOOLEAN DEFAULT TRUE,
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    assigned_by UUID REFERENCES users(id),
    last_synced TIMESTAMPTZ,
    UNIQUE(tenant_id, group_id, role_id)
);
ALTER TABLE group_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_roles FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON group_roles
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON group_roles
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- Indexes (Search index configuration)
-- ============================================================
CREATE TABLE indexes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    display_name TEXT,
    description TEXT,
    category TEXT,
    source_type TEXT CHECK (source_type IN ('sharepoint', 'knowledge_base', 'custom', 'upload')),
    source_url TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    is_system_index BOOLEAN DEFAULT FALSE,
    search_config JSONB DEFAULT '{}',
    -- {"endpoint": "...", "index_name": "...", "embedding_deployment": "text-embedding-3-large",
    --  "top_k": 5, "min_score": 0.6}
    metadata JSONB DEFAULT '{}',
    -- {"doc_count": 145, "chunk_count": 2847, "total_size_mb": 487}
    last_sync TIMESTAMPTZ,
    sync_interval_hours INT DEFAULT 24,
    next_sync TIMESTAMPTZ,
    stats JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID,
    UNIQUE(tenant_id, name)
);
CREATE INDEX idx_indexes_azure ON indexes (tenant_id, is_active);
ALTER TABLE indexes ENABLE ROW LEVEL SECURITY;
ALTER TABLE indexes FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON indexes
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON indexes
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- Role-Index Permissions (replaces ARRAY_CONTAINS pattern)
-- ============================================================
CREATE TABLE role_index_permissions (
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    index_id UUID NOT NULL REFERENCES indexes(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    PRIMARY KEY (role_id, index_id)
);
ALTER TABLE role_index_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_index_permissions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON role_index_permissions
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON role_index_permissions
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- Conversations
-- ============================================================
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES users(id),
    title TEXT DEFAULT 'New Conversation',
    summary TEXT,
    channel TEXT DEFAULT 'web',
    index_ids TEXT[] DEFAULT '{}',
    message_count INT DEFAULT 0,
    tokens_used INT DEFAULT 0,
    cost_usd NUMERIC(10,4) DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    archived_at TIMESTAMPTZ
);
CREATE INDEX idx_conversations_user ON conversations (tenant_id, user_id, updated_at DESC);
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON conversations
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON conversations
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- User Preferences
-- ============================================================
CREATE TABLE user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    preferences JSONB NOT NULL DEFAULT '{}',
    -- {"theme": "dark", "language": "en", "notifications": {"email": true, "push": false},
    --  "display": {"compact_mode": false, "show_sources": true}}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, user_id)
);
ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_preferences FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON user_preferences
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON user_preferences
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- User Profiles (learned preferences)
-- ============================================================
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    profile_version INT DEFAULT 1,
    interests JSONB DEFAULT '{}',
    -- {"finance": 0.9, "hr": 0.3, "engineering": 0.1}
    expertise_level TEXT DEFAULT 'intermediate',
    communication_style TEXT DEFAULT 'formal',
    preferred_response_length TEXT DEFAULT 'medium',
    query_history JSONB DEFAULT '{}',
    learned_preferences JSONB DEFAULT '{}',
    learning_score NUMERIC(4,3) DEFAULT 0.0,
    next_model_update TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, user_id)
);
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON user_profiles
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON user_profiles
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- Consent Events (immutable audit trail)
-- ============================================================
CREATE TABLE consent_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES users(id),
    consent_type TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('granted', 'revoked', 'updated')),
    details JSONB DEFAULT '{}',
    ip_address INET,
    user_agent TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_consent_user ON consent_events (tenant_id, user_id, timestamp DESC);
ALTER TABLE consent_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON consent_events
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON consent_events
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- Feedback
-- ============================================================
CREATE TABLE feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES users(id),
    message_id UUID,
    conversation_id UUID REFERENCES conversations(id),
    rating SMALLINT CHECK (rating BETWEEN 1 AND 5),
    feedback_type TEXT,
    comment TEXT,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'reviewed', 'resolved')),
    context JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_feedback_message ON feedback (tenant_id, message_id);
CREATE INDEX idx_feedback_status ON feedback (tenant_id, status, created_at DESC);
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON feedback
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON feedback
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- Conversation Documents
-- ============================================================
CREATE TABLE conversation_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_type TEXT,
    size_bytes BIGINT,
    storage_path TEXT,             -- object storage path (S3/Blob/GCS)
    processing_status TEXT DEFAULT 'pending' CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed')),
    chunk_count INT DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_convdocs_conversation ON conversation_documents (tenant_id, conversation_id);
ALTER TABLE conversation_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_documents FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON conversation_documents
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON conversation_documents
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- Usage Daily (pre-aggregated analytics)
-- ============================================================
CREATE TABLE usage_daily (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    date DATE NOT NULL,
    service TEXT NOT NULL,
    dimension TEXT,
    metrics JSONB NOT NULL DEFAULT '{}',
    -- {"queries": 450, "tokens": 125000, "cost_usd": 4.50, "unique_users": 23}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, date, service, dimension)
);
CREATE INDEX idx_usage_daily_date ON usage_daily (tenant_id, date DESC, service);
ALTER TABLE usage_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_daily FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON usage_daily
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON usage_daily
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- Question Categories (pre-computed analytics)
-- ============================================================
CREATE TABLE question_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    date DATE NOT NULL,
    category TEXT NOT NULL,
    count INT DEFAULT 0,
    sample_queries JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, date, category)
);
ALTER TABLE question_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE question_categories FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON question_categories
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON question_categories
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- MCP Servers
-- ============================================================
CREATE TABLE mcp_servers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    display_name TEXT,
    description TEXT,
    server_type TEXT DEFAULT 'external',
    is_active BOOLEAN DEFAULT TRUE,
    connection_url TEXT NOT NULL,
    tools JSONB DEFAULT '[]',
    requires_auth BOOLEAN DEFAULT FALSE,
    auth_config JSONB DEFAULT '{}',
    retry_policy JSONB DEFAULT '{"max_retries": 3, "backoff_ms": 100}',
    rate_limits JSONB DEFAULT '{"requests_per_minute": 60}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, name)
);
ALTER TABLE mcp_servers ENABLE ROW LEVEL SECURITY;
ALTER TABLE mcp_servers FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON mcp_servers
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
CREATE POLICY tenant_isolation_insert ON mcp_servers
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);
```

## Appendix B: Query Pattern Comparison (Updated for Pure PostgreSQL)

| Operation                  | Current Cosmos DB                                 | Pure PostgreSQL                                           | Improvement                          |
| -------------------------- | ------------------------------------------------- | --------------------------------------------------------- | ------------------------------------ |
| Find user by email         | Cross-partition scan (`LOWER(c.email)`) ~10-50 RU | `WHERE email = $1` with unique index, <1ms                | 10-50x cheaper                       |
| Get user's roles           | 2 queries: user_roles + batch roles, ~15 RU       | `JOIN roles ON role_id`, single query, <1ms               | 5x cheaper                           |
| Check index permissions    | `ARRAY_CONTAINS` full scan, ~20 RU                | `JOIN role_index_permissions`, <1ms                       | 10x cheaper                          |
| List conversations         | Partition-scoped by user_id, ~5 RU                | `WHERE user_id = $1 ORDER BY updated_at DESC`, <1ms       | Comparable                           |
| Add chat message           | Partition-scoped write, ~10 RU                    | `INSERT INTO messages`, <1ms (partitioned table)          | Comparable                           |
| Load conversation messages | Partition-scoped read, ~5 RU                      | `WHERE conversation_id = $1 ORDER BY created_at`, <1ms    | Comparable                           |
| Glossary semantic search   | Load all embeddings to Python, numpy cosine sim   | `ORDER BY embedding <=> $1 LIMIT 5` (HNSW), <5ms          | 5x faster, zero memory               |
| Glossary full-text search  | `CONTAINS(LOWER(c.term))` string scan             | `search_vector @@ to_tsquery(...)` with GIN index, <1ms   | 100x faster                          |
| Write event                | 11 composite index updates per write, ~20 RU      | `INSERT INTO events` (partitioned), 5 index updates, <1ms | 2-3x cheaper per write               |
| User event timeline        | Cross-partition (unless same month), ~10-50 RU    | `WHERE user_id = $1 ORDER BY timestamp DESC`, <5ms        | Always fast (index + partition)      |
| Admin audit query          | Cross-partition, 11 composite indexes, ~100 RU    | `WHERE action = $1 AND timestamp BETWEEN ...`, <10ms      | 10x cheaper                          |
| Feedback stats             | Full container scan, Python aggregation           | `SELECT COUNT(*), type FROM ... GROUP BY type`, <5ms      | 100x cheaper                         |
| Tenant data deletion       | Iterate every container, every document           | `DELETE FROM ... WHERE tenant_id = $1` + FK cascade       | 100x simpler                         |
| Cross-tenant analytics     | Cross-partition on every container                | `SET ROLE platform_admin` then normal queries             | Operationally simpler                |
| Notification cleanup       | Per-item TTL (Cosmos DB automatic)                | `pg_cron` daily: `DELETE WHERE expires_at < NOW()`        | Equivalent (batch is more efficient) |

---

**Document Version**: 2.0
**Last Updated**: March 4, 2026
**Decision**: Pure PostgreSQL -- single database system, no Cosmos DB
**Phase 1 Timeline**: 8 weeks (unchanged from hybrid estimate)
**Total Lines**: 680+
