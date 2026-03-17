# CLAUDE.md — mingai Codegen Instructions

Preloaded instructions for AI codegen agents working on the mingai platform.
Read this before writing any backend or frontend code.

Last validated: 2026-03-17.

---

## What Is mingai

mingai is a multi-tenant enterprise AI assistant platform. End users query a RAG-backed AI through a chat interface. Tenant admins manage their workspace — users, documents, glossary, agents, issues, analytics. Platform admins operate the entire platform — tenants, LLM profiles, dashboards, registries.

---

## Architecture Overview

### Stack

| Layer            | Technology                                                        |
| ---------------- | ----------------------------------------------------------------- |
| Backend          | FastAPI + SQLAlchemy (async) + PostgreSQL + Redis                 |
| Frontend         | Next.js 14 (App Router) + TypeScript + Tailwind CSS + React Query |
| Auth             | JWT v2 (HS256 local) — Auth0 JWKS integration prepared            |
| Multi-tenancy    | PostgreSQL Row-Level Security (RLS)                               |
| Async processing | Redis Streams (issue triage), Redis Pub/Sub (notifications SSE)   |
| AI               | Azure OpenAI via `AsyncAzureOpenAI`, pgvector for embeddings      |

### Ports

- **Backend API**: `8022`
- **Frontend**: `3022`
- **API prefix**: `/api/v1/` (all backend endpoints)

---

## Backend

### Root Structure

```
src/backend/
  app/
    main.py                   # FastAPI app, startup lifespan, router registration
    api/
      router.py               # Aggregates all module routers under /api/v1/
    core/
      config.py               # pydantic_settings.BaseSettings — all values from .env
      database.py             # get_set_tenant_sql(), validate_tenant_id(), RLS helpers
      dependencies.py         # get_current_user, require_tenant_admin, require_platform_admin
      session.py              # Async SQLAlchemy engine + get_async_session()
      redis_client.py         # build_redis_key(), get_redis(), close_redis()
      cache.py                # CacheService, @cached decorator, invalidate_cache()
      middleware.py           # CORS, security headers, request ID injection
      health.py               # build_health_response()
      logging.py              # structlog JSON setup
      bootstrap.py            # First-run schema/seed logic
      seeds.py                # Seed data helpers
      schema.py               # Shared Pydantic base schemas
      storage.py              # Cloud-agnostic presigned URL (aws/azure/gcp/local)
    modules/
      auth/
        jwt.py                # decode_jwt_token(), decode_jwt_token_v1_compat()
        routes.py             # /auth/local/login, /auth/token/refresh, /auth/logout, /auth/current
      chat/
        orchestrator.py       # ChatOrchestrationService — 8-stage RAG pipeline
        routes.py             # POST /chat/stream, /chat/feedback; GET/DELETE /conversations/...
        embedding.py          # EmbeddingService — reads EMBEDDING_MODEL from env
        vector_search.py      # VectorSearchService — tenant-scoped pgvector search
        persistence.py        # ConversationPersistenceService
        prompt_builder.py     # SystemPromptBuilder — 6-layer prompt assembly
      issues/
        routes.py             # Full CRUD + admin/platform queues + GitHub webhook
        blur_service.py       # ScreenshotBlurService — PIL Gaussian blur
        stream.py             # Redis Stream producer (XADD) — issue_reports:incoming
        worker.py             # Redis Stream consumer (XREADGROUP) — triage loop
        triage_agent.py       # LLM-based issue classifier
      memory/
        working_memory.py     # WorkingMemoryService — per-user/per-agent Redis context
        team_working_memory.py# TeamWorkingMemoryService — anonymized team context
        org_context.py        # OrgContextService — JWT claims extraction
        notes.py              # Memory notes model (200-char max)
        routes.py             # /memory/notes, GDPR export/clear
      notifications/
        publisher.py          # publish_notification() — Redis Pub/Sub producer
        routes.py             # GET /notifications/stream — SSE StreamingResponse
      glossary/
        expander.py           # GlossaryExpander — query expansion + injection protection
        routes.py             # CRUD + bulk import + export + miss analytics
      documents/
        sharepoint.py         # SharePoint connect/test/sync/status
        google_drive.py       # Google Drive connect/test/sync/status
        indexing.py           # DocumentIndexingPipeline — PDF/DOCX/PPTX/TXT → pgvector
      har/
        crypto.py             # Ed25519 keypair generation, Fernet private-key encryption
        signing.py            # create_signed_event(), verify_event_signature(), nonce check
        state_machine.py      # Transaction state machine (DRAFT→...→COMPLETED)
        routes.py             # /har/transactions CRUD + transition + approve/reject
        trust.py              # compute_trust_score(agent_id, tenant_id, db)
        health_monitor.py     # AgentHealthMonitor — asyncio background hourly task
      admin/
        workspace.py          # GET/PATCH /admin/workspace; GET/POST /admin/sso; POST /admin/sso/test; GET/PATCH /admin/sso/group-sync/config
        analytics.py          # Satisfaction dashboard (TA-026), per-agent analytics (TA-027/028), glossary impact (TA-029), engagement v2 (TA-030)
        onboarding.py         # Onboarding wizard persistence (TA-031) — tenant_configs JSONB storage
        bulk_user_actions.py  # Bulk suspend/role_change/kb_assignment (TA-032) — self-lockout protection
        kb_sources.py         # KB source health, document search, source detach (TA-034)
      users/routes.py         # invite, bulk invite, list, GDPR erase
      teams/routes.py         # CRUD, members, working memory, audit log
      agents/routes.py        # list, create, update, status toggle, deploy from template, test run, upgrade check
      agents/templates.py     # Agent template CRUD (platform admin)
      tenants/routes.py       # Tenant CRUD, health, quota, LLM profiles, token budget
      platform/routes.py      # Platform admin dashboard, audit log
      registry/routes.py      # HAR agent registry — public discovery + CRUD
      llm_profiles/routes.py  # LLM profile slot→deployment mapping (platform admin)
      profile/learning.py     # ProfileLearningService — async learning from queries
      feedback/routes.py      # User feedback collection
      glossary/routes.py      # CRUD + bulk import + export + miss analytics + version history (TA-012) + rollback (TA-013)
  tests/
    unit/                     # Tier 1 — mocked, < 1s each. 2087+ tests passing.
    integration/              # Tier 2 — real PostgreSQL + Redis (Docker required)
    e2e/                      # Tier 3 — Playwright, full stack
    fixtures/                 # Shared test data (llm_providers.json etc.)
    conftest.py               # Root conftest — session-scoped TestClient
  alembic/
    versions/                 # v001–v029 migrations (schema, RLS, HAR, cache, agents, KB access control, etc.)
  docker-compose.yml          # PostgreSQL + Redis for local dev/testing
  pyproject.toml
```

