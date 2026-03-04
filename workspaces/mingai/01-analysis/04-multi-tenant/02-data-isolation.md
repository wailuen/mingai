# Tenant Data Isolation Strategy

**Date**: March 4, 2026
**Status**: Architecture Design
**Scope**: Multi-tenant data isolation for all storage layers

---

## Overview

The current system has zero tenant awareness -- no `tenant_id` field in any data model, no tenant-aware partition keys, no cross-tenant query guards. This document designs the complete data isolation strategy.

---

## Strategy Selection: Hybrid Pool + Silo

**Recommended approach**: Shared database with logical isolation (Pool model) for standard tenants, with optional dedicated databases (Silo model) for enterprise tenants.

| Strategy                            | Cost   | Isolation | Complexity | When                      |
| ----------------------------------- | ------ | --------- | ---------- | ------------------------- |
| Pool (shared DB + tenant_id filter) | Low    | Logical   | Low        | Default for all tenants   |
| Silo (dedicated DB per tenant)      | High   | Physical  | Medium     | Enterprise tier only      |
| Hybrid                              | Medium | Mixed     | Medium     | Production recommendation |

---

## PostgreSQL: Adding tenant_id with Row-Level Security

### Table Changes

Every table gets a `tenant_id` column (VARCHAR, NOT NULL). Row-Level Security (RLS) policies enforce tenant isolation at the database engine level.

| Table             | tenant_id Column | RLS Policy                                     | Index Strategy                          | Rationale                                           |
| ----------------- | ---------------- | ---------------------------------------------- | --------------------------------------- | --------------------------------------------------- |
| users             | NOT NULL         | `tenant_id = current_setting('app.tenant_id')` | `(tenant_id, email)` unique             | Users queried by tenant                             |
| roles             | NOT NULL         | `tenant_id = current_setting('app.tenant_id')` | `(tenant_id, name)` unique              | Roles scoped to tenant                              |
| user_roles        | NOT NULL         | `tenant_id = current_setting('app.tenant_id')` | `(tenant_id, user_id, role_id)` unique  | Queried with tenant filter                          |
| group_roles       | NOT NULL         | `tenant_id = current_setting('app.tenant_id')` | `(tenant_id, group_id)`                 | Queried with tenant filter                          |
| knowledge_sources | NOT NULL         | `tenant_id = current_setting('app.tenant_id')` | `(tenant_id)`                           | Indexes per tenant                                  |
| conversations     | NOT NULL         | `tenant_id = current_setting('app.tenant_id')` | `(tenant_id, user_id, created_at DESC)` | Query by tenant + user                              |
| messages          | NOT NULL         | `tenant_id = current_setting('app.tenant_id')` | `(conversation_id, created_at)`         | FK to conversations; tenant_id for RLS              |
| events            | NOT NULL         | `tenant_id = current_setting('app.tenant_id')` | `(tenant_id, user_id, timestamp DESC)`  | Partitioned by month for query efficiency           |
| mcp_servers       | NOT NULL         | `tenant_id = current_setting('app.tenant_id')` | `(tenant_id)`                           | Some global (tenant_id='platform'), some per-tenant |
| notifications     | NOT NULL         | `tenant_id = current_setting('app.tenant_id')` | `(tenant_id, user_id, created_at DESC)` | Notifications per tenant                            |
| glossary_terms    | NOT NULL         | `tenant_id = current_setting('app.tenant_id')` | `(tenant_id, term)` unique              | Glossary per tenant                                 |
| feedback          | NOT NULL         | `tenant_id = current_setting('app.tenant_id')` | `(tenant_id, user_id)`                  | Feedback per tenant                                 |

### Row-Level Security (RLS) Setup

PostgreSQL RLS enforces tenant isolation at the database engine level. Unlike application-layer filtering, RLS cannot be bypassed by application code bugs.

```sql
-- 1. Set tenant context on each connection (done by middleware)
SET app.tenant_id = 'acme-corp';

-- 2. Enable RLS on each table
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

-- 3. Create tenant isolation policy (applied to all tenant-scoped tables)
CREATE POLICY tenant_isolation ON users
  USING (tenant_id = current_setting('app.tenant_id'))
  WITH CHECK (tenant_id = current_setting('app.tenant_id'));

-- 4. Platform admin bypass for cross-tenant operations
CREATE POLICY platform_admin_bypass ON users
  USING (current_setting('app.scope', true) = 'platform')
  WITH CHECK (current_setting('app.scope', true) = 'platform');
```

### Updated Data Models

