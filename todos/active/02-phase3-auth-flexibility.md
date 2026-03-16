# 02 — Phase 3: Auth Flexibility (Auth0 + SSO)

**Generated**: 2026-03-15
**Phase**: 3 (Weeks 13-15 of implementation roadmap)
**Numbering**: P3AUTH-001 through P3AUTH-021
**Stack**: FastAPI + Auth0 + SAML 2.0 + OIDC + PostgreSQL + Redis
**Source plans**: `workspaces/mingai/02-plans/01-implementation-roadmap.md` Phase 3 + `workspaces/mingai/01-analysis/01-research/38-auth0-sso-architecture.md`

---

## Overview

Phase 3 introduces Auth0 as the identity broker, allowing tenants to configure SSO via SAML 2.0, OIDC, Google Workspace, or Okta — while preserving local auth as a permanent fallback for dev environments and non-SSO tenants. JIT provisioning and group-to-role sync reduce ongoing tenant admin overhead.

**Prerequisite**: Phase 2 complete (P2LLM-008 tenant config migration must be live before Auth0 config is stored in `tenant_configs`)

**Blocked items from Phase 1** now unblocked: API-064/065/066 (SSO SAML/OIDC configure), API-086 (Auth0 group sync PATCH route), TEST-004 (JWT v1→v2 dual acceptance), TEST-005 (Auth0 JWKS validation)

---

## Backend Items

### P3AUTH-001: Auth0 tenant setup

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: none (external setup task)
**Description**: Configure Auth0 organization. Existing Azure Entra becomes one upstream connection in Auth0 (not replaced — promoted to be one of several connections). Update `.env.example` with new vars: `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_AUDIENCE`, `AUTH0_MANAGEMENT_API_TOKEN`. Create Auth0 application (Regular Web App) + API resource in Auth0 Dashboard. Document connection IDs for downstream tasks.
**Acceptance criteria**:

- [ ] Auth0 org created with Azure Entra as one upstream connection
- [ ] `.env.example` updated with all 5 new AUTH0\_\* vars (no real values, documented descriptions)
- [ ] Auth0 Application (Regular Web App) created with correct callback URLs (localhost:3022 + production domain)
- [ ] Auth0 API resource created with correct identifier (matches AUTH0_AUDIENCE)
- [ ] Connection IDs documented in implementation notes (not in code)
- [ ] Local `.env` updated with real test values (never committed)

---

### P3AUTH-002: Auth0 JWKS validation

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: P3AUTH-001
**Description**: Replace local JWT secret validation (`HS256` with `JWT_SECRET_KEY`) with Auth0 JWKS endpoint validation (`RS256`). File: `app/core/auth/jwt.py`. New function `decode_jwt_token_auth0(token)` fetches JWKS from `https://{AUTH0_DOMAIN}/.well-known/jwks.json` with in-process LRU cache (TTL: 3600s). Maintain local JWT fallback for dev: if `AUTH0_DOMAIN` not set in env, fall back to HS256 validation. Unblocks TEST-005.
**Acceptance criteria**:

- [ ] `decode_jwt_token_auth0()` validates RS256 tokens from Auth0 JWKS endpoint
- [ ] JWKS response cached in-process LRU (not Redis) with 3600s TTL
- [ ] JWKS cache auto-invalidates on key rotation (catches `InvalidSignatureError` → refetch once → retry)
- [ ] `AUTH0_DOMAIN` absent → falls back to `decode_jwt_token_v1_compat()` (existing local JWT)
- [ ] Both validation paths extract same `request.state.user` fields
- [ ] Unit tests: mock JWKS endpoint, test token validation + cache behavior
- [ ] Integration tests (TEST-005): real Auth0 test tenant token validated correctly

---

### P3AUTH-003: Tenant SSO configuration API

**Status**: ⬜ TODO
**Effort**: 5h
**Depends on**: P3AUTH-001, P2LLM-008
**Description**: `PATCH /admin/sso/config` — stores SSO provider type and Auth0 connection_id in `tenant_configs` under `sso_config` key. Request: `{ "provider_type": "entra|google|okta|saml|oidc", "auth0_connection_id": "con_xxx", "enabled": true }`. `GET /admin/sso/config` returns current config (connection_id safe to return). Requires `require_tenant_admin`.
**Acceptance criteria**:

- [ ] GET returns current sso_config from tenant_configs (or null if not configured)
- [ ] PATCH validates `provider_type` against allowed set (entra|google|okta|saml|oidc)
- [ ] PATCH validates `auth0_connection_id` format matches `con_` prefix (basic format check)
- [ ] Config stored in tenant_configs under `sso_config` key via `TenantConfigService`
- [ ] Config change logged to `audit_log` with actor, action, before/after values
- [ ] `require_tenant_admin` enforced

---

### P3AUTH-004: SAML 2.0 SSO wizard API

**Status**: ⬜ TODO
**Effort**: 10h
**Depends on**: P3AUTH-001, P3AUTH-003, P3AUTH-021
**Description**: `POST /admin/sso/saml/configure`. Accepts IdP metadata URL (fetched server-side) or raw XML (uploaded). Parses metadata to extract entityID, SSO URL, X.509 cert. Creates Auth0 SAML connection via Auth0 Management API. Returns SP metadata XML (download endpoint) and connection_id. `POST /admin/sso/saml/test` triggers test authentication flow. Unblocks API-064.
**Acceptance criteria**:

- [ ] Accepts both `{ "metadata_url": "..." }` and `{ "metadata_xml": "..." }` request bodies
- [ ] Server-side metadata URL fetch with 10s timeout and SSL validation
- [ ] Parses SAML metadata: entityID, SingleSignOnService URL, X.509 certificate
- [ ] Creates Auth0 SAML connection via Management API (`POST /api/v2/connections`)
- [ ] Returns `{ "connection_id": "con_xxx", "sp_metadata_url": "/admin/sso/saml/sp-metadata" }`
- [ ] `GET /admin/sso/saml/sp-metadata` returns valid SP metadata XML
- [ ] `POST /admin/sso/saml/test` returns test flow initiation URL (Auth0 authorize URL)
- [ ] Error if tenant already has a SAML connection (must DELETE first)
- [ ] All operations require `require_tenant_admin`
- [ ] Unit tests cover metadata parsing, error cases (P3AUTH-018)

---

### P3AUTH-005: OIDC SSO wizard API

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: P3AUTH-001, P3AUTH-003, P3AUTH-021
**Description**: `POST /admin/sso/oidc/configure`. Auto-discovery via `{issuer}/.well-known/openid-configuration`. Request: `{ "issuer": "https://...", "client_id": "...", "client_secret": "..." }`. Creates Auth0 OIDC connection. `POST /admin/sso/oidc/test` triggers test flow. Unblocks API-065.
**Acceptance criteria**:

- [ ] Server-side OIDC discovery with 10s timeout
- [ ] Discovery validates: `authorization_endpoint`, `token_endpoint`, `jwks_uri` present
- [ ] Client secret encrypted before storage (vault ref pattern — same as BYOLLM/SharePoint)
- [ ] Creates Auth0 OIDC connection via Management API
- [ ] Returns `{ "connection_id": "con_xxx", "issuer_validated": true }`
- [ ] `POST /admin/sso/oidc/test` returns Auth0 authorize URL for test flow
- [ ] Unit tests cover discovery, error cases (P3AUTH-019)

---

### P3AUTH-006: Google Workspace SSO

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P3AUTH-001, P3AUTH-003, P3AUTH-021
**Description**: Configure Auth0 Google social connection per tenant. `POST /admin/sso/google/configure`. Tenant provides: Google OAuth client_id + client_secret (from their Google Cloud Console). Creates or updates Auth0 Google connection scoped to tenant's Auth0 org. Returns `connection_id`.
**Acceptance criteria**:

- [ ] Accepts `{ "client_id": "...", "client_secret": "..." }` (Google OAuth credentials)
- [ ] Client secret encrypted via vault ref pattern before storage
- [ ] Auth0 Google connection created/updated via Management API
- [ ] Connection scoped to this tenant's Auth0 organization
- [ ] Returns connection_id and Google auth URL for verification
- [ ] `require_tenant_admin` enforced

---

