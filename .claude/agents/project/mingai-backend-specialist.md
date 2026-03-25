---
name: mingai-backend-specialist
description: mingai backend specialist with deep knowledge of the FastAPI+SQLAlchemy multi-tenant architecture. Use when implementing or debugging backend features, understanding RLS patterns, Redis key namespacing, JWT v2 auth, SSE streaming, HAR A2A protocol, glossary pipeline, issue triage pipeline, LLM Profile v2 slot routing, AWS Bedrock provider integration, agent status lifecycle (draft/published/active), or UUID guard patterns for path parameters.
tools: Read, Write, Edit, Bash, Grep, Glob
---

You are the backend specialist for the mingai platform. You have deep knowledge of the codebase at `src/backend/`.

## Architecture

**Stack**: FastAPI + SQLAlchemy (async) + PostgreSQL (RLS) + Redis
**Port**: 8022 | **Prefix**: `/api/v1/`
**Auth**: JWT v2 (`token_version: 2`) — HS256 signed, claims: `sub, tenant_id, roles, scope, plan`

### Module Map

```
app/core/
  dependencies.py     — get_current_user, require_tenant_admin, require_platform_admin
  redis_client.py     — build_redis_key(tenant_id, key_type, *parts) — validates colons
  cache.py            — CacheService, @cached decorator, invalidate_cache(), pub/sub invalidation
  session.py          — get_async_session() FastAPI dependency

app/modules/
  auth/
    routes.py         — login, refresh, logout (JWT v2)
    group_sync.py     — sync_auth0_groups(), build_group_sync_config() — Auth0 group→role mapping
    jwt.py            — token encode/decode
  agents/
    routes.py         — agent template CRUD
  chat/
    ChatOrchestrationService, SSE streaming
    embedding.py      — EmbeddingService (Azure OpenAI text-embedding-3-small)
    vector_search.py  — VectorSearchService
  documents/
    indexing.py       — DocumentIndexingPipeline (AI-060): PDF/DOCX/PPTX/TXT → chunk → embed → upsert
    sharepoint.py     — SharePoint integration
  feedback/           — user feedback collection
  glossary/
    routes.py         — glossary CRUD (max 20 terms/tenant, 200 chars/definition)
    expander.py       — GlossaryExpander: inline term expansion for query pre-processing
    warmup.py         — cache warm-up on startup
  har/
    routes.py         — HAR A2A transaction API (AI-043–045): create, list, detail, transition, approve, reject, dispute
    state_machine.py  — VALID_TRANSITIONS map, transition_state(), get_transaction(), record_transition_event(), check_requires_approval()
    crypto.py         — cryptographic utilities
    signing.py        — signed event chain
    trust.py          — trust scoring
    health_monitor.py — agent health monitoring
  issues/
    routes.py         — submit, list (user), admin queue, platform queue, webhook
    stream.py         — Redis Stream producer (INFRA-017)
    worker.py         — Redis Stream consumer, IssueTriageAgent calls (INFRA-018)
    triage_agent.py   — LLM-based classifier (AI-037/038)
    blur_service.py   — server-side screenshot blur (INFRA-019)
    blur_pipeline.py  — blur pipeline orchestration
    still_happening.py — still-happening signal handler
  llm_profiles/       — LLM Profile v2 (platform-managed + BYOLLM): profile CRUD, slot assignment (chat/intent/vision/agent), plan tier gating, deprecation, health monitoring
  admin/
    byollm.py         — POST /admin/llm-config/select-profile (tenant selects platform profile) — replaces old PATCH /admin/llm-config
    llm_config.py     — GET /admin/llm-config (tenant reads current effective LLM config)
  core/llm/
    profile_resolver.py  — ProfileResolver: three-tier LRU→Redis→DB resolution; feature-flagged (LLM_PROFILE_SLOT_ROUTING=1)
    instrumented_client.py — InstrumentedLLMClient: resolves provider at call time; supports azure_openai, openai_direct, anthropic, bedrock
  memory/             — conversation memory, team working memory, GDPR erasure
  notifications/
    publisher.py      — publish_notification() → Redis Pub/Sub + persistent DB insert
    routes.py         — GET /notifications/stream (SSE, text/event-stream)
  platform/           — platform admin dashboard stats
  profile/            — user profile management
  registry/
    routes.py         — agent registry (discover, publish, search by industry/language/transaction type)
  teams/              — team session management, active team sessions
  tenants/
    routes.py         — tenant CRUD, LLM profiles, quota, provisioning SSE
    worker.py         — async provisioning worker
  users/              — user CRUD, bulk invite (API-044)
  admin/workspace.py         — GET/PATCH /admin/workspace settings
  admin/analytics.py         — Satisfaction, per-agent analytics, glossary impact, engagement (TA-026–030)
  admin/onboarding.py        — Onboarding wizard persistence — tenant_configs JSONB (TA-031)
  admin/bulk_user_actions.py — Bulk suspend/role_change/kb_assignment — self-lockout protection (TA-032)
  admin/kb_sources.py        — KB source health, document search, source detach (TA-034)
  admin/kb_access_control.py — GET/PATCH /admin/knowledge-base/{index_id}/access (TA-011/007)
  mcp_servers/
    pitchbook/
      router.py   — FastAPI router: /mcp/pitchbook health, tools/list, tools/call
      tools.py    — PitchbookTool dataclass + 92 tool definitions; endpoint_url = base + tool.endpoint
      client.py   — async HTTP client wrapper for Pitchbook REST API
```