```sql
-- users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
    email VARCHAR NOT NULL,
    full_name VARCHAR NOT NULL,
    external_auth_id VARCHAR,          -- SSO provider object ID
    is_active BOOLEAN DEFAULT TRUE,
    department VARCHAR,
    job_title VARCHAR,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (tenant_id, email)
);

-- conversations table
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES users(id),
    title VARCHAR,
    message_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- messages table
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id),
    tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
    user_id UUID REFERENCES users(id),
    role VARCHAR NOT NULL,              -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    sources JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- events table (partitioned by month for query efficiency)
CREATE TABLE events (
    id UUID DEFAULT gen_random_uuid(),
    tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
    user_id UUID REFERENCES users(id),
    event_type VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT now(),
    details JSONB,
    PRIMARY KEY (id, timestamp)
) PARTITION BY RANGE (timestamp);
```

### Composite Indexes

```sql
-- Optimized for common tenant-scoped query patterns
CREATE INDEX idx_users_tenant_email ON users (tenant_id, email);
CREATE INDEX idx_users_tenant_active ON users (tenant_id, is_active);
CREATE INDEX idx_conversations_tenant_user ON conversations (tenant_id, user_id, created_at DESC);
CREATE INDEX idx_messages_conversation ON messages (conversation_id, created_at);
CREATE INDEX idx_events_tenant_user_time ON events (tenant_id, user_id, timestamp DESC);
```

---

## Row-Level Security: Database-Level Enforcement

PostgreSQL RLS provides built-in row-level security, enforced at the database engine level. This is stronger than application-layer filtering because it cannot be bypassed by SQL injection, ORM misconfiguration, or developer error.

### Tenant-Aware Middleware Pattern

```python
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession

@asynccontextmanager
async def tenant_session(tenant_id: str, scope: str = "tenant") -> AsyncSession:
    """
    Create a database session with tenant context set via RLS.
    All queries through this session are automatically tenant-scoped
    by PostgreSQL RLS policies -- no application-layer filtering needed.
    """
    async with get_async_session() as session:
        # Set tenant context for RLS policies
        await session.execute(text("SET app.tenant_id = :tid"), {"tid": tenant_id})
        await session.execute(text("SET app.scope = :scope"), {"scope": scope})
        yield session


# Usage in services -- no tenant_id filter needed in queries
class ConversationService:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    async def list_user_conversations(self, user_id: str):
        async with tenant_session(self.tenant_id) as session:
            # RLS automatically filters to current tenant -- no WHERE tenant_id needed
            result = await session.execute(
                text("SELECT * FROM conversations WHERE user_id = :uid ORDER BY created_at DESC"),
                {"uid": user_id},
            )
            return result.fetchall()
```

### Defense in Depth

Multiple layers prevent cross-tenant access:

1. **JWT Validation**: tenant_id extracted from JWT, cannot be spoofed
2. **Middleware**: Sets `app.tenant_id` on every database connection before any query runs
3. **PostgreSQL RLS**: Database engine enforces tenant isolation -- cannot be bypassed by application code
4. **Application Layer**: ORM models include tenant_id for explicit scoping (belt-and-suspenders)
5. **Audit Logging**: All data access logged with tenant context
6. **Integration Tests**: Verify cross-tenant queries return empty

```python
# Test: Cross-tenant isolation via RLS
async def test_cross_tenant_isolation():
    """Verify tenant A cannot see tenant B data via PostgreSQL RLS."""
    # Create data as tenant A
    async with tenant_session("tenant-a") as session:
        await session.execute(text(
            "INSERT INTO conversations (id, tenant_id, user_id, title) "
            "VALUES (:id, :tid, :uid, :title)"
        ), {"id": "conv-1", "tid": "tenant-a", "uid": "user-1", "title": "test"})
        await session.commit()

    # Query as tenant B -- RLS must filter out tenant A data
    async with tenant_session("tenant-b") as session:
        result = await session.execute(text("SELECT * FROM conversations"))
        rows = result.fetchall()
        assert len(rows) == 0  # tenant B sees nothing from tenant A

    # Direct ID lookup as tenant B -- RLS must still filter
    async with tenant_session("tenant-b") as session:
        result = await session.execute(
            text("SELECT * FROM conversations WHERE id = :id"),
            {"id": "conv-1"},
        )
        assert result.fetchone() is None  # cannot access by ID either
```

---

## Tenant Routing

### Strategy: JWT Claim (Primary) + Subdomain (Secondary)

```python
async def extract_tenant_id(request: Request) -> str:
    """
    Extract tenant_id from request context.

    Priority:
    1. JWT token tenant_id claim (most secure, always available after auth)
    2. Subdomain mapping (acme.aihub.com -> tenant lookup)
    3. X-Tenant-ID header (for API key auth / service-to-service)
    """
    # 1. JWT claim (primary for authenticated requests)
    token = get_jwt_from_request(request)
    if token and token.get("tenant_id"):
        return token["tenant_id"]

    # 2. Subdomain mapping
    host = request.headers.get("host", "")
    subdomain = host.split(".")[0] if "." in host else None
    if subdomain and subdomain not in ("www", "api", "app"):
        tenant = await lookup_tenant_by_slug(subdomain)
        if tenant:
            return tenant.id

    # 3. API key header (for programmatic access)
    api_key = request.headers.get("X-API-Key")
    if api_key:
        tenant = await lookup_tenant_by_api_key(api_key)
        if tenant:
            return tenant.id

    raise HTTPException(401, "Tenant context required")
```