### P3AUTH-007: Okta SSO

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P3AUTH-001, P3AUTH-003, P3AUTH-021
**Description**: Auth0 OIDC connection for Okta. `POST /admin/sso/okta/configure`. Tenant provides: Okta domain + client_id + client_secret. OIDC discovery URL constructed as `https://{okta_domain}/.well-known/openid-configuration`. Delegates to the same Auth0 OIDC connection creation logic as P3AUTH-005.
**Acceptance criteria**:

- [ ] Accepts `{ "okta_domain": "mycompany.okta.com", "client_id": "...", "client_secret": "..." }`
- [ ] Constructs and validates OIDC discovery URL from okta_domain
- [ ] Reuses P3AUTH-005 OIDC connection creation logic (no duplication)
- [ ] Client secret encrypted
- [ ] `require_tenant_admin` enforced

---

### P3AUTH-008: JIT provisioning on first SSO login

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: P3AUTH-001, P3AUTH-002
**Description**: Auth0 post-login Action (JavaScript, deployed to Auth0 Actions pipeline). On first login: checks if `user_id` exists in PostgreSQL `users` table. If not: creates user record with `auth0_user_id`, `email`, `tenant_id` (from org_id claim), `role="viewer"` (default). Emits `user.created` audit event. On subsequent logins: updates `last_login_at`. Connection from Auth0 Action to PostgreSQL via HTTPS to internal API endpoint `POST /internal/users/jit-provision` (internal-only, not in public API).
**Acceptance criteria**:

- [ ] Auth0 Action JavaScript deployed to Auth0 dashboard
- [ ] `POST /internal/users/jit-provision` endpoint created (internal network only — not in public router)
- [ ] First login creates user row with correct tenant_id extracted from Auth0 org claim
- [ ] Default role `viewer` assigned unless group sync overrides (P3AUTH-009)
- [ ] `user.created` event written to `audit_log`
- [ ] Subsequent login updates `last_login_at` — no duplicate user creation
- [ ] Internal endpoint validates a shared secret header (not JWT — JIT call comes from Auth0 before JWT is issued)
- [ ] Unit tests cover first login, repeat login, missing org claim (P3AUTH-020)

---

### P3AUTH-009: Group-to-role sync

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: P3AUTH-008, P3AUTH-010
**Description**: Auth0 post-login Action reads IdP group claims from token (`groups` or `roles` claim depending on IdP). Maps group names to mingai roles via `tenant_configs.sso_group_role_mapping`. Calls internal API `POST /internal/users/sync-roles` with `{ "auth0_user_id", "groups", "tenant_id" }`. Backend: updates `user_roles` table based on group mapping. If no mapping matches, role unchanged from JIT provisioning default.
**Acceptance criteria**:

- [ ] Auth0 Action reads groups from both `groups` and `roles` JWT claims (whichever present)
- [ ] `POST /internal/users/sync-roles` endpoint created (internal-only)
- [ ] Group-role mapping read from `tenant_configs.sso_group_role_mapping` (set by P3AUTH-010)
- [ ] Role updated in `user_roles` table on each login (idempotent upsert)
- [ ] Audit log entry on role change (not on no-change)
- [ ] If `sso_group_role_mapping` not configured, sync is a no-op (no error)
- [ ] Unit tests: mapping hit, mapping miss, multiple groups, role downgrade (P3AUTH-020)

---

### P3AUTH-010: Auth0 group sync allowlist PATCH route

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P2LLM-008
**Description**: Wire existing `app/modules/auth/group_sync.py` (which has `sync_auth0_groups()` + `build_group_sync_config()` functions but no HTTP route) to a new endpoint. `PATCH /admin/sso/group-sync/config`. Request: `{ "allowed_groups": ["HR-Staff", "Finance-Team"], "group_role_mapping": { "HR-Staff": "viewer", "HR-Admins": "editor" } }`. `GET /admin/sso/group-sync/config` returns current mapping. Unblocks API-086 and DEF-012.
**Acceptance criteria**:

- [ ] `GET /admin/sso/group-sync/config` returns current allowlist + mapping from tenant_configs
- [ ] `PATCH /admin/sso/group-sync/config` validates role values against allowed set (viewer|editor|admin)
- [ ] Config stored in `tenant_configs` under `sso_group_role_mapping` key
- [ ] Calls `build_group_sync_config()` from existing `group_sync.py` to structure data
- [ ] `require_tenant_admin` on both routes
- [ ] Unit tests: valid mapping, invalid role value, empty mapping

