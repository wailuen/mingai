# 08 — LLM Provider Credentials Management

**Generated**: 2026-03-17
**Phase**: New feature — Platform LLM Provider Credentials Management
**Numbering**: PVDR-001 through PVDR-020
**Stack**: PostgreSQL + FastAPI + Next.js + Fernet encryption
**Related plan**: `workspaces/mingai/02-plans/11-llm-provider-config-plan.md`
**Related flows**: `workspaces/mingai/03-user-flows/21-llm-provider-config-flows.md`

---

## Overview

Move LLM provider credentials from hardcoded `.env` vars into a `llm_providers` PostgreSQL table managed via Platform Admin UI. Seven provider types supported (azure_openai, openai, anthropic, deepseek, dashscope, doubao, gemini). Six deployment slots (primary, intent, vision, doc_embedding, kb_embedding, intent_fallback). Env vars remain as break-glass fallback only.

---

## Backend Items — PVDR-001 to PVDR-012

---

### PVDR-001: `llm_providers` Alembic Migration

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `src/backend/alembic/versions/v039_llm_providers.py` — table created, BYTEA column for `api_key_encrypted`, partial unique index `llm_providers_single_default`, RLS policy `llm_providers_platform`
**Priority**: P0
**Effort**: 3h
**Depends on**: None
**File**: `src/backend/alembic/versions/v039_llm_providers.py`

**Description**:

Create the `llm_providers` table. This is a platform-level table (no tenant isolation — platform admin only). Columns match the architecture design exactly:

- `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
- `provider_type VARCHAR(50) NOT NULL` with CHECK: azure_openai, openai, anthropic, deepseek, dashscope, doubao, gemini
- `display_name VARCHAR(200) NOT NULL`
- `description TEXT`
- `endpoint VARCHAR(500)` — nullable; required for azure_openai, null for key-only providers
- `api_key_encrypted BYTEA NOT NULL` — Fernet-encrypted bytes
- `models JSONB NOT NULL DEFAULT '{}'` — slot → deployment_name mapping
- `options JSONB NOT NULL DEFAULT '{}'` — api_version, reasoning_effort, etc.
- `pricing JSONB` — nullable pricing override
- `is_enabled BOOLEAN NOT NULL DEFAULT true`
- `is_default BOOLEAN NOT NULL DEFAULT false`
- `provider_status VARCHAR(50) NOT NULL DEFAULT 'unchecked'` — unchecked | healthy | error
- `last_health_check_at TIMESTAMPTZ`
- `health_error TEXT`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `created_by UUID` — nullable FK to users.id

Partial unique index: `CREATE UNIQUE INDEX llm_providers_single_default ON llm_providers (is_default) WHERE is_default = true`

RLS: platform_admin_bypass policy ONLY. No tenant isolation. RLS added in this migration file — do NOT rely on v002 `_V001_TABLES`.

Migration must be reversible (`downgrade()` drops the index and table).

**Acceptance criteria**:

- [x] `alembic upgrade head` runs clean (after v036_mcp_servers)
- [x] `alembic downgrade -1` drops table and index cleanly
- [x] Partial unique index rejects second `is_default=true` row
- [x] CHECK constraint rejects unknown `provider_type` values
- [x] BYTEA column accepts Fernet-encrypted bytes (confirmed by integration test)
- [x] RLS policy `platform_admin_bypass` added in migration, not in v002
- [x] Migration is in `v039_llm_providers.py` — no version gaps

---

### PVDR-002: `ProviderService` Class

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `src/backend/app/core/llm/provider_service.py` — `encrypt_api_key/decrypt_api_key`, all CRUD methods, `set_default()` two-step atomic, `test_connectivity()`
**Priority**: P0
**Effort**: 4h
**Depends on**: PVDR-001
**File**: `src/backend/app/core/llm/provider_service.py`

**Description**:

New service class. All `llm_providers` CRUD operations plus encryption helpers. Follows the same structure as `app/core/tenant_config_service.py`. Uses Fernet encryption from `app/modules/har/crypto.py` — same pattern as `app/modules/admin/byollm.py`.

Methods to implement:

- `list_providers(db, enabled_only=False) -> list[dict]` — never returns `api_key_encrypted` field; returns `key_present: bool`
- `get_provider(db, provider_id) -> dict | None`
- `get_default_provider(db) -> dict | None` — queries `is_default=true AND is_enabled=true`
- `create_provider(db, payload, created_by) -> dict`
- `update_provider(db, provider_id, updates) -> dict | None`
- `set_default(db, provider_id) -> None` — two-step atomic update, single commit
- `delete_provider(db, provider_id) -> bool`
- `encrypt_api_key(plaintext_key: str) -> bytes` — calls `get_fernet()`, never stores key on self
- `decrypt_api_key(encrypted_bytes: bytes) -> str` — decrypts; caller must clear variable after use
- `test_connectivity(provider_row: dict) -> tuple[bool, str | None]` — decrypts key in-memory, makes real API call, returns (success, error_message_or_None)

`set_default()` two-step pattern:

```python
await db.execute(text("UPDATE llm_providers SET is_default = false WHERE is_default = true"))
await db.execute(text("UPDATE llm_providers SET is_default = true WHERE id = :id"), {"id": provider_id})
await db.commit()
```

**Acceptance criteria**:

- [x] Plaintext key never stored in DB or as instance attribute
- [x] `list_providers()` never returns `api_key_encrypted` field
- [x] `set_default()` uses two-step update in single transaction
- [x] `test_connectivity()` catches all exceptions, returns `(False, message)` on failure
- [x] `encrypt_api_key → decrypt_api_key` round-trip produces original string
- [x] `update_provider()` with no `api_key` key in updates dict: does not touch `api_key_encrypted` column
- [x] `delete_provider()` returns False (not error) if provider_id not found

---

### PVDR-003: Platform Provider API

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: 8 endpoints at `/api/v1/platform/providers` in `src/backend/app/modules/platform/llm_providers/routes.py`, `bootstrap_active` field in list response, registered in `router.py`
**Priority**: P0
**Effort**: 5h
**Depends on**: PVDR-002
**Files**:

- `src/backend/app/modules/platform/llm_providers/__init__.py` (empty)
- `src/backend/app/modules/platform/llm_providers/routes.py`
- `src/backend/app/api/router.py` (add `include_router`)

**Description**:

New FastAPI router at prefix `/platform/providers`. All routes require `require_platform_admin` from `app/core/dependencies.py`.

Endpoints:

| Method | Path                                   | Notes                                                 |
| ------ | -------------------------------------- | ----------------------------------------------------- |
| GET    | `/platform/providers`                  | List all; never return `api_key_encrypted`            |
| GET    | `/platform/providers/{id}`             | Detail; no key                                        |
| POST   | `/platform/providers`                  | Create; encrypt key before DB write                   |
| PATCH  | `/platform/providers/{id}`             | Update; omit key field = preserve existing            |
| DELETE | `/platform/providers/{id}`             | 409 if default or only provider                       |
| POST   | `/platform/providers/{id}/test`        | Returns `{success, latency_ms, error}`                |
| POST   | `/platform/providers/{id}/set-default` | Two-step atomic update                                |
| GET    | `/platform/providers/health-summary`   | `{total, healthy, error, unchecked, last_checked_at}` |

`GET /platform/providers` list response must include `bootstrap_active: bool` at the top level — `true` when table has no rows OR env fallback is the active path.

`CreateProviderRequest` validation:

- `provider_type`: must be in `_VALID_PROVIDER_TYPES = frozenset({...7 types...})`
- `display_name`: 1–200 chars
- `endpoint`: required when `provider_type == "azure_openai"`
- `api_key`: min 1 char
- `models`: dict with valid slot keys only

`DELETE` guards:

- `is_default=true` → 409 "Cannot delete the default provider. Set another provider as default first."
- Only enabled provider → 409 "Cannot delete the only active provider."

`api_key` field must NEVER appear in any structlog call. Use `api_key="[REDACTED]"` if logging the request shape.

**Acceptance criteria**:

- [x] GET list/detail never returns `api_key_encrypted` or raw `api_key` value
- [x] POST creates row with encrypted bytes in DB (confirmed by integration test reading DB directly)
- [x] PATCH without `api_key` field: `api_key_encrypted` unchanged in DB
- [x] DELETE default provider returns 409
- [x] `/test` endpoint returns `{success: bool, latency_ms: int, error: str | null}`
- [x] `bootstrap_active` field present in list response
- [x] Router registered at `/api/v1/platform/providers`
- [x] Log line `api_key` value never appears in structlog output during POST

---

### PVDR-004: `InstrumentedLLMClient._resolve_library_adapter()` Migration + Bypass Module Consolidation

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `InstrumentedLLMClient._resolve_library_adapter()` queries `llm_providers` table, env fallback with WARNING log, `AzureOpenAIProvider` constructor updated to accept explicit credentials; all 8 bypass modules consolidated
**Priority**: P0
**Effort**: 8h (expanded — 8 bypass modules found by codebase analysis)
**Depends on**: PVDR-002
**Files**:

- `src/backend/app/core/llm/instrumented_client.py` (primary)
- `src/backend/app/core/azure_openai.py` (constructor fix — different from `app/core/llm/azure_openai.py`)
- `src/backend/app/modules/chat/orchestrator.py:627,639-640`
- `src/backend/app/modules/chat/intent_detection.py:299-301,354-366`
- `src/backend/app/modules/chat/embedding.py:52-66`
- `src/backend/app/modules/issues/triage_agent.py:159,173-174,193`
- `src/backend/app/modules/profile/learning.py:400,448-449,464`
- `src/backend/app/modules/agents/routes.py:1846,1858-1859`
- `src/backend/app/modules/platform/llm_library/routes.py:535`
- `src/backend/app/modules/platform/routes.py:1172,1255`

**Description**:

**CRITICAL SCOPE NOTE**: Codebase analysis found that `InstrumentedLLMClient` is NOT the only LLM entry point. 8 modules bypass it and read env vars directly. All must be consolidated.

**Step 1 — Fix `AzureOpenAIProvider` constructor** (`app/core/azure_openai.py`):
Change `__init__(self)` (reads from env) → `__init__(self, api_key: str, endpoint: str, api_version: str = "2024-02-01")`. 4 instantiation sites must pass credentials.

**Step 2 — Migrate `InstrumentedLLMClient`**:
Replace current `_resolve_library_adapter()` implementation. Currently reads `PRIMARY_MODEL` from `os.environ`. New implementation reads from `llm_providers` table.

New flow:

1. Query default row: `SELECT * FROM llm_providers WHERE is_default=true AND is_enabled=true LIMIT 1`
2. If found: decrypt key → construct provider-specific adapter → overwrite `decrypted_key = ""` → return `(adapter, model, "library")`
3. If `llm_library_id` is set on tenant config: use that entry's `model_name` as the primary slot override
4. If no default row: env fallback — log `"llm_providers_env_fallback_active"` at WARNING level, then use `PRIMARY_MODEL` env var as today

Adapter construction by `provider_type` (match/case on `provider_row["provider_type"]`):

- `azure_openai` → `AzureOpenAIProvider(api_key=decrypted_key, endpoint=..., api_version=...)`
- `openai` → `OpenAIDirectProvider(api_key=decrypted_key)`
- Others (anthropic, deepseek, etc.) → reserved; raise `NotImplementedError` with clear message until respective adapters are implemented

Decrypted key MUST be cleared after use: `decrypted_key = ""` immediately after adapter instantiation. Never assigned to `self`.

**Acceptance criteria**:

- [x] `AzureOpenAIProvider.__init__()` accepts `(api_key, endpoint, api_version)` — no env reads in constructor
- [x] All 4 `AzureOpenAIProvider()` instantiation sites updated to pass credentials
- [x] Chat completion works when `llm_providers` has a valid default row
- [x] Chat completion works via env fallback when table has zero rows
- [x] `"llm_providers_env_fallback_active"` logged at WARNING during env fallback
- [x] Decrypted key not present in any log line (confirmed by security test PVDR-019)
- [x] `decrypted_key` variable overwritten with `""` immediately after adapter instantiation
- [x] `ChatOrchestrator._generate_answer()` no longer reads `PRIMARY_MODEL` or `AZURE_PLATFORM_*` from env
- [x] `IntentDetectionService._get_llm_client()` no longer reads `CLOUD_PROVIDER` or `AZURE_PLATFORM_*` from env
- [x] `EmbeddingService.__init__()` no longer reads `EMBEDDING_MODEL` or `AZURE_PLATFORM_*` from env
- [x] `TriageAgent._call_llm()` no longer reads `AZURE_PLATFORM_*` from env
- [x] `ProfileLearningService._run_intent_classification()` no longer reads `AZURE_PLATFORM_*` from env
- [x] `AgentExecutor._run_agent_test()` no longer reads `AZURE_PLATFORM_*` from env
- [x] Platform LLM library test harness passes credentials from DB to `AzureOpenAIProvider` constructor
- [x] `grep -r "AZURE_PLATFORM_OPENAI_API_KEY" src/backend/app/` returns only bootstrap/config (not pipeline code)

---

### PVDR-005: `embed()` Path Migration

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `embed()` uses `doc_embedding` slot from DB provider row, env fallback `EMBEDDING_MODEL` with warning log
**Priority**: P0
**Effort**: 2h
**Depends on**: PVDR-002, PVDR-004
**File**: `src/backend/app/core/llm/instrumented_client.py`

**Description**:

Replace `os.environ.get("EMBEDDING_MODEL")` in `embed()` with DB lookup.

New logic:

1. Get default provider row
2. Use `provider_row["models"].get("doc_embedding")` as embedding model name
3. If `provider_type == "anthropic"`: call `_resolve_embedding_fallback_adapter()` (PVDR-010)
4. If no default row: env fallback `EMBEDDING_MODEL` (warn: `"llm_providers_embed_env_fallback_active"`)
5. `kb_embedding` slot: `provider_row["models"].get("kb_embedding") or provider_row["models"].get("doc_embedding")` (fallback within provider)

**Acceptance criteria**:

- [x] `embed()` uses `doc_embedding` slot from DB when default provider configured
- [x] `embed()` falls back to `EMBEDDING_MODEL` env var when table empty
- [x] Anthropic primary provider triggers `_resolve_embedding_fallback_adapter()` call
- [x] `kb_embedding` slot falls back to `doc_embedding` if not set

---

### PVDR-006: Bootstrap Auto-Seed

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `seed_llm_provider_from_env()` in `src/backend/app/core/seeds.py`, called in `src/backend/app/main.py` lifespan handler
**Priority**: P0
**Effort**: 3h
**Depends on**: PVDR-002
**File**: `src/backend/app/core/seeds.py`

**Description**:

Add `seed_llm_provider_from_env()` async function to the existing seeds module. Called at application startup in `app/main.py` lifespan handler (after DB pool is ready, same location as existing bootstrap calls). Must be idempotent.

Logic:

1. Count rows in `llm_providers`. If `> 0`: return `False` immediately (no-op).
2. Read `AZURE_PLATFORM_OPENAI_API_KEY`, `AZURE_PLATFORM_OPENAI_ENDPOINT`, `PRIMARY_MODEL` from env.
3. If any of the three are absent/empty: log `"llm_provider_bootstrap_skip_missing_env"` at WARNING. Return `False`.
4. Build `models` dict from env vars (PRIMARY_MODEL → primary, INTENT_MODEL → intent, EMBEDDING_MODEL → doc_embedding, and optional slots from `AZURE_OPENAI_VISION_DEPLOYMENT`, `AZURE_OPENAI_KB_EMBEDDING_DEPLOYMENT`, `AZURE_OPENAI_INTENT_FALLBACK_DEPLOYMENT`).
5. Call `ProviderService().create_provider()` with `is_default=True`, commit.
6. Log `"llm_provider_seeded_from_env"` at INFO with `slot_count`.
7. Return `True`.

**Acceptance criteria**:

- [x] Second call with populated table: returns `False`, no DB write
- [x] Seeds exactly one `is_default=true` row when env vars present and table empty
- [x] Does nothing if table has rows (even if zero rows are `is_enabled=true`)
- [x] Warning logged when env vars missing, no exception raised
- [x] `seed_llm_provider_from_env()` is called in `app/main.py` lifespan handler

---

### PVDR-007: Health Check Background Job

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `src/backend/app/modules/platform/provider_health_job.py` — APScheduler every 600s, per-provider jitter, registered in `src/backend/app/main.py`
**Priority**: P1
**Effort**: 3h
**Depends on**: PVDR-002
**File**: `src/backend/app/modules/platform/provider_health_job.py`

**Description**:

Background APScheduler job. Pattern mirrors `app/modules/platform/tool_health_job.py` and `health_score_job.py`. Runs every 600 seconds (10 minutes).

Job logic:

1. Fetch all `is_enabled=true` providers
2. For each provider (iterate, not gather — serial to avoid rate limit spikes):
   a. Record `start_time = time.monotonic()`
   b. Call `ProviderService.test_connectivity(provider_row)`
   c. Calculate `latency_ms = int((time.monotonic() - start_time) * 1000)`
   d. Update `provider_status`, `last_health_check_at`, `health_error` in DB
   e. Log `"provider_health_check"` structured log: `provider_id`, `provider_type`, `status`, `latency_ms`
3. Wrap per-provider check in `try/except Exception` — one failure must not abort remaining checks

Per-provider jitter: `await asyncio.sleep(random.randint(0, 30))` before each check to avoid thundering herd when multiple providers exist.

**Acceptance criteria**:

- [x] Job registered in scheduler at application startup
- [x] `provider_status` set to "healthy" on success, "error" on failure
- [x] `last_health_check_at` updated after every check attempt
- [x] `health_error` cleared (set to NULL) on successful check
- [x] One failing provider does not prevent remaining providers from being checked
- [x] Structured log emitted per provider per run

---

### PVDR-008: Tenant Provider Selection API

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `GET /admin/llm-config/providers` and `PATCH /admin/llm-config/provider` in `src/backend/app/modules/admin/llm_config.py`
**Priority**: P1
**Effort**: 3h
**Depends on**: PVDR-002
**File**: `src/backend/app/modules/admin/llm_config.py`

**Description**:

Extend the existing Tenant Admin LLM config module. Add two new endpoints to the existing `router` in this file.

`GET /admin/llm-config/providers`

- Requires `require_tenant_admin`
- Returns enabled platform providers (no credentials)
- Each item includes: `id`, `display_name`, `provider_type`, `is_default`, `provider_status`, `slots_available: list[str]`
- `slots_available` derived from non-empty keys in `provider_row["models"]`

`PATCH /admin/llm-config/provider`

- Requires `require_tenant_admin`
- Body: `{"provider_id": "uuid" | null}`
- `provider_id = null` → delete `llm_provider_selection` row from `tenant_configs` (revert to default)
- `provider_id = "uuid"` → validate exists and `is_enabled=true`, then upsert `tenant_configs` row with `config_type = 'llm_provider_selection'`
- Call `_invalidate_config_cache(current_user.tenant_id)` on success
- Return `{provider_id: str | null, using_default: bool}`

**Acceptance criteria**:

- [x] GET returns only enabled providers, no credentials, with `slots_available`
- [x] PATCH with unknown `provider_id` returns 404
- [x] PATCH with disabled `provider_id` returns 422
- [x] PATCH with `provider_id=null` removes selection, returns `using_default: true`
- [x] `tenant_configs` row upserted with `ON CONFLICT (tenant_id, config_type) DO UPDATE`
- [x] Config cache invalidated on successful PATCH

---

### PVDR-009: Tenant Selection in `InstrumentedLLMClient`

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `InstrumentedLLMClient` checks `llm_provider_selection` in `TenantConfigService`, falls back to default with `tenant_provider_selection_invalid_fallback` WARNING log
**Priority**: P1
**Effort**: 2h
**Depends on**: PVDR-004, PVDR-008
**File**: `src/backend/app/core/llm/instrumented_client.py`

**Description**:

Extend `_resolve_adapter()` to respect tenant's `llm_provider_selection` config. Before calling `_resolve_library_adapter()`, check `TenantConfigService.get(tenant_id, "llm_provider_selection")`. If present and has a `provider_id`, pass it to `_resolve_library_adapter(llm_library_id, provider_id=selected_provider_id)`.

`_resolve_library_adapter()` gets an optional `provider_id` parameter. When supplied:

1. Look up that specific provider row
2. If found and `is_enabled=true`: use it
3. If not found or `is_enabled=false`: log `"tenant_provider_selection_invalid_fallback"` at WARNING, fall through to default provider

**Acceptance criteria**:

- [x] Tenant with no selection uses default provider
- [x] Tenant with valid selection uses their chosen provider
- [x] Tenant with selection pointing to disabled/deleted provider falls back to default (with warning log)
- [x] Warning log includes `tenant_id`, `selected_provider_id`, `fallback_provider_id`

---

### PVDR-010: Anthropic Embedding Fallback

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `_resolve_embedding_fallback_adapter()` in `src/backend/app/core/llm/instrumented_client.py` — SQL fallback query for azure_openai/openai providers with `doc_embedding` slot
**Priority**: P1
**Effort**: 2h
**Depends on**: PVDR-005
**File**: `src/backend/app/core/llm/instrumented_client.py`

**Description**:

New private method `_resolve_embedding_fallback_adapter()` called from `embed()` when active provider has no embedding support (i.e. `provider_type == "anthropic"` or `doc_embedding` slot is empty).

SQL query to find fallback:

```sql
SELECT * FROM llm_providers
WHERE is_enabled = true
  AND provider_type IN ('azure_openai', 'openai')
  AND models->>'doc_embedding' IS NOT NULL
  AND models->>'doc_embedding' != ''
