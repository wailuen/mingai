# LLM Provider Configuration — Architecture Design

**Date**: March 17, 2026
**Status**: Implementation-Ready Specification
**Scope**: Complete technical architecture for the missing `llm_providers` layer

---

## 1. PostgreSQL Table Schema

### `llm_providers` DDL

```sql
-- Platform-managed LLM provider credential store.
-- One row = one named provider configuration (endpoint + encrypted key + slot mappings).
-- Platform Admin manages this table; tenants reference rows via tenant_configs.
CREATE TABLE IF NOT EXISTS llm_providers (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Human-readable identifier (e.g. "Azure East US 2 Primary", "Anthropic Claude Production")
    display_name        TEXT        NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),

    -- Provider type enum — drives which adapter class is constructed
    provider_type       TEXT        NOT NULL CHECK (
                            provider_type IN (
                                'azure_openai', 'openai', 'anthropic',
                                'deepseek', 'dashscope', 'doubao', 'gemini'
                            )
                        ),

    -- Base endpoint URL. For Azure OpenAI this is the resource endpoint.
    -- For OpenAI direct this may be null (SDK uses default endpoint).
    -- For Anthropic/Gemini this is the API base URL.
    endpoint            TEXT        CHECK (length(endpoint) <= 2048),

    -- Fernet-encrypted API key. Derived from JWT_SECRET_KEY via PBKDF2HMAC.
    -- NEVER returned in API responses. Decrypted in-memory only at call time.
    -- Stored as ASCII Fernet token (base64url-encoded ciphertext).
    encrypted_api_key   TEXT        NOT NULL CHECK (length(encrypted_api_key) > 0),

    -- Last 4 characters of the plaintext API key (for UI display only).
    -- Populated at save time, before encryption. Never re-derivable from encrypted_api_key.
    key_last4           CHAR(4),

    -- JSONB deployment slot mappings. Schema varies by provider_type.
    --
    -- For azure_openai:
    --   {
    --     "chat":            "agentic-worker",
    --     "intent":          "agentic-router",
    --     "vision":          "agentic-vision",
    --     "doc_embedding":   "text-embedding-3-small",
    --     "kb_embedding":    "text-embedding-ada-002",
    --     "intent_fallback": "intent-detection"
    --   }
    --
    -- For openai / anthropic / gemini:
    --   {
    --     "chat":            "gpt-4o",       -- or "claude-opus-4" etc.
    --     "intent":          "gpt-4o-mini",
    --     "vision":          "gpt-4o"        -- null if provider does not support vision
    --   }
    --   Note: embedding keys are not present for Anthropic (no embedding support).
    slot_mappings       JSONB       NOT NULL DEFAULT '{}',

    -- API version string. Required for Azure OpenAI. Null for other providers.
    api_version         TEXT        CHECK (length(api_version) <= 50),

    -- Marks this provider as the default for new tenants and fallback routing.
    -- CONSTRAINT: at most one row may have is_default = true.
    -- Enforced via partial unique index below.
    is_default          BOOLEAN     NOT NULL DEFAULT false,

    -- Last time the /test endpoint was called and all slots returned 200.
    -- Null if never tested.
    last_tested_at      TIMESTAMPTZ,

    -- P50 latency in ms from the last test run (primary/chat slot).
    last_test_latency_ms INTEGER,

    -- Status for soft-delete / disable without deletion.
    -- 'active'   — used for routing
    -- 'inactive' — exists but not used for routing (maintenance mode)
    -- 'error'    — last test failed; not used until re-tested
    provider_status     TEXT        NOT NULL DEFAULT 'active'
                            CHECK (provider_status IN ('active', 'inactive', 'error')),

    -- Who created/last modified this provider (Platform Admin user ID).
    created_by          UUID,
    updated_by          UUID,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enforce single default at the database level.
-- A partial unique index on a constant expression ensures only one row with is_default = true.
CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_providers_single_default
    ON llm_providers ((true))
    WHERE is_default = true;

-- Fast lookup by status for routing queries.
CREATE INDEX IF NOT EXISTS idx_llm_providers_status
    ON llm_providers (provider_status, is_default);

-- Enable JSONB path lookups on slot_mappings (e.g., find all providers with a chat slot).
CREATE INDEX IF NOT EXISTS idx_llm_providers_slots
    ON llm_providers USING GIN (slot_mappings);
```

