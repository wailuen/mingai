# 01 — Phase 2: LLM Library & Multi-Provider Abstraction

**Generated**: 2026-03-15
**Phase**: 2 (Weeks 9-12 of implementation roadmap)
**Numbering**: P2LLM-001 through P2LLM-019
**Stack**: FastAPI + Kailash DataFlow + PostgreSQL + Redis + Azure OpenAI + OpenAI Direct
**Source plan**: `workspaces/mingai/02-plans/01-implementation-roadmap.md` Phase 2

---

## Overview

Phase 2 delivers the LLM abstraction layer that decouples the RAG pipeline from any single LLM provider. Platform admin manages a model catalog (LLM Library). Tenant admins select from published profiles or bring their own LLM credentials (Enterprise tier). All token usage flows into a cost tracking table for billing reconciliation and gross margin calculation.

**Critical path**: P2LLM-004 (table) → P2LLM-005 (platform API) → P2LLM-006 (tenant API) → P2LLM-008 (config migration) → P2LLM-009 (instrumented client) → P2LLM-010 (usage_events) → P2LLM-012 (cost API)

---

## Backend Items

### P2LLM-001: LLMProvider abstract interface

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: none
**Description**: Define `LLMProvider` abstract base class in `app/core/llm/base.py`. Method signature: `async def complete(messages: list[dict], model: str, **kwargs) -> CompletionResponse`. `CompletionResponse` dataclass: `content: str`, `tokens_in: int`, `tokens_out: int`, `model: str`, `provider: str`, `latency_ms: int`. Also define `EmbeddingProvider` ABC with `async def embed(texts: list[str], model: str) -> list[list[float]]`.
**Acceptance criteria**:

- [ ] `LLMProvider` ABC defined in `app/core/llm/base.py`
- [ ] `CompletionResponse` dataclass with all required fields
- [ ] `EmbeddingProvider` ABC defined
- [ ] Both ABCs have `__abstractmethods__` enforced — cannot be instantiated directly
- [ ] Module exports cleanly from `app/core/llm/__init__.py`
- [ ] No hardcoded model names anywhere in the interface definition

---

### P2LLM-002: Azure OpenAI adapter

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P2LLM-001
**Description**: Wrap existing Azure OpenAI integration (currently scattered across `app/core/llm_client.py` and `app/modules/ai/embedding_service.py`) behind the `LLMProvider` interface. New file: `app/core/llm/azure_openai.py`. Reads credentials from `.env` (`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`). Supports both chat completion and embedding endpoints.
**Acceptance criteria**:

- [ ] `AzureOpenAIProvider` class in `app/core/llm/azure_openai.py` implements `LLMProvider`
- [ ] `AzureOpenAIEmbeddingProvider` implements `EmbeddingProvider`
- [ ] Both read credentials from env vars, never hardcoded
- [ ] `CompletionResponse` fields populated from Azure API response (including token counts)
- [ ] Existing `llm_client.py` usages updated to delegate to this adapter
- [ ] Unit tests pass (see P2LLM-016)

---

### P2LLM-003: OpenAI Direct adapter

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P2LLM-001
**Description**: New adapter for direct OpenAI API access (non-Azure). `app/core/llm/openai_direct.py`. Accepts API key from env (`OPENAI_API_KEY`) or from tenant BYOLLM config (P2LLM-007). Supports chat completions and embeddings via `openai` Python package.
**Acceptance criteria**:

- [ ] `OpenAIDirectProvider` implements `LLMProvider`
- [ ] `OpenAIDirectEmbeddingProvider` implements `EmbeddingProvider`
- [ ] Can accept API key at construction time (for BYOLLM) or from env (for default)
- [ ] API key never logged or included in error messages
- [ ] Same `CompletionResponse` shape as Azure adapter
- [ ] Unit tests pass (see P2LLM-016)

---

