# LLM Provider Credentials Management — Product Opportunity

**Date**: March 17, 2026
**Status**: Pre-implementation Analysis
**Scope**: Platform Admin credential management for all LLM provider infrastructure

---

## 1. Problem Statement

### The Core Contradiction

mingai is a multi-tenant enterprise AI platform. Enterprise software, by definition, must be configurable without touching server infrastructure. Yet today, every LLM credential change requires:

1. SSH access to the production host
2. Editing `.env` directly (or redeploying via CI with updated secrets)
3. A full process restart to pick up the change
4. Coordination across every backend pod in a multi-instance deployment

This is not a minor operational inconvenience — it is a category-level architectural defect. A platform that charges enterprise customers for reliability and manageability cannot require SSH access for routine operations.

### Why This Happened

The architecture evolved correctly in spirit but incompletely in implementation. Two separate layers were designed:

- **Layer 1 — `llm_library` table** (built): The model catalog. Describes models available to tenants — display name, provider type, model_name, pricing, lifecycle status. This is the "what can tenants use" layer.
- **Layer 2 — `llm_providers` table** (missing): The credential store. Holds the actual endpoint, encrypted API key, deployment slot mappings, and `is_default` flag needed to actually call those models. This is the "how does the platform call them" layer.

Layer 1 was implemented. Layer 2 was designed in the product documents but never implemented. As a result, `InstrumentedLLMClient._resolve_library_adapter()` falls back to environment variables for the actual connection details:

```python
# Current code — reads from env, cannot be changed without restart
primary_model = os.environ.get("PRIMARY_MODEL", "").strip()
if not primary_model:
    raise ValueError("PRIMARY_MODEL environment variable is required. Set it in .env.")
```

Similarly, `AzureOpenAIProvider.__init__()` reads credentials at construction time from `AZURE_PLATFORM_OPENAI_API_KEY` and `AZURE_PLATFORM_OPENAI_ENDPOINT`. These are baked in at startup and cannot change while the process runs.

### The Full Scope of the Problem

It is not just one env var. The current deployment has up to 13 LLM-related environment variables:

| Environment Variable                      | Purpose                                  |
| ----------------------------------------- | ---------------------------------------- |
| `AZURE_PLATFORM_OPENAI_API_KEY`           | Primary / embedding / vision credentials |
| `AZURE_PLATFORM_OPENAI_ENDPOINT`          | Primary / embedding / vision endpoint    |
| `AZURE_PLATFORM_OPENAI_API_VERSION`       | API version string                       |
| `PRIMARY_MODEL`                           | Chat deployment name                     |
| `EMBEDDING_MODEL`                         | Doc embedding deployment name            |
| `INTENT_MODEL`                            | Intent detection deployment name         |
| `AZURE_OPENAI_VISION_DEPLOYMENT`          | Vision deployment name                   |
| `AZURE_OPENAI_KB_EMBEDDING_DEPLOYMENT`    | Legacy KB embedding deployment           |
| `AZURE_OPENAI_INTENT_FALLBACK_DEPLOYMENT` | Intent circuit-breaker fallback          |
| `AZURE_OPENAI_CHAT_FALLBACK_DEPLOYMENT`   | Chat circuit-breaker fallback            |
| `AZURE_OPENAI_INTENT_REASONING_EFFORT`    | Reasoning effort for intent              |
| `AZURE_OPENAI_CHAT_REASONING_EFFORT`      | Reasoning effort for chat                |
| `BYOLLM_COST_PER_1K_IN_USD`               | Cost estimation fallback                 |

Each of these is a hardcoded operational dependency. None can be changed without a restart.

---

## 2. Current State vs. Target State

### Current State

```
┌─────────────────────────────────────────────────────────────────┐
│  .env file (on server)                                          │
│  AZURE_PLATFORM_OPENAI_API_KEY=...                              │
│  PRIMARY_MODEL=mingai-main                                      │
│  EMBEDDING_MODEL=text-embedding-3-large                         │
│  ... (10 more vars)                                             │
└────────────────────┬────────────────────────────────────────────┘
                     │  os.environ.get() at startup — frozen
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  AzureOpenAIProvider (singleton-ish)                            │
│  Reads: AZURE_PLATFORM_OPENAI_API_KEY, ENDPOINT at __init__()   │
│  Cannot be reconfigured without restart                          │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  InstrumentedLLMClient._resolve_library_adapter()               │
│  → Falls back to PRIMARY_MODEL env var                          │
│  → llm_library lookup gives model_name, but NOT credentials     │
│  → The actual API call still needs env-provided endpoint + key  │
└─────────────────────────────────────────────────────────────────┘
```

