# 07 — Deferred Phase 1 Items (Now Actionable)

**Generated**: 2026-03-15
**Phase**: Deferred from Phase 1 — now unblocked by Phase 2 prerequisites
**Numbering**: DEF-001 through DEF-020
**Stack**: PostgreSQL + pgvector + FastAPI + Auth0 + Redis
**Source**: Phase 1 audit sessions (15-19) — items confirmed NOT implemented with investigation notes

---

## Overview

These items were deferred from Phase 1 due to external dependencies (Phase 2 tables, Auth0, pgvector). They are now actionable as Phase 2 and Phase 3 work proceeds. They are organized by unblocking dependency so they can be picked up alongside the relevant parent work.

**Recommended pickup order**:

1. DEF-001–006 (DB tables): pick up alongside relevant Phase 2 table migrations
2. DEF-007 (secrets manager): required before HAR Phase 1 goes to production
3. DEF-008/009/010 (infrastructure gaps): pick up in Phase 2 sprint planning
4. DEF-011/012 (API gaps): unblocked by TA-006 and P3AUTH-010
5. DEF-013–020 (testing gaps): unblocked by respective feature completions

---

## Database Deferred Items

### DEF-001: `issue_embeddings` table

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: Alembic migration `v032_issue_embeddings.py` with pgvector HNSW index on issue_embeddings, RLS enabled.
**Effort**: 3h
**Depends on**: CACHE-007 (pgvector migration — must be applied first)
**Description**: pgvector HNSW index for duplicate issue detection. When new issues are reported, embed them and find near-duplicate existing issues. Alembic migration for `issue_embeddings` table. Columns: `id` UUID PK, `issue_id` UUID FK (issue_reports.id), `tenant_id` UUID FK, `embedding` VECTOR(1536), `created_at` TIMESTAMPTZ. HNSW index: `CREATE INDEX ON issue_embeddings USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`. RLS: tenant sees own rows.
**Acceptance criteria**:

- [ ] Migration applies after CACHE-007 (pgvector extension already enabled)
- [ ] HNSW index created on `embedding` column
- [ ] FK to `issue_reports.id` with CASCADE DELETE
- [ ] RLS tenant isolation
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Migration is reversible
- [ ] `alembic upgrade head` clean

---

### DEF-002: `consent_events` table

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: Alembic migration `v033_consent_events.py` with split RLS policies (SELECT vs INSERT).
**Effort**: 3h
**Depends on**: none (independent migration)
**Description**: GDPR consent audit trail. Immutable: no UPDATE or DELETE allowed (audit log pattern). Columns: `id` UUID PK, `tenant_id` UUID FK, `user_id` UUID FK, `consent_type` VARCHAR (data_processing|memory_learning|org_context|profile_sharing), `action` VARCHAR CHECK(granted|revoked), `ip_address` INET, `user_agent` TEXT, `created_at` TIMESTAMPTZ. Index on `(tenant_id, user_id, created_at DESC)`. RLS: user sees own rows; tenant_admin sees tenant rows; platform_admin sees all.
**Acceptance criteria**:

- [ ] Alembic migration with all columns
- [ ] `action` CHECK constraint enforces granted|revoked
- [ ] `consent_type` CHECK constraint enforces 4 allowed values
- [ ] RLS: 3-tier visibility (user, tenant_admin, platform_admin)
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Application-layer INSERT-only enforcement: DELETE endpoint does not exist; route returns 405
- [ ] Index on `(tenant_id, user_id, created_at DESC)` for audit queries
- [ ] Migration is reversible

---

### DEF-003: `notification_preferences` table

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: Alembic migration `v034_notification_preferences.py`.
**Effort**: 3h
**Depends on**: none
**Description**: User notification preferences. Columns: `id` UUID PK, `tenant_id` UUID FK, `user_id` UUID FK (users.id), `notification_type` VARCHAR (issue_update|sync_failure|access_request|platform_message|digest), `channel` VARCHAR CHECK(in_app|email|both), `enabled` BOOLEAN DEFAULT true, `created_at` TIMESTAMPTZ, `updated_at` TIMESTAMPTZ. UNIQUE(tenant_id, user_id, notification_type). API: `GET /me/notification-preferences` and `PATCH /me/notification-preferences`. Default: in_app enabled for all types.
**Acceptance criteria**:

- [ ] UNIQUE constraint on `(tenant_id, user_id, notification_type)`
- [ ] `channel` CHECK constraint enforces in_app|email|both
- [ ] Default: if no row, treat as `channel=in_app, enabled=true`
- [ ] `GET /me/notification-preferences` returns all 5 types with current settings (or defaults)
- [ ] `PATCH /me/notification-preferences` upserts preference for specified type(s)
- [ ] `require_authenticated_user` (any role) on both routes
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Migration is reversible

---

### DEF-004: `user_privacy_settings` table

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: Alembic migration `v035_user_privacy_settings.py`.
**Effort**: 3h
**Depends on**: none
**Description**: Per-user privacy settings controlling personalization features. Columns: `id` UUID PK, `tenant_id` UUID FK, `user_id` UUID FK, `profile_learning_enabled` BOOLEAN DEFAULT true, `working_memory_enabled` BOOLEAN DEFAULT true, `org_context_enabled` BOOLEAN DEFAULT true, `updated_at` TIMESTAMPTZ. UNIQUE(tenant_id, user_id). API: `GET /me/privacy-settings` and `PATCH /me/privacy-settings`. Profile learning and working memory services check this table before collecting data.
**Acceptance criteria**:

- [ ] UNIQUE(tenant_id, user_id)
- [ ] Default: if no row, all 3 features enabled (true)
- [ ] `GET /me/privacy-settings` returns current settings or defaults
- [ ] `PATCH /me/privacy-settings` accepts any subset of the 3 boolean fields
- [ ] `ProfileLearningService.on_query_completed()` checks `profile_learning_enabled` before collecting
- [ ] `WorkingMemoryService` checks `working_memory_enabled` before storing snapshots
- [ ] `OrgContextService` checks `org_context_enabled` before reading org context
- [ ] `require_authenticated_user` on both routes
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Migration is reversible

---

### DEF-005: `mcp_servers` table

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: Alembic migration `v036_mcp_servers.py`, `app/modules/admin/mcp_servers.py` with CREATE/LIST/DELETE endpoints.
**Effort**: 3h
**Depends on**: none
**Description**: MCP server configuration per tenant (from original Phase 1 plan — deferred due to Phase 1 scope). Columns: `id` UUID PK, `tenant_id` UUID FK, `name` VARCHAR, `endpoint` VARCHAR, `auth_type` VARCHAR CHECK(none|api_key|oauth2), `auth_config` JSONB (encrypted API key ref), `status` VARCHAR CHECK(active|inactive), `last_verified_at` TIMESTAMPTZ, `created_at` TIMESTAMPTZ. UNIQUE(tenant_id, name). RLS: tenant sees own rows.
**Acceptance criteria**:

- [ ] UNIQUE(tenant_id, name)
- [ ] `auth_config` stores vault ref (not plaintext credentials)
- [ ] `status` CHECK constraint
- [ ] RLS: tenant isolation
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] CRUD API: `POST /admin/mcp-servers`, `GET /admin/mcp-servers`, `DELETE /admin/mcp-servers/{id}`
- [ ] `require_tenant_admin` on all routes
- [ ] Migration is reversible

---

### DEF-006: `dag_runs`, `dag_nodes`, `dag_synthesis` tables

**Status**: ⛔ GATED — Phase 5 scope only
**Depends on**: Phase 5 DAG replay implementation
**Description**: DAG replay tables for conversation graph visualization. Retention policy: 7 days (Starter), 30 days (Professional), 90 days (Enterprise). NOT in scope until Phase 5. Do NOT implement.
**Notes**: Included here as explicit "do not prematurely implement" marker.

---

## Infrastructure Deferred Items

### DEF-007: Secrets manager for private keys

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: none (but MUST complete before HAR Phase 1 production deployment)
**Description**: INFRA-027 gap. Ed25519 keypairs for HAR agents currently stored in PostgreSQL (plaintext private key in `agent_cards` or related table). Must move to actual secrets manager before production. Target: Azure Key Vault (consistent with Azure infrastructure) or AWS Secrets Manager. Pattern: store key reference (vault URI) in PostgreSQL; retrieve plaintext key from vault only at signing time. Never log or return private key.
**Acceptance criteria**:

- [ ] Azure Key Vault or AWS Secrets Manager integration in `app/core/secrets/vault_client.py`
- [ ] `vault_client.store_secret(key_id, plaintext)` → returns vault_ref URI
- [ ] `vault_client.get_secret(vault_ref)` → returns plaintext (in-memory only)
- [ ] Ed25519 private keys migrated: existing DB rows updated with vault_ref; plaintext column dropped via migration
- [ ] Vault credentials from env: `AZURE_KEY_VAULT_URL` or `AWS_SECRETS_ARN_PREFIX`
- [ ] Unit test: store + retrieve roundtrip via mock vault client
- [ ] Security test: plaintext key not present in any DB column after migration

---

### DEF-008: Auth0 group sync DB writes + login hook

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P3AUTH-008, P3AUTH-009
**Description**: INFRA-035 gap. `group_sync.py` has `sync_auth0_groups()` + `build_group_sync_config()` functions but these are NOT called on login. No DB writes to `team_memberships` occur on SSO login. Wire: on-login hook must call `sync_auth0_groups()` after JIT provisioning (P3AUTH-008). `sync_auth0_groups()` should update `team_memberships` table based on Auth0 group claims. This is the DB write side of P3AUTH-009.
**Acceptance criteria**:

- [ ] `sync_auth0_groups()` called from `POST /internal/users/sync-roles` endpoint (P3AUTH-009)
- [ ] `sync_auth0_groups()` writes to `team_memberships` table (add/remove memberships based on IdP groups)
- [ ] Team membership writes are idempotent (upsert pattern)
- [ ] `team_membership_audit` table entry written on each membership change
- [ ] Unit test: group sync adds correct team_memberships for known group → team mapping

---

### DEF-009: MULTI_TENANT_ENABLED flag consumption

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `app/core/tenant_middleware.py` — `_is_multi_tenant_enabled()` reads from `os.environ` (not `@lru_cache`); `TenantContextMiddleware.dispatch()` sets `request.state.tenant_id = "default"` when flag is false. `.env.example` documents `MULTI_TENANT_ENABLED=true`. `tests/unit/test_multi_tenant_flag.py` — 10 tests passing.
**Effort**: 3h
**Depends on**: none
**Description**: INFRA-050 gap. `MULTI_TENANT_ENABLED` flag defined in `app/core/config.py` but no component reads it. Intended use: strangler fig middleware to check this flag; when `false`, all requests treated as single-tenant (tenant_id="default"). Implementation: middleware reads `MULTI_TENANT_ENABLED` from env; if false, overwrites `request.state.user.tenant_id` to "default" regardless of JWT claims.
**Acceptance criteria**:

- [ ] `MULTI_TENANT_ENABLED` read from env in middleware (not from `@lru_cache` Settings after P2LLM-008)
- [ ] When `false`: `request.state.user.tenant_id` set to "default" after JWT validation
- [ ] When `true` (default): no change to behavior
- [ ] `.env.example` documents `MULTI_TENANT_ENABLED=true` with comment
- [ ] Unit test: middleware with `MULTI_TENANT_ENABLED=false` forces tenant_id="default"

---

### DEF-010: Google Drive sync worker

**Status**: ⬜ TODO
**Effort**: 10h
**Depends on**: TA-019 (Google Drive connect API — must be complete first)
**Description**: Full Google Drive sync worker. Per Plan 04 Phase 4 deferred item. New file: `app/modules/documents/google_drive/sync_worker.py`. Features: folder browser (API: `GET /documents/google-drive/{id}/folders` — implemented in TA-019), incremental sync via `drive.changes.list()` (only sync files changed since `last_sync_at`), push notification channels (Google Drive webhook for real-time change notifications). Worker mirrors SharePoint sync worker pattern.
**Acceptance criteria**:

- [ ] `sync_worker.py` in `app/modules/documents/google_drive/`
- [ ] Incremental sync: uses `pageToken` from Google Drive `changes.list` (not full re-scan)
- [ ] Push notifications: `POST /documents/google-drive/{id}/watch` creates Drive notification channel; webhook receives change events at `POST /webhooks/google-drive/changes`
- [ ] On file change: re-embed document and update vector store
- [ ] Sync state stored in `sync_jobs` table (same pattern as SharePoint)
- [ ] Error handling: inaccessible files logged + skipped (not crash)
- [ ] Integration test: real Google Drive API with test service account (or mock drive API)