### Notes on design decisions

**Why `key_last4` is stored separately**: The Fernet token is not reversibly decomposable — you cannot get the last 4 chars from the ciphertext without decrypting the entire key. Storing `key_last4` at save time allows the UI to show `****X8k2` without performing a decryption.

**Why `slot_mappings` is JSONB not normalized columns**: The slot schema varies meaningfully by provider type. Anthropic has no embedding slots. Azure OpenAI has 6 slots. A normalized slot table would require a join and a variable number of rows per provider. JSONB keeps the provider record self-contained and queryable. The GIN index allows `slot_mappings @> '{"chat": "..."}' :: jsonb` queries.

**Why `provider_status` instead of boolean `is_active`**: The three-state enum (`active`, `inactive`, `error`) allows the system to automatically mark a provider as `error` after a failed health check without requiring Platform Admin intervention. `inactive` is a deliberate admin action (maintenance); `error` is a system-detected state.

**Why `is_default` has a partial unique index**: `CREATE UNIQUE INDEX ON table ((true)) WHERE condition` is a PostgreSQL idiom for "at most one row satisfies this condition." It enforces the constraint at the DB layer, not just in application code. Attempting to INSERT a second `is_default = true` row raises a `UniqueViolation` exception.

### RLS Policy

`llm_providers` is platform-scope data — no RLS by tenant. All rows are visible to platform admins. Tenant-level queries go through `ProviderService.get_provider_for_tenant(tenant_id)` which resolves the appropriate provider via `tenant_configs`.

```sql
-- No RLS on llm_providers — platform admin table, not tenant-scoped.
-- The tenant_configs table (which is RLS-protected) acts as the join layer.
-- Tenants cannot query llm_providers directly.
```

---

## 2. `ProviderConfig` Dataclass

```python
# app/modules/platform/providers/models.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SlotMappings:
    """
    Deployment name or model name per operational slot.

    For azure_openai: deployment names (e.g. "agentic-worker").
    For other providers: model names (e.g. "claude-opus-4-5").
    None means the slot is not available for this provider.
    """
    chat: Optional[str] = None
    intent: Optional[str] = None
    vision: Optional[str] = None
    doc_embedding: Optional[str] = None
    kb_embedding: Optional[str] = None
    intent_fallback: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "SlotMappings":
        return cls(
            chat=d.get("chat"),
            intent=d.get("intent"),
            vision=d.get("vision"),
            doc_embedding=d.get("doc_embedding"),
            kb_embedding=d.get("kb_embedding"),
            intent_fallback=d.get("intent_fallback"),
        )


@dataclass
class ProviderConfig:
    """
    In-memory representation of one llm_providers row.

    The `api_key` field holds the PLAINTEXT key — decrypted on load.
    This object must NEVER be logged, serialized to disk, or cached.
    Only the provider_id and non-sensitive fields are safe to cache in Redis.

    Usage:
        config = await ProviderService().get_provider_for_tenant(tenant_id)
        adapter = config.build_adapter()
    """
    provider_id: str           # UUID string — safe to cache/log
    display_name: str          # Safe to log
    provider_type: str         # 'azure_openai' | 'openai' | 'anthropic' | ...
    endpoint: Optional[str]    # Safe to log
    api_key: str               # PLAINTEXT — NEVER log, cache, or serialize
    api_version: Optional[str] # Safe to log
    slot_mappings: SlotMappings # Safe to cache
    is_default: bool
    key_last4: Optional[str]   # Safe to log


@dataclass
class CachedProviderRef:
    """
    Cache-safe subset of ProviderConfig. Contains everything EXCEPT the plaintext key.
    Stored in Redis. When needed for an LLM call, the full key is fetched from DB.

    Redis key: mingai:platform:provider:{provider_id}
    TTL: 300 seconds
    """
    provider_id: str
    provider_type: str
    endpoint: Optional[str]
    api_version: Optional[str]
    slot_mappings: dict        # Raw dict for JSON serialization
    is_default: bool
```

