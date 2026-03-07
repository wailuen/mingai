# CLAUDE.md — mingai Backend Codegen Instructions

Preloaded instructions for AI codegen agents. Read this before writing any backend code.
Validated against real Phase 1 code on 2026-03-07.

---

## Architecture Overview

**Stack**: FastAPI + SQLAlchemy (async) + Redis + PostgreSQL
**Port**: 8022
**Prefix**: All API endpoints under `/api/v1/`
**Auth**: Local JWT (Phase 1), Auth0 JWKS (Phase 2)
**Multi-tenant**: Row-Level Security (RLS) at PostgreSQL level

### Module Structure

```
src/backend/app/
  api/
    router.py              # Aggregates all module routers under /api/v1/
  core/
    config.py              # pydantic_settings.BaseSettings — all from .env
    database.py            # RLS helpers, get_set_tenant_sql(), validate_tenant_id()
    dependencies.py        # FastAPI DI: get_current_user, require_tenant_admin, require_platform_admin
    session.py             # Async SQLAlchemy engine + get_async_session() dependency
    redis_client.py        # get_redis() / close_redis()
    middleware.py          # CORS, security headers, request ID injection
    health.py              # build_health_response() helper
    logging.py             # structlog JSON setup
    bootstrap.py           # First-run schema/seed logic
    seeds.py               # Seed data helpers
    schema.py              # Shared Pydantic base schemas
  modules/
    auth/
      jwt.py               # decode_jwt_token(), decode_jwt_token_v1_compat(), JWTValidationError
      routes.py            # POST /auth/local/login, /auth/token/refresh, /auth/logout, GET /auth/current
    issues/
      routes.py            # Full CRUD for issue_reports — blur gate enforced here
      blur_service.py      # ScreenshotBlurService — PIL Gaussian blur pipeline
    chat/
      orchestrator.py      # ChatOrchestrationService — 8-stage RAG pipeline
      routes.py            # POST /chat/stream, /chat/feedback; GET/DELETE /conversations/...
      embedding.py         # EmbeddingService — reads EMBEDDING_MODEL from env
      vector_search.py     # VectorSearchService — tenant-scoped pgvector search
      persistence.py       # ConversationPersistenceService — saves exchanges to DB
      prompt_builder.py    # SystemPromptBuilder — 6-layer prompt assembly
    memory/
      working_memory.py    # WorkingMemoryService — per-user/per-agent Redis context
      team_working_memory.py  # TeamWorkingMemoryService — anonymized team context
      org_context.py       # OrgContextService — JWT claims extraction
      notes.py             # Memory notes model and validation (200-char enforcement)
      routes.py            # GET/POST/DELETE /memory/notes, GDPR export/clear
    admin/
      workspace.py         # GET/PATCH /admin/workspace — workspace settings
    glossary/
      expander.py          # GlossaryExpander — inline query expansion + injection protection
      routes.py            # CRUD for glossary_terms, bulk import
    documents/
      sharepoint.py        # SharePoint connection, test, sync trigger, sync status
    users/routes.py        # User management — invite, GDPR erase, profile
    teams/routes.py        # Team management — create, members, working memory
    tenants/routes.py      # Platform admin — tenant CRUD
    platform/routes.py     # Platform admin dashboard
    profile/learning.py    # ProfileLearningService — async learning from queries
```

---

## Key Patterns

### 1. DB Helpers Are Module-Level Async Functions (Mockable)

Every route module defines its DB operations as standalone async functions at module level,
not as class methods. This makes them patchable with `unittest.mock.patch`.

```python
# CORRECT pattern (in routes.py)
async def create_issue_db(tenant_id, user_id, title, ..., db) -> dict:
    await db.execute(text("INSERT ..."), {...})
    await db.commit()
    return {...}

@router.post("/issues")
async def create_issue(request, current_user=Depends(...), session=Depends(...)):
    result = await create_issue_db(..., db=session)
    return result

# In unit tests:
with patch("app.modules.issues.routes.create_issue_db", new_callable=AsyncMock) as mock:
    mock.return_value = {...}
    resp = client.post(...)
```

### 2. Dynamic SQL Uses Column Allowlists + text() Parameterized Bindings

Never construct SQL with f-strings using user data. Always use `sqlalchemy.text()` with
a named params dict. For dynamic PATCH/UPDATE, filter through an allowlist first.

