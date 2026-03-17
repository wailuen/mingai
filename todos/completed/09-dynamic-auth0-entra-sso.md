# 09 — Dynamic Auth0 Azure Entra SSO

**Generated**: 2026-03-17
**Last updated**: 2026-03-17 (all items complete)
**Phase**: 3.5 (post Phase 3 — incremental SSO feature)
**Numbering**: ENTRA-001 through ENTRA-011
**Stack**: FastAPI + Auth0 Management API + Azure AD (waad) + PostgreSQL + Next.js + TypeScript
**Source context**: `workspaces/mingai/01-analysis/01-research/38-auth0-sso-architecture.md`, `src/backend/app/modules/admin/sso_saml.py`, `src/backend/app/modules/admin/sso_oidc.py`

---

## Overview

The mingai SaaS platform uses Auth0 as the identity broker for enterprise SSO. For Option B per-tenant SSO, each enterprise customer with Azure AD must get their own Auth0 enterprise connection. Currently the SAML, OIDC, Google Workspace, and Okta wizards already dynamically create Auth0 connections via Management API — but Azure Entra (strategy: `waad`) is missing this self-service capability.

The first Entra connection (`mingai-entra`, `con_gZzXoNvQ58MWRJMa`) was **manually** created for TPC Group / IMC Industrial Group (domain `imcindustrialgroup.com`). Every subsequent enterprise Azure AD customer requires the same manual Auth0 intervention from the mingai team — blocking onboarding at scale.

This feature implements a self-service wizard that mirrors the existing SAML/OIDC patterns: a tenant admin enters their Azure AD App Registration credentials once, and the platform automatically creates a scoped Auth0 Entra connection, enables it on the tenant's Auth0 Organization, and persists metadata. Client secrets are sent to Auth0 once and never stored in mingai's database.

**Key constraint**: Client secrets must NOT be stored in `tenant_configs` or any mingai DB table. They are transmitted to Auth0 once during connection creation and discarded from mingai's memory.

---

## Backend Items

### ENTRA-001: POST /admin/sso/entra/configure — initial connection creation

**Status**: COMPLETE
**Effort**: 6h
**Depends on**: P3AUTH-001 (Auth0 tenant + Management API), P3AUTH-003 (SSO config API), P3AUTH-021 (Client Credentials flow)
**Description**: New module `src/backend/app/modules/admin/sso_entra.py`. Implements `POST /admin/sso/entra/configure`. Validates request inputs, checks for duplicate configuration, creates an Auth0 `waad` (Windows Azure Active Directory) enterprise connection via Management API, enables the connection on the tenant's Auth0 Organization, stores connection metadata (never the secret) in `tenant_configs`, writes audit log, and returns the new `connection_id` plus test URL.

Request body:

```json
{ "client_id": "<UUID>", "client_secret": "<string>", "domain": "contoso.com" }
```

Auth0 connection payload:

```json
{
  "name": "entra-{tenant_id[:8]}",
  "strategy": "waad",
  "options": {
    "client_id": "<client_id>",
    "client_secret": "<client_secret>",
    "tenant_domain": "<domain>",
    "waad_protocol": "openid-connect",
    "app_id": "<client_id>"
  }
}
```

After creating the connection, read `auth0_org_id` from `tenant_configs` and call `POST /api/v2/organizations/{org_id}/enabled_connections` with `{ "connection_id": "<id>", "assign_membership_on_login": true }`.

Store in `tenant_configs` via `_upsert_sso_provider_config_db()`:

```json
{
  "provider_type": "entra",
  "auth0_connection_id": "<connection_id>",
  "enabled": true,
  "domain": "<domain>",
  "client_id": "<client_id>"
}
```

**Acceptance criteria**:

- [x] Request body validated: `domain` matches regex `^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$`, `client_id` is valid UUID format, `client_secret` non-empty
- [x] `_get_any_sso_config_db()` checked before creation — returns HTTP 409 if tenant already has any SSO config
- [x] `management_api_request("POST", "connections", {...})` called with `strategy: "waad"` and correct options payload
- [x] `auth0_org_id` read from `tenant_configs` and connection enabled via `POST organizations/{org_id}/enabled_connections`
- [x] `tenant_configs` row upserted with `provider_type="entra"`, `auth0_connection_id`, `enabled=True`, `domain`, `client_id` — `client_secret` is NOT present in stored data
- [x] Audit log entry written: `action="sso.entra.configured"`, `actor=<requesting user>`, `metadata={"domain": <domain>, "connection_id": <id>}`
- [x] Response: `{ "connection_id": "con_xxx", "test_url": "https://{AUTH0_DOMAIN}/authorize?...", "domain": "<domain>" }` — `client_secret` not in response
- [x] `require_tenant_admin` enforced
- [x] HTTP 502 returned if Auth0 Management API call fails (propagate Auth0 error message)
- [x] If `auth0_org_id` not found in `tenant_configs`: log warning, continue — connection is created but org wiring is deferred (do not fail the whole request)

---

### ENTRA-002: PATCH /admin/sso/entra/configure — update existing connection

**Status**: COMPLETE
**Effort**: 3h
**Depends on**: ENTRA-001
**Description**: Implements `PATCH /admin/sso/entra/configure` for re-keying (rotating client secret) or updating the tenant domain of an existing Auth0 Entra connection. Fetches the existing `auth0_connection_id` from `tenant_configs`, calls `PATCH /api/v2/connections/{connection_id}` on Auth0 with only the changed fields, updates `tenant_configs` if `domain` changed, and writes audit log.

Request body (all fields optional, at least one required):

```json
{ "client_secret": "<new secret>", "domain": "<new domain>" }
```

**Acceptance criteria**:

- [x] HTTP 404 returned if no existing Entra config found in `tenant_configs` for this tenant
- [x] HTTP 400 returned if request body contains neither `client_secret` nor `domain`
- [x] `management_api_request("PATCH", f"connections/{connection_id}", {"options": {...}})` called with only the provided fields
- [x] If `domain` updated: `tenant_configs` record updated with new domain value
- [x] `client_secret` never stored in `tenant_configs` even during re-key
- [x] Audit log entry written: `action="sso.entra.updated"`, metadata contains changed fields (domain if changed, `client_secret_rotated: true` if secret provided — never the actual secret value)
- [x] Response: updated provider config object (same shape as GET response — no secret field)
- [x] `require_tenant_admin` enforced
- [x] HTTP 502 returned if Auth0 PATCH call fails

---

### ENTRA-003: SSO enable/disable lifecycle for Entra connections

**Status**: COMPLETE
**Effort**: 4h
**Depends on**: ENTRA-001, P3AUTH-003
**Description**: Modify `patch_sso_connection_config()` in `src/backend/app/modules/admin/workspace.py` so that `PATCH /admin/sso/config` with `enabled=false` removes the Entra connection from the tenant's Auth0 Organization (without deleting the Auth0 connection itself), and re-enabling adds it back.

On disable (when existing config has `provider_type="entra"` and `auth0_connection_id` is set):

- `management_api_request("DELETE", f"organizations/{org_id}/enabled_connections/{connection_id}")`
- Update `tenant_configs`: set `enabled=false`

On re-enable:

- `management_api_request("POST", f"organizations/{org_id}/enabled_connections", {"connection_id": ..., "assign_membership_on_login": true})`
- Update `tenant_configs`: set `enabled=true`

For non-Entra provider types (saml, oidc, google, okta): existing behaviour is unchanged.

**Acceptance criteria**:

- [x] `PATCH /admin/sso/config` with `enabled=false` calls `DELETE organizations/{org_id}/enabled_connections/{connection_id}` when `provider_type="entra"`
- [x] `PATCH /admin/sso/config` with `enabled=true` on a previously-disabled Entra config calls `POST organizations/{org_id}/enabled_connections`
- [x] Auth0 connection object itself is NOT deleted on disable (preserve for re-enable)
- [x] `tenant_configs.enabled` field reflects new state after each toggle
- [x] If Management API call fails on toggle: return HTTP 502, do NOT update `tenant_configs` (keep consistent)
- [x] SAML, OIDC, Google, Okta toggle paths are not modified — only the Entra branch is new
- [x] Audit log entry written for each toggle: `action="sso.entra.disabled"` or `"sso.entra.enabled"`
- [x] `require_tenant_admin` enforced (inherited from existing `patch_sso_connection_config()`)

