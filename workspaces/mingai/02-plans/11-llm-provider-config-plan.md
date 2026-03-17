# 11 — LLM Provider Credentials Management — Implementation Plan

**Generated**: 2026-03-17
**Feature**: Platform LLM Provider Credentials Management (PVDR)
**Numbering**: PVDR-001 through PVDR-020
**Stack**: PostgreSQL + FastAPI + Next.js + Fernet encryption
**Related flows**: `03-user-flows/21-llm-provider-config-flows.md`
**Related todos**: `todos/active/08-llm-provider-config.md`

---

## Executive Summary

Move LLM provider credentials from `.env` hardcoding into a `llm_providers` PostgreSQL table managed via Platform Admin UI. The `InstrumentedLLMClient` currently reads `PRIMARY_MODEL`, `EMBEDDING_MODEL`, and `INTENT_MODEL` directly from environment variables. After this feature, it reads from the database, finds the default provider row, decrypts the API key in-memory, and constructs the adapter dynamically.

Env vars remain as break-glass emergency fallback only: if the table has zero rows at startup, credentials are auto-seeded from env into the first `llm_providers` row.

**Seven supported provider types**: azure_openai, openai, anthropic, deepseek, dashscope, doubao, gemini.

**Six deployment slots**: primary, intent, vision, doc_embedding, kb_embedding, intent_fallback.

---

## Critical Path

```
PVDR-001 (migration)
    └─> PVDR-002 (ProviderService)
            ├─> PVDR-003 (Platform Provider API)
            ├─> PVDR-004 (_resolve_library_adapter migration)
            │       └─> PVDR-005 (embed() migration)
            │       └─> PVDR-009 (tenant selection adapter)
            │               └─> PVDR-010 (Anthropic embedding fallback)
            ├─> PVDR-006 (bootstrap auto-seed)
            ├─> PVDR-007 (health check job)
            └─> PVDR-008 (tenant provider selection API)
                    └─> PVDR-016 (Tenant Provider Selection UI)
PVDR-003 ──> PVDR-013 (Provider List screen)
                 └─> PVDR-014 (Provider Form + test button)
                         └─> PVDR-015 (Bootstrap banner)
PVDR-002 ──> PVDR-017 (unit tests)
PVDR-003 ──> PVDR-018 (integration tests)
PVDR-019 (security tests) — parallel with PVDR-017/018
PVDR-020 (E2E) — after PVDR-013/014/016 complete
PVDR-012 (remove env var requirements) — LAST, after all DB paths confirmed green
```

---

## Phase Overview

### Phase A — Data Layer (PVDR-001, PVDR-002)

Establish the `llm_providers` table and `ProviderService` class. All other backend work depends on this.

**Duration**: 1 day
**Risk**: Low — additive migration, no existing table changed.

### Phase B — Backend API + Client Migration (PVDR-003 to PVDR-011)

Platform and tenant APIs. Migrate `InstrumentedLLMClient` to read from DB. Bootstrap auto-seed. Health check job.

**Duration**: 3 days
**Risk**: Medium — `InstrumentedLLMClient` is on the critical path for every chat request. Must keep env fallback working until Phase C is validated.

### Phase C — Frontend (PVDR-013 to PVDR-016)

Provider list, form, bootstrap banner, tenant selection extension.

**Duration**: 2 days
**Risk**: Low — new UI pages, no existing page destructively modified.

### Phase D — Testing + Cleanup (PVDR-017 to PVDR-020, PVDR-012)

Unit, integration, security, E2E tests. Remove env var hard requirements last.

**Duration**: 2 days
**Risk**: Low if Phase B passes integration tests cleanly.

---

## Backend Items

### PVDR-001 — `llm_providers` Alembic Migration

**File**: `src/backend/alembic/versions/v037_llm_providers.py`
**Effort**: 3h
**Depends on**: None (additive)
**Priority**: P0

Create `llm_providers` table with all columns as specified in the architecture design. Key details:

- `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
- `provider_type VARCHAR(50) NOT NULL` with CHECK constraint: azure_openai, openai, anthropic, deepseek, dashscope, doubao, gemini
- `api_key_encrypted BYTEA NOT NULL` — Fernet token stored as bytea
- `models JSONB NOT NULL DEFAULT '{}'` — slot → deployment_name mapping
- `options JSONB NOT NULL DEFAULT '{}'` — api_version, reasoning_effort, extra options
- `pricing JSONB` — nullable, for optional override
- `is_enabled BOOLEAN NOT NULL DEFAULT true`
- `is_default BOOLEAN NOT NULL DEFAULT false`
- `provider_status VARCHAR(50) NOT NULL DEFAULT 'unchecked'` — unchecked | healthy | error
- `last_health_check_at TIMESTAMPTZ`, `health_error TEXT`
- `created_at`, `updated_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()
- `created_by UUID` — nullable FK to users.id

