# Backend Implementation Instructions (Phase 1)

**Worktree**: backend
**Branch**: `feat/phase-1-foundation`
**Source reference**: `/Users/wailuen/Development/aihub2` (read before writing)

---

## Pre-Implementation Checklist

Before writing a single line of code:

- [ ] Read `/Users/wailuen/Development/aihub2/app/core/database.py` — understand current DB connection
- [ ] Read `/Users/wailuen/Development/aihub2/app/modules/` — all 18 modules, especially `auth`, `chat`, `roles`
- [ ] Read `/Users/wailuen/Development/aihub2/scripts/init_system_roles.py` — 7 system roles, 9 functions
- [ ] Read `workspaces/mingai/02-plans/02-technical-migration-plan.md` — full migration plan
- [ ] Read `workspaces/mingai/01-analysis/01-research/12-database-architecture-analysis.md` — PostgreSQL decision
- [ ] Confirm `.env` exists with DATABASE_URL, REDIS_URL, CLOUD_PROVIDER, PRIMARY_MODEL, INTENT_MODEL

---

## Step 1: Project Setup

```bash
# Create backend project structure
mkdir -p src/backend/app/{core,modules,api}
mkdir -p src/backend/alembic/versions
mkdir -p src/backend/tests/{unit,integration,e2e}

# Initialize with Kailash SDK
pip install kailash kailash-nexus kailash-dataflow kailash-kaizen

# Database dependencies
pip install asyncpg sqlalchemy alembic pgvector psycopg2-binary

# FastAPI + tooling
pip install fastapi uvicorn pydantic-settings python-jose redis hiredis
```

**`src/backend/.env.example`** (copy and fill for local dev):

```
DATABASE_URL=postgresql://user:pass@localhost:5432/mingai
REDIS_URL=redis://localhost:6379/0
CLOUD_PROVIDER=self-hosted
PRIMARY_MODEL=                  # from .env — do not hardcode
INTENT_MODEL=                   # from .env — do not hardcode
EMBEDDING_MODEL=                # from .env — do not hardcode
MULTI_TENANT_ENABLED=false      # Start false; flip true after migration
JWT_SECRET_KEY=                 # generate: openssl rand -hex 32
```

---

## Step 2: Database Setup (Alembic Migrations)

Migration files must be created in order. Read `02-technical-migration-plan.md` Section 1 for exact column specs.

**`alembic/versions/001_add_tenant_id_columns.py`**:

- Add `tenant_id UUID NOT NULL DEFAULT 'default'` to all 19 migrated tables
- See migration plan Table in Section 1 for column + index specs per table

**`alembic/versions/002_create_tenant_tables.py`**:

- Create `tenants` table
- Create `tenant_configs` table (with full schema from migration plan Section 3)
- Create `user_feedback` table (with exact schema from migration plan Section 1 New Tables)

**`alembic/versions/003_backfill_default_tenant.py`**:

- INSERT default tenant row into `tenants`
- UPDATE all 19 tables: `SET tenant_id = 'default'::UUID WHERE tenant_id IS NULL`
- Batch 100 rows at a time

**`alembic/versions/004_add_rls_policies.py`**:

- For each tenant-scoped table: `ALTER TABLE ... ENABLE ROW LEVEL SECURITY; FORCE ROW LEVEL SECURITY;`
- Create `tenant_isolation` policy: `USING (tenant_id = current_setting('app.tenant_id')::UUID)`
- Create `platform_admin_bypass` policy: `USING (current_setting('app.scope', true) = 'platform')`
- See migration plan Section 1 "Row-Level Security (RLS) Setup" for exact SQL

**`alembic/versions/005_platform_rbac.py`**:

- Add `scope` column to `roles` table: existing rows get `scope = 'tenant'`
- Create `platform_members` table (no tenant_id — platform-scoped)
- Seed 4 platform roles: `platform_admin`, `platform_operator`, `platform_support`, `platform_security`
- See `workspaces/mingai/01-analysis/01-research/24-platform-rbac-specification.md` for full permission matrix

---

## Step 3: Core Infrastructure

### Tenant Middleware (`app/core/tenant_middleware.py`)

```python
# Pattern from migration plan Section 6 (strangler fig)
# If MULTI_TENANT_ENABLED=false: inject tenant_id="default", pass through
# If MULTI_TENANT_ENABLED=true: extract tenant_id from JWT, SET app.tenant_id on connection
```

Key behaviors:

- Extract `tenant_id` from JWT `tenant_id` claim
- Extract `scope` from JWT `scope` claim (`tenant` | `platform`)
- Execute `SET app.tenant_id = '{tenant_id}'` and `SET app.scope = '{scope}'` on each DB connection
- 401 if tenant not found or suspended
- Inject into `request.state` for downstream use