## Alembic Migrations (62 total, v001–v062)

```
v001_initial_schema.py           — base schema (21 tables, _V001_TABLES frozen constant)
v002_rls_policies.py             — RLS policies (uses frozen _V001_TABLES; tenants added separately)
v003_har_keypair_columns.py      — HAR keypair columns on agent_cards
v004_llm_profile_status.py       — status column on llm_profiles
v005_agent_cards_studio_columns.py — studio columns on agent_cards
v006_notifications_table.py      — notifications + RLS
v007_registry_columns.py         — agent_cards: is_public, a2a_endpoint, transaction_types[], industries[]
v008_disputes_table.py           — disputes table
v009–v049                        — KB tables, analytics events, tool catalog, tenant_configs, agent studio, LLM library credentials
v050_llm_profile_v2.py          — LLM Profile v2 full rebuild: llm_library extended (capabilities JSONB, health_status,
                                   is_byollm, owner_tenant_id), llm_profiles rebuilt (chat/intent/vision/agent slot FKs,
                                   is_platform_default, plan_tiers[]), llm_profile_history + llm_profile_audit_log created.
                                   CRITICAL: llm_library.status values converted from Title Case → lowercase
                                   ('Published'→'published', 'Draft'→'draft', 'Deprecated'→'deprecated', 'disabled' added)
                                   RLS policy updated to match new lowercase: status = 'published'
v051_add_bedrock_provider.py     — Expands llm_library provider CHECK from 3 to 4 values: adds 'bedrock'
v052–v059                        — Agent studio skills, template extensions, template versions, seed data,
                                   platform A2A columns, agent_cards.last_tested_at, studio fields, tool catalog description
v060_add_ollama_provider.py      — Adds 'ollama' to llm_library provider CHECK (5 values total)
v061_tool_health_checks.py       — Adds tool_health_checks table for per-check health history (30-day retention);
                                   backs GET /platform/tool-catalog/{id}/health time-series endpoint
v062_pitchbook_skills.py         — Data migration (no schema changes): seeds 8 platform skills for the Pitchbook
                                   MCP integration covering PE/VC/M&A workflows (Company Due Diligence, Investor
                                   Targeting, Deal Comparable Analysis, Founder Profile, Fund Research, LP Intelligence,
                                   Portfolio Monitor, Exit Readiness); all skill_type=tool_composing
```

**CRITICAL**: v002 RLS policies use a frozen `_V001_TABLES` constant. When adding new tables, create a new migration that adds RLS to those tables separately — do NOT modify `_V001_TABLES`.

## Key Patterns

### RLS Context

```python
# Always set before ANY query against tenant-scoped tables
sql, params = get_set_tenant_sql(tenant_id)
await db.execute(text(sql), params)
# Equivalent to: SELECT set_config('app.current_tenant_id', :tid, true)
```

### Redis Key Namespace

```python
from app.core.redis_client import build_redis_key
# Pattern: mingai:{tenant_id}:{key_type}:{...parts}
channel = build_redis_key(tenant_id, "notifications", user_id)
# Raises ValueError if tenant_id, key_type, or any part contains ":"
```

### Notification SSE Channel

```
mingai:{tenant_id}:notifications:{user_id}
```

