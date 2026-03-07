# mingai Backend — Developer Reference

## Architecture Overview

**Stack**: FastAPI + SQLAlchemy async (asyncpg) + PostgreSQL 16 + Redis 7 + pgvector

**Entry point**: `src/backend/app/main.py`
**Router**: `src/backend/app/api/router.py` — all API prefixes registered here
**Migrations**: `src/backend/alembic/`

## Module Map

```
app/
  core/
    database.py       # validate_tenant_id(), get_set_tenant_sql() — see CRITICAL PATTERNS
    dependencies.py   # get_current_user, require_tenant_admin (JWT validation)
    session.py        # get_async_session dependency
  modules/
    auth/             # login, refresh, logout, /me
    chat/             # SSE stream, feedback, conversations
      orchestrator.py # 8-stage RAG pipeline (CRITICAL — see below)
      embedding.py    # EmbeddingService (Azure text-embedding-3-small)
      vector_search.py
      prompt_builder.py
      persistence.py
      routes.py
    issues/           # Issue reports + screenshot blur
      routes.py       # GET/POST /issues, PATCH status, POST events
      blur_service.py # ScreenshotBlurService (Pillow, Gaussian r=20)
    memory/
      working_memory.py       # WorkingMemoryService (per-user, per-agent)
      team_working_memory.py  # TeamWorkingMemoryService (anonymised team context)
      org_context.py          # OrgContextService (Auth0/Okta/SAML sources)
    profile/
      learning.py     # ProfileLearningService (LLM extraction, Redis L1, PG L2)
    glossary/
      expander.py     # GlossaryExpander (Layer 6 inline query expansion)
    users/routes.py   # Invite, role change, status
    admin/
      workspace.py    # GET/PATCH /admin/workspace (tenant settings)
      tenants.py      # Platform admin tenant management
      llm_profiles.py # LLM profile CRUD
    platform/         # Platform admin routes
```

## CRITICAL PATTERNS

### 1. `get_set_tenant_sql()` returns a TUPLE, not a string

```python
# CORRECT
sql, params = get_set_tenant_sql(tenant_id)
await db.execute(text(sql), params)

# WRONG — was a string before Phase 1 fix
sql = get_set_tenant_sql(tenant_id)  # returns tuple now
```

### 2. `_stream_llm` must be mocked in ALL unit tests

`ChatOrchestrationService._stream_llm()` reads `CLOUD_PROVIDER` from env.
With `CLOUD_PROVIDER=azure`, it makes a live Azure API call and raises `ValueError` if the key is absent.

```python
# In every unit test file that imports the orchestrator:
async def _fake_stream_llm(self, system_prompt, query, tenant_id):
    yield "Test LLM response."

@pytest.fixture(autouse=True)
def mock_llm_stream(monkeypatch):
    from app.modules.chat import orchestrator as _orch_module
    monkeypatch.setattr(
        _orch_module.ChatOrchestrationService, "_stream_llm", _fake_stream_llm
    )
```

### 3. asyncpg JSON parameters require CAST

```sql
-- CORRECT (asyncpg)
INSERT INTO t (col) VALUES (CAST(:val AS jsonb))

-- WRONG (psycopg2 syntax, breaks asyncpg)
INSERT INTO t (col) VALUES (:val::jsonb)
```

### 4. Column allowlist for dynamic SET clauses

Any route that builds a dynamic `SET col = :val` SQL MUST maintain an explicit allowlist:

```python
_X_UPDATE_ALLOWLIST = {"name", "timezone", "locale"}

invalid = set(updates) - _X_UPDATE_ALLOWLIST
if invalid:
    raise ValueError(f"Invalid update fields: {invalid}")
```

### 5. Multi-tenant isolation

Every DB query MUST be scoped to `tenant_id` from the JWT claim (`current_user.tenant_id`).
Never trust a `tenant_id` from the request body without re-validating it matches the JWT.

### 6. Screenshot blur gate

`POST /issues` rejects when `screenshot_url` is set and `blur_acknowledged=False`:

```python
if request.screenshot_url is not None and not request.blur_acknowledged:
    raise HTTPException(status_code=422, detail="blur_acknowledged must be true when screenshot_url is provided")
```

## 8-Stage RAG Pipeline (`orchestrator.py`)

| Stage | What happens |
|---|---|
| 1 | Embed query (EmbeddingService) |
| 2 | Glossary expansion (GlossaryExpander) |
| 3 | Vector search (VectorSearchService) |
| 4a | User working memory (WorkingMemoryService) |
| 4b | Team working memory (TeamWorkingMemoryService) — skipped if no active_team_id |
| 5 | Org context (OrgContextService) |
| 6 | Build system prompt (SystemPromptBuilder) |
| 7 | Stream LLM response (_stream_llm — MUST be mocked in unit tests) |
| 8 | Persist conversation + update memories |

## Environment Variables (key ones)

| Var | Purpose |
|---|---|
| `JWT_SECRET_KEY` | HS256 JWT signing (64-char min) |
| `JWT_ALGORITHM` | Always `HS256` |
| `DATABASE_URL` | asyncpg connection string |
| `REDIS_URL` | Redis connection |
| `CLOUD_PROVIDER` | `azure` or `openai` — controls LLM client in _stream_llm |
| `PRIMARY_MODEL` | LLM deployment name (never hardcode) |
| `AZURE_PLATFORM_OPENAI_API_KEY` | Azure OpenAI key (eastus2) |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI key (southeastasia) |
| `EMBEDDING_MODEL` | Embedding deployment (text-embedding-3-small) |

## Testing

- **432 unit tests** — all must pass: `cd src/backend && python -m pytest tests/unit/ -q`
- **Tier 1 (unit)**: Mock DB session, mock services — fast, isolated
- **Tier 2 (integration)**: Real PostgreSQL + Redis via Docker Compose — no mocking of infra
- **Tier 3 (E2E)**: Full stack via Playwright — see `tests/e2e/`

## Security Notes

- JWT error detail must NEVER disclose env var names: use `"Authentication service unavailable"`
- 403 errors must not disclose caller scope/roles
- Email fields use `EmailStr` from pydantic (not manual `"@" in` checks)
- Notification preferences: max 20 keys, 4KB JSON limit
- Image uploads: 10MB size guard before Pillow processing (decompression bomb protection)
- `validate_tenant_id()` enforces UUID format — rejects SQL injection attempts

## Known Gotchas

1. `on_event` in `main.py` is deprecated — migrate to `lifespan` when refactoring startup
2. `VectorSearchService` takes no constructor arguments — never pass `db=` to it
3. `WorkingMemoryService` takes no constructor arguments — Redis connection is internal
4. `TeamWorkingMemoryService.get_context()` is an alias for `get_for_prompt()` — returns `None` if empty (Layer 4b skipped silently)
5. Issues router MUST be registered before chat router in `api/router.py` to prevent path collision