### P2LLM-004: `llm_library` PostgreSQL table

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: none
**Description**: Alembic migration for `llm_library` table. Platform-managed model catalog. Columns: `id` UUID PK, `provider` VARCHAR (azure_openai|openai_direct|anthropic), `model_name` VARCHAR, `display_name` VARCHAR, `plan_tier` VARCHAR (starter|professional|enterprise), `is_recommended` BOOLEAN, `status` VARCHAR CHECK(Draft|Published|Deprecated), `best_practices_md` TEXT, `pricing_per_1k_tokens_in` NUMERIC(10,6), `pricing_per_1k_tokens_out` NUMERIC(10,6), `created_at` TIMESTAMPTZ, `updated_at` TIMESTAMPTZ. RLS: platform admin full access; tenant admin read Published only.
**Acceptance criteria**:

- [ ] Alembic migration file created (v009 or next available)
- [ ] All columns as specified with correct types and constraints
- [ ] `status` CHECK constraint enforces Draft|Published|Deprecated only
- [ ] RLS policy: `platform_admin` role can SELECT/INSERT/UPDATE/DELETE
- [ ] RLS policy: `tenant` role can SELECT WHERE status = 'Published'
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Migration applies cleanly: `alembic upgrade head` with no errors
- [ ] Migration is reversible: `alembic downgrade -1` removes table cleanly

---

### P2LLM-005: Platform LLM Library API

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: P2LLM-004
**Description**: CRUD endpoints for platform admin to manage the model catalog. Module: `app/modules/platform/llm_library/routes.py`. Endpoints: `POST /platform/llm-library` (create in Draft), `GET /platform/llm-library` (list all with status filter), `GET /platform/llm-library/{id}` (detail), `PATCH /platform/llm-library/{id}` (update; Published → Deprecated allowed; Draft → Published allowed; Deprecated → any BLOCKED), `POST /platform/llm-library/{id}/publish` (Draft → Published lifecycle action), `POST /platform/llm-library/{id}/deprecate` (Published → Deprecated).
**Acceptance criteria**:

- [ ] All 6 endpoints implemented and registered in `main.py`
- [ ] `require_platform_admin` dependency on all routes
- [ ] Draft→Published transition: validates `model_name`, `provider`, `pricing_per_1k_tokens_*` non-null
- [ ] Published→Deprecated transition: succeeds even if tenants are assigned (preserves existing assignments)
- [ ] Deprecated→any: returns 409 with clear error message
- [ ] `GET /platform/llm-library` supports `?status=` filter
- [ ] Response schema does NOT include internal IDs for BYOLLM key refs
- [ ] Integration tests with real PostgreSQL (DataFlow model or raw asyncpg)

---

### P2LLM-006: Tenant LLM Setup API

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: P2LLM-004, P2LLM-005
**Description**: Endpoints for tenant admin to configure their active LLM. `GET /admin/llm-config` returns current config. `PATCH /admin/llm-config` accepts `{ "model_source": "library"|"byollm", "llm_library_id": UUID (if library) }`. Only one active config per tenant (upsert pattern). BYOLLM config handled by P2LLM-007.
**Acceptance criteria**:

- [ ] `GET /admin/llm-config` returns current model_source, active profile details, BYOLLM status (key present: true/false — never the key itself)
- [ ] `PATCH /admin/llm-config` with `model_source=library` validates the referenced `llm_library_id` is Published
- [ ] `PATCH /admin/llm-config` with `model_source=byollm` requires Enterprise plan tier (403 for Starter/Professional)
- [ ] Config stored in `tenant_configs` JSONB under `llm_config` key
- [ ] Config change triggers Redis cache invalidation for that tenant (DEL `mingai:{tenant_id}:config`)
- [ ] `require_tenant_admin` dependency on both routes

---

### P2LLM-007: BYOLLM support

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: P2LLM-006
**Description**: Enterprise-only feature. Tenant admin POSTs their own API key. Key stored AES-256 encrypted using vault ref pattern (matching existing SharePoint credential pattern in `app/modules/documents/sharepoint/credentials.py`). `PATCH /admin/llm-config/byollm` accepts `{ "provider": "openai_direct"|"azure_openai", "api_key": "sk-...", "endpoint": "optional" }`. Key ref stored in `tenant_configs`; plaintext key NEVER persisted or returned.
**Acceptance criteria**:

- [ ] Endpoint gated behind Enterprise plan check (403 for non-Enterprise)
- [ ] API key encrypted before storage using same AES-256 pattern as SharePoint credentials
- [ ] Vault ref string (not plaintext key) stored in `tenant_configs`
- [ ] `GET /admin/llm-config` returns `{ "byollm": { "provider": "...", "key_present": true } }` — no key value
- [ ] `DELETE /admin/llm-config/byollm` removes key ref and reverts to library mode
- [ ] Security test: grep for plaintext key in DB after insertion confirms zero matches (see P2LLM-017)
- [ ] Integration test: full BYOLLM round-trip with real PostgreSQL

---

### P2LLM-008: Tenant config migration to PostgreSQL

**Status**: ⬜ TODO
**Effort**: 10h
**Depends on**: P2LLM-004, P2LLM-006
**Description**: Replace `@lru_cache` Settings singleton (currently `app/core/config.py`) with a tiered read path: Redis (15-min TTL) → PostgreSQL `tenant_configs` → env fallback. New service: `app/core/tenant_config_service.py`. Write path: update PostgreSQL → DEL Redis key. All modules that currently import `settings.SOME_MODEL` must be updated to call `await tenant_config_service.get(tenant_id, "llm_config")`.
**Acceptance criteria**:

- [ ] `TenantConfigService.get(tenant_id, key)` implements Redis → PostgreSQL → env fallback chain
- [ ] `TenantConfigService.set(tenant_id, key, value)` writes to PostgreSQL then DELs Redis key
- [ ] Redis TTL: 900 seconds (15 min) on cache hits
- [ ] Env fallback reads from `os.environ` (not hardcoded defaults)
- [ ] All callers of `settings.INTENT_MODEL`, `settings.PRIMARY_MODEL`, `settings.EMBEDDING_MODEL` migrated
- [ ] `@lru_cache` Settings singleton removed or scoped to non-tenant-specific values only
- [ ] Integration test: real Redis + PostgreSQL; verify cache hit, cache miss, env fallback paths
- [ ] No circular import introduced between `tenant_config_service` and other core modules

---

### P2LLM-009: Instrumented LLM client

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: P2LLM-001, P2LLM-002, P2LLM-003, P2LLM-008
**Description**: Platform-level wrapper `app/core/llm/instrumented_client.py`. At request time: reads tenant's `model_source` from `TenantConfigService`, selects appropriate adapter (library → AzureOpenAI or OpenAIDirectProvider; BYOLLM → OpenAIDirectProvider with decrypted key), executes completion, logs to `usage_events` (P2LLM-010). All RAG pipeline code uses `InstrumentedLLMClient` — never a raw adapter directly.
**Acceptance criteria**:

- [ ] `InstrumentedLLMClient.complete(tenant_id, messages, **kwargs)` resolves adapter from config at call time
- [ ] `InstrumentedLLMClient.embed(tenant_id, texts, **kwargs)` same pattern for embeddings
- [ ] After every call: async fire-and-forget write to `usage_events` table (non-blocking)
- [ ] `model_source` field in usage_events set correctly (library|byollm)
- [ ] Decrypted BYOLLM key used in-memory only, never written to any log or DB column
- [ ] Chat pipeline (`app/modules/chat/pipeline.py`) updated to use `InstrumentedLLMClient`
- [ ] Embedding service updated to use `InstrumentedLLMClient`
- [ ] Latency (ms) captured and stored in usage_events

---

### P2LLM-010: `usage_events` PostgreSQL table

**Status**: ⬜ TODO
**Effort**: 3h
**Depends on**: P2LLM-004
**Description**: Alembic migration for `usage_events` table. Columns: `id` UUID PK, `tenant_id` UUID FK (tenants.id), `user_id` UUID FK nullable, `conversation_id` UUID FK nullable, `provider` VARCHAR, `model` VARCHAR, `tokens_in` INTEGER, `tokens_out` INTEGER, `model_source` VARCHAR CHECK(library|byollm), `cost_usd` NUMERIC(10,8), `latency_ms` INTEGER, `created_at` TIMESTAMPTZ. Partitioned by month via `created_at`. RLS: tenant sees own rows; platform admin sees all.
**Acceptance criteria**:

- [ ] Alembic migration file created (next available version after P2LLM-004)
- [ ] All columns with correct types and CHECK constraints
- [ ] `model_source` CHECK constraint enforces library|byollm
- [ ] RLS policy consistent with tenant isolation pattern from v002
- [ ] Index on `(tenant_id, created_at DESC)` for cost analytics queries
- [ ] Index on `(tenant_id, model, created_at)` for model breakdown queries
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Migration is reversible

---

### P2LLM-011: Cost tracking per tenant

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P2LLM-009, P2LLM-010
**Description**: Every LLM call via `InstrumentedLLMClient` calculates `cost_usd` from model pricing constants. Pricing loaded from `llm_library` table (per-token rates). For BYOLLM models not in the library, use env var pricing constants (`BYOLLM_COST_PER_1K_IN_USD`, `BYOLLM_COST_PER_1K_OUT_USD`). Cost calculation: `(tokens_in / 1000 * price_in) + (tokens_out / 1000 * price_out)`.
**Acceptance criteria**:

- [ ] `cost_usd` populated on every `usage_events` row
- [ ] Pricing loaded from `llm_library.pricing_per_1k_tokens_*` for library models
- [ ] BYOLLM fallback to env var pricing (with 0.0 as default if env var absent)
- [ ] Cost calculation within 1% of expected value (see P2LLM-018)
- [ ] Pricing lookup cached in Redis to avoid DB hit on every LLM call (TTL: 3600s)
- [ ] If pricing lookup fails, usage_events row still written with `cost_usd = null` (non-blocking)

---

### P2LLM-012: Cost analytics API

**Status**: ⬜ TODO
**Effort**: 5h
**Depends on**: P2LLM-010, P2LLM-011
**Description**: `GET /platform/tenants/{id}/cost-usage`. Query params: `period` (7d|30d|90d|custom), `from` and `to` dates. Response: total tokens, total cost_usd, breakdown by model, breakdown by day. Also: `GET /platform/cost-analytics/summary` for cross-tenant aggregate. Both require `require_platform_admin`.
**Acceptance criteria**:

- [ ] `GET /platform/tenants/{id}/cost-usage` returns correct aggregation from `usage_events` table
- [ ] Period filter works for all supported values
- [ ] Model breakdown groups by `(provider, model)` pair
- [ ] Daily breakdown returns one row per calendar day (UTC) within period
- [ ] `GET /platform/cost-analytics/summary` returns totals across all tenants, sorted by cost_usd DESC
- [ ] Both endpoints require platform_admin scope
- [ ] Response time < 2s for 90-day query (index-backed aggregation)

---

## Frontend Items

### P2LLM-013: Platform LLM Library management UI

**Status**: ⬜ TODO
**Effort**: 12h
**Depends on**: P2LLM-005
**Description**: New screen at `app/(platform)/platform/llm-library/`. Components: `LibraryList` (table of models with status badges, plan tier chips), `ProfileForm` (provider selector, model name, plan tier, pricing fields, best-practices markdown editor), `PublishLifecycleActions` (Draft→Publish, Publish→Deprecate buttons with confirmation dialogs). Follows Obsidian Intelligence design system: `--bg-surface` cards, DM Mono for pricing values, `--accent` for Published status, `--warn` for Draft, `--text-faint` for Deprecated.
**Acceptance criteria**:

- [ ] `LibraryList` table shows all models with sortable status column
- [ ] `ProfileForm` validates all required fields before enabling Publish action
- [ ] Markdown editor for `best_practices_md` with preview toggle
- [ ] Plan tier selector uses outlined chip components (not filled at idle)
- [ ] Confirmation dialog before Deprecate (lists tenants currently using this profile)
- [ ] 0 TypeScript errors (`npm run typecheck`)
- [ ] Matches Obsidian Intelligence design: no purple/blue, no glassmorphism, DM Mono for numbers

