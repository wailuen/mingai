---
id: 33
title: LLM Profile Redesign — Phase B6+B7: Tenant Admin API Rewrite + BYOLLM API
status: pending
priority: high
phase: B
estimated_days: 1.5
---

# LLM Profile Redesign — Phase B6+B7: Tenant Admin API Rewrite + BYOLLM API

## Context

Two tenant-facing API areas are rewritten here. The first is the existing `admin/llm-config` endpoint which currently exposes raw model settings — it is rewritten to return the effective resolved profile (read-only per slot, no overrides). The second is a new BYOLLM API for Enterprise tenants to manage their own library entries and profiles.

These are grouped in one todo because they share the plan tier middleware (todo 32), share the same security requirement (api_key never returned), and are both deployed together to make the tenant-facing LLM configuration experience complete.

## Scope

Files to modify:

- `src/backend/app/modules/admin/llm_config.py` — rewrite to v2 (three endpoints replacing old structure)

Files to create:

- `src/backend/app/modules/admin/byollm/routes.py` — new BYOLLM sub-module
- `src/backend/app/modules/admin/byollm/__init__.py`

## Requirements

### B6: Tenant Admin LLM Config API (rewrite)

**Old behaviour** (to be replaced): exposed raw `provider`, `primary_model`, `intent_model` fields directly. Tenants could configure per-model settings.

**New behaviour**: read-only profile view + profile selector.

```
GET /admin/llm-config
```

- Calls `service.get_effective_profile(tenant_id)` → ProfileResolver
- Returns `EffectiveProfileResponse`:
  ```json
  {
    "profile_id": "...",
    "profile_name": "Standard GPT-5",
    "is_byollm": false,
    "slots": {
      "chat": { "model_name": "gpt-5.2-chat", "provider": "azure_openai" },
      "intent": { "model_name": "gpt-5-mini", "provider": "azure_openai" },
      "vision": { "model_name": "gpt-4o", "provider": "azure_openai" },
      "agent": { "model_name": "gpt-5.2-chat", "provider": "azure_openai" }
    }
  }
  ```
- Never returns endpoint_url, api_key, or api_version in this response

```
GET /admin/llm-config/available-profiles
```

- Returns platform profiles available for the tenant's plan tier
- Filters: `owner_tenant_id IS NULL AND status = 'active' AND plan_tier = ANY(plan_tiers)`
- Each item: `{id, name, description, plan_tiers, slot_summary, estimated_cost_per_1k_queries}`
- `estimated_cost_per_1k_queries` is a display hint stored in the profile (set by platform admin), not calculated dynamically

```
POST /admin/llm-config/select-profile
```

- Decorated with `@require_plan_tier(minimum="professional")`
- Body: `{profile_id: UUID}`
- Calls `service.select_profile(tenant_id, profile_id, actor_id)`
- Invalidates cache for the tenant
- Returns 200 with new effective profile (same shape as GET)
- Starter tenants receive 403 before any DB access

No slot override endpoints exist. Tenants cannot mix slots.

### B7: BYOLLM API

All endpoints decorated with `@require_plan_tier(minimum="enterprise")`.

#### Library entry management

```
GET /admin/byollm/library-entries
```

- Returns entries where `owner_tenant_id = requesting_tenant_id`
- Response: `[{id, name, provider, endpoint_url, api_version, model_name, api_key_last4, status, test_passed_at, capabilities}]`
- `api_key_encrypted`: NEVER in response

```
POST /admin/byollm/library-entries
```

- Body: `{name, provider, endpoint_url, api_version, model_name, api_key, capabilities}`
- Validation sequence:
  1. `validate_llm_endpoint(endpoint_url)` — raises 400 with plain language if SSRF
  2. Encrypt `api_key` → store only `api_key_encrypted` and `api_key_last4`
  3. Set `owner_tenant_id = tenant_id`, `status = 'draft'`
- Returns 201 with entry (api_key NOT in response, only api_key_last4)

```
PATCH /admin/byollm/library-entries/{id}
```

- Validates ownership
- Allows updating: name, endpoint_url (re-validates SSRF), api_version, model_name, capabilities
- Does NOT allow changing api_key via this endpoint (use rotate-key instead)

