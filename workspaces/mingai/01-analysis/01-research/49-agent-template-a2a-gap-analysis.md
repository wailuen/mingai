# 49. Agent Template A2A Compliance, KB/RAG Binding, MCP Tool Assignment, and Guardrail Enforcement — Gap Analysis

> **Status**: Failure Point Analysis
> **Date**: 2026-03-21
> **Priority**: P0 — 4 gaps are CRITICAL (data silently dropped or security enforcement missing)
> **Scope**: Agent template deploy pipeline, runtime guardrail enforcement, MCP/tool wiring, A2A discovery
> **Source files examined**: `agents/routes.py`, `platform/routes.py`, `chat/orchestrator.py`, `chat/prompt_builder.py`, `chat/vector_search.py`, `admin/mcp_servers.py`, `alembic/versions/v001`, `v005`, `v020`, `v028`, `v030`, `v036`
> **Architecture references**: `18-a2a-agent-architecture.md`, `25-a2a-guardrail-enforcement.md`, `33-agent-library-studio-architecture.md`, `32-hosted-agent-registry-architecture.md`

---

## Executive Summary

The agent template system has a working deployment pipeline (templates resolve, system prompts substitute, agents insert into `agent_cards`), but **ten gaps exist between the architecture specifications and the running code**. Four are CRITICAL: KB bindings are silently dropped on deploy, tool assignments have no storage, guardrails are stored but never enforced at runtime, and `agent_access_control` is never populated on deploy. The combined effect is that a tenant admin who configures an agent with KB bindings, tools, access restrictions, and guardrails will see a "success" response while none of those configurations actually take effect. Complexity score: **Enterprise (27 points)** — spans schema, business logic, runtime pipeline, and A2A protocol layers.

---

## Gap 1: KB Bindings / kb_ids Silently Dropped on Deploy

### Evidence

**Architecture spec** (`33-agent-library-studio-architecture.md` Section 2.2): Agent instances carry `kb_bindings` — an array of `{index_id, display_name, required_role}` objects. Section 4.3 specifies query-time RBAC enforcement per KB.

**Actual code**: `deploy_agent_template_db()` at `agents/routes.py:287-358` accepts `kb_ids` as a parameter but the INSERT statement does not include `kb_ids` in either the column list or VALUES clause. The `agent_cards` table (v001) has no `kb_ids`, `kb_bindings`, or `kb_mode` column.

For `deploy_from_library_db()`, `kb_ids` are converted to `capabilities` entries (`[{"type": "knowledge_base", "id": kb_id}]`) and stored inside the `capabilities` JSONB column. However, this path does not resolve KBs at search time either.

The log at lines 643–651 explicitly acknowledges this: `"access_control and kb_ids require schema migration before they are enforced"`.

**Vector search** (`vector_search.py`): Search uses `index_id = f"{tenant_id}-{agent_id}"` — searches the agent's own index only. Does NOT resolve `kb_ids` from the agent's configuration to search multiple KB indexes. The `kb_ids` stored in `capabilities` are never read at search time.

### Root Cause

Schema gap (no dedicated column) combined with inconsistent handling across two deploy paths and no runtime resolution of KB bindings during vector search.

### Blast Radius

- **Today**: Tenant admin deploys an agent with KB bindings via `/templates/{id}/deploy` — KBs are silently ignored. Agent responds with zero RAG context for the selected KBs.
- **At scale**: Agents appear to work but never retrieve from the intended knowledge bases. Users get hallucinated answers with no grounding. Trust collapses.

### Failure Mode

**Silent data loss** — API returns 201 Created, KB configuration vanishes.

### Fix Complexity: L (Large)

Requires: (1) Alembic migration for `agent_kb_bindings` join table, (2) update both deploy paths, (3) update `VectorSearchService.search()` to resolve and query multiple KB indexes, (4) RBAC enforcement per-KB at query time per spec Section 4.3.

### Dependencies

Depends on Gap 9 (access control) for per-KB RBAC enforcement.

---

## Gap 2: tool_ids Silently Dropped — No agent_tool_assignments Table