### Database Migrations

```bash
cd src/backend
alembic upgrade head                              # apply all
alembic revision --autogenerate -m "description" # generate new
```

31 migrations applied (v001–v029 + **init**).

---

## Backend Patterns

### 1. RLS Context — Always Set Before Querying Tenant Tables

```python
from app.core.database import get_set_tenant_sql
from sqlalchemy import text

# get_set_tenant_sql returns (sql_str, params_dict) — NOT a string
sql, params = get_set_tenant_sql(tenant_id)
await db.execute(text(sql), params)
```

Never pass `get_set_tenant_sql(...)` directly to `text()` — it returns a tuple.

### 2. Redis Key Construction — Always Use build_redis_key

```python
from app.core.redis_client import build_redis_key

# Pattern: mingai:{tenant_id}:{key_type}:{...parts}
key = build_redis_key(tenant_id, "working_memory", user_id, agent_id)
channel = build_redis_key(tenant_id, "notifications", user_id)
```

`build_redis_key` raises `ValueError` if any segment contains a colon. Never construct Redis keys with f-strings.

Key namespace reference:

```
mingai:{tenant_id}:working_memory:{user_id}:{agent_id}  # per-user working memory
mingai:{tenant_id}:team_memory:{team_id}                 # team working memory
mingai:{tenant_id}:glossary_terms                         # glossary cache
mingai:{tenant_id}:embedding_cache:{sha256_hash[:16]}    # embedding cache
mingai:{tenant_id}:notifications:{user_id}               # SSE pub/sub channel
{tenant_id}:nonce:{nonce}                                # HAR replay protection
```

### 3. Dynamic PATCH — Column Allowlist Required

