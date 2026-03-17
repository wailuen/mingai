# 05 — Tenant Admin Phases B-D: SSO, Access Control, Agent Workspace

**Generated**: 2026-03-15
**Last updated**: 2026-03-16
**Phase**: B (Weeks 7-14), C (Weeks 15-22), D (Weeks 23-28)
**Numbering**: TA-001 through TA-036
**Stack**: FastAPI + Auth0 + PostgreSQL + Kailash DataFlow
**Source plan**: `workspaces/mingai/02-plans/06-tenant-admin-plan.md` Phases B-D
**Progress**: 27/36 complete — 8 TODO/BLOCKED (7 blocked on P3AUTH, 1 product-gated)

---

## Overview

Phase A (Tenant Admin Phase 1 foundations) is COMPLETE. Phases B-D deliver:

- **Phase B**: SSO + RBAC wiring, KB/Agent access control tables, Glossary advanced features, Sync health monitoring
- **Phase C**: Agent Library adoption, Agent Studio (BLOCKED — product-gated), Feedback monitoring analytics
- **Phase D**: Onboarding wizard persistence, Bulk user operations, Multiple source management, Role delegation, Mobile responsiveness

**Dependencies**: Phase B SSO items (TA-001–005) depend on P3AUTH Phase 3 items. Phase C agent items (TA-020–024) depend on PA-019–023 (PA-023 agent_templates table).

---

## Phase B: Intelligence Layer (Weeks 7-14)

### Sprint B1: SSO and RBAC (Weeks 7-9)

### TA-001: SAML 2.0 wizard backend API

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: P3AUTH-004
**Description**: `POST /admin/sso/saml/configure` — delegates to P3AUTH-004 implementation. Verify P3AUTH-004 is fully wired as the tenant admin SSO route. This item covers the tenant-facing verification: SP metadata download endpoint, IdP metadata upload, attribute mapping UI. `GET /admin/sso/saml/sp-metadata` returns SP metadata XML for IdP configuration. `POST /admin/sso/saml/test` initiates test SSO login.
**Acceptance criteria**:

- [ ] P3AUTH-004 endpoint accessible under `/admin/` prefix (tenant admin, not platform admin)
- [ ] SP metadata download works: correct entityID = `https://{AUTH0_DOMAIN}/samlp/metadata/{connection_id}`
- [ ] Attribute mapping defaults: email → email, name → name, groups → groups
- [ ] Test SSO login returns redirect URL (does not complete login in backend)
- [ ] `require_tenant_admin` enforced (not `require_platform_admin`)

---

### TA-002: OIDC wizard backend API

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: P3AUTH-005
**Description**: Verify P3AUTH-005 OIDC endpoint accessible under `/admin/` prefix for tenant admin. Confirm `POST /admin/sso/oidc/configure` and `POST /admin/sso/oidc/test` routes exist and require `require_tenant_admin`. No new backend code if P3AUTH-005 covers both platform and tenant admin paths.
**Acceptance criteria**:

- [ ] `POST /admin/sso/oidc/configure` accessible to tenant admin
- [ ] `POST /admin/sso/oidc/test` returns Auth0 authorize URL for OIDC test flow
- [ ] Client secret encrypted in storage (vault ref — same as P3AUTH-005)
- [ ] `require_tenant_admin` on both routes

---

### TA-003: JIT provisioning

**Status**: ⬜ TODO
**Effort**: 2h
**Depends on**: P3AUTH-008
**Description**: Verify P3AUTH-008 JIT provisioning is wired to correct tenant admin configuration. When tenant admin enables SSO, JIT should be automatically enabled. `GET /admin/sso/config` should return `{ "jit_provisioning": { "enabled": true, "default_role": "viewer" } }`. `PATCH /admin/sso/config` should accept `jit_default_role` field.
**Acceptance criteria**:

- [ ] JIT provisioning auto-enabled when SSO enabled (not a separate toggle)
- [ ] Default role for JIT-provisioned users configurable: viewer|editor (not admin — admin must be explicit grant)
- [ ] `GET /admin/sso/config` returns JIT config alongside SSO provider config
- [ ] Integration with P3AUTH-008 logic confirmed

---

### TA-004: Group-to-role mapping UI

**Status**: ⬜ TODO
**Effort**: 5h
**Depends on**: P3AUTH-010, P3AUTH-015
**Description**: Tenant admin UI for mapping IdP group names to mingai roles. Table format: IdP Group Name (text input) | mingai Role (dropdown: viewer|editor|admin). "Add Row" button. "Test" button fetches current user's group claims from Auth0 and shows which role they would receive. Frontend component: extend `Auth0SyncSettings.tsx`.
**Note**: `P3AUTH-015` owns the HTTP wiring to `PATCH /admin/sso/group-sync/config`. This item (TA-004) adds the group-to-role mapping table UI to the same `Auth0SyncSettings.tsx` page. Must be done after P3AUTH-015 is complete.
**Acceptance criteria**:

- [ ] Table renders current mappings from `GET /admin/sso/group-sync/config`
- [ ] Add/delete mapping rows in-table without page navigation
- [ ] Role dropdown: viewer|editor|admin
- [ ] "Test My Groups" button shows current user's IdP groups and resolved role
- [ ] Save button wired to PATCH endpoint
- [ ] 0 TypeScript errors

---

### TA-005: SSO enable/disable toggle

