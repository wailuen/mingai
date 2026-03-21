# 14 — Agent Template A2A Compliance

**Generated**: 2026-03-21
**Phase**: Agent Template A2A — Schema enforcement, KB bindings, access control, guardrails, discovery, tool ecosystem
**Numbering**: ATA-001 through ATA-058
**Stack**: FastAPI + PostgreSQL + pgvector + Redis + Next.js 14 / Obsidian Intelligence
**Related plan**: `workspaces/mingai/02-plans/14-agent-template-a2a-plan.md` (v1.1, red-team validated)
**Related research**: `workspaces/mingai/01-analysis/01-research/49-agent-template-a2a-gap-analysis.md`, `50-agent-template-requirements.md`, `51-agent-template-coc-analysis.md`, `52-agent-template-implementation-approach.md`
**Related value audit**: `workspaces/mingai/01-analysis/16-agent-template-value-audit/01-enterprise-buyer-perspective.md`, `02-ux-design-spec.md`
**UX flows**: `workspaces/mingai/03-user-flows/23-agent-template-flows.md`
**Status**: IN PROGRESS — Phase A+B COMPLETE (commits e3e2fcb, 8e5dd50). Phase C backend COMPLETE (commit 1fca7ec). COC rules ATA-048–055 COMPLETE. Frontend ATA-037–047 remaining. ATA-057 deferred.

---

## Overview

Ten gaps exist between the agent template architecture spec and the running code. The blast radius is severe: a tenant admin who configures KB bindings, access restrictions, tool assignments, and guardrails receives a `201 Created` response while none of those configurations take effect at runtime.

**Four CRITICAL gaps require immediate action (Phase A)**:

| Gap                                               | COC Fault Line     | Risk Today                                                             |
| ------------------------------------------------- | ------------------ | ---------------------------------------------------------------------- |
| Guardrails stored, never enforced                 | Security Blindness | Bloomberg agent will provide investment advice on demand               |
| `agent_access_control` never populated on deploy  | Security Blindness | All agents accessible to all workspace users regardless of restriction |
| KB bindings silently dropped                      | Security Blindness | All agents query the same index — KB config is cosmetic                |
| Silent discard comment in routes.py lines 639–651 | Convention Drift   | Admin believes restriction is active — it is not                       |

**Phase sequencing**: Phase A (Weeks 1–3) breaks silent data loss. Phase B (Weeks 4–6) completes A2A protocol compliance and guardrail enforcement. Phase C (Weeks 7–10) builds the MCP tool ecosystem and UX authoring surfaces.

**Must ship Phase A as a unit**: All Sprint 1–2 items share a migration dependency chain. Deploy all four together or deploy none.

---

## Alembic Chain

```
v044 (current head)
  └── v045 (agent_templates: required_credentials, auth_mode, plan_required) [Phase A Sprint 1]
        └── v046a (agent_cards GIN index on capabilities->kb_ids) [Phase A Sprint 2]
              └── v046b (agent_access_control backfill — DML only) [Phase A Sprint 2]
                    └── v047 (agent_cards: credentials_vault_path) [Phase B Sprint 4]
                          └── v048 (tool_catalog RLS update: allow degraded status) [Phase C Sprint 5]
```

Chain confirmed correct: v045 → v046a → v046b → v047 → v048. Each migration's `down_revision` must match the previous revision ID exactly.

---

## COC Institutional Rules (Must Be Encoded in Source)

The following 6 rules must be embedded in code comments/docstrings — not documents only:

| Rule        | Location                                                                  | Enforcement Point             |
| ----------- | ------------------------------------------------------------------------- | ----------------------------- |
| RULE A2A-01 | `orchestrator.py` class docstring + `OutputGuardrailChecker` docstring    | Stage 7b before Stage 8       |
| RULE A2A-02 | `GuardrailsSchema` Pydantic class docstring + create_agent inline comment | DB storage ≠ enforcement      |
| RULE A2A-03 | `deploy_agent_template_db()` docstring                                    | 422 on silent discard         |
| RULE A2A-04 | `_validate_ssrf_safe_url()` docstring in `a2a_routing.py`                 | Per-request SSRF check        |
| RULE A2A-05 | `run_daily_credential_health_check()` docstring                           | DistributedJobLock per tenant |
| RULE A2A-06 | `_AGENT_UPDATE_SQL` comment block in `agents/routes.py`                   | tenant_id in all UPDATE WHERE |

---

## Phase A — Foundation (Weeks 1–3)

**Objective**: Every field a tenant admin configures on an agent deploy must either be enforced or rejected with a 422. No silent discard.

> **WARNING — PHASE A MUST SHIP AS A UNIT**
> ATA-001 through ATA-014 MUST be deployed together in a single release.
> Do NOT merge individual items to production independently.
> Partial deploy creates inconsistent state: access control rows inserted
> but 422 gate not yet removed (or vice versa).
> Use a feature branch `feat/phase-a-agent-a2a` and merge all at once.

---

### ATA-001: v045 Migration — agent_templates schema extension

**Status**: [x] COMPLETE
**Priority**: P0 — CRITICAL, first in chain, unblocks ATA-002, ATA-009, ATA-025
**Sprint**: 1 (Week 1–2)
**Effort**: 1h
**Depends on**: None (first in migration chain)

**Description**: Add `required_credentials JSONB NOT NULL DEFAULT '[]'`, `auth_mode VARCHAR(32) NOT NULL DEFAULT 'none'`, and `plan_required VARCHAR(32) NULL` to the `agent_templates` table. Add two CHECK constraints. The 4 existing seed templates (HR, IT Helpdesk, Procurement, Onboarding) are RAG-only — empty credentials and `auth_mode='none'` are semantically correct defaults.

**Files to create**:

- `src/backend/alembic/versions/v045_agent_templates_required_credentials.py`

**Files to modify**:

- `src/backend/app/modules/agents/routes.py` — `CreateAgentTemplateRequest` and `UpdateAgentTemplateRequest` Pydantic schemas (add 3 fields with validators), `_TEMPLATE_UPDATE_ALLOWLIST`, `_create_agent_template_db()` INSERT, GET response

**Acceptance criteria**:

- [ ] Migration `v045` runs cleanly with `alembic upgrade head` and rolls back cleanly with `alembic downgrade -1`
- [ ] `revision = "045"`, `down_revision = "044"` in migration file
- [ ] `agent_templates` has `required_credentials JSONB NOT NULL DEFAULT '[]'`
- [ ] `agent_templates` has `auth_mode VARCHAR(32) NOT NULL DEFAULT 'none'`
- [ ] `agent_templates` has `plan_required VARCHAR(32) NULL`
- [ ] CHECK constraint `ck_agent_templates_auth_mode` enforces `IN ('none', 'tenant_credentials', 'platform_credentials')`
- [ ] CHECK constraint `ck_agent_templates_plan_required` enforces `IS NULL OR IN ('starter', 'professional', 'enterprise')`
- [ ] `server_default="'[]'"` fills all 4 existing seed templates automatically at migration time
- [ ] All 4 seed templates have `auth_mode='none'`, `required_credentials=[]`, `plan_required=null` after migration
- [ ] `POST /api/v1/platform/agent-templates` with `auth_mode="invalid"` returns 422
- [ ] `GET /api/v1/agents/templates` returns `auth_mode`, `plan_required`, `required_credentials` for all templates
- [ ] `pytest tests/unit/test_agent_templates.py -k "test_template_create_with_auth_mode"` passes
- [ ] `_TEMPLATE_UPDATE_ALLOWLIST` in `agents/routes.py` includes `"required_credentials"`, `"auth_mode"`, `"plan_required"` — verified by unit test that PATCHes each field and confirms persistence
- [ ] Seed template INSERT statements in `scripts/seed_templates.py` (or equivalent) include explicit `auth_mode='none'`, `required_credentials='[]'`, `plan_required=NULL` — not relying on server_default only
- [ ] Fresh install test: after running seeder on empty DB, all 4 templates have correct default values

**Dependencies**: None

---

### ATA-002: Access Control Population on All Three Deploy Paths

**Status**: [x] COMPLETE
**Priority**: P0 — CRITICAL, closes Security Blindness gap
**Sprint**: 1 (Week 1–2)
**Effort**: 3h
**Depends on**: None (independent of ATA-001 schema, operates on existing tables)

**Description**: Add `_ACCESS_CONTROL_MAP` constant at module level in `routes.py`, then INSERT into `agent_access_control` immediately after the `agent_cards` INSERT in all three deploy paths: `deploy_agent_template_db()`, `deploy_from_library_db()`, and `create_agent_studio_db()`. The INSERT must happen in the same transaction as the agent card creation.

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Acceptance criteria**:

- [ ] `_ACCESS_CONTROL_MAP` constant defined at module level: `{"workspace": "workspace_wide", "role": "role_restricted", "user": "user_specific"}`
- [ ] `deploy_agent_template_db()` INSERTs into `agent_access_control` after `agent_cards` INSERT, same transaction
- [ ] `deploy_from_library_db()` INSERTs into `agent_access_control` after `agent_cards` INSERT, same transaction
- [ ] `create_agent_studio_db()` INSERTs into `agent_access_control` after `agent_cards` INSERT, same transaction
- [ ] All three paths use `ON CONFLICT (agent_id, tenant_id) DO NOTHING` for idempotency
- [ ] `list(body.allowed_roles or [])` and `list(body.allowed_user_ids or [])` coercions applied in all INSERT calls (asyncpg VARCHAR[] safety)
- [ ] Deploy with default `access_control=None`: `SELECT * FROM agent_access_control WHERE agent_id = :new_id` returns exactly one row with `visibility_mode = 'workspace_wide'`
- [ ] No `logger.warning("agent_deploy_config_not_persisted", ...)` call exists anywhere in routes.py after this change
- [ ] `pytest tests/integration/test_agent_deploy_access_control.py -k "test_access_control_populated_on_deploy"` passes
- [ ] Verify `DeployFromTemplateRequest` (and equivalent request body models for all 3 deploy paths) includes: `access_control: Optional[str]`, `allowed_roles: Optional[List[str]]`, `allowed_user_ids: Optional[List[UUID]]`
- [ ] If missing, add these fields to the Pydantic model as part of this todo item

**Notes**: Scope — `required_credentials`, `auth_mode`, `plan_required` are template-level concepts. Custom agents created via `create_agent_studio_db()` (without a template) do NOT support these fields in Phase A. Template-less agents always have `auth_mode='none'` and `required_credentials=[]` implicitly. If custom agents need credential support, that is a separate future todo.

**Dependencies**: None (independent of ATA-001)

---

### ATA-003: 422 Gate — Remove Silent Discard (RULE A2A-03)

**Status**: [x] COMPLETE
**Priority**: P0 — CRITICAL, encodes RULE A2A-03
**Sprint**: 1 (Week 1–2)
**Effort**: 30m
**Depends on**: ATA-002 (gate logic is interim behavior until KB enforcement is live)

**Description**: Remove the warning-and-discard comment block at lines 639–651 of `routes.py`. Replace with a 422 gate: any deploy request where `access_control != 'workspace'` OR `kb_ids` is non-empty returns HTTP 422 with a specific message. This is the interim behavior until Phase A Item ATA-007/ATA-008 confirm KB binding enforcement is live. The RULE A2A-03 docstring must be added to `deploy_agent_template_db()`.

**Note**: This gate covers `access_control` and `kb_ids` fields only. The `platform_credentials` interim 422 is handled separately in ATA-025.

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Acceptance criteria**:

- [ ] Lines 639–651 (warning-and-discard block) are removed
- [ ] `deploy_agent_template_db()` has RULE A2A-03 docstring explaining interim 422 behavior
- [ ] Deploy with `access_control='role'` returns HTTP 422 with message containing "enforcement"
- [ ] Deploy with `access_control='workspace'` and `kb_ids=["kb-123"]` returns HTTP 422
- [ ] Deploy with `access_control='workspace'` and no `kb_ids` returns 201 (default path unblocked)
- [ ] The 422 guard uses `body.access_control` (NOT `body.access_mode` — C4 red-team correction)

**Dependencies**: ATA-002

---

### ATA-004: RULE A2A-06 Encoded in `_AGENT_UPDATE_SQL`

**Status**: [x] COMPLETE
**Priority**: P1
**Sprint**: 1 (Week 1–2)
**Effort**: 15m
**Depends on**: None

**Description**: Add the RULE A2A-06 comment block before the `_AGENT_UPDATE_SQL` constant in `agents/routes.py`. This convention encodes that every UPDATE to `agent_cards` MUST include `AND tenant_id = :tenant_id` in the WHERE clause — absence allows cross-tenant access control override.

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Acceptance criteria**:

- [ ] RULE A2A-06 comment block added before `_AGENT_UPDATE_SQL` constant
- [ ] Comment text matches the plan spec verbatim: "CONVENTION: Every UPDATE to agent_cards MUST include tenant_id = :tenant_id..."
- [ ] Verify `PATCH /admin/agents/{id}/access` endpoint in `agent_access_control.py` already has `AND tenant_id = :tenant_id` predicate — document finding in PR

**Dependencies**: None

---

### ATA-005: Refactor VectorSearchService — Extract `_search_single_index` (Sub-task A3.0)

**Status**: [x] COMPLETE
**Priority**: P0 — CRITICAL prerequisite for ATA-006
**Sprint**: 1 (Week 1–2)
**Effort**: 2h
**Depends on**: None (can start Day 1 in parallel with ATA-001)

**Description**: Extract the single-index search body (approximately lines 464–489 of the current `search()` method) into a new private `_search_single_index(self, index_id, query_vector, top_k, query_text, conversation_id, user_id) -> list[SearchResult]` method. The existing public `search()` must continue to work identically — this is a pure refactor, not a behavior change. Correct parameter note: `query_vector: list[float]` — embedding happens before this call; `_search_single_index` does NOT accept a raw `query: str`.

**Files to modify**:

- `src/backend/app/modules/chat/vector_search.py`

**Acceptance criteria**:

- [ ] `_search_single_index()` private method exists with signature `(self, index_id: str, query_vector: list[float], top_k: int, query_text: str, conversation_id: str | None, user_id: str) -> list[SearchResult]`
- [ ] `_search_single_index` docstring notes: "Raises on index not found — caller (the fan-out gather) must handle exceptions"
- [ ] Existing public `search()` calls `_search_single_index` for the primary agent index — same behavior as before
- [ ] All existing vector search tests pass without modification
- [ ] No behavior change verified: run the full chat integration test suite and confirm no regressions

**Dependencies**: None (can start Day 1)

---

### ATA-006: KB Binding Fan-Out in `VectorSearchService.search()`

**Status**: [x] COMPLETE
**Priority**: P0 — CRITICAL, closes KB bindings Security Blindness gap
**Sprint**: 1 (Week 1–2)
**Effort**: 3h
**Depends on**: ATA-005

**Description**: Add `kb_ids: list[str] | None = None` parameter to the public `search()` method. When `kb_ids` is non-empty, fan-out to each KB index in addition to the agent's own index using `asyncio.gather`. Individual index failures must be logged and skipped — never raised. Re-rank merged results by score and return top_k.

**Files to modify**:

- `src/backend/app/modules/chat/vector_search.py`

**Acceptance criteria**:

- [ ] `search()` signature extended: `kb_ids: list[str] | None = None`
- [ ] Agent's own index always included: `f"{tenant_id}-{agent_id}"`
- [ ] KB binding indexes use `kb_id` directly (the integration's `index_id`, not `f"{tenant_id}-{kb_id}"`)
- [ ] `asyncio.gather(*search_tasks, return_exceptions=True)` used for parallel execution
- [ ] Exceptions from individual indexes are logged with `kb_search_index_failed` event and skipped — never raised
- [ ] Merged results sorted by `score` descending, returned `[:top_k]`
- [ ] `kb_ids` entries are de-duplicated against `indexes_to_search` before gather
- [ ] Agent with `kb_ids=["integration-1"]`: queries both agent index and integration-1 index
- [ ] `pytest tests/integration/test_kb_binding_resolution.py` passes (two-agent doc isolation)

**Dependencies**: ATA-005

---

### ATA-007: `_get_agent_prompt()` Returns `kb_ids`

**Status**: [x] COMPLETE
**Priority**: P0 — CRITICAL, wires KB data out of capabilities JSONB
**Sprint**: 1 (Week 1–2)
**Effort**: 1h
**Depends on**: None (can run in parallel with ATA-005)

**Description**: Change the return type of `_get_agent_prompt()` in `prompt_builder.py` from `tuple[str, dict]` to `tuple[str, dict, list[str]]` — the third element is `kb_ids` extracted from `capabilities["kb_ids"]` in the same DB round-trip. Guard against malformed JSONB: if `kb_ids` is not a list, return `[]`.

**Files to modify**:

- `src/backend/app/modules/chat/prompt_builder.py`

**Acceptance criteria**:

- [ ] `_get_agent_prompt()` return type is `tuple[str, dict, list[str]]`
- [ ] `kb_ids = capabilities.get("kb_ids", [])` extracted from the same row fetch
- [ ] Guard: `if not isinstance(kb_ids, list): kb_ids = []`
- [ ] Guard: `[str(k) for k in kb_ids if k]` — coerce to strings, exclude empty/null entries
- [ ] All callers of `_get_agent_prompt()` updated to handle three-element return
- [ ] Unit test: agent with `capabilities={"kb_ids": ["kb-1", "kb-2"]}` returns `kb_ids=["kb-1", "kb-2"]`
- [ ] Unit test: agent with `capabilities={"kb_ids": "not-a-list"}` returns `kb_ids=[]` (malformed JSONB guard)

**Dependencies**: None (can run in parallel with ATA-005)

---

### ATA-008: Orchestrator Stage 4 Wired to Pass `kb_ids`

**Status**: [x] COMPLETE
**Priority**: P0 — CRITICAL, completes KB binding chain
**Sprint**: 1 (Week 1–2)
**Effort**: 1h
**Depends on**: ATA-006, ATA-007

**Description**: In `orchestrator.py`, extract `kb_ids` from the three-element return value of `_get_agent_prompt()` (already called in Stage 3). Forward `kb_ids` to `VectorSearchService.search()` at Stage 4. Once this is deployed and verified in staging, remove the 422 gate from ATA-003 (that gate is the interim behavior until this item is live).

**Files to modify**:

- `src/backend/app/modules/chat/orchestrator.py`

**Acceptance criteria**:

- [ ] `_get_agent_prompt()` called once in Stage 3; return value destructured as `(system_prompt, capabilities, kb_ids)`
- [ ] `kb_ids` forwarded to `VectorSearchService.search(kb_ids=kb_ids)` at Stage 4
- [ ] No second DB call to fetch kb_ids — same round-trip as Stage 3
- [ ] Two-agent KB isolation test: Agent A (kb_ids=["integration-1"]) does not return docs from integration-2
- [ ] Two-agent KB isolation test: Agent B (kb_ids=["integration-2"]) does not return docs from integration-1
- [ ] `pytest tests/integration/test_kb_binding_resolution.py` passes

**Dependencies**: ATA-006, ATA-007
**Post-deploy action**: Remove the 422 gate from ATA-003 once this item is verified in staging. The gate comment in `deploy_agent_template_db()` references the commit that removes it.

---

### ATA-009: `_check_agent_access()` in Chat Orchestrator

**Status**: [x] COMPLETE
**Priority**: P0 — CRITICAL, enforces access restrictions at chat time
**Sprint**: 2 (Week 3)
**Effort**: 3h
**Depends on**: ATA-002 (rows must exist to check)

**Description**: Add `_check_agent_access(agent_id, tenant_id, user_id, user_roles, db)` helper to `orchestrator.py`. Call it before Stage 1 in `stream_response()`. Query `agent_access_control` table (not `agent_cards`). No row → `workspace_wide` (backward compat). Access check runs BEFORE any SSE response headers are sent — return HTTP 403 directly. If headers have already been sent, fall back to SSE error event.

**Files to modify**:

- `src/backend/app/modules/chat/orchestrator.py`

**Acceptance criteria**:

- [ ] `_check_agent_access()` defined with correct signature and returns `bool`
- [ ] Called before any pipeline stage in `stream_response()`
- [ ] `workspace_wide`: always returns `True`
- [ ] `role_restricted`: `bool(set(user_roles) & set(list(row.allowed_roles or [])))` — returns `True` only if intersection is non-empty
- [ ] `user_specific`: `user_id in list(row.allowed_user_ids or [])` — returns `True` only if match
- [ ] No row in `agent_access_control`: returns `True` (workspace_wide backward compat, per v046b backfill)
- [ ] `list(row.allowed_roles or [])` and `list(row.allowed_user_ids or [])` coercions applied (asyncpg VARCHAR[] safety)
- [ ] Access check runs BEFORE any SSE response headers are sent — therefore return HTTP 403 (not SSE error)
- [ ] Verify by checking if `stream_response()` sends response headers before calling `_check_agent_access()`. If headers are sent first, switch to SSE error event: `event: error\ndata: {"code": 403, "message": "You do not have access to this agent."}`
- [ ] Access denied: NO pipeline stages run, no LLM call made
- [ ] If SSE headers already sent when access check runs: emit `event: error\ndata: {"code": 403, "message": "You do not have access to this agent."}`
- [ ] Frontend chat component handles `event: error` with code 403 by showing an inline error in the chat thread, not a page-level error
- [ ] Error message does NOT disclose the user's roles or the agent's access configuration
- [ ] RULE A2A-06 docstring verifies `AND tenant_id = :tenant_id` is in the WHERE clause
- [ ] Unaccessible agent returns HTTP 403 with correct error message (verified by integration test)
- [ ] User with `roles=['analyst']` denied access to `role_restricted` agent requiring `['hr_manager']`
- [ ] User with `roles=['hr_manager']` receives SSE response from same agent

**Dependencies**: ATA-002

---

### ATA-010: End-User Agent List Filtered by Access Control

**Status**: [x] COMPLETE
**Priority**: P1 — prevents enumeration via sidebar listing
**Sprint**: 2 (Week 3)
**Effort**: 2h
**Depends on**: ATA-002, ATA-009

**Description**: Modify `GET /api/v1/agents` (end-user list) to JOIN `agent_access_control` and apply WHERE predicate filtering by the calling user's roles and ID. Users must only see agents they have access to — unrestricted agents must not appear in the sidebar for unauthorized users.

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Acceptance criteria**:

- [ ] `GET /api/v1/agents` query JOINs `agent_access_control`
- [ ] `workspace_wide` agents appear for all users
- [ ] `role_restricted` agent appears only for users whose JWT roles overlap with `allowed_roles`
- [ ] `user_specific` agent appears only for the specific user in `allowed_user_ids`
- [ ] Agent with no `agent_access_control` row (pre-backfill): treated as `workspace_wide`, visible to all
- [ ] `GET /api/v1/agents` for analyst user does NOT include the `hr_manager`-restricted agent
- [ ] `GET /api/v1/agents` response includes `kb_count` (integer), `tool_count` (integer), `has_credentials` (boolean) derived from JOIN — no N+1 queries

**Dependencies**: ATA-002, ATA-009

---

### ATA-011: v046a Migration — GIN Index on `capabilities->kb_ids`

**Status**: [x] COMPLETE
**Priority**: P1 — enables reverse-lookup "which agents reference this KB"
**Sprint**: 2 (Week 3)
**Effort**: 30m
**Depends on**: ATA-001 (migration chain: v045 → v046a)

**Description**: Create GIN index `ix_agent_cards_capabilities_kb_ids` on `agent_cards.capabilities` using `jsonb_path_ops`. Use plain `CREATE INDEX` (without `CONCURRENTLY`) — the table is small, the lock is brief at migration time, and `CONCURRENTLY` cannot run inside an Alembic transaction (H1 red-team finding).

**Files to create**:

- `src/backend/alembic/versions/v046a_gin_index_capabilities_kb_ids.py`

**Acceptance criteria**:

- [ ] `revision = "046a"`, `down_revision = "045"` in migration file
- [ ] `op.create_index("ix_agent_cards_capabilities_kb_ids", "agent_cards", ["capabilities"], postgresql_using="gin", postgresql_ops={"capabilities": "jsonb_path_ops"})`
- [ ] NO `CONCURRENTLY` keyword — plain `CREATE INDEX` only
- [ ] Migration runs cleanly and rolls back cleanly
- [ ] Comment in migration explains Option A (plain) vs Option B (CONCURRENTLY) choice

**Dependencies**: ATA-001

---

### ATA-012: v046b Migration — Access Control Backfill

**Status**: [x] COMPLETE
**Priority**: P0 — required before ATA-009 can correctly handle legacy agents
**Sprint**: 2 (Week 3)
**Effort**: 30m
**Depends on**: ATA-011 (migration chain: v046a → v046b)

**Description**: DML-only migration (no DDL). INSERT `workspace_wide` access control rows for all existing `agent_cards` that have no `agent_access_control` entry. Use explicit `ARRAY[]::VARCHAR[]` and `ARRAY[]::UUID[]` casts — NOT `'{}'` string literals. Do NOT inject a default guardrails object for existing agents — leave the `guardrails` key absent (V1 latency regression lesson: injecting `{"max_response_length": 0}` caused `_has_active_guardrails()` to return `True` for ALL agents, adding 1–2s buffering to every request).

**Files to create**:

- `src/backend/alembic/versions/v046b_agent_access_control_backfill.py`

**Acceptance criteria**:

- [ ] `revision = "046b"`, `down_revision = "046a"` in migration file
- [ ] DML INSERT uses `ARRAY[]::VARCHAR[]` and `ARRAY[]::UUID[]` explicit casts (NOT `'{}'`)
- [ ] Existing agents without `agent_access_control` rows get exactly one `workspace_wide` row
- [ ] Agents that already have an `agent_access_control` row are NOT touched
- [ ] No `capabilities ||= '{"guardrails": ...}'` injection — guardrails key left absent
- [ ] Comment in migration explains V1 latency regression and why guardrail key is left absent
- [ ] `downgrade()` is a no-op (`pass`) with a comment: "Access control rows are safe to leave"
- [ ] Pre-deploy audit query documented in migration comment for Item B2 (max_response_length)
- [ ] Migration runs cleanly on fresh DB (empty tables case handled by LEFT JOIN / WHERE NULL)

**Dependencies**: ATA-011

---

### ATA-056: Update Next.js TypeScript API client types for all new backend fields

**Status**: [x] COMPLETE
**Phase**: A Sprint 2 (deploy alongside ATA-012)

**Files to modify**:

- `src/web/lib/types/agent.ts` (or equivalent type declaration files)

**Dependencies**: ATA-001 (template schema), ATA-002 (deploy paths), ATA-007 (prompt builder), ATA-025 (credentials)

**Acceptance criteria**:

- [ ] `AgentTemplate` interface includes `auth_mode: string`, `required_credentials: CredentialRequirement[]`, `plan_required: string | null`
- [ ] `AgentCard` interface includes `kb_ids: string[]`, `tool_ids: string[]`, `has_credentials: boolean`
- [ ] `DeployFromTemplateRequest` type includes `credentials?: Record<string, string>`, `allowed_roles?: string[]`, `allowed_user_ids?: string[]`
- [ ] SSE event types include `guardrail_triggered` event: `{rule_id: string, action: "block"|"redact"|"flag", user_message: string, agent_id: string}`
- [ ] `WellKnownAgentCard` type for `/.well-known/agent.json` response
- [ ] TypeScript compiles with 0 errors after changes (`npm run typecheck` passes)

**Notes**: Must be updated before any production frontend work begins. Prototype HTML (ATA-037 onward) can proceed without this but production wiring requires it.

---

### ATA-057: Remove 422 gate (installed by ATA-003) after Phase A enforcement live

**Status**: [ ] NOT STARTED
**Phase**: A Sprint 2 — MUST BE DONE in same release as ATA-008 enforcement

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Dependencies**: ATA-006 (KB fan-out), ATA-008 (orchestrator wired), ATA-009 (access control check) — ALL THREE must be deployed to staging and verified before this item starts

**Acceptance criteria**:

- [ ] The 422 guard block (checking `body.access_control not in ("workspace", None) or body.kb_ids`) is deleted
- [ ] Deploy with `access_control='role'` returns 201 (not 422)
- [ ] Deploy with non-empty `kb_ids` returns 201 (not 422)
- [ ] RULE A2A-03 docstring updated: "Enforcement is now live as of commit [hash]. 422 gate removed."
- [ ] `tests/integration/test_agent_deploy_access_control.py` updated to test non-workspace deploy returns 201

**Notes**: This item exists to prevent the 422 gate from being forgotten post-staging. It is intentionally a separate todo to force a human decision that enforcement is verified.

---

### ATA-013: Integration Tests — Deploy + Access Control

**Status**: [x] COMPLETE
**Priority**: P1
**Sprint**: 2 (Week 3)
**Effort**: 3h
**Depends on**: ATA-002, ATA-003, ATA-009, ATA-010, ATA-011, ATA-012

**Description**: Integration tests covering all three deploy paths, the 422 gate, and access control enforcement. Real database, NO MOCKING per testing rules.

**Files to create**:

- `tests/integration/test_agent_deploy_access_control.py`

**Acceptance criteria**:

- [ ] Test: `deploy_agent_template_db()` with `access_control='workspace'` → `agent_access_control` row exists with `visibility_mode='workspace_wide'`
- [ ] Test: `deploy_from_library_db()` with `access_control='workspace'` → `agent_access_control` row exists
- [ ] Test: `create_agent_studio_db()` with `access_control='workspace'` → `agent_access_control` row exists
- [ ] Test: deploy with `access_control='role'` → HTTP 422 with "enforcement" in message
- [ ] Test: deploy with `access_control='workspace'` and `kb_ids=["kb-1"]` → HTTP 422
- [ ] Test: `_check_agent_access()` with `role_restricted` agent and matching role → allow (HTTP 200 SSE)
- [ ] Test: `_check_agent_access()` with `role_restricted` agent and non-matching role → deny (403 SSE)
- [ ] Test: `GET /api/v1/agents` for restricted role user → restricted agent not in response
- [ ] All tests use real database (no mock, no MagicMock)
- [ ] `pytest tests/integration/test_agent_deploy_access_control.py` passes

**Dependencies**: ATA-002, ATA-003, ATA-009, ATA-010, ATA-011, ATA-012

---

### ATA-014: Integration Tests — KB Binding Resolution

**Status**: [x] COMPLETE
**Priority**: P0 — CRITICAL validation of KB isolation
**Sprint**: 2 (Week 3)
**Effort**: 2h
**Depends on**: ATA-006, ATA-007, ATA-008

**Description**: Two-agent document isolation test verifying that KB bindings enforce complete data separation. Real database, NO MOCKING.

**Files to create**:

- `tests/integration/test_kb_binding_resolution.py`

**Acceptance criteria**:

- [ ] Setup: Create Agent A with `kb_ids=["integration-1"]`, Agent B with `kb_ids=["integration-2"]`
- [ ] Setup: Index doc1 under `integration-1`, doc2 under `integration-2`
- [ ] Test: Query Agent A about doc2 content → doc2 does NOT appear in results
- [ ] Test: Query Agent B about doc1 content → doc1 does NOT appear in results
- [ ] Test: Query Agent A about doc1 content → doc1 DOES appear with correct source citation
- [ ] Test: Agent with `kb_ids` referencing non-existent index → logged warning, no 500 error, pipeline continues
- [ ] All tests use real database and real pgvector (no mock)
- [ ] `pytest tests/integration/test_kb_binding_resolution.py` passes

**Dependencies**: ATA-006, ATA-007, ATA-008

---

## Phase B — A2A Compliance (Weeks 4–6)

**Objective**: Platform is discoverable via A2A standard. Guardrail enforcement is live. Credential deploy validation blocks deployments with missing required credentials.

---

### ATA-015: Create `app/modules/discovery/` Package

**Status**: [x] COMPLETE
**Priority**: P1
**Sprint**: 3 (Week 4–5)
**Effort**: 15m
**Depends on**: None (fully independent, can start Day 1 in parallel)

**Description**: Create the `discovery` package by adding an empty `__init__.py`. Structural prerequisite for ATA-016.

**Files to create**:

- `src/backend/app/modules/discovery/__init__.py` (empty)

**Acceptance criteria**:

- [ ] File exists at the correct path
- [ ] File is empty (no imports, no code)
- [ ] `from app.modules.discovery.routes import well_known_router` resolves without error after ATA-016

**Dependencies**: None

---

### ATA-016: `/.well-known/agent.json` Discovery Endpoint

**Status**: [x] COMPLETE
**Priority**: P1 — closes A2A discovery gap (Gap 6)
**Sprint**: 3 (Week 4–5)
**Effort**: 3h
**Depends on**: ATA-015

**Description**: Implement the A2A v0.3 platform-level discovery endpoint at `/.well-known/agent.json`. This endpoint is unauthenticated (A2A protocol spec requirement). It MUST NOT return any of: `system_prompt`, `credentials_vault_path`, `kb_bindings` with index IDs, `access_rules` with role IDs, or `tenant_id`. Returns platform-level AgentCard only. Rate limit: 60 requests/minute per IP using slowapi. Requires `PUBLIC_BASE_URL` env var; return 503 if not set.

**Files to create**:

- `src/backend/app/modules/discovery/routes.py`

**Files to modify**:

- `src/backend/app/main.py` — mount `well_known_router` at root level, BEFORE the `/api/v1` router (A2A spec requires domain root, not `/api/v1/`)
- `src/backend/.env.example` — add `PUBLIC_BASE_URL=https://your-domain.com`

**Acceptance criteria**:

- [ ] `GET /.well-known/agent.json` returns HTTP 200 with `Content-Type: application/json` — no authentication required
- [ ] Response contains: `name`, `description`, `url`, `version`, `provider`, `capabilities`, `authentication`, `defaultInputModes`, `defaultOutputModes`, `endpoints`
- [ ] Response does NOT contain: `system_prompt`, `tenant_id`, `kb_bindings`, `credentials_vault_path`, `access_rules`
- [ ] Endpoint is mounted at `/` root level — NOT under `/api/v1/` prefix
- [ ] Rate limit: 61st request within 60s from same IP returns 429
- [ ] `PUBLIC_BASE_URL` not set → 503 response body is JSON: `{"error": "discovery_not_configured", "detail": "PUBLIC_BASE_URL environment variable is not set"}` with `Content-Type: application/json`
- [ ] Module-level docstring lists all fields that MUST NOT be returned (security contract)
- [ ] RULE A2A-04 docstring reference in `a2a_routing.py` — verify `_validate_ssrf_safe_url()` exists there
- [ ] `pytest tests/integration/test_a2a_discovery.py` passes

**Dependencies**: ATA-015

---

### ATA-017: Integration Tests — A2A Discovery

**Status**: [x] COMPLETE
**Priority**: P1
**Sprint**: 3 (Week 4–5)
**Effort**: 2h
**Depends on**: ATA-016

**Description**: Integration tests covering schema validation, field exclusion, rate limiting, and missing env var handling.

**Files to create**:

- `tests/integration/test_a2a_discovery.py`

**Acceptance criteria**:

- [ ] Test: `GET /.well-known/agent.json` → 200, `Content-Type: application/json`, no auth required
- [ ] Test: Response contains required A2A fields (`name`, `capabilities`, `authentication`, `endpoints`)
- [ ] Test: Response does NOT contain `tenant_id`, `system_prompt`, `kb_bindings`, `credentials_vault_path`
- [ ] Test: 61st request from same IP within 60s → 429
- [ ] Test: `PUBLIC_BASE_URL` unset → 503
- [ ] A2A v0.3 AgentCard schema validation passes against the response
- [ ] All tests use real HTTP (no mock transport)

**Dependencies**: ATA-016

---

### ATA-018: Create `app/modules/chat/guardrails.py` — `OutputGuardrailChecker`

**Status**: [x] COMPLETE
**Priority**: P0 — CRITICAL, closes guardrail Security Blindness gap
**Sprint**: 3 (Week 4–5)
**Effort**: 4h
**Depends on**: None (independent module creation)

**Description**: Create `OutputGuardrailChecker` with `FilterResult` and `GuardrailRule` dataclasses. The `check()` method MUST be `async` from day one (forward compat for future semantic_check rules). Fail-closed: any exception in `check()` returns a canned error, never the unfiltered response. RULE A2A-01 and RULE A2A-02 encoded in class docstring. `_has_active_guardrails()` helper guards against zero-value dicts injected by migration artifacts.

**Files to create**:

- `src/backend/app/modules/chat/guardrails.py`

**Acceptance criteria**:

- [ ] `FilterResult` dataclass: `passed: bool`, `rule_id: Optional[str]`, `reason: Optional[str]`, `action: str` (pass/block/redact/warn), `filtered_text: Optional[str]`, `violation_metadata: Optional[dict]`
- [ ] `GuardrailRule` dataclass: `rule_id`, `rule_type`, `patterns: List[str]`, `on_violation`, `user_message`, `replacement`
- [ ] `OutputGuardrailChecker.__init__(agent_capabilities: dict, retrieval_confidence: float = 1.0)`
- [ ] `async def check(response_text: str) -> FilterResult` — async signature (not sync)
- [ ] `check()` handles: confidence_threshold check, max_response_length truncation at word boundary, keyword_block pattern matching
- [ ] `check()` handles `redact` action with `rule.replacement` substitution
- [ ] Fail-closed: any exception in `check()` returns `FilterResult(action="block", filtered_text=_CANNED_BLOCK_RESPONSE)`
- [ ] `_has_active_guardrails(guardrails: dict) -> bool` function defined in module — checks `blocked_topics`, `rules`, `confidence_threshold > 0`, `max_response_length > 0`
- [ ] `_has_active_guardrails({})` → `False`
- [ ] `_has_active_guardrails({"max_response_length": 0})` → `False` (zero value = inactive)
- [ ] `_has_active_guardrails({"blocked_topics": ["investment advice"]})` → `True`
- [ ] `TODO-SEMANTIC-CHECK` comment in `__init__` documenting the deferred Bloomberg requirement
- [ ] RULE A2A-01 docstring in class header
- [ ] RULE A2A-02 docstring in class header

**Dependencies**: None

---

### ATA-019: Wire OutputGuardrailChecker into Orchestrator as Stage 7b

**Status**: [x] COMPLETE
**Priority**: P0 — CRITICAL, closes guardrail enforcement gap
**Sprint**: 3 (Week 4–5)
**Effort**: 4h
**Depends on**: ATA-018

**Description**: Wire Stage 7b into `ChatOrchestrationService`. At Stage 3, determine `guardrail_enabled = _has_active_guardrails(capabilities.get("guardrails", {}))`. Stage 7 behavior is conditional: guardrail-enabled agents buffer all LLM chunks; default agents stream live. Stage 7b runs after buffering completes, before Stage 8 (`save_exchange`). On `action=block`: emit guardrail_triggered SSE, yield canned message, call audit log writer, return (do NOT call `save_exchange`). On `action=redact` or `warn`: replace `response_text`, continue to Stage 8. Stage 8 receives `guardrail_violations` metadata.

**Files to modify**:

- `src/backend/app/modules/chat/orchestrator.py`

**Acceptance criteria**:

- [ ] `guardrail_enabled = _has_active_guardrails(capabilities.get("guardrails", {}))` determined at Stage 3
- [ ] Stage 7: guardrail-enabled agents buffer ALL chunks before yielding any tokens to SSE stream
- [ ] Stage 7: default agents (no active guardrails) stream chunks live — no behavior change
- [ ] Stage 7b: `await OutputGuardrailChecker(capabilities, retrieval_confidence).check(response_text)`
- [ ] Stage 7b runs BEFORE `_persistence.save_exchange()` — never after (RULE A2A-01)
- [ ] `action=block`: emit `guardrail_triggered` SSE event, yield canned message SSE, yield `done` SSE, call `_write_guardrail_violation_audit()`, return without calling `save_exchange`
- [ ] `action=redact`: replace `response_text` with `filtered_text`, continue to Stage 8
- [ ] `action=warn` or `action=pass`: continue to Stage 8 unchanged
- [ ] `_write_guardrail_violation_audit()` helper persists `{rule_id, action, reason, violation_metadata}` to `audit_log` table — NOT the original blocked text
- [ ] `save_exchange()` receives `guardrail_violations=[violation_metadata]` if violation occurred, `[]` otherwise
- [ ] Guardrail-enabled agent: NO token delivered to client until full LLM response completes
- [ ] Default agent: live streaming, no buffering, no latency change
- [ ] RULE A2A-01 added to `ChatOrchestrationService` class docstring Stage list
- [ ] SSE event schema constant defined in `guardrails.py`: `GUARDRAIL_TRIGGERED_EVENT = 'guardrail_triggered'`
- [ ] SSE event data format: `{"rule_id": "...", "action": "block|redact|flag", "user_message": "...", "agent_id": "..."}` — documented as a constant in `guardrails.py`
- [ ] Frontend SSE parser handles `guardrail_triggered` event type by displaying the `user_message` field instead of LLM output
- [ ] `pytest tests/integration/test_guardrail_enforcement.py` passes

**Dependencies**: ATA-018

---

### ATA-020: Confidence Threshold Pre-LLM Check (Stage 3.5)

**Status**: [x] COMPLETE
**Priority**: P1 — prevents LLM call when retrieval confidence is too low
**Sprint**: 3 (Week 4–5)
**Effort**: 1h
**Depends on**: ATA-018, ATA-019

**Description**: After Stage 3 (agent prompt fetch) and before Stage 4 (vector search), add a pre-LLM confidence gate. If `capabilities.guardrails.confidence_threshold > 0` AND `retrieval_confidence < threshold`, return a canned low-confidence SSE response without calling the LLM at all (skip Stages 4–7).

**Files to modify**:

- `src/backend/app/modules/chat/orchestrator.py`

**Acceptance criteria**:

- [ ] Check performed AFTER retrieval confidence is known (Stage 4 result) and BEFORE LLM call (Stage 5)
- [ ] `confidence_threshold > 0` required to trigger — threshold of `0.0` means disabled
- [ ] Below threshold: emit canned low-confidence SSE response, no LLM call, no buffering, no Stage 7b needed
- [ ] Below threshold: `save_exchange()` called with the canned response (conversation history preserved)
- [ ] `confidence_threshold = 0.9`, `retrieval_confidence = 0.7` → canned response returned
- [ ] `confidence_threshold = 0.0` → normal pipeline regardless of retrieval confidence

**Dependencies**: ATA-018, ATA-019

---

### ATA-021: Guardrail Violations Audit Trail

**Status**: [x] COMPLETE
**Priority**: P1 — SOC 2 compliance, blocked content must reach audit_log not conversation_messages
**Sprint**: 3 (Week 4–5)
**Effort**: 1h
**Depends on**: ATA-019

**Description**: The `_write_guardrail_violation_audit()` helper (defined in ATA-019) must persist violation metadata to the `audit_log` table. The blocked original response text MUST NOT be stored anywhere. The `save_exchange()` path must store `guardrail_violations` in message metadata JSONB (no schema migration needed — uses existing JSONB column).

**Files to modify**:

- `src/backend/app/modules/chat/orchestrator.py`
- `src/backend/app/modules/chat/guardrails.py` (audit log helper)

**Acceptance criteria**:

- [ ] `action=block`: `audit_log` table receives one row with `action='guardrail_violation'`, `resource_type='agent'`, `resource_id=agent_id`
- [ ] `action=block`: blocked original LLM response text is NOT in `audit_log` or `conversation_messages`
- [ ] `action=block`: `save_exchange()` is NOT called — no conversation history entry
- [ ] `action=redact`: `conversation_messages.metadata` JSONB includes `guardrail_violations: [{rule_id, action, timestamp}]`
- [ ] `action=redact`: blocked text in `guardrail_violations` is violation metadata only — not the original text
- [ ] `SELECT action FROM audit_log WHERE action='guardrail_violation'` returns one row per blocked response
- [ ] `SELECT guardrail_violations FROM conversation_messages WHERE ...` for redacted message shows metadata

**Dependencies**: ATA-019

---

### ATA-022: Template Guardrail Validation at Create/Update

**Status**: [x] COMPLETE
**Priority**: P1 — validates guardrail config structure at write time (RULE A2A-02)
**Sprint**: 4 (Week 6)
**Effort**: 2h
**Depends on**: ATA-018

**Description**: Add `GuardrailsSchema` Pydantic class to `routes.py` for template create/update validation. Validate: `blocked_topics` max 50 items, `confidence_threshold` 0.0–1.0, `max_response_length` 0–10000, `rules` max 20 items each with valid `type` and `action`, and all regex patterns compile cleanly. RULE A2A-02 encoded in `GuardrailsSchema` docstring.

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Acceptance criteria**:

- [ ] `GuardrailsSchema` Pydantic class defined with RULE A2A-02 docstring
- [ ] `_VALID_GUARDRAIL_RULE_TYPES = frozenset({"keyword_block", "citation_required", "max_length", "confidence_threshold", "semantic_check"})`
- [ ] `_VALID_GUARDRAIL_ACTIONS = frozenset({"block", "redact", "warn"})`
- [ ] POST with `guardrails.rules=[{"type": "invalid_type"}]` → 422
- [ ] POST with `guardrails.rules=[{"type": "keyword_block", "patterns": ["[unclosed"]}]` → 422 (invalid regex)
- [ ] POST with valid `keyword_block` rule → 201
- [ ] POST with `confidence_threshold=1.5` → 422 (out of range)
- [ ] POST with `blocked_topics` list of 51 items → 422 (exceeds max)
- [ ] `pytest tests/unit/test_agent_template_validation.py -k "test_guardrail_validation"` passes

**Dependencies**: ATA-018

---

### ATA-023: Integration Tests — Guardrail Enforcement

**Status**: [x] COMPLETE
**Priority**: P0 — validates CRITICAL guardrail behavior
**Sprint**: 4 (Week 6)
**Effort**: 4h
**Depends on**: ATA-018, ATA-019, ATA-020, ATA-021

**Description**: Integration tests covering all guardrail enforcement behaviors. Real database, NO MOCKING.

**Files to create**:

- `tests/integration/test_guardrail_enforcement.py`

**Acceptance criteria**:

- [ ] Test: `blocked_topics=["investment advice"]` → asking "give me investment advice" returns canned block, not LLM output
- [ ] Test: blocked response NOT in `conversation_messages`; violation IS in `audit_log`
- [ ] Test: `action=redact` → redacted text IS in `conversation_messages`; `guardrail_violations` metadata populated
- [ ] Test: guardrail checker raises exception internally → canned error returned, not original LLM output (fail-closed)
- [ ] Test: `confidence_threshold=0.9`, query with low retrieval confidence → canned low-confidence response, no LLM call
- [ ] Test: agent with empty `guardrails` config → chunks stream live (no buffering), latency unchanged
- [ ] Test: agent with non-empty `guardrails` → no token delivered until full LLM response completes
- [ ] Test: `max_response_length` truncation → redacted response with "[Response truncated by policy]" suffix
- [ ] All tests use real database (no mock)
- [ ] `pytest tests/integration/test_guardrail_enforcement.py` passes

**Dependencies**: ATA-018, ATA-019, ATA-020, ATA-021

---

### ATA-024: v047 Migration — `credentials_vault_path` on `agent_cards`

**Status**: [x] COMPLETE
**Priority**: P1
**Sprint**: 4 (Week 6)
**Effort**: 30m
**Depends on**: ATA-012 (migration chain: v046b → v047)

**Description**: Add `credentials_vault_path TEXT NULL` to `agent_cards`. This column stores the vault path prefix for agents deployed with `auth_mode='tenant_credentials'`.

**Files to create**:

- `src/backend/alembic/versions/v047_agent_cards_vault_path.py`

**Acceptance criteria**:

- [ ] `revision = "047"`, `down_revision = "046b"` in migration file
- [ ] `credentials_vault_path TEXT NULL` added to `agent_cards`
- [ ] Migration runs cleanly and rolls back cleanly
- [ ] Note in migration: `platform_credentials auth_mode deferred to Phase C`

**Dependencies**: ATA-012

---

### ATA-025: Credential Deploy Validation Against Vault

**Status**: [x] COMPLETE
**Priority**: P1 — closes Gap 3 and Gap 4 (credential deploy)
**Sprint**: 4 (Week 6)
**Effort**: 4h
**Depends on**: ATA-001, ATA-024

**Description**: Implement `_validate_and_store_credentials()` in the deploy handler. When `auth_mode='tenant_credentials'` and `required_credentials` is non-empty: check that all `required: true` keys are provided in `body.credentials`. If any missing, return 422 naming the missing keys. Store each credential in vault at `{tenant_id}/agents/{agent_id}/{key}`. Store returned vault path prefix in `agent_cards.credentials_vault_path`. If `auth_mode='platform_credentials'`: return 422 with "not yet available" message. Add `credentials: Optional[Dict[str, str]]` field to `DeployFromTemplateRequest`. Modify `get_agent_by_id_db()` to return `has_credentials: bool` — never the vault path.

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Files to reference**:

- `src/backend/app/core/secrets/vault_client.py` — `VaultClient.get_secret()` and `VaultClient.store_secret()`

**Acceptance criteria**:

- [ ] `_validate_and_store_credentials()` defined in `routes.py`
- [ ] `auth_mode='platform_credentials'` → 422 with "not yet available" message
- [ ] `auth_mode='tenant_credentials'` with missing required credential keys → 422 with sorted list of missing keys
- [ ] `auth_mode='tenant_credentials'` with all credentials → 201, vault path stored, `credentials_vault_path` non-null in DB
- [ ] `auth_mode='none'` → returns `None` immediately (no vault interaction)
- [ ] `DeployFromTemplateRequest` has `credentials: Optional[Dict[str, str]]` field
- [ ] `GET /api/v1/admin/agents/{id}` returns `has_credentials: bool` only — vault path NOT in response
- [ ] SSRF note in `_validate_and_store_credentials()` docstring: this function does not make outbound calls; RULE A2A-04 applies only to credential test endpoints (separate step)
- [ ] `pytest tests/integration/test_credential_deploy_validation.py` passes

**Dependencies**: ATA-001, ATA-024

---

### ATA-026: Integration Tests — Credential Deploy Validation

**Status**: [x] COMPLETE
**Priority**: P1
**Sprint**: 4 (Week 6)
**Effort**: 2h
**Depends on**: ATA-025

**Description**: Integration tests covering credential validation at deploy time. Real database, NO MOCKING.

**Files to create**:

- `tests/integration/test_credential_deploy_validation.py`

**Acceptance criteria**:

- [ ] Test: deploy `auth_mode='tenant_credentials'` with `required_credentials=[{key: "api_key", required: true}]` without providing credentials → 422 with "Missing required credentials: ['api_key']"
- [ ] Test: deploy with all required credentials → 201; `SELECT credentials_vault_path FROM agent_cards WHERE id = :id` returns non-null
- [ ] Test: `GET /api/v1/admin/agents/{id}` returns `has_credentials: true` — vault path NOT in response body
- [ ] Test: deploy with `auth_mode='platform_credentials'` → 422 with "not yet available"
- [ ] All tests use real database and real vault client
- [ ] `pytest tests/integration/test_credential_deploy_validation.py` passes

**Dependencies**: ATA-025

---

### ATA-027: RULE A2A-04 Docstring in `a2a_routing.py`

**Status**: [x] COMPLETE
**Priority**: P1 — encodes SSRF check convention
**Sprint**: 3 (Week 4–5)
**Effort**: 15m
**Depends on**: None

**Description**: Verify `_validate_ssrf_safe_url()` exists in `src/backend/app/modules/registry/a2a_routing.py`. If it exists, add the RULE A2A-04 docstring to the function (DNS resolution must happen on every outbound HTTP call, not just registration). If the function does not exist, this is a blocker for ATA-016 and ATA-032 — escalate to user.

**Files to modify**:

- `src/backend/app/modules/registry/a2a_routing.py`

**Acceptance criteria**:

- [ ] `_validate_ssrf_safe_url()` exists in `a2a_routing.py`
- [ ] RULE A2A-04 docstring added to the function explaining DNS rebinding attack vector
- [ ] Docstring includes: "Import from app.modules.registry.a2a_routing — never reimplement inline"
- [ ] Function is referenced from `discovery/routes.py` docstring SECURITY section

**Dependencies**: None

---

### ATA-058: Template deprecation backend — PATCH /platform/agent-templates/{id} with status='Deprecated'

**Status**: [x] COMPLETE
**Priority**: P1
**Sprint**: B Sprint 5 (week 6)
**Effort**: 2h
**Depends on**: ATA-001 (template schema)

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Acceptance criteria**:

- [ ] `PATCH /platform/agent-templates/{id}` with `{"status": "Deprecated"}` succeeds (200)
- [ ] `GET /api/v1/agents/templates` for tenants excludes deprecated templates
- [ ] `POST /api/v1/agents/deploy` with deprecated template ID returns 422 "Template has been deprecated and is no longer available"
- [ ] Existing `agent_cards` deployed from the template are unaffected (continue running)
- [ ] Template can be restored: `PATCH` with `{"status": "Published"}` returns it to catalog
- [ ] `tests/integration/test_template_deprecation.py` covers all transitions

---

## Phase C — Tool Ecosystem (Weeks 7–10)

**Objective**: MCP tool assignments resolved and injected into orchestrator context. Tool catalog integration live. UX authoring surfaces in platform template panel and tenant deploy wizard.

---

### ATA-028: Create `app/modules/chat/tool_resolver.py` — `ToolResolver`

**Status**: [x] COMPLETE
**Priority**: P1 — closes Gap 2 (tool_ids never read at chat time)
**Sprint**: 5 (Week 7–8)
**Effort**: 3h
**Depends on**: ATA-007 (capabilities extracted in same round-trip), ATA-011 (v046a deployed)

**Description**: Implement `ToolResolver` with a single UNION ALL query across `tool_catalog` and `mcp_servers`. One DB round-trip regardless of tool count. Returns `list[ResolvedTool]`. Unknown tool IDs: log warning and skip, never 500. `ResolvedTool` dataclass: `tool_id, name, source, endpoint, auth_type, status`. Note: `tool_catalog` RLS blocks `degraded` tools until v048 deploys (ATA-033) — document this dependency.

**Files to create**:

- `src/backend/app/modules/chat/tool_resolver.py`

**Acceptance criteria**:

- [ ] `ResolvedTool` dataclass: `tool_id, name, source ("tool_catalog"|"mcp_server"), endpoint, auth_type, status`
- [ ] `ToolResolver(db, tenant_id)` class with `async def resolve(tool_ids: List[str]) -> List[ResolvedTool]`
- [ ] Single UNION ALL query: `tool_catalog WHERE id = ANY(:tool_ids)` UNION ALL `mcp_servers WHERE id = ANY(:tool_ids) AND tenant_id = :tenant_id`
- [ ] `tool_catalog` leg: `health_status != 'inactive'` filter
- [ ] `mcp_servers` leg: `status = 'active'` AND `tenant_id = :tenant_id` filter
- [ ] Missing tool IDs: logged with `tool_resolution_missing` event, not raised
- [ ] Module docstring includes SSRF note: this module does not make outbound calls; RULE A2A-04 applies to the tool execution layer only
- [ ] Module docstring notes v048 RLS dependency for degraded tool visibility
- [ ] `pytest tests/integration/test_tool_resolver.py` passes

**Dependencies**: ATA-007

---

### ATA-029: `_get_agent_prompt()` Extended to Return `tool_ids`

**Status**: [x] COMPLETE
**Priority**: P1 — wires tool_ids out of capabilities in same DB round-trip
**Sprint**: 5 (Week 7–8)
**Effort**: 1h
**Depends on**: ATA-007

**Description**: Extend `_get_agent_prompt()` return type from `tuple[str, dict, list[str]]` to `tuple[str, dict, list[str], list[str]]` — the fourth element is `tool_ids` extracted from `capabilities["tool_ids"]` in the same DB round-trip as `kb_ids`.

**Files to modify**:

- `src/backend/app/modules/chat/prompt_builder.py`

**Acceptance criteria**:

- [ ] `_get_agent_prompt()` return type is `tuple[str, dict, list[str], list[str]]` — `(system_prompt, capabilities, kb_ids, tool_ids)`
- [ ] `tool_ids = capabilities.get("tool_ids", [])` extracted from same row fetch
- [ ] Guard: `if not isinstance(tool_ids, list): tool_ids = []`
- [ ] Guard: `[str(t) for t in tool_ids if t]` coercion
- [ ] All callers updated to handle four-element return (orchestrator in ATA-030)

**Dependencies**: ATA-007

---

### ATA-030: Wire `ToolResolver` into Orchestrator and Prompt Builder

**Status**: [x] COMPLETE
**Priority**: P1 — closes tool_ids gap in chat pipeline
**Sprint**: 5 (Week 7–8)
**Effort**: 2h
**Depends on**: ATA-028, ATA-029

**Description**: In `orchestrator.py`, extract `tool_ids` from the four-element return of `_get_agent_prompt()`. Call `ToolResolver.resolve(tool_ids)` before Stage 3 completes. In `prompt_builder.py`, if `resolved_tools` is non-empty, append a tools context block to the system prompt: `"Available tools:\n- {tool.name}: {tool.source}, status={tool.status}"`. This is Layer 1 tool awareness — LLM knows tools are available. Actual MCP invocation deferred to follow-on sprint.

**Files to modify**:

- `src/backend/app/modules/chat/orchestrator.py`
- `src/backend/app/modules/chat/prompt_builder.py`

**Acceptance criteria**:

- [ ] `tool_ids` extracted from four-element `_get_agent_prompt()` return at Stage 3
- [ ] `ToolResolver(db, tenant_id).resolve(tool_ids)` called once per request
- [ ] Resolved tool names and sources appended to system prompt when non-empty
- [ ] Agent with `tool_ids=["tool-abc"]`: resolved tool name appears in system prompt context block
- [ ] Non-existent `tool_id`: logged warning, pipeline continues without error
- [ ] `pytest tests/integration/test_tool_resolver.py` passes (covers orchestrator wiring)

**Dependencies**: ATA-028, ATA-029

---

### ATA-031: Integration Tests — Tool Resolver

**Status**: [x] COMPLETE
**Priority**: P1
**Sprint**: 5 (Week 7–8)
**Effort**: 2h
**Depends on**: ATA-028, ATA-029, ATA-030, ATA-033

**Description**: Integration tests covering tool resolution from both tables, degraded tool visibility, and missing tool handling. Real database, NO MOCKING.

**Files to create**:

- `tests/integration/test_tool_resolver.py`

**Acceptance criteria**:

- [ ] Test: healthy tool in `tool_catalog` → resolved and returned
- [ ] Test: degraded tool in `tool_catalog` → visible after v048 migration (ATA-033), shown with `status=degraded`
- [ ] Test: inactive tool in `tool_catalog` → NOT returned
- [ ] Test: `mcp_server` tool → resolved and returned (requires `status='active'` and matching `tenant_id`)
- [ ] Test: unknown tool ID → warning logged, not included in results, no 500
- [ ] Test: tool names appear in resolved system prompt
- [ ] All tests use real database (no mock)
- [ ] `pytest tests/integration/test_tool_resolver.py` passes

**Dependencies**: ATA-028, ATA-029, ATA-030, ATA-033

---

### ATA-032: Create `app/modules/chat/mcp_resolver.py` — `MCPToolResolver`

**Status**: [x] COMPLETE
**Priority**: P1 — closes MCP caching gap (Gap 4)
**Sprint**: 6 (Week 8)
**Effort**: 3h
**Depends on**: ATA-028

**Description**: Implement Redis-cached MCP server configuration resolver. Cache key: `mingai:{tenant_id}:mcp_tool:{tool_id}`, TTL: 300s. Cache miss: query `mcp_servers` table, cache result (including `None` for missing tools). Cache hit: return cached dict. Uses `build_redis_key()` from `app.core.redis_client`. SSRF check note: this module does not make outbound calls — RULE A2A-04 applies to the tool execution layer.

**Files to create**:

- `src/backend/app/modules/chat/mcp_resolver.py`

**Acceptance criteria**:

- [ ] `get_mcp_tool_config(tool_id, tenant_id, redis, db) -> Optional[dict]` function
- [ ] Cache key: `build_redis_key(tenant_id, "mcp_tool", tool_id)` — uses established namespace convention
- [ ] Cache TTL: 300 seconds
- [ ] Cache miss: DB query, result written to cache with `setex(cache_key, 300, json.dumps(config))`
- [ ] Cache miss for non-existent tool: `json.dumps(None)` cached (prevents repeated DB queries)
- [ ] Cache hit: return `json.loads(cached)` without DB query
- [ ] `invalidate_mcp_tool_cache(tenant_id, tool_id, redis)` function uses `redis.delete()` (immediate, not expire)
- [ ] Module docstring references Redis key convention from doc 51

**Dependencies**: ATA-028

---

### ATA-033: Cache Invalidation on MCP Server CRUD

**Status**: [x] COMPLETE
**Priority**: P1 — prevents stale cache after admin action
**Sprint**: 6 (Week 8)
**Effort**: 1h
**Depends on**: ATA-032

**Description**: Add `invalidate_mcp_tool_cache()` calls to `mcp_servers.py` admin endpoints: after `POST` (create), after `DELETE`, and after `PATCH .../status` toggle. Each call happens after DB commit.

**Files to modify**:

- `src/backend/app/modules/admin/mcp_servers.py`

**Acceptance criteria**:

- [ ] `POST /admin/mcp-servers` → `invalidate_mcp_tool_cache(tenant_id, new_id, redis)` called after commit
- [ ] `DELETE /admin/mcp-servers/{id}` → `invalidate_mcp_tool_cache(tenant_id, tool_id, redis)` called after commit
- [ ] `PATCH /admin/mcp-servers/{id}/status` → `invalidate_mcp_tool_cache(tenant_id, tool_id, redis)` called after commit
- [ ] Create MCP server, then immediately `get_mcp_tool_config()` → DB miss (newly cached after create)
- [ ] Delete MCP server, then immediately `get_mcp_tool_config()` → returns `None` (cache invalidated)

**Dependencies**: ATA-032

---

### ATA-034: Integration Tests — MCP Resolver

**Status**: [x] COMPLETE
**Priority**: P1
**Sprint**: 6 (Week 8)
**Effort**: 2h
**Depends on**: ATA-032, ATA-033

**Description**: Integration tests covering cache hit/miss, write-back, invalidation, and key format. Real database and real Redis, NO MOCKING.

**Files to create**:

- `tests/integration/test_mcp_resolver.py`

**Acceptance criteria**:

- [ ] Test: first `get_mcp_tool_config()` call → cache miss (DB queried), config returned
- [ ] Test: second call within 300s → cache hit (no DB query)
- [ ] Test: `invalidate_mcp_tool_cache()` called → next request hits DB
- [ ] Test: delete MCP server → `get_mcp_tool_config()` returns `None` immediately
- [ ] Test: Redis key format verified: `mingai:{tenant_id}:mcp_tool:{tool_id}` (use `redis.keys("mingai:*")` pattern)
- [ ] All tests use real Redis and real DB (no mock)
- [ ] `pytest tests/integration/test_mcp_resolver.py` passes

**Dependencies**: ATA-032, ATA-033

---

### ATA-035: v048 Migration — Tool Catalog RLS Update

**Status**: [x] COMPLETE
**Priority**: P1 — required for ToolResolver to surface degraded tools
**Sprint**: 5 (Week 7–8)
**Effort**: 30m
**Depends on**: ATA-024 (migration chain: v047 → v048)

**Description**: Update the RLS policy on `tool_catalog` to allow tenant `SELECT` for `health_status IN ('healthy', 'degraded')`. Currently only `health_status = 'healthy'` tools are visible to tenant sessions. Without this change, degraded tools are silently invisible to `ToolResolver`, providing no graceful degradation signal to the LLM or user.

**Files to create**:

- `src/backend/alembic/versions/v048_tool_catalog_rls_degraded.py`

**Acceptance criteria**:

- [ ] `revision = "048"`, `down_revision = "047"` in migration file
- [ ] RLS policy updated: `health_status IN ('healthy', 'degraded')` for tenant session SELECT
- [ ] `inactive` tools remain invisible to tenant sessions
- [ ] Migration runs cleanly and rolls back cleanly
- [ ] After migration: `ToolResolver.resolve()` returns degraded tools (not just healthy)

**Dependencies**: ATA-024

---

### ATA-036: Credential Health Check Scheduled Job

**Status**: [x] COMPLETE
**Priority**: P1 — closes Gap 8 (credential health monitoring)
**Sprint**: 7 (Week 9)
**Effort**: 4h
**Depends on**: ATA-025 (credentials_vault_path must exist on agent_cards)

**Description**: Create `run_daily_credential_health_check()` function in a new `credential_health.py` module. Must acquire `DistributedJobLock(f"cred_health:{tenant_id}", ttl_seconds=86000)` before executing (RULE A2A-05). Check each agent_card with non-null `credentials_vault_path` for vault accessibility. Emit admin notification if any credential is unreachable or expired. Register as daily job in `jobs.py`.

**Files to create**:

- `src/backend/app/modules/platform/credential_health.py`

**Files to modify**:

- `src/backend/app/core/scheduler/jobs.py`

**Acceptance criteria**:

- [ ] `run_daily_credential_health_check()` function defined in `credential_health.py`
- [ ] RULE A2A-05 encoded in function docstring (verbatim from plan spec)
- [ ] `DistributedJobLock(f"cred_health:{tenant_id}", ttl_seconds=86000)` acquired before any vault check
- [ ] Per-tenant: queries `agent_cards` where `credentials_vault_path IS NOT NULL`
- [ ] For each agent: checks vault accessibility at `credentials_vault_path`
- [ ] Unreachable or expired credential: emits admin notification (via existing notification service)
- [ ] Job registered in `jobs.py` as daily (24h interval)
- [ ] Multi-worker safety: only one worker runs the check per tenant per day (DistributedJobLock ensures this)

**Notes**: Prerequisite — verify `app.core.scheduler.jobs.py` and `DistributedJobLock` class exist before starting. These were created by TODO-13 (distributed job scheduling). If missing, that is a blocker — file a gap against the implementation.

**Dependencies**: ATA-025

---

### ATA-037: Platform Template Authoring UX — Sections 3–6

**Status**: [ ] NOT STARTED
**Priority**: P2 — UX spec closure (doc 16/02 Section 2)
**Sprint**: 8 (Week 9–10)
**Effort**: 6h
**Depends on**: ATA-001 (auth_mode/plan_required fields), ATA-016 (A2A fields)

**Description**: Extend the platform template authoring slide-in panel (`pa-panel-templates` in the prototype) with new Sections 3–6. All new sections follow the Obsidian Intelligence design system: section headings 11px uppercase letter-spacing 0.06em `--text-faint`, card padding 20px, `--border` separator lines, DM Mono for data values, Plus Jakarta Sans for labels.

**Files to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Acceptance criteria**:

- [ ] Section 3 — Authentication: `auth_mode` radio group (None / Tenant Credentials / Platform Credentials). Credential schema table hidden when `auth_mode=none`. Table columns: Key (DM Mono), Label, Type, Sensitive toggle. `[+ Add Credential Field]` inline add button. `type` options: string / url / oauth2.
- [ ] Section 4 — Plan & Access Gate: `plan_required` dropdown (None / Starter / Professional / Enterprise). `capabilities` chip input. `cannot_do` chip input. Chips use outlined neutral style (NOT accent-dim at idle).
- [ ] Section 5 — Tool Assignments: checkbox list from tool catalog. Each row: checkbox, tool name, classification badge (Read-Only = accent dot, Write = `--warn` lightning icon), health status colored per design system. Degraded tools still assignable with `--warn` health label.
- [ ] Section 6 — KB Binding: multi-select from integrations list (integration name, document count in DM Mono).
- [ ] Draft → Published: "Publish" button is primary accent CTA.
- [ ] Published → Deprecated: grayed-out row, no Edit action, only View/Restore.
- [ ] Template catalog table shows `auth_mode` badge (`--warn` for tenant_credentials, `--alert` for platform_credentials) and `plan_required` in DM Mono.
- [ ] All new form controls wire to existing template create/update API fields.

**Dependencies**: ATA-001

---

### ATA-038: Tenant Deploy Wizard — Step 1: Select Template

**Status**: [ ] NOT STARTED
**Priority**: P2 — UX spec closure (doc 16/02 Section 3)
**Sprint**: 8 (Week 9–10)
**Effort**: 2h
**Depends on**: ATA-001

**Description**: Implement the 4-step tenant deploy wizard in the prototype. Step 1: template selection grid. Wizard uses the existing wizard/step modal pattern: max-width 640px, `border-radius: var(--r-lg)`, progress bar top with accent fill, "Step N of M" label, footer [← Back ghost] + [→ Next primary] + × close.

**Files to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Acceptance criteria**:

- [ ] Template selection grid: template card with name, description, `auth_mode` badge, `plan_required` badge
- [ ] Filter by category, search by name
- [ ] Selected template highlighted with accent (`--accent`) border
- [ ] Wizard modal follows established pattern: max-width 640px, progress bar, "Step N of M"
- [ ] Dynamic step count: "Step 1 of N" where N depends on template `auth_mode` and variable presence

**Dependencies**: ATA-001

---

### ATA-039: Tenant Deploy Wizard — Step 2: Credentials (Conditional)

**Status**: [ ] NOT STARTED
**Priority**: P2
**Sprint**: 8 (Week 9–10)
**Effort**: 3h
**Depends on**: ATA-025, ATA-038

**Description**: Credentials step shown only when `auth_mode='tenant_credentials'`. Fields rendered dynamically from `template.required_credentials`. Sensitive fields use `<input type="password">` with show/hide eye toggle. "Test Connection" button with 4 states: idle → testing → passed/failed. Step skipped for `auth_mode=none` and `auth_mode=platform_credentials`.

**Files to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Acceptance criteria**:

- [ ] Step 2 rendered only when `auth_mode='tenant_credentials'`
- [ ] One input per `required_credentials` entry: key slug (DM Mono), label, type-appropriate input
- [ ] `sensitive=true` entries: `type="password"` with show/hide toggle eye icon
- [ ] "Test Connection" button: idle (outlined neutral) → testing (spinner + "Validating...") → passed (accent check + masked account info) → failed (`--alert` X + error + "Retry")
- [ ] `auth_mode=none`: step 2 skipped, wizard shows 2–3 steps total
- [ ] `auth_mode=tenant_credentials`: wizard shows 4 steps
- [ ] Wizard step count and progress bar update when step is skipped

**Dependencies**: ATA-025, ATA-038

---

### ATA-040: Tenant Deploy Wizard — Step 3: KB & Tools

**Status**: [ ] NOT STARTED
**Priority**: P2
**Sprint**: 8 (Week 9–10)
**Effort**: 3h
**Depends on**: ATA-038

**Description**: KB binding and tool assignment step. KB checkbox list. Tool toggles only shown if template has assigned tools. Degraded tool handling matches execute-class vs. read-only classification.

**Files to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Acceptance criteria**:

- [ ] KB checkbox list: KB name (Plus Jakarta Sans 13px/500), source path (11px faint), doc count (DM Mono 11px)
- [ ] Search Mode radio: Parallel / Priority Order
- [ ] Tools subsection shown only if template has `tool_ids`. Toggle per tool, degraded tools show `--warn` health label
- [ ] Empty KB state: "No knowledge bases configured. [Go to Documents]"
- [ ] Execute-class tool Down: block proceeding to next step with inline error
- [ ] Read-Only tool Down: warn banner but allow proceeding

**Dependencies**: ATA-038

---

### ATA-041: Tenant Deploy Wizard — Step 4: Access & Limits

**Status**: [ ] NOT STARTED
**Priority**: P2
**Sprint**: 8 (Week 9–10)
**Effort**: 3h
**Depends on**: ATA-038, ATA-019

**Description**: Final wizard step with "Deploy Agent" CTA. Access control, rate limits, and guardrail summary. `guardrail_triggered` SSE handling on deploy response.

**Files to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Acceptance criteria**:

- [ ] Access control radio: All workspace users / Specific roles (chip input) / Specific users (search)
- [ ] Rate limit inputs (DM Mono), inline error if exceeds plan max
- [ ] Guardrails section (custom agents only): confidence threshold slider, citation mode, max output tokens. For library agents: read-only note "Guardrails are managed by the platform template"
- [ ] Final step CTA changes from "Next →" to "Deploy Agent" (accent primary button)
- [ ] On `guardrail_triggered` SSE event: show canned message instead of raw LLM output
- [ ] Agent card after deploy shows KB count badge, tool count badge (if tools > 0), credential health badge (if `auth_mode != none`)

**Dependencies**: ATA-038, ATA-019

---

### ATA-042: Agent Detail Panel — Post-Deploy Enhanced View

**Status**: [ ] NOT STARTED
**Priority**: P2
**Sprint**: 8 (Week 9–10)
**Effort**: 2h
**Depends on**: ATA-006, ATA-028, ATA-019, ATA-025

**Description**: Extend the deployed agent detail panel (slide-in from right) with sections for KB bindings, tool assignments, guardrail summary, credential status, and A2A metadata.

**Files to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Acceptance criteria**:

- [ ] KB bindings section: resolved names (not raw UUIDs)
- [ ] Tool assignments: tool name + health status badge (`--accent` healthy, `--warn` degraded, `--alert` down)
- [ ] Guardrail summary: "N rules active", last violation timestamp (DM Mono)
- [ ] Credential status: each required credential with ✓ stored / ✗ missing indicator
- [ ] A2A metadata section: agent URL, capabilities flags (streaming, a2a, mcp)
- [ ] "Configure" button → reconfigure panel (ATA-043)

**Dependencies**: ATA-006, ATA-028, ATA-019, ATA-025

---

### ATA-043: Agent Reconfigure Panel — Post-Deploy KB/Tool Changes

**Status**: [ ] NOT STARTED
**Priority**: P2
**Sprint**: 8 (Week 9–10)
**Effort**: 2h
**Depends on**: ATA-042

**Description**: Post-deploy reconfiguration panel for changing KB bindings and tool toggles. Locked fields: system prompt, guardrail rules (locked to template version). KB-required warning when removing last KB.

**Files to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Acceptance criteria**:

- [ ] KB binding: add/remove checkboxes — cannot remove last KB if template `requires_kb=true`
- [ ] Tool toggle: on/off per tool, health status badge
- [ ] System prompt and guardrail rules: read-only with lock icon + note "Managed by platform template"
- [ ] Save → calls `PATCH /api/v1/agents/{agent_id}` with updated `capabilities`

**Dependencies**: ATA-042

---

### ATA-044: Platform Admin — Template Publishing Flow

**Status**: [ ] NOT STARTED
**Priority**: P2
**Sprint**: 8 (Week 9–10)
**Effort**: 2h
**Depends on**: ATA-037

**Description**: Template publishing flow including pre-publish validation checklist, version labeling, and change summary.

**Files to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Acceptance criteria**:

- [ ] Pre-publish checklist: all required fields filled, guardrail config valid, credential schema complete
- [ ] Version label: patch / minor / major radio selection
- [ ] Change summary text field (free text)
- [ ] "Publish" button becomes primary CTA only when checklist passes
- [ ] Published template card shows version badge (DM Mono)

**Dependencies**: ATA-037

---

### ATA-045: Template Version Diff View for Tenants

**Status**: [ ] NOT STARTED
**Priority**: P2
**Sprint**: 8 (Week 9–10)
**Effort**: 2h
**Depends on**: ATA-038

**Description**: "Update available" banner on deployed agent cards when the base template has a new version. Diff view showing changes. Accept / Dismiss actions.

**Files to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Acceptance criteria**:

- [ ] "Update available" banner on deployed agent card when template version incremented
- [ ] Diff view: system prompt changes, guardrail rule additions/removals, tool changes
- [ ] Accept action: re-deploy with new template version
- [ ] Dismiss-for-7-days action: suppresses banner for 7 days
- [ ] Version pinning note: "Next message uses new version" (no conversation-level pinning in Phase C)

**Dependencies**: ATA-038

---

### ATA-046: Guardrail Compliance View — Platform Admin

**Status**: [ ] NOT STARTED
**Priority**: P2
**Sprint**: 8 (Week 9–10)
**Effort**: 3h
**Depends on**: ATA-021

**Description**: Guardrail violations audit table for platform admins. Privacy: no user identity, no conversation content shown.

**Files to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Acceptance criteria**:

- [ ] Violations table: timestamp (DM Mono), rule triggered, action, agent name, conversation_id (DM Mono), tenant name
- [ ] Filters: date range, rule type (keyword_block / confidence / max_length), action (block / redact / warn), tenant
- [ ] Export CSV button: right-aligned in filter bar row, Plus Jakarta Sans 12px/500
- [ ] Privacy: no user ID, no email, no conversation content shown — violation metadata only
- [ ] DM Mono for timestamps and conversation_id; Plus Jakarta Sans for labels

**Dependencies**: ATA-021

---

### ATA-047: Guardrail Compliance View — Tenant Admin

**Status**: [ ] NOT STARTED
**Priority**: P2
**Sprint**: 8 (Week 9–10)
**Effort**: 2h
**Depends on**: ATA-046

**Description**: Tenant-scoped guardrail violations view. Same table layout as platform admin view but scoped to the single tenant (no tenant filter column).

**Files to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Acceptance criteria**:

- [ ] Same table layout as ATA-046 without the tenant filter column
- [ ] Direct CSV export (tenant owns their own data, no key exchange needed)
- [ ] All privacy rules from ATA-046 apply (no user identity, no conversation content)

**Dependencies**: ATA-046

---

## COC Rules Encoding Items

These items encode institutional rules in code. They do not ship new functionality — they prevent convention drift across sessions.

---

### ATA-048: RULE A2A-01 in Orchestrator Class Docstring

**Status**: [x] COMPLETE
**Priority**: P0 — prevents SOC 2 violation via guardrail placement drift
**Sprint**: 3 (Week 4–5) — alongside ATA-019
**Effort**: 15m
**Depends on**: ATA-019

**Description**: Add Stage 7b description to `ChatOrchestrationService` class docstring Stage list. Include CRITICAL note about guardrail placement (before Stage 8, never after).

**Files to modify**:

- `src/backend/app/modules/chat/orchestrator.py`

**Acceptance criteria**:

- [ ] RULE A2A-01 text (verbatim from plan spec) in class docstring Stage list as Stage 7b entry
- [ ] CRITICAL note: "WRONG placement: post-Stage-8 (blocked content already in DB, SOC 2 violation)"
- [ ] CORRECT pipeline sequence: "Stage 7 → Stage 7b (filter) → Stage 8 (persist filtered/canned text)"

**Dependencies**: ATA-019

---

### ATA-049: RULE A2A-02 in GuardrailsSchema Docstring

**Status**: [x] COMPLETE
**Priority**: P0 — prevents false confidence that DB storage = enforcement
**Sprint**: 4 (Week 6) — alongside ATA-022
**Effort**: 10m
**Depends on**: ATA-022

**Description**: RULE A2A-02 text encoded in `GuardrailsSchema` Pydantic class docstring. Also add inline comment at the `create_agent` endpoint.

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Acceptance criteria**:

- [ ] RULE A2A-02 text in `GuardrailsSchema` docstring: "CRITICAL: Storing guardrails in this schema does nothing unless ChatOrchestrationService reads and applies them on every request"
- [ ] Inline comment at create_agent endpoint referencing guardrails.py Stage 7b

**Dependencies**: ATA-022

---

### ATA-050: RULE A2A-03 in `deploy_agent_template_db()` Docstring

**Status**: [x] COMPLETE
**Priority**: P0 — preserves 422 gate rationale for future sessions
**Sprint**: 1 (Week 1–2) — alongside ATA-003
**Effort**: 10m
**Depends on**: ATA-003

**Description**: RULE A2A-03 encoded in `deploy_agent_template_db()` docstring. The comment must include a note about which commit removes the gate (the commit that adds ATA-008).

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Acceptance criteria**:

- [ ] RULE A2A-03 text in docstring: "CRITICAL: Until Phase A access control enforcement is live, the deploy endpoint MUST return HTTP 422 for any request where access_control != 'workspace_wide' OR kb_ids is non-empty"
- [ ] Comment notes: "Check git blame for the commit that removes this guard — that is the moment enforcement is live"

**Dependencies**: ATA-003

---

### ATA-051: RULE A2A-04 in `_validate_ssrf_safe_url()`

**Status**: [x] COMPLETE
**Priority**: P0 — prevents DNS rebinding SSRF
**Sprint**: 3 (Week 4–5) — same as ATA-027
**Effort**: 10m
**Depends on**: ATA-027

**Description**: Covered by ATA-027. Verify the docstring is present and complete. Cross-reference item.

**Files to modify**:

- `src/backend/app/modules/registry/a2a_routing.py`

**Acceptance criteria**:

- [ ] RULE A2A-04 text in `_validate_ssrf_safe_url()` docstring explaining DNS rebinding attack
- [ ] "Import from app.modules.registry.a2a_routing — never reimplement inline" in docstring

**Dependencies**: ATA-027

---

### ATA-052: RULE A2A-05 in `run_daily_credential_health_check()`

**Status**: [x] COMPLETE
**Priority**: P1 — prevents duplicate vault notifications on multi-worker deploy
**Sprint**: 7 (Week 9) — same as ATA-036
**Effort**: 10m
**Depends on**: ATA-036

**Description**: Covered by ATA-036. Cross-reference item to confirm RULE A2A-05 docstring is present.

**Files to modify**:

- `src/backend/app/modules/platform/credential_health.py`

**Acceptance criteria**:

- [ ] RULE A2A-05 text in function docstring: "CONVENTION: All scheduled per-tenant jobs MUST acquire DistributedJobLock(f'cred_health:{tenant_id}', ttl_seconds=86000) before executing"
- [ ] Explanation of duplicate notification risk in multi-worker deployments

**Dependencies**: ATA-036

---

### ATA-053: RULE A2A-06 in `_AGENT_UPDATE_SQL` Comment Block

**Status**: [x] COMPLETE
**Priority**: P0 — prevents cross-tenant RLS bypass via application layer
**Sprint**: 1 (Week 1–2) — same as ATA-004
**Effort**: 10m
**Depends on**: ATA-004

**Description**: Covered by ATA-004. Cross-reference item to confirm RULE A2A-06 comment block is present.

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Acceptance criteria**:

- [ ] RULE A2A-06 comment block before `_AGENT_UPDATE_SQL` constant
- [ ] Text: "CONVENTION: Every UPDATE to agent_cards MUST include tenant_id = :tenant_id in the WHERE clause"
- [ ] Cross-tenant bypass risk documented: "Missing tenant_id on the UPDATE path allows a crafted request to overwrite a different tenant's agent access control configuration"

**Dependencies**: ATA-004

---

### ATA-054: `TODO-SEMANTIC-CHECK` Comment in `OutputGuardrailChecker`

**Status**: [x] COMPLETE
**Priority**: P1 — prevents Bloomberg compliance gap from being forgotten
**Sprint**: 3 (Week 4–5) — same as ATA-018
**Effort**: 5m
**Depends on**: ATA-018

**Description**: Covered by ATA-018. Cross-reference to confirm `TODO-SEMANTIC-CHECK` is present in `OutputGuardrailChecker.__init__`.

**Files to modify**:

- `src/backend/app/modules/chat/guardrails.py`

**Acceptance criteria**:

- [ ] `TODO-SEMANTIC-CHECK` comment in `__init__` or class docstring
- [ ] Comment text: "semantic_check rules (embedding similarity against violation exemplar index) are required for regulated deployments (Bloomberg, CapIQ, Oracle Fusion). keyword_block rules are bypassable via paraphrase. Do not communicate Bloomberg agent as fully compliant until semantic_check is calibrated."

**Dependencies**: ATA-018

---

### ATA-055: Pre-Deploy Audit Query Documented in v046b Migration

**Status**: [x] COMPLETE
**Priority**: P1 — prevents unintended truncation regressions when ATA-019 deploys
**Sprint**: 2 (Week 3) — same as ATA-012
**Effort**: 5m
**Depends on**: ATA-012

**Description**: Covered by ATA-012. Cross-reference to confirm the pre-deploy audit query is documented as a comment in v046b migration file.

**Files to modify**:

- `src/backend/alembic/versions/v046b_agent_access_control_backfill.py`

**Acceptance criteria**:

- [ ] Pre-deploy audit query in migration comment: `SELECT id, capabilities->'guardrails' AS guardrails FROM agent_cards WHERE capabilities->'guardrails' IS NOT NULL AND (capabilities->'guardrails'->>'max_response_length')::int > 0`
- [ ] Comment explains: "Any agent with max_response_length > 0 will start truncating responses after Item B2 deploys. Confirm this is intentional before deploying ATA-019."

**Dependencies**: ATA-012

---

## Tests Required Summary

| Test File                                                | Covers                                                                           | Phase | ATA Items                          |
| -------------------------------------------------------- | -------------------------------------------------------------------------------- | ----- | ---------------------------------- |
| `tests/integration/test_agent_deploy_access_control.py`  | All 3 deploy paths, 422 gate, role-restricted 403, enumeration prevention        | A     | ATA-002, ATA-003, ATA-009, ATA-010 |
| `tests/integration/test_kb_binding_resolution.py`        | Two-agent doc isolation, fan-out, orphaned index handling                        | A     | ATA-006, ATA-007, ATA-008          |
| `tests/integration/test_a2a_discovery.py`                | Schema validation, field exclusion, rate limit, missing env var                  | B     | ATA-016                            |
| `tests/integration/test_guardrail_enforcement.py`        | Blocked topic, confidence threshold, fail-closed, buffering vs. live streaming   | B     | ATA-018, ATA-019, ATA-020, ATA-021 |
| `tests/integration/test_credential_deploy_validation.py` | Missing creds 422, full creds 201, platform_credentials 422, GET field exclusion | B     | ATA-025                            |
| `tests/integration/test_tool_resolver.py`                | Healthy/degraded/inactive tools, missing tool warning, system prompt injection   | C     | ATA-028, ATA-030, ATA-033          |
| `tests/integration/test_mcp_resolver.py`                 | Cache hit/miss/write-back, invalidation, key format                              | C     | ATA-032, ATA-033                   |
| `tests/unit/test_agent_templates.py`                     | Template create with auth_mode, invalid auth_mode 422                            | A     | ATA-001                            |
| `tests/unit/test_agent_template_validation.py`           | Guardrail rule validation, invalid rule type 422, invalid regex 422              | B     | ATA-022                            |

All Tier 2 integration tests MUST use real database and real Redis. NO mocking (per `rules/testing.md`).

---

## Migration Sequence Table

| Migration | File                                           | Tables Affected        | Type                              | Phase | Sprint   | Depends On          |
| --------- | ---------------------------------------------- | ---------------------- | --------------------------------- | ----- | -------- | ------------------- |
| v045      | `v045_agent_templates_required_credentials.py` | `agent_templates`      | ALTER TABLE + 2 CHECK constraints | A     | Sprint 1 | v044 (current head) |
| v046a     | `v046a_gin_index_capabilities_kb_ids.py`       | `agent_cards`          | CREATE INDEX (no CONCURRENTLY)    | A     | Sprint 2 | v045                |
| v046b     | `v046b_agent_access_control_backfill.py`       | `agent_access_control` | DML only — INSERT backfill        | A     | Sprint 2 | v046a               |
| v047      | `v047_agent_cards_vault_path.py`               | `agent_cards`          | ALTER TABLE (1 column)            | B     | Sprint 4 | v046b               |
| v048      | `v048_tool_catalog_rls_degraded.py`            | `tool_catalog`         | RLS policy update                 | C     | Sprint 5 | v047                |

**v046 split rationale**: `CREATE INDEX CONCURRENTLY` cannot run inside an Alembic transaction. v046a contains DDL only; v046b contains DML only. This pattern applies to any future migration combining index creation with data backfill.

**Rollback safety**: All migrations reversible via `downgrade()`. v046b `downgrade()` is a no-op — access control rows are safe to leave.

---

## Dependency Graph

```
ATA-001 (v045 migration) ──────────────────────────────── (independent — first in chain)
ATA-002 (access control INSERT all 3 deploy paths) ─────── (independent of ATA-001)
ATA-003 (422 gate) ────────────────────── depends on ATA-002
ATA-004 (RULE A2A-06 comment) ──────────────────────────── (independent)
ATA-005 (extract _search_single_index) ─────────────────── (independent — Day 1 parallel)
ATA-006 (kb_ids fan-out in search) ────────── depends on ATA-005
ATA-007 (_get_agent_prompt returns kb_ids) ─────────────── (independent — Day 1 parallel)
ATA-008 (orchestrator Stage 4 kb_ids) ─── depends on ATA-006, ATA-007
ATA-009 (_check_agent_access in orchestrator) ── depends on ATA-002
ATA-010 (end-user list filtered) ─────── depends on ATA-002, ATA-009
ATA-011 (v046a GIN index) ────────────── depends on ATA-001 (migration chain)
ATA-012 (v046b backfill) ─────────────── depends on ATA-011
ATA-013 (tests — deploy + access control) ── depends on ATA-002, ATA-003, ATA-009, ATA-010, ATA-011, ATA-012
ATA-014 (tests — KB binding) ─────────── depends on ATA-006, ATA-007, ATA-008

ATA-015 (discovery package) ────────────────────────────── (independent)
ATA-016 (/.well-known/agent.json) ─────── depends on ATA-015
ATA-017 (tests — A2A discovery) ─────── depends on ATA-016
ATA-018 (OutputGuardrailChecker) ───────────────────────── (independent)
ATA-019 (Stage 7b orchestrator wire) ─── depends on ATA-018
ATA-020 (confidence pre-LLM check) ───── depends on ATA-018, ATA-019
ATA-021 (guardrail audit trail) ─────── depends on ATA-019
ATA-022 (template guardrail validation) ── depends on ATA-018
ATA-023 (tests — guardrail enforcement) ── depends on ATA-018, ATA-019, ATA-020, ATA-021
ATA-024 (v047 vault_path migration) ──── depends on ATA-012 (migration chain)
ATA-025 (credential deploy validation) ── depends on ATA-001, ATA-024
ATA-026 (tests — credential deploy) ──── depends on ATA-025
ATA-027 (RULE A2A-04 docstring) ────────────────────────── (independent)

ATA-028 (ToolResolver) ──────────────── depends on ATA-007
ATA-029 (_get_agent_prompt returns tool_ids) ── depends on ATA-007
ATA-030 (orchestrator + prompt_builder tool wiring) ── depends on ATA-028, ATA-029
ATA-031 (tests — tool resolver) ─────── depends on ATA-028, ATA-029, ATA-030, ATA-033
ATA-032 (MCPToolResolver Redis cache) ── depends on ATA-028
ATA-033 (cache invalidation on MCP CRUD) ── depends on ATA-032
ATA-034 (tests — MCP resolver) ─────── depends on ATA-032, ATA-033
ATA-035 (v048 RLS update) ───────────── depends on ATA-024 (migration chain)

ATA-036 (credential health job) ─────── depends on ATA-025
ATA-037 (platform authoring UX) ─────── depends on ATA-001
ATA-038 (deploy wizard step 1) ─────── depends on ATA-001
ATA-039 (deploy wizard step 2 — credentials) ── depends on ATA-025, ATA-038
ATA-040 (deploy wizard step 3 — KB & tools) ── depends on ATA-038
ATA-041 (deploy wizard step 4 — access & limits) ── depends on ATA-038, ATA-019
ATA-042 (agent detail panel enhanced) ── depends on ATA-006, ATA-028, ATA-019, ATA-025
ATA-043 (agent reconfigure panel) ────── depends on ATA-042
ATA-044 (template publish flow) ─────── depends on ATA-037
ATA-045 (template version diff) ─────── depends on ATA-038
ATA-046 (compliance view — platform) ── depends on ATA-021
ATA-047 (compliance view — tenant) ──── depends on ATA-046

COC rules (ATA-048–055): co-located with their parent implementation items
```

**Critical path**: ATA-001 → ATA-002 → ATA-009 → ATA-019 → ATA-022 → ATA-025 → ATA-028 → ATA-032 (sequential main chain). ATA-005, ATA-007, ATA-015, ATA-018 can run in parallel from Day 1.

---

## Phase Success Criteria

### Phase A Complete (end of Week 3)

- [ ] `POST /api/v1/agents/templates` returns 201 with `auth_mode`, `plan_required`, `required_credentials` fields persisted — verified by GET
- [ ] Every agent deploy creates an `agent_access_control` row — verified by `SELECT * FROM agent_access_control WHERE agent_id = :new_id`
- [ ] Deploy with `access_control != 'workspace'` or `kb_ids` non-empty → HTTP 422 — no silent discard
- [ ] Two KB-bound agents query different indexes — HR agent does not surface procurement docs
- [ ] User without required role cannot invoke a role-restricted agent (403 from orchestrator)
- [ ] v045, v046a, v046b migrations run cleanly on fresh DB and roll back cleanly
- [ ] All 4 existing seed templates retain `auth_mode='none'`, `required_credentials=[]` after v045
- [ ] `pytest tests/integration/test_agent_deploy_access_control.py` passes
- [ ] `pytest tests/integration/test_kb_binding_resolution.py` passes

### Phase B Complete (end of Week 6)

- [ ] `GET /.well-known/agent.json` returns HTTP 200 without auth; no `system_prompt`, `tenant_id`, `kb_bindings` in response
- [ ] Agent with `blocked_topics=["investment advice"]` → asking returns canned block message, not LLM output
- [ ] Guardrail `action=block`: message NOT in `conversation_messages`; violation IS in `audit_log`
- [ ] Guardrail `action=redact`: redacted text IS in `conversation_messages`; `guardrail_violations` metadata populated
- [ ] `OutputGuardrailChecker` exception → canned error returned, never original LLM output
- [ ] Agent with empty guardrails: SSE streams live (no buffering), latency unchanged
- [ ] Agent with non-empty guardrails: no token delivered until full LLM response completes
- [ ] Invalid guardrail rule type → 422 with the unrecognized type name
- [ ] Deploy `auth_mode=tenant_credentials` with missing credential → 422
- [ ] Deploy with all required credentials → `credentials_vault_path` set; GET shows `has_credentials=true` not the path
- [ ] Deploy `auth_mode=platform_credentials` → 422 "not yet available"
- [ ] v047 migration runs cleanly
- [ ] `pytest tests/integration/test_a2a_discovery.py` passes
- [ ] `pytest tests/integration/test_guardrail_enforcement.py` passes
- [ ] `pytest tests/integration/test_credential_deploy_validation.py` passes

### Phase C Complete (end of Week 10)

- [ ] Agent with `tool_ids` assigned: resolved tool names appear in system prompt context block
- [ ] Non-existent `tool_id` → warning logged, no 500 error, pipeline continues
- [ ] Degraded tool visible to ToolResolver (v048 RLS deployed)
- [ ] MCP server create → cache populated. Delete → `redis.get(key)` returns `None` immediately
- [ ] Redis key format verified: `mingai:{tenant_id}:mcp_tool:{tool_id}`
- [ ] Platform admin slide-in: can save template with all new fields (auth_mode, required_credentials, plan_required, tool assignments, KB bindings, guardrails)
- [ ] Tenant deploy wizard: 4 steps for `auth_mode=tenant_credentials`, 2–3 steps for `auth_mode=none`
- [ ] Credential test button transitions through all 4 states
- [ ] v048 migration runs cleanly
- [ ] `pytest tests/integration/test_tool_resolver.py` passes
- [ ] `pytest tests/integration/test_mcp_resolver.py` passes

---

## Risk Register

| Risk                                                        | Probability | Impact                                  | Mitigation                                                                                                        |
| ----------------------------------------------------------- | ----------- | --------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| KB fan-out hits non-existent index (orphaned JSONB ref)     | High        | Medium (500 during search)              | `_search_single_index` catches exceptions; never raises (ATA-006)                                                 |
| Guardrail `keyword_block` bypassed via paraphrase           | High        | High (Bloomberg compliance gap)         | `TODO-SEMANTIC-CHECK` comment; do not communicate Bloomberg as compliant (ATA-054)                                |
| Duplicate credential health check on multi-worker deploy    | Medium      | Medium (duplicate vault notifications)  | `DistributedJobLock` per tenant (RULE A2A-05, ATA-036)                                                            |
| Output filter drifts to post-Stage-8 on future refactor     | Low         | Critical (SOC 2 violation)              | RULE A2A-01 encoded in class docstring + `OutputGuardrailChecker` docstring (ATA-048)                             |
| `agent_cards` UPDATE missing `tenant_id` predicate          | Low         | Critical (cross-tenant access override) | RULE A2A-06 comment before `_AGENT_UPDATE_SQL` (ATA-053)                                                          |
| v046a GIN index creation blocks table during migration      | Low         | Low (brief lock, small table)           | Plain `CREATE INDEX` without CONCURRENTLY — acceptable at migration time (ATA-011)                                |
| Agents with non-zero max_response_length truncated after B2 | Medium      | High (unintended behavior change)       | Pre-deploy audit query documented in v046b; `_has_active_guardrails()` guards zero-value dicts (ATA-012, ATA-055) |
| `tool_catalog` degraded tools invisible to ToolResolver     | Medium      | Medium (silent tool drop)               | v048 extends RLS to allow `degraded` status (ATA-035)                                                             |
| A2A discovery endpoint enumerated                           | Low         | Low (platform-level card only)          | Rate limit 60 req/min per IP; no per-agent data exposed (ATA-016)                                                 |

---

## Deferred / Out-of-Scope Items (Phase D+)

| Item          | Description                                          | Gate Condition                                                   | References                    |
| ------------- | ---------------------------------------------------- | ---------------------------------------------------------------- | ----------------------------- |
| ATA-DEFER-001 | Template update push notification backend            | Post-Phase C; requires notification service                      | Gap 7, ATA-045                |
| ATA-DEFER-002 | Conversation-level template version pinning          | Post-Phase C; requires `template_version` on conversations table | ATA-045 UX note, F2 red team  |
| ATA-DEFER-003 | `platform_credentials` auth_mode full implementation | Vault platform credential storage design                         | ATA-025 note                  |
| ATA-DEFER-004 | Blockchain audit trail for HAR                       | 100+ completed transactions gate                                 | HAR-013-017 (todos/deferred/) |

---

**Document Version**: 1.1
**Generated**: 2026-03-21
**Last updated**: 2026-03-21 (red-team findings applied: C1, C2, H-F2, H-F3, H-F4, H-F5, H1, H2, H3, H4, H-F15, M1, M2, M3, F1, L1)
**Source plan**: `workspaces/mingai/02-plans/14-agent-template-a2a-plan.md` v1.1 (red-team validated, 4 CRITICAL + 6 HIGH + 5 MEDIUM findings addressed)
**Next action**: Sprint 1 — ATA-001 (v045 migration) unblocks ATA-002, ATA-009, ATA-025. ATA-005 (extract `_search_single_index`) and ATA-015 (discovery package) can start in parallel from Day 1.