Partial unique index: `CREATE UNIQUE INDEX llm_providers_single_default ON llm_providers (is_default) WHERE is_default = true` — enforces single default row at DB level.

RLS: this is a platform-level table. Apply `platform_admin_bypass` policy only (no tenant isolation). RLS must be added in this migration file — do not rely on v002's frozen `_V001_TABLES`.

Migration must be reversible (`downgrade()` drops table and index).

**Acceptance criteria**:

- `alembic upgrade head` runs clean
- `alembic downgrade -1` removes table cleanly
- Partial unique index rejects second `is_default=true` row
- CHECK constraint rejects unknown `provider_type`
- BYTEA column accepts Fernet-encrypted bytes

---

### PVDR-002 — `ProviderService` Class

**File**: `src/backend/app/core/llm/provider_service.py`
**Effort**: 4h
**Depends on**: PVDR-001
**Priority**: P0

New service class encapsulating all `llm_providers` CRUD and crypto operations. Follows the same pattern as `TenantConfigService` in `app/core/tenant_config_service.py`.

Methods:

```python
class ProviderService:
    async def list_providers(
        self, db: AsyncSession, enabled_only: bool = False
    ) -> list[dict]: ...

    async def get_provider(
        self, db: AsyncSession, provider_id: str
    ) -> dict | None: ...

    async def get_default_provider(
        self, db: AsyncSession
    ) -> dict | None: ...

    async def create_provider(
        self, db: AsyncSession, payload: dict, created_by: str
    ) -> dict: ...

    async def update_provider(
        self, db: AsyncSession, provider_id: str, updates: dict
    ) -> dict | None: ...

    async def set_default(
        self, db: AsyncSession, provider_id: str
    ) -> None: ...

    async def delete_provider(
        self, db: AsyncSession, provider_id: str
    ) -> bool: ...

    def encrypt_api_key(self, plaintext_key: str) -> bytes: ...

    def decrypt_api_key(self, encrypted_bytes: bytes) -> str: ...

    async def test_connectivity(
        self, provider_row: dict
    ) -> tuple[bool, str | None]: ...
```

Encryption uses `get_fernet()` from `app/modules/har/crypto.py` — same pattern as BYOLLM in `app/modules/admin/byollm.py`:

```python
from app.modules.har.crypto import get_fernet

def encrypt_api_key(self, plaintext_key: str) -> bytes:
    fernet = get_fernet()
    return fernet.encrypt(plaintext_key.encode("utf-8"))

def decrypt_api_key(self, encrypted_bytes: bytes) -> str:
    fernet = get_fernet()
    return fernet.decrypt(encrypted_bytes).decode("utf-8")
```

`set_default()` must use a two-step atomic transaction: `UPDATE llm_providers SET is_default = false WHERE is_default = true`, then `UPDATE llm_providers SET is_default = true WHERE id = :id`. Single commit. The DB partial unique index is a safety net, not a substitute for the two-step update.

`test_connectivity()` decrypts the key, makes one real API call (a minimal `/models` list or 1-token completion), catches all exceptions, returns `(True, None)` on success or `(False, error_message)` on failure. Plaintext key is in local scope only — not stored on `self`.

`list_providers()` MUST NOT include `api_key_encrypted` in the returned dicts. Return `key_present: bool` derived from `api_key_encrypted IS NOT NULL` instead.

**Acceptance criteria**:

- Plaintext key never stored in DB or on `self` attributes
- `set_default()` single commit, no partial state
- `list_providers()` never returns `api_key_encrypted` field
- `test_connectivity()` works for azure_openai and openai provider types
- Unit tests cover encrypt → decrypt round-trip

---

### PVDR-003 — Platform Provider API

**File**: `src/backend/app/modules/platform/llm_providers/routes.py`
**Supporting**: `src/backend/app/modules/platform/llm_providers/__init__.py`
**Router registration**: add `include_router(llm_providers_router)` in `src/backend/app/api/router.py`
**Effort**: 5h
**Depends on**: PVDR-002
**Priority**: P0

New FastAPI router. All routes require `require_platform_admin`.

Prefix: `/platform/providers`

Endpoints:

| Method | Path                                   | Description                     |
| ------ | -------------------------------------- | ------------------------------- |
| GET    | `/platform/providers`                  | List all providers (no keys)    |
| GET    | `/platform/providers/{id}`             | Get provider detail (no key)    |
| POST   | `/platform/providers`                  | Create new provider             |
| PATCH  | `/platform/providers/{id}`             | Update provider (key optional)  |
| DELETE | `/platform/providers/{id}`             | Delete provider                 |
| POST   | `/platform/providers/{id}/test`        | Test connectivity               |
| POST   | `/platform/providers/{id}/set-default` | Set as platform default         |
| GET    | `/platform/providers/health-summary`   | Health summary for PA dashboard |