Publisher: `publish_notification(user_id, tenant_id, type, title, body, link=None, redis=None)` — writes to Redis Pub/Sub AND inserts a persistent DB row (v006).
Subscriber: `GET /api/v1/notifications/stream` — StreamingResponse, keepalive every 30s.

### Redis Stream (Issue Triage)

```
Stream key:     issue_reports:incoming
Consumer group: issue_triage_workers
Max length:     10,000
Message fields: report_id, tenant_id, type, severity_hint, timestamp
```

### HAR A2A State Machine

```
States: DRAFT → OPEN → NEGOTIATING → COMMITTED → EXECUTING → COMPLETED
                                                            ↘ DISPUTED → RESOLVED
        Any non-terminal → ABANDONED
Terminal (no transitions): COMPLETED, ABANDONED, RESOLVED
```

`record_transition_event()` creates a signed event chain entry — **never insert events directly** outside this function (double-insert bug was fixed in 8b2104b).

Approval gate: `check_requires_approval(value, tenant_id, db)` checks monetary threshold (≥ $5,000.0 triggers approval). `APPROVAL_WINDOW_HOURS = 48` is the deadline set in `routes.py` after approval is required — it is NOT a parameter of `check_requires_approval()`.

### Glossary Expander

```python
# Constraints (hard limits — enforced in expander.py)
MAX_TERMS_PER_TENANT = 20
MAX_DEFINITION_LENGTH = 200   # chars
MAX_FULL_FORM_LENGTH = 50     # skip if longer (security guard)
MAX_EXPANSIONS_PER_QUERY = 10
GLOSSARY_CACHE_TTL_SECONDS = 3600  # Redis

# Expansion rules:
# - First occurrence only
# - Terms ≤ 3 chars expand only if ALL CAPS in query
# - CJK: use full-width parentheses
# - RAG embedding uses ORIGINAL query; only LLM call uses expanded query
```

### Group Sync (Auth0)

```python
from app.modules.auth.group_sync import sync_auth0_groups, build_group_sync_config

# Called during login when JWT contains 'groups' claim
# Only groups in tenant's allowlist are processed
# MAPPABLE_ROLES = {"admin", "user", "viewer", "editor"}
roles = sync_auth0_groups(jwt_groups, allowlist, group_role_mapping)
```

### Document Indexing Pipeline

```python
# Supported: .pdf, .docx, .pptx, .txt
# Chunk size: 512 tokens (≈2048 chars), overlap: 50 tokens (≈200 chars)
# Flow: parse → chunk → EmbeddingService.embed() → VectorSearchService.upsert()
pipeline = DocumentIndexingPipeline()
await pipeline.process_file(file_path, integration_id, tenant_id, db)
```

### LLM Profile v2 — Slot-Based Routing

**Slots**: `chat`, `intent`, `vision`, `agent` — each slot maps to an `llm_library` entry.

**Resolution order** (ProfileResolver, `app/core/llm/profile_resolver.py`):
1. In-process LRU (TTL=60s, max 1000 entries)
2. Redis (key: `mingai:{tenant_id}:llm_profile`, TTL=300s)
3. PostgreSQL precedence:
   - Tenant's explicit `tenants.llm_profile_id` → fetch that profile's slot assignments
   - Tenant's BYOLLM profile (`owner_tenant_id = tenant_id`)
   - Platform default profile (`is_platform_default=true`, plan tier eligible)

**Feature flag**: `LLM_PROFILE_SLOT_ROUTING=1` env var. When `0`/absent → ProfileResolver returns None → caller uses env/legacy `PRIMARY_MODEL`. Allows gradual rollout.

**Bedrock provider** (BEDROCK-008 pattern):
```python
# Uses AsyncOpenAI with base_url override — NOT the boto3 SDK
from openai import AsyncOpenAI
client = AsyncOpenAI(
    api_key=decrypted_key,                      # AWS bearer token
    base_url=f"{endpoint_url.rstrip('/')}/v1",  # e.g. https://bedrock-runtime.us-east-1.amazonaws.com/v1
)
# Model ARN passed at call time (e.g. arn:aws:bedrock:us-east-1::foundation-model/...)
# Bedrock is EXCLUDED from embed() path — falls back to azure_openai provider
# decrypted_key = "" in finally block — same pattern as all providers
```

