# 50. Agent Template A2A Compliance & Capabilities -- Requirements Breakdown

> **Status**: Requirements Analysis
> **Date**: 2026-03-21
> **Purpose**: Close 10 implementation gaps between the product specification (docs 18, 25, 33) and the current codebase. Phased into three delivery groups with explicit dependency ordering.
> **Depends on**: `18-a2a-agent-architecture.md`, `25-a2a-guardrail-enforcement.md`, `33-agent-library-studio-architecture.md`
> **Current schema baseline**: `agent_cards` (v001 + v005 + v007 + v022 + v030), `agent_templates` (v020), `agent_access_control` (v028), `mcp_servers` (v036)

---

## Executive Summary

| Attribute          | Value                               |
| ------------------ | ----------------------------------- |
| Total gaps         | 10                                  |
| Phase A (blockers) | 4 requirements (must ship together) |
| Phase B (A2A)      | 3 requirements                      |
| Phase C (ops)      | 3 requirements                      |
| Risk level         | High (data loss + compliance gaps)  |
| Estimated effort   | 8-12 days total                     |

---

## Architecture Decision Records

### ADR-050-A: KB Bindings and Tool Assignments -- First-Class Columns vs JSONB Capabilities Bag

#### Status

Proposed

#### Context

The current codebase stores `kb_ids` and `tool_ids` inside a JSONB `capabilities` column on `agent_cards`. This was an expedient choice during the Agent Studio MVP (API-069 to API-073). The product spec in doc 33 defines `kb_bindings` as a structured array with per-KB access overrides (`required_role`, `display_name`) and `tool_ids` as references to MCP servers with join-table semantics.

The problem is threefold:

1. **Data loss**: KB IDs stored in JSONB are not FK-constrained. Deleting an integration leaves orphaned IDs in the capabilities blob. No cascade, no referential integrity.
2. **Query inefficiency**: Finding "all agents that use integration X" requires full-table JSONB scans.
3. **Access control gap**: Per-KB role overrides (`required_role`) cannot be expressed in a flat string array.

#### Decision

Introduce two new relational structures:

1. **`agent_kb_bindings`** table: `(id, agent_id FK agent_cards, integration_id FK integrations, display_name, required_role, sort_order, created_at)`. One row per agent-KB relationship. FK cascade on both sides.

2. **`agent_tool_assignments`** table: `(id, agent_id FK agent_cards, mcp_server_id FK mcp_servers, created_at)`. One row per agent-tool relationship. FK cascade on both sides.

The existing `capabilities.kb_ids` and `capabilities.tool_ids` JSONB fields are preserved read-only during a transition period. A data migration copies existing values into the new tables. After verification, a subsequent migration removes the JSONB fields.

#### Consequences

**Positive**:

- FK constraints prevent orphaned references (data integrity)
- Per-KB role overrides are now first-class columns
- Efficient queries for "which agents use this KB/tool"
- CASCADE delete handles integration removal cleanly

**Negative**:

- Two new tables add migration complexity
- Deploy flow must write to both new tables (not just JSONB)
- Transition period has dual-write overhead

#### Alternatives Considered

**Option 1: Structured JSONB with CHECK constraints**

- Store `kb_bindings` as a JSONB array with a JSON Schema CHECK constraint. Rejected because PostgreSQL JSON Schema validation is limited, does not support FK integrity, and per-KB role overrides still require application-level enforcement.

**Option 2: Single `agent_associations` polymorphic table**

- One table for both KB and tool bindings with a `type` discriminator. Rejected because FK targets differ (`integrations` vs `mcp_servers`), making polymorphic FK impossible without removing the constraint.

---

### ADR-050-B: Guardrail Output Filter Placement -- Orchestrator Layer vs Agent Container

#### Status

Proposed

#### Context

Doc 25 specifies a three-layer guardrail system. Layer 2 (output filter) is the hard enforcement mechanism. The question is where Layer 2 runs in the current architecture.