```
PATCH /admin/byollm/library-entries/{id}/rotate-key
```

- Body: `{api_key: "new_key"}`
- Validates ownership
- Re-encrypts key, updates api_key_last4, resets test_passed_at to NULL (key change invalidates previous test)
- Returns updated entry (api_key_last4 shown, no full key)

```
POST /admin/byollm/library-entries/{id}/test
```

- Validates ownership
- Calls `validate_llm_endpoint(entry.endpoint_url)` first
- Sends a minimal test prompt to the entry
- On success: sets `test_passed_at = NOW()`, `status = 'published'`
- On failure: sets `test_passed_at = NULL`, `status = 'draft'`, returns 200 with `{success: false, error: plain_language_message}`
- Authentication failure → "Authentication failed — check your API key"
- SSRF validation failure → "Endpoint address is not permitted"
- Timeout → "Connection timed out — check the endpoint URL"
- Response body contents are NEVER stored or returned

```
DELETE /admin/byollm/library-entries/{id}
```

- Validates ownership
- Blocked if entry is assigned to any BYOLLM profile slot: returns 409
- Soft deletes (status = 'disabled'), does not hard delete

#### Profile management

```
GET /admin/byollm/profiles
```

- Returns profiles where `owner_tenant_id = tenant_id`

```
POST /admin/byollm/profiles
```

- Body: `{name, description}`
- Calls `service.create_byollm_profile(tenant_id, req, actor_id)`

```
PATCH /admin/byollm/profiles/{id}/slots/{slot}
```

- Body: `{library_id}`
- Calls `service.update_byollm_slot(tenant_id, profile_id, slot, library_id, actor_id)`
- Validates that library_id belongs to this tenant

```
POST /admin/byollm/profiles/{id}/activate
```

- Calls `service.activate_byollm_profile(tenant_id, profile_id, actor_id)`
- Returns 422 with clear message if required slots not all assigned+tested

```
DELETE /admin/byollm/profiles/{id}
```

- Validates ownership
- Blocked if profile is currently active for the tenant (tenant must switch away first)
- Soft delete (status = 'deprecated')

### Security invariants

- `api_key_encrypted` NEVER appears in any response body (platform or tenant routes)
- `api_key_last4` is the only key-related field returned
- Ownership checks on every BYOLLM endpoint mutation before any DB operation
- SSRF validation on every endpoint URL save and test

### Legacy Endpoint Deprecation (GAP-13)

The existing `llm_config.py` is being rewritten — but the old `useLLMConfig` hook in the frontend still points to the old response shape. To avoid breaking the frontend during the API transition:

1. The rewritten `GET /admin/llm-config` endpoint MUST include a `_deprecated_model_source` field in the response that returns the old `model_source` string value ("library" or "byollm") for backwards compatibility during the frontend transition.
2. This compat field is removed in Phase D once the frontend is updated to use the new response shape.
3. The existing `PATCH /admin/llm-config` (old model_source update) is removed entirely — replaced by `POST /admin/llm-config/select-profile`.
4. The existing `GET /admin/llm-config/library-options` endpoint is preserved temporarily and now delegates to `GET /admin/llm-config/available-profiles` (redirect or alias).

Document the deprecation clearly in the rewritten `llm_config.py` with `# DEPRECATED: remove in Phase D` comments.

## Acceptance Criteria

- `GET /admin/llm-config` returns model names for each slot without any key or endpoint fields
- `POST /admin/llm-config/select-profile` returns 403 for Starter plan tenants
- `POST /admin/byollm/library-entries` with a private IP endpoint returns 400 with plain language
- `POST /admin/byollm/library-entries/{id}/test` with wrong API key returns `{success: false, error: "Authentication failed — check your API key"}`
- `GET /admin/byollm/library-entries` never returns api_key_encrypted
- `POST /admin/byollm/profiles/{id}/activate` returns 422 when chat slot unassigned
- BYOLLM endpoints return 403 for Professional plan tenants (plan tier middleware active)
- Cross-tenant isolation: tenant A cannot access tenant B's library entries (returns 404 not 403)

## Dependencies

- 27 (schema)
- 28 (SSRF middleware) — imported for endpoint validation
- 29 (LLMProfileService) — all mutations via service
- 32 (plan tier middleware)