Request body for POST/PATCH uses a Pydantic model. `api_key` is a `str` field in the request — it is encrypted by `ProviderService.encrypt_api_key()` before any DB write. The raw `api_key` field must never appear in any log statement.

For PATCH: if `api_key` is omitted or `None`, do not overwrite the existing encrypted key. Only overwrite when explicitly supplied.

`CreateProviderRequest` validation:

- `provider_type` must be in `_VALID_PROVIDER_TYPES` frozenset
- `display_name` min 1 char, max 200
- `endpoint` required when `provider_type == "azure_openai"`
- `models` dict values must be non-empty strings
- `api_key` min 1 char

`DELETE` must reject if `is_default=true` — return 409 Conflict with message "Cannot delete the default provider. Set another provider as default first."

`DELETE` must reject if provider is the only enabled provider — return 409 Conflict.

`/health-summary` returns: `{total: int, healthy: int, error: int, unchecked: int, last_checked_at: str | null}`.

**Acceptance criteria**:

- GET list never returns `api_key_encrypted` field
- POST/PATCH test with raw key — DB stores only encrypted bytes
- DELETE default provider returns 409
- `/test` returns `{success: bool, latency_ms: int, error: str | null}`
- Router registered and reachable at `/api/v1/platform/providers`

---

### PVDR-004 — `InstrumentedLLMClient._resolve_library_adapter()` Migration

**File**: `src/backend/app/core/llm/instrumented_client.py`
**Effort**: 4h
**Depends on**: PVDR-002
**Priority**: P0

Replace the existing `_resolve_library_adapter()` method. Current implementation reads `PRIMARY_MODEL` from `os.environ`. New implementation:

1. Query `llm_providers` for the default row (`is_default = true AND is_enabled = true`)
2. If found: decrypt `api_key_encrypted`, construct the appropriate adapter subclass
3. If `llm_library_id` is set on the tenant config: use that specific library entry's `model_name` as the `primary` slot override
4. If no default row found: fall back to env vars (`PRIMARY_MODEL`, `AZURE_PLATFORM_OPENAI_API_KEY`, `AZURE_PLATFORM_OPENAI_ENDPOINT`) — log a warning `"llm_providers_env_fallback_active"` at WARNING level

Adapter construction by `provider_type`:

```python
match provider_row["provider_type"]:
    case "azure_openai":
        from app.core.llm.azure_openai import AzureOpenAIProvider
        adapter = AzureOpenAIProvider(
            api_key=decrypted_key,
            endpoint=provider_row["endpoint"],
            api_version=provider_row["options"].get("api_version", "2024-02-01"),
        )
        model = provider_row["models"].get("primary", "")
    case "openai":
        from app.core.llm.openai_direct import OpenAIDirectProvider
        adapter = OpenAIDirectProvider(api_key=decrypted_key)
        model = provider_row["models"].get("primary", "")
    case "anthropic":
        # Delegate to anthropic adapter (must exist before this PVDR ships)
        ...
```

The decrypted key must be in a local variable (`decrypted_key`), used to instantiate the adapter, and then overwritten: `decrypted_key = ""` after adapter construction. It must never be assigned to `self` or logged.

DB lookup uses `async_session_factory()` (same pattern as existing `_resolve_library_adapter` when reading `llm_library`).

**Acceptance criteria**:

- Chat completion works when `llm_providers` has a default row
- Chat completion works via env fallback when table has zero rows
- `"llm_providers_env_fallback_active"` warning appears in logs during fallback
- Decrypted key not present in any log line
- Integration test: create provider row, run `_resolve_library_adapter`, assert correct adapter type

---

### PVDR-005 — `embed()` Path Migration

**File**: `src/backend/app/core/llm/instrumented_client.py`
**Effort**: 2h
**Depends on**: PVDR-002, PVDR-004
**Priority**: P0

Replace the `embed()` method's `os.environ.get("EMBEDDING_MODEL")` read with a DB lookup.

New logic:

1. Query `llm_providers` for default row
2. Use `provider_row["models"].get("doc_embedding")` as the embedding model name
3. If provider type is `anthropic` (no embedding support): use `_resolve_embedding_fallback_adapter()` — finds any enabled azure_openai provider with a `doc_embedding` slot (PVDR-010)
4. Env fallback: if no default row, use `EMBEDDING_MODEL` env var (same warning logged)
5. For `kb_embedding` slot: use `provider_row["models"].get("kb_embedding")`, fall back to `doc_embedding` slot value

**Acceptance criteria**:

- `embed()` succeeds when default provider has `doc_embedding` slot configured
- `embed()` falls back to env `EMBEDDING_MODEL` when table has zero rows
- Anthropic primary provider triggers fallback to azure_openai embedding provider

---

### PVDR-006 — Bootstrap Auto-Seed

**File**: `src/backend/app/core/seeds.py`
**Effort**: 3h
**Depends on**: PVDR-002
**Priority**: P0