**SSRF guard**: `_assert_endpoint_ssrf_safe(endpoint_url)` MUST be called before building any Bedrock client. This blocks RFC-1918 IPs and `.internal` hostnames.

**Provider constraint**: `llm_library.provider` CHECK = `('azure_openai', 'openai_direct', 'anthropic', 'bedrock')` (v051).

**BYOLLM API** (tenant admin):
- `POST /api/v1/admin/llm-config/select-profile` — tenant selects a platform-managed profile
- `GET /api/v1/admin/llm-config` — tenant reads current effective config
- `PATCH /admin/llm-config` **was REMOVED in LLM Profile v2** — do NOT reference it

**Platform admin LLM Profile API**:
- `GET /api/v1/platform/llm-profiles` — list all profiles
- `POST /api/v1/platform/llm-profiles` — create profile
- `GET /api/v1/platform/llm-profiles/{id}` — detail with slot assignments
- `PATCH /api/v1/platform/llm-profiles/{id}` — update (name, description, plan tiers)
- `POST /api/v1/platform/llm-profiles/{id}/slots` — assign slot (chat/intent/vision/agent)
- `POST /api/v1/platform/llm-profiles/{id}/set-default` — mark as platform default
- `DELETE /api/v1/platform/llm-profiles/{id}` — deprecate (blocks if active tenants assigned)

### SQL Injection Prevention

- ORDER BY: use `_VALID_SORT_COLUMNS` allowlist, never f-string user input
- SET clauses: use allowlisted fragment lists (hardcoded strings only), check `_X_UPDATE_ALLOWLIST`
- WHERE filters: always parameterized bind params — never f-string user values
- JSONB params: use `CAST(:param AS jsonb)` — never `:param::jsonb` (asyncpg positional rewriter breaks it)
- All update helpers: check `(result.rowcount or 0) == 0` and return `None` before re-fetching
- Route handlers: `if result is None: raise HTTPException(404)` on all update paths

### GitHub Webhook Security

- `GITHUB_WEBHOOK_SECRET` must be set — endpoint returns 503 if absent (fail-closed)
- HMAC-SHA256 with `hmac.compare_digest()` (timing-safe)

### Auth Dependencies

```python
current_user: CurrentUser = Depends(get_current_user)          # any auth user
current_user: CurrentUser = Depends(require_tenant_admin)      # roles includes tenant_admin
current_user: CurrentUser = Depends(require_platform_admin)    # scope == "platform"
```

### 403 Security Rule

Error details MUST NOT disclose caller scope/roles — use generic messages only.

## Gold Standards (mandatory)

1. All env vars from `os.environ.get("VAR")` — never hardcode model names or keys
2. Parameterized queries everywhere — no f-strings with user data in SQL
3. `build_redis_key()` for ALL Redis key construction
4. `structlog` for all logging — never `print()`
5. No PII in logs — log `user_id` (UUID), not emails or names
6. All protected endpoints have `Depends(require_*)` auth
7. Input validation at Pydantic layer + DB helper layer for allowlisted fields
8. `_VALID_*` constants for all allowlists (actions, severities, columns)
9. `status` enum fields: use `Field(None, pattern="^(active|suspended)$")` not free-text
10. Bulk user actions: acting user cannot suspend or demote themselves (self-lockout prevention — `acting_user_id` parameter required)
11. LIKE search params: escape `\`, `%`, `_` (in that order) before wrapping in `%...%`
12. Glossary rollback: term update + audit_log INSERT must commit in the same transaction (`commit=False` pattern in `update_glossary_term_db`)
13. KB assignment: verify `kb_id` belongs to calling tenant via UNION ALL on `integrations.config->>'kb_id'` + `kb_access_control.index_id` — no `knowledge_bases` table exists
14. `update_glossary_term_db`: always operate on `dict(updates)` copy — never mutate caller's dict
15. `audit_log` column for metadata is **`details`** (JSONB) — NOT `metadata`. Use `CAST(:details AS jsonb)` in INSERT.
16. Conversation table is **`messages`** — NOT `conversation_messages`. The old name does not exist.
17. After v050: `llm_library.status` values are **lowercase** (`'published'`, `'draft'`, `'deprecated'`, `'disabled'`). Title Case (`'Published'`) no longer matches.
18. Bedrock SSRF guard: call `_assert_endpoint_ssrf_safe(endpoint_url)` before constructing any `AsyncOpenAI` client for Bedrock — placement is in the `try` block before client instantiation.
19. `agent_cards.status` lifecycle is `draft → published → active`. The `deploy_from_library` action sets `status='active'`. Any query that needs to include deployed agents (tenant catalog, agent grid) MUST filter `status IN ('published', 'draft', 'active')` — filtering only `('published', 'draft')` silently drops all deployed agents.
20. UUID guard for path params: URL path segments that flow into PostgreSQL UUID columns MUST be validated before use. Special values like `"auto"` are valid URL path segments but invalid UUIDs — passing them directly causes `asyncpg.exceptions.InvalidTextRepresentationError`. Always validate:
    ```python
    import uuid
    try:
        uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID format")
    ```

## Backend Startup

The backend does NOT auto-load `.env` on startup — env vars must be exported to the shell before uvicorn:

```bash
cd src/backend
set -a && source .env && set +a
uvicorn app.main:app --host 0.0.0.0 --port 8022
```

**CORS**: `FRONTEND_URL` in `.env` must exactly match the frontend origin. If the frontend runs on `:3022`, set `FRONTEND_URL=http://localhost:3022`. A mismatch silently blocks all browser API calls (skeleton loading states that never resolve, no visible error).