---

## API Deferred Items

### DEF-011: KB access control routes

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: Routes registered in `router.py` at `/admin/knowledge-base/{id}/access-control` (canonical) with `/access` alias. `require_tenant_admin` enforced. Gap fixed: `verify_kb_belongs_to_tenant()` added to `kb_access_control.py` — GET and PATCH return 404 for foreign tenant KBs. Tests in `tests/unit/test_kb_access_api.py` and `tests/unit/test_kb_access_control_paths.py`.
**Effort**: 2h
**Depends on**: TA-006 (kb_access_control table), TA-007 (KB access control API)
**Description**: API-067/068 deferred items. `GET /admin/knowledge-base/{id}/access-control` and `PATCH /admin/knowledge-base/{id}/access-control`. These are the same as TA-007 (`GET/PATCH /admin/knowledge-base/{id}/access`) — just verify the routes are registered in `main.py` under the correct path. The `/access-control` suffix vs `/access` discrepancy must be resolved.
**Acceptance criteria**:

- [ ] Determine canonical path: `/access` or `/access-control` (pick one, document in route comment)
- [ ] Route registered in main.py under correct prefix
- [ ] Route returns 404 for KBs belonging to different tenant (not 403 — don't reveal existence)
- [ ] `require_tenant_admin` enforced
- [ ] Integration test: verify route accessible and returns correct response shape

---

### DEF-012: Auth0 group sync PATCH route

**Status**: ✅ RESOLVED
**Resolved by**: P3AUTH-010 which fully implements `PATCH /admin/sso/group-sync/config` and `GET /admin/sso/group-sync/config`. When P3AUTH-010 is complete, API-086 is addressed. No separate implementation needed.
**Depends on**: P3AUTH-010 (PATCH /admin/sso/group-sync/config)
**Description**: API-086 deferred item. Wire `app/modules/auth/group_sync.py` to HTTP endpoint. Fully covered by P3AUTH-010.
**Acceptance criteria**:

- [ ] `PATCH /admin/sso/group-sync/config` exists and is accessible
- [ ] `GET /admin/sso/group-sync/config` exists
- [ ] Both routes call `build_group_sync_config()` from `group_sync.py`
- [ ] DB writes to `team_memberships` occur on config save (via DEF-008 hook)
- [ ] `require_tenant_admin` enforced

---

## Testing Deferred Items

### DEF-013: pgvector semantic cache integration tests

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `tests/integration/test_pgvector_cache.py` — 9 tests: exact match retrieval, expiry, version mismatch, cross-tenant isolation (3 tests), similarity threshold boundary (exact/near/distant). All 9 passing against real PostgreSQL+pgvector.
**Effort**: 4h
**Depends on**: CACHE-007 (pgvector migration), CACHE-008 (SemanticCacheService)
**Description**: TEST-011/012/013 from Phase 1 testing file. Integration tests requiring pgvector. Now unblocked by CACHE-007. Tests: embedding cache hit/miss with real pgvector, cross-tenant cache isolation, similarity threshold boundary tests. File: `tests/integration/test_pgvector_cache.py`. Tier 2 — real PostgreSQL + pgvector.
**Acceptance criteria**:

- [ ] TEST-011: embedding stored and retrieved correctly via pgvector
- [ ] TEST-012: cross-tenant isolation — tenant A embedding not returned for tenant B query
- [ ] TEST-013: similarity threshold boundary — exact match at 1.0, near-match at 0.92 threshold, miss at 0.85
- [ ] Real PostgreSQL with pgvector extension (not mock)
- [ ] All tests pass: `pytest tests/integration/test_pgvector_cache.py`

---

### DEF-014: SAML/OIDC SSO integration tests

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P3AUTH-004 (SAML wizard), P3AUTH-005 (OIDC wizard)
**Description**: TEST-026/027 from Phase 1 testing file. Integration tests for SSO wizards. Now unblocked by P3AUTH-004/005 implementation. File: `tests/integration/test_sso_wizards.py`. Tests: SAML metadata parsing end-to-end, OIDC discovery end-to-end, Auth0 connection creation (mocked Auth0 Management API — not real Auth0 call in CI).
**Acceptance criteria**:

- [ ] TEST-026: SAML wizard creates connection with mocked Auth0 Management API
- [ ] TEST-027: OIDC wizard creates connection with mocked Auth0 Management API
- [ ] Metadata parsing with real SAML/OIDC fixture files
- [ ] Auth0 Management API calls mocked in test (not real — avoid external dependency in CI)
- [ ] All tests pass: `pytest tests/integration/test_sso_wizards.py`

---

### DEF-015: SSO E2E tests

**Status**: ⬜ TODO
**Effort**: 5h
**Depends on**: P3AUTH (Phase 3 complete)
**Description**: TEST-038/039 from Phase 1 testing file. Playwright E2E tests for full SSO login flow. TEST-038: SAML SSO login → dashboard. TEST-039: OIDC SSO login → dashboard. Requires real Auth0 test tenant (unblocked by P3AUTH-001). File: `tests/e2e/test_sso_flows.spec.ts`. Use Auth0 test tenant credentials from CI secrets.
**Acceptance criteria**:

- [ ] TEST-038: Playwright navigates to login → selects SAML SSO → Auth0 redirect → SAML IdP mock → callback → dashboard
- [ ] TEST-039: OIDC flow same pattern with OIDC IdP mock
- [ ] Tests run in CI with Auth0 test tenant credentials in secrets
- [ ] Tests skipped gracefully if `AUTH0_TEST_*` env vars not present
- [ ] All tests pass in CI

---

### DEF-016: Glossary pipeline integration tests

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `tests/integration/test_glossary_pipeline.py` — 10 tests covering CRUD, version history, rollback, miss signals, multi-tenant isolation. All passing.
**Effort**: 4h
**Depends on**: TA-013 (glossary miss signals API)
**Description**: TEST-033/034/035 from Phase 1 testing file. Integration tests for glossary pipeline. TEST-033: glossary terms returned in query results. TEST-034: miss signals populated for unmatched terms. TEST-035: glossary cache invalidation on term update. File: `tests/integration/test_glossary_pipeline.py`. Tier 2 — real PostgreSQL + Redis.
**Acceptance criteria**:

- [ ] TEST-033: query containing a known glossary term returns term expansion in response
- [ ] TEST-034: unmatched domain term appears in `glossary_miss_signals` after query
- [ ] TEST-035: glossary Redis cache DELeted on term PATCH; subsequent query re-fetches from DB
- [ ] Real PostgreSQL and Redis (not mocks)
- [ ] All tests pass: `pytest tests/integration/test_glossary_pipeline.py`

---

### DEF-017: Registry E2E tests

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `tests/e2e/test_registry_e2e.py` — 10 tests covering agent registration, search/browse, trust score validation, health status, transaction initiation, multi-tenant isolation. All passing.
**Effort**: 4h
**Depends on**: HAR-002 (CRUD audit), HAR-003 (search filters), HAR-005 (registry UI)
**Description**: TEST-049 from Phase 1 testing file. Playwright E2E test for registry publish and discover flow. File: `tests/e2e/test_registry_flows.spec.ts`. Scenarios: (1) workspace agent published to registry (form submitted, card appears in search), (2) registry search filters work, (3) [Connect] button initiates A2A transaction flow.
**Acceptance criteria**:

- [ ] Publish flow: fill registration form → submit → agent card appears in registry search results
- [ ] Search: filter by industry → only matching cards shown
- [ ] Connect: click [Connect] → transaction initiation modal appears
- [ ] All tests pass: `playwright test tests/e2e/test_registry_flows.spec.ts`

---

### DEF-018: Profile/memory E2E tests

**Status**: ⬜ TODO
**Effort**: 5h
**Depends on**: DEF-004 (user_privacy_settings table wired to services)
**Description**: TEST-059 from Phase 1 testing file. 10 Playwright tests for critical memory flows. Scenarios: (1) user asks question → profile learning captures topic → next session greeting reflects topic, (2) working memory persists within session, (3) org context available in response, (4) privacy toggle off → no learning, (5) memory note created → visible in ME → affects response. File: `tests/e2e/test_memory_flows.spec.ts`.
**Acceptance criteria**:

- [ ] 10 Playwright test cases covering all 5 memory feature scenarios (2 tests per scenario)
- [ ] Privacy toggle scenario: disable profile_learning → verify topic NOT captured
- [ ] Memory note scenario: create note via UI → verify it influences next chat response
- [ ] All tests pass: `playwright test tests/e2e/test_memory_flows.spec.ts`

---

### DEF-019: Teams E2E tests

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `src/web/tests/e2e/test_teams_flows.spec.ts` — 410-line file with 7+ test scenarios covering team creation, member add, shared working memory, member removal. File exists and is complete.
**Effort**: 4h
**Depends on**: none (teams backend COMPLETE per Phase 1 master index — check why TEST-066 pending)
**Description**: TEST-066 from Phase 1 testing file. 7 Playwright E2E tests for team working memory flows. The team backend is implemented (Teams Phase 1 per master index) but E2E tests were pending. Investigate why: check if `tests/e2e/test_teams_flows.spec.ts` exists. If it does: check why it was marked pending. If it doesn't exist: create it. Scenarios: create team, add member, team working memory shared, remove member loses access.
**Acceptance criteria**:

- [ ] First action: investigate current state of teams E2E tests (file may already exist)
- [ ] If file exists and passing: mark DEF-019 RESOLVED, update master index
- [ ] If file missing: create `tests/e2e/test_teams_flows.spec.ts` with 7 test scenarios
- [ ] Team creation → member add → shared memory verify → member remove → access verify
- [ ] All 7 tests pass: `playwright test tests/e2e/test_teams_flows.spec.ts`

---

### DEF-020: Load tests

**Status**: ⛔ GATED — Phase 6 scope
**Depends on**: TEST-070/071/072/074 from Phase 1 testing file
**Description**: 50 concurrent tenants at realistic workload. Deferred to Phase 6. Gate condition: all Phase 2-5 features complete and stable in production for 30+ days.
**Notes**: TEST-070 (backend load), TEST-071 (database load), TEST-072 (cache load), TEST-074 (E2E load). Do not implement until Phase 6.

---

## Quick Pickup Guide

When implementing a Phase 2+ item, pick up these DEF items at the same time:

| When implementing...              | Also pick up                                    |
| --------------------------------- | ----------------------------------------------- |
| CACHE-007 (pgvector)              | DEF-001, DEF-013                                |
| P3AUTH-004/005 (SSO wizards)      | DEF-014                                         |
| P3AUTH (Phase 3 complete)         | DEF-015                                         |
| TA-006 (kb_access_control)        | DEF-011                                         |
| P3AUTH-010 (group sync route)     | DEF-012                                         |
| TA-013 (miss signals)             | DEF-016                                         |
| HAR-002/003/005 (registry)        | DEF-017                                         |
| DEF-004 (privacy settings)        | DEF-018                                         |
| Any sprint start                  | Check DEF-019 (teams E2E — may already be done) |
| P2LLM-008 (config migration)      | DEF-009 (MULTI_TENANT_ENABLED)                  |
| P3AUTH-008/009 (JIT + group sync) | DEF-008 (team_memberships DB writes)            |
| HAR Phase 1 production deploy     | DEF-007 (secrets manager — REQUIRED)            |
| DEF-003 (notification_prefs)      | Wire to TA-011 access request notifications     |
| DEF-004 (privacy settings)        | Wire to TA-004 (group mapping) context          |

---

## Notes

- DEF-019 (Teams E2E) should be investigated before assuming new work is needed — teams backend is complete and may have passing tests already
- DEF-006 (DAG tables) and DEF-020 (load tests) are explicitly gated — do not start them during Phase 2-4
- DEF-007 (secrets manager) is a security prerequisite for HAR Phase 1 production deployment, not just Phase 2. Do not deploy HAR to production until DEF-007 is complete
- DEF-002 (consent_events) is required before PA-035 (GDPR deletion) goes to production — ensure consent records exist before deletion pipeline runs
- DEF-003/004 (notification_prefs + privacy_settings) are UX quality improvements — they should be paired with the frontend privacy settings screen (not yet specced — add to a future frontend sprint)
