# 01 -- Agent Studio: Gap and Risk Analysis

> **Status**: Failure Point Analysis
> **Date**: 2026-03-21
> **Analyst**: deep-analyst
> **Complexity Score**: 24 (Complex) -- Governance: 5, Legal: 7, Strategic: 6, Technical: 6
> **Source Documents**: `18-a2a-agent-architecture.md`, `33-agent-library-studio-architecture.md`, `23-agent-template-flows.md`, `49-agent-template-a2a-gap-analysis.md`, `50-agent-template-requirements.md`, `52-agent-template-implementation-approach.md`, `TemplateAuthoringForm.tsx`

---

## Executive Summary

The current `TemplateAuthoringForm.tsx` implements 3 of 7 required configuration dimensions for agent templates (identity, system prompt with variables, and guardrail patterns). The remaining 4 dimensions -- authentication/credential schema, plan gating with capability tags, tool assignments from the platform catalog, and version history with semantic changelog -- are absent from the UI, meaning platform admins cannot author production-ready templates. The gap analysis in doc 49 confirms this is not just a UI problem: 10 backend gaps exist where configured data is silently dropped on deploy (KB bindings, tool assignments, access control) or stored but never enforced at runtime (guardrails). The most impactful redesign scope is the Platform Admin template authoring surface (the form itself), because it is the upstream bottleneck: tenant admins cannot deploy what platform admins cannot author. However, the tenant-facing deployment wizard (Flow 3 in doc 23) also requires implementation to close the loop.

---

## What an Agent IS

An agent in mingai is not a chatbot configuration. It is a **governed runtime entity** with seven distinct configuration layers that determine what it can access, what it can say, who can use it, and what external systems it can call. The conceptual model has three tiers:

### Tier 1: Agent Template (Platform-authored, immutable to tenants)

A template is the platform admin's complete specification of an agent's identity and behavioral boundaries. It defines:

- **Identity**: Name, description, category, icon -- what tenants see in the catalog.
- **System prompt template**: The base behavioral instruction, with `{{variable}}` placeholders that tenants fill at deployment time (e.g., `{{org_name}}`). This is a static string at runtime -- never concatenated with user input.
- **Authentication schema**: Whether the agent needs external API credentials (Bloomberg BSSO, CapIQ API key), what fields to collect from tenants, and which fields are sensitive (masked in UI, encrypted at rest).
- **Plan gate and capabilities**: Which subscription tier unlocks this agent, what it can do (capability tags shown to tenants), and what it explicitly cannot do (informational "cannot_do" tags).
- **Guardrail rules**: Regex-based keyword blocking, redaction, and warning patterns with per-rule violation messages. These are the hard behavioral boundaries that the output filter enforces. Tenants cannot override them.
- **Recommended KB categories**: Hints that sort matching tenant KBs to the top of the binding picker during deployment. Not bindings themselves -- tenants choose their own KBs.
- **Tool assignments**: Which items from the platform Tool Catalog (MCP servers like Tavily, Jira, Confluence) this agent can invoke. Tools are registered platform-wide; templates select a subset.
- **Version history**: Semantic versioning (major/minor/patch) with changelog entries. Breaking changes (prompt, guardrails, tools, credentials) require a version bump and trigger update notifications to all tenant instances.

### Tier 2: Agent Instance (Tenant-configured, deployed)

An instance is created when a tenant admin either adopts a template or builds from scratch in Agent Studio. It adds tenant-specific configuration on top of the template:

- **KB bindings**: Actual tenant document sources (SharePoint indexes, Google Drive collections) that the agent searches at query time. Per-KB RBAC overrides allow restricting specific KBs to specific roles.
- **Tool enablement**: Tenant-level toggle of template-assigned tools (a tenant may disable Confluence Search but keep Jira).
- **Access control**: Who can use this agent -- workspace-wide, role-restricted, or user-list. Enforced at query time via JWT claims.
- **LLM config**: Model selection, temperature, max tokens (within platform bounds).
- **Rate limits**: Per-user-per-day query cap (within plan maximum).
- **Credentials vault**: Actual API keys and tokens stored in tenant-scoped vault paths, injected at runtime via short-lived vault tokens.
- **Variable values**: Tenant-specific fills for template variables (`org_name` = "Acme Capital").

### Tier 3: Runtime Behavior

At query time, the agent is not a static config file. The orchestrator:

