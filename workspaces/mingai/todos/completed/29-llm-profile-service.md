---
id: 29
title: LLM Profile Redesign — Phase B2: LLMProfileService
status: pending
priority: critical
phase: B
estimated_days: 2
---

# LLM Profile Redesign — Phase B2: LLMProfileService

## Context

The service layer is the core business logic for all profile management operations. It sits between the API routes and the database, owns all validation rules, writes the history and audit trails, and manages cache invalidation signals. All profile mutations must go through this service — no direct DB writes from routes.

Two critical design rules enforced here:

- Slot assignment validates that the library entry is published, has a passing test, and its `capabilities.eligible_slots` includes the target slot
- `set_platform_default` must be an atomic swap — clearing the old default and setting the new one in a single transaction to prevent a window where no default exists

## Scope

Files to create:

- `src/backend/app/modules/llm_profiles/service.py`

No other files in this todo. Tests for the service are covered in todo 34 (Phase B integration tests).

## Requirements

### LLMProfileService class

Constructor: `__init__(self, db, redis_client)` — db is the async DB connection/pool, redis_client for cache invalidation.

#### Platform profile methods

`async create_profile(req: CreateProfileRequest, actor_id: UUID) -> LLMProfile`

- Inserts into `llm_profiles` with `owner_tenant_id = NULL`
- Calls `_write_history(profile_id, actor_id, 'created', previous_state=None, new_state=profile_dict)`
- Calls `_write_audit(profile_id, tenant_id=None, actor_id, 'profile_created', details={})`
- Returns the created profile

`async update_profile(profile_id: UUID, req: UpdateProfileRequest, actor_id: UUID) -> LLMProfile`

- Fetches current state for history snapshot
- Updates mutable fields (name, description, plan_tiers, custom_slots)
- Does NOT allow changing owner_tenant_id or status via this method
- Calls `_write_history` and `_write_audit`
- Calls `_invalidate_cache(profile_id)`

`async assign_slot(profile_id: UUID, slot: SlotName, library_id: UUID, params: dict, actor_id: UUID) -> LLMProfile`

- Validates: library entry exists and status == 'published'
- Validates: library entry has a passing test (`test_passed_at IS NOT NULL`)
- Validates: slot is in `library_entry.capabilities['eligible_slots']`
- Updates the appropriate `{slot}_library_id` column and `{slot}_params` column
- Calls `_write_history` with previous/new slot assignment
- Calls `_write_audit` with event_type 'slot_assigned'
- Calls `_invalidate_cache(profile_id)` — all tenants using this profile need refresh

`async set_platform_default(profile_id: UUID, actor_id: UUID) -> None`

- Profile must be platform-owned (`owner_tenant_id IS NULL`) and have status 'active'
- Atomic transaction: `UPDATE llm_profiles SET is_platform_default = FALSE WHERE is_platform_default = TRUE AND owner_tenant_id IS NULL`, then `UPDATE llm_profiles SET is_platform_default = TRUE WHERE id = profile_id`
- Both UPDATEs in single transaction — no window with zero defaults
- Calls `_write_audit` with event_type 'default_changed'
- Calls `_invalidate_cache(None)` — flush all tenant profile caches (pattern: `mingai:*:llm_profile:effective`)

`async deprecate_profile(profile_id: UUID, actor_id: UUID) -> None`

- Checks `SELECT COUNT(*) FROM tenants WHERE llm_profile_id = profile_id` — if > 0, raises `ProfileDeprecationBlockedError` with count of affected tenants
- Updates status to 'deprecated'
- Calls `_write_history`, `_write_audit`
- Does NOT flush tenant caches (deprecated profiles are still in use until tenants switch)

`async list_platform_profiles(plan_tier: str | None = None) -> list[LLMProfile]`

- Returns profiles where `owner_tenant_id IS NULL`
- If plan_tier provided, filters where plan_tier is in `plan_tiers` array column
- Orders by `is_platform_default DESC, name ASC`

#### Tenant-facing methods

`async select_profile(tenant_id: UUID, profile_id: UUID, actor_id: UUID) -> None`

- Fetches tenant's plan_tier from DB
- Fetches profile's plan_tiers array
- If tenant plan_tier not in profile.plan_tiers, raises `PlanTierInsufficientError`
- Updates `tenants.llm_profile_id = profile_id`
- Calls `_write_audit` with event_type 'tenant_selected', details={'previous_profile_id': ...}
- Calls `_invalidate_cache(tenant_id=tenant_id)` — key: `mingai:{tenant_id}:llm_profile:effective`

`async get_effective_profile(tenant_id: UUID) -> ResolvedProfile`

- Delegates to `ProfileResolver.resolve(tenant_id)` — do NOT implement resolution logic here
- Returns whatever ProfileResolver returns

