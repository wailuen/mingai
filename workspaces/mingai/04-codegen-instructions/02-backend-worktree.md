# 02 — Backend Implementation Guide

**Worktree**: backend
**Branch**: `feat/phase-1-backend`
**Framework**: FastAPI + Kailash SDK (DataFlow + Nexus + Kaizen)
**Port**: 8022

Read `01-context-loading.md` and `todos/active/00-master-index.md` before starting.

---

## Project Setup

```bash
mkdir -p src/backend
cd src/backend
python -m venv venv && source venv/bin/activate
pip install kailash kailash-dataflow kailash-nexus kailash-kaizen
pip install fastapi uvicorn[standard] alembic asyncpg redis python-jose pydantic-settings
pip install httpx pytest pytest-asyncio pytest-cov python-dotenv
cp .env.example .env  # fill all values before running
```

### Directory Structure

```
src/backend/
├── app/
│   ├── main.py                    # FastAPI app + Nexus registration
│   ├── core/
│   │   ├── config.py              # Settings from .env (pydantic-settings)
│   │   ├── database.py            # DataFlow connection + RLS middleware
│   │   ├── redis_client.py        # Redis connection pool
│   │   ├── middleware.py          # Tenant resolver, security headers, CORS
│   │   └── dependencies.py        # FastAPI deps: current_user, current_tenant, db
│   ├── modules/
│   │   ├── auth/                  # JWT validation, Auth0 JWKS (Phase 2)
│   │   ├── chat/                  # ChatOrchestrationService, SSE streaming
│   │   ├── profile/               # ProfileLearningService, WorkingMemoryService
│   │   ├── memory/                # MemoryNotesService, OrgContextService
│   │   ├── glossary/              # GlossaryExpander, glossary CRUD
│   │   ├── teams/                 # TeamWorkingMemoryService, team management
│   │   ├── users/                 # User management, invites
│   │   ├── tenants/               # Tenant management, provisioning
│   │   ├── agents/                # Agent registry, HAR (Phase 2)
│   │   ├── documents/             # Document indexing pipeline
│   │   ├── feedback/              # RAG quality feedback
│   │   ├── issues/                # Issue reporting (Phase 3)
│   │   └── platform/              # Platform admin, LLM profiles
│   └── api/
│       └── router.py              # Aggregate all module routers
├── alembic/
│   ├── env.py
│   └── versions/
│       ├── 001_initial_schema.py
│       ├── 002_rls_policies.py
│       ├── 003_profile_memory.py
│       ├── 004_teams_glossary.py
│       └── 005_har_phase0.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── .env                           # NOT committed
├── .env.example                   # Committed (no real values)
└── pyproject.toml
```

---

## Step 1: Environment Configuration (INFRA-001)

`app/core/config.py`:

```python
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Database
    database_url: str
    redis_url: str

    # Cloud
    cloud_provider: str  # aws | azure | gcp | local

    # AI Models — from .env, never hardcode
    primary_model: str
    intent_model: str
    embedding_model: str

    # Auth
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Auth0 (Phase 2)
    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_management_client_id: str = ""
    auth0_management_client_secret: str = ""

    # Platform
    frontend_url: str
    multi_tenant_enabled: bool = True

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## Step 2: Database + RLS Setup (DB-001 to DB-022)

### DataFlow Connection

`app/core/database.py`:

```python
from dataflow import DataFlow
from app.core.config import settings
import asyncpg

db = DataFlow(settings.database_url)

async def set_tenant_context(conn: asyncpg.Connection, tenant_id: str):
    """Set RLS context for every database transaction."""
    # Validate UUID format before use — never interpolate user-controlled values into SQL
    import uuid
    uuid.UUID(tenant_id)  # raises ValueError if not a valid UUID
    await conn.execute(
        "SELECT set_config('app.current_tenant_id', $1, true)", tenant_id
    )
```

### Alembic Migration 001: Initial Schema

Key tables in migration order (DB-001 through DB-022):

```sql
-- 001_initial_schema.py

-- Core platform
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    plan VARCHAR(50) NOT NULL DEFAULT 'professional',
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    primary_contact_email VARCHAR(255) NOT NULL,
    llm_profile_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    role VARCHAR(50) NOT NULL DEFAULT 'user',
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, email)
);