---

### ENTRA-004: POST /admin/sso/entra/test — return authorize URL for test SSO flow

**Status**: COMPLETE
**Effort**: 1h
**Depends on**: ENTRA-001
**Description**: Implements `POST /admin/sso/entra/test`. Fetches `auth0_connection_id` from `tenant_configs`, constructs and returns the Auth0 authorize URL that initiates a test SSO login via the Entra connection. Matches the pattern in `sso_saml.py`'s test endpoint.

Authorize URL format:

```
https://{AUTH0_DOMAIN}/authorize?connection={connection_id}&client_id={AUTH0_CLIENT_ID}&response_type=code&redirect_uri={FRONTEND_URL}/sso/callback&scope=openid%20profile%20email
```

**Acceptance criteria**:

- [x] HTTP 404 returned if no Entra config found in `tenant_configs` for this tenant
- [x] HTTP 404 returned if `enabled=false` on existing config (cannot test a disabled connection)
- [x] Response: `{ "test_url": "https://..." }` — same response shape as SAML test endpoint
- [x] URL contains correct `connection` param (Auth0 connection ID, not name), `client_id` from `AUTH0_CLIENT_ID` env var, `redirect_uri` from `FRONTEND_URL` env var
- [x] `require_tenant_admin` enforced

---

### ENTRA-005: Register sso_entra router in admin router

**Status**: COMPLETE
**Effort**: 0.5h
**Depends on**: ENTRA-001, ENTRA-002, ENTRA-004
**Description**: Include the new `sso_entra` router in the admin module's router registration. Follow the exact pattern used to register `sso_saml_router` and `sso_oidc_router` in `app/main.py` or the admin router include file. Confirm the prefix resolves to `/api/v1/admin/sso/entra/...` after the global `/api/v1` prefix is applied.

**Acceptance criteria**:

- [x] `POST /api/v1/admin/sso/entra/configure` returns 422 (not 404) on missing body — confirms routing is active
- [x] `PATCH /api/v1/admin/sso/entra/configure` reachable
- [x] `POST /api/v1/admin/sso/entra/test` reachable
- [x] No existing route registrations changed or broken
- [x] OpenAPI schema at `/docs` shows all three new Entra endpoints under the `admin` tag

---

### ENTRA-006: Unit tests for sso_entra.py

**Status**: COMPLETE
**Effort**: 5h
**Depends on**: ENTRA-001, ENTRA-002, ENTRA-003, ENTRA-004
**Description**: New file `tests/unit/test_entra_wizard.py`. All tests are Tier 1 (mock `management_api_request`, `_get_any_sso_config_db`, `_upsert_sso_provider_config_db`, `db`). Minimum 20 test cases covering the scenarios listed in the acceptance criteria.

**Acceptance criteria**:

- [x] Happy path configure: valid inputs → `management_api_request` called with correct `waad` payload → `_upsert_sso_provider_config_db` called → `connection_id` returned
- [x] Happy path configure: Auth0 Org enable step called with `org_id` fetched from `tenant_configs`
- [x] 409 returned when `_get_any_sso_config_db()` returns an existing config
- [x] 400 returned for invalid domain format (bare label, no TLD, spaces)
- [x] 400 returned for non-UUID `client_id`
- [x] 400 returned for empty `client_secret`
- [x] 502 returned when `management_api_request` raises on connection creation
- [x] 502 returned when `management_api_request` raises on org-enable step
- [x] Org enable: if `auth0_org_id` absent from `tenant_configs`, warning logged and function continues (connection still created, no 500)
- [x] Happy path PATCH update: `client_secret` provided → Management API PATCH called → `tenant_configs` domain unchanged
- [x] Happy path PATCH update: `domain` provided → `tenant_configs` domain updated
- [x] 404 returned on PATCH when no existing Entra config
- [x] 400 returned on PATCH with empty body
- [x] Disable lifecycle: `DELETE organizations/{org_id}/enabled_connections/{connection_id}` called when `enabled=false` set on Entra config
- [x] Re-enable lifecycle: `POST organizations/{org_id}/enabled_connections` called when `enabled=true` set on disabled Entra config
- [x] Non-Entra provider disable: org connection endpoints NOT called (SAML/OIDC disable path unchanged)
- [x] Test endpoint: returns `test_url` with correct query params
- [x] Test endpoint: 404 when config absent
- [x] Test endpoint: 404 when `enabled=false`
- [x] Secret hygiene: `client_secret` does NOT appear in any mock assertion on `_upsert_sso_provider_config_db` call args, nor in response body
- [x] Audit log mock: `audit_log` write called once on configure with `action="sso.entra.configured"`
- [x] All tests pass: `pytest tests/unit/test_entra_wizard.py -v`

---

## Frontend Items

### ENTRA-007: useConfigureEntra, useUpdateEntraConfig, useTestEntraConnection hooks

**Status**: COMPLETE
**Effort**: 2h
**Depends on**: ENTRA-001, ENTRA-002, ENTRA-004
**Description**: Add three new hooks to `src/web/lib/hooks/useSSO.ts`, following the exact pattern of the existing `useConfigureSAML`, `useConfigureOIDC`, `useConfigureGoogle`, and `useConfigureOkta` hooks already in that file.

- `useConfigureEntra()` — POST `/api/v1/admin/sso/entra/configure`
- `useUpdateEntraConfig()` — PATCH `/api/v1/admin/sso/entra/configure`
- `useTestEntraConnection()` — POST `/api/v1/admin/sso/entra/test`

Each hook returns `{ mutate, isLoading, error }`. `useConfigureEntra` and `useUpdateEntraConfig` invalidate the SSO config query on success. `useTestEntraConnection` returns `{ test_url }` which the UI opens in a new tab.

**Acceptance criteria**:

- [x] `useConfigureEntra` calls `POST /api/v1/admin/sso/entra/configure` with `{ client_id, client_secret, domain }`
- [x] `useUpdateEntraConfig` calls `PATCH /api/v1/admin/sso/entra/configure` with only the fields that changed
- [x] `useTestEntraConnection` calls `POST /api/v1/admin/sso/entra/test` and returns `test_url`
- [x] All three hooks follow the same error-handling pattern as existing SSO hooks (surface `error.message` to caller)
- [x] Existing hooks (`useConfigureSAML`, `useConfigureOIDC`, etc.) are not modified
- [x] 0 TypeScript errors after adding hooks

---

### ENTRA-008: Microsoft Entra ID tab in the SSO Setup Wizard UI

**Status**: COMPLETE
**Effort**: 6h
**Depends on**: ENTRA-007, P3AUTH-014
**Description**: Add "Microsoft Entra ID" as a selectable provider in `src/web/app/(platform)/workspace/settings/` SSO Setup Wizard. The wizard currently shows SAML, OIDC, Google Workspace, and Okta as provider options. Entra ID is added as a fifth option.

**Wizard step flow for Entra ID**:

1. **Instructions step** — Setup guide displayed as static content:
   - "In Azure Portal, go to App Registrations > New Registration"
   - "Set the redirect URI to `https://{AUTH0_DOMAIN}/login/callback` (Web platform)"
   - "Under API Permissions, add `GroupMember.Read.All` (Microsoft Graph) and grant admin consent"
   - "Under Certificates & Secrets, create a new Client Secret and copy the value"
   - "Copy your Application (client) ID and your primary domain (e.g. contoso.com)"

2. **Credentials step** — Three form fields:
   - Azure AD Domain: text input, placeholder `contoso.com`, helper text "Your primary Azure AD domain"
   - Client ID: text input (UUID format), placeholder `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`
   - Client Secret: password input, helper text "This value is sent to Auth0 once and never stored by mingai"