```python
_WORKSPACE_UPDATE_ALLOWLIST = {"name", "timezone", "locale", "notification_preferences"}

invalid = set(updates) - _WORKSPACE_UPDATE_ALLOWLIST
if invalid:
    raise ValueError(f"Invalid fields: {invalid}")

await db.execute(
    text("UPDATE workspace SET col = :col WHERE id = :id"),
    {"col": value, "id": record_id},
)
```

Never use f-strings to inject column names from user input.

### 4. asyncpg JSON Parameters — Always Use CAST

```sql
-- CORRECT (asyncpg)
INSERT INTO t (col) VALUES (CAST(:val AS jsonb))

-- WRONG (psycopg2 syntax, breaks asyncpg)
INSERT INTO t (col) VALUES (:val::jsonb)
```

### 5. asyncpg TIMESTAMPTZ — Pass datetime Objects, Not Strings

```python
# CORRECT
from datetime import datetime, timezone
created_at = datetime.now(timezone.utc)  # datetime object

# WRONG — raises DataError
created_at = datetime.now(timezone.utc).isoformat()  # string
```

### 6. DB Helpers Are Module-Level Async Functions

Every route module defines DB operations as standalone async functions at module level, not class methods. This makes them patchable in unit tests.

```python
# In routes.py
async def create_issue_db(tenant_id, user_id, title, ..., db) -> dict:
    ...

@router.post("/issues")
async def create_issue(request, current_user=Depends(...), session=Depends(...)):
    result = await create_issue_db(..., db=session)
    return result

# In unit tests
with patch("app.modules.issues.routes.create_issue_db", new_callable=AsyncMock) as mock:
    mock.return_value = {...}
```

### 7. Route Registration Order — Specific Before Parameterized

```python
# CORRECT — specific sub-paths registered first
@router.patch("/issues/{id}/status")   # registered first
@router.post("/issues/{id}/events")    # registered first
@router.get("/issues/{id}")            # parameterized last

# Also: /users/me before /users/{id}, /glossary/import before /glossary/{id}
```

### 8. Screenshot Blur Gate — Enforced in Route Handler

```python
# In issues/routes.py — NOT in the DB helper
if request.screenshot_url is not None and not request.blur_acknowledged:
    raise HTTPException(status_code=422, detail="blur_acknowledged must be true...")
```

Do not move this check into `create_issue_db`.

### 9. GitHub Webhook — Fail-Closed

```python
# If GITHUB_WEBHOOK_SECRET is not set, return 503 immediately
# Never process an unverified webhook payload
```

### 10. Notification SSE Pattern

```python
# notifications/routes.py
async def event_generator(pubsub):
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
            if msg:
                yield f"data: {msg['data']}\n\n"
            else:
                yield ": keepalive\n\n"  # prevent proxy timeouts
    finally:
        await pubsub.unsubscribe()  # ALWAYS release in finally

return StreamingResponse(event_generator(pubsub), media_type="text/event-stream")
```

### 11. HAR Cryptography

```python
from app.modules.har.crypto import generate_agent_keypair, sign_payload, verify_signature

public_key_b64, private_key_enc_b64 = generate_agent_keypair()
signature_b64 = sign_payload(private_key_enc_b64, canonical_bytes)
ok = verify_signature(public_key_b64, canonical_bytes, signature_b64)
# verify_signature never raises — returns False on any error
```

Ed25519 private keys are Fernet-encrypted using PBKDF2HMAC derived from `JWT_SECRET_KEY` (200k iterations, SHA256, salt `b"mingai-har-v1"`). Never store raw private keys.

HAR signed event canonical payload uses `json.dumps(dict, sort_keys=True)` with `.isoformat()` for timestamps (T-separator). `str(datetime)` produces space-separated format — do not use it in signing.

### 12. Trust Score Formula

```
score = max(0, min(100, kyb_pts + min(30, completed_count) - min(30, disputed_count × 10)))
kyb_pts: {0→0, 1→15, 2→30, 3→40}
```

`compute_trust_score()` does NOT commit — the caller must `await db.commit()`.

### 13. AgentHealthMonitor — Never Await Directly

```python
# In main.py startup — CORRECT
asyncio.create_task(health_monitor.start())

# WRONG — blocks forever
await health_monitor.start()
```