-- Conversations + Messages
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id UUID,
    title VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,  -- user | assistant
    content TEXT NOT NULL,
    tokens_used INTEGER,
    retrieval_confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Enable RLS on ALL tables
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

-- RLS policy pattern (apply to EVERY table)
CREATE POLICY tenant_isolation ON users
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
CREATE POLICY tenant_isolation ON conversations
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
CREATE POLICY tenant_isolation ON messages
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

### Migration 003: Profile + Memory Tables

```sql
-- 003_profile_memory.py

CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    technical_level VARCHAR(20),       -- beginner | intermediate | expert
    communication_style VARCHAR(20),   -- concise | detailed | formal | casual
    interests JSONB DEFAULT '[]',
    expertise_areas JSONB DEFAULT '[]',
    common_tasks JSONB DEFAULT '[]',
    profile_learning_enabled BOOLEAN DEFAULT true,
    org_context_enabled BOOLEAN DEFAULT true,
    share_manager_info BOOLEAN DEFAULT true,
    query_count INTEGER DEFAULT 0,
    last_learned_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, user_id)
);

CREATE TABLE memory_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,  -- NULL = global
    content TEXT NOT NULL,
    source VARCHAR(20) NOT NULL,  -- user_directed | auto_extracted
    created_at TIMESTAMPTZ DEFAULT NOW()
);
-- Memory notes: 200 char limit enforced in API layer (NOT just DB)
CREATE INDEX idx_memory_notes_user ON memory_notes(tenant_id, user_id, created_at DESC);

CREATE TABLE profile_learning_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
    extracted_attributes JSONB,
    conversations_analyzed INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE profile_learning_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON user_profiles
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
CREATE POLICY tenant_isolation ON memory_notes
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
CREATE POLICY tenant_isolation ON profile_learning_events
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

### Migration 004: Teams + Glossary

```sql
-- 004_teams_glossary.py

CREATE TABLE tenant_teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    source VARCHAR(20) NOT NULL DEFAULT 'manual',  -- manual | auth0_sync
    auth0_group_name VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);

CREATE TABLE team_memberships (
    team_id UUID NOT NULL REFERENCES tenant_teams(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source VARCHAR(20) NOT NULL DEFAULT 'manual',  -- manual | auth0_sync
    added_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (team_id, user_id)
);
CREATE INDEX idx_team_memberships_user ON team_memberships(user_id);

CREATE TABLE team_membership_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES tenant_teams(id),
    user_id UUID NOT NULL REFERENCES users(id),
    action VARCHAR(20) NOT NULL,  -- added | removed
    actor_id UUID REFERENCES users(id),
    source VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE glossary_terms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    term VARCHAR(200) NOT NULL,
    full_form VARCHAR(50) NOT NULL,  -- max 50 chars (security guard)
    aliases JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, term)
);
CREATE INDEX idx_glossary_tenant ON glossary_terms(tenant_id);

-- Enable RLS
ALTER TABLE tenant_teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_membership_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE glossary_terms ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON tenant_teams
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
CREATE POLICY tenant_isolation ON team_memberships
    USING (team_id IN (
        SELECT id FROM tenant_teams
        WHERE tenant_id = current_setting('app.current_tenant_id')::uuid
    ));
CREATE POLICY tenant_isolation ON team_membership_audit
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
CREATE POLICY tenant_isolation ON glossary_terms
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

---

## Step 3: Middleware (INFRA-051, INFRA-052, INFRA-053)

`app/core/middleware.py`:

```python
import os
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

def setup_middleware(app: FastAPI):
    # CORS — MUST come first (INFRA-051)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.environ["FRONTEND_URL"]],  # NEVER wildcard
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # Security headers (INFRA-052)
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # Tenant resolver
    @app.middleware("http")
    async def resolve_tenant(request: Request, call_next):
        # Extract tenant_id from JWT claims (set by JWT validation dependency)
        # This is set by get_current_tenant() dependency per-route
        return await call_next(request)
```

---

## Step 4: Auth (API-001 to API-010)

### Phase 1: JWT Validation