1. Resolves the agent instance from cache (Redis, 5-min TTL)
2. Checks user access against `agent_access_control` (JWT claims)
3. Builds the system message from static components: agent prompt + org context + glossary terms + retrieved documents (user query is NEVER in the system message)
4. Searches all bound KBs with per-KB RBAC enforcement (users only see results from KBs they have access to, without knowing other KBs exist)
5. Resolves and invokes assigned tools (MCP clients)
6. Synthesizes via LLM (buffered for guardrail-enabled agents)
7. Runs output guardrail filter (Stage 7.5): blocked responses are replaced with safe fallback messages; redacted responses have offending phrases stripped inline
8. Streams to client via SSE

The critical insight: **an agent is a governed pipeline, not a prompt**. The system prompt is one of seven configuration dimensions. The current UI treats it as the primary dimension, which is why the form feels inadequate.

---

## Current vs. Vision: Gap Table

| Dimension | Product Vision (doc 23, 33) | Current TemplateAuthoringForm.tsx | Gap |
|---|---|---|---|
| 1. Identity | Name, description, category (from expanded list), icon (6-option picker) | Name, description, category (7 hardcoded options: HR/IT/Procurement/Onboarding/Legal/Finance/Custom) | PARTIAL -- icon picker missing, categories hardcoded instead of from API |
| 2. System Prompt + Variables | Monospace textarea, `{{variable}}` detection, inline variable schema editor (key, label, required toggle), 2000-char limit with accent counter, preview mode | Textarea with preview mode, variable highlighting, VariableDefinitions component, character count absent | PARTIAL -- variable schema component exists but no character limit enforcement in UI, no auto-detection of new variables from prompt text |
| 3. Authentication | Radio group (none/tenant_credentials/platform_credentials), dynamic credential schema table (key, label, type, sensitive toggle), conditional visibility | ABSENT | MISSING -- no auth_mode, no required_credentials schema editor |
| 4. Plan Gate + Capabilities | Plan dropdown (none/starter/professional/enterprise), capabilities chip input, cannot_do chip input | ABSENT | MISSING -- no plan_required, no capability tags, no cannot_do tags |
| 5. Guardrails | Blocked topics with expandable pattern config (rule type dropdown, regex textarea, violation action radio, user message field), confidence threshold, citation mode dropdown, max response length | Pattern/action/reason rows (flat, no regex support visible), confidence threshold slider, no citation mode, no max response length | PARTIAL -- guardrail UI exists but is too simple: no rule type selection, no regex validation, no citation_mode, no max_response_length |
| 6. KB Recommendations + Tool Assignments | Recommended KB categories (chip input), tool catalog checkbox list with health status and classification badges | ABSENT | MISSING -- no KB category recommendations, no tool assignment from catalog |
| 7. Version History + Changelog | Version history section in panel, version modal on breaking changes (patch/minor/major radio), required changelog per version, diff view for tenants | VersionHistoryDrawer component exists (separate panel) | PARTIAL -- version history exists as a viewer but the version-bump-on-breaking-change workflow is not implemented |

### Summary Counts

- **MISSING (no implementation)**: 3 dimensions (Authentication, Plan/Capabilities, KB/Tools)
- **PARTIAL (incomplete implementation)**: 4 dimensions (Identity, System Prompt, Guardrails, Version History)
- **COMPLETE**: 0 dimensions

---

## Platform Admin Surface Needs

The Platform Admin authors templates in the slide-in panel accessed from `pa-panel-templates`. The product vision (doc 23, Flow 1) specifies a **single scrollable panel with 7 collapsible sections**, not a multi-step wizard. This is the correct pattern for the Platform Admin authoring experience because:

1. Platform admins are technical operators who need to see all configuration in context
2. Templates are iterated on (draft/edit/publish cycle) -- wizards are for one-time flows
3. The slide-in panel pattern is consistent with all other Platform Admin detail views (Tenants, LLM Profiles)

### What the Platform Admin surface needs

| Component | Current State | Required |
|---|---|---|
| Template list table | TemplateList.tsx exists with name/category/status/version columns | Add filter tabs (All/Published/Draft/Deprecated), add adoption count column, add three-dot menu per row (Duplicate/Export/Deprecate) |
| Authoring panel (slide-in) | TemplateAuthoringForm.tsx -- 3 sections | Expand to 7 collapsible sections per Flow 1 |
| Section 1: Identity | Exists | Add icon picker (6-option grid) |
| Section 2: System Prompt | Exists | Add 2000-char counter, auto-detect `{{variables}}` and sync with schema |
| Section 3: Authentication | ABSENT | Radio group + dynamic credential schema table |
| Section 4: Plan + Capabilities | ABSENT | Plan dropdown + capabilities/cannot_do chip inputs |
| Section 5: KB + Tools | ABSENT | KB category chips + tool catalog checkbox list with health badges |
| Section 6: Guardrails | Exists (simple) | Expand: rule type dropdown, regex validation on blur, violation action radio (block/redact/warn), user message field, citation_mode dropdown, max_response_length input |
| Section 7: Version History | VersionHistoryDrawer exists | Embed inline in panel instead of separate drawer; add version-bump modal on breaking-change save |
| Publish workflow | Not implemented | Pre-publish checklist (inline expansion), version label input, required changelog |
| Deprecation flow | Not implemented | Confirmation dialog with tenant count, status transition |
| Test Harness | TestHarnessPanel.tsx exists | Verify it sends to correct backend endpoint, verify audit logging |
| Lifecycle Actions | LifecycleActions.tsx exists | Verify publish/deprecate/archive actions match Flow 2, 2B, 2C |