**Critical constraint**: `ProviderConfig` contains the plaintext API key. It must never be cached in Redis, serialized to a log, or stored in any persistent medium. The pattern is:

1. Check Redis for `CachedProviderRef` (no key, just metadata + provider_id)
2. Cache hit → fetch encrypted key from DB by provider_id → decrypt → build `ProviderConfig` in memory
3. Cache miss → fetch full row from DB → decrypt → cache `CachedProviderRef` in Redis → return `ProviderConfig`

This two-step approach means the Redis cache stores no credentials, but still avoids a DB query on the hot path for metadata.

---

## 3. `ProviderService` Interface

```python
# app/modules/platform/providers/service.py

class ProviderService:
    """
    Resolves the correct ProviderConfig for a given tenant and operational slot.

    Lookup order:
    1. Check tenant_configs for an explicit provider override
       (config_type = 'llm_provider_id', config_data = {"provider_id": "..."})
    2. Fall back to the is_default = true provider in llm_providers
    3. If no default in DB, fall back to environment variables (bootstrap mode)
    """

    async def get_provider_for_tenant(
        self,
        tenant_id: str,
        slot: str = "chat",
    ) -> ProviderConfig:
        """
        Returns the ProviderConfig for a tenant + slot.
        Raises ProviderNotConfiguredError if no provider can be resolved.
        """
        ...

    async def get_default_provider(self) -> Optional[ProviderConfig]:
        """
        Returns the is_default provider, or None if no default is configured.
        Checks Redis cache first (CachedProviderRef), then DB.
        """
        ...

    async def get_env_fallback_provider(self) -> Optional[ProviderConfig]:
        """
        Builds a synthetic ProviderConfig from environment variables.
        Used ONLY when llm_providers table has zero rows.
        Returns None if env vars are also missing.
        """
        ...

    async def list_providers(self) -> list[ProviderSummary]:
        """
        Returns all providers (without api_key). Platform Admin use only.
        """
        ...

    async def save_provider(
        self,
        provider_type: str,
        display_name: str,
        endpoint: Optional[str],
        api_key: str,           # Plaintext — encrypted before persistence
        api_version: Optional[str],
        slot_mappings: dict,
        is_default: bool,
        created_by: str,
    ) -> ProviderSummary:
        """
        Encrypts api_key using get_fernet(), saves to DB, invalidates Redis cache.
        If is_default=True, clears is_default on all other rows first (in same transaction).
        Returns ProviderSummary (no api_key in response).
        """
        ...

    async def test_provider(
        self,
        provider_id: str,
        slots_to_test: Optional[list[str]] = None,
    ) -> ProviderTestResult:
        """
        Fires one test call per configured slot using the provider's credentials.
        Updates last_tested_at and last_test_latency_ms on success.
        Sets provider_status = 'error' on any slot failure.
        Returns per-slot test results.
        """
        ...

    async def set_default(self, provider_id: str, set_by: str) -> None:
        """
        Atomically sets is_default = true on provider_id and false on all others.
        Invalidates Redis cache for all cached provider refs.
        """
        ...

    async def delete_provider(self, provider_id: str) -> None:
        """
        Soft-deletes (sets status = 'inactive') if not is_default.
        Raises ProviderInUseError if provider is referenced by any tenant_configs.
        Raises ProviderIsDefaultError if is_default = true (must set new default first).
        """
        ...

    def _invalidate_cache(self, provider_id: Optional[str] = None) -> None:
        """
        DEL the Redis cache for a specific provider or all providers.
        Called after save/delete/set-default.
        """
        ...
```

---

## 4. API Endpoints

All endpoints require `platform_admin` scope (enforced by `require_platform_admin` dependency).

### `GET /platform/providers`

List all configured providers. Never returns encrypted keys or plaintext keys.