```python
# CORRECT
_WORKSPACE_UPDATE_ALLOWLIST = {"name", "timezone", "locale", "notification_preferences"}

invalid = set(updates) - _WORKSPACE_UPDATE_ALLOWLIST
if invalid:
    raise ValueError(f"Invalid workspace update fields: {invalid}")

await db.execute(
    text("UPDATE ... SET col = :col WHERE id = :id"),
    {"col": value, "id": record_id},
)

# NEVER
await db.execute(f"UPDATE ... SET {col} = '{value}'")  # SQL injection
```

### 3. `get_set_tenant_sql()` Returns a Tuple — Unpack Before execute()

`database.get_set_tenant_sql(tenant_id)` returns `(sql_str, params_dict)`, NOT a string.

```python
# CORRECT
from app.core.database import get_set_tenant_sql
sql, params = get_set_tenant_sql(tenant_id)
await db.execute(text(sql), params)

# WRONG — will fail
await db.execute(text(get_set_tenant_sql(tenant_id)))  # TypeError: text() got a tuple
```

### 4. `_stream_llm` in Orchestrator Must Be Mocked in Unit Tests (autouse fixture)

`ChatOrchestrationService._stream_llm` reads `PRIMARY_MODEL` and `CLOUD_PROVIDER` from
env and makes a real OpenAI/Azure API call. In Tier 1 unit tests, this MUST be intercepted
via an `autouse=True` fixture using `monkeypatch.setattr`.

```python
# Required in test_orchestrator.py (autouse=True means it applies to ALL tests in the file)
async def _fake_stream_llm(self, system_prompt, query, tenant_id):
    yield "Test LLM response."

@pytest.fixture(autouse=True)
def mock_llm_stream(monkeypatch):
    from app.modules.chat import orchestrator as _orch_module
    monkeypatch.setattr(
        _orch_module.ChatOrchestrationService, "_stream_llm", _fake_stream_llm
    )
```

If you forget this fixture, the test will fail at import time or make a real API call.

### 5. Redis Key Namespace

All Redis keys follow this namespace convention:

```
mingai:{tenant_id}:{service}:{id}

Examples:
  mingai:{tenant_id}:working_memory:{user_id}:{agent_id}   # per-user working memory
  mingai:{tenant_id}:team_memory:{team_id}                  # team working memory
  mingai:{tenant_id}:glossary_terms                          # glossary term cache
  mingai:{tenant_id}:embedding_cache:{sha256_hash[:16]}     # embedding cache
```

### 6. Team Memory: Never Store user_id

`TeamWorkingMemoryService` stores anonymized queries only. `user_id` is never written
to any Redis key or value. The stored schema is:

```json
{ "topics": ["string"], "recent_queries": ["a team member asked: <truncated>"] }
```

Any code that attempts to store `user_id` in team memory violates GDPR isolation.

### 7. Screenshot Blur Gate — Always Enforce Before Storing

Before accepting any `screenshot_url` in issue creation, the route must verify
`blur_acknowledged=True`. This check lives in the route handler, not the DB helper.

```python
# In issues/routes.py
if request.screenshot_url is not None and not request.blur_acknowledged:
    raise HTTPException(status_code=422, detail="blur_acknowledged must be true...")
```

Do not move this check into `create_issue_db`. The route layer is the enforcement point.

### 8. `InviteUserRequest.email` Uses Pydantic `EmailStr`

`users/routes.py` imports `EmailStr` from Pydantic and uses it as the type for
`InviteUserRequest.email`. No manual `"@" not in v` check is needed.

```python
from pydantic import BaseModel, EmailStr

class InviteUserRequest(BaseModel):
    email: EmailStr  # Pydantic validates — no manual check needed
```

Note: `auth/routes.py` `LoginRequest.email` uses a manual `"@"` check (Phase 1 bootstrap
only). Do not replicate that pattern in new code.

### 9. Route Registration Order — Specific Before Parameterized

Routes with specific path segments must be registered BEFORE parameterized routes
to avoid FastAPI path collision.

```python
# CORRECT order in issues/routes.py:
@router.patch("/issues/{issue_id}/status")   # specific — registered first
@router.post("/issues/{issue_id}/events")    # specific — registered first
@router.get("/issues/{issue_id}")            # parameterized — registered last
```

Same pattern applies in `users/routes.py`: `/users/me` routes before `/users/{id}`.

### 10. asyncpg JSON Parameters Require CAST

asyncpg does not auto-cast Python dicts to jsonb. Use `CAST(:param AS jsonb)`:

```sql
-- CORRECT (asyncpg)
INSERT INTO t (col) VALUES (CAST(:val AS jsonb))
-- or pass json.dumps(dict) as a string parameter — asyncpg accepts string → jsonb

-- WRONG (psycopg2 syntax, breaks asyncpg)
INSERT INTO t (col) VALUES (:val::jsonb)
```