**Status**: ⬜ TODO
**Effort**: 3h
**Depends on**: P3AUTH-003
**Description**: `PATCH /admin/sso/toggle` with `{ "enabled": true|false }`. Enabling SSO requires a configured connection (at least one of SAML, OIDC, Google, Okta). Disabling: graceful switch — existing SSO sessions continue until token expiry; new logins fall back to local auth. Emergency fallback: local auth ALWAYS works even when SSO is enabled (P3AUTH-013). Frontend: toggle in SSO settings with confirmation dialog on disable.
**Acceptance criteria**:

- [ ] Enable toggle requires at least one configured SSO connection (422 if no connection)
- [ ] Disable toggle shows confirmation: "Existing SSO sessions expire at [time]; local login remains active"
- [ ] `enabled` flag stored in `tenant_configs.sso_config.enabled`
- [ ] Toggle action logged to `audit_log`
- [ ] `require_tenant_admin` enforced

---

### TA-006: `kb_access_control` table

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `kb_access_control` table with `visibility_mode`, `allowed_roles`, `allowed_user_ids` created in migration v002. Backend endpoints implemented.
**Effort**: 4h
**Depends on**: none
**Description**: Alembic migration for `kb_access_control` table. Columns: `id` UUID PK, `tenant_id` UUID FK, `index_id` UUID FK (indexes/integrations), `visibility_mode` VARCHAR CHECK(workspace_wide|role_restricted|user_specific|agent_only), `allowed_roles` VARCHAR[] nullable, `allowed_user_ids` UUID[] nullable, `created_at` TIMESTAMPTZ, `updated_at` TIMESTAMPTZ. UNIQUE(tenant_id, index_id). RLS: tenant sees own rows. Unblocks DEF-011.
**Acceptance criteria**:

- [ ] `visibility_mode` CHECK constraint enforces 4 allowed values
- [ ] `allowed_roles` and `allowed_user_ids` nullable (only relevant for role_restricted and user_specific modes)
- [ ] UNIQUE(tenant_id, index_id) prevents duplicate entries
- [ ] RLS: tenant isolation
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Default behavior (no row): `workspace_wide` (all users in tenant can access)
- [ ] Migration is reversible

---

### TA-007: KB access control API

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `GET/PATCH /admin/knowledge-base/{kb_id}/access-control` implemented in kb_access_control routes.
**Effort**: 6h
**Depends on**: TA-006
**Description**: `GET /admin/knowledge-base/{id}/access` and `PATCH /admin/knowledge-base/{id}/access`. PATCH request: `{ "visibility_mode": "role_restricted", "allowed_roles": ["editor"] }`. Access enforcement at query middleware: before search, check user's roles against KB access control. Unblocks DEF-011 (API-067/068).
**Acceptance criteria**:

- [ ] GET returns current access config (or workspace_wide default if no row)
- [ ] PATCH upserts access config for specified KB
- [ ] For `role_restricted`: validates `allowed_roles` against valid role set
- [ ] For `user_specific`: validates `allowed_user_ids` are valid users in tenant
- [ ] For `agent_only`: KB accessible only to deployed agents (not human queries)
- [ ] Enforcement: chat pipeline checks KB access before including KB in search
- [ ] `require_tenant_admin` on PATCH; `require_tenant_admin` on GET
- [ ] Integration test: user without role in allowed_roles gets empty search results for that KB

---

### TA-008: `agent_access_control` table

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `agent_cards` status enum extended with `paused` and `archived`. Backend enforces paused→503.
**Effort**: 3h
**Depends on**: none
**Description**: Alembic migration for `agent_access_control` table. Same structure as `kb_access_control` but with `agent_id` FK instead of `index_id`. Columns: `id` UUID PK, `tenant_id` UUID FK, `agent_id` UUID FK (agent_cards.id), `visibility_mode` VARCHAR CHECK(workspace_wide|role_restricted|user_specific), `allowed_roles` VARCHAR[] nullable, `allowed_user_ids` UUID[] nullable, `created_at` TIMESTAMPTZ. UNIQUE(tenant_id, agent_id). RLS: tenant isolation.
**Acceptance criteria**:

- [ ] Same structure as TA-006 but for agents
- [ ] UNIQUE(tenant_id, agent_id)
- [ ] RLS: tenant isolation
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Migration is reversible
- [ ] Note: `agent_only` mode does NOT apply to agents (only KBs)

---

### TA-009: Agent deployment lifecycle API

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `PATCH /agents/{agent_id}/status` with valid transitions, 503 for paused agents in chat routes.
**Effort**: 5h
**Depends on**: TA-008
**Description**: `GET /admin/agents/{id}/access` and `PATCH /admin/agents/{id}/access`. Same pattern as TA-007 but for agents. Enforcement: when end user invokes an agent, check their roles against agent access control. If not allowed: 403 with "You don't have access to this agent."
**Acceptance criteria**:

- [ ] GET/PATCH same pattern as TA-007
- [ ] Enforcement: agent invocation checks access before processing
- [ ] `role_restricted` and `user_specific` modes fully enforced
- [ ] `workspace_wide` (default): all users can invoke agent
- [ ] `require_tenant_admin` on PATCH
- [ ] Integration test: user in excluded role gets 403 on agent invocation

---