ORDER BY is_default DESC, created_at ASC
LIMIT 1
```

Returns `(adapter, model_name)` on success.
Raises `ValueError` with actionable message if no fallback found:

> "Primary provider (anthropic) does not support embeddings and no Azure OpenAI / OpenAI provider with a doc_embedding slot was found. Add an Azure OpenAI provider with doc_embedding configured."

Decrypted key cleared after adapter instantiation (same pattern as PVDR-004).

**Acceptance criteria**:

- [x] Anthropic primary + Azure fallback: `embed()` uses Azure adapter and `doc_embedding` model
- [x] No embedding-capable fallback: `embed()` raises ValueError with actionable message
- [x] Unit test covers both paths (mock DB query)
- [x] Decrypted key cleared after adapter instantiation

---

### PVDR-011: Provider Health Summary on Platform Dashboard

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `GET /platform/providers/health-summary` endpoint in `src/backend/app/modules/platform/llm_providers/routes.py`
**Priority**: P1
**Effort**: 2h
**Depends on**: PVDR-007
**File**: `src/backend/app/modules/platform/routes.py`

**Description**:

Add `llm_providers` health summary to the `GET /platform/providers/health-summary` endpoint (can also be surfaced via the existing `GET /admin/dashboard` response for use in the PA dashboard widget).

Query:

```sql
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN provider_status = 'healthy' THEN 1 ELSE 0 END) AS healthy,
    SUM(CASE WHEN provider_status = 'error' THEN 1 ELSE 0 END) AS error,
    SUM(CASE WHEN provider_status = 'unchecked' THEN 1 ELSE 0 END) AS unchecked,
    MAX(last_health_check_at) AS last_checked_at