### Evidence

**Architecture spec** (`18-a2a-agent-architecture.md` Section 1): Layer 2 tool catalog (Tavily, Calculator, Weather) is registered by platform admin, enabled per tenant. Agents should be assignable to specific tools.

**Actual code**: `CreateAgentRequest` and `UpdateAgentRequest` accept `tool_ids: List[str]`. These are stuffed into `capabilities` JSONB. There is no `agent_tool_assignments` join table. The orchestrator has no tool dispatch logic. The prompt builder does not inject tool availability into the system prompt.

### Root Cause

Missing join table and missing runtime wiring. Tools are accepted in the API contract but never persisted in a queryable structure and never invoked.

### Blast Radius

- **Today**: Tool assignments are cosmetic — nothing reads or executes them. No tool is ever invoked at runtime.
- **At scale**: Enterprise customers expecting Tavily web search or calculator tools integrated with their agents will find them non-functional.

### Failure Mode

**Silent data loss** (tool assignments) + **missing functionality** (no tool invocation at runtime).

### Fix Complexity: XL (Extra Large)

Requires: (1) `agent_tool_assignments` table, (2) tool dispatch stage in orchestrator (new Stage 2.5 or post-intent routing), (3) MCP client integration for tool execution, (4) tool output injection into LLM context.

### Dependencies

Depends on Gap 10 (MCP server routes) for tool health/availability checks.

---

## Gap 3: agent_templates Missing required_credentials, auth_mode, plan_required Columns

### Evidence

**Architecture spec** (`33-agent-library-studio-architecture.md` Section 2.1): Template data model specifies `plan_required` (starter/professional/enterprise), `auth_mode` (none/tenant_credentials/platform_credentials), and `required_credentials` (array of credential field schemas).

**Actual schema** (`v020_agent_templates.py`): Table has: `id, name, description, category, system_prompt, variable_definitions, guardrails, confidence_threshold, version, status, changelog, created_by, created_at, updated_at`. No `plan_required`, `auth_mode`, or `required_credentials` columns.

### Root Cause

Schema designed before credential architecture was specified. The v020 migration predates the full architecture in doc 33.

### Blast Radius

- **Today**: All templates appear available regardless of tenant plan. No credential schema communicated to tenant admin during adoption. Credential validation cannot run.
- **At scale**: Bloomberg and CapIQ agents cannot enforce credential collection during adoption. Plan-gating is impossible — starter-tier tenants can adopt enterprise-only templates.

### Failure Mode

**Wrong behavior** — no plan-gating, no credential schema enforcement.

### Fix Complexity: M (Medium)

Alembic migration to add 3 columns + update platform routes schema + update tenant-facing catalog API to surface these fields.

### Dependencies

Feeds into Gap 4 (credentials_vault_path wiring).

---

## Gap 4: credentials_vault_path Not Wired on Deploy

### Evidence

**Architecture spec** (`33-agent-library-studio-architecture.md` Section 3.2 step 6): Adoption workflow stores credentials at `{tenant_id}/agents/{instance_id}/{credential_key}` in vault. Agent instance carries `credentials_vault_path`.

**Actual schema**: `agent_cards` has no `credentials_vault_path` column. No vault integration exists in the deploy path. `CredentialTestRunner` class specified but not implemented.

### Root Cause

Vault integration not yet built. The credential architecture is fully designed but zero implementation exists.

### Blast Radius

- **Today**: No external data agent (Bloomberg, CapIQ, Oracle Fusion) can function — no credentials can be stored or injected.
- **At scale**: The entire A2A agent layer for external data sources is non-functional.

### Failure Mode

**Missing functionality** — no error today. Surfaces as 500 or timeout when a deployed Bloomberg agent receives a real query and has no credentials to authenticate.

### Fix Complexity: XL (Extra Large)

Requires: (1) vault service integration, (2) `credentials_vault_path` column on `agent_cards`, (3) credential collection during adoption flow, (4) credential injection at A2A task dispatch time, (5) `CredentialTestRunner` implementation, (6) daily health check job.