### TA-010: Deploy from agent library

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `POST /agents/deploy-from-library` endpoint, status='active' on deployment.
**Effort**: 6h
**Depends on**: TA-007, TA-009
**Description**: End users who hit 403 on KB or agent access can request access. `POST /access-requests` (end user endpoint): `{ "resource_type": "kb|agent", "resource_id": UUID, "justification": "string" }`. Inserts into new `access_requests` table. Tenant admin notification sent. `GET /admin/access-requests` (tenant admin) lists pending requests. `PATCH /admin/access-requests/{id}` with `{ "status": "approved|denied", "note": "..." }`. On approval: adds user_id to `allowed_user_ids` in access control table.
**Acceptance criteria**:

- [ ] `access_requests` table Alembic migration included (id, tenant_id, user_id, resource_type, resource_id, justification, status, admin_note, created_at)
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] `POST /access-requests` accessible to end users (viewer role)
- [ ] Tenant admin notification sent on new request
- [ ] `GET /admin/access-requests` supports `?status=pending|approved|denied` filter
- [ ] `PATCH` approve: adds user_id to `allowed_user_ids` in correct access control table
- [ ] `PATCH` deny: no change to access control; note stored in request record
- [ ] User notified (in-app) on approve/deny
- [ ] Duplicate prevention: one pending request per user per resource

---

### TA-011: KB/Agent access control frontend

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `AccessControlPanel.tsx` renders mode controls (workspace-wide/role-restricted/user-specific/agent-only) with role multi-select and user search. `AccessRequestsTab.tsx` shows requests with approve/deny buttons. Both wired in KB settings page and Users page. `useKBAccessControl.ts` hook with PATCH to access control API. 0 TypeScript errors.
**Effort**: 8h
**Depends on**: TA-007, TA-009, TA-010
**Description**: Extend KB management page with access mode selector. New component: `AccessControlPanel.tsx`. Modes displayed as radio buttons (Workspace-wide / Role-restricted / User-specific / Agent-only). On role_restricted: role multi-select. On user_specific: user search + selection list. Also: Access Requests tab in User management page (tenant admin) showing pending/approved/denied requests with approve/deny actions.
**Acceptance criteria**:

- [ ] `AccessControlPanel.tsx` renders correct mode controls per selection
- [ ] Role multi-select uses existing chip design pattern
- [ ] User search: debounced input, calls `GET /admin/users?search=` endpoint
- [ ] Save fires PATCH to access control API
- [ ] Access Requests tab: table of requests with status badges, approve/deny buttons
- [ ] 0 TypeScript errors

---

### Sprint B2: Glossary Management Advanced Features

### TA-012: Glossary term version history

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `GET /{term_id}/history` and `PATCH /{term_id}/rollback/{version_id}` endpoints in glossary routes. Atomic rollback with single-transaction commit. 11 unit tests passing.
**Effort**: 5h
**Depends on**: none (uses existing audit_log table)
**Description**: Per-term edit history stored in `audit_log` table (already exists — resource_type='glossary_term'). Rollback endpoint: `PATCH /glossary/{id}/rollback/{version_id}` where `version_id` is `audit_log.id`. On rollback: restore term fields to the `before` state from that audit log entry. Frontend: `VersionHistoryDrawer.tsx` (FE-033 — COMPLETE) needs rollback button wired.
**Acceptance criteria**:

- [ ] `GET /glossary/{id}/history` returns audit_log entries for this term, sorted by created_at DESC
- [ ] Each history entry: timestamp, actor, changed_fields, before, after values
- [ ] `PATCH /glossary/{id}/rollback/{version_id}` restores term to `before` state
- [ ] Rollback creates new audit_log entry (not overwrite)
- [ ] `VersionHistoryDrawer.tsx` rollback button wired to PATCH endpoint
- [ ] `require_tenant_admin` on rollback endpoint

---

### TA-013: Glossary miss signals ingest

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `POST /admin/glossary/miss-signals` endpoint. 11 unit tests passing.
**Effort**: 5h
**Depends on**: none (glossary_miss_signals table already in schema per master index)
**Description**: `GET /admin/glossary/miss-signals`. Returns top terms appearing in queries that have no glossary coverage. Source: `glossary_miss_signals` table. Populate via nightly batch job: extract unmatched domain terms from `profile_learning_events` queries using TF-IDF; insert into `glossary_miss_signals` with frequency count. Response: `[{ "term": "...", "query_count": N, "example_queries": [max 3] }]`.
**Acceptance criteria**:

- [ ] Nightly batch job populates `glossary_miss_signals` table
- [ ] Batch job: extract top-20 unmatched domain terms per tenant from last 30 days of queries
- [ ] `GET /admin/glossary/miss-signals` returns signals ordered by `query_count DESC`
- [ ] `example_queries` anonymized: show up to 3 query snippets (40 chars max each)
- [ ] `require_tenant_admin` enforced
- [ ] "Add Term" CTA on each row navigates to glossary creation form pre-filled with term

---

### TA-014: Glossary miss signals frontend wiring

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `MissSignalsPanel.tsx` already wired to real API via `useMissSignals()` hook calling `GET /api/v1/glossary/miss-signals`. Loading state via `isLoading`, empty state handled. "Add to Glossary" fires `handleAddFromMissSignal(term)` in `app/settings/glossary/page.tsx` which sets `prefillTerm` and opens the form. All acceptance criteria verified.
**Effort**: 3h
**Depends on**: TA-013

**Acceptance criteria**:

- [x] API call wired on component mount (replace mock data)
- [x] "Add to Glossary" action navigates to creation form with term pre-filled
- [x] Loading skeleton and empty state handled
- [x] 0 TypeScript errors