```
Response 200:
[
  {
    "id": "uuid",
    "display_name": "Azure East US 2 Primary",
    "provider_type": "azure_openai",
    "endpoint": "https://eastus2.api.cognitive.microsoft.com/",
    "api_version": "2024-02-01",
    "key_set": true,
    "key_last4": "X8k2",
    "slot_mappings": {
      "chat": "agentic-worker",
      "intent": "agentic-router",
      "vision": "agentic-vision",
      "doc_embedding": "text-embedding-3-small",
      "kb_embedding": "text-embedding-ada-002",
      "intent_fallback": "intent-detection"
    },
    "is_default": true,
    "provider_status": "active",
    "last_tested_at": "2026-03-17T08:00:00Z",
    "last_test_latency_ms": 142,
    "created_at": "...",
    "updated_at": "..."
  }
]

If llm_providers table is empty:
Response 200:
[]
Headers: X-Provider-Source: env-fallback
(Signals to the UI to show the "Environment fallback active" banner)
```

### `POST /platform/providers`

Create a new provider. API key is accepted in plaintext, encrypted before persistence.

```
Request body:
{
  "display_name": "Azure East US 2 Primary",
  "provider_type": "azure_openai",        -- validated against allowlist
  "endpoint": "https://...",             -- required for azure_openai
  "api_key": "sk-...",                   -- plaintext, encrypted before DB insert
  "api_version": "2024-02-01",           -- optional, defaults per provider type
  "slot_mappings": { "chat": "agentic-worker", ... },
  "is_default": false
}

Validation:
- provider_type: must be in {'azure_openai', 'openai', 'anthropic', ...}
- endpoint: required for azure_openai; must be valid URL
- api_key: min 10 chars
- slot_mappings: each slot value min 1 char, max 200 chars
- if is_default=true: clears is_default on existing default row

Response 201: ProviderSummary (no api_key field)
```

### `PATCH /platform/providers/{id}`

Update non-credential fields or rotate the API key. Partial update.

```
Request body (all optional):
{
  "display_name": "...",
  "endpoint": "...",
  "api_key": "sk-...",        -- if present, re-encrypts; if absent, key unchanged
  "api_version": "...",
  "slot_mappings": { ... },
  "is_default": false
}

Notes:
- If api_key is present in request: key_last4 is updated, encrypted_api_key is replaced
- If api_key is absent: existing encrypted key is preserved unchanged
- If is_default changes from false → true: atomic swap of default flag
- Updating any field invalidates the provider's Redis cache entry

Response 200: Updated ProviderSummary
Response 404: Provider not found
```

### `POST /platform/providers/{id}/test`

Fire test completions against each configured slot and report per-slot results.

```
Request body (optional):
{
  "slots": ["chat", "intent", "vision"]  -- subset to test; defaults to all configured slots
}

Response 200:
{
  "provider_id": "uuid",
  "tested_at": "2026-03-17T09:00:00Z",
  "overall_status": "pass",   -- "pass" | "partial" | "fail"
  "slot_results": [
    {
      "slot": "chat",
      "deployment": "agentic-worker",
      "status": "pass",
      "http_status": 200,
      "latency_ms": 142,
      "tokens_in": 12,
      "tokens_out": 8,
      "error": null
    },
    {
      "slot": "intent",
      "deployment": "agentic-router",
      "status": "pass",
      "http_status": 200,
      "latency_ms": 89,
      "tokens_in": 12,
      "tokens_out": 5,
      "error": null
    },
    {
      "slot": "vision",
      "deployment": "agentic-vision",
      "status": "fail",
      "http_status": 401,
      "latency_ms": 23,
      "tokens_in": 0,
      "tokens_out": 0,
      "error": "Unauthorized — check API key permissions for vision deployment"
    }
  ]
}

Side effects:
- On overall_status = "pass": updates last_tested_at, last_test_latency_ms (chat slot), provider_status = 'active'
- On overall_status = "fail": updates provider_status = 'error'
- On overall_status = "partial": updates provider_status = 'active' (partial is acceptable)
- In all cases: invalidates Redis cache

Response 504: Test exceeded 30s timeout
Response 404: Provider not found
```

### `DELETE /platform/providers/{id}`

Soft-delete (set `provider_status = 'inactive'`). Hard-delete is blocked if tenants reference this provider.

```
Validation:
- is_default = true → 409 "Cannot delete the default provider. Set a new default first."
- Any tenant_configs rows reference this provider_id → 409 "Provider is in use by N tenants"
- Otherwise: sets provider_status = 'inactive', invalidates cache

Response 204: No content
Response 409: Conflict (is_default or in use)
Response 404: Not found
```

### `PATCH /platform/providers/{id}/set-default`