---

### P3AUTH-011: Session management

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: P3AUTH-002
**Description**: Auth0 token refresh integration. `POST /auth/token/refresh` updated to use Auth0 refresh token exchange (`/oauth/token` with `grant_type=refresh_token`). Concurrent session limits enforced via Redis: track active sessions per user, limit by plan (Starter: 3, Professional: 10, Enterprise: unlimited). Force logout: `POST /admin/users/{id}/force-logout` DELetes all Redis session keys for user.
**Acceptance criteria**:

- [ ] Auth0 refresh token exchange works end-to-end
- [ ] Redis session tracking: key `mingai:{tenant_id}:sessions:{user_id}` as sorted set (score = expiry timestamp)
- [ ] On new session: prune expired entries, check count vs plan limit, reject if over limit (409)
- [ ] `POST /admin/users/{id}/force-logout` DELetes session sorted set + DELs all associated token keys
- [ ] `require_tenant_admin` on force-logout endpoint
- [ ] Local auth fallback path (P3AUTH-013) also uses Redis session tracking

---

### P3AUTH-012: Migration tooling

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: P3AUTH-001, P3AUTH-002
**Description**: One-time migration script `scripts/migrate_users_to_auth0.py`. Maps existing users (identified by email) to Auth0 user IDs via Auth0 Management API `GET /api/v2/users-by-email`. Updates `users.auth0_user_id` column (add column in migration if not present). Dual-token window: 30 days where both HS256 local tokens and RS256 Auth0 tokens are accepted. Script generates CSV report of migrated/failed/not-found users.
**Acceptance criteria**:

- [ ] Script queries all users from PostgreSQL, looks up Auth0 ID by email
- [ ] Updates `users.auth0_user_id` for matched users
- [ ] CSV report: migrated count, not-found list, error list
- [ ] Dual-token window active after migration: `decode_jwt_token_auth0()` OR `decode_jwt_token_v1_compat()` accepted (unblocks TEST-004)
- [ ] Script idempotent: re-running skips already-migrated users
- [ ] `users.auth0_user_id` column Alembic migration included
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Dry-run mode: `--dry-run` flag shows what would change without writing

---

### P3AUTH-013: Local auth fallback

**Status**: ⬜ TODO
**Effort**: 2h
**Depends on**: P3AUTH-002
**Description**: Ensure local username/password auth (`POST /auth/local/login`) continues working when `AUTH0_DOMAIN` is set (for tenants without SSO, and always for dev). The local login path must not be accidentally broken by Auth0 JWKS validation introduction. Verify: if tenant has `sso_config.enabled=false`, local login is the only auth path. If tenant has `sso_config.enabled=true`, local login still works as emergency fallback.
**Acceptance criteria**:

- [ ] `POST /auth/local/login` returns valid JWT regardless of `AUTH0_DOMAIN` env var presence
- [ ] Local JWT validated by `decode_jwt_token_v1_compat()` path (not JWKS)
- [ ] SSO-enabled tenants can still log in via local auth (emergency fallback — not just dev)
- [ ] No new environment variable needed to toggle local auth; it is always on
- [ ] Integration test: local login works with Auth0 env vars present

---

## Frontend Items

### P3AUTH-014: SSO configuration PATCH route wired

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P3AUTH-004, P3AUTH-005
**Description**: Connect existing `SSOSetupWizard.tsx` (already built in FE-039 area) to new API endpoints P3AUTH-004 (SAML) and P3AUTH-005 (OIDC). Currently the wizard has no HTTP calls wired. Add: `POST /admin/sso/saml/configure` call on SAML wizard submit, `POST /admin/sso/oidc/configure` call on OIDC wizard submit. Show SP metadata download button after SAML configuration succeeds.
**Acceptance criteria**:

- [ ] SAML wizard submits to `POST /admin/sso/saml/configure` with metadata URL or XML
- [ ] OIDC wizard submits to `POST /admin/sso/oidc/configure` with issuer + credentials
- [ ] SP metadata download button appears after SAML setup (fetches `GET /admin/sso/saml/sp-metadata`)
- [ ] Error states shown for configuration failures (invalid metadata, Auth0 API error)
- [ ] Success state shows `connection_id` reference (not full credentials)
- [ ] 0 TypeScript errors

---

### P3AUTH-015: Auth0 group sync config UI

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P3AUTH-010
**Description**: Wire existing `Auth0SyncSettings.tsx` to `PATCH /admin/sso/group-sync/config`. Currently has no HTTP route (noted as gap INFRA-035). Add: `GET /admin/sso/group-sync/config` on mount to load current mapping, `PATCH` on save. The HTTP wiring (`GET`/`PATCH` calls) is the sole responsibility of this item.
**Note**: The HTTP wiring (`PATCH /admin/sso/group-sync/config`) is owned by this item. The group-to-role mapping table UI in the same settings page is owned by `TA-004`. Both items touch `Auth0SyncSettings.tsx` — implement P3AUTH-015 first (HTTP layer), then TA-004 adds the mapping table to the same page.
**Acceptance criteria**:

- [ ] On mount: loads current mapping via GET and populates table rows
- [ ] Save button fires PATCH with current mapping state
- [ ] Save button disabled when no changes pending
- [ ] Success toast on save; error toast on API failure
- [ ] 0 TypeScript errors

---

## Testing Items

### P3AUTH-016: Auth0 JWKS validation integration tests

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P3AUTH-002
**Description**: Integration tests in `tests/integration/test_auth0_jwks.py` using real Auth0 test tenant. Unblocks TEST-005. Tests: (1) RS256 token from Auth0 test tenant validates correctly, (2) expired token rejected, (3) wrong audience rejected, (4) JWKS cache populated after first validation, (5) JWKS refetch on key rotation (simulate by revoking + reissuing test key).
**Acceptance criteria**:

- [ ] All 5 scenarios with real Auth0 test tenant
- [ ] Tests skipped gracefully if `AUTH0_DOMAIN` not in test env (not failed)
- [ ] All tests pass: `pytest tests/integration/test_auth0_jwks.py -k auth0`

---

### P3AUTH-017: JWT v1-to-v2 dual acceptance integration tests

**Status**: ⬜ TODO
**Effort**: 3h
**Depends on**: P3AUTH-012
**Description**: Integration tests in `tests/integration/test_jwt_dual_acceptance.py`. Unblocks TEST-004. Tests: (1) HS256 v1 token (no tenant_id claim) accepted during dual-accept window with default tenant_id="default", (2) RS256 Auth0 v2 token accepted on same endpoint, (3) v1 token rejected after dual-accept window expires (mock time travel), (4) both token types produce identical `request.state.user` structure.
**Acceptance criteria**:

- [ ] All 4 scenarios covered
- [ ] Window expiry tested via mock datetime (not real wait)
- [ ] Both token types hit same protected endpoint and return 200
- [ ] All tests pass: `pytest tests/integration/test_jwt_dual_acceptance.py`

---

### P3AUTH-018: SAML SSO unit tests

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P3AUTH-004
**Description**: Unit tests in `tests/unit/test_saml_wizard.py`. Tests: SP metadata generation (valid XML with entityID + ACS URL), IdP metadata parsing (extract entityID, SSO URL, cert from fixture XML), attribute mapping roundtrip, invalid metadata XML raises `ValueError`, unreachable metadata URL raises `TimeoutError`.
**Acceptance criteria**:

- [ ] SP metadata is valid XML parseable by `lxml`
- [ ] IdP metadata parsing tested with both URL and raw XML paths
- [ ] All error cases covered
- [ ] No real HTTP calls in unit tests (mock `httpx.AsyncClient`)
- [ ] All tests pass: `pytest tests/unit/test_saml_wizard.py`

---

### P3AUTH-019: OIDC SSO unit tests

**Status**: ⬜ TODO
**Effort**: 3h
**Depends on**: P3AUTH-005
**Description**: Unit tests in `tests/unit/test_oidc_wizard.py`. Tests: auto-discovery extracts correct endpoints from fixture JSON, client credential encryption uses vault ref pattern, invalid issuer (missing required fields) raises `ValueError`, unreachable discovery endpoint raises `TimeoutError`.
**Acceptance criteria**:

- [ ] Discovery parsing tested with fixture `.well-known/openid-configuration` JSON
- [ ] All required fields validated
- [ ] Client secret not present in any returned value after encryption
- [ ] All tests pass: `pytest tests/unit/test_oidc_wizard.py`

---

### P3AUTH-020: JIT provisioning unit tests

**Status**: ⬜ TODO
**Effort**: 3h
**Depends on**: P3AUTH-008, P3AUTH-009
**Description**: Unit tests in `tests/unit/test_jit_provisioning.py`. Tests: (1) first login creates user with role=viewer, (2) second login does NOT create duplicate user, (3) `user.created` audit event emitted only on first login, (4) group-to-role sync overrides default viewer role, (5) missing org claim from Auth0 token raises `ValueError`.
**Acceptance criteria**:

- [ ] All 5 scenarios covered
- [ ] Mock PostgreSQL session used (Tier 1 — no real DB)
- [ ] Audit event emission verified via mock assertion
- [ ] All tests pass: `pytest tests/unit/test_jit_provisioning.py`

---

### P3AUTH-021: Auth0 Management API — Client Credentials flow

**Status**: ⬜ TODO
**Priority**: HIGH — Production blocker for SSO wizard
**Effort**: 4h
**Depends on**: P3AUTH-001 (Auth0 tenant setup)

The SSO wizard uses Auth0 Management API to create SAML/OIDC connections. The static `AUTH0_MANAGEMENT_API_TOKEN` is short-lived (24h) and will silently break in production. Production must use Client Credentials grant to auto-refresh Management API tokens.

**Acceptance criteria**:

- [ ] Remove `AUTH0_MANAGEMENT_API_TOKEN` from `.env.example`
- [ ] Implement `get_management_api_token()` using Client Credentials: POST `https://{AUTH0_DOMAIN}/oauth/token` with `client_credentials` grant and `audience=https://{AUTH0_DOMAIN}/api/v2/`
- [ ] Token cached in Redis with TTL = expires_in − 60 seconds
- [ ] All Management API calls use `get_management_api_token()` instead of static env var
- [ ] Unit test: token refresh on expiry (mock Redis miss + mock token endpoint)
- [ ] Integration test: Management API call succeeds after static token removed from env

**Note**: This must be complete before P3AUTH-004/005/006/007 go to production. Can be implemented in the same sprint as P3AUTH-001.

---

## Dependencies Map

```
P3AUTH-001 (Auth0 tenant setup)
  ├── P3AUTH-002 (JWKS validation) → P3AUTH-016 (integration tests) / P3AUTH-017 (dual JWT)
  ├── P3AUTH-003 (SSO config API)
  │     ├── P3AUTH-004 (SAML wizard) → P3AUTH-014 (frontend) / P3AUTH-018 (unit tests)
  │     ├── P3AUTH-005 (OIDC wizard) → P3AUTH-014 (frontend) / P3AUTH-019 (unit tests)
  │     ├── P3AUTH-006 (Google Workspace)
  │     └── P3AUTH-007 (Okta)
  ├── P3AUTH-008 (JIT provisioning) → P3AUTH-020 (unit tests)
  │     └── P3AUTH-009 (group sync) → needs P3AUTH-010 (PATCH route)
  └── P3AUTH-012 (migration tooling) → P3AUTH-013 (local fallback)

P2LLM-008 (tenant config service) — prerequisite for P3AUTH-003/010/011
```

---

## Notes

- Phase 1 already has `app/modules/auth/group_sync.py` with logic built but unrouted — P3AUTH-010 wires it
- Local auth (`POST /auth/local/login`) must remain functional after Auth0 changes — P3AUTH-013 is a verification item, not new code
- Auth0 Management API token (`AUTH0_MANAGEMENT_API_TOKEN`) is short-lived (24h) — production should use Client Credentials flow for Management API, not a static token
- TEST-004 (JWT dual acceptance) and TEST-005 (JWKS validation) have been DEFERRED since Session 5; they unblock in this phase
- SAML attribute mapping: default attribute names `email` → `email`, `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name` → `name` — document in code, not hardcoded