3. **Test step** — "Test Connection" button calls `useTestEntraConnection()` and opens `test_url` in new tab. Status indicator shows whether test was initiated.

4. **Confirm step** — "Enable SSO" button calls `useConfigureEntra()`. On success, shows `connection_id` (DM Mono font) and a confirmation that the connection is active.

**Re-configure flow** (when existing Entra config is detected on mount):

- Skip to a condensed "Update Credentials" view
- Domain field pre-filled from existing config (editable)
- Client ID field pre-filled (editable, shown as plain text)
- Client Secret field empty with label "Enter new secret to rotate (leave blank to keep current)"
- Submit calls `useUpdateEntraConfig()` with only changed fields

**Design rules** (Obsidian Intelligence):

- Provider selection card uses `--bg-elevated` background, `--border` border, Microsoft Entra logo/icon from `lucide-react` or inline SVG
- Selected provider card: `border-color: var(--accent-ring)`, `background: var(--accent-dim)`
- Form inputs: `background: var(--bg-elevated)`, `border: 1px solid var(--border)`, `border-radius: var(--r)`, `color: var(--text-primary)`
- Connection ID displayed in `font-family: "DM Mono"` after successful setup
- Error states use `--alert` colour with `--alert-dim` background
- No `shadow-lg`, `rounded-2xl`, `rounded-sm` on badges, Inter font, or purple/blue palette

**Acceptance criteria**:

- [x] "Microsoft Entra ID" option appears in provider selection step alongside existing providers
- [x] All four wizard steps render correctly: Instructions, Credentials, Test, Confirm
- [x] Instructions step displays correct Azure Portal setup steps with `AUTH0_DOMAIN` variable resolved
- [x] Credentials form validates: domain format (client-side regex), Client ID non-empty, Client Secret non-empty on initial configure
- [x] "Test Connection" opens `test_url` in new tab via `window.open(url, '_blank')`
- [x] "Enable SSO" calls `useConfigureEntra()` with `{ client_id, client_secret, domain }`
- [x] On success: `connection_id` shown in DM Mono, success toast rendered
- [x] On API error: error message shown, wizard remains on Confirm step for retry
- [x] Re-configure mode: domain and client_id pre-filled; secret field blank; PATCH called (not POST)
- [x] Client Secret input is `type="password"` and never displayed as plain text
- [x] All Obsidian Intelligence design tokens used — no hardcoded hex colours, no banned font families
- [x] 0 TypeScript errors

---

### ENTRA-009: Frontend hook wiring verification

**Status**: COMPLETE
**Effort**: 1h
**Depends on**: ENTRA-007, ENTRA-008
**Description**: Verify that the three new hooks in `useSSO.ts` are correctly wired to the wizard component. Run TypeScript compilation and confirm no type errors. Verify the hook call signatures match between the wizard component and the hook definitions. If the project has a frontend unit test setup for hooks (e.g. React Testing Library or vitest), add at minimum a smoke test that confirms `useConfigureEntra` calls the correct endpoint path.

**Acceptance criteria**:

- [x] `npx tsc --noEmit` (or equivalent project type-check command) returns 0 errors
- [x] Hook import in wizard component resolves without error
- [x] If frontend test infrastructure exists: at minimum one test that mocks `fetch` and asserts `useConfigureEntra` calls `POST /api/v1/admin/sso/entra/configure`
- [x] No regressions introduced in existing SSO hook tests

---

## Documentation Items

### ENTRA-010: Update API reference documentation

**Status**: COMPLETE
**Effort**: 1h
**Depends on**: ENTRA-001, ENTRA-002, ENTRA-004
**Description**: Update `docs/00-authority/01-api-reference.md` with the three new Entra endpoints. Follow the existing format used for the SAML and OIDC SSO endpoints already documented in that file.

Add under the Tenant Admin / SSO section:

**POST /admin/sso/entra/configure**