FROM llm_providers
WHERE is_enabled = true
```

Return shape: `{total: int, healthy: int, error: int, unchecked: int, last_checked_at: str | null}`

Requires `require_platform_admin`.

**Acceptance criteria**:

- [x] Endpoint accessible at `/api/v1/platform/providers/health-summary`
- [x] Returns correct counts from DB
- [x] `last_checked_at` is the most recent `last_health_check_at` across enabled providers
- [x] Returns all zeros when table is empty (not an error)

---

### PVDR-012: Remove Mandatory Env Var Requirements

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: Graceful fallback with WARNING logs in `src/backend/app/core/llm/instrumented_client.py`; no hard `ValueError` at import time when env vars absent and DB row exists
**Priority**: P2
**Effort**: 1h
**Depends on**: PVDR-004, PVDR-005, PVDR-006, PVDR-018 (integration tests green)
**File**: `src/backend/app/core/llm/instrumented_client.py`

**Description**:

Change the hard `ValueError` raises on missing `PRIMARY_MODEL`, `EMBEDDING_MODEL`, `INTENT_MODEL` from hard failures to graceful fallback with warning log. The system should only hard-fail if BOTH the DB table has zero rows AND the relevant env var is absent.

Update module docstring to document that these env vars are now "break-glass emergency fallback only".

**DO NOT implement before PVDR-018 passes** — need integration tests to confirm DB path is stable first.

**Acceptance criteria**:

- [x] Server starts cleanly with no env vars set if `llm_providers` has a default row
- [x] Missing env vars with empty DB: warning logged at startup, ValueError raised only on first actual request (not at import time or server startup)
- [x] Module docstring updated to describe env vars as break-glass fallback

---

## Frontend Items — PVDR-013 to PVDR-016

---

### PVDR-013: Platform Provider List Screen

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `src/web/app/(platform)/platform/providers/page.tsx`, `src/web/app/(platform)/platform/providers/elements/ProviderList.tsx`, `src/web/lib/hooks/useLLMProviders.ts`
**Priority**: P0
**Effort**: 4h
**Depends on**: PVDR-003
**Files**:

- `src/web/app/(platform)/platform/providers/page.tsx`
- `src/web/app/(platform)/platform/providers/elements/ProviderList.tsx`
- `src/web/lib/hooks/useLLMProviders.ts`

**Description**:

New Platform Admin screen. Pattern matches `src/web/app/(platform)/platform/llm-profiles/page.tsx`.

`useLLMProviders.ts` hooks (mirror `useLLMProfiles.ts` structure):

- `useLLMProviders()` — GET `/api/v1/platform/providers`
- `useCreateProvider()` — POST `/api/v1/platform/providers`
- `useUpdateProvider({ id, payload })` — PATCH `/api/v1/platform/providers/{id}`
- `useDeleteProvider()` — DELETE `/api/v1/platform/providers/{id}`
- `useTestProvider()` — POST `/api/v1/platform/providers/{id}/test`
- `useSetDefaultProvider()` — POST `/api/v1/platform/providers/{id}/set-default`

`ProviderList` table design:

- `th`: 11px, uppercase, `letter-spacing: .05em`, `color: var(--text-faint)`
- `td`: 13px, `padding: 12px 14px`, `vertical-align: middle`
- Row hover: `background: var(--accent-dim)`
- Columns: Provider Name | Type (DM Mono chip) | Status badge | Default | Slots Configured | Actions

Status badge colors (from design system):

- `healthy` → accent green (`--accent`)
- `error` → alert orange (`--alert`)
- `unchecked` → text-faint grey

"Default" column: accent green checkmark icon when `is_default=true`, em dash otherwise.

"Slots Configured": compact chips, `font-size: 11px`, DM Mono.

Bootstrap banner (PVDR-015) rendered above table when `response.bootstrap_active === true`.

Actions per row:

- Edit (pencil) → opens ProviderForm edit mode
- Test (bolt) → POST `/{id}/test`, toast result
- Set Default → POST `/{id}/set-default`; button `disabled` + tooltip "Already default" when `is_default=true`
- Delete (trash) → `disabled` when `is_default=true` (tooltip: "Set another provider as default first"); confirmation dialog when enabled

**Acceptance criteria**:

- [x] No `api_key` data rendered anywhere on the page
- [x] Status badge colors match design system tokens
- [x] Delete button disabled for default provider with explanatory tooltip
- [x] Provider count shown in page subtitle (e.g. "3 providers")
- [x] Hook correctly calls `/api/v1/platform/providers` (not `/platform/llm-profiles`)
- [x] Bootstrap banner conditionally rendered

---

### PVDR-014: Provider Form (Create/Edit)

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `src/web/app/(platform)/platform/providers/elements/ProviderForm.tsx`, `src/web/app/(platform)/platform/providers/elements/SlotMappingGrid.tsx` — 2-step wizard, slot capability matrix
**Priority**: P0
**Effort**: 5h
**Depends on**: PVDR-013
**Files**:

- `src/web/app/(platform)/platform/providers/elements/ProviderForm.tsx`
- `src/web/app/(platform)/platform/providers/elements/SlotMappingGrid.tsx`

**Description**:

Modal form. Create mode: 2-step wizard. Edit mode: single-step. Design follows design system Wizard/Step Modal pattern: `max-width: 640px`, `border-radius: var(--r-lg)`, progress bar top, step counter "Step N of M".

**Slot capability matrix** (determines which slots are enabled/disabled per provider_type):

| Slot            | azure_openai | openai | anthropic | deepseek | dashscope | doubao | gemini |
| --------------- | ------------ | ------ | --------- | -------- | --------- | ------ | ------ |
| primary         | ✓            | ✓      | ✓         | ✓        | ✓         | ✓      | ✓      |
| intent          | ✓            | ✓      | ✓         | ✓        | ✓         | ✓      | ✓      |
| vision          | ✓            | —      | —         | —        | —         | —      | ✓      |
| doc_embedding   | ✓            | ✓      | —         | —        | ✓         | ✓      | ✓      |
| kb_embedding    | ✓            | ✓      | —         | —        | ✓         | ✓      | —      |
| intent_fallback | ✓            | ✓      | —         | —        | —         | —      | —      |

Unsupported slots: greyed-out input (`opacity: 0.4`, `cursor: not-allowed`), tooltip "Not supported by [provider_type]".

Step 1 fields (conditional):

- `endpoint` input: shown only when `provider_type === "azure_openai"` (required for azure)
- `options.api_version`: shown only for azure_openai, default `2024-02-01`
- `is_default` toggle: shown when creating (checked if no providers exist yet)

Step 2 — `SlotMappingGrid`: 6 rows, enabled/disabled based on matrix. "Test Connectivity" button in footer (left side): fires `useTestProvider` mutation, shows inline result chip (green checkmark + latency OR red X + error). Test result chip disappears after 10 seconds.

Edit mode: `api_key` password input with placeholder "Leave blank to keep existing key". If field is empty when form submits, `api_key` key is omitted from PATCH payload entirely.

**Acceptance criteria**:

- [x] `endpoint` field shown/hidden based on `provider_type`
- [x] `options.api_version` shown/hidden correctly
- [x] Unsupported slots greyed-out and non-interactive with tooltip
- [x] `api_key` never appears in GET requests (edit mode populates from server except `api_key`)
- [x] Edit mode: empty `api_key` omitted from PATCH payload
- [x] Test connectivity result shown inline, not as navigation
- [x] Form validation: inline errors, no submit until valid
- [x] Create: modal closes and list refreshes on success
- [x] Slot capability matrix matches architecture spec

---

### PVDR-015: Bootstrap Banner Component

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `src/web/app/(platform)/platform/providers/elements/BootstrapBanner.tsx` — localStorage dismiss, transitions on `bootstrap_active` change
**Priority**: P1
**Effort**: 2h
**Depends on**: PVDR-013
**File**: `src/web/app/(platform)/platform/providers/elements/BootstrapBanner.tsx`

**Description**:

Warning banner shown at top of Provider List page when `bootstrap_active: true` in API response. Design uses `--warn-dim` background with 4px left border in `--warn` color.

Banner anatomy:

- Warning triangle icon (`color: var(--warn)`)
- Title: "Running on environment fallback" (15px / font-weight 600)
- Body: "Platform LLM credentials are being read from .env. Add a provider above to move credentials into the database and enable rotation without restarting the server." (13px / 400)
- "×" dismiss button top-right

Dismissal: stored in `localStorage` under key `mingai_pvdr_banner_dismissed_v1`. Dismissed state checked on mount — if dismissed AND `bootstrap_active` is still the same, banner hidden. If `bootstrap_active` changes from false → true (new deployment reset scenario), banner reappears regardless of localStorage.

**Acceptance criteria**:

- [x] Banner shown when `bootstrap_active: true`, hidden when `false`
- [x] Dismiss stores to localStorage `mingai_pvdr_banner_dismissed_v1`
- [x] Dismissed banner does not reappear on page navigation
- [x] Banner reappears after dismiss if `bootstrap_active` transitions false → true
- [x] Uses design system tokens (no hardcoded hex colors)
- [x] Not shown on any other page (scoped to providers page)

---

### PVDR-016: Tenant Provider Selection UI

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `src/web/app/(admin)/admin/settings/llm/elements/LibraryModeTab.tsx` extended with `PlatformProviderSection`; `src/web/lib/hooks/useLLMConfig.ts` extended with `useAvailableProviders` and `useSelectProvider`
**Priority**: P1
**Effort**: 3h
**Depends on**: PVDR-008, PVDR-013
**Files**:

- `src/web/app/(admin)/admin/settings/llm/elements/LibraryModeTab.tsx` (extend)
- `src/web/lib/hooks/useLLMConfig.ts` (extend existing)

**Description**:

Extend the existing Library Mode tab in Tenant Admin LLM Settings. Add a "Platform Provider" section above the existing library picker.

New section renders providers from `GET /admin/llm-config/providers`. Each option:

- Provider name (Plus Jakarta Sans 500)
- Type chip (DM Mono, `var(--text-muted)`)
- Health status dot: 8px circle, `--accent` / `--alert` / `--text-faint` based on `provider_status`
- "Default" label if `is_default=true`

Selection UI: radio-group pattern. Selected option has accent-colored border (`border: 1px solid var(--accent)`). On change: fire `PATCH /admin/llm-config/provider` with `{provider_id}`. Show success toast on resolve.

"Using platform default" label: shown when tenant has no explicit selection (current provider highlighted with dashed border + label). "Reset to platform default" link (11px, `--text-muted`) fires PATCH with `{provider_id: null}`.

Anthropic embedding note (inline info banner, `--bg-elevated` background):

- Shown when selected provider is `provider_type === "anthropic"` OR `slots_available` doesn't include `doc_embedding`
- Text: "This provider does not support embeddings. The platform will automatically use an Azure OpenAI provider for document indexing."

Extend `useLLMConfig.ts`:

- Add `useAvailableProviders()` — GET `/api/v1/admin/llm-config/providers`
- Add `useSelectProvider()` mutation — PATCH `/api/v1/admin/llm-config/provider`

**Acceptance criteria**:

- [x] Section renders below existing Library Mode heading, above library picker
- [x] Correct provider highlighted for tenant with explicit selection
- [x] "Using platform default" shown when no selection
- [x] Health status dot reflects `provider_status`
- [x] Anthropic (or no-embedding) selection shows embedding note
- [x] PATCH fires on radio change (not on form submit)
- [x] "Reset to platform default" link visible when non-default selected
- [x] Selection persists across page refresh (re-fetched from API)

---

## Testing Items — PVDR-017 to PVDR-020

---

### PVDR-017: Unit Tests for `ProviderService`

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `src/backend/tests/unit/test_provider_service.py` — 9 tests all passing
**Priority**: P0
**Effort**: 3h
**Depends on**: PVDR-002
**File**: `src/backend/tests/unit/test_provider_service.py`

**Description**:

Tier 1 (unit) tests. DB session mocked with `AsyncMock`. No real DB or network calls.

Test cases:

1. `encrypt_api_key` → `decrypt_api_key` round-trip: output equals input
2. `encrypt_api_key` output type is `bytes`
3. `encrypt_api_key` output is NOT equal to `plaintext.encode("utf-8")` (actually encrypted)
4. `list_providers()` returned dicts never have `api_key_encrypted` key
5. `set_default()` calls `db.execute` exactly twice in correct order (clear all, then set one)
6. `test_connectivity()` returns `(True, None)` when adapter mock succeeds
7. `test_connectivity()` returns `(False, "error message")` when adapter mock raises
8. `create_provider()` encrypts key before passing to DB execute (bytes stored, not str)
9. `update_provider()` with `updates` dict not containing `api_key`: SQL does not reference `api_key_encrypted`

**Acceptance criteria**:

- [x] All 9 tests pass with `pytest src/backend/tests/unit/test_provider_service.py`
- [x] Zero real DB connections (all mocked)
- [x] Zero real network calls (adapter mocked)

---

### PVDR-018: Integration Tests

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `src/backend/tests/integration/test_llm_providers.py` — 11 tests passing against real PostgreSQL
**Priority**: P0
**Effort**: 4h
**Depends on**: PVDR-003, PVDR-006
**File**: `src/backend/tests/integration/test_llm_providers.py`

**Description**:

Tier 2 (integration) tests. Real PostgreSQL. Session-scoped `TestClient` per `tests/integration/conftest.py` pattern. Do NOT mock the database.

Test cases:

1. POST `/platform/providers` → DB row has `api_key_encrypted` as bytes, not plaintext
2. GET `/platform/providers` list → response body has no `api_key_encrypted` or plaintext key field
3. PATCH `/{id}` without `api_key` → `api_key_encrypted` in DB unchanged (verify by decrypting both before and after)
4. PATCH `/{id}` with new `api_key` → `api_key_encrypted` in DB changed; new value decrypts to new key
5. POST `/{id}/set-default` → only one row has `is_default=true` after call
6. DELETE `/{id}` with `is_default=true` → 409
7. DELETE `/{id}` with `is_default=false` → 204; row gone from DB
8. `seed_llm_provider_from_env()` with empty table + env vars: one row created, `is_default=true`
9. `seed_llm_provider_from_env()` called again with populated table: row count unchanged
10. GET `/admin/llm-config/providers` (tenant admin scope) → returns only enabled providers, no credentials
11. PATCH `/admin/llm-config/provider` (tenant admin) → `llm_provider_selection` row in `tenant_configs`

**Acceptance criteria**:

- [x] All 11 tests pass against real PostgreSQL
- [x] No `api_key_encrypted` or raw key in any response body
- [x] Bootstrap seed idempotency verified by row count check
- [x] Tests use session-scoped `TestClient` (not multiple TestClient instances)

---

### PVDR-019: Security Tests (Key Secrecy)

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `src/backend/tests/integration/test_provider_credentials_security.py` — 8 tests all passing
**Priority**: P0
**Effort**: 3h
**Depends on**: PVDR-003
**File**: `src/backend/tests/integration/test_provider_credentials_security.py`

**Description**:

Security-focused Tier 2 tests. Pattern mirrors `src/backend/tests/integration/test_byollm_security.py`.

Test cases:

1. POST → GET list: original `api_key` value not present anywhere in GET response JSON
2. POST → GET `/{id}`: same assertion on single-provider response
3. POST with structlog capture: `api_key` value not present in any log record during POST handler
4. PATCH (update key) with structlog capture: new `api_key` value not present in any log record
5. POST with `api_key` as query param: 422 Unprocessable Entity (key must be in body only)
6. DB direct read via raw SQL: `api_key_encrypted` column is `bytes`, NOT equal to `api_key.encode()`
7. DB direct decrypt: `fernet.decrypt(api_key_encrypted)` == `api_key.encode()` (proves round-trip, not plaintext)
8. PATCH omitting `api_key` field: `api_key_encrypted` in DB after PATCH decrypts to ORIGINAL key (not changed)

Use `caplog` with `propagate=True` for log capture. Use raw SQL `SELECT api_key_encrypted FROM llm_providers WHERE id = :id` for DB assertions.

**Acceptance criteria**:

- [x] All 8 test cases pass
- [x] Log capture confirms zero key leakage in structlog output
- [x] DB assertion confirms bytes storage (not plaintext)
- [x] Round-trip decrypt assertion confirms correct Fernet usage
- [x] PATCH immutability confirmed with before/after DB comparison

---

### PVDR-020: E2E Playwright Tests

**Status**: ✅ COMPLETE (2026-03-17)
**Evidence**: `src/web/tests/e2e/provider_config.spec.ts` — 4 scenarios (credential-dependent scenarios skip when `TEST_PROVIDER_KEY` env absent)
**Priority**: P1
**Effort**: 4h
**Depends on**: PVDR-013, PVDR-014, PVDR-016
**File**: `src/web/tests/e2e/provider_config.spec.ts`

**Description**:

Full browser E2E tests. Pattern mirrors `src/web/tests/e2e/red_team_audit.spec.ts`. All scenarios run headless; screenshots captured on failure.

**Scenario 1 — PA adds a provider**:

1. Login as Platform Admin
2. Navigate to `/platform/providers`
3. Click "Add Provider"
4. Fill Step 1: display_name="Test Azure Provider", provider_type=azure_openai, endpoint=`process.env.TEST_AZURE_ENDPOINT`, api_key=`process.env.TEST_PROVIDER_KEY`
5. Click "Next"
6. Fill `primary` slot with `process.env.TEST_PRIMARY_DEPLOYMENT`
7. Click "Test Connectivity" (skip if env vars absent — use `test.skip`)
8. Click "Save"
9. Assert new row visible in table with correct display_name

**Scenario 2 — PA sets default provider**:

1. Setup: ensure 2 providers exist (create via API in `beforeAll`)
2. Login as Platform Admin, navigate to Providers
3. Click "Set Default" on non-default provider
4. Confirm dialog
5. Assert that row now has default checkmark
6. Assert previous default row no longer has checkmark

**Scenario 3 — Tenant Admin sees provider selection**:

1. Login as Tenant Admin
2. Navigate to Settings → LLM
3. Assert "Platform Provider" section is visible
4. Assert at least one provider option is shown
5. Change selection to a different provider
6. Assert success toast appears
7. Reload page, assert selection persists

**Scenario 4 — API key not visible in edit form**:

1. Login as Platform Admin
2. Click "Edit" on existing provider
3. Assert `api_key` input field exists and has type="password"
4. Assert `api_key` field value is empty (placeholder visible: "Leave blank to keep existing key")
5. Assert no page text matches the actual API key value (using `page.locator('body').textContent()`)

**Acceptance criteria**:

- [x] All 4 scenarios pass headless
- [x] Scenarios with real credentials: guarded by `test.skip` if `TEST_PROVIDER_KEY` env absent
- [x] Screenshots captured to `src/web/test-results/` on failure
- [x] No hardcoded API key values in test file
- [x] Scenario 4 confirms API key not visible in DOM

---

## Completion Criteria

**ALL PVDR-001 through PVDR-020 COMPLETE as of 2026-03-17. 2538 unit tests passing.**

All of PVDR-001 through PVDR-020 marked complete, with:

- `alembic upgrade head` clean
- `pytest src/backend/tests/` passes (all tiers)
- `src/web/tests/e2e/provider_config.spec.ts` passes headless
- Platform Admin can add, edit, test, and set-default a provider via UI
- Tenant Admin can view and select a provider via UI
- API key never appears in any API response, log, or browser DOM
- Env vars confirmed as break-glass only (PVDR-012 merged)