`app/modules/auth/jwt.py`:

```python
from jose import JWTError, jwt
from app.core.config import settings

def decode_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

### Phase 2: Auth0 JWKS Validation (INFRA-061)

```python
import httpx
from jose import jwk, jwt
from cachetools import TTLCache

# Cache JWKS keys for 1 hour (INFRA-061: Auth0 Management API token manager)
_jwks_cache = TTLCache(maxsize=1, ttl=3600)

async def get_auth0_public_key(kid: str) -> dict:
    if "jwks" not in _jwks_cache:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://{settings.auth0_domain}/.well-known/jwks.json"
            )
            _jwks_cache["jwks"] = resp.json()
    # Find key by kid
    for key in _jwks_cache["jwks"]["keys"]:
        if key["kid"] == kid:
            return key
    raise HTTPException(status_code=401, detail="Unknown key")
```

---

## Step 5: AI Services (Critical Path)

**IMPLEMENT IN THIS ORDER**:

1. `AI-056` ChatOrchestrationService — THE core RAG orchestrator
2. `AI-054` EmbeddingService
3. `AI-055` VectorSearchService
4. `AI-059` ConversationPersistenceService
5. `AI-001` ProfileLearningService
6. `AI-011` WorkingMemoryService

See `05-ai-services.md` for detailed implementation of each service.

All AI services live in `app/modules/` and are imported by `chat/orchestrator.py`.

---

## Step 6: API Endpoints

All endpoints follow this pattern:

```python
from fastapi import APIRouter, Depends, HTTPException
from app.core.dependencies import get_current_user, get_db

router = APIRouter(prefix="/api/v1", tags=["feature"])

@router.get("/resource/{id}")
async def get_resource(
    id: str,
    current_user: User = Depends(get_current_user),
    db = Depends(get_db)
):
    # get_db dependency sets RLS context (tenant_id) before returning connection
    ...
```

`app/core/dependencies.py`:

```python
from fastapi import Depends, HTTPException, Header
from app.core.database import db, set_tenant_context

async def get_db(current_user: User = Depends(get_current_user)):
    """Returns DB connection with RLS tenant context set."""
    async with db.connection() as conn:
        await set_tenant_context(conn, str(current_user.tenant_id))
        yield conn

async def get_current_user(authorization: str = Header(...)):
    """Decode JWT and return user. Works for Phase 1 (local JWT) and Phase 2 (Auth0)."""
    token = authorization.replace("Bearer ", "")
    payload = decode_jwt(token)
    return User(
        id=payload["sub"],
        tenant_id=payload["tenant_id"],
        roles=payload.get("roles", []),
        scope=payload.get("scope", "tenant"),
        plan=payload.get("plan", "professional")
    )

async def require_platform_admin(user: User = Depends(get_current_user)):
    if user.scope != "platform":
        raise HTTPException(status_code=403, detail="Platform admin required")
    return user

async def require_tenant_admin(user: User = Depends(get_current_user)):
    if "tenant_admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Tenant admin required")
    return user
```

### Error Response Format (Consistent Everywhere)

```python
from fastapi import Request
from fastapi.responses import JSONResponse
import uuid

async def global_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": str(exc) if settings.debug else "An error occurred",
            "request_id": request.state.request_id
        }
    )
```

---

## Step 7: Rate Limiting (INFRA-053)

```python
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter
import redis.asyncio as aioredis

# In main.py startup:
@app.on_event("startup")
async def startup():
    redis_conn = aioredis.from_url(settings.redis_url)
    await FastAPILimiter.init(redis_conn)

# On chat endpoint (strictest limit):
@router.post("/chat/stream")
@limiter.limit("30/minute")  # 30 queries/minute per user
async def chat_stream(...):
    ...

# On auth endpoints:
@router.post("/auth/local/login")
@limiter.limit("10/minute")  # Brute force protection
async def login(...):
    ...
```

---

## Step 8: Background Jobs (INFRA-031 to INFRA-040)

Use Kailash Core SDK workflows for async background processing:

```python
from kailash.workflow.builder import WorkflowBuilder
from kailash.runtime import AsyncLocalRuntime