Add `seed_llm_provider_from_env()` async function. Called during application startup (in `app/main.py` lifespan handler, after DB is ready). It must be idempotent.

Logic:

```python
async def seed_llm_provider_from_env() -> bool:
    """
    If llm_providers table has zero rows and env vars are present,
    seed the first provider row from env. Returns True if seeded.
    """
    async with async_session_factory() as session:
        count = (await session.execute(
            text("SELECT COUNT(*) FROM llm_providers")
        )).scalar()
        if count > 0:
            return False  # Already seeded — do nothing

        api_key = os.environ.get("AZURE_PLATFORM_OPENAI_API_KEY", "").strip()
        endpoint = os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT", "").strip()
        primary = os.environ.get("PRIMARY_MODEL", "").strip()
        embedding = os.environ.get("EMBEDDING_MODEL", "").strip()
        intent = os.environ.get("INTENT_MODEL", "").strip()

        if not api_key or not endpoint or not primary:
            logger.warning("llm_provider_bootstrap_skip_missing_env")
            return False

        svc = ProviderService()
        models = {}
        if primary: models["primary"] = primary
        if intent: models["intent"] = intent
        if embedding: models["doc_embedding"] = embedding
        # Fill remaining slots from env if present
        for slot, env_var in [
            ("vision", "AZURE_OPENAI_VISION_DEPLOYMENT"),
            ("kb_embedding", "AZURE_OPENAI_KB_EMBEDDING_DEPLOYMENT"),
            ("intent_fallback", "AZURE_OPENAI_INTENT_FALLBACK_DEPLOYMENT"),
        ]:
            val = os.environ.get(env_var, "").strip()
            if val:
                models[slot] = val

        await svc.create_provider(session, {
            "provider_type": "azure_openai",
            "display_name": "Platform Azure OpenAI (seeded from env)",
            "description": "Auto-seeded from environment variables at startup.",
            "endpoint": endpoint,
            "api_key": api_key,
            "models": models,
            "options": {"api_version": "2024-02-01"},
            "is_default": True,
            "is_enabled": True,
        }, created_by=None)
        await session.commit()

        logger.info("llm_provider_seeded_from_env", slot_count=len(models))
        return True
```

**Acceptance criteria**:

- Called at startup, idempotent (second call does nothing)
- Seeds exactly one `is_default=true` row when env vars present and table empty
- Does nothing if table already has rows (even zero-enabled rows)
- Warning logged if env vars missing (not an error — env may intentionally be absent in prod)

---

### PVDR-007 — Health Check Background Job

**File**: `src/backend/app/modules/platform/provider_health_job.py`
**Effort**: 3h
**Depends on**: PVDR-002
**Priority**: P1

Background job that pings each `is_enabled=true` provider every 10 minutes. Pattern mirrors `app/modules/platform/tool_health_job.py` and `health_score_job.py`.

Job behaviour:

- Fetch all `is_enabled=true` providers
- For each: call `ProviderService.test_connectivity(provider_row)` with decrypted key
- Update `provider_status`, `last_health_check_at`, `health_error` in DB
- Write a structured log entry `"provider_health_check"` with `provider_id`, `status`, `latency_ms`
- Job runs every 600 seconds via APScheduler (same scheduler as existing jobs)
- Failures on one provider must not abort checks for remaining providers

**Acceptance criteria**:

- Job registered in scheduler at startup
- `provider_status` transitions correctly: unchecked → healthy / error
- `last_health_check_at` updated after every run
- One failing provider does not prevent others from being checked
- Unit test with mocked `test_connectivity` verifies DB updates

---

### PVDR-008 — Tenant Provider Selection API

**File**: `src/backend/app/modules/admin/llm_config.py`
**Effort**: 3h
**Depends on**: PVDR-002
**Priority**: P1

Extend the existing Tenant Admin LLM config module with two new endpoints.

`GET /admin/llm-config/providers` — list enabled platform providers (no credentials). Returns:

```json
[
  {
    "id": "...",
    "display_name": "Platform Azure OpenAI",
    "provider_type": "azure_openai",
    "is_default": true,
    "provider_status": "healthy",
    "slots_available": ["primary", "intent", "doc_embedding", "vision"]
  }
]
```

`PATCH /admin/llm-config/provider` — tenant selects a provider. Body: `{"provider_id": "uuid"}`. Validates that `provider_id` exists and `is_enabled=true`. Stores `provider_id` in `tenant_configs` under `config_type = 'llm_provider_selection'`. Invalidates the tenant config cache via `_invalidate_config_cache()`.

`slots_available` is derived from which keys are non-empty in `provider_row["models"]`.

Requires `require_tenant_admin`.

**Acceptance criteria**:

- GET returns only enabled providers, no credentials
- PATCH rejects unknown provider_id with 404
- PATCH rejects disabled provider with 422
- `tenant_configs` row upserted with ON CONFLICT
- Config cache invalidated on successful PATCH