#### BYOLLM methods

`async create_byollm_profile(tenant_id: UUID, req: CreateProfileRequest, actor_id: UUID) -> LLMProfile`

- Creates with `owner_tenant_id = tenant_id`
- Status starts as 'draft'
- Calls `_write_history`, `_write_audit`

`async update_byollm_slot(tenant_id: UUID, profile_id: UUID, slot: SlotName, library_id: UUID, actor_id: UUID) -> LLMProfile`

- Validates ownership: `profile.owner_tenant_id == tenant_id`, raises `OwnershipError` otherwise
- Validates library entry: `owner_tenant_id == tenant_id` (tenant can only use their own entries)
- Calls `assign_slot` internal logic after ownership checks

`async activate_byollm_profile(tenant_id: UUID, profile_id: UUID, actor_id: UUID) -> None`

- Validates ownership
- Required slots: chat, intent, agent must all be assigned and their library entries must have `test_passed_at IS NOT NULL`
- Vision slot is optional for activation
- Updates status to 'active', sets tenant's llm_profile_id
- Calls `_write_audit` with 'byollm_activated'
- Calls `_invalidate_cache(tenant_id=tenant_id)`

#### Internal methods

`async _write_history(profile_id, actor_id, action, previous_state, new_state) -> None`

- Inserts into `llm_profile_history`

`async _write_audit(profile_id, tenant_id, actor_id, event_type, details) -> None`

- Inserts into `llm_profile_audit_log`
- Never raises — audit failure is logged but does not roll back the main operation

`async _invalidate_cache(profile_id: UUID | None = None, tenant_id: UUID | None = None) -> None`

- If tenant_id given: DELETE `mingai:{tenant_id}:llm_profile:effective`
- If profile_id given: find all tenants using this profile, invalidate each
- If neither given (global flush): use SCAN + DEL on pattern `mingai:*:llm_profile:effective`
- Never raises — cache invalidation failure is logged but does not roll back

### Traffic Split Weight Validation (GAP-07)

When `assign_slot` or any update includes a `traffic_split` payload, validate:

```python
import math

def _validate_traffic_split(split: list[dict]) -> None:
    if not split:
        return  # empty = no splitting, single model
    total = 0
    for entry in split:
        w = entry.get("weight", 0)
        if not math.isfinite(w):  # rejects NaN and Inf
            raise ValueError("Traffic split weight must be a finite number")
        if w <= 0:
            raise ValueError("Traffic split weight must be positive")
        total += w
    if abs(total - 100) > 0.01:
        raise ValueError(f"Traffic split weights must sum to 100 (got {total})")
    # Validate all library_entry_ids exist and are published
    for entry in split:
        library_id = entry.get("library_entry_id")
        # DB check: library entry exists, status == 'published', has test_passed_at
```

`_validate_traffic_split` is called from `assign_slot` and `update_profile` when traffic split is present. Deprecated or disabled entries in traffic splits are rejected. `math.isfinite()` check is mandatory — `NaN` weight bypasses all numeric comparisons silently.

### SlotName type

```python
from typing import Literal
SlotName = Literal["chat", "intent", "vision", "agent"]
```

Embedding slots (doc_embedding, kb_embedding) are NOT valid SlotName values. They are excluded from profiles entirely.

### Error classes

All errors in `src/backend/app/modules/llm_profiles/exceptions.py`:

- `ProfileDeprecationBlockedError(profile_id, tenant_count)`
- `PlanTierInsufficientError(tenant_plan, required_plan)`
- `SlotNotEligibleError(slot, library_id, eligible_slots)`
- `LibraryEntryNotPublishedError(library_id, current_status)`
- `LibraryEntryNotTestedError(library_id)`
- `OwnershipError(resource_type, resource_id, requesting_tenant_id)`

## Acceptance Criteria

- `assign_slot` with an unpublished library entry raises `LibraryEntryNotPublishedError`
- `assign_slot` with a published but untested entry raises `LibraryEntryNotTestedError`
- `assign_slot` when `eligible_slots` excludes target slot raises `SlotNotEligibleError`
- `set_platform_default` executes single atomic transaction (no intermediate state)
- `deprecate_profile` raises `ProfileDeprecationBlockedError` when tenants are using the profile
- `activate_byollm_profile` raises an error if chat, intent, or agent slot is unassigned or untested
- `update_byollm_slot` raises `OwnershipError` when profile does not belong to requesting tenant
- Every mutation writes both a history record and an audit log entry
- Cache invalidation is called on every mutation (failure does not roll back mutation)
- Embedding slots cannot be assigned via `assign_slot`

## Dependencies

- 27 (schema) — tables must exist
- 28 (SSRF middleware) — not directly imported here, but BYOLLM endpoint (todo 33) depends on both