### Dependencies

Depends on Gap 3 (required_credentials schema). Feeds into Gap 8 (health check job).

---

## Gap 5: Guardrails Stored in JSONB but Never Enforced at Runtime

### Evidence

**Architecture spec** (`25-a2a-guardrail-enforcement.md`): Three-layer enforcement — (1) positional prompt ordering, (2) output filter (hard enforcement), (3) registration-time audit. Spec explicitly states: "The entire hard enforcement burden rests on Layer 2 (output filter). Removing Layer 2 while keeping Layer 1 would leave the platform with no enforcement at all."

**Actual code**:

- **Layer 1 (prompt positioning)**: `SystemPromptBuilder.build()` assembles layers 0–5 but has NO guardrail block injection. Does not read guardrails from the agent record at all.
- **Layer 2 (output filter)**: `ChatOrchestrationService.stream_response()` streams LLM output directly to client via SSE with zero post-processing filter. No `AgentOutputFilter`, no `check()` call, no violation detection. Flow: LLM → chunk → yield to client. No interception point.
- **Layer 3 (registration audit)**: No `JAILBREAK_PRE_FILTER_PATTERNS` check, no LLM audit of prompt extensions.

Guardrails exist in two formats: `agent_templates.guardrails` JSONB (`[{pattern, action, reason}]`) and `agent_cards.capabilities.guardrails` JSONB (`{blocked_topics, confidence_threshold, max_response_length}`). Neither is read by the orchestrator, prompt builder, or any middleware.

### Root Cause

The runtime pipeline (orchestrator + prompt builder) was built as a RAG pipeline before the guardrail architecture was specified. No integration point was added.

### Blast Radius

- **Today**: A Bloomberg agent could provide investment advice. An Oracle Fusion agent could leak cross-tenant data. The platform has zero compliance enforcement.
- **At scale**: Regulatory violation in financial services. The platform's primary USP ("platform-guaranteed compliance boundaries") is a false claim.

### Failure Mode

**CRITICAL — Wrong behavior with regulatory consequences.** No error, no log, no indication that guardrails are unenforced.

### Fix Complexity: XL (Extra Large)

Requires: (1) `AgentOutputFilter` service with keyword_block, semantic_check, citation_required, scope_check, data_origin rules, (2) integration into orchestrator between LLM stream and SSE yield, (3) prompt builder guardrail block injection (Layer 1), (4) registration-time audit service (Layer 3), (5) violation audit logging, (6) golden test set infrastructure, (7) fail-closed behavior on filter errors.

### Dependencies

Standalone. Must be completed before any A2A agent goes to production. Blocks all regulated-industry deployments.

---

## Gap 6: /.well-known/agent.json Endpoint Not Served

### Evidence

**Architecture spec** (`18-a2a-agent-architecture.md` Section 5): A2A protocol requires `AgentCard` published at `/.well-known/agent.json` for discovery (Google A2A v0.3 standard).

**Actual code**: No FastAPI route serves `/.well-known/agent.json`. The `a2a_routing.py` module handles outbound A2A message routing but there is no corresponding inbound discovery endpoint.

### Root Cause

A2A discovery protocol not yet implemented. Outbound routing was built, inbound discovery was not.

### Blast Radius

- **Today**: No external system can discover mingai agents via the A2A standard.
- **At scale**: Blocks cross-platform agent interoperability and HAR Phase 1 launch.

### Failure Mode

**404 Not Found** when external agents attempt A2A discovery.

### Fix Complexity: S (Small)

Single FastAPI route that reads `agent_cards` and returns JSON AgentCard. Must respect tenant isolation (only expose agents with explicit external visibility).

### Dependencies

None. Can be implemented independently.

---

## Gap 7: Template Update Notifications Not Triggered on Publish

### Evidence

**Architecture spec** (`33-agent-library-studio-architecture.md` Section 3.3): When platform admin publishes a new template version, all active instances must be marked `template_update_available: true` with in-app notification to tenant admins.