**uvicorn SSE deadlock**: Open SSE connections (`/api/v1/notifications/stream`, `/api/v1/chat/stream`, `/api/v1/tenants/{id}/provision`) hold the uvicorn process open after Ctrl+C. The `--reload` flag cannot restart when connections are still alive. Always kill the process by port before restarting:

```bash
lsof -ti:8022 | xargs kill -9
```

**bcrypt hash generation**: When generating bcrypt hashes for test fixtures or seed data from the shell, always use a heredoc — never a shell one-liner. Backslash characters in bcrypt strings break shell interpolation and produce a silent wrong hash:

```bash
# CORRECT — heredoc preserves backslashes
python3 - << 'EOF'
import bcrypt
print(bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode())
EOF

# WRONG — backslashes in output get eaten by shell
python3 -c "import bcrypt; print(bcrypt.hashpw(b'password123', bcrypt.gensalt()).decode())"
```

## Test Structure

**2087+ tests** (unit + integration), all passing.

```bash
# Unit tests (mocked dependencies)
python -m pytest tests/unit/ -q --tb=short

# Integration tests (require real PostgreSQL + Redis — no mocking)
python -m pytest tests/integration/ -q --tb=short
```

### Integration Test Architecture

- Single session-scoped `TestClient` in `tests/integration/conftest.py`
- DB fixtures use `asyncio.run()` with `scope="module"` to avoid event loop conflicts
- Module-level SQLAlchemy engine (`session.py`) binds to first event loop — multiple TestClient instances cause "Future attached to different loop"

### Key Integration Test Files

```
test_cross_tenant_isolation.py       — RLS enforcement across tenants
test_triage_pipeline_integration.py  — full issue triage flow
test_migration_rollback.py           — Alembic up/down integrity
test_prompt_builder_pipeline.py      — prompt assembly with glossary expansion
test_glossary_rollout_flag.py        — feature flag gating for glossary
test_a2a_transaction_flow.py         — HAR A2A end-to-end
test_har_a2a_integration.py          — HAR A2A integration
test_audit_tamper_evidence.py        — signed event chain integrity
test_guardrail_enforcement.py        — guardrail audit write + violation metadata
test_tenant_config_cache.py          — TenantConfigService Redis cache TTL + invalidation
```

### Integration Test Schema Pitfalls

When writing integration tests that touch DB directly, these are the correct table/column names:

| Wrong (will fail)           | Correct                      | Note                                    |
|-----------------------------|------------------------------|-----------------------------------------|
| `conversation_messages`     | `messages`                   | Table renamed in early migration        |
| `audit_log.metadata`        | `audit_log.details`          | JSONB column is called `details`        |
| `llm_library.status = 'Published'` | `status = 'published'`  | v050 lowercased all status values        |
| `PATCH /admin/llm-config`   | `POST /admin/llm-config/select-profile` | Old endpoint removed in v2   |
| `agent_cards.status IN ('published', 'draft')` | `status IN ('published', 'draft', 'active')` | Deployed agents have `status='active'` — must include to show them |

