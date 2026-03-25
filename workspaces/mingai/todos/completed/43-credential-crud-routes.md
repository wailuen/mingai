---
id: TODO-43
title: CRUD routes for platform credentials (credentials_routes.py + router registration)
status: pending
priority: high
phase: A2
dependencies: [TODO-41, TODO-42]
---

## Goal

Create `app/modules/platform/credentials_routes.py` with five endpoints for storing, listing, rotating, deleting, and health-checking platform credentials. Register the new router in `app/api/router.py`. All routes require `require_platform_admin`.

## Context

There are currently no HTTP endpoints for managing platform credentials. The Template Studio Panel Credentials tab (TODO-50) and the publish gate (TODO-48) both depend on these routes. The API contract is defined in `workspaces/mingai/01-analysis/19-platform-credential-vault/02-requirements-and-adr.md`.

## Implementation

### New file: `app/modules/platform/credentials_routes.py`

Base path: `/platform/templates/{template_id}/credentials`

All five routes must:
- Import and use the `require_platform_admin` dependency (follow the pattern in the existing `app/modules/platform/routes.py`)
- Use the `CredentialManager` (dependency-injected or imported singleton — follow existing pattern)
- Obtain a database session for metadata reads/writes

#### POST — store credential (FR-01)

```
POST /platform/templates/{template_id}/credentials
```

Request body:
```json
{
  "key": "PITCHBOOK_API_KEY",
  "value": "sk-...",
  "description": "optional",
  "allowed_domains": ["api.pitchbook.com"],
  "injection_config": {"type": "header", "header_name": "X-Api-Key"}
}
```

`injection_config` is optional; defaults to `{"type": "header", "header_name": "Authorization", "header_format": "{value}"}`. Validate that `type` is one of `"bearer"`, `"header"`, `"query_param"`, `"basic_auth"` — 400 on unknown type.

All credential endpoints MUST set response headers `Cache-Control: no-store` and `Pragma: no-cache`.

Steps:
1. Validate `key` matches `^[a-zA-Z][a-zA-Z0-9_]{1,63}$` (note: starts with letter, per API contract)
2. Validate `value` is non-empty — 400 if blank
3. Validate `allowed_domains` is a non-empty array — 400 if empty array provided
4. Check `agent_templates` record exists — 404 if not
5. Check `platform_credential_metadata` for existing active row with same `(template_id, key)` — 409 if found
6. Call `credential_manager.set_platform_credential(..., injection_config=injection_config)`
7. Insert row into `platform_credential_metadata` (id, template_id, key, allowed_domains, description, version=1, injection_config, created_by=current_user_id)
8. Insert audit record: action=`store`, actor_id=current_user_id, source_ip from request
9. Return 201 with `{key, template_id, description, version: 1, created_at, created_by}`

#### GET — list keys (FR-02)

```
GET /platform/templates/{template_id}/credentials
```

Steps:
1. Check `agent_templates` record exists — 404 if not
2. Query `platform_credential_metadata WHERE template_id = ? AND deleted_at IS NULL`
3. Return 200 with `{template_id, credentials: [{key, description, created_at, updated_at, created_by, version, injection_config}]}`
4. Empty array (not 404) when no credentials exist
5. Never return values

#### PUT — rotate credential (FR-03)

```
PUT /platform/templates/{template_id}/credentials/{key}
```

Request body: `{ "value": "sk-newvalue..." }`
Required header: `If-Match: {version}` (integer as string)

Steps:
1. Validate `If-Match` header is present and is a valid integer — 400 if absent/invalid
2. Fetch active metadata row for `(template_id, key)` — 404 if not found
3. If `deleted_at IS NOT NULL` — 400 "Cannot rotate a deleted credential"
4. Compare `If-Match` value against `metadata.version` — 409 if mismatch (optimistic concurrency, risk C-03)
5. Call `credential_manager.set_platform_credential(...)` with the new value
6. Update metadata row: `version = version + 1`, `updated_at = now()`, `updated_by = current_user_id`
7. Insert audit record: action=`rotate`, actor_id=current_user_id
8. Return 200 with `{key, template_id, updated_at, updated_by, version}` (version is the new incremented value)

#### DELETE — soft-delete credential (FR-04)

```
DELETE /platform/templates/{template_id}/credentials/{key}?force=false
```

Steps:
1. Fetch active metadata row — 404 if not found
2. Count active agent deployments that reference this template AND have `auth_mode = 'platform_credentials'`
3. If count > 0 AND `force` is False: return 409 `{error: "active_agents", affected_agent_count: N, force_available: true}`
4. Call `credential_manager.delete_platform_credential(...)`
5. Update metadata row: `deleted_at = now()`, `deleted_by = current_user_id`, `retention_until = now() + 30 days`
6. Insert audit record: action=`delete`, actor_id=current_user_id, metadata=`{affected_agents: N}`
7. Return 200 `{key, deleted_at, retention_until, affected_agents: N}`

#### GET /health — completeness check (FR-06, FR-07)

```
GET /platform/templates/{template_id}/credentials/health
```

Steps:
1. Fetch `agent_templates` record — 404 if not found
2. If `required_credentials` is null or empty: return `{status: "not_required", template_id, required_credentials: [], keys: {}}`
3. For each key in `required_credentials`:
   - Check `platform_credential_metadata` for active row → "stored"
   - Check for soft-deleted row (deleted_at IS NOT NULL) → "revoked"
   - No row at all → "missing"
4. Derive overall status: all "stored" → "complete"; any "missing" or "revoked" → "incomplete"
5. Return `{template_id, required_credentials: [...], status, keys: {KEY: "stored"|"missing"|"revoked"}}`

Note: `GET /health` must be declared before `/{key}` in the router to avoid path parameter shadowing.

### Router registration

In `app/api/router.py`:
- Import the new `credentials_router` from `app/modules/platform/credentials_routes`
- Register with prefix `/platform/templates/{template_id}` or the full path — follow the existing platform router pattern

## Acceptance Criteria

- [ ] `POST` returns 201 on first store; 409 on duplicate active key; 404 on missing template; 400 on empty value
- [ ] `POST` returns `version: 1` in the 201 response body
- [ ] `POST` with empty `allowed_domains: []` returns 400
- [ ] `POST` with unknown `injection_config.type` returns 400
- [ ] `POST` never echoes the credential value back in the response
- [ ] `GET` returns empty `credentials` array (not 404) when no keys are stored
- [ ] `GET` excludes soft-deleted rows by default
- [ ] `GET` list includes `version` and `injection_config` per credential
- [ ] `PUT` returns 409 when `If-Match` version does not match current metadata version
- [ ] `PUT` returns 400 when trying to rotate a soft-deleted credential
- [ ] `PUT` returns the incremented `version` in the 200 response
- [ ] `DELETE` returns 409 with `affected_agent_count` when active agents exist and `force=false`
- [ ] `DELETE` proceeds when `?force=true` regardless of active agent count
- [ ] `DELETE` sets `retention_until = deleted_at + 30 days`
- [ ] `GET /health` returns `status: "not_required"` when `required_credentials` is empty
- [ ] `GET /health` returns per-key `stored|missing|revoked` correctly
- [ ] All five routes require platform_admin role — tenant admin or unauthenticated requests return 403/401
- [ ] All write operations append a row to `platform_credential_audit`
- [ ] All credential endpoints return `Cache-Control: no-store` and `Pragma: no-cache` response headers
- [ ] Routes are registered in `app/api/router.py` and accessible under `/api/v1/`
- [ ] `GET /health` path is declared before `/{key}` to prevent route shadowing