**Actual code**: `_patch_agent_template_db()` updates the template row and commits. No post-publish hook, no scan of dependent `agent_cards`, no notification dispatch. The pull-based `check_agent_upgrade_available` endpoint exists — but push notification on publish does not.

### Root Cause

Pull-based upgrade check was implemented; push-based notification trigger was not.

### Blast Radius

- **Today**: Template updates invisible to tenant admins unless they actively check each agent.
- **At scale**: Critical security patches to agent templates won't propagate.

### Failure Mode

**Silent staleness** — agents run on outdated template versions without admin awareness.

### Fix Complexity: M (Medium)

Requires: (1) post-publish hook querying `agent_cards WHERE template_id = :id`, (2) in-app notification insert, (3) optional email/webhook notification.

### Dependencies

None. Can be implemented independently.

---

## Gap 8: Agent Credential Health Check Job Missing

### Evidence

**Architecture spec** (`33-agent-library-studio-architecture.md` Section 8.1): Daily `run_daily_credential_health_check()` job re-tests all active agent credentials, flags failures, notifies tenant admins.

**Actual code**: No scheduled job exists for credential health checks. `CredentialTestRunner` not implemented. `credentials_vault_path` column does not exist (Gap 4).

### Root Cause

Credential management infrastructure (vault, test runner, health job) is entirely unbuilt.

### Blast Radius

- **Today**: No impact (no credentials stored). Becomes CRITICAL the moment Gap 4 is resolved.
- **At scale**: Expired Bloomberg API keys silently break agents with unbounded mean time to detection.

### Failure Mode

**Silent degradation** — agents fail at runtime with opaque API errors after credentials expire.

### Fix Complexity: L (Large)

Requires: (1) `CredentialTestRunner` with per-provider test classes, (2) scheduled job in existing asyncio loop infrastructure, (3) `credential_status` column on `agent_cards`, (4) admin notification.

### Dependencies

Blocked by Gap 4 (credentials_vault_path). Must be implemented after vault integration.

---

## Gap 9: agent_access_control Not Populated on Deploy

### Evidence

**Schema** (`v028_agent_access_control.py`): Table exists — `tenant_id, agent_id, visibility_mode, allowed_roles, allowed_user_ids`. RLS policies in place.

**Actual code**: Neither `deploy_agent_template_db()`, `deploy_from_library_db()`, nor `create_agent_studio_db()` INSERT into `agent_access_control` after creating the `agent_cards` row. `access_control` and `access_mode` values are logged as warnings and discarded.

The chat pipeline takes `agent_id` but performs no access control check before running the RAG pipeline. Any tenant user can invoke any agent by passing the agent_id.

### Root Cause

The access control table was created as schema infrastructure but business logic to populate and enforce it was never wired.

### Blast Radius

- **Today**: All agents are effectively `workspace_wide` regardless of configured access_mode. Role-restricted and user-specific agents are accessible by all users.
- **At scale**: RBAC for agents is a false promise. SOC 2 audit finding. Data leakage through unrestricted KB access.

### Failure Mode

**CRITICAL — Wrong behavior.** No error. System silently grants access to all users for all agents.

### Fix Complexity: M (Medium)

Requires: (1) INSERT into `agent_access_control` in all three deploy/create paths, (2) access check in `ChatOrchestrationService.stream_response()` before running pipeline, (3) access check in end-user agent list endpoint.

### Dependencies

Feeds into Gap 1 (per-KB RBAC enforcement depends on agent-level access control as the first gate).

---

## Gap 10: mcp_servers Table Exists with No Runtime Integration

### Evidence

**Schema** (`v036_mcp_servers.py`): Table — `tenant_id, name, endpoint, auth_type, auth_config, status`.

**Actual code**: `admin/mcp_servers.py` provides tenant-scoped CRUD routes. These routes exist and function. However, there is no integration between registered MCP servers and the agent runtime. No agent references an MCP server. No tool invocation happens.

Additionally, `platform/routes.py` queries `mcp_servers` for platform-wide tools but references columns (`safety_class`, `capabilities`, `plan_tiers`, `health_check_last`) that do not exist in the v036 migration — schema mismatch that will throw 500 errors.