### 14. Team Working Memory — Never Store user_id

`TeamWorkingMemoryService` stores only anonymized strings: `"a team member asked: <truncated>"`. Writing `user_id` to team memory is a GDPR violation.

---

## Auth Architecture

### JWT v2 Payload

```json
{
  "sub": "<user_id>",
  "tenant_id": "<uuid>",
  "roles": ["end_user"],
  "scope": "tenant",
  "plan": "professional",
  "email": "user@example.com",
  "exp": 1234567890,
  "iat": 1234567890,
  "token_version": 2
}
```

### Role Enforcement Dependencies

```python
current_user = Depends(get_current_user)         # any authenticated user
current_user = Depends(require_tenant_admin)     # roles includes "tenant_admin"
current_user = Depends(require_platform_admin)   # scope == "platform"
```

| Role             | Scope      | Access                                                     |
| ---------------- | ---------- | ---------------------------------------------------------- |
| `end_user`       | `tenant`   | Chat, memory, own issues, own profile                      |
| `tenant_admin`   | `tenant`   | Above + user mgmt, glossary, workspace, agents, all issues |
| `platform_admin` | `platform` | Above + tenant mgmt, LLM profiles, platform analytics      |

---

## Backend Test Patterns

### Tier 1 — Unit Tests

Location: `src/backend/tests/unit/`
Run: `cd src/backend && python -m pytest tests/unit/ -q`

Rules:

- Mock ALL external dependencies (DB, Redis, LLM APIs) with `AsyncMock` / `MagicMock`
- Use `patch("app.modules.<module>.routes.<function>", new_callable=AsyncMock)`
- JWT tokens: 64-char test secret (`"a" * 64`), never real env vars
- Use `TestClient(app, raise_server_exceptions=False)` for route tests
- Patch env vars via `patch.dict(os.environ, {...})` in a fixture

Standard fixture:

```python
TEST_JWT_SECRET = "a" * 64
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_USER_ID = "user-001"

@pytest.fixture
def env_vars():
    with patch.dict(os.environ, {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": "HS256",
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
    }):
        yield

@pytest.fixture
def client(env_vars):
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)
```

For `ChatOrchestrationService._stream_llm` — always intercept with `autouse=True` monkeypatch fixture. It makes real API calls without interception.

### Tier 2 — Integration Tests

Location: `src/backend/tests/integration/`
Requires: `cd src/backend && docker-compose up -d`

- NO MOCKING — real PostgreSQL and real Redis
- Session-scoped `TestClient` shared across tests to avoid event loop binding errors
- `asyncio.run()` for DB fixture setup, function-scoped DB engines

### Tier 3 — E2E Tests

Location: `src/backend/tests/e2e/`
Requires: Full running stack. Uses Playwright.

---

## Backend Known Gotchas

1. `get_set_tenant_sql()` returns a tuple — never pass to `text()` directly.
2. `_stream_llm` makes real API calls — `autouse=True` monkeypatch required in test_orchestrator.py.
3. Route registration order matters — specific paths before parameterized in every module.
4. Module-level SQLAlchemy engine in `session.py` binds to the first event loop — integration tests need session-scoped TestClient.
5. `EmbeddingService.__init__` reads env vars at instantiation — raises `ValueError` if absent.
6. `GlossaryExpander(db=None)` is valid for unit tests — returns [] from `_get_terms()`.
7. Issues router must be registered BEFORE chat router — prevents wildcard path shadowing.
8. `on_event` in main.py is deprecated — migrate to `lifespan` when refactoring startup.
9. SSE connections hold Redis subscriptions open — always `await pubsub.unsubscribe()` in `finally`.
10. `ensure_stream_group` must run before worker's XREADGROUP loop.
11. `GITHUB_WEBHOOK_SECRET` unset → 503, not 401 — fail-closed.
12. `_SAFE_SEGMENT_RE` validates all Redis key segments — colons raise `ValueError`.
13. asyncpg event loop binding in integration tests — multiple `asyncio.run()` calls require resetting `app.core.redis_client._redis_pool = None`.
14. `generate_bootstrap_sql()` returns `list[tuple[text_obj, dict]]` — call `await session.execute(sql, params)`.
15. HAR `verify_event_signature()` uses `.isoformat()` not `str()` for datetime — they produce different formats.

