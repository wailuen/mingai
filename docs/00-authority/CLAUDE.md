# CLAUDE.md — mingai Backend Codegen Instructions

Preloaded instructions for AI codegen agents. Read this before writing any backend code.
Validated against real Phase 1 code on 2026-03-07. Phase 2 ongoing as of 2026-03-08.

## Implementation State (2026-03-08)

**Tests**: 1082 passing / 2 failed / 4 errors. The 2 failures and 4 errors are pre-existing asyncpg event loop binding noise from test ordering — not regressions. All feature tests pass.

**Phase 2 endpoint groups completed**:
- Auth, Chat, Issues (full CRUD + triage stream + admin/platform queues + GitHub webhook)
- Memory (notes, working memory, GDPR erasure, org context)
- Glossary (CRUD, bulk import, export, miss analytics, cache warm-up)
- Documents (SharePoint + Google Drive connect/sync, sync failure diagnosis)
- Users (invite, bulk invite, enhanced list, GDPR export)
- Teams (CRUD, members, audit log, Auth0 sync allowlist)
- Agents (list, create, update, status toggle, deploy from template)
- Agent templates (create, update, list with platform filter — platform admin)
- Tool catalog (list, register — platform admin)
- Analytics: satisfaction + engagement (tenant admin); cost + health (platform admin)
- Cache analytics: summary, by-index, cost savings, per-index TTL (API-106–109)
- Memory policy GET/PATCH (API-076–077)
- Audit logs: workspace (API-087) + platform (API-112)
- HAR A2A: transactions, signed events, trust score, health monitor (AI-040–060)
- Document indexing pipeline (AI-060)
- Notifications SSE (API-012)
- Tenant management: provisioning, health score, quota, LLM profiles, token budget

**Pending (Session 13 parallel launch)**:
- API-089–098: Registry (HAR agent registry CRUD, public discovery)
- API-113–120: Platform extras (impersonation, daily digest, GDPR deletion, notifications)
- API-121–125: Gap remediation items

**Migrations applied**: v001 (schema), v002 (RLS), v003 (HAR tables), v004 (cache tables), v005 (agent cards)

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
      routes.py            # Full CRUD + admin/platform queues + GitHub webhook
      blur_service.py      # ScreenshotBlurService — PIL Gaussian blur pipeline
      stream.py            # Redis Stream producer (XADD) — issue_reports:incoming
      worker.py            # Redis Stream consumer (XREADGROUP) — triage worker loop
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
      indexing.py          # DocumentIndexingPipeline — PDF/DOCX/PPTX/TXT → chunks → embeddings → vector index
    har/
      crypto.py            # Ed25519 keypair generation, Fernet private-key encryption, sign/verify
      signing.py           # create_signed_event(), verify_event_signature(), check_nonce_replay(), verify_event_chain()
      state_machine.py     # HAR transaction state machine (DRAFT→OPEN→NEGOTIATING→COMMITTED→EXECUTING→COMPLETED)
      routes.py            # POST/GET /har/transactions — create, list, get, transition, approve, reject
      trust.py             # compute_trust_score(agent_id, tenant_id, db) — KYB + completed − disputed formula
      health_monitor.py    # AgentHealthMonitor — asyncio background task, hourly trust score recomputation
    users/routes.py        # User management — invite, GDPR erase, profile
    teams/routes.py        # Team management — create, members, working memory
    tenants/routes.py      # Platform admin — tenant CRUD
    platform/routes.py     # Platform admin dashboard
    profile/learning.py    # ProfileLearningService — async learning from queries
    notifications/
      publisher.py         # publish_notification() — Redis Pub/Sub producer
      routes.py            # GET /notifications/stream — SSE delivery via StreamingResponse
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

### 11. Notification Channel Naming and SSE Pattern

Redis Pub/Sub channel for per-user notifications:

```
mingai:{tenant_id}:notifications:{user_id}
```

`publisher.py` publishes JSON to this channel. The route subscribes and forwards events as SSE:

```python
# notifications/routes.py — the SSE generator pattern
async def event_generator(pubsub):
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
            if msg:
                yield f"data: {msg['data']}\n\n"
            else:
                yield ": keepalive\n\n"  # every 30s to prevent proxy timeouts
    finally:
        await pubsub.unsubscribe()

# Route uses StreamingResponse with media_type="text/event-stream"
return StreamingResponse(event_generator(pubsub), media_type="text/event-stream")
```

`publish_notification(user_id, tenant_id, notification_type, title, body, link=None, redis=None)` is the sole write path. Never publish directly to the channel outside this function.

### 12. Redis Stream Constants and Patterns

Stream key and consumer group are module-level constants in `issues/stream.py`:

```python
STREAM_KEY = "issue_reports:incoming"
CONSUMER_GROUP = "issue_triage_workers"
STREAM_MAX_LEN = 10_000  # MAXLEN ~ applied on XADD
```