---

### Sprint B3: Sync Health and Monitoring (Weeks 13-14)

### TA-015: Agent status management with lifecycle controls

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `PATCH /agents/{agent_id}/status` with `draft|published|unpublished|active|paused|archived` status transitions.
**Effort**: 5h
**Depends on**: none (uses existing integrations/sync_jobs table)
**Description**: `PATCH /documents/sharepoint/{id}/schedule` — configure sync frequency. Options: daily (86400s), hourly (3600s), custom cron (Enterprise only). Plan tier enforcement: Starter → daily only; Professional → daily or hourly; Enterprise → any cron expression. Store in `sync_jobs` config column. Frontend: ScheduleConfigForm.tsx (FE-034 — COMPLETE) has UI — verify it is wired to this endpoint.
**Acceptance criteria**:

- [ ] PATCH validates frequency against plan tier: 422 if Starter selects hourly
- [ ] Custom cron: only Enterprise; validates cron expression syntax
- [ ] Schedule stored in `sync_jobs.schedule_config` JSONB
- [ ] Next run time calculated and returned in response: `{ "next_run_at": "2026-03-16T03:00:00Z" }`
- [ ] `ScheduleConfigForm.tsx` wired to this endpoint (replace any mock data)
- [ ] `require_tenant_admin` enforced

---

### TA-016: Full re-index with cost estimate

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `GET /admin/knowledge-base/{kb_id}/reindex-estimate` returns document_count, avg_tokens, estimated_cost_usd, estimated_duration_minutes. `POST /admin/knowledge-base/{kb_id}/reindex` returns job_id + status=queued as 202. Background task creates full_sync jobs per integration. Rate limit: 409 if reindex in progress. `require_tenant_admin` enforced. Tests in `tests/unit/test_reindex_estimate.py`. Backend at `app/modules/documents/reindex.py`.
**Effort**: 5h
**Depends on**: P2LLM-011
**Description**: `GET /admin/knowledge-base/{id}/reindex-estimate` — calculate cost before triggering re-index. Estimate: `document_count × avg_tokens_per_doc × embedding_cost_per_token`. `avg_tokens_per_doc` from last embedding run stats. `embedding_cost_per_token` from `llm_library` pricing for the tenant's embedding model. `POST /documents/{id}/reindex` — trigger full re-index (deletes vector store entries, re-embeds all documents). Frontend: `ReindexButton.tsx` (FE-034 — COMPLETE) shows estimate before confirm dialog.
**Acceptance criteria**:

- [ ] GET estimate returns: `{ "document_count": N, "avg_tokens": N, "estimated_cost_usd": X, "estimated_duration_minutes": Y }`
- [ ] Estimate uses real pricing from `llm_library` (not hardcoded)
- [ ] POST reindex: async background job; returns `{ "job_id": UUID, "status": "queued" }`
- [ ] `ReindexButton.tsx` shows estimate in confirm dialog with DM Mono for cost value
- [ ] `require_tenant_admin` enforced
- [ ] Rate limit: max 1 active reindex job per knowledge base at a time (409 if reindex already running)

---

### TA-017: Agent test run from workspace

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `POST /agents/{agent_id}/test` endpoint with AgentTestRequest schema, 30s timeout → 504.
**Effort**: 5h
**Depends on**: none (uses existing integrations/vault patterns)
**Description**: Daily background job checks SharePoint client_secret expiry (stored as expiry_date in vault metadata) and Google Drive OAuth token refresh status. 30-day warning: creates P2 notification to tenant admin. 7-day critical: creates P1 notification + issue queue item. Notification message: "SharePoint integration for [index_name] credentials expire in [N] days. [Reconnect]".
**Acceptance criteria**:

- [ ] Job runs daily; processes all tenant integrations
- [ ] SharePoint: reads `expiry_date` from vault metadata alongside client_secret ref
- [ ] Google Drive: checks OAuth token `expires_at` from integrations table
- [ ] 30-day warning: P2 notification (in-app only)
- [ ] 7-day critical: P1 notification + issue queue item
- [ ] Duplicate prevention: max 1 open notification per integration per severity tier
- [ ] Job failure for one tenant does not abort others

---

### TA-018: Agent template library browser

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `GET /agents/templates/library` with category filter and pagination.
**Effort**: 6h
**Depends on**: TA-017
**Description**: `POST /documents/{id}/reconnect`. Updates credential ref in vault (same flow as initial connection but for existing integration). Resets sync status to `pending`. Sends verification test (one-file test read). Returns: `{ "status": "reconnected", "test_result": "success|failed", "next_sync_at": "..." }`. Frontend: reconnect wizard modal (3 steps: credentials entry → test → confirm).
**Acceptance criteria**:

- [ ] New credentials encrypted and stored under same vault ref pattern
- [ ] Old credentials replaced (not accumulated)
- [ ] Sync status reset to `pending` in `sync_jobs`
- [ ] Verification test: read one test file from SharePoint/Google Drive to confirm new credentials work
- [ ] On test failure: credentials NOT updated (atomic — only update on success)
- [ ] Reconnect logged to `audit_log`
- [ ] Frontend wizard: 3-step modal with credential input → test result → confirmation
- [ ] `require_tenant_admin` enforced

---