---

## Environment Variables

| Variable                         | Required    | Description                                   |
| -------------------------------- | ----------- | --------------------------------------------- |
| `DATABASE_URL`                   | Yes         | `postgresql+asyncpg://user:pass@host:port/db` |
| `REDIS_URL`                      | Yes         | `redis://host:port/db`                        |
| `CLOUD_PROVIDER`                 | Yes         | `aws` / `azure` / `gcp` / `local`             |
| `PRIMARY_MODEL`                  | Yes         | LLM deployment name for chat responses        |
| `INTENT_MODEL`                   | Yes         | LLM deployment name for intent routing        |
| `EMBEDDING_MODEL`                | Yes         | Embedding model name                          |
| `JWT_SECRET_KEY`                 | Yes         | Min 32 chars                                  |
| `JWT_ALGORITHM`                  | No          | Default `HS256`                               |
| `FRONTEND_URL`                   | Yes         | Must not be `*` — enforced in config.py       |
| `AZURE_OPENAI_API_KEY`           | If azure    | mingai-owned eastasia resource                |
| `AZURE_PLATFORM_OPENAI_API_KEY`  | If azure    | Shared platform eastus2 resource              |
| `AZURE_PLATFORM_OPENAI_ENDPOINT` | If azure    | eastus2 endpoint                              |
| `DEBUG`                          | No          | `true` exposes exception details in responses |
| `GITHUB_WEBHOOK_SECRET`          | If webhooks | HMAC-SHA256 secret; 503 returned if unset     |

### Azure OpenAI Deployments (provisioned)

| Deployment               | Model                  | Resource                    | Use               |
| ------------------------ | ---------------------- | --------------------------- | ----------------- |
| `agentic-gpt5`           | gpt-5                  | agentic-openai01 (eastasia) | mingai primary    |
| `agentic-router`         | gpt-5-mini             | agentic-openai-eastus2      | Intent routing    |
| `agentic-worker`         | gpt-5.2                | agentic-openai-eastus2      | Primary worker    |
| `agentic-vision`         | gpt-5.2-chat           | agentic-openai-eastus2      | Vision/multimodal |
| `text-embedding-3-small` | text-embedding-3-small | agentic-openai-eastus2      | Embeddings        |

---

## Security Invariants

Never violate these:

1. All SQL uses `text()` with named params. No f-strings with user data.
2. Dynamic column selection (PATCH) uses a module-level allowlist set.
3. All secrets from `os.environ`. No hardcoded keys, passwords, or model names.
4. `screenshot_url` rejected unless `blur_acknowledged=True` — blur gate in route handler.
5. `user_id` never stored in team working memory.
6. Application DB user must be `NOSUPERUSER` (superusers bypass PostgreSQL RLS).
7. `FRONTEND_URL` must not be `*` — enforced in config.py validator.
8. Glossary definitions sanitized against injection patterns before storage.
9. Error responses never leak internal config in production (`DEBUG=false`).
10. Logs never record passwords, tokens, or full API keys.
11. GitHub webhook payload rejected (503) when `GITHUB_WEBHOOK_SECRET` is unset.
12. Redis key segments validated against `_SAFE_SEGMENT_RE` — colons raise `ValueError`.
13. Ed25519 private keys Fernet-encrypted at rest — never store raw private keys.
14. `verify_signature()` never raises — returns `False` on any error.
15. HAR transaction routes require `require_tenant_admin` — never expose to end users.
16. Nonce replay protection: Redis SETNX with TTL=600. Duplicate nonce → reject.
17. `compute_trust_score()` does not commit — caller must commit.
18. Bulk user actions: acting user cannot suspend or demote themselves (self-lockout prevention).
19. LIKE search params must escape `\`, `%`, `_` (in that order) before wrapping in `%...%`.
20. Glossary rollback: term update + audit_log INSERT must commit in the same transaction (`commit=False` pattern).
21. KB assignment: verify `kb_id` belongs to calling tenant before upserting `kb_access_control`.
22. `update_glossary_term_db` must operate on a copy of `updates` dict (never mutate caller's dict).
23. `audit_log.actor_id` must always be set to `current_user.id` (the acting user's ID), never `tenant_id`.

---

## Frontend

### Root Structure

```
src/web/
  app/
    layout.tsx                    # Root layout — fonts, QueryClientProvider, dark theme
    globals.css                   # CSS custom properties — all Obsidian Intelligence tokens
    page.tsx                      # Root redirect
    login/page.tsx                # Login page
    (admin)/admin/                # Tenant admin routes (scope=tenant, role=tenant_admin)
      page.tsx                    # Dashboard
      agents/page.tsx             # Agent library (FE-035)
      agents/studio/              # Agent Studio — NOT STARTED (FE-036, product-gated)
      analytics/page.tsx          # Analytics dashboard
      sync/page.tsx               # Document stores + sync health
      teams/page.tsx              # Team management
    (platform)/platform/          # Platform admin routes (scope=platform)
      page.tsx                    # Platform dashboard
      agent-templates/page.tsx    # Agent template management
      alerts/page.tsx             # Alert summary (FE-040)
      analytics/page.tsx          # Platform analytics
      audit-log/page.tsx          # Platform audit log
      elements/page.tsx           # Provisioning progress (FE-041)
      issues/page.tsx             # Engineering issue queue
      llm-profiles/page.tsx       # LLM profile management
      registry/page.tsx           # Agent registry
      tenants/page.tsx            # Tenant management
      tool-catalog/page.tsx       # Tool catalog
    settings/                     # Tenant admin settings tabs
      agent-templates/page.tsx
      analytics-platform/page.tsx
      cost-analytics/page.tsx
      dashboard/page.tsx
      engineering-issues/page.tsx
      glossary/page.tsx
      issue-queue/page.tsx
      knowledge-base/page.tsx
      llm-profiles/page.tsx
      memory/page.tsx
      privacy/page.tsx
      sso/page.tsx
      tenants/page.tsx
      tool-catalog/page.tsx
      users/page.tsx
      workspace/page.tsx
    chat/page.tsx                  # End-user chat (two-state layout)
    discover/page.tsx              # Agent registry discovery
    my-reports/page.tsx            # End-user issue reports
    onboarding/page.tsx            # Onboarding wizard
  components/
    chat/                          # Chat components (message list, input, citations)
    issue-reporter/                # Issue report components
    layout/                        # AppShell, Sidebar, Topbar
    notifications/                 # Notification bell + SSE hook
    privacy/                       # Privacy/memory management
    shared/                        # ErrorBoundary, LoadingState, SafeHTML
  lib/
    api.ts                         # apiClient — Bearer token injection, error handling
    auth.ts                        # getStoredToken(), decodeToken(), isTokenExpired(), isTenantAdmin(), isPlatformAdmin(), hasRole()
    chartColors.ts                 # CHART_COLORS.accent, CHART_COLORS.alert etc.
    react-query.tsx                # QueryClientProvider
    sanitize.ts                    # DOMPurify wrapper
    sse.ts                         # SSE hook utility
    types/
      issues.ts                    # Issue-related TypeScript types
    hooks/                         # useAuth.ts, useChat.ts, useMyReports.ts
    utils.ts                       # Shared utilities
  middleware.ts                    # Route protection by JWT scope/role
  tailwind.config.ts               # Obsidian Intelligence design tokens
  next.config.mjs
  package.json