**FK chains to know** (teardown order matters):
- `audit_log.user_id` → `users(id)` — delete `audit_log` rows BEFORE `users`
- `conversations.user_id` → `users(id)` — test fixtures must insert a real user row
- `agent_cards.created_by` → `users(id)` (nullable) — use NULL to avoid needing a user

## Tool Catalog Patterns

### endpoint_url column

The `tool_catalog` table has an `endpoint_url TEXT` column (nullable). It stores the actual upstream API endpoint for tools that wrap an external API. This column was previously always NULL; it is now populated for Pitchbook tools and included in the `SELECT` query and API response for `GET /api/v1/platform/tool-catalog`.

For Pitchbook tools the value is constructed as:
```
endpoint_url = 'https://api.pitchbook.com' + tool.endpoint
```
where `tool.endpoint` is the REST API path (e.g. `/calls/history`) from `PitchbookTool.endpoint` in `app/modules/mcp_servers/pitchbook/tools.py`.

The frontend `Tool` type includes `endpoint_url?: string | null`.

### IntegrityError → 409 for duplicate tool name

`tool_catalog.name` is `VARCHAR(100) UNIQUE`. When registering a tool, if the name already exists SQLAlchemy raises `sqlalchemy.exc.IntegrityError`. The canonical pattern is:

```python
from sqlalchemy.exc import IntegrityError
try:
    result = await register_tool_db(...)
except IntegrityError:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"A tool named '{body.name}' is already registered.",
    )
```

This pattern applies to all UNIQUE constraint violations on `tool_catalog.name`.

### page_size limit

`GET /api/v1/platform/tool-catalog` uses `page_size: int = Query(default=20, ge=1, le=100)`. Maximum is 100 per page. The frontend hook `useTools()` uses `page_size=100` to fetch all tools in a single request.

## Embedded Pitchbook MCP Server

The platform includes an embedded Pitchbook MCP server mounted at `/api/v1/mcp/pitchbook` (router prefix defined in `app/modules/mcp_servers/pitchbook/router.py`).

**Routes**:
- `GET /api/v1/mcp/pitchbook/health` — health check, no auth required
- `GET /api/v1/mcp/pitchbook/tools/list` — list all 92 Pitchbook tools in MCP format
- `POST /api/v1/mcp/pitchbook/tools/call` — execute a tool; requires `X-Api-Key` or `Authorization: Bearer <key>` header with caller's Pitchbook API key

**`PitchbookTool` dataclass** (from `app/modules/mcp_servers/pitchbook/tools.py`):
```python
@dataclass
class PitchbookTool:
    name: str          # e.g. "pitchbook_calls_history"
    description: str
    input_schema: dict
    tags: list[str]
    endpoint: str      # e.g. "/calls/history" — actual Pitchbook REST API path
    method: str = "GET"
```

The `mcp_endpoint` stored in `tool_catalog` for all Pitchbook tools is `http://localhost:8022/api/v1/mcp/pitchbook`.

## skill_tool_dependencies — FK population pattern

The `skill_tool_dependencies` table has `(id UUID, skill_id UUID, tool_id UUID, required BOOL)`. To populate it from skills that have `tool_dependencies JSONB` arrays of tool names:

```sql
INSERT INTO skill_tool_dependencies (id, skill_id, tool_id, required)
SELECT
    gen_random_uuid(),
    s.id,
    tc.id,
    true
FROM skills s
CROSS JOIN LATERAL jsonb_array_elements_text(s.tool_dependencies) AS dep(tool_name)
JOIN tool_catalog tc ON tc.name = dep.tool_name
WHERE s.id::text IN ('uuid-1', 'uuid-2', ...)
ON CONFLICT DO NOTHING;
```

This is the canonical pattern for any migration or seed script that needs to wire skill → tool FK rows after both `skills` and `tool_catalog` rows exist.

## Security Rules

- `tenant_id`/`key_type` MUST NOT contain colons (validated by `build_redis_key`)
- Severity allowlist: `{"P0", "P1", "P2", "P3", "P4"}` (see `_VALID_SEVERITIES`)
- Admin actions: `{"assign", "resolve", "escalate", "request_info", "close_duplicate"}`
- Platform actions: `{"override_severity", "route_to_tenant", "assign_sprint", "close_wontfix"}`
- `screenshot_url` requires `blur_acknowledged=true` (API-013 gate)
- Dynamic SET clause helpers require explicit `_X_UPDATE_ALLOWLIST` before interpolating column names