Atomically swap the `is_default` flag. No request body needed.

```
Behavior:
BEGIN TRANSACTION;
UPDATE llm_providers SET is_default = false WHERE is_default = true;
UPDATE llm_providers SET is_default = true  WHERE id = :id;
COMMIT;

Side effects: invalidates all provider Redis cache entries

Response 200: Updated ProviderSummary
Response 404: Not found
Response 422: Provider is not 'active' — cannot set inactive/error provider as default
```

---

## 5. `InstrumentedLLMClient` Changes

### Current `_resolve_library_adapter()` (reads from env)

```python
async def _resolve_library_adapter(self, llm_library_id):
    primary_model = os.environ.get("PRIMARY_MODEL", "").strip()
    if not primary_model:
        raise ValueError("PRIMARY_MODEL environment variable is required.")
    # ...
    adapter = AzureOpenAIProvider()  # reads AZURE_PLATFORM_OPENAI_API_KEY from env
    return adapter, primary_model, "library"
```

### Target `_resolve_library_adapter()` (reads from ProviderService)

```python
async def _resolve_library_adapter(
    self, tenant_id: str, llm_library_id: Optional[str], slot: str = "chat"
) -> tuple[LLMProvider, str, str]:
    """
    Resolve adapter for library mode.

    1. Get ProviderConfig from ProviderService (DB/cache, env fallback if empty)
    2. Get model name for the requested slot from slot_mappings
    3. If llm_library_id is set, use library entry's model_name for the chat slot
    4. Build appropriate adapter class based on provider_type
    """
    from app.modules.platform.providers.service import ProviderService

    svc = ProviderService()
    config = await svc.get_provider_for_tenant(tenant_id=tenant_id, slot=slot)

    # Determine model name for this slot
    slot_model = getattr(config.slot_mappings, slot.replace("-", "_"), None)
    if slot_model is None:
        raise ValueError(
            f"Provider '{config.display_name}' has no configuration for slot '{slot}'. "
            f"Update slot_mappings in Platform Admin > Providers."
        )

    # If a library entry is specified, its model_name overrides the slot default
    if llm_library_id and slot == "chat":
        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    text(
                        "SELECT model_name FROM llm_library "
                        "WHERE id = :id AND status = 'Published'"
                    ),
                    {"id": llm_library_id},
                )
                row = result.fetchone()
                if row:
                    slot_model = row[0]
        except Exception as exc:
            logger.warning("library_lookup_failed", error=str(exc))

    # Build adapter from provider config
    adapter = _build_adapter(config)
    return adapter, slot_model, "library"


def _build_adapter(config: ProviderConfig) -> LLMProvider:
    """
    Construct the appropriate LLMProvider adapter from a ProviderConfig.
    The api_key is used here and immediately goes out of scope — never stored.
    """
    if config.provider_type == "azure_openai":
        from openai import AsyncAzureOpenAI
        from app.core.llm.azure_openai import AzureOpenAIProvider
        # Build with explicit credentials, not env vars
        client = AsyncAzureOpenAI(
            api_key=config.api_key,
            azure_endpoint=config.endpoint,
            api_version=config.api_version or "2024-02-01",
        )
        return AzureOpenAIProvider(_client=client)

    elif config.provider_type == "openai":
        from app.core.llm.openai_direct import OpenAIDirectProvider
        return OpenAIDirectProvider(api_key=config.api_key)

    elif config.provider_type == "anthropic":
        from app.core.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=config.api_key)

    # ... additional provider types

    else:
        raise ValueError(f"Unknown provider_type: {config.provider_type!r}")
```

**Key changes from current implementation**:

- `AzureOpenAIProvider` receives a pre-built `_client` rather than reading env vars at `__init__`
- The `api_key` goes out of scope after `_build_adapter()` returns — no long-lived reference
- The `slot` parameter routes to different deployments/models based on the operation type
- The fallback chain is inside `ProviderService`, not scattered across individual adapters

---

## 6. Bootstrap Problem Solution

### `ProviderService.get_env_fallback_provider()`