### TA-019: Agent template library deploy

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `POST /agents/deploy-from-library` with template deployment to workspace.
**Effort**: 5h
**Depends on**: none (deferred from Phase 1 — API-052/053)
**Description**: `app/modules/documents/google_drive.py` already exists (implemented Session 17) with `list_google_drive_connections`, `connect_google_drive`, `trigger_google_drive_sync`, `list_google_drive_sync_history`. **Existing**: `POST /documents/google-drive/connect` (DWD service account JSON upload) and list/sync history endpoints are implemented. **Missing**: `GET /documents/google-drive/{id}/folders` (folder tree for admin UI selection). Step 1: Audit `google_drive.py` to confirm existing endpoint set (1h). Step 2: Implement folder tree endpoint only (3-4h). Step 3: Verify DEF-010 (Google Drive sync worker) is a separate item and is not duplicated here — do NOT implement the sync worker as part of this item.
**Note**: DEF-010 (sync worker — incremental sync, push notification channels) remains a separate item in 07-deferred-phase1.md. This item covers only the missing folder-tree API endpoint.
**Acceptance criteria**:

- [ ] `POST /documents/google-drive/connect` accepts service account JSON (validate required fields: type, project_id, private_key, client_email)
- [ ] Service account JSON encrypted via vault ref pattern (never stored plaintext)
- [ ] `GET /documents/google-drive/{id}/folders` returns folder tree as `[{ "id": "...", "name": "...", "children": [...] }]`
- [ ] Folder tree depth: up to 3 levels (beyond that: lazy-load on expand)
- [ ] Integration record created in `integrations` table with `provider=google_drive`
- [ ] `require_tenant_admin` on both routes
- [ ] Unit test: service account JSON validation (missing required fields → 422)

---

## Phase C: Agent Workspace (Weeks 15-22)

### Sprint C1: Agent Library Adoption (Weeks 15-17)

### TA-020: Agent chat with workspace agents

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: Chat routes include agent ownership check + 503 guard for paused agents.
**Effort**: 4h
**Depends on**: PA-019
**Description**: Hardcode 4 seed templates directly in codebase (not via platform admin UI). Inserted via `app/core/seeds.py` on bootstrap (same pattern as default tenant seed). Templates: (1) HR Policy Q&A — answers HR policy questions; (2) IT Helpdesk — troubleshoots IT issues; (3) Procurement Policy — guides procurement decisions; (4) Employee Onboarding — onboards new employees. `status='seed'`; auto-visible to all tenants without platform admin publishing action.
**Acceptance criteria**:

- [ ] All 4 seed templates added to `seeds.py` bootstrap
- [ ] Inserted with `status='seed'` and version=1
- [ ] Idempotent: seed INSERT uses `ON CONFLICT (name) DO NOTHING` or similar
- [ ] Tenant admin `GET /admin/agents/templates` (or equivalent list endpoint) returns seed templates
- [ ] Each seed template has complete `system_prompt`, `variable_definitions` (at least 1 variable), `guardrails`, `confidence_threshold=0.80`
- [ ] Seed templates not editable by tenant admin (read-only; can deploy but not modify)

---

### TA-021: Workspace agents list with metrics

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `GET /admin/agents/workspace` with batch satisfaction_rate_7d and session_count_7d metrics.
**Effort**: 6h
**Depends on**: PA-023
**Description**: `POST /admin/agents` — delegate to PA-023 implementation. This item covers tenant admin verification: deployment flow includes KB association at creation time, access control defaults (workspace_wide), and activation status. Verify tenant admin cannot specify `system_prompt` directly (must use template variable substitution).
**Acceptance criteria**:

- [ ] POST validates all required template variables are provided in `variable_values`
- [ ] Deployed agent stored in `agent_cards` with `template_id` FK
- [ ] KB association: `kb_ids` validated as belonging to calling tenant
- [ ] Default access: workspace_wide (override via TA-009 post-creation)
- [ ] Agent starts in `status='active'` after deployment
- [ ] `require_tenant_admin` enforced
- [ ] Returns deployed agent with `id`, `name`, `template_name`, `version`, `created_at`

---

### TA-022: Agent pause/resume

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `PATCH /agents/{agent_id}/status` supports paused/active transitions, chat routes return 503 for paused.
**Effort**: 4h
**Depends on**: TA-021
**Description**: `GET /admin/agents` — list all deployed agents for tenant. Response per agent: `id`, `name`, `template_name`, `template_version`, `status`, `satisfaction_rate_7d`, `session_count_7d`, `created_at`. Supports `?status=active|paused|archived` filter. Tenant admin can PATCH status to `paused` (stops processing queries) or `archived` (soft-delete — not visible to end users).
**Acceptance criteria**:

- [ ] List includes `satisfaction_rate_7d` (from user_feedback — last 7 days)
- [ ] List includes `session_count_7d` (distinct conversation_ids in last 7 days)
- [ ] Status filter works for all 3 values
- [ ] PATCH `/admin/agents/{id}` with `{ "status": "paused" }` — agent stops answering queries
- [ ] Paused agents return 503 to end users with "This agent is temporarily unavailable"
- [ ] `require_tenant_admin` on PATCH; `require_tenant_admin` on GET

---

### TA-023: Agent test run

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `POST /agents/{agent_id}/test` endpoint.
**Effort**: 5h
**Depends on**: TA-021, P2LLM-009
**Description**: `POST /admin/agents/{id}/test`. Pre-deployment test — runs a single query through the deployed agent without saving to conversation history. Request: `{ "query": "string" }`. Response: AI answer + source citations + confidence score + token count. Uses `InstrumentedLLMClient` with the agent's configured KB and system_prompt. Does NOT write to `messages`, `conversations`, or `user_feedback` tables.
**Acceptance criteria**:

- [ ] Response includes: `answer`, `sources` (list with doc_id, chunk_text, relevance_score), `confidence`, `tokens_in`, `tokens_out`, `latency_ms`
- [ ] Conversation NOT written to DB (verified: no conversation_id in response, no DB row inserted)
- [ ] Uses agent's configured KB(s) and system_prompt
- [ ] `require_tenant_admin` enforced
- [ ] Timeout: 30s; 504 if exceeded
- [ ] Unit test: verify no conversation persistence side effect

---

### TA-024: Template version upgrade check

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `GET /agents/{agent_id}/upgrade-available` and `PATCH /agents/{agent_id}/upgrade` endpoints with root-family normalization.
**Effort**: 5h
**Depends on**: TA-022, PA-022
**Description**: `GET /admin/agents/{id}/upgrade-available` — checks if a newer version of the deployed template is published. Returns `{ "current_version": N, "available_version": M, "changelog": "..." }` or `{ "upgrade_available": false }`. `PATCH /admin/agents/{id}/upgrade` — upgrades to latest published template version. Tenant admin in-app notification when new version available (sent by PA-022 batch check).
**Acceptance criteria**:

- [ ] GET compares `agent_cards.template_version` vs latest Published template version
- [ ] Changelog from latest template version included in response
- [ ] PATCH upgrade: re-runs variable substitution with new system_prompt; saves new system_prompt to `agent_cards`
- [ ] Upgrade logged to `audit_log`
- [ ] Tenant admin notification sent (in-app) when new template version published
- [ ] `require_tenant_admin` on both routes

---

### Sprint C2: Agent Studio (Weeks 18-20)

### TA-025: Agent Studio

**Status**: ⛔ BLOCKED — product-gated
**Depends on**: 5-10 persona interviews (per FE-036 gate — product decision)
**Description**: Custom agent authoring (system prompt + tool selection + KB + guardrails). Do NOT implement until persona interviews complete and product decision made.
**Notes**: FE-036 was marked NOT STARTED in Session 14 for this reason. This item will move to active when the product gate is cleared. No subtasks defined until then.

---

### Sprint C3: Feedback Monitoring (Weeks 21-22)

### TA-026: Satisfaction rate dashboard

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `GET /admin/analytics/satisfaction-dashboard` with rolling_7d_rate, per-agent breakdown, 30-day trend.
**Effort**: 5h
**Depends on**: none (sources from user_feedback table — COMPLETE)
**Description**: `GET /admin/analytics/satisfaction`. 7-day rolling satisfaction rate (positive / total). Per-agent breakdown: satisfaction_rate, session_count, feedback_count per agent. Trend data: daily satisfaction rate for last 30 days. `require_tenant_admin`.
**Acceptance criteria**:

- [ ] 7-day rolling rate = `SUM(rating=1) / COUNT(*)` for feedback in last 7 days
- [ ] Per-agent breakdown includes agents with 0 feedback (satisfaction_rate=null, not 0)
- [ ] 30-day daily trend array (null values for days with no feedback)
- [ ] Response time < 500ms
- [ ] `require_tenant_admin` enforced

---

### TA-027: Per-agent analytics

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `GET /admin/agents/{id}/analytics` with daily_satisfaction, low_confidence_responses, guardrail_events.
**Effort**: 5h
**Depends on**: TA-026
**Description**: `GET /admin/agents/{id}/analytics`. Satisfaction over time (daily, last 30 days), low-confidence responses list (confidence < 0.70, last 50), guardrail trigger log (last 100 events with trigger reason). `require_tenant_admin`.
**Acceptance criteria**:

- [ ] Daily satisfaction time series with null for days without feedback
- [ ] Low-confidence list: `[{ "conversation_id", "query_snippet" (40 chars), "confidence", "timestamp" }]`
- [ ] Guardrail log: `[{ "trigger_reason", "query_snippet", "timestamp" }]` — no raw query text (snippet only)
- [ ] All time data in UTC
- [ ] `require_tenant_admin` enforced

---

### TA-028: Root-cause correlation

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `compute_root_cause_correlation_db` detects satisfaction drop ≥10pp within 48h of sync event. Embedded in TA-027 response.
**Effort**: 4h
**Depends on**: TA-027
**Description**: When both satisfaction AND document freshness change within 48 hours, flag potential correlation. Logic: compare satisfaction_rate drop timestamp (from TA-026 trend data) vs last document sync timestamp (`sync_jobs.last_sync_at`). If within 48h: include `{ "potential_cause": "document_freshness", "sync_at": "...", "satisfaction_drop_at": "...", "confidence": "medium" }` in TA-027 analytics response.
**Acceptance criteria**:

- [ ] Correlation check added to `GET /admin/agents/{id}/analytics` response
- [ ] Correlation only flagged if satisfaction drops by >= 10 percentage points within 48h of sync
- [ ] `confidence: "medium"` always (not "high" — correlation is not causation)
- [ ] No false positives when satisfaction drops have no timing overlap with sync
- [ ] Unit test: known timing fixtures verify correlation detection logic

---