**Pain points:**

- Every API key rotation requires a deployment
- Switching from one Azure OpenAI resource to another requires a deployment
- Adding a second provider (Anthropic, Gemini) requires code changes + deployment
- No audit trail for credential changes
- No validation before activating new credentials
- Platform Admin has no UI to see what credentials are configured

### Target State

```
┌─────────────────────────────────────────────────────────────────┐
│  PostgreSQL: llm_providers table                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ id │ provider_type │ display_name │ endpoint │            │  │
│  │ encrypted_api_key │ slot_mappings (JSONB) │ is_default   │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────────────────────┘
                     │  Redis cache (TTL 300s, invalidated on write)
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  ProviderService.get_default_provider()                         │
│  → Cache hit → return cached ProviderConfig                     │
│  → Cache miss → DB query → cache → return                       │
│  → Both empty (bootstrap) → env var emergency fallback          │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  InstrumentedLLMClient._resolve_library_adapter()               │
│  → Gets ProviderConfig with credentials + slot mappings         │
│  → Builds provider adapter with those credentials               │
│  → No env var dependency for LLM calls                          │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Platform Admin Web UI                                          │
│  → Provider list (type, endpoint, status, is_default)           │
│  → Add/edit provider (form with test-before-save)               │
│  → Slot mapping UI (Chat → agentic-worker, Intent → agentic-router) │
│  → Credential health indicators (last tested, latency)          │
└─────────────────────────────────────────────────────────────────┘
```

**Gains:**

- API key rotation via UI, takes effect within 5 minutes (Redis TTL drain)
- Multi-provider support (Azure + Anthropic simultaneously) without code changes
- Audit log for every credential change
- Built-in connectivity test before credentials go live
- Zero env var dependency for LLM calls in steady state
- Platform Admin has full visibility into configured providers

---

## 3. Who Benefits and Why

### Platform Admin

**Today**: Must have server SSH access or CI pipeline permissions to change any LLM setting. Cannot see what credentials are currently configured without reading the server's `.env`. Has no way to test new credentials before they go live.

**With this feature**:

- Self-service credential management via the Web UI
- Real-time connectivity test before saving (catch wrong keys immediately)
- Complete audit history of every credential change with timestamps
- Health dashboard showing latency per provider slot
- Can swap providers (e.g., from Azure East US 2 to Azure Southeast Asia) without a deployment

**Concrete scenario**: Azure rotates API keys quarterly. Today this is a coordinated deployment. After this feature: Platform Admin opens Providers tab, clicks "Edit", pastes new key, clicks "Test Connection" (sees 200ms latency, 200 OK), clicks "Save". Done. No deployment. No SSH.

### Tenant Admin

**Today**: Picks from the platform-approved `llm_library` entries but has no visibility into which physical provider actually serves their tenant. If the default provider is degraded, they see slow responses with no explanation.

**With this feature**:

- The Platform Admin can configure multiple providers and mark one as default
- When a provider is degraded, Platform Admin can switch the default to a backup provider in minutes
- Tenant Admin's "Model Settings" screen correctly shows the provider type backing the selected library entry
- Provider health is visible in the Platform Admin dashboard (affects Tenant Admin indirectly via faster issue resolution)

### End Users

**Today**: If a key expires or an Azure endpoint has a regional outage, chat breaks with a generic error. Recovery requires a deployment cycle.

**With this feature**:

- Provider failover can be triggered within the UI (set a backup provider as default)
- The `is_default` flag flip propagates to all tenants within one Redis TTL cycle (5 minutes maximum)
- No user-visible downtime for planned key rotations

### Platform Business

**Today**: Every customer request to "switch to Anthropic Claude" requires a custom code fork. The platform is de facto Azure-only despite the provider abstraction being partially designed.

**With this feature**:

- Can sign agreements with Anthropic, Gemini, Deepseek and activate them without code changes
- Different regional deployments (US, EU, Asia) can be configured as separate providers and assigned to tenants by geography
- BYOLLM (existing feature) becomes a complement to platform-managed providers, not a workaround for the platform's own inflexibility
- Platform can offer SLA-backed provider routing as a premium feature (e.g., "your tenant always routes to the lowest-latency provider")