### JWT v2 (`app/core/jwt.py`)

Target token structure (from migration plan Section 2):

```json
{
  "sub": "user_id",
  "tenant_id": "uuid",
  "scope": "tenant",
  "plan": "professional",
  "roles": ["admin"],
  "token_version": 2
}
```

Dual-accept window: accept both v1 (no tenant_id) and v2 tokens for 30 days.
v1 tokens: treat as `tenant_id="default"`, `scope="tenant"`, `plan="professional"`.

---

## Step 4: Kailash DataFlow Models

Use DataFlow for all PostgreSQL models. Never write raw SQL outside of migration scripts.

```python
# src/backend/app/core/models.py
from kailash.dataflow import DataFlow
from dataclasses import field

db = DataFlow(os.environ["DATABASE_URL"])

@db.model
class Tenant:
    id: str = field(primary_key=True)
    name: str
    plan: str  # starter | professional | enterprise
    status: str  # Draft | Active | Suspended | ScheduledDeletion | Deleted
    created_at: ...  # auto-managed

@db.model
class TenantConfig:
    id: str = field(primary_key=True)
    tenant_id: str
    config_type: str
    provider: str
    primary_model: str  # stored reference, not hardcoded — from tenant's LLM profile
    ...
```

---

## Step 5: Tenant Provisioning Workflow (Kailash Core SDK)

```python
from kailash.workflow.builder import WorkflowBuilder
from kailash.runtime import AsyncLocalRuntime

def build_provisioning_workflow():
    workflow = WorkflowBuilder()
    # Steps in order:
    # 1. CreateTenantRecord — DataFlow CreateTenant node
    # 2. SeedDefaultRoles — DataFlow CreateRole × 7 system roles
    # 3. ApplyRLSPolicies — execute Alembic tenant-scoped RLS
    # 4. CreateSearchIndex — CLOUD_PROVIDER-specific node
    # 5. CreateObjectStoreBucket — CLOUD_PROVIDER-specific node
    # 6. RegisterRedisNamespace — Redis namespace init
    # 7. SendInviteEmail — SendGrid node
    # Rollback on any step failure: compensating transactions per step
    return workflow

runtime = AsyncLocalRuntime()
results, run_id = await runtime.execute_workflow_async(
    build_provisioning_workflow().build(),
    inputs={"tenant_id": tenant_id, "admin_email": email}
)
```

---

## Step 6: Glossary Module (`app/modules/glossary/`)

Full spec: `workspaces/mingai/01-analysis/01-research/23-glossary-management-architecture.md`

Key implementation points:

- Storage: PostgreSQL `glossary_terms` table (already in migration plan, tenant_id RLS)
- pgvector HNSW index on `embedding` column for similarity search
- Redis cache: `mingai:{tenant_id}:glossary:active` (60-second TTL)
- RAG injection: **system message only** (never user message — prompt injection prevention)
- Injection limit: **max 20 terms, max 200 chars/definition, 800-token hard ceiling** (canonical spec)
- Enrichment: cosine similarity between query embedding and term embeddings (NOT keyword match)

---

## Step 7: Response Feedback Module (`app/modules/feedback/`)

Schema: exactly as in `user_feedback` table in migration plan Section 1.

- `rating SMALLINT NOT NULL CHECK (rating IN (1, -1))` — 1=thumbs up, -1=thumbs down
- Tenant admin review API: flag messages with 3+ negative ratings
- Label in UI: always "retrieval confidence" (canonical spec)

---

## Step 8: Platform Admin API (Nexus)

```python
from kailash.nexus import Nexus

app = Nexus()
# Register admin routes: tenant CRUD, LLM profile management, quota
# All routes under /admin/* must check scope=platform + platform role
app.register(tenant_provisioning_workflow)
app.start()
```

---

## Testing Requirements

**Tier 1 (unit)**: Mock external services. Test business logic isolation.
**Tier 2 (integration)**: Real PostgreSQL in Docker. Real Redis. NO MOCKING.
**Tier 3 (E2E)**: Full stack. Use Playwright for frontend-triggered backend tests.

RLS isolation test (mandatory before phase completion):

```python
def test_cross_tenant_isolation():
    # Create tenant A data
    # Query as tenant B
    # Assert zero rows returned
    # This test MUST pass before Phase 1 ships
```

---

## Docker Compose for Local Dev

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: mingai
      POSTGRES_USER: mingai
      POSTGRES_PASSWORD: local_dev_only
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

Run migrations: `alembic upgrade head`