```python
async def get_env_fallback_provider(self) -> Optional[ProviderConfig]:
    """
    Builds a ProviderConfig from environment variables.
    Called ONLY when llm_providers table has zero active rows.

    This is the emergency fallback / migration bootstrap path.
    When this method is called, a warning is logged and the
    GET /platform/providers response includes X-Provider-Source: env-fallback.
    """
    import os
    api_key = os.environ.get("AZURE_PLATFORM_OPENAI_API_KEY", "").strip()
    endpoint = os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT", "").strip()

    if not api_key or not endpoint:
        logger.error(
            "provider_resolution_failed",
            reason="llm_providers table is empty and env vars are also missing",
        )
        return None

    logger.warning(
        "provider_env_fallback_active",
        hint="Configure providers in Platform Admin > Providers to eliminate this fallback",
    )

    primary_model = os.environ.get("PRIMARY_MODEL", "mingai-main")
    intent_model = os.environ.get("INTENT_MODEL", "intent5")
    embedding_model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-large")

    return ProviderConfig(
        provider_id="env-fallback",           # Sentinel ID — never a real UUID
        display_name="Environment Fallback",
        provider_type="azure_openai",
        endpoint=endpoint,
        api_key=api_key,                      # Plaintext — not cached
        api_version=os.environ.get("AZURE_PLATFORM_OPENAI_API_VERSION", "2024-02-01"),
        slot_mappings=SlotMappings(
            chat=primary_model,
            intent=intent_model,
            vision=os.environ.get("AZURE_OPENAI_VISION_DEPLOYMENT", primary_model),
            doc_embedding=embedding_model,
            kb_embedding=os.environ.get("AZURE_OPENAI_KB_EMBEDDING_DEPLOYMENT", "text-embedding-ada-002"),
            intent_fallback=os.environ.get("AZURE_OPENAI_INTENT_FALLBACK_DEPLOYMENT", "intent-detection"),
        ),
        is_default=True,
        key_last4=None,                       # Not available without decryption
    )
```

### Complete resolution flow

```
ProviderService.get_provider_for_tenant(tenant_id, slot):

1. Check tenant_configs for explicit provider assignment:
   SELECT config_data FROM tenant_configs
   WHERE tenant_id = :tid AND config_type = 'llm_provider_id'

   → Found: provider_id = config_data['provider_id']
   → Not found: proceed to step 2

2. Check Redis for cached default provider ref:
   GET mingai:platform:provider:default
   → Hit: extract provider_id, proceed to step 4
   → Miss: proceed to step 3

3. Query DB for default provider:
   SELECT id FROM llm_providers
   WHERE is_default = true AND provider_status = 'active'
   → Found: cache provider_id as "default" in Redis (TTL 300s)
   → Not found: proceed to step 5

4. Fetch encrypted key and build ProviderConfig:
   SELECT encrypted_api_key, endpoint, api_version, slot_mappings, ...
   FROM llm_providers WHERE id = :provider_id
   → Decrypt api_key using get_fernet()
   → Build ProviderConfig(api_key=decrypted, ...)
   → Return ProviderConfig (NOT cached — contains plaintext key)

5. No DB provider → env fallback:
   → Call get_env_fallback_provider()
   → If env vars present: return synthetic ProviderConfig
   → If env vars missing: raise ProviderNotConfiguredError
```

---

## 7. Credential Encryption

The existing Fernet pattern from `app/modules/har/crypto.py` is reused without modification:

```python
# In ProviderService.save_provider():
from app.modules.har.crypto import get_fernet

fernet = get_fernet()
encrypted_api_key = fernet.encrypt(api_key.encode("utf-8")).decode("ascii")
key_last4 = api_key[-4:] if len(api_key) >= 4 else api_key
# api_key reference goes out of scope here

await db.execute(
    text(
        "INSERT INTO llm_providers (..., encrypted_api_key, key_last4, ...) "
        "VALUES (..., :encrypted_key, :key_last4, ...)"
    ),
    {"encrypted_key": encrypted_api_key, "key_last4": key_last4, ...}
)

# In ProviderService._decrypt_provider_key():
from app.modules.har.crypto import get_fernet

fernet = get_fernet()
plaintext = fernet.decrypt(encrypted_api_key.encode("ascii")).decode("utf-8")
return plaintext
# plaintext goes out of scope when ProviderConfig is GC'd
```