# Tenant provisioning workflow
async def provision_tenant_async(tenant_id: str, config: dict):
    workflow = WorkflowBuilder()
    workflow.add_node("CreateDatabaseSchema", "create_schema", {
        "tenant_id": tenant_id,
        "tables": ["conversations", "messages", "user_profiles", ...]
    })
    workflow.add_node("CreateSearchIndex", "create_index", {
        "tenant_id": tenant_id,
        "cloud_provider": settings.cloud_provider
    })
    workflow.add_node("SeedDefaultTemplates", "seed_templates", {
        "tenant_id": tenant_id,
        "templates": ["hr_policy", "it_helpdesk", "procurement", "onboarding"]
    })
    # Connect: schema → index → templates
    workflow.connect("create_schema", "create_index", {})
    workflow.connect("create_index", "seed_templates", {})

    runtime = AsyncLocalRuntime()
    results, run_id = await runtime.execute_workflow_async(
        workflow.build(), inputs={"tenant_id": tenant_id}
    )
    return results
```

---

## Step 9: GDPR Endpoints (API-111 to API-115)

```python
@router.delete("/me/profile")
async def clear_profile_data(
    current_user: User = Depends(get_current_user),
    db = Depends(get_db),
    redis: Redis = Depends(get_redis)
):
    """
    GDPR erasure. MUST clear ALL 3 stores.
    CRITICAL: aihub2 bug — working memory NOT cleared there. Fix it here.
    """
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.id)

    # 1. PostgreSQL
    await db.execute("DELETE FROM user_profiles WHERE user_id = $1", user_id)
    await db.execute("DELETE FROM memory_notes WHERE user_id = $1", user_id)
    await db.execute("DELETE FROM profile_learning_events WHERE user_id = $1", user_id)

    # 2. Redis L2 cache
    await redis.delete(f"mingai:{tenant_id}:profile_learning:profile:{user_id}")
    await redis.delete(f"mingai:{tenant_id}:profile_learning:query_count:{user_id}")
    await redis.delete(f"mingai:{tenant_id}:org_context:{user_id}")

    # 3. Working memory (aihub2 GDPR bug — MUST fix here)
    pattern = f"mingai:{tenant_id}:working_memory:{user_id}:*"
    async for key in redis.scan_iter(pattern):
        await redis.delete(key)

    # 4. L1 cache (in-process ProfileLRUCache — call service method)
    await profile_learning_service.clear_l1_cache(user_id)

    return {"status": "erased"}
```

---

## Step 10: LLM Circuit Breaker (INFRA-055)

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import openai

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(openai.RateLimitError)
)
async def call_llm_with_circuit_breaker(
    messages: list,
    model: str,  # always from settings/tenant config
    max_tokens: int = 2048
) -> str:
    client = get_openai_client()  # configured from .env
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        stream=True
    )
    return response
```

---

## Step 11: Monitoring + Alerting (INFRA-058)

```python
# Structured logging (every request)
import structlog

logger = structlog.get_logger()

# Log format (JSON for log aggregation)
logger.info(
    "chat_request",
    tenant_id=str(current_user.tenant_id),
    user_id=str(current_user.id),
    tokens_used=tokens_used,
    retrieval_confidence=confidence,
    model=model_used,
    latency_ms=latency
)

# Metrics (Prometheus-compatible)
from prometheus_client import Counter, Histogram

chat_requests_total = Counter("chat_requests_total", "Total chat requests", ["tenant_id", "status"])
chat_latency = Histogram("chat_latency_seconds", "Chat request latency", ["tenant_id"])
```

---

## Running the Backend

```bash
# Development
uvicorn app.main:app --host 0.0.0.0 --port 8022 --reload

# Run migrations
alembic upgrade head

# Run tests
pytest tests/unit/ -v --cov=app --cov-report=html
pytest tests/integration/ -v  # requires running PostgreSQL + Redis
```

### main.py Pattern

```python
from fastapi import FastAPI
from app.core.middleware import setup_middleware
from app.api.router import router
from app.core.config import settings

app = FastAPI(title="mingai API", version="1.0.0")
setup_middleware(app)
app.include_router(router)

# Global error handler (API-122)
app.add_exception_handler(Exception, global_error_handler)
```