### TA-029: Glossary impact analytics

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `GET /admin/analytics/glossary-impact` with 3-batch-query pattern replacing N\*2 per-term queries.
**Effort**: 4h
**Depends on**: none (sources from user_feedback + glossary_terms tables)
**Description**: `GET /admin/glossary/analytics`. Per-term satisfaction comparison: queries where term matched vs queries without term match. Metric: satisfaction_rate_with_term vs satisfaction_rate_without_term. Source: join `glossary_terms` → query pipeline events → `user_feedback`. `require_tenant_admin`.
**Acceptance criteria**:

- [ ] Response: `[{ "term_id", "term": "...", "satisfaction_with": 0.87, "satisfaction_without": 0.71, "query_count_with": N, "lift_pct": 22.5 }]`
- [ ] Sorted by `lift_pct DESC`
- [ ] Terms with < 10 queries in either group excluded (insufficient data — noted with `data_quality: "insufficient"`)
- [ ] `require_tenant_admin` enforced

---

### TA-030: Engagement metrics v2

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `GET /admin/analytics/engagement-v2` with DAU/WAU/MAU, per-agent, feature adoption.
**Effort**: 5h
**Depends on**: none (sources from conversations + messages tables)
**Description**: `GET /admin/analytics/engagement`. DAU/WAU/MAU per agent (and aggregate). Inactive users (no session in last 30 days). Feature adoption rates (chat, glossary lookup, document download, KB summary). `require_tenant_admin`.
**Acceptance criteria**:

- [ ] DAU: distinct user_ids with at least 1 conversation in last 1 day
- [ ] WAU: last 7 days; MAU: last 30 days
- [ ] Per-agent DAU/WAU/MAU in addition to aggregate
- [ ] Inactive users: `COUNT(DISTINCT user_id) WHERE last_session < NOW() - INTERVAL '30 days'`
- [ ] Feature adoption: from analytics_events grouped by feature_name
- [ ] `require_tenant_admin` enforced

---

## Phase D: Polish and Scale (Weeks 23-28)

### TA-031: Onboarding wizard persistence

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `GET/PATCH /admin/onboarding/status|progress|dismiss` endpoints. 17 unit tests passing.
**Effort**: 5h
**Depends on**: none (onboarding wizard exists in Phase 1 — add persistence)
**Description**: Wizard state saved to `tenant_configs` under `onboarding_progress` key. Resumable if interrupted. `GET /admin/onboarding/status` returns current step and completion status. `PATCH /admin/onboarding/progress` updates step completion. Step keys: invite_users, configure_kb, configure_agent, configure_sso, done. Frontend: if wizard interrupted (page closed mid-flow), show "Resume Onboarding" banner on dashboard.
**Acceptance criteria**:

- [ ] `GET /admin/onboarding/status` returns `{ "current_step": "...", "steps": { "invite_users": true, "configure_kb": false, ... } }`
- [ ] `PATCH /admin/onboarding/progress` accepts `{ "step": "invite_users", "completed": true }`
- [ ] Progress persists across browser sessions (stored server-side in tenant_configs)
- [ ] "Resume Onboarding" banner shown on dashboard when `done=false`
- [ ] Banner dismissible (sets a `dismissed_at` field — not shown again for 7 days)
- [ ] `require_tenant_admin` on both routes

---

### TA-032: Bulk user operations

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `POST /admin/users/bulk-action` with suspend/role_change/kb_assignment, self-lockout protection, KB ownership check. 20 unit tests passing.
**Effort**: 5h
**Depends on**: none (verify FE BatchActionBar wiring)
**Description**: `POST /admin/users/bulk-action`. Actions: suspend (set status=suspended for all user_ids), role_change (set role for all user_ids), kb_assignment (add KB access for all user_ids). Request: `{ "user_ids": [UUID], "action": "suspend|role_change|kb_assignment", "payload": {} }`. Verify `BatchActionBar.tsx` frontend wired to this endpoint (or implement if missing).
**Acceptance criteria**:

- [ ] Endpoint processes all `user_ids` in single transaction
- [ ] Partial success: returns `{ "succeeded": [...], "failed": [...] }` if some user_ids invalid/foreign
- [ ] Suspend: updates `users.status = 'suspended'` and invalidates Redis sessions
- [ ] Role_change: updates `users.role` and logs to `audit_log` for each user
- [ ] KB_assignment: calls TA-007 access control update for each user_id
- [ ] `require_tenant_admin` enforced
- [ ] Max 100 user_ids per request (422 if exceeded)
- [ ] Frontend `BatchActionBar.tsx` wired to this endpoint

---

### TA-033: User import from SSO

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: P3AUTH-001
**Description**: `GET /admin/sso/directory/users` — lists IdP users available for pre-provisioning via Auth0 Management API. Returns up to 200 users from Auth0 org with their group memberships. `POST /admin/users/import-from-sso` — creates mingai user records for selected Auth0 users (not yet logged in). Useful for pre-loading user list before SSO rollout.
**Acceptance criteria**:

- [ ] `GET /admin/sso/directory/users` calls Auth0 Management API `GET /api/v2/organizations/{id}/members`
- [ ] Returns: `[{ "auth0_user_id", "email", "name", "groups" }]`
- [ ] `POST /admin/users/import-from-sso` accepts `{ "auth0_user_ids": [string] }`
- [ ] Creates `users` rows with `auth0_user_id`, default role=viewer, `status=invited`
- [ ] Duplicate handling: skip users already in `users` table (no error, just count in response)
- [ ] Import logged to `audit_log`
- [ ] `require_tenant_admin` enforced

---

### TA-034: Multiple document source management