The mingai orchestrator is the Python FastAPI backend (`app/modules/chat/`). There are no separate "agent containers" -- all agent execution happens in the chat pipeline within the same process. The product spec (doc 25) describes the output filter as running "inside the A2A agent container before returning the Artifact." In the current monolithic architecture, this translates to a filter step in the chat response pipeline, after LLM synthesis and before SSE streaming to the client.

The alternative is to place the filter at the prompt_builder level (before LLM call), but this only addresses Layer 1 (prompt positioning) and cannot catch LLM output violations.

#### Decision

Implement the output filter as a post-synthesis middleware in the chat pipeline:

```
prompt_builder -> LLM synthesis -> [OUTPUT FILTER] -> SSE streaming
```

The filter is a synchronous function call, not a separate service. It receives the synthesized text and the agent's guardrail ruleset (loaded from `agent_templates.guardrails` or `agent_cards.capabilities.guardrails`). It returns either the original text, a redacted version, or a block response.

Filter configuration is stored in `agent_templates.guardrails` (JSONB, already exists in v020) for template-based agents, and in `agent_cards.capabilities.guardrails` for custom agents.

The filter fails closed: any exception in the filter returns a safe canned error, never the unfiltered response.

#### Consequences

**Positive**:

- No infrastructure change required (no sidecar, no new service)
- Latency impact is minimal (regex + optional embedding similarity)
- Single enforcement point for all agent types (template + custom)
- Fail-closed behavior prevents compliance bypass

**Negative**:

- Filter runs in the hot path of every response (must be fast)
- `semantic_check` rule type requires embedding model call (adds ~100ms); deferred to Phase B
- No process-level isolation between agent execution and filter

#### Alternatives Considered

**Option 1: Separate filter microservice**

- HTTP call to a dedicated filter service. Rejected because the current architecture is monolithic and adding a synchronous HTTP hop to every response doubles latency for marginal isolation benefit. Revisit if/when agent execution moves to separate containers.

**Option 2: LLM-based output classification**

- Use a second LLM call to classify the output. Rejected for latency (300-500ms per response) and cost (doubles LLM spend). `keyword_block` + `citation_required` rules cover 90% of cases without LLM.

---

### ADR-050-C: Agent Templates Schema Extension Strategy -- ALTER TABLE vs New Version Table

#### Status

Proposed

#### Context

The `agent_templates` table (v020) is missing three columns specified in doc 33: `required_credentials` (JSONB), `auth_mode` (VARCHAR), and `plan_required` (VARCHAR). These columns are needed for the adoption workflow (plan gating, credential collection, auth mode display).

Two approaches: (1) ALTER TABLE to add columns, or (2) create a new `agent_template_versions` table that holds versioned metadata alongside the core template row.

#### Decision

ALTER TABLE to add three nullable columns to `agent_templates`. Rationale:

- The columns are template-level metadata, not version-specific. `plan_required` and `auth_mode` do not change between versions of the same template. `required_credentials` changes only when the underlying integration changes (rare, accompanies a major version bump).
- A separate versions table adds JOIN overhead to every catalog query and complicates the already-working upgrade-available check (TA-024).
- All three columns are nullable with safe defaults (`auth_mode` defaults to `'none'`, `plan_required` defaults to NULL meaning "all plans", `required_credentials` defaults to `'[]'`).

Migration: single Alembic file, reversible. No data migration needed (new columns are NULL/default for existing rows).

#### Consequences

**Positive**:

- Minimal schema change, no new tables
- Backward compatible (existing queries unaffected)
- Catalog API can immediately filter by `plan_required`

**Negative**:

- If `required_credentials` schema needs to change per-version in the future, a migration to a versions table will be needed
- NULL `auth_mode` on existing rows means the API must handle the absence gracefully

#### Alternatives Considered

**Option 1: `agent_template_versions` table**

- Separate table with (template_id, version, required_credentials, auth_mode, plan_required). Rejected because it over-engineers for the current requirement. Can be introduced later if versioned credential schemas become necessary.

---

## Phased Requirements Breakdown

### Phase A: Data Integrity Blockers (Must Ship Together)

These four requirements address data loss and integrity issues. They share a migration dependency chain and must ship atomically.

---

#### REQ-A1: KB Bindings Table and Deploy Logic

