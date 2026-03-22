---
id: 32
title: LLM Profile Redesign — Phase B5: Platform Profile API + Plan Tier Middleware
status: pending
priority: high
phase: B
estimated_days: 1.5
---

# LLM Profile Redesign — Phase B5: Platform Profile API + Plan Tier Middleware

## Context

The platform admin needs a full CRUD API to manage profiles — create, assign slots, set the default, test, deprecate, and view tenant usage. These endpoints are gated behind the `platform_admin` role. The plan tier enforcement middleware also lives here and gates tenant-facing mutations (profile selection = Professional minimum, BYOLLM = Enterprise minimum).

## Scope

Files to create:

- `src/backend/app/modules/llm_profiles/routes.py` — new module under llm_profiles
- `src/backend/app/core/middleware/plan_tier.py` — plan tier enforcement decorator

Files to modify:

- Wherever the FastAPI router is assembled (likely `src/backend/app/main.py` or a router registry) — register the new routes

## Requirements

### Plan Tier Middleware (plan_tier.py)

`@require_plan_tier(minimum: str)` decorator for route handlers.

- Extracts `plan_tier` claim from the JWT (already decoded by existing auth middleware)
- Plan order: `starter < professional < enterprise`
- If tenant's plan_tier < minimum: returns 403 with body `{"error": "plan_upgrade_required", "minimum_plan": minimum, "current_plan": current}`
- Only applies to mutation endpoints (POST, PATCH, PUT, DELETE) — GET endpoints are open to all authenticated tenants
- Validates the JWT claim server-side on every mutation — does NOT trust a cached/stale claim

### Platform Profile API Routes

All routes require: authenticated platform admin role (existing RBAC middleware handles this).

```
GET    /platform/llm-profiles
```

- Calls `service.list_platform_profiles(plan_tier=query_param)`
- Returns list with summary per profile (id, name, status, is_platform_default, plan_tiers, tenant_count, slot names)

```
POST   /platform/llm-profiles
```

- Body: `{name, description, plan_tiers: []}`
- Calls `service.create_profile(req, actor_id)`
- Returns 201 with created profile

```
GET    /platform/llm-profiles/{id}
```

- Returns full profile detail including slot assignments (library entry names, not keys), plan_tiers, status

```
PATCH  /platform/llm-profiles/{id}
```

- Partial update: name, description, plan_tiers only
- Calls `service.update_profile`

```
PUT    /platform/llm-profiles/{id}/slots
```

- Atomic assign all 4 slots in one request
- Body: `{chat: {library_id, params}, intent: {library_id, params}, vision: {library_id, params}, agent: {library_id, params}}`
- Vision and agent are optional (nullable). Chat and intent are required.
- Calls `service.assign_slot` for each non-null slot in a single transaction

```
PATCH  /platform/llm-profiles/{id}/slots/{slot}
```

- Assign single slot: `{library_id, params}`
- Calls `service.assign_slot`
- Returns updated profile

```
DELETE /platform/llm-profiles/{id}/slots/{slot}
```

- Unassign a slot: sets `{slot}_library_id = NULL` and `{slot}_params = {}`
- Blocked if slot is chat or intent (required slots cannot be unassigned from an active profile)
- Calls `service.update_profile` with null slot

```
POST   /platform/llm-profiles/{id}/set-default
```

- No body required
- Calls `service.set_platform_default(profile_id, actor_id)`
- Returns 200 with `{"previous_default_id": ..., "new_default_id": ...}`

```
DELETE /platform/llm-profiles/{id}
```

- Semantically: deprecate (not hard delete)
- Calls `service.deprecate_profile`
- If `ProfileDeprecationBlockedError`: returns 409 with `{"error": "profile_in_use", "tenant_count": N, "message": "Remove this profile from N tenants before deprecating"}`

```
POST   /platform/llm-profiles/{id}/test
```

- Triggers a canned test prompt through each assigned slot
- Returns per-slot results: `{slot: {latency_ms, model_name, token_count, success, error_message}}`
- Vision slot sends a 1x1 PNG if assigned
- Max 10s per slot, parallel execution across slots
- Results NOT stored (test is ephemeral)

```
GET    /platform/llm-profiles/{id}/tenants
```

- Returns list of tenants currently using this profile: `[{tenant_id, name, plan_tier, selected_at}]`
- Paginated: default 50, max 200

```
GET    /platform/llm-profiles/available-models/{slot}
```

- Returns llm_library entries where `capabilities.eligible_slots` contains `slot` and status = 'published'
- Ordered by: health_status (healthy first), then name
- Response includes: `{id, name, provider, model_name, health_status, health_checked_at, test_passed_at}`
- api_key fields: NEVER returned

### Security invariants

- `api_key_encrypted`, `api_key_hash` NEVER appear in any response body from platform routes
- Only `api_key_last4` is returned to indicate a key is configured
- Platform admin cannot view or export tenant BYOLLM credentials

## Acceptance Criteria

- `GET /platform/llm-profiles/available-models/chat` returns only entries with 'chat' in eligible_slots
- `POST /platform/llm-profiles/{id}/set-default` is atomic (no intermediate state between old and new default)
- `DELETE /platform/llm-profiles/{id}` returns 409 when tenants are active, not 500
- `POST /platform/llm-profiles/{id}/test` returns results for each configured slot within 10s
- `@require_plan_tier(minimum="professional")` returns 403 for Starter tenants on select-profile endpoint
- `@require_plan_tier(minimum="enterprise")` returns 403 for Professional tenants on BYOLLM endpoints
- No API key fields in any platform API response (verified by integration tests)
- Routes registered and reachable (confirmed by `GET /openapi.json`)

## Dependencies

- 27 (schema)
- 29 (LLMProfileService)
- 30 (ProfileResolver) — test endpoint uses resolver to verify effective resolution