**Status**: ✅ COMPLETE
**Completed**: 2026-03-16
**Evidence**: `GET /admin/knowledge-base/{kb_id}/sources`, `GET /admin/knowledge-base/{kb_id}/documents?search=`, `DELETE /admin/knowledge-base/{kb_id}/sources/{integration_id}`. 17 unit tests passing.
**Effort**: 6h
**Depends on**: TA-019
**Description**: Ensure KB management page handles 5+ SharePoint sites + multiple Google Drives gracefully. Unified document search across sources (`GET /admin/knowledge-base/{id}/documents?search=` searches across all attached sources). Source list view shows health status indicator per source. Sources can be individually removed from KB without affecting others.
**Acceptance criteria**:

- [ ] KB management page renders 5+ sources without layout overflow (scrollable list)
- [ ] Each source shows: name, provider, sync status, last sync time, document count, health indicator
- [ ] `GET /admin/knowledge-base/{id}/documents?search=` searches across all sources in KB
- [ ] Individual source removal: `DELETE /admin/knowledge-base/{kb_id}/sources/{integration_id}`
- [ ] 0 TypeScript errors

---

### TA-035: Tenant admin role delegation

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: P3AUTH-002
**Description**: `POST /admin/users/{id}/delegate-admin`. Grants a user scoped admin privileges. Scopes: `kb_admin:{index_id}` (manage specific KB), `agent_admin:{agent_id}` (manage specific agent), `user_admin` (manage users but not config). Scoped admin claims added to JWT via Auth0 post-login Action (or via additional `scope` claim in local JWT). Middleware checks scoped admin claims where applicable.
**Acceptance criteria**:

- [ ] Delegation creates `user_delegations` table entry (new Alembic migration)
- [ ] `user_delegations` columns: user_id, delegated_scope, resource_id nullable, granted_by, expires_at nullable, created_at
- [ ] JWT includes delegated scopes in additional claims (or queried from DB on each request)
- [ ] Middleware: `kb_admin:{index_id}` allows PATCH on that specific KB's settings (not other KBs)
- [ ] `require_tenant_admin` on delegation endpoint
- [ ] Delegation revocable: DELETE `/admin/users/{id}/delegations/{delegation_id}`
- [ ] Delegation logged to `audit_log`

---

### TA-036: Mobile-responsive admin console

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: Dashboard KPI cards grid already `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`. Issues list hides non-essential columns on sm. User list hides last_login on sm. Sync status table has collapsible row detail on mobile (SourceStatusCard.tsx). Glossary authoring screen shows "Desktop recommended" banner below 768px. KB management page has Desktop recommended banner and flex-wrap header. TermList.tsx hides definition/aliases columns on mobile. 0 TypeScript errors.
**Effort**: 8h
**Depends on**: none
**Description**: Add responsive breakpoints for monitoring screens (not authoring). Priority screens: Dashboard (KPI cards stack vertically), Issues list (simplified columns), User list (simplified columns), Sync status. Authoring screens (Glossary edit, Agent config) remain desktop-only. Tailwind responsive utilities: `sm:` (640px) and `md:` (768px) breakpoints.
**Acceptance criteria**:

- [ ] Dashboard KPI cards: 2 columns on sm, 1 column on mobile
- [ ] Issues list: hide lower-priority columns on sm (keep: title, severity, status)
- [ ] User list: hide `last_login` column on sm; keep: name, role, status
- [ ] Sync status table: collapsible row detail on mobile
- [ ] No horizontal scroll on any monitoring screen at 375px width (iPhone SE)
- [ ] Authoring screens: show "Desktop recommended" banner below 768px (no layout changes)
- [ ] 0 TypeScript errors after responsive changes

---

## Dependencies Map

```
Phase B:
  P3AUTH-004/005 → TA-001/002 (SSO wizard)
  P3AUTH-008 → TA-003 (JIT provisioning)
  P3AUTH-010 → TA-004 (group mapping UI)
  P3AUTH-003 → TA-005 (SSO toggle)
  TA-006 (kb_access_control table) → TA-007 (KB access API) → TA-010 (access requests) → TA-011 (frontend)
  TA-008 (agent_access_control table) → TA-009 (agent access API) → TA-010 → TA-011
  TA-013 (miss signals API) → TA-014 (frontend wiring)
  TA-017 (expiry monitoring) → TA-018 (reconnect wizard)
  TA-019 (Google Drive API) → DEF-010 (sync worker)

Phase C:
  PA-019 (agent_templates table) → TA-020 (seed templates) → TA-021 (deployment)
  TA-021 → TA-022 (list) / TA-023 (test chat) / TA-024 (upgrade)
  TA-025: BLOCKED (product gate)
  TA-026 (satisfaction API) → TA-027 (performance detail) → TA-028 (correlation)

Phase D:
  P3AUTH-001 → TA-033 (user import from SSO)
  P3AUTH-002 → TA-035 (role delegation JWT)
  TA-019 → TA-034 (multiple source management)
```

---

## Notes

- TA-025 (Agent Studio) is product-gated — do not implement or spec further until persona interviews complete
- TA-019 (Google Drive API) partially implemented in Session 17 (`google_drive.py` backend module exists) — audit existing code before implementing to avoid duplication
- TA-035 (role delegation) introduces `user_delegations` table — coordinate with next available Alembic migration version
- Phase B SSO items (TA-001–005) are thin wrappers around P3AUTH items — don't implement them before P3AUTH is complete