**Gap**: `kb_ids` stored in JSONB capabilities blob without FK constraints. Deletions orphan references. Per-KB role overrides impossible.

**Acceptance Criteria**:

- `agent_kb_bindings` table exists with FK to `agent_cards.id` and `integrations.id`
- Deploy-from-library (API-073) writes to `agent_kb_bindings` instead of capabilities JSONB
- Create-agent (API-070) and update-agent (API-071) write to `agent_kb_bindings`
- Deleting an integration CASCADE-deletes its bindings
- GET agent detail returns `kb_bindings` array with `integration_id`, `display_name`, `required_role`
- Data migration copies existing `capabilities.kb_ids` to new table for all existing agents
- Frontend KB selector continues to work (already exists, just needs response shape update)

**Backend Changes**:

- New Alembic migration: `agent_kb_bindings` table
- Data migration: extract `capabilities.kb_ids` into new rows
- `deploy_from_library_db()`: INSERT into `agent_kb_bindings` after agent row
- `create_agent_studio_db()`: INSERT into `agent_kb_bindings`
- `update_agent_studio_db()`: DELETE + re-INSERT bindings
- `get_agent_by_id_db()`: LEFT JOIN to return bindings
- `_validate_kb_ids_for_tenant()`: already exists, reuse

**Frontend Changes**:

- Agent detail panel: read `kb_bindings` array from response (currently reads `capabilities.kb_ids`)
- Deploy form: already sends `kb_ids`, no change needed
- Agent Studio form: already sends `kb_ids`, no change needed

**Migration**: Yes -- new table + data migration

**Dependencies**: None (first in chain)

---

#### REQ-A2: Tool Assignments Table and MCP Server Linking

**Gap**: `tool_ids` stored in JSONB capabilities blob. No FK to `mcp_servers`. No validation that referenced tools exist.

**Acceptance Criteria**:

- `agent_tool_assignments` table exists with FK to `agent_cards.id` and `mcp_servers.id`
- Create-agent and update-agent write to `agent_tool_assignments`
- Deleting an MCP server CASCADE-deletes its assignments
- GET agent detail returns `tool_assignments` array with `mcp_server_id` and `name`
- Data migration copies existing `capabilities.tool_ids` to new table

**Backend Changes**:

- New Alembic migration: `agent_tool_assignments` table
- Data migration: extract `capabilities.tool_ids` and match to `mcp_servers.id`
- `create_agent_studio_db()`: INSERT into `agent_tool_assignments`
- `update_agent_studio_db()`: DELETE + re-INSERT assignments
- `get_agent_by_id_db()`: LEFT JOIN to return assignments
- New validation: `_validate_tool_ids_for_tenant()` -- confirm tool IDs exist in `mcp_servers` for this tenant

**Frontend Changes**:

- Agent detail panel: read `tool_assignments` from response
- Agent Studio form: tool selector reads from `/admin/mcp-servers` (already exists per DEF-005)

**Migration**: Yes -- new table + data migration

**Dependencies**: REQ-A1 (same migration batch), REQ-C3 (mcp_servers API must exist for tool validation)

---

#### REQ-A3: Agent Templates Schema Extension

**Gap**: `agent_templates` table missing `required_credentials`, `auth_mode`, `plan_required` columns per doc 33.

**Acceptance Criteria**:

- Three new columns on `agent_templates`: `required_credentials JSONB DEFAULT '[]'`, `auth_mode VARCHAR(30) DEFAULT 'none'`, `plan_required VARCHAR(50) NULL`
- `auth_mode` CHECK constraint: `('none', 'tenant_credentials', 'platform_credentials')`
- `plan_required` CHECK constraint: `('starter', 'professional', 'enterprise')` or NULL
- Platform admin publish/update endpoints accept and persist these fields
- Catalog API (API-039) returns these fields to tenant admins
- Catalog API filters by `plan_required` against caller's plan

**Backend Changes**:

- New Alembic migration: ALTER TABLE `agent_templates` ADD COLUMN x3
- `POST /platform/agent-templates`: accept `required_credentials`, `auth_mode`, `plan_required` in request schema
- `PATCH /platform/agent-templates/{id}`: add columns to `_TEMPLATE_UPDATE_ALLOWLIST`
- `GET /agents/templates`: return new columns in response
- Deploy-from-library: plan check before deployment (`template.plan_required <= user.plan`)