---

## Test Patterns

### Tier 1 — Unit Tests (target: < 1s each)

Location: `src/backend/tests/unit/`
Run: `cd src/backend && python -m pytest tests/unit/ -q`

Rules:

- Mock ALL external dependencies: DB, Redis, LLM APIs
- Use `AsyncMock` for async functions, `MagicMock` for sync
- Use `patch("app.modules.<module>.routes.<function_name>", new_callable=AsyncMock)`
- JWT tokens: use a 64-char test secret (`"a" * 64`), never real env vars
- Use `TestClient(app, raise_server_exceptions=False)` for route tests
- Patch env vars via `patch.dict(os.environ, {...})` in a fixture
- `autouse=True` fixtures for cross-cutting mocks (e.g., `_stream_llm`)

Standard fixture pattern:

```python
TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_USER_ID = "user-001"

@pytest.fixture
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
    }
    with patch.dict(os.environ, env):
        yield

@pytest.fixture
def client(env_vars):
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)
```

### Tier 2 — Integration Tests (requires Docker)

Location: `src/backend/tests/integration/`

Rules:

- NO MOCKING — use real PostgreSQL and real Redis from docker-compose
- Guard with `pytest.skip()` when required env vars are absent
- Session-scoped `TestClient` shared across all integration tests

### Tier 3 — E2E Tests

Location: `src/backend/tests/e2e/`
No mocking. Requires full running stack. Uses Playwright.

---

## Known Gotchas

1. **`get_set_tenant_sql()` returns a tuple** — never pass directly to `text()`. Always `sql, params = ...`.
2. **`_stream_llm` makes real API calls** — `autouse=True` monkeypatch fixture required in test_orchestrator.py.
3. **Route order matters** — specific paths (`/issues/{id}/status`) before parameterized (`/issues/{id}`).
4. **`logout()` is a no-op in Phase 1** — no token revocation. Known limitation.
5. **Bootstrap login compares passwords in plaintext** — intentional for bootstrap admin only. Never replicate.
6. **Module-level engine in session.py** — integration tests must use a single session-scoped TestClient.
7. **`EmbeddingService.__init__` reads env vars** — instantiation raises ValueError if env vars absent.
8. **`GlossaryExpander(db=None)` is valid** — returns [] from `_get_terms()` with debug log. For unit tests only.
9. **Issues router must be registered BEFORE chat router** — prevents chat router's wildcard paths from shadowing `/issues`.
10. **`on_event` in main.py is deprecated** — migrate to `lifespan` when refactoring startup.

---

## Environment Variables Reference

| Variable                         | Required | Description                                   |
| -------------------------------- | -------- | --------------------------------------------- |
| `DATABASE_URL`                   | Yes      | `postgresql+asyncpg://user:pass@host:port/db` |
| `REDIS_URL`                      | Yes      | `redis://host:port/db`                        |
| `CLOUD_PROVIDER`                 | Yes      | `aws` / `azure` / `gcp` / `local`             |
| `PRIMARY_MODEL`                  | Yes      | LLM deployment name for chat responses        |
| `INTENT_MODEL`                   | Yes      | LLM deployment name for intent routing        |
| `EMBEDDING_MODEL`                | Yes      | Embedding model name                          |
| `JWT_SECRET_KEY`                 | Yes      | Min 32 chars                                  |
| `JWT_ALGORITHM`                  | No       | Default `HS256`                               |
| `FRONTEND_URL`                   | Yes      | Must not be `*`. Used for CORS.               |
| `AZURE_PLATFORM_OPENAI_API_KEY`  | If azure | Required when `CLOUD_PROVIDER=azure`          |
| `AZURE_PLATFORM_OPENAI_ENDPOINT` | If azure | Required when `CLOUD_PROVIDER=azure`          |
| `DEBUG`                          | No       | `true` exposes exception details in responses |

---

## Security Invariants (never violate these)

1. All SQL uses `text()` with named params. No f-strings with user data.
2. Dynamic column selection (PATCH endpoints) uses a module-level allowlist set.
3. All secrets from `os.environ`. No hardcoded keys, passwords, or model names.
4. `screenshot_url` rejected unless `blur_acknowledged=True` — blur gate in route handler.
5. `user_id` never stored in team working memory.
6. Application DB user must be `NOSUPERUSER` (superusers bypass PostgreSQL RLS).
7. `FRONTEND_URL` must not be `*` — enforced in `config.py` validator.
8. Glossary definitions sanitized against injection patterns before storage.
9. Error responses never leak internal config in production (`DEBUG=false`).
10. Logs never record passwords, tokens, or full API keys.