- Auth: `require_tenant_admin`
- Request: `{ client_id: string (UUID), client_secret: string, domain: string }`
- Response 200: `{ connection_id: string, test_url: string, domain: string }`
- 400: invalid input format, 409: SSO already configured, 502: Auth0 API error

**PATCH /admin/sso/entra/configure**

- Auth: `require_tenant_admin`
- Request: `{ client_secret?: string, domain?: string }` (at least one required)
- Response 200: updated provider config (no secret field)
- 400: empty body, 404: not configured, 502: Auth0 API error

**POST /admin/sso/entra/test**

- Auth: `require_tenant_admin`
- Request: `{}` (empty body)
- Response 200: `{ test_url: string }`
- 404: not configured or disabled

**Acceptance criteria**:

- [x] All three endpoints documented in `docs/00-authority/01-api-reference.md`
- [x] Request/response schemas match implementation
- [x] Error codes documented for each endpoint
- [x] Note added: "client_secret is transmitted to Auth0 once on configure/re-key and is never stored in mingai's database"
- [x] Existing SAML/OIDC documentation not modified

---

### ENTRA-011: Verify no new environment variables are needed

**Status**: COMPLETE
**Effort**: 0.5h
**Depends on**: ENTRA-001
**Description**: Confirm that the Entra feature requires no new environment variables beyond those already defined in `.env.example` for Auth0 (`AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_AUDIENCE`, `AUTH0_MANAGEMENT_CLIENT_ID`, `AUTH0_MANAGEMENT_CLIENT_SECRET`, `FRONTEND_URL`). The `waad` connection strategy uses the same Management API credentials as SAML/OIDC. Update `.env.example` only if a genuinely new variable is discovered during ENTRA-001 implementation.

**Acceptance criteria**:

- [x] Implementation of ENTRA-001 through ENTRA-004 reviewed — no new `AUTH0_*` or `AZURE_*` env vars required
- [x] If any new var IS discovered: added to `.env.example` with description and example value (no real credentials)
- [x] `src/backend/.env.example` diff reviewed — only additive changes allowed (no existing var removal)

---

## Dependencies Map

```
P3AUTH-001 (Auth0 tenant setup)
  └── P3AUTH-021 (Management API Client Credentials)
        └── P3AUTH-003 (SSO config API — _get_any_sso_config_db, _upsert_sso_provider_config_db)
              ├── ENTRA-001 (POST configure) ─────────────────────────────────┐
              │     └── ENTRA-002 (PATCH configure)                           │
              │     └── ENTRA-003 (enable/disable lifecycle in workspace.py)  │
              │     └── ENTRA-004 (POST test)                                 │
              │           └── ENTRA-005 (router registration)                 │
              │                 └── ENTRA-006 (unit tests)                    │
              │                                                                │
              └── P3AUTH-014 (SSO frontend wiring already complete)           │
                    └── ENTRA-007 (new hooks in useSSO.ts) ──────────────────►│
                          └── ENTRA-008 (wizard UI — Entra tab)               │
                                └── ENTRA-009 (TS verification)               │
                                                                               │
ENTRA-010 (API reference docs) ◄──────────────────────────────────────────────┘
ENTRA-011 (env var audit) — can run in parallel with ENTRA-001
```

---

## Risk Assessment

- **HIGH**: Client secret hygiene — must verify at every layer (DB upsert args, response serialization, audit log metadata) that `client_secret` is absent. Add an explicit assertion in ENTRA-006 for this.
- **HIGH**: Auth0 Org ID availability — if a tenant was provisioned before Auth0 Org wiring was in place, `auth0_org_id` may be absent from `tenant_configs`. ENTRA-001 must handle this gracefully (warn + continue) so the connection is still created even if org-enable fails silently.
- **MEDIUM**: Connection name collision — Auth0 connection names must be unique per tenant. The pattern `entra-{tenant_id[:8]}` should be sufficiently unique but a duplicate name will cause a 409 from Auth0. Map this to a meaningful 409 response for the tenant admin.
- **MEDIUM**: `waad` strategy requires Azure AD admin consent for `GroupMember.Read.All` — the Instructions step in the wizard must clearly describe this step; without it, group sync will silently return no groups.
- **LOW**: PATCH /admin/sso/config toggle for Entra interacts with new lifecycle code in ENTRA-003 — ensure the existing SAML/OIDC/Google/Okta toggle paths are covered by regression tests in ENTRA-006.