**Frontend Changes**:

- Platform admin template form: add `auth_mode` dropdown, `plan_required` dropdown, `required_credentials` JSON editor
- Tenant admin catalog: show plan badge, show "credentials required" indicator
- Deploy wizard: if `auth_mode == 'tenant_credentials'`, show credential input fields based on `required_credentials` schema

**Migration**: Yes -- ALTER TABLE

**Dependencies**: None (independent schema change)

---

#### REQ-A4: Agent Access Control Population on Deploy

**Gap**: `agent_access_control` table (v028) exists but is never populated during deploy. The deploy-from-library flow (API-073) accepts `access_mode` but only logs a warning that it is "not persisted" (line 643-651 of routes.py).

**Acceptance Criteria**:

- Deploy-from-library inserts an `agent_access_control` row with the requested `access_mode`
- Create-agent (Agent Studio) inserts an `agent_access_control` row
- Default mode (`workspace_wide`) creates a row (explicit default, not absence-means-default)
- Chat agent resolution checks `agent_access_control` before returning agent to user
- End-user agent list (`GET /agents`) filters by access control

**Backend Changes**:

- `deploy_from_library_db()`: INSERT into `agent_access_control` after agent creation
- `create_agent_studio_db()`: INSERT into `agent_access_control` after agent creation
- `deploy_agent_template_db()`: INSERT into `agent_access_control`
- Existing `PATCH /admin/agents/{id}/access` (agent_access_control.py) already handles updates -- no change
- `GET /agents` (end-user list, API-117): JOIN `agent_access_control` and filter by user's role/ID
- Data migration: INSERT `workspace_wide` rows for all existing `agent_cards` that lack an `agent_access_control` entry

**Frontend Changes**:

- None (access control selector already exists in deploy/studio forms; PATCH endpoint already works)

**Migration**: Yes -- data migration for existing agents

**Dependencies**: REQ-A1 (same migration batch)

---

### Phase B: A2A Compliance

These requirements implement A2A protocol compliance. They can ship independently after Phase A.

---

#### REQ-B1: Guardrail Runtime Output Filter

**Gap**: Doc 25 specifies a three-layer guardrail system. Layer 1 (prompt positioning) exists in `prompt_builder.py`. Layer 2 (output filter) and Layer 3 (registration audit) are not implemented.

**Acceptance Criteria**:

- Output filter runs after LLM synthesis, before SSE streaming
- Filter loads guardrail rules from `agent_templates.guardrails` (template agents) or `agent_cards.capabilities.guardrails` (custom agents)
- `keyword_block` rule type: regex match, action = block/redact
- `citation_required` rule type: data pattern present + citation pattern absent = warn
- Filter fails closed (exception = safe canned error, never unfiltered response)
- Violation audit log entry written for every triggered rule
- `semantic_check` and `scope_check` rule types deferred (require embedding model infrastructure)

**Backend Changes**:

- New module: `app/modules/chat/output_filter.py`
  - `AgentOutputFilter` class with `check(text, guardrails) -> FilterResult`
  - `GuardrailRule` dataclass: `id`, `type`, `patterns`, `on_violation`, `user_message`, `replacement`
  - `FilterResult` dataclass: `passed`, `rule_id`, `reason`, `action`, `filtered_text`
- `app/modules/chat/routes.py`: call `output_filter.check()` after synthesis, before streaming
- Violation logging: INSERT into `audit_log` with `action='guardrail_violation'`
- Circuit breaker: log + alert if filter error rate > 1%

**Frontend Changes**:

- Chat UI: handle new response shape when `action=block` (show user_message instead of AI response)
- Chat UI: handle `action=warn` (append warning footer to response)
- Chat UI: `action=redact` is transparent (filtered text replaces original)

**Migration**: None (guardrails JSONB column already exists on `agent_templates`)

**Dependencies**: None (independent of Phase A, but should ship after to avoid blocking)

---