---

### P2LLM-014: Tenant LLM Setup UI

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: P2LLM-006, P2LLM-007
**Description**: New settings tab at `app/(admin)/admin/settings/llm/`. Two modes: Library mode (dropdown of Published profiles with descriptions — not raw model names) and BYOLLM mode (Enterprise gated — shows upgrade prompt for non-Enterprise; shows key entry form for Enterprise). Active config displayed as read-only summary. Change confirmation dialog showing cost implications.
**Acceptance criteria**:

- [ ] Library mode: shows profile display_name + best_practices_md snippet, not raw model_name
- [ ] BYOLLM tab: gated behind plan tier check; non-Enterprise sees upgrade CTA, not a broken form
- [ ] API key input: `type="password"` with show/hide toggle; never echoed after save
- [ ] After save: page re-fetches config and shows `key_present: true` indicator only
- [ ] Change confirmation dialog appears before PATCH request fires
- [ ] 0 TypeScript errors
- [ ] Responsive at 1280px+ (admin console breakpoint)

---

### P2LLM-015: Cost analytics enhancement

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: P2LLM-012
**Description**: Extend existing cost analytics dashboard (Platform Admin → Finance → Cost Analytics) with model breakdown chart and usage_events-backed data. New sub-panel: `ModelBreakdownTable` (model name, tokens in, tokens out, cost_usd per model). Replace any mock/static data with real `GET /platform/tenants/{id}/cost-usage` calls. Add period selector (7d/30d/90d).
**Acceptance criteria**:

- [ ] `ModelBreakdownTable` wired to real API data
- [ ] Period selector changes API query param and re-fetches
- [ ] Cost values in DM Mono font
- [ ] Loading skeleton shown during fetch (no layout shift)
- [ ] Empty state when no usage_events in period
- [ ] 0 TypeScript errors

---

## Testing Items

### P2LLM-016: LLMProvider abstraction unit tests

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P2LLM-001, P2LLM-002, P2LLM-003
**Description**: Unit test suite in `tests/unit/test_llm_providers.py`. Both adapters (Azure, OpenAI Direct) must pass identical test suite via parametrize. Tests: interface compliance, `CompletionResponse` field completeness, API key not in repr/str of adapter, error handling for invalid model name.
**Acceptance criteria**:

- [ ] Both adapters parametrized against same test suite — no adapter-specific test branching
- [ ] `isinstance(adapter, LLMProvider)` passes for both
- [ ] API key not present in `repr(adapter)` or any exception message
- [ ] Mock network calls (Tier 1 — no real API calls in unit tests)
- [ ] All tests pass: `pytest tests/unit/test_llm_providers.py`

---

### P2LLM-017: BYOLLM key storage security tests

**Status**: ⬜ TODO
**Effort**: 3h
**Depends on**: P2LLM-007
**Description**: Security-focused integration tests in `tests/integration/test_byollm_security.py`. Tier 2 — real PostgreSQL. Tests: (1) plaintext key never in any DB column after storage, (2) API response never contains plaintext key, (3) only vault ref stored in `tenant_configs`, (4) DELETE removes all key material, (5) non-Enterprise tenant receives 403.
**Acceptance criteria**:

- [ ] All 5 security scenarios covered
- [ ] Test executes actual DB query after API call and asserts no plaintext key present
- [ ] Tests use real PostgreSQL (not mock)
- [ ] All tests pass: `pytest tests/integration/test_byollm_security.py`

---

### P2LLM-018: Cost tracking accuracy integration tests

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P2LLM-009, P2LLM-010, P2LLM-011
**Description**: Integration tests in `tests/integration/test_cost_tracking.py`. Tier 2 — real PostgreSQL. Tests: token count in usage_events matches actual LLM response token count (use known-size fixture response), cost_usd calculation within 1% of expected formula result, model_source field set correctly for library vs BYOLLM calls.
**Acceptance criteria**:

- [ ] Token count assertion: `abs(recorded_tokens - actual_tokens) <= 1` (off-by-one tolerance for tokenizer variance)
- [ ] Cost calculation assertion: within 1% of `(tokens_in/1000 * price_in) + (tokens_out/1000 * price_out)`
- [ ] `model_source` correctly set to "library" or "byollm"
- [ ] Tests use real PostgreSQL
- [ ] All tests pass

---

### P2LLM-019: Config cache TTL integration tests

**Status**: ⬜ TODO
**Effort**: 3h
**Depends on**: P2LLM-008
**Description**: Integration tests in `tests/integration/test_tenant_config_cache.py`. Tier 2 — real Redis. Tests: (1) cache populated on first read, (2) subsequent read serves from Redis (no DB hit), (3) PATCH config triggers DEL on Redis key, (4) next read after DEL re-fetches from PostgreSQL, (5) env fallback when key absent from both Redis and PostgreSQL.
**Acceptance criteria**:

- [ ] All 5 cache scenarios covered with real Redis
- [ ] DB hit verified via query counter or mock assertion on DB session
- [ ] TTL verified: `redis.ttl(key) <= 900` after cache population
- [ ] All tests pass: `pytest tests/integration/test_tenant_config_cache.py`

---

### P2LLM-020: E2E test suite — LLM Library flows

**Status**: ⬜ TODO
**Priority**: HIGH — Revenue-critical BYOLLM feature
**Effort**: 6h
**Depends on**: P2LLM-013, P2LLM-014 (frontend complete)
**Description**: Playwright E2E tests for LLM Library flows. File: `tests/e2e/test_llm_library.spec.ts`.
**Acceptance criteria**:

- [ ] Platform admin creates a new LLM profile (Draft → Published lifecycle via UI)
- [ ] Platform admin runs test harness on draft profile (3 queries; results visible in panel)
- [ ] Tenant admin selects published profile from library (library mode)
- [ ] Tenant admin enters BYOLLM key — Enterprise tenant sees key form; non-Enterprise sees upgrade CTA (not a broken form)
- [ ] BYOLLM key is never returned in any API response (assert network response bodies contain no `api_key` value)
- [ ] Config change reflected in next chat request (within 15 minutes — test with TTL bypass or cache DEL)
- [ ] Tests: minimum 8 tests covering all 5 flows above
- [ ] Tests pass: `playwright test tests/e2e/test_llm_library.spec.ts`

---

## Dependencies Map

```
P2LLM-001 (ABC)
  ├── P2LLM-002 (Azure adapter)
  ├── P2LLM-003 (OpenAI Direct adapter)
  └── P2LLM-016 (unit tests)

P2LLM-004 (llm_library table)
  ├── P2LLM-005 (platform API)
  │     └── P2LLM-013 (platform UI)
  ├── P2LLM-006 (tenant API)
  │     ├── P2LLM-007 (BYOLLM)
  │     │     ├── P2LLM-014 (tenant UI)
  │     │     └── P2LLM-017 (security tests)
  │     └── P2LLM-008 (config migration)
  │           └── P2LLM-019 (cache TTL tests)
  └── P2LLM-010 (usage_events table)
        ├── P2LLM-011 (cost tracking)
        │     └── P2LLM-018 (accuracy tests)
        └── P2LLM-012 (cost API)
              └── P2LLM-015 (cost UI)

P2LLM-009 (instrumented client)
  Depends on: P2LLM-001, P2LLM-002, P2LLM-003, P2LLM-008
  Feeds: P2LLM-011
```

---

## Notes

- `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` already in `.env` — do not add new env vars for Azure adapter
- BYOLLM vault pattern must match `app/modules/documents/sharepoint/credentials.py` exactly — do not invent a new encryption scheme
- `usage_events` table is the source of truth for PA-012 (gross margin) and PA-013 (cost monitoring) in Phase B
- All new Alembic migrations must increment version tag sequentially after v008 (last confirmed migration)