---

### PVDR-009 — Tenant Provider Selection in `InstrumentedLLMClient`

**File**: `src/backend/app/core/llm/instrumented_client.py`
**Effort**: 2h
**Depends on**: PVDR-004, PVDR-008
**Priority**: P1

Extend `_resolve_adapter()` to respect a tenant's chosen `provider_id`:

```python
async def _resolve_adapter(self, tenant_id: str):
    llm_config = await self._config_svc.get(tenant_id, "llm_config")
    model_source = "library"
    llm_library_id = None
    if llm_config and isinstance(llm_config, dict):
        model_source = llm_config.get("model_source", "library")
        llm_library_id = llm_config.get("llm_library_id")

    if model_source == "byollm":
        return await self._resolve_byollm_adapter(tenant_id)

    # Check for tenant-selected provider
    provider_selection = await self._config_svc.get(
        tenant_id, "llm_provider_selection"
    )
    selected_provider_id = None
    if provider_selection and isinstance(provider_selection, dict):
        selected_provider_id = provider_selection.get("provider_id")

    return await self._resolve_library_adapter(
        llm_library_id, provider_id=selected_provider_id
    )
```

`_resolve_library_adapter()` gains an optional `provider_id` parameter. If supplied and found in DB, use that provider. If not found (deleted/disabled), fall back to default provider (log a warning).

**Acceptance criteria**:

- Tenant with no selection uses default provider
- Tenant with selection uses their chosen provider
- Selection pointing to disabled/deleted provider falls back to default (with warning log)

---

### PVDR-010 — Anthropic Embedding Fallback

**File**: `src/backend/app/core/llm/instrumented_client.py`
**Effort**: 2h
**Depends on**: PVDR-005
**Priority**: P1

New private method `_resolve_embedding_fallback_adapter()`:

```python
async def _resolve_embedding_fallback_adapter(self) -> tuple[LLMProvider, str]:
    """
    When the active provider does not support embeddings (e.g. Anthropic),
    find the first enabled azure_openai or openai provider that has a
    doc_embedding slot configured.

    Returns (adapter, model_name).
    Raises ValueError if no suitable fallback found.
    """
```

Queries: `SELECT * FROM llm_providers WHERE is_enabled = true AND provider_type IN ('azure_openai', 'openai') AND models->>'doc_embedding' IS NOT NULL ORDER BY is_default DESC, created_at ASC LIMIT 1`

Raises `ValueError` with actionable message if no fallback found:

> "Primary provider (anthropic) does not support embeddings and no Azure OpenAI / OpenAI provider with a doc_embedding slot was found. Add an Azure OpenAI provider with doc_embedding configured."

**Acceptance criteria**:

- Anthropic primary + Azure embedding fallback: `embed()` uses Azure
- No azure_openai fallback + Anthropic primary: `embed()` raises ValueError with clear message
- Unit test covers both paths

---

### PVDR-011 — Provider Health Summary on Platform Dashboard

**File**: `src/backend/app/modules/platform/routes.py`
**Effort**: 2h
**Depends on**: PVDR-007
**Priority**: P1

Add health summary data to the existing `GET /admin/dashboard` endpoint response, or expose it at `GET /platform/providers/health-summary`. The Platform Dashboard frontend (`usePlatformDashboard.ts`) should be able to show provider health.

Return structure:

```json
{
  "llm_providers": {
    "total": 3,
    "healthy": 2,
    "error": 1,
    "unchecked": 0,
    "last_checked_at": "2026-03-17T10:00:00Z"
  }
}
```

**Acceptance criteria**:

- Endpoint returns accurate counts from `llm_providers` table
- `last_checked_at` is the most recent `last_health_check_at` across all providers

---

### PVDR-012 — Remove Mandatory Env Var Requirements

**File**: `src/backend/app/core/llm/instrumented_client.py`
**Effort**: 1h
**Depends on**: PVDR-004, PVDR-005, PVDR-006, PVDR-018 (integration tests green)
**Priority**: P2

Change `ValueError` raises on missing `PRIMARY_MODEL` / `EMBEDDING_MODEL` / `INTENT_MODEL` from hard failures to warning-level log + fallback. Only block if BOTH the DB table has zero rows AND env vars are absent.

Update docstring: these env vars are now "break-glass emergency fallback only".

**Acceptance criteria**:

- Server starts cleanly with no env vars set if `llm_providers` has a default row
- Missing env vars with empty DB logs a warning, then raises ValueError on first actual request (not at startup)

---

## Frontend Items

### PVDR-013 — Platform Provider List Screen

**File**: `src/web/app/(platform)/platform/providers/page.tsx`
**Supporting elements**: `src/web/app/(platform)/platform/providers/elements/ProviderList.tsx`
**Hook**: `src/web/lib/hooks/useLLMProviders.ts`
**Effort**: 4h
**Depends on**: PVDR-003
**Priority**: P0