---

## Testing Requirements

- **Tier 1 (unit)**: ENTRA-006 — 22 tests, all HTTP and DB calls mocked. File: `tests/unit/test_entra_wizard.py`.
- **Tier 2 (integration)**: If AUTH0 Management API credentials are available in the integration test environment, add `tests/integration/test_entra_wizard.py` with real Management API calls. Gate tests with `pytest.mark.skipif(not os.getenv("AUTH0_MANAGEMENT_CLIENT_ID"), reason="Auth0 creds not available")`. Minimum scenarios: configure creates real `waad` connection, PATCH updates it, DELETE from org on disable, re-add on enable, cleanup in teardown via `management_api_request("DELETE", f"connections/{connection_id}")`.
- **Tier 3 (E2E)**: Not required for this feature in the current sprint. The existing SSO E2E in `tests/integration/test_sso_wizards.py` (DEF-014) covers the Management API mock pattern — Entra can be added in a future E2E pass.

---

## Definition of Done

- [x] ENTRA-001 through ENTRA-011 all accepted
- [x] `pytest tests/unit/test_entra_wizard.py` passes with 22 tests
- [x] `npx tsc --noEmit` returns 0 errors in `src/web/`
- [x] A tenant admin can configure Azure AD SSO end-to-end via the UI wizard with no manual Auth0 intervention
- [x] `client_secret` is confirmed absent from `tenant_configs` rows and API responses (verified by ENTRA-006 mock assertions)
- [x] Existing SAML, OIDC, Google, and Okta SSO flows pass their existing unit tests unchanged
- [x] All three new endpoints appear in the OpenAPI schema at `/docs`
- [x] `docs/00-authority/01-api-reference.md` updated with the three new endpoints
- [x] Code review completed (intermediate-reviewer)
- [x] Security review completed (security-reviewer) — particular focus on secret handling and Auth0 API error propagation

---

## Summary Table

| Item      | Description                                    | Status   | Effort  | Depends On                         |
| --------- | ---------------------------------------------- | -------- | ------- | ---------------------------------- |
| ENTRA-001 | POST /admin/sso/entra/configure                | COMPLETE | 6h      | P3AUTH-001, P3AUTH-003, P3AUTH-021 |
| ENTRA-002 | PATCH /admin/sso/entra/configure               | COMPLETE | 3h      | ENTRA-001                          |
| ENTRA-003 | Enable/disable lifecycle in workspace.py       | COMPLETE | 4h      | ENTRA-001, P3AUTH-003              |
| ENTRA-004 | POST /admin/sso/entra/test                     | COMPLETE | 1h      | ENTRA-001                          |
| ENTRA-005 | Register sso_entra router                      | COMPLETE | 0.5h    | ENTRA-001, ENTRA-002, ENTRA-004    |
| ENTRA-006 | Unit tests (22 cases, test_entra_wizard.py)    | COMPLETE | 5h      | ENTRA-001–004                      |
| ENTRA-007 | useConfigureEntra / useUpdateEntraConfig hooks | COMPLETE | 2h      | ENTRA-001, ENTRA-002, ENTRA-004    |
| ENTRA-008 | Entra ID tab in SSO Setup Wizard UI            | COMPLETE | 6h      | ENTRA-007, P3AUTH-014              |
| ENTRA-009 | Frontend hook wiring verification              | COMPLETE | 1h      | ENTRA-007, ENTRA-008               |
| ENTRA-010 | Update API reference docs                      | COMPLETE | 1h      | ENTRA-001, ENTRA-002, ENTRA-004    |
| ENTRA-011 | Verify no new env vars needed                  | COMPLETE | 0.5h    | ENTRA-001                          |
| **Total** |                                                |          | **30h** |                                    |