---

## Tenant Admin Surface Needs

The Tenant Admin operates in two surfaces:

### Agent Library (adoption of platform templates)

Entry point: `ta-panel-agents` > "+ New Agent" > "From Template". This is a **wizard modal** (not slide-in panel) because deployment is a one-time linear flow with conditional steps.

| Component | Current State | Required |
|---|---|---|
| Template catalog | Not implemented as wizard | 4-step wizard modal: (1) Select Template, (2) KB and Tools, (3) Access and Limits, (4) Credentials [conditional] |
| Plan gating in catalog | Not implemented | Locked card state for plan-gated templates |
| KB binding picker | Not implemented | Checkbox list of tenant KBs with recommended-category sorting |
| Tool enablement | Not implemented | Checkbox list filtered to template-assigned tools with health badges |
| Credential entry | Not implemented | Dynamic form from template credential schema, test connection button |
| Access control | Not implemented | Radio group (workspace_wide/role_restricted/user_list) |
| Rate limit config | Not implemented | Numeric input with plan-max reference |
| Deploy confirmation | Not implemented | Processing overlay, success state with summary |

### Agent Studio (custom agent authoring by tenant admin)

Entry point: `ta-panel-agents` > "+ New Agent" > "Custom Agent". This is a **slide-in panel** (same pattern as Platform Admin authoring, but with tenant-scoped options).

| Component | Current State | Required |
|---|---|---|
| Custom agent panel | Not implemented | Slide-in with: system prompt (full edit), KB bindings (tenant KBs), tool enablement (tenant-enabled tools), access control, LLM config, guardrails (tenant-editable, unlike template agents) |
| Test mode | Not implemented | Test query with sandbox execution, audit logging |
| Publish flow | Not implemented | Draft-to-active transition |

### Agent Management (post-deployment)

| Component | Current State | Required |
|---|---|---|
| Agent card grid | Not implemented in tenant view | Card per deployed agent: icon, name, template version, KB count, tool count, satisfaction bar, action buttons |
| Template update banner | Not implemented | "v1.1.0 available" on agent cards with diff view panel |
| Agent configure slide-in | Not implemented | Edit KB bindings, access rules, rate limits, credentials (not system prompt for template agents) |
| Agent analytics | Not implemented | Usage stats, satisfaction scores, guardrail violation counts |

---

## Critical Failure Points

### CRITICAL Severity

**FP-01: Guardrails are stored but never enforced at runtime.**
The output filter (Stage 7.5) does not exist in the orchestrator pipeline. Any guardrail rule configured by a platform admin -- including regulatory compliance boundaries for financial agents -- has zero runtime effect. A Bloomberg agent could provide investment advice. An Oracle Fusion agent could leak cross-tenant data. This is documented in Gap 5 of doc 49 and is the single highest-risk deficiency in the system.
- Likelihood: Certain (100% -- the code path does not exist)
- Impact: Regulatory violation in financial services deployments, platform liability
- Mitigation: Implement output filter as Stage 7.5 per doc 52 Section 3 before any regulated-industry deployment

**FP-02: Agent access control is not populated or enforced.**
The `agent_access_control` table exists (v028 migration) with RLS policies, but neither the deploy flow nor the create flow inserts rows into it. The chat pipeline performs no access check before running the RAG pipeline. Any tenant user can invoke any agent by passing the agent_id.
- Likelihood: Certain (100% -- no INSERT and no CHECK in code)
- Impact: RBAC is a false promise; SOC 2 audit finding; data leakage through unrestricted KB access
- Mitigation: Wire INSERT in all deploy/create paths; add access check in ChatOrchestrationService before pipeline execution