#### REQ-B2: A2A Discovery Endpoint (/.well-known/agent.json)

**Gap**: A2A protocol requires each agent to publish an AgentCard at `/.well-known/agent.json`. Not implemented.

**Acceptance Criteria**:

- `GET /.well-known/agent.json?agent_id={id}` returns an A2A v0.3 compliant AgentCard
- AgentCard includes: `name`, `description`, `skills` (from capabilities), `url`, `provider`
- Unauthenticated access (A2A discovery is public by protocol spec)
- Only returns cards for agents with `status='active'` or `status='published'`
- Rate-limited (10 req/s per IP)

**Backend Changes**:

- New route in `app/api/router.py` or dedicated module: `GET /.well-known/agent.json`
- Query `agent_cards` by ID, format as A2A AgentCard JSON
- Response follows A2A v0.3 schema: `{ "name", "description", "url", "provider", "version", "skills": [...], "defaultInputModes": ["text"], "defaultOutputModes": ["text"] }`
- Rate limit middleware on this route only

**Frontend Changes**: None

**Migration**: None

**Dependencies**: None

---

#### REQ-B3: Credentials Vault Integration in Deploy Flow

**Gap**: Doc 33 specifies `credentials_vault_path` on agent instances, with credentials stored in tenant-scoped vault. Current deploy flow does not handle credential storage. `VaultClient` exists (`app/core/secrets/vault_client.py`) but is only used for HAR Ed25519 keys.

**Acceptance Criteria**:

- Deploy-from-library: if template has `auth_mode='tenant_credentials'`, request body must include `credentials` dict
- Credentials validated against `required_credentials` schema from template
- Each credential value stored via `VaultClient.store_secret()` at path `{tenant_id}/agents/{agent_id}/{credential_key}`
- `credentials_vault_path` stored on `agent_cards` row (new column needed)
- Credentials never returned in any GET response
- Credential update endpoint: `PATCH /admin/agents/{id}/credentials`

**Backend Changes**:

- Alembic migration: ADD COLUMN `credentials_vault_path TEXT` to `agent_cards`
- `DeployFromLibraryRequest` schema: add optional `credentials: Dict[str, str]`
- Deploy flow: validate credentials against template's `required_credentials`, store via vault, save vault path
- New endpoint: `PATCH /admin/agents/{id}/credentials` -- update stored credentials
- `get_agent_by_id_db()`: return `has_credentials: bool` (never return actual values)

**Frontend Changes**:

- Deploy wizard: conditional credential form fields when `auth_mode='tenant_credentials'`
- Agent detail panel: show credential status (stored/missing/expired), "Update Credentials" button
- Credential update modal: re-enter credential values

**Migration**: Yes -- ADD COLUMN

**Dependencies**: REQ-A3 (template must have `required_credentials` and `auth_mode` columns first)

---

### Phase C: Operational Completeness

These requirements address operational health and completeness. Ship after Phase B.

---

#### REQ-C1: Template Update Notifications

**Gap**: Doc 33 section 3.3 specifies that when platform admin publishes a new template version, all tenant instances based on that template receive an in-app notification. The upgrade-available check (TA-024) exists but is pull-based (tenant admin must check). No push notification on publish.

**Acceptance Criteria**:

- When platform admin publishes a new template version (`PATCH /platform/agent-templates/{id}` with status='Published'), the system finds all `agent_cards` rows with matching `template_id`
- For each affected tenant, an in-app notification is created: "Agent '{name}' has an update available (v{N}). What's new: {changelog}."
- Notification visible in tenant admin dashboard
- `agent_cards.template_update_available` boolean flag set to true
- Flag cleared when tenant admin upgrades (TA-024 upgrade endpoint)

**Backend Changes**:

- Alembic migration: ADD COLUMN `template_update_available BOOLEAN DEFAULT FALSE` to `agent_cards`
- Platform publish endpoint: after status change to 'Published', query `agent_cards WHERE template_id = :id`, SET `template_update_available = true`
- Create notification records (requires `notifications` table -- if it does not exist, create it)
- TA-024 upgrade endpoint: SET `template_update_available = false` after successful upgrade

