---
id: 34
title: LLM Profile Redesign — Phase B Tests: Security + Resolution + Integrity
status: completed
priority: high
phase: B
estimated_days: 1.5
---

# LLM Profile Redesign — Phase B Tests: Security + Resolution + Integrity

## Context

The backend test suite for the LLM Profile redesign. Grouped into three areas: security tests (SSRF, credential handling, cross-tenant isolation, plan tier bypass), resolution tests (cache tiers, fallback behaviour, Redis failure), and profile integrity tests (slot validation, deprecation logic, BYOLLM activation). All tests use real infrastructure (real DB, real Redis) per the project's no-mock-in-tier-2 rule.

## Scope

Files to create:

Security tests:

- `tests/integration/test_tier_bypass_starter.py`
- `tests/integration/test_tier_bypass_professional.py`
- `tests/integration/test_byollm_cross_tenant_isolation.py`
- `tests/integration/test_credential_never_returned.py`

(SSRF tests are in todo 28)

Resolution tests:

- `tests/integration/test_resolution_platform_profile.py`
- `tests/integration/test_resolution_byollm_profile.py`
- `tests/integration/test_resolution_default_fallback.py`
- `tests/integration/test_resolution_redis_failure.py`
- `tests/integration/test_resolution_null_slot.py`
- `tests/integration/test_cache_invalidation_on_profile_update.py`
- `tests/integration/test_cache_invalidation_on_library_deprecate.py`

Profile integrity tests:

- `tests/integration/test_slot_assignment_validation.py`
- `tests/integration/test_profile_deprecation_blocked_if_active.py`
- `tests/integration/test_byollm_activation_requires_required_slots.py`
- `tests/integration/test_concurrent_profile_update.py`

## Requirements

### Security tests

`test_tier_bypass_starter.py`:

- Starter tenant calls `POST /admin/llm-config/select-profile` → expects 403
- Starter tenant calls any BYOLLM endpoint → expects 403
- JWT with `plan_tier=starter` is not re-validated against DB on GET (performance), IS re-validated on mutations

`test_tier_bypass_professional.py`:

- Professional tenant calls any BYOLLM endpoint → expects 403
- Professional tenant calls `POST /admin/llm-config/select-profile` → expects 200

`test_byollm_cross_tenant_isolation.py`:

- Create library entry for tenant A
- Tenant B attempts `GET /admin/byollm/library-entries/{id_from_tenant_A}` → expects 404 (not 403)
- Tenant B attempts `PATCH /admin/byollm/library-entries/{id_from_tenant_A}` → expects 404
- Tenant B attempts to create BYOLLM profile with `library_id` from tenant A → expects 422 with ownership error
- 404 not 403: revealing that a resource exists is itself an information leak

`test_credential_never_returned.py`:

- Create library entry with a test API key
- `GET /admin/byollm/library-entries` response JSON: assert `api_key_encrypted` absent, `api_key` absent
- `GET /admin/byollm/library-entries/{id}` response JSON: same assertion
- `POST /admin/byollm/library-entries` response JSON: same assertion
- `POST /admin/byollm/library-entries/{id}/test` response JSON: no key fields
- `GET /platform/llm-profiles` response JSON: no key fields in any nested object
- `GET /platform/llm-profiles/{id}` response JSON: same assertion
- Helper: `assert_no_credential_fields(response_json)` — recursive check of entire JSON tree

### Resolution tests

`test_resolution_platform_profile.py`:

- Create tenant with `llm_profile_id = platform_profile_id`
- Call `ProfileResolver.resolve(tenant_id)`
- Assert returned `ResolvedProfile.profile_id == platform_profile_id`
- Assert `is_byollm == False`
- Assert each slot's `model_name` matches what was assigned in the profile

`test_resolution_byollm_profile.py`:

- Create tenant with BYOLLM profile active
- Call `ProfileResolver.resolve(tenant_id)`
- Assert `is_byollm == True`
- Assert slot entries have `owner_tenant_id == tenant_id`
- Assert `validate_tenant_ownership` returns True for tenant's own entries

`test_resolution_default_fallback.py`:

- Create tenant with `llm_profile_id = NULL`
- Set a platform profile as default (`is_platform_default = TRUE`)
- Call `ProfileResolver.resolve(tenant_id)`
- Assert the default profile is returned
- Remove the default → call resolver → assert `ProfileResolutionError` raised

`test_resolution_redis_failure.py`:

- Prime the in-memory LRU for a tenant
- Disconnect/mock Redis to be unavailable
- Call `ProfileResolver.resolve(tenant_id)` multiple times
- Assert: LRU hit on second call (no DB query), no exception propagated
- Assert: after LRU TTL expires and Redis still down, DB is queried (third tier)

`test_resolution_null_slot.py`:

- Create profile with chat assigned but intent = NULL
- When `InstrumentedLLMClient._resolve_adapter(slot="intent")` is called
- Assert `SlotNotConfiguredError` raised (not a KeyError or None fallback)

`test_cache_invalidation_on_profile_update.py`:

- Resolve a profile → confirm Redis key exists
- Call `service.update_profile` (trigger cache invalidation)
- Assert Redis key deleted for all tenants using the profile
- Assert next resolver call hits DB (not Redis)

`test_cache_invalidation_on_library_deprecate.py`:

- Assign library entry to a slot in a profile
- Resolve the profile → confirm cache populated
- Deprecate the library entry (via service or direct DB)
- Assert cache invalidated for all affected tenants
- Note: the resolver itself does not deprecate library entries; this tests the invalidation side-effect

### Profile integrity tests

`test_slot_assignment_validation.py`:

- Attempt `assign_slot` with unpublished library entry → expect `LibraryEntryNotPublishedError`
- Attempt `assign_slot` with published but untested entry → expect `LibraryEntryNotTestedError`
- Attempt `assign_slot` with entry lacking the slot in `eligible_slots` → expect `SlotNotEligibleError`
- All three error types carry enough context to be human-readable (library_id, slot name)

`test_profile_deprecation_blocked_if_active.py`:

- Create platform profile, assign to 3 tenants
- Call `service.deprecate_profile(profile_id)`
- Assert `ProfileDeprecationBlockedError` raised with `tenant_count = 3`
- Remove tenants from profile (update them to use another profile)
- Call `service.deprecate_profile(profile_id)` again → expect success, status = 'deprecated'

`test_byollm_activation_requires_required_slots.py`:

- Create BYOLLM profile, assign chat only (no intent, no agent)
- Call `service.activate_byollm_profile` → expect error (missing intent + agent)
- Assign intent and agent, but do not test them
- Call again → expect error (entries not tested)
- Test all three entries
- Call again → expect success

`test_concurrent_profile_update.py`:

- Simulate two concurrent requests to `set_platform_default` for different profiles
- Assert only one profile ends up as `is_platform_default = TRUE` (atomic swap integrity)
- Use `asyncio.gather` or real concurrent DB sessions

## Acceptance Criteria

- All 15 test files exist and contain at least the test cases described
- No test uses mocking (real DB, real Redis per project testing rules)
- All tests pass in isolation and in parallel
- `assert_no_credential_fields` helper is reusable across test files
- Concurrent profile update test demonstrates no double-default state is possible

## Dependencies

- 27 (schema)
- 28 (SSRF middleware)
- 29 (LLMProfileService)
- 30 (ProfileResolver)
- 31 (InstrumentedLLMClient)
- 32 (platform API + plan tier middleware)
- 33 (tenant admin + BYOLLM API)