---

## 4. The Bootstrap Problem

### The Chicken-and-Egg

The `llm_providers` table lives in PostgreSQL. PostgreSQL is accessed by the backend application. The backend application also uses LLM calls for several internal operations (triage agent, auto-titling, confidence scoring). Therefore:

- To store provider credentials: the app must be running
- For the app to be useful: LLM must work
- For LLM to work: provider credentials must be stored

More specifically, the initial `docker compose up` or Kubernetes deployment must bootstrap provider credentials somehow before the first tenant query arrives.

### The Solution: Env Vars as Emergency Fallback Only

The bootstrap problem is solved by preserving `.env` vars as an **emergency fallback**, not the primary configuration source:

```
ProviderService.resolve():
  1. Check Redis cache → return if hit
  2. Query llm_providers WHERE is_default = true
  3. If found: cache it, return ProviderConfig
  4. If NOT found (zero rows):
     → Log warning: "no providers configured in DB, falling back to env"
     → Read AZURE_PLATFORM_OPENAI_API_KEY, AZURE_PLATFORM_OPENAI_ENDPOINT from env
     → Build a synthetic ProviderConfig from env vars
     → DO NOT cache this (force DB check on next request)
     → Return synthetic config
```

This means:

- First deployment works exactly as today (`.env` vars present, DB empty)
- Platform Admin logs in and configures providers via UI
- Once a provider is saved with `is_default = true`, env fallback is never used again
- If the DB row is later deleted without setting a new default, env fallback re-activates automatically as a safety net

### Migration Path

The migration from `.env` to DB credentials is non-destructive and reversible:

**Phase 1 — Deploy the new code** (backwards compatible):

- `llm_providers` table is empty
- All LLM calls use env var fallback (identical to today's behavior)
- Platform Admin UI shows "No providers configured — using environment fallback"

**Phase 2 — Configure first provider via UI**:

- Platform Admin enters the same credentials that are in `.env`
- Clicks "Test Connection" — verifies the credentials work
- Saves with `is_default = true`
- All new LLM calls now route through the DB-backed provider
- Env vars are now redundant but harmless (fallback never fires)

**Phase 3 — Decommission env vars** (optional, future):

- Remove LLM env vars from `.env` and deployment manifests
- System now runs entirely from DB-backed provider configuration
- Env vars become truly optional emergency break-glass

**Phase 4 — Multi-provider** (unlocked after Phase 3):

- Add second provider (e.g., Anthropic for Claude-backed tenants)
- No code changes required
- Slot mappings stored in `llm_providers.slot_mappings JSONB`

### What Never Goes Away from .env

Even after full migration to DB-backed credentials, the following env vars remain required forever:

| Env Var          | Why it stays in .env                                                                                                                                                 |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `JWT_SECRET_KEY` | Derives the Fernet key used to encrypt API keys stored in DB. If this is in DB, you have a circular dependency: you need it to decrypt it. It must stay out-of-band. |
| `DATABASE_URL`   | PostgreSQL connection string. Cannot be stored in PostgreSQL itself.                                                                                                 |
| `REDIS_URL`      | Redis connection string. Same logic.                                                                                                                                 |
| `CLOUD_PROVIDER` | Bootstrap routing decision, needed before any DB connection.                                                                                                         |

Everything else — all LLM-related env vars — can be fully replaced by DB-backed provider configuration.

---

## 5. Summary

The missing `llm_providers` layer is not a nice-to-have enhancement. It is the gap that prevents mingai from being a properly managed enterprise platform. Without it:

- The platform cannot be operated by non-engineers
- Key rotations require coordination and risk
- Provider diversity (beyond Azure OpenAI) requires code changes
- Tenants are invisible to each other's provider health

Implementing it closes the loop between Layer 1 (model catalog, already built) and the actual LLM calls, replacing fragile env var coupling with a proper managed credential store that is UI-accessible, audit-logged, test-validated, and cache-efficient.

---

**Document Version**: 1.0
**Author**: Analysis Agent
**References**: `src/backend/app/core/llm/instrumented_client.py`, `src/backend/app/core/llm/azure_openai.py`, `src/backend/app/core/tenant_config_service.py`, `workspaces/mingai/01-analysis/04-multi-tenant/04-llm-provider-management.md`, `workspaces/mingai/01-analysis/01-research/21-llm-model-slot-analysis.md`