### Subdomain Routing

```
acme.aihub.com      -> tenant_id = "acme-tenant-uuid"
bigcorp.aihub.com   -> tenant_id = "bigcorp-tenant-uuid"
api.aihub.com       -> platform API (tenant from JWT/API key)
app.aihub.com       -> default tenant selection page
```

---

## Search Index Strategy

### Option A: Tenant-Prefixed Indexes (Recommended)

Each tenant gets their own search indexes with a tenant prefix:

```
tenant-acme-hr-policies
tenant-acme-finance-reports
tenant-bigcorp-hr-policies
tenant-bigcorp-engineering-docs
```

Advantages:

- Complete isolation at the search layer
- No risk of cross-tenant document leakage
- Per-tenant index scaling and configuration
- Clean deletion when tenant is removed

Disadvantages:

- More indexes to manage
- Higher Azure Search costs (per-index pricing at higher tiers)

### Index Provisioning

```python
async def provision_tenant_indexes(tenant_id: str, tenant_slug: str):
    """Create default search indexes for a new tenant."""
    search_client = get_search_admin_client()

    for index_template in DEFAULT_INDEX_TEMPLATES:
        index_name = f"tenant-{tenant_slug}-{index_template.name}"

        index_definition = SearchIndex(
            name=index_name,
            fields=[
                SimpleField(name="id", type=SearchFieldDataType.String, key=True),
                SimpleField(name="tenant_id", type=SearchFieldDataType.String,
                           filterable=True),
                SearchableField(name="content", type=SearchFieldDataType.String),
                SearchField(name="content_vector",
                           type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                           searchable=True,
                           vector_search_dimensions=3072,
                           vector_search_profile_name="default-profile"),
                SimpleField(name="source_url", type=SearchFieldDataType.String),
                SimpleField(name="title", type=SearchFieldDataType.String),
                SimpleField(name="created_at", type=SearchFieldDataType.DateTimeOffset),
            ],
            vector_search=VectorSearch(
                profiles=[VectorSearchProfile(name="default-profile", algorithm_configuration_name="hnsw-config")],
                algorithms=[HnswAlgorithmConfiguration(name="hnsw-config")],
            ),
        )

        search_client.create_index(index_definition)
```

---

## Redis Isolation

### Key Prefixing

All Redis keys include tenant_id as a prefix:

```python
class TenantRedisClient:
    """Redis client with automatic tenant key prefixing."""

    def __init__(self, tenant_id: str):
        self.prefix = f"aihub:{tenant_id}:"
        self.redis = get_redis_client()

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    async def get(self, key: str):
        return await self.redis.get(self._key(key))

    async def set(self, key: str, value: str, ex: int = None):
        await self.redis.set(self._key(key), value, ex=ex)

    async def delete(self, key: str):
        await self.redis.delete(self._key(key))


# Key patterns:
# aihub:tenant-uuid:perms:user-uuid          (permission cache)
# aihub:tenant-uuid:session:session-uuid      (session data)
# aihub:tenant-uuid:rate:user-uuid:chat       (rate limit counter)
# aihub:tenant-uuid:embed:hash                (embedding cache)
# aihub:tenant-uuid:intent:hash               (intent cache)

# Platform-level keys (no tenant prefix):
# aihub:platform:tenant-list                   (active tenant list)
# aihub:platform:provider-status               (provider health)
```

### Cache Invalidation

```python
# Tenant-scoped pub/sub channels
CHANNEL_PATTERN = "aihub:{tenant_id}:invalidation"

async def publish_cache_invalidation(tenant_id: str, key_pattern: str):
    """Broadcast cache invalidation to all API instances for a tenant."""
    channel = f"aihub:{tenant_id}:invalidation"
    await redis.publish(channel, json.dumps({
        "pattern": key_pattern,
        "timestamp": datetime.now(UTC).isoformat(),
    }))
```

---

## Migration Plan: Single-Tenant to Multi-Tenant

### Phase 1: Add tenant_id Columns (Alembic Migration, Zero Downtime)

```python
# Alembic migration: 001_add_tenant_id_columns.py
from alembic import op
import sqlalchemy as sa

TABLES = [
    "users", "roles", "user_roles", "group_roles",
    "knowledge_sources", "conversations", "messages", "events",
    "mcp_servers", "notifications", "glossary_terms", "feedback",
]

def upgrade():
    # Add tenant_id column with default to avoid breaking existing queries
    for table in TABLES:
        op.add_column(table, sa.Column(
            "tenant_id", sa.String(), nullable=False, server_default="default"
        ))
        op.create_index(f"idx_{table}_tenant_id", table, ["tenant_id"])

def downgrade():
    for table in TABLES:
        op.drop_index(f"idx_{table}_tenant_id", table)
        op.drop_column(table, "tenant_id")
```