**Frontend Changes**:

- Agent list: show update badge on agents where `template_update_available = true`
- Notification bell: show template update notifications
- Agent detail: "Update Available" banner with changelog and "Review & Update" button

**Migration**: Yes -- ADD COLUMN (+ possibly notifications table)

**Dependencies**: TA-024 (already implemented), REQ-A3 (template versioning)

---

#### REQ-C2: Agent Credential Health Check Job

**Gap**: Doc 33 section 8.1 specifies a daily scheduled job that re-tests credentials for all active agents with credential test classes. Not implemented.

**Acceptance Criteria**:

- Scheduled job runs daily per tenant (configurable via env var `CREDENTIAL_HEALTH_CHECK_HOUR`, default 02:00 UTC)
- For each active agent with `credentials_vault_path` set: fetch credentials from vault, run credential test
- If test fails: set `credential_status='failed'` on agent, create warning notification for tenant admin
- If test passes: set `credential_status='healthy'`
- If no test class exists: set `credential_status='unverifiable'` (no alert unless inactive 30+ days)
- Health check results visible in agent detail panel

**Backend Changes**:

- New module: `app/modules/agents/credential_health.py`
  - `CredentialTestRunner` with pluggable test classes per template type
  - `run_daily_credential_health_check(tenant_id)` async function
- Alembic migration: ADD COLUMN `credential_status VARCHAR(20) DEFAULT 'unknown'` to `agent_cards`
- Scheduler integration (APScheduler or equivalent) to run job daily
- Initial test classes: stub implementations that return `passed=None` (real Bloomberg/CapIQ tests deferred to integration phase)

**Frontend Changes**:

- Agent list: credential status indicator (green/yellow/red dot)
- Agent detail: credential health section with last check timestamp and status

**Migration**: Yes -- ADD COLUMN

**Dependencies**: REQ-B3 (credentials must be stored in vault first)

---

#### REQ-C3: MCP Servers API Routes Completion

**Gap**: `mcp_servers` table exists (v036). Basic CRUD routes exist in `app/modules/admin/mcp_servers.py` (POST, GET, DELETE). Missing: PATCH (update), health check endpoint, status toggle.

**Acceptance Criteria**:

- `PATCH /admin/mcp-servers/{id}` -- update name, endpoint, auth_type, auth_config
- `POST /admin/mcp-servers/{id}/verify` -- trigger health check, update `last_verified_at`
- `PATCH /admin/mcp-servers/{id}/status` -- toggle active/inactive
- GET response includes `last_verified_at` timestamp
- Health check: HTTP HEAD to endpoint, timeout 5s, update status

**Backend Changes**:

- `app/modules/admin/mcp_servers.py`: add PATCH, POST verify, PATCH status routes
- Health check: async HTTP HEAD to MCP server endpoint, update `last_verified_at` and `status`
- Validation: endpoint URL must be HTTPS in production (HTTP allowed in dev)

**Frontend Changes**:

- MCP servers management page: edit button, verify button, status toggle
- Status indicator: healthy/degraded/unavailable based on `last_verified_at` age

**Migration**: None (table already has all needed columns)

**Dependencies**: None (independent, but Phase A tool assignments depend on this)

---

## Dependency Graph

```
Phase A (ship together):
  REQ-A3 ──────────────────────────────── (independent)
  REQ-A1 ──────────────────────────────── (independent)
  REQ-A2 ── depends on ── REQ-C3 (soft)   (tool validation needs MCP API)
  REQ-A4 ──────────────────────────────── (independent)

Phase B (after Phase A):
  REQ-B1 ──────────────────────────────── (independent)
  REQ-B2 ──────────────────────────────── (independent)
  REQ-B3 ── depends on ── REQ-A3          (needs auth_mode, required_credentials)

Phase C (after Phase B):
  REQ-C1 ── depends on ── REQ-A3          (needs template versioning)
  REQ-C2 ── depends on ── REQ-B3          (needs credentials in vault)
  REQ-C3 ──────────────────────────────── (independent, but A2 soft-depends)
```

**Recommended build order** (respecting dependencies):