**FP-03: KB bindings silently dropped on deploy.**
The deploy endpoint accepts `kb_ids` but the INSERT statement omits them. The `agent_cards` table has no `kb_bindings` column. Vector search only queries the agent's own index (`{tenant_id}-{agent_id}`) and never resolves multi-KB bindings. Tenants who configure KB bindings see a success response while the agent runs with zero RAG context from those KBs.
- Likelihood: Certain (100% -- verified in doc 49 Gap 1)
- Impact: Agents hallucinate instead of using grounded knowledge; trust collapses
- Mitigation: Either add relational tables (ADR-050-A in doc 50) or fix JSONB capabilities path (doc 52 Section 1); update VectorSearchService to resolve and query multiple KB indexes

**FP-04: Credential infrastructure entirely absent.**
No vault integration, no `credentials_vault_path` column, no `CredentialTestRunner`, no health check job. The entire A2A agent layer for external data sources (Bloomberg, CapIQ, Oracle Fusion) is non-functional. Any template requiring tenant credentials cannot be operationally deployed.
- Likelihood: Certain for credential-requiring agents
- Impact: 6 of 9 canonical agents (Bloomberg, CapIQ, Oracle Fusion, Teamworks, PitchBook, iLevel) are non-functional
- Mitigation: Phase B delivery per doc 49 dependency graph

### HIGH Severity

**FP-05: Template authoring form missing 4 of 7 sections creates an incomplete template pipeline.**
Platform admins cannot configure auth mode, plan gates, tool assignments, or KB recommendations. Templates created through the current form are missing critical metadata that the tenant deployment wizard (Flow 3) requires to render correctly. The tenant-facing catalog will show incomplete information (no credential requirements, no plan eligibility, no capability tags).
- Likelihood: Certain (current form state verified in `TemplateAuthoringForm.tsx`)
- Impact: Deployment pipeline bottleneck; templates are structurally incomplete
- Mitigation: Redesign the authoring form to 7 collapsible sections per Flow 1

**FP-06: Template version-bump workflow not implemented.**
Breaking changes (system prompt, guardrails, tools, credentials) can be saved to published templates without version bumps. No diff is generated. No tenant notifications are triggered. Tenant instances silently run on stale template versions with no awareness of changes.
- Likelihood: High (any edit to a published template)
- Impact: Silent behavior changes in production agents; trust erosion with tenant admins
- Mitigation: Implement the breaking-change detection and version modal (Flow 2B Step 3-4)

**FP-07: Tool assignments accepted by API but never persisted or executed.**
`tool_ids` are stuffed into the `capabilities` JSONB blob. No `agent_tool_assignments` table exists. The orchestrator has no tool dispatch logic. No MCP client integration exists for tool execution.
- Likelihood: Certain for any agent with tool assignments
- Impact: Tool-dependent agents (Tavily web search, Jira, Confluence) are non-functional
- Mitigation: Phase C delivery per doc 49; requires MCP client integration in orchestrator

**FP-08: Prompt injection risk in tenant-authored system prompts (Agent Studio).**
The `SystemPromptValidator` class is specified in doc 33 Section 4.2 but not implemented. Custom agents authored by tenant admins in Agent Studio have no server-side validation of their system prompts. A malicious or naive tenant admin could craft a prompt that exfiltrates system context, ignores guardrails, or jailbreaks the LLM.
- Likelihood: Medium (requires malicious or careless tenant admin)
- Impact: Guardrail bypass, potential data exfiltration from system context
- Mitigation: Implement `SystemPromptValidator` with the blocked pattern list from doc 33; validate on every save

### MEDIUM Severity

**FP-09: Cognitive overload risk in 7-section authoring panel.**
The product vision specifies all 7 sections expanded by default on create. Platform admins must scroll through authentication schemas, credential field definitions, regex guardrail patterns, tool health statuses, and version history in a single 480px-wide panel. For complex agents (Bloomberg with credentials + 5 guardrail rules + 3 tools), the panel could exceed 3000px of scroll height.
- Likelihood: Medium (depends on template complexity)
- Impact: Configuration errors, missed fields, admin fatigue
- Mitigation: Collapsible sections with section-level validation indicators (green check / red alert in section header). Consider progressive disclosure: expand only Identity and System Prompt on create, collapse optional sections.

**FP-10: Template name uniqueness check is synchronous and global.**
Flow 1 specifies globally unique template names validated on blur. This requires a network round-trip on every blur event from the name field. For platform admins editing frequently, this creates latency and potential for race conditions (two admins creating templates with the same name simultaneously).
- Likelihood: Low (small number of platform admins)
- Impact: Minor UX friction, potential 409 Conflict on save
- Mitigation: Debounce the uniqueness check (300ms after last keystroke, not on blur). Handle 409 Conflict on save with clear error messaging.

