# 08 — LLM Provider Credentials Management

**Generated**: 2026-03-17
**Moved to completed**: 2026-03-17
**Phase**: New feature — Platform LLM Provider Credentials Management
**Numbering**: PVDR-001 through PVDR-020
**Stack**: PostgreSQL + FastAPI + Next.js + Fernet encryption
**Related plan**: `workspaces/mingai/02-plans/11-llm-provider-config-plan.md`
**Related flows**: `workspaces/mingai/03-user-flows/21-llm-provider-config-flows.md`

**Archive note**: ALL PVDR-001 through PVDR-020 COMPLETE as of 2026-03-17. 2538 unit tests passing. No remaining work.

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
**Effort**: 8h
**Depends on**: PVDR-002

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
**Depends on**: PVDR-004, PVDR-005, PVDR-006, PVDR-018

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