```
 1. REQ-C3  (MCP API completion -- unblocks REQ-A2 tool validation)
 2. REQ-A3  (agent_templates schema -- unblocks REQ-B3, REQ-C1)
 3. REQ-A1  (KB bindings table)
 4. REQ-A2  (tool assignments table)
 5. REQ-A4  (access control population)
 --- Phase A complete, single migration batch for A1+A2+A4 data migrations ---
 6. REQ-B1  (guardrail output filter)
 7. REQ-B2  (A2A discovery endpoint)
 8. REQ-B3  (credentials vault integration)
 --- Phase B complete ---
 9. REQ-C1  (template update notifications)
10. REQ-C2  (credential health check job)
 --- Phase C complete ---
```

---

## Migration Plan

All Phase A migrations should be in a single Alembic revision to ensure atomic rollback:

| Migration ID | Tables Affected                | Type         | Phase |
| ------------ | ------------------------------ | ------------ | ----- |
| v037         | `agent_templates`              | ALTER TABLE  | A     |
| v038         | `agent_kb_bindings` (new)      | CREATE TABLE | A     |
| v039         | `agent_tool_assignments` (new) | CREATE TABLE | A     |
| v040         | `agent_cards` + data migration | ALTER + DML  | A     |
| v041         | `agent_cards` (vault path)     | ALTER TABLE  | B     |
| v042         | `agent_cards` (update flag)    | ALTER TABLE  | C     |
| v043         | `agent_cards` (cred status)    | ALTER TABLE  | C     |

Note: v038 and v039 can share a single migration file if preferred. v040 handles both the `agent_access_control` backfill and the data migration from JSONB to relational tables.

---

## Risk Assessment

### High Probability, High Impact (Critical)

1. **Data migration from JSONB capabilities to relational tables (REQ-A1, REQ-A2)**
   - Risk: Existing `capabilities.kb_ids` may reference deleted integrations
   - Mitigation: Migration script must handle orphaned IDs gracefully (skip + log, do not fail)
   - Prevention: Run migration in dry-run mode on staging first

2. **Output filter false positives (REQ-B1)**
   - Risk: `keyword_block` patterns too aggressive, blocking legitimate responses ("buy groceries" triggers "buy" pattern on a procurement agent)
   - Mitigation: Golden test set per template (doc 25 section 6)
   - Prevention: Regex patterns must use word boundaries and context-aware matching

### Medium Risk (Monitor)

3. **Vault client reliability (REQ-B3)**
   - Risk: `LocalDBVaultClient` (dev fallback) stores secrets as base64 in vault_ref URI -- not encrypted
   - Mitigation: Existing design, documented in vault_client.py docstring
   - Prevention: CI test that `AZURE_KEY_VAULT_URL` is set in staging/production env

4. **A2A discovery endpoint abuse (REQ-B2)**
   - Risk: Public unauthenticated endpoint could be used for enumeration
   - Mitigation: Rate limiting (10 req/s/IP), only returns minimal AgentCard data
   - Prevention: Agent ID required in query param (no listing endpoint)

### Low Risk (Accept)

5. **Template update notification volume (REQ-C1)**
   - Risk: Platform publishes template update affecting 500 tenants, generating 500 notification INSERTs
   - Mitigation: Batch INSERT, async processing
   - Acceptance: Notification delivery is best-effort, not transactional with template publish

---

## Success Criteria

- [ ] All 10 gaps closed with passing integration tests
- [ ] KB bindings survive integration deletion (CASCADE verified)
- [ ] Tool assignments survive MCP server deletion (CASCADE verified)
- [ ] Deploy flow persists access control (no more warning log at line 643)
- [ ] Guardrail output filter blocks known violation patterns (golden test)
- [ ] Guardrail output filter fails closed on internal error
- [ ] `/.well-known/agent.json` returns valid A2A v0.3 AgentCard
- [ ] Credentials stored in vault, never returned in API responses
- [ ] Template publish triggers notification to affected tenants
- [ ] Credential health check runs on schedule and flags failures
- [ ] MCP servers fully CRUD-able with health verification

---

**Document Version**: 1.0
**Last Updated**: 2026-03-21