**FP-11: Guardrail regex patterns not validated for catastrophic backtracking.**
Flow 1 Step 8 specifies regex validation on blur, but only for syntax validity. A syntactically valid regex can still cause catastrophic backtracking (e.g., `(a+)+$` on certain inputs), which would cause the output filter to hang or timeout at query time.
- Likelihood: Low-Medium (requires specific regex patterns)
- Impact: Agent response timeout for all users when the problematic pattern is evaluated
- Mitigation: Add ReDoS (Regular Expression Denial of Service) detection at save time. Use a regex complexity analyzer or enforce a timeout on pattern evaluation during test.

**FP-12: Concurrent template edit by multiple platform admins.**
Flow 2B edge cases mention 409 Conflict handling, but the current form has no optimistic concurrency control. Two admins editing the same template will silently overwrite each other's changes (last-write-wins).
- Likelihood: Low (small admin team)
- Impact: Lost configuration changes
- Mitigation: Add `updated_at` or ETag-based optimistic concurrency to PATCH endpoints. Show "modified by another admin" error with reload option.

**FP-13: Credential test connection has no timeout boundary.**
Flow 3 Step 4 shows a [Test Connection] button that calls an async endpoint. If the external service (Bloomberg, CapIQ) is slow or unreachable, the test could hang indefinitely, blocking the wizard.
- Likelihood: Medium (external service latency is unpredictable)
- Impact: Wizard appears frozen; tenant admin may close and retry, creating duplicate deploy attempts
- Mitigation: 15-second hard timeout on credential test. After timeout: show "Connection test timed out. The service may be temporarily unavailable. You can save credentials and test later."

---

## Scope Recommendation

### The question: What does "current agent templates are not what we want" mean?

Based on the evidence across all documents, the answer is **(c) Both surfaces need redesign**, but with different priorities and different scopes.

### Priority 1: Platform Admin Template Authoring (the upstream bottleneck)

**Why first**: The Platform Admin authoring form is the source of truth for agent templates. Every downstream surface (tenant catalog, deployment wizard, agent card, runtime pipeline) depends on data authored here. If the form cannot capture authentication mode, plan gates, tool assignments, KB recommendations, or proper guardrail configurations, then no tenant-facing surface can display or enforce them.

**Scope**: Redesign `TemplateAuthoringForm.tsx` from a 3-section flat form to a 7-section collapsible panel per Flow 1. Add the publish workflow (Flow 2), the breaking-change version modal (Flow 2B), and the deprecation flow (Flow 2C). This is the single highest-leverage change.

**Risk if deferred**: Every template created today is structurally incomplete. Fixing this later requires migrating all existing templates to add missing fields.

### Priority 2: Tenant Admin Deployment Wizard (the adoption pipeline)

**Why second**: Once templates are complete, tenants need the 4-step wizard (Flow 3) to deploy them with KB bindings, tool enablement, access control, and credentials. This is the revenue-generating surface -- tenants adopting agents is the core product action.

**Scope**: New component: deployment wizard modal (does not exist today). New component: agent card grid in `ta-panel-agents`. New component: template update diff view (Flow 3B).

**Risk if deferred**: Templates exist in the catalog but tenants have no way to properly deploy them.

### Priority 3: Backend Runtime Enforcement (the trust foundation)

**Why parallel**: FP-01 (guardrails), FP-02 (access control), and FP-03 (KB bindings) are CRITICAL runtime gaps that exist independently of the UI. Even if both surfaces are perfectly redesigned, the runtime will silently drop configurations and fail to enforce guardrails. These backend fixes (Phase A in doc 49) must ship in parallel with or before the UI redesign.

**Scope**: Phase A from doc 49 -- output filter, access control wiring, KB binding resolution.

### Recommended Implementation Order

```
Week 1-2: Backend Phase A (FP-01, FP-02, FP-03) -- Runtime enforcement
Week 2-3: Platform Admin authoring form redesign (FP-05) -- 7 sections
Week 3-4: Platform Admin publish/version/deprecate workflows
Week 4-5: Tenant Admin deployment wizard (Flow 3)
Week 5-6: Tenant Admin agent management (cards, update review, configure)
Week 6+:  Backend Phase B (FP-04, credentials vault) + Phase C (FP-07, tools)
```

Backend Phase A and UI redesign can proceed in parallel since they touch different codepaths (Python orchestrator vs. Next.js components).

---

**Document Version**: 1.0
**Last Updated**: 2026-03-21
**Analysis Method**: Cross-document synthesis of architecture specifications (docs 18, 33), gap analysis (doc 49), requirements breakdown (doc 50), implementation approach (doc 52), user flows (doc 23), and current UI source code (TemplateAuthoringForm.tsx).