`ensure_stream_group(redis)` is idempotent — uses `XGROUP CREATE ... MKSTREAM` with `SETID 0`. Call once at worker startup; safe to call repeatedly.

`publish_issue_to_stream(report_id, tenant_id, issue_type, severity_hint, redis)` does XADD with `maxlen=STREAM_MAX_LEN, approximate=True`.

Worker (`issues/worker.py`) uses `XREADGROUP GROUP ... COUNT 10 BLOCK 5000`. On failure it applies exponential backoff with 3 retries before NACK. `reclaim_abandoned_messages` uses XCLAIM to recover messages idle >5 min from any dead consumer.

### 13. Issue Action Allowlists — State Machine Enforcement

Both admin and platform issue action endpoints enforce transitions through a module-level allowlist. Never accept arbitrary action strings.

Tenant admin actions (`POST /admin/issues/{id}/action`):

```python
_ADMIN_ISSUE_ACTIONS = {"assign", "resolve", "escalate", "request_info", "close_duplicate"}
```

Platform admin actions (`POST /platform/issues/{id}/action`):

```python
_PLATFORM_ISSUE_ACTIONS = {"override_severity", "route_to_tenant", "assign_sprint", "close_wontfix"}
```

Both follow the same route pattern as other PATCH endpoints: validate action against allowlist, then execute parameterized SQL. Reject unknown actions with 422.

### 14. HAR A2A Cryptography — Ed25519 + Fernet

Ed25519 keypairs are generated per agent on deploy. Private keys are stored Fernet-encrypted using PBKDF2HMAC derived from `JWT_SECRET_KEY` (200k iterations, SHA256, fixed salt `b"mingai-har-v1"`).

```python
from app.modules.har.crypto import generate_agent_keypair, sign_payload, verify_signature

# Generate (returns base64-encoded strings)
public_key_b64, private_key_enc_b64 = generate_agent_keypair()

# Sign (private_key_enc_b64 = Fernet-encrypted seed, payload = bytes)
signature_b64 = sign_payload(private_key_enc_b64, canonical_bytes)

# Verify (never raises — returns False on any error)
ok = verify_signature(public_key_b64, canonical_bytes, signature_b64)
```

### 15. HAR Signed Events — Canonical Payload Format

Every signed event is created via `create_signed_event()`. The canonical payload is always:

```python
canonical_dict = {
    "transaction_id": str,
    "event_type": str,
    "actor_agent_id": str,
    "payload": dict,
    "nonce": secrets.token_hex(32),   # 64 hex chars
    "timestamp": datetime.now(UTC).isoformat(),  # ISO 8601 with T separator
}
canonical_bytes = json.dumps(canonical_dict, sort_keys=True).encode()
event_hash = sha256(canonical_bytes + signature.encode()).hexdigest()
```

**Critical**: `created_at` passed to asyncpg INSERT must be a `datetime` object, NOT `isoformat()` string.
`verify_event_signature()` must use `.isoformat()` (T-separated), NOT `str()` (space-separated) to match.

### 16. Nonce Replay Protection — Redis SETNX TTL=600

```python
key = f"{tenant_id}:nonce:{nonce}"
was_set = await redis.set(key, "1", nx=True, ex=600)
# True = fresh, False = replay
```

### 17. Trust Score Formula

```
trust_score = max(0, min(100, kyb_pts + min(30, completed_count) - min(30, disputed_count * 10)))
kyb_pts: {0:0, 1:15, 2:30, 3:40}
```

Called by `compute_trust_score(agent_id, tenant_id, db)` which does NOT commit — caller commits.

### 18. GitHub Webhook — HMAC-SHA256, Fail-Closed

`POST /webhooks/github` validates the `X-Hub-Signature-256` header using HMAC-SHA256 over the raw request body. The secret comes from `GITHUB_WEBHOOK_SECRET` in env.

Fail-closed rule: if `GITHUB_WEBHOOK_SECRET` is not set, the endpoint returns 503 immediately. Never process an unverified webhook payload.

Event-to-status mapping (applied to `issue_reports`):

| GitHub event          | New status        |
| --------------------- | ----------------- |
| `issues.labeled`      | `triaged`         |
| `pull_request.opened` | `fix_in_progress` |
| `pull_request.merged` | `fix_merged`      |
| `release.published`   | `fix_deployed`    |

