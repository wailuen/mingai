---
id: 30
title: LLM Profile Redesign — Phase B3: Three-Tier ProfileResolver
status: pending
priority: critical
phase: B
estimated_days: 1
---

# LLM Profile Redesign — Phase B3: Three-Tier ProfileResolver

## Context

Every LLM call in the system needs to know which model to use for a given tenant and slot. The ProfileResolver is the hot path for this lookup — it runs on every query. It must be fast (Redis cache first), resilient (survive Redis failures via in-memory LRU), and never fail-open (if all tiers fail, raise — do not silently fall back to a hardcoded model).

The resolver is also the place where the legacy single-model resolution (pre-profile-redesign) is bridged via a feature flag. This allows gradual rollout without breaking existing deployments.

## Scope

Files to create:

- `src/backend/app/core/llm/profile_resolver.py`

Tests are in todo 34 (Phase B integration tests).

## Requirements

### ProfileResolver class

Constructor: `__init__(self, db, redis_client)` — stores references, initialises in-memory LRU.

In-memory LRU cache:

- Max 1000 entries
- 5-minute TTL per entry
- Implementation: use `cachetools.TTLCache(maxsize=1000, ttl=300)` if available, otherwise a manual dict with timestamps
- Survives Redis connection failures — resolver continues serving cached profiles from LRU

#### resolve(tenant_id: UUID) -> ResolvedProfile

Resolution order (stop at first success):

1. Check in-memory LRU for `tenant_id` → return if present and not expired
2. Check Redis key `mingai:{tenant_id}:llm_profile:effective` → if hit, deserialise and store in LRU, return
3. DB query (never skip):
   a. `SELECT llm_profile_id FROM tenants WHERE id = tenant_id`
   b. If `llm_profile_id IS NOT NULL`: resolve that profile → store in Redis (60s TTL) + LRU → return
   c. If NULL: `SELECT id FROM llm_profiles WHERE is_platform_default = TRUE AND owner_tenant_id IS NULL`
   d. If found: resolve platform default → store in Redis + LRU → return
   e. If NULL: check `PLATFORM_DEFAULT_PROFILE_ID` env var → resolve that profile ID → store + return
   f. If env var absent or profile not found: raise `ProfileResolutionError`

Never raise a different exception to "not found" — always `ProfileResolutionError`. Log the actual DB/Redis error internally.

#### validate_tenant_ownership(tenant_id: UUID, library_entry_id: UUID) -> bool

For BYOLLM library entries: checks `llm_library.owner_tenant_id == tenant_id`. Returns False (does not raise) — callers decide how to handle.

#### flush_tenant_cache(tenant_id: UUID) -> None

Deletes `mingai:{tenant_id}:llm_profile:effective` from Redis. Removes from in-memory LRU. Called by `LLMProfileService._invalidate_cache`.

#### flush_all_caches() -> None

Emergency method for urgent deprecations. Deletes all `mingai:*:llm_profile:effective` keys from Redis (use SCAN to avoid blocking). Clears in-memory LRU entirely. Logs the flush as a WARNING with actor context.

### Feature flag: LLM_PROFILE_SLOT_ROUTING

Env var `LLM_PROFILE_SLOT_ROUTING` (default: "false").

When `LLM_PROFILE_SLOT_ROUTING=false`:

- `resolve()` still runs the full resolution pipeline and caching
- But `ResolvedProfile.use_legacy_routing = True` is set on the returned object
- The caller (`InstrumentedLLMClient` in B4) checks this flag and uses the legacy single-model env-var approach if set
- This allows gradual rollout: resolver and service are live but LLM calls still use old env vars

When `LLM_PROFILE_SLOT_ROUTING=true`:

- `ResolvedProfile.use_legacy_routing = False`
- All LLM calls use the slot-resolved library entries

### ResolvedProfile dataclass

```python
@dataclass
class ResolvedProfile:
    profile_id: UUID
    profile_name: str
    tenant_id: UUID
    is_byollm: bool
    use_legacy_routing: bool  # from LLM_PROFILE_SLOT_ROUTING flag
    slots: dict[str, ResolvedSlot | None]  # keys: chat, intent, vision, agent
    resolved_at: datetime
```

```python
@dataclass
class ResolvedSlot:
    library_id: UUID
    endpoint_url: str
    api_key_encrypted: str  # still encrypted at this point
    api_version: str | None
    model_name: str
    provider: str
    params: dict  # merged profile params + library defaults
    traffic_split: dict  # from profile.chat_traffic_split (if applicable)
```

`api_key_encrypted` is decrypted by `InstrumentedLLMClient` just before use and cleared in `finally`. It is NEVER stored decrypted anywhere outside the request scope.

### ProfileResolutionError

```python
class ProfileResolutionError(Exception):
    def __init__(self, tenant_id: UUID, reason: str):
        self.tenant_id = tenant_id
        self.reason = reason
        super().__init__(f"Profile resolution failed for tenant {tenant_id}: {reason}")
```

This error surfaces to the LLM call as a 503 with a generic "Service temporarily unavailable" message. The `reason` is logged internally only.

### Dual-Path Precedence Rule (GAP-08: Legacy vs New Resolution)

The existing system stores LLM config in `tenant_configs` table (`config_type = 'llm_config'` and `config_type = 'byollm_key_ref'` JSONB blobs). The new system uses `tenants.llm_profile_id` → `llm_profiles`.

When `LLM_PROFILE_SLOT_ROUTING=true`, the resolver uses `tenants.llm_profile_id` exclusively. The `tenant_configs` LLM entries are ignored. This is the explicit precedence rule — new system wins.

When `LLM_PROFILE_SLOT_ROUTING=false`, the resolver sets `use_legacy_routing=True` and `InstrumentedLLMClient` falls back to env-var resolution, bypassing `tenant_configs` LLM entries entirely (same as today).

The `tenant_configs` rows with `config_type IN ('llm_config', 'llm_provider_selection', 'byollm_key_ref')` will be deprecated and cleaned up in a future migration once all tenants have been assigned `llm_profile_id` values. Do NOT delete them in Phase B — they are the fallback for any tenant not yet migrated.

Document this dual-path rule in a comment block at the top of `profile_resolver.py`.

## Acceptance Criteria

- On first call for a tenant: DB is queried, result stored in Redis and LRU
- On second call within 5 minutes: LRU is used, no DB query, no Redis call
- When Redis is unavailable: LRU continues serving, no exception propagated
- When Redis and LRU both miss: DB is queried
- When tenant has no profile and no platform default exists: `ProfileResolutionError` is raised
- `LLM_PROFILE_SLOT_ROUTING=false` returns `use_legacy_routing=True` in all resolved profiles
- `flush_tenant_cache` clears both Redis key and LRU entry
- `validate_tenant_ownership` returns False for entries owned by other tenants, True for own entries

## Dependencies

- 27 (schema) — llm_profiles and llm_library tables must exist
- 29 (LLMProfileService) — service calls resolver; resolver does not depend on service