### Phase 2: Enable Row-Level Security

```python
# Alembic migration: 002_enable_rls.py
from alembic import op

TABLES = [
    "users", "roles", "user_roles", "group_roles",
    "knowledge_sources", "conversations", "messages", "events",
    "mcp_servers", "notifications", "glossary_terms", "feedback",
]

def upgrade():
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
              USING (tenant_id = current_setting('app.tenant_id'))
              WITH CHECK (tenant_id = current_setting('app.tenant_id'))
        """)
        op.execute(f"""
            CREATE POLICY platform_admin_bypass ON {table}
              USING (current_setting('app.scope', true) = 'platform')
              WITH CHECK (current_setting('app.scope', true) = 'platform')
        """)

def downgrade():
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS platform_admin_bypass ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
```

### Phase 3: Update Application Code

```python
# Before (single-tenant, direct queries):
result = await session.execute(
    text("SELECT * FROM conversations WHERE user_id = :uid"),
    {"uid": user_id},
)

# After (multi-tenant, RLS handles isolation):
async with tenant_session(tenant_id) as session:
    # SET app.tenant_id already done by tenant_session context manager
    # RLS automatically filters -- same query, no tenant_id WHERE clause needed
    result = await session.execute(
        text("SELECT * FROM conversations WHERE user_id = :uid"),
        {"uid": user_id},
    )
```

### Phase 4: Verify Isolation

```python
# Automated verification suite
async def verify_tenant_isolation():
    """Run after migration to verify RLS enforces tenant isolation."""
    tenants = await list_all_tenants()

    for table in TABLES:
        for tenant in tenants:
            async with tenant_session(tenant.id) as session:
                result = await session.execute(text(f"SELECT * FROM {table}"))
                rows = result.fetchall()

                for row in rows:
                    assert row.tenant_id == tenant.id, \
                        f"LEAK: {table}/{row.id} " \
                        f"has tenant_id={row.tenant_id} " \
                        f"but was queried from tenant {tenant.id}"

    log.info("Tenant isolation verified: RLS enforces no cross-tenant data leaks")
```

---

## Enterprise Tier: Dedicated Databases

For enterprise tenants requiring physical isolation:

```python
class TenantDatabaseRouter:
    """Route database operations to the correct PostgreSQL database."""

    async def get_engine(self, tenant_id: str):
        tenant = await get_tenant(tenant_id)

        if tenant.features.get("dedicated_database"):
            # Enterprise: dedicated PostgreSQL database (separate RDS instance)
            return create_async_engine(tenant.db_config["database_url"])
        else:
            # Standard: shared database with RLS (tenant isolation via SET app.tenant_id)
            return get_shared_engine()
```

---

## Blob Storage Isolation

For document storage (PDFs, uploaded files):

```
Container structure:
  aihub-documents/
    tenant-acme-uuid/
      indexes/
        hr-policies/
          doc-001.pdf
          doc-002.docx
      uploads/
        user-uuid/
          uploaded-file.pdf
    tenant-bigcorp-uuid/
      indexes/
        ...
```

```python
class TenantBlobStorage:
    def __init__(self, tenant_id: str):
        self.prefix = f"{tenant_id}/"
        self.container = get_blob_container("aihub-documents")

    async def upload(self, path: str, data: bytes):
        blob_name = f"{self.prefix}{path}"
        await self.container.upload_blob(blob_name, data)

    async def download(self, path: str) -> bytes:
        blob_name = f"{self.prefix}{path}"
        blob = await self.container.download_blob(blob_name)
        return await blob.readall()

    async def list_blobs(self, prefix: str = ""):
        full_prefix = f"{self.prefix}{prefix}"
        return [b async for b in self.container.list_blobs(name_starts_with=full_prefix)]
```

---

## Summary: Isolation by Layer

| Layer         | Isolation Method                   | Enforcement        |
| ------------- | ---------------------------------- | ------------------ |
| API Gateway   | JWT tenant_id claim                | Middleware         |
| Application   | tenant_session() context manager   | Code pattern       |
| PostgreSQL    | Row-Level Security (RLS) policies  | Database engine    |
| Search Index  | Tenant-prefixed indexes            | Physical isolation |
| Redis         | Key prefixing (aihub:{tenant_id}:) | Client wrapper     |
| Blob/Object   | Tenant-prefixed paths              | Client wrapper     |
| Secrets Vault | Tenant-scoped secrets              | Vault policies     |

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