Unrecognized events return 200 with `{"processed": false}` — do not raise errors for unknown event types.

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
4. **`logout()` revokes the Redis session key** — `build_redis_key(tenant_id, "session", user_id)` deleted on logout. `local_login()` writes the same key via `_write_session_to_redis()` (fire-and-forget, non-fatal if Redis down).
5. **Bootstrap login uses `hmac.compare_digest()` for plaintext fallback** — constant-time to prevent timing attacks even on non-hashed bootstrap passwords. Never use `==` for password comparison.
6. **Module-level engine in session.py** — integration tests must use a single session-scoped TestClient.
7. **`EmbeddingService.__init__` reads env vars** — instantiation raises ValueError if env vars absent.
8. **`GlossaryExpander(db=None)` is valid** — returns [] from `_get_terms()` with debug log. For unit tests only.
9. **Issues router must be registered BEFORE chat router** — prevents chat router's wildcard paths from shadowing `/issues`.
10. **`on_event` in main.py is deprecated** — migrate to `lifespan` when refactoring startup.
11. **SSE connections hold Redis subscriptions open** — always `await pubsub.unsubscribe()` in a `finally` block on disconnect.
12. **`ensure_stream_group` must run before the worker's XREADGROUP loop** — if the group doesn't exist the XREADGROUP call raises a Redis error.
13. **`GITHUB_WEBHOOK_SECRET` unset → 503, not 401** — fail-closed; never fall through to processing.
14. **`_SAFE_SEGMENT_RE` in `redis_client.py` now validates both `tenant_id` and `key_type` and all `*parts`** — any segment with a colon raises ValueError immediately.
15. **asyncpg event loop binding in integration tests** — module-scoped SQLAlchemy engines bind to the first event loop. Each integration test that needs a DB session must create and dispose a fresh engine (function-scoped fixture). Module-scoped engine = "Future attached to a different loop" error.
16. **`generate_bootstrap_sql()` returns `list[tuple[text_obj, dict]]`** — each tuple is `(sqlalchemy.text(...), params_dict)`. Call `await session.execute(sql, params)` not `await session.execute(text(sql))`. Raw SQL strings are never returned.
17. **asyncpg TIMESTAMPTZ needs a `datetime` object** — passing `datetime.isoformat()` string to a TIMESTAMPTZ column raises `DataError: invalid input for query argument $N (expected datetime)`. Always pass `datetime.now(timezone.utc)` directly.
18. **HAR `verify_event_signature()` uses `.isoformat()` not `str()`** — `str(datetime)` produces space-separated format (`"2026-03-08 05:11:41+00:00"`); `.isoformat()` produces T-separator (`"2026-03-08T05:11:41+00:00"`). Signing and verification must match.
19. **Redis singleton across `asyncio.run()` calls causes "readline waiting" errors** — if integration tests call `asyncio.run()` multiple times, reset `app.core.redis_client._redis_pool = None` before each call to force a fresh connection in the new event loop.
20. **`AgentHealthMonitor.start()` is an infinite loop** — it must be launched as an `asyncio.create_task()` in `app.main:startup()`. Never `await` it directly.

---

## Environment Variables Reference

| Variable                         | Required    | Description                                                           |
| -------------------------------- | ----------- | --------------------------------------------------------------------- |
| `DATABASE_URL`                   | Yes         | `postgresql+asyncpg://user:pass@host:port/db`                         |
| `REDIS_URL`                      | Yes         | `redis://host:port/db`                                                |
| `CLOUD_PROVIDER`                 | Yes         | `aws` / `azure` / `gcp` / `local`                                     |
| `PRIMARY_MODEL`                  | Yes         | LLM deployment name for chat responses                                |
| `INTENT_MODEL`                   | Yes         | LLM deployment name for intent routing                                |
| `EMBEDDING_MODEL`                | Yes         | Embedding model name                                                  |
| `JWT_SECRET_KEY`                 | Yes         | Min 32 chars                                                          |
| `JWT_ALGORITHM`                  | No          | Default `HS256`                                                       |
| `FRONTEND_URL`                   | Yes         | Must not be `*`. Used for CORS.                                       |
| `AZURE_PLATFORM_OPENAI_API_KEY`  | If azure    | Required when `CLOUD_PROVIDER=azure`                                  |
| `AZURE_PLATFORM_OPENAI_ENDPOINT` | If azure    | Required when `CLOUD_PROVIDER=azure`                                  |
| `DEBUG`                          | No          | `true` exposes exception details in responses                         |
| `GITHUB_WEBHOOK_SECRET`          | If webhooks | HMAC-SHA256 secret for GitHub webhook. Endpoint returns 503 if unset. |

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
11. GitHub webhook payload rejected (503) when `GITHUB_WEBHOOK_SECRET` is unset — never process unverified payloads.
12. Redis key segments (`tenant_id`, `key_type`, all `*parts`) validated against `_SAFE_SEGMENT_RE` — colons in any segment raise ValueError before key construction.
13. Ed25519 private keys encrypted at rest with Fernet (`private_key_enc` column) — never store raw private keys.
14. `verify_signature()` never raises — returns False on any error (malformed key, bad signature, etc.).
15. HAR transaction routes require `require_tenant_admin` — never expose to end users.
16. Nonce replay attack prevention: every signed event nonce is recorded in Redis with 600s TTL. Duplicate nonce → reject.
17. `compute_trust_score()` does not commit — caller must `await db.commit()` after calling it.