New Platform Admin screen. Pattern matches `src/web/app/(platform)/platform/llm-profiles/page.tsx`.

`useLLMProviders.ts` hook structure (mirrors `useLLMProfiles.ts`):

- `useLLMProviders()` — GET `/api/v1/platform/providers`
- `useCreateProvider()` — POST `/api/v1/platform/providers`
- `useUpdateProvider()` — PATCH `/api/v1/platform/providers/{id}`
- `useDeleteProvider()` — DELETE `/api/v1/platform/providers/{id}`
- `useTestProvider()` — POST `/api/v1/platform/providers/{id}/test`
- `useSetDefaultProvider()` — POST `/api/v1/platform/providers/{id}/set-default`

`ProviderList` renders an admin table (design system: 11px uppercase `th`, 13px `td`, `padding: 12px 14px`, `hover: var(--accent-dim)`).

Columns: Provider Name | Type | Status badge | Default | Slots Configured | Actions (Edit / Test / Set Default / Delete).

Status badge colors:

- `healthy` → accent green
- `error` → alert orange
- `unchecked` → text-faint grey

Type pill uses DM Mono font for the provider_type value.

"Default" column: accent green checkmark icon when `is_default=true`, dash otherwise.

"Slots Configured" column: compact chip list showing slot names that are non-empty in the `models` dict (e.g. `primary`, `intent`, `doc_embedding`).

Actions:

- Edit → opens `ProviderForm` in edit mode (PVDR-014)
- Test → POST `/{id}/test`, shows inline result toast
- Set Default → POST `/{id}/set-default`, disabled when already default
- Delete → disabled when `is_default=true`; confirmation dialog before executing

Bootstrap banner (PVDR-015) shown above the table when `bootstrap_active: true` in response.

**Acceptance criteria**:

- No API key data rendered anywhere on this page
- Status badge colors match design system tokens
- Delete disabled for default provider (tooltip explains why)
- Provider count shown in page subtitle

---

### PVDR-014 — Provider Form (Create/Edit)

**Files**:

- `src/web/app/(platform)/platform/providers/elements/ProviderForm.tsx`
- `src/web/app/(platform)/platform/providers/elements/SlotMappingGrid.tsx`
  **Effort**: 5h
  **Depends on**: PVDR-013
  **Priority**: P0

Modal form (`max-width: 640px`, `border-radius: var(--r-lg)`). Design follows the Wizard/Step Modal pattern from the design system.

**Create mode** (2 steps):

Step 1 — Provider Identity:

- `display_name` text input (required)
- `provider_type` select: azure_openai / openai / anthropic / deepseek / dashscope / doubao / gemini
- `endpoint` text input — shown only when `provider_type === "azure_openai"`; labelled "Azure Endpoint URL"
- `api_key` password input (required in create mode)
- `description` textarea (optional)
- `is_default` toggle — only show if zero providers exist OR explicitly toggling
- `options.api_version` text input — shown only for azure_openai, default "2024-02-01"

Step 2 — Slot Mapping (`SlotMappingGrid`):

- Grid of the 6 slots: primary, intent, vision, doc_embedding, kb_embedding, intent_fallback
- Each slot: label + deployment name text input
- Slots not supported by the selected `provider_type` are shown greyed-out with tooltip "Not supported by [type]"
- Supported slots per type must match the provider capability matrix in the architecture design
- "Test Connectivity" button — fires POST `/{id}/test` (or pre-save test on Step 2 footer) — shows latency_ms and success/error inline

**Edit mode** (single-step, all fields visible):

- `api_key` field placeholder: "Leave blank to keep existing key"
- Pre-populated with existing values from provider row
- Slot mapping grid pre-filled

Footer: [← Back] ghost + [Save →] primary in create/step mode; [Cancel] + [Save Changes] in edit mode.

**Acceptance criteria**:

- Azure endpoint field shown/hidden based on provider_type
- Unsupported slots visually disabled with tooltip
- `api_key` never logged, never sent in GET requests
- Edit mode: empty `api_key` omitted from PATCH payload
- Test result shown inline (not a navigation event)
- Form resets after successful submit

---

### PVDR-015 — Bootstrap Banner Component

**File**: `src/web/app/(platform)/platform/providers/elements/BootstrapBanner.tsx`
**Effort**: 2h
**Depends on**: PVDR-013
**Priority**: P1

Shown at the top of the Provider List screen when `GET /platform/providers` response includes a `bootstrap_active: true` flag (backend adds this when no providers exist or when env fallback is active).

Visual design:

- `background: var(--warn-dim)` with `border: 1px solid var(--warn)` left border (4px accent-left stripe)
- Icon: warning triangle in `var(--warn)`
- Title: "Running on environment fallback" (15px/600)
- Body: "Platform LLM credentials are being read from .env. Add a provider above to move credentials into the database and enable rotation without restarting the server." (13px/400)
- Dismiss: "×" button top-right that stores dismissal in localStorage under `mingai_pvdr_banner_dismissed_{version}` key. Banner reappears if `bootstrap_active` becomes true again after a new deployment.

**Acceptance criteria**:

- Banner shown when `bootstrap_active: true`
- Banner hidden when `bootstrap_active: false`
- Dismiss persists across page navigations (localStorage)
- Dismiss resets when `bootstrap_active` transitions from false → true

---

### PVDR-016 — Tenant Provider Selection UI

**File**: `src/web/app/(admin)/admin/settings/llm/elements/LibraryModeTab.tsx`
**Supporting hook**: `src/web/lib/hooks/useLLMConfig.ts` (extend existing)
**Effort**: 3h
**Depends on**: PVDR-008, PVDR-013
**Priority**: P1

Extend the existing Tenant Admin LLM Settings page (Library Mode tab). Currently this tab shows the LLM Library selection. Add a new section: "Platform Provider" above the library picker.

New section shows:

- Heading "Platform Provider" (section heading style)
- Radio/select of available providers from `GET /admin/llm-config/providers`
- Each option shows: display_name, provider_type chip (DM Mono), health status dot
- Currently selected provider highlighted with accent border
- "Using platform default" label when no explicit selection
- PATCH `/admin/llm-config/provider` on change — shows success toast

When the selected provider does not support embeddings (e.g. Anthropic), show an inline info banner:

> "This provider does not support embeddings. The platform will automatically use an Azure OpenAI provider for document indexing."

**Acceptance criteria**:

- Correct provider highlighted when tenant has a selection
- "Using platform default" shown when no selection
- Health status dot reflects provider_status
- Anthropic selection triggers embedding note
- Selection persists across page refresh

---

## Testing Items

### PVDR-017 — Unit Tests for `ProviderService`

**File**: `src/backend/tests/unit/test_provider_service.py`
**Effort**: 3h
**Depends on**: PVDR-002
**Priority**: P0

Tier 1 (unit) tests. Mock the DB session.

Test cases:

- `encrypt_api_key` → `decrypt_api_key` round-trip produces original string
- `encrypt_api_key` output is bytes (BYTEA compatible)
- `encrypt_api_key` output is never equal to plaintext input
- `list_providers()` result never contains `api_key_encrypted` key
- `set_default()` emits two UPDATE statements in correct order
- Duplicate `is_default=true` rejected at DB level (partial unique index)
- `test_connectivity()` returns `(True, None)` on mock success, `(False, "msg")` on mock failure
- `create_provider()` stores encrypted bytes, not plaintext
- Slot validation: unknown slot name in `models` dict raises ValueError

**Acceptance criteria**:

- All tests pass with `pytest src/backend/tests/unit/test_provider_service.py`
- No real network calls — all provider HTTP mocked
- No real DB calls — session is AsyncMock

---

### PVDR-018 — Integration Tests

**File**: `src/backend/tests/integration/test_llm_providers.py`
**Effort**: 4h
**Depends on**: PVDR-003, PVDR-006
**Priority**: P0

Tier 2 (integration) tests. Real PostgreSQL. `TestClient` against full FastAPI app.

Test cases:

- POST `/platform/providers` creates row with encrypted key in DB
- GET `/platform/providers` returns list without key field
- PATCH `/platform/providers/{id}` without `api_key` does not overwrite existing key
- PATCH `/platform/providers/{id}` with new `api_key` replaces encrypted key
- POST `/platform/providers/{id}/set-default` sets new default, clears old default
- DELETE `/platform/providers/{id}` with `is_default=true` returns 409
- DELETE `/platform/providers/{id}` with `is_default=false` succeeds
- Bootstrap auto-seed: empty table + env vars present → `seed_llm_provider_from_env()` creates row
- Bootstrap auto-seed idempotency: second call with table populated → no new row
- `GET /admin/llm-config/providers` returns only enabled providers
- `PATCH /admin/llm-config/provider` stores selection in `tenant_configs`

Do NOT mock the database — use real PostgreSQL test instance per `tests/integration/conftest.py` session-scoped `TestClient` pattern.

**Acceptance criteria**:

- All tests pass with real PostgreSQL
- No `api_key_encrypted` field in any response body
- Bootstrap seed idempotency verified

---

### PVDR-019 — Security Tests (Key Secrecy)

**File**: `src/backend/tests/integration/test_provider_credentials_security.py`
**Effort**: 3h
**Depends on**: PVDR-003
**Priority**: P0

Pattern mirrors `src/backend/tests/integration/test_byollm_security.py`.

Test cases:

- POST then GET: key never appears in GET response body (neither plaintext nor encrypted token)
- POST then GET detail: same assertion on single-provider GET
- Captured structlog output during POST: `api_key` value never appears in any log record
- Captured structlog output during PATCH: same assertion
- POST with `api_key` in query string (edge case): 422 validation error (key must be in body only)
- DB direct read: `api_key_encrypted` column contains bytes, not the original plaintext
- Fernet decrypt of DB bytes produces original key (proves round-trip, not plaintext storage)
- PATCH without `api_key` field: `api_key_encrypted` in DB unchanged (old key still decryptable)

**Acceptance criteria**:

- All 8 test cases pass
- Log capture assertion uses `caplog` fixture with `propagate=True`
- DB direct assertion uses raw SQL `SELECT api_key_encrypted FROM llm_providers WHERE id = :id`

---

### PVDR-020 — E2E Playwright Tests

**File**: `src/web/tests/e2e/provider_config.spec.ts`
**Effort**: 4h
**Depends on**: PVDR-013, PVDR-014, PVDR-016
**Priority**: P1

Full browser tests. Pattern mirrors `src/web/tests/e2e/red_team_audit.spec.ts`.

Scenarios:

**Scenario 1: PA adds provider**

1. Login as Platform Admin
2. Navigate to `/platform/providers`
3. Click "Add Provider"
4. Fill Step 1: display_name, provider_type=azure_openai, endpoint, api_key, description
5. Click Next → Step 2
6. Fill primary and doc_embedding slots
7. Click "Test Connectivity" — assert success indicator
8. Click Save
9. Assert new provider row appears in table

**Scenario 2: PA sets provider as default**

1. Provider list visible with at least 2 providers
2. Click "Set Default" on non-default provider
3. Assert that row now shows default checkmark
4. Assert previous default row no longer shows checkmark

**Scenario 3: Tenant admin sees provider selection**

1. Login as Tenant Admin
2. Navigate to Settings → LLM
3. Assert "Platform Provider" section visible
4. Assert current provider shown (either explicit selection or "platform default")
5. Change selection — assert toast success

**Scenario 4: API key not visible**

1. Login as Platform Admin
2. Navigate to provider detail (click Edit)
3. Assert no input field shows the actual key value
4. Assert `api_key` field placeholder reads "Leave blank to keep existing key"

**Acceptance criteria**:

- All 4 scenarios pass headless
- Screenshots captured on failure
- No test hardcodes API key values — uses `process.env.TEST_PROVIDER_KEY` or skips connectivity test if absent

---

## Migration Strategy

### Backward Compatibility

The migration is additive. No existing tables are altered. The `InstrumentedLLMClient` env fallback ensures zero downtime during rollout:

1. Deploy backend with PVDR-001 migration — `llm_providers` table created (empty)
2. PVDR-006 bootstrap auto-seed runs at startup — seeds row from env vars
3. System continues working exactly as before (now reading from DB, but DB has same values as env)
4. Platform Admin can now edit via UI — rotates key without server restart
5. After validation: deprecate env vars in runbook (but keep in .env as emergency break-glass)

### Rollback

If rollback is needed before PVDR-012 (env var removal):

- `alembic downgrade -1` drops `llm_providers` table
- `InstrumentedLLMClient` env fallback still works — no production impact

After PVDR-012 is merged, rollback requires re-adding env vars to `.env` and restarting.

### Env Var Deprecation Timeline

| Phase                | Status              | Action                                                           |
| -------------------- | ------------------- | ---------------------------------------------------------------- |
| Phase A-C            | Required (fallback) | No change to .env                                                |
| Phase D complete     | Recommended         | Add comment in .env marking vars as "break-glass"                |
| 30 days post Phase D | Optional            | Remove from `.env.example`; keep in production .env indefinitely |

---

## Risk Register

| Risk                                                                             | Likelihood | Impact | Mitigation                                                                                                                                   |
| -------------------------------------------------------------------------------- | ---------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Fernet key rotation (JWT_SECRET_KEY change) invalidates all stored provider keys | Low        | High   | Document: changing JWT_SECRET_KEY requires re-entering all provider API keys. Add startup check that attempts to decrypt a known test value. |
| Partial unique index bypass under concurrent transactions                        | Low        | Medium | DB-level index is the final guard. `set_default()` two-step runs in single transaction.                                                      |
| Health check job hammers provider APIs (rate limits)                             | Medium     | Low    | 10-minute interval is conservative. Per-provider jitter ±60s added.                                                                          |
| Tenant selects a provider, PA later disables it                                  | Medium     | Medium | PVDR-009 fallback to default on disabled selection. Warning emitted per request until tenant updates selection.                              |
| API key in error message if provider returns 401                                 | Low        | High   | `test_connectivity()` returns `(False, "Authentication failed — check API key")` — never echoes the key back in the message.                 |
| Bootstrap seed runs on every cold start if something empties the table           | Low        | High   | Seed checks `COUNT(*) > 0` before any write — idempotent.                                                                                    |