```

### Frontend Patterns

**API client**: All API calls go through `lib/api.ts` `apiClient`. The base URL comes from `NEXT_PUBLIC_API_URL` in `.env.local`. Never hardcode the backend URL.

**Auth**: JWT stored in httpOnly cookie. `middleware.ts` blocks:

- `/platform/*` unless `scope=platform`
- `/admin/*` unless `scope=tenant` + `tenant_admin` role

**React Query**: All server state managed via React Query. Use `useQuery` and `useMutation` hooks. Session-level `QueryClientProvider` is in `app/layout.tsx`.

**Charts**: Use `CHART_COLORS` from `lib/chartColors.ts` for all chart series. Never hardcode hex colors in chart configs.

**Role-based routing groups**:

- `app/(admin)/` — tenant admin screens
- `app/(platform)/` — platform admin screens
- `app/` root — end-user screens (chat, discover, my-reports)

---

## Design System — Obsidian Intelligence

Dark-first enterprise AI design system. Dark is the primary experience.

### Core Color Tokens (CSS custom properties)

```css
/* Dark mode (default) */
--bg-base: #0c0e14;
--bg-surface: #161a24;
--bg-elevated: #1e2330;
--bg-deep: #0a0c12;
--border: #2a3042;
--accent: #4fffb0; /* mint — active states, CTAs, positive metrics only */
--accent-dim: rgba(79, 255, 176, 0.08);
--alert: #ff6b35; /* P0/P1 errors, at-risk signals */
--warn: #f5c518; /* P2, quota warnings, health 50-69 */
--text-primary: #f1f5fb;
--text-muted: #8892a4;
--text-faint: #4a5568;
```

### Typography

```css
/* All UI text */
font-family: "Plus Jakarta Sans", sans-serif;
/* Data/numbers */
font-family: "DM Mono", monospace;
```

| Role            | Size / Weight                                    |
| --------------- | ------------------------------------------------ |
| Page title      | 22px / 700                                       |
| Section heading | 15px / 600                                       |
| Body / rows     | 13px / 400-500                                   |
| Labels / nav    | 11px / 500-600, uppercase, letter-spacing 0.06em |
| Data values     | 12-14px / 400-500, DM Mono                       |

### Spacing and Radius

```css
--r: 7px; /* inputs, buttons, chips */
--r-lg: 10px; /* cards, panels, modals */
--r-sm: 4px; /* badges */
```

Card padding: `20px`. Admin content: `28px 32px`. Section gap: `24-28px`.

### Key Component Rules

- AI response: no card, no bubble, no background. Text flows directly on `--bg-base`.
- Filter chips: outlined neutral at idle. Never fill with `accent-dim` unless selected.
- Admin tables: `th` 11px uppercase faint; `td` 13px; row hover `accent-dim`; numbers in DM Mono.
- Tab navigation: `border-bottom: 2px solid var(--accent)` on active tab.
- KB hint to end users: `"SharePoint · Google Drive · 2,081 documents indexed"` — never show "RAG ·".

### Severity Colors

| State                 | Color                |
| --------------------- | -------------------- |
| P0                    | `#FF3547` red        |
| P1                    | `--alert` orange     |
| P2                    | `--warn` yellow      |
| P3/P4                 | `--bg-elevated` grey |
| Active/Healthy (≥70)  | `--accent` green     |
| At Risk (50-69)       | `--warn` yellow      |
| Suspended/Error (<50) | `--alert` orange     |

### Banned Patterns

- `#6366F1`, `#8B5CF6`, `#3B82F6` (purple/blue palette)
- Inter, Roboto (wrong typefaces)
- Purple-to-blue gradients, glassmorphism
- AI response wrapped in card or bubble
- Hardcoded hex colors in component files (use tokens)
- `transition-all 300ms`, `rounded-2xl`, `shadow-lg` on every card

---

## Module Coverage Summary

### Backend Modules (all implemented)

auth, chat, issues (+ stream + worker + triage), memory, notifications, glossary, documents (sharepoint + gdrive + indexing), har (crypto + signing + state_machine + trust + health_monitor), admin/workspace (+ SSO config + group-sync config), users, teams, agents (+ templates), tenants, platform, registry, llm_profiles, profile/learning, feedback

### Frontend Screens by Role

**End User**: chat (two-state), discover (agent registry), my-reports, onboarding, privacy/memory controls, issue reporter modal, notification bell

**Tenant Admin**: dashboard, agents (library + deploy from template), analytics, document stores (SharePoint + Google Drive + sync health), glossary, knowledge-base, teams (members + audit log + memory controls + Auth0 sync), users (directory + bulk invite), workspace settings, SSO wizard, memory policy, issue queue, analytics, agent templates, cost analytics

**Platform Admin**: dashboard (tenant health table + alert summary + provisioning), tenants (CRUD + health + quota + LLM profiles + token budget), LLM profiles, agent templates, tool catalog, registry, engineering issue queue (platform queue + severity override + GitHub issue link), analytics (platform-wide + cost), audit log

**Not started (product-gated)**: FE-036 Agent Studio (`/admin/agents/studio/`) — full authoring environment with prompt editor, AI suggestions, example conversation builder, test chat.