### Root Cause

MCP server table created for two purposes (tenant MCP configs and platform tool catalog) but neither is connected to agent execution pipeline.

### Blast Radius

- **Today**: MCP servers can be registered but serve no runtime purpose. Platform routes may throw 500 errors on column access.
- **At scale**: External tool integrations (Tavily, custom MCP servers) are non-functional.

### Failure Mode

**Missing functionality** + possible **500 errors** on schema column mismatch.

### Fix Complexity: L (Large)

Requires: (1) schema alignment (add missing columns or separate `platform_tools` table), (2) agent-to-tool assignment (Gap 2), (3) MCP client in orchestrator for tool execution.

### Dependencies

Depends on Gap 2 (agent_tool_assignments). Must be co-developed.

---

## Dependency Graph

```
Gap 3 (template credentials schema)
  └──> Gap 4 (credentials_vault_path) ──> Gap 8 (credential health job)

Gap 9 (agent_access_control) ──> Gap 1 (KB bindings + per-KB RBAC)

Gap 10 (MCP server wiring) <──> Gap 2 (tool assignments)

Gap 5 (guardrail enforcement) ──> standalone P0 blocker

Gap 6 (/.well-known/agent.json) ──> standalone, blocks HAR

Gap 7 (template update notifications) ──> standalone
```

Critical path for production: **Gap 5 → Gap 9 → Gap 1** (guardrails, access control, KB bindings).

---

## Summary Table

| #   | Gap                                     | Root Cause                         | Failure Mode                     | Severity | Fix Size | Phase |
| --- | --------------------------------------- | ---------------------------------- | -------------------------------- | -------- | -------- | ----- |
| 5   | Guardrails never enforced at runtime    | Pipeline predates spec             | Wrong behavior — regulatory risk | CRITICAL | XL       | A     |
| 9   | agent_access_control not populated      | Business logic not wired           | Wrong behavior — false RBAC      | CRITICAL | M        | A     |
| 1   | KB bindings dropped on deploy           | Schema gap + no runtime resolution | Silent data loss                 | CRITICAL | L        | A     |
| 2   | tool_ids dropped — no join table        | Missing table + runtime wiring     | Silent data loss + missing fn    | HIGH     | XL       | C     |
| 3   | Templates missing credentials/plan cols | Schema predates arch               | Wrong behavior — no plan-gating  | HIGH     | M        | B     |
| 4   | credentials_vault_path not wired        | Vault integration unbuilt          | Missing functionality            | HIGH     | XL       | B     |
| 8   | Credential health check job missing     | Credential infra unbuilt           | Silent degradation               | HIGH     | L        | B     |
| 10  | mcp_servers orphaned                    | No runtime integration             | Missing fn + possible 500s       | HIGH     | L        | C     |
| 7   | Template update notifications missing   | Push not built                     | Silent staleness                 | MEDIUM   | M        | B     |
| 6   | /.well-known/agent.json missing         | A2A discovery not built            | 404 on discovery                 | MEDIUM   | S        | B     |

## Recommended Implementation Phases

**Phase A — Security & Compliance Blockers (must ship together, blocks production)**

1. Gap 5: Guardrail enforcement (output filter + prompt positioning + registration audit)
2. Gap 9: agent_access_control population and runtime enforcement
3. Gap 1: KB bindings with join table and multi-index search

**Phase B — A2A Compliance** 4. Gap 3: Template credential/plan schema columns 5. Gap 4: Credentials vault integration 6. Gap 6: /.well-known/agent.json endpoint 7. Gap 7: Template update push notifications 8. Gap 8: Credential health check job

**Phase C — Tool Ecosystem** 9. Gap 2: agent_tool_assignments + tool dispatch in orchestrator 10. Gap 10: MCP server runtime integration + schema fix

---

**Document Version**: 1.0
**Last Updated**: 2026-03-21
**Analysis Method**: Code-level evidence against architecture specifications. Every gap validated against actual SQL migrations, route handlers, and runtime service code.