**No new crypto code required.** The `get_fernet()` function, PBKDF2HMAC derivation, and Fernet encryption/decryption are reused exactly as implemented in `har/crypto.py`. This is the "Fernet singleton" already trusted for BYOLLM keys and HAR agent signing keys.

---

## 8. The 6-Slot Model: How Slots Map to Provider Config

```
Operation                    → Slot Name       → slot_mappings key
─────────────────────────────────────────────────────────────────
Chat synthesis (streaming)   → chat            → "chat"
Intent detection             → intent          → "intent"
Confidence scoring           → intent          → "intent"   (shared)
Auto-titling                 → intent          → "intent"   (shared)
Profile extraction           → intent          → "intent"   (shared)
Suggestions                  → intent          → "intent"   (shared)
Email generation             → intent          → "intent"   (shared)
Index selection              → intent          → "intent"   (shared)
Image analysis / OCR         → vision          → "vision"
Document indexing embeddings → doc_embedding   → "doc_embedding"
Legacy KB search embeddings  → kb_embedding    → "kb_embedding"
Intent detection fallback    → intent          → "intent_fallback" (circuit breaker)
```

All "auxiliary" operations (intent, confidence, titling, profiling, etc.) share the `intent` slot. This consolidation matches the analysis in `21-llm-model-slot-analysis.md` — these operations all have the same performance profile (fast, structured output, cost-optimized).

The circuit breaker for intent falls back to `intent_fallback`. If `intent_fallback` is null in slot_mappings, the circuit breaker falls back to `chat`. This prevents a single deployment outage from breaking all auxiliary operations.

---

## 9. Redis Cache Strategy

### Cache structure

```
Key:   mingai:platform:provider:default
Type:  String (JSON)
TTL:   300 seconds
Value: {"provider_id": "uuid", "provider_type": "azure_openai", ...}
       (CachedProviderRef — no api_key, no encrypted_api_key)

Key:   mingai:platform:provider:{provider_id}
Type:  String (JSON)
TTL:   300 seconds
Value: CachedProviderRef for that provider_id

Key:   mingai:platform:provider:list
Type:  String (JSON)
TTL:   300 seconds
Value: [CachedProviderRef, ...] — used for GET /platform/providers
```

### Invalidation triggers

| Event                             | Keys to invalidate                                                                                                    |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Provider created                  | `mingai:platform:provider:list`                                                                                       |
| Provider updated (non-key fields) | `mingai:platform:provider:{id}`, `mingai:platform:provider:list`                                                      |
| Provider key rotated              | `mingai:platform:provider:{id}`, `mingai:platform:provider:list`                                                      |
| Default changed                   | `mingai:platform:provider:default`, all `mingai:platform:provider:*`                                                  |
| Provider deleted                  | `mingai:platform:provider:{id}`, `mingai:platform:provider:default` (if was default), `mingai:platform:provider:list` |
| Provider test ran                 | `mingai:platform:provider:{id}` (status/latency updated)                                                              |

### Multi-pod invalidation

In a multi-pod deployment (3+ uvicorn instances), a Redis DEL from one pod is immediately visible to all others — Redis is the shared cache. There is no per-pod in-process cache. All pods read from Redis on cache miss; all pods write the same key format on cache population.

No message-passing or pub/sub is required. The Redis DEL is sufficient for cross-pod invalidation because:

1. Only one pod will execute the write operation (the one handling the API request)
2. All pods miss the cache after the DEL and re-read from DB on next request
3. The DB is the source of truth; Redis is acceleration only

**Maximum inconsistency window**: `300 seconds` (TTL) — but only if the DEL fails (Redis connectivity issue). In normal operation, the DEL is synchronous and invalidation is immediate.

---

**Document Version**: 1.0
**Author**: Analysis Agent
**References**: `src/backend/app/core/llm/instrumented_client.py`, `src/backend/app/core/llm/azure_openai.py`, `src/backend/app/modules/har/crypto.py`, `src/backend/app/modules/admin/byollm.py`, `workspaces/mingai/01-analysis/01-research/21-llm-model-slot-analysis.md`, `workspaces/mingai/01-analysis/04-multi-tenant/04-llm-provider-management.md`
