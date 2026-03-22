# 15. Agent Studio Redesign Implementation Plan

> **Status**: Implementation Plan
> **Date**: 2026-03-21
> **Priority**: P1 -- upstream bottleneck for agent adoption pipeline
> **Effort**: 4 phases across ~10 sprints
> **Shipping Order**: Option B -- PA template authoring first, then TA surfaces follow
> **Source Documents**: `17-agent-studio/01-gap-and-risk-analysis.md`, `17-agent-studio/02-ux-design-spec.md`, `17-agent-studio/03-red-team-critique.md`, `33-agent-library-studio-architecture.md`, `52-agent-template-implementation-approach.md`
> **Depends On**: Plan 14 (Agent Template A2A Compliance) for backend runtime enforcement (guardrails Stage 7.5, access control wiring, KB binding resolution)

---

## Overview and Option B Rationale

The agent template authoring form (`TemplateAuthoringForm.tsx`) implements 3 of 7 required configuration dimensions. The 4 missing dimensions (authentication/credentials, plan gating, KB recommendations/tool assignments, version lifecycle) mean platform admins cannot author production-ready templates, which blocks the entire downstream pipeline: tenant admins cannot deploy what platform admins cannot configure. Option B (PA template authoring redesign first) is chosen because the PA authoring surface is the upstream bottleneck -- every tenant-facing surface (catalog, deployment wizard, agent card, chat identity) depends on data authored here. The 4 seed templates exist in the codebase and will be the first templates configurable through the redesigned PA surface. Once PA authoring produces structurally complete templates, Phase 2 delivers the TA deployment wizard to unlock tenant adoption of those templates. Phase 3 adds the TA custom agent builder. Phase 4 closes the feedback loop with template performance metrics.

---

## Phase Table

| Phase | Deliverable | Backend | Frontend | Dependencies | Sprints |
|-------|-------------|---------|----------|--------------|---------|
| 1 | PA Agent Template Studio | v045 migration, `SystemPromptValidator`, template API extensions, version bump logic | `TemplateStudioPanel.tsx` (800px slide-in, 4 tabs, 7 progressive sections) | Plan 14 Phase A (guardrails, access control, KB bindings) should be in flight or complete | 3 |
| 2 | TA Agent Deployment Wizard | KB binding resolution fix, access control INSERT on deploy, credential vault integration, chat agent list filtering | `AgentDeployWizard.tsx` (640px modal, 4-step), `AgentLibraryPage.tsx` catalog cards, chat agent selector identity | Phase 1 complete (templates must be structurally complete) | 3 |
| 3 | TA Custom Agent Studio | Verify studio create/update/test/publish endpoints, `SystemPromptValidator` for tenant prompts | `CustomAgentStudioPanel.tsx` (560px slide-in, 5 sections) | Phase 2 (shared components: KB picker, access control, guardrails editor) | 2 |
| 4 | PA Template Performance Dashboard | `GET /platform/agent-templates/{id}/performance` aggregation endpoint | `TemplatePerformanceTab.tsx` within `TemplateStudioPanel` | Phase 2 (needs deployed instances generating usage data) | 2 |

---

## Phase 1: PA Agent Template Studio

### 1.1 Backend Changes

#### Migration v045: Agent Template Schema Extension

```sql
-- v045_agent_templates_required_credentials.py
ALTER TABLE agent_templates ADD COLUMN required_credentials JSONB NOT NULL DEFAULT '[]';
ALTER TABLE agent_templates ADD COLUMN auth_mode VARCHAR(32) NOT NULL DEFAULT 'none';
ALTER TABLE agent_templates ADD COLUMN plan_required VARCHAR(32);
```

The 4 existing seed templates (HR, IT Helpdesk, Procurement, Onboarding) receive safe defaults automatically: `required_credentials = []`, `auth_mode = 'none'`, `plan_required = NULL`.

#### SystemPromptValidator (CRITICAL -- security boundary)

New module: `app/modules/agents/prompt_validator.py`

- Regex-based blocked pattern detection per doc 33 Section 4.2 (ignore instructions, exfiltrate system context, jailbreak patterns)
- 2000-character limit enforcement
- ReDoS detection: reject regex patterns in guardrail rules that exhibit catastrophic backtracking (enforce evaluation timeout of 50ms per pattern during save)
- Called on every template save (create, update) and every tenant custom agent save (Phase 3)
- Returns `ValidationResult(valid: bool, reason: str | None, blocked_patterns: list[str])`

#### Platform Admin Template API Extensions

Modify `app/modules/agents/routes.py`:

- `POST /platform/agent-templates` -- accept `auth_mode`, `required_credentials`, `plan_required`, `capabilities`, `cannot_do`, `recommended_kb_categories`
- `PUT /platform/agent-templates/{id}` -- accept all above fields, run `SystemPromptValidator` on `system_prompt_template`
- `POST /platform/agent-templates/{id}/publish` -- accept `version_label` and `changelog` (required), increment version, detect breaking changes (prompt, guardrails, credentials, tools changed = minor/major), persist changelog entry
- `GET /platform/agent-templates/{id}/versions` -- return version history with changelog entries
- Add `ETag` header to GET/PUT responses for optimistic concurrency (return 409 if `If-Match` does not match `updated_at`)

#### Version Bump Logic

New module: `app/modules/agents/versioning.py`

- `detect_breaking_changes(old_template, new_template) -> ChangeType` -- compares prompt, guardrails, required_credentials, tool assignments
- `bump_version(current_version: str, change_type: ChangeType) -> str` -- semver increment
- On publish: store changelog entry in `agent_template_versions` (new table or JSONB array on template)

### 1.2 Frontend Changes

#### New Components

| Component | Replaces | Width | Description |
|-----------|----------|-------|-------------|
| `TemplateStudioPanel.tsx` | `TemplateAuthoringForm.tsx` | 800px slide-in | 4-tab panel: Edit, Test, Instances, Version History |
| `SystemPromptEditor.tsx` | inline textarea | -- | DM Mono textarea, live `{{variable}}` detection, chip display, 2000-char counter (warn at 1600, alert at 1800), variable schema table with auto-sync |
| `CredentialSchemaEditor.tsx` | (absent) | -- | Inline editable table: key (auto-generated from label), label, type (string/secret), sensitive toggle. Add/remove rows |
| `GuardrailsEditor.tsx` | simplified pattern list | -- | Rule cards: name, rule type dropdown (keyword_block/regex_match/content_filter), regex textarea with syntax validation on blur, violation action radio (block/redact/warn), user message textarea. Plus confidence slider, citation_mode dropdown, max_response_length input |
| `VersionHistoryTab.tsx` | `VersionHistoryDrawer.tsx` | -- | Vertical timeline layout within panel tab. Version, date, type badge (Initial/Patch/Minor/Major), changelog, publisher |
| `TestHarnessTab.tsx` | `TestHarnessPanel.tsx` | -- | Embedded as panel tab (not separate slide-in). Query input, run button, result display: response, confidence, sources, KB queries, guardrail events, latency |
| `PublishFlow.tsx` | (absent) | -- | Pre-publish checklist (inline expansion), version label input, required changelog textarea, confirm/cancel |
| `PlanCapabilitiesEditor.tsx` | (absent) | -- | Plan dropdown (None/Starter/Professional/Enterprise), capabilities chip input, cannot_do chip input (alert-dim styling) |
| `KBToolsEditor.tsx` | (absent) | -- | Recommended KB categories chip input + tool catalog checkbox list with health badges |
| `IconPicker.tsx` | (absent) | -- | 6-option grid (HR, Finance, Legal, IT, Search, Custom), 40x40px buttons |

#### Progressive Disclosure (Confirmed Decision)

The form uses progressive complexity based on agent type selection:

- **Default state (RAG-only)**: Section 1 (Identity), Section 2 (System Prompt), Section 6 (Guardrails), Section 7 (Summary/Pre-publish) are visible. Sections 3 (Auth + Creds), 4 (Plan + Capabilities), and 5 (KB Recommendations + Tool Assignments) show collapsed one-line summaries: "No authentication required", "No plan restriction", "No tools assigned"
- **When `auth_mode` changes to `tenant_credentials` or `platform_credentials`**: Section 3 expands with credential schema editor, Section 5 expands with tool assignment list, Section 4 expands (A2A agents typically need plan gating)
- Transition: 220ms ease, matching design system `--t` variable

#### Deprecated Components

| Component | Disposition |
|-----------|-------------|
| `TemplateAuthoringForm.tsx` | Replaced by `TemplateStudioPanel.tsx` -- delete after migration |
| `VersionHistoryDrawer.tsx` | Replaced by `VersionHistoryTab.tsx` -- delete after migration |
| `TestHarnessPanel.tsx` | Replaced by `TestHarnessTab.tsx` -- delete after migration |

#### Hook Changes

| Hook | Change |
|------|--------|
| `useAgentTemplatesAdmin.ts` | Extend mutation payloads to include `auth_mode`, `required_credentials`, `plan_required`, `capabilities`, `cannot_do`, `recommended_kb_categories`. Add `ETag` support (send `If-Match` on PUT, handle 409) |
| `useTemplateVersion.ts` (NEW) | `publishTemplate(id, version_label, changelog)` mutation. `useVersionHistory(id)` query. Breaking-change detection helper |
| `useTemplateTest.ts` (NEW) | `runTest(id, query)` mutation. Returns response, confidence, sources, guardrail events, latency |

### 1.3 Acceptance Criteria

- [ ] Platform admin can create a new template with all 7 configuration dimensions
- [ ] Progressive disclosure: RAG-only template shows 4 sections; selecting `auth_mode = tenant_credentials` reveals sections 3, 4, 5
- [ ] `{{variable}}` tokens auto-detected from system prompt text and synced to variable schema table
- [ ] Character counter shows warn at 1600, alert at 1800, blocks save at 2000
- [ ] Credential schema editor: add/remove/edit rows, key auto-generated from label, sensitive toggle
- [ ] Guardrail rule editor: add/remove rules, regex validation on blur, violation action radio
- [ ] Publish flow: pre-publish checklist, required changelog, version label input
- [ ] Version history tab: vertical timeline with changelog entries
- [ ] Test harness tab: execute test query, display response with metrics and guardrail events
- [ ] Instances tab: list tenant deployments with version, status, usage count
- [ ] `SystemPromptValidator` rejects known injection patterns server-side
- [ ] Optimistic concurrency: concurrent edit by two admins returns 409 with "modified by another admin" message
- [ ] 800px slide-in panel opens/closes without layout disruption

### 1.4 Dependency Ordering Within Phase

```
Week 1: v045 migration + SystemPromptValidator + API extensions (backend)
         IconPicker + SystemPromptEditor + CredentialSchemaEditor (frontend, parallel)
Week 2: GuardrailsEditor + PlanCapabilitiesEditor + KBToolsEditor (frontend)
         Version bump logic + publish endpoint (backend)
Week 3: TemplateStudioPanel assembly (4 tabs, progressive disclosure)
         PublishFlow + TestHarnessTab + VersionHistoryTab (frontend)
         Integration testing: full create/edit/publish/test cycle
```

---

## Phase 2: TA Agent Deployment Wizard

### 2.1 Backend Changes

#### KB Binding Resolution Fix

Modify `app/modules/chat/vector_search.py`:

- `VectorSearchService.search()` must resolve `kb_ids` from `capabilities` JSONB at chat time
- Query multiple KB indexes in parallel (not just `{tenant_id}-{agent_id}`)
- Per-KB RBAC enforcement: check user access for each KB binding before querying
- Proceed with partial context if some KBs are inaccessible (do not reveal inaccessible KBs exist)

Note: This fix may already be delivered by Plan 14 Phase A. If so, verify and skip.

#### Access Control INSERT on Deploy

Modify `app/modules/agents/routes.py` deploy handler:

- INSERT rows into `agent_access_control` based on `access_rules` from deployment request
- Support three modes: `workspace_wide` (all users), `role_restricted` (specified role IDs), `user_list` (specified user IDs)
- `GET /agents` (end-user chat agent list) must filter by `agent_access_control` JOIN for the requesting user's JWT claims

Note: This fix may already be delivered by Plan 14 Phase A. If so, verify and skip.

#### Credential Vault Integration

New module: `app/modules/agents/credential_manager.py`

- `store_credentials(tenant_id, agent_id, credentials: dict, schema: list)` -- validate against template's `required_credentials` schema, store via `VaultClient` at `{tenant_id}/agents/{agent_id}/{credential_key}`
- `test_credentials(template_id, credentials: dict) -> CredentialTestResult` -- delegate to `CredentialTestRunner` per doc 33 Section 8 (15-second hard timeout)
- `get_credentials(tenant_id, agent_id, credential_key) -> str` -- fetch from vault for runtime injection

Modify deploy endpoint:

- When `auth_mode = tenant_credentials`: validate all required credentials provided, store via vault, run async credential test
- Return `credential_test: passed | failed | pending` in response

#### Chat Agent Identity

Modify `GET /agents` response to include `icon`, `name`, `description` fields per agent (not just agent ID and status). These fields power the end-user chat agent selector.

#### Cache Invalidation Verification

Verify Redis pub/sub is wired for agent instance cache keys on ALL mutation paths: deploy, update access rules, update guardrails, pause, archive, credential update. The 5-minute TTL is a fallback, not the primary invalidation mechanism.

### 2.2 Frontend Changes

#### New Components

| Component | Width | Description |
|-----------|-------|-------------|
| `AgentDeployWizard.tsx` | 640px modal | 4-step wizard (step 3 conditional on `auth_mode != none`). Progress bar, step labels, back/next navigation |
| `WizardStep1TemplateSelect.tsx` | -- | Card list of published templates. Search input. Plan-gated cards locked. Shows capabilities, auth_mode, description |
| `WizardStep2KBTools.tsx` | -- | KB checkbox list (recommended-category KBs sorted to top with accent dot). Tool toggle list filtered to template-assigned tools. KB search mode radio (parallel/priority) |
| `WizardStep3Access.tsx` | -- | Access mode radio (workspace_wide/role_restricted/user_list). Role/user multi-select. Rate limit numeric input with plan-max reference. Guardrail summary (read-only from template) |
| `WizardStep4Credentials.tsx` | -- | Dynamic form generated from template `required_credentials` schema. Sensitive fields as password with eye toggle. [Test Connection] button with 15s timeout. Variable fill inputs from template variables |
| `DeployConfirmation.tsx` | -- | Success overlay: checkmark, agent name, summary of bindings/tools/access, [Go to Agents] / [Deploy Another] |
| `AgentLibraryPage.tsx` | -- | Replaces flat list in `ta-panel-agents`. Card grid: icon, name, template version, KB count, tool count, satisfaction bar, action buttons. Template update banner ("v1.1.0 available") on cards with stale version |
| Chat agent selector update | -- | Agent card in end-user chat mode selector shows icon, name, one-line description (not just name) |

### 2.3 Acceptance Criteria

- [ ] Tenant admin can browse template catalog with search and plan filtering
- [ ] Plan-gated templates show locked state with upgrade prompt
- [ ] Wizard Step 1: select template, preview capabilities and auth requirements
- [ ] Wizard Step 2: bind KBs (recommended sorted to top), toggle template-assigned tools
- [ ] Wizard Step 3: set access control (workspace/role/user), set rate limit, view guardrail summary
- [ ] Wizard Step 4 (conditional): enter credentials per schema, test connection with timeout
- [ ] Deploy creates agent instance with KB bindings, access control rows, vault credentials
- [ ] Deployed agent appears in end-user chat agent selector with icon, name, description
- [ ] End-user chat agent list filters by access control (users only see agents they are authorized for)
- [ ] Template update banner appears on agent cards when newer template version is available
- [ ] Cache invalidation fires on deploy (agent list cache refreshed immediately)

### 2.4 Dependency Ordering Within Phase

```
Week 4: KB binding resolution fix + access control INSERT (backend, if not done in Plan 14)
         WizardStep1TemplateSelect + WizardStep2KBTools (frontend, parallel)
Week 5: Credential vault integration + chat agent identity endpoint (backend)
         WizardStep3Access + WizardStep4Credentials + DeployConfirmation (frontend)
Week 6: AgentDeployWizard assembly + AgentLibraryPage
         Chat agent selector identity update
         Integration testing: full template-to-chat deployment cycle
```

---

## Phase 3: TA Custom Agent Studio

### 3.1 Backend Changes

#### Verify Existing Endpoints

The studio endpoints already exist per doc 33 Section 4.1:

- `POST /admin/agents/studio/create` -- creates draft
- `PUT /admin/agents/studio/{id}` -- updates draft
- `POST /admin/agents/studio/{id}/test` -- test harness (audit log required: `mode=test`)
- `POST /admin/agents/studio/{id}/publish` -- draft to active

Verify all four endpoints work end-to-end. In particular:

- Create must persist KB bindings in capabilities JSONB (not silently drop them)
- Test must write audit log with `mode: "test"` and `test_as_user_id = requesting admin's own ID`
- Publish must INSERT into `agent_access_control`

#### SystemPromptValidator for Tenant Prompts

The `SystemPromptValidator` from Phase 1 must also run on tenant custom agent saves. Tenant-authored prompts carry higher injection risk (Finding 6, FP-08 elevated to CRITICAL). Wire the validator into the `PUT /admin/agents/studio/{id}` handler.

### 3.2 Frontend Changes

#### New Components

| Component | Width | Description |
|-----------|-------|-------------|
| `CustomAgentStudioPanel.tsx` | 560px slide-in | Standard TA panel width. 5 accordion sections. No auth/credentials (custom agents use internal data only in v1). No version history (custom agents are not versioned in v1) |

The 5 sections reuse components from Phases 1 and 2:

| Section | Reused Component | Notes |
|---------|-----------------|-------|
| S1: Identity | `IconPicker`, identity fields from `TemplateStudioPanel` | Same fields minus version controls |
| S2: System Prompt + KB | `SystemPromptEditor` (no variable schema -- custom agents have literal prompts), KB picker from `WizardStep2KBTools` | KB picker shows tenant KBs only |
| S3: Access Control | Access controls from `WizardStep3Access` | Same radio group, role/user selectors |
| S4: Guardrails | `GuardrailsEditor` from Phase 1 | Fully editable (tenant owns guardrails for custom agents) |
| S5: Test + Publish | `TestHarnessTab` content adapted to panel context | Test query, run, view results, [Publish] button |

### 3.3 Acceptance Criteria

- [ ] Tenant admin can create a custom agent with system prompt, KB bindings, access control, guardrails
- [ ] `SystemPromptValidator` runs on every save (CRITICAL security boundary)
- [ ] Test harness executes query against draft configuration, writes audit log
- [ ] Publish transitions to active, agent appears in end-user chat selector
- [ ] Custom agents are NOT versioned (no version history section)
- [ ] Custom agents have NO auth/credential section (v1 limitation)
- [ ] Tenant custom agents cannot be promoted to platform templates (design decision: different entity types)

### 3.4 Dependency Ordering Within Phase

```
Week 7: Verify studio endpoints, wire SystemPromptValidator (backend)
         CustomAgentStudioPanel assembly from reused components (frontend)
Week 8: Integration testing: create/edit/test/publish custom agent
         End-to-end: custom agent visible in chat, access control enforced
```

---

## Phase 4: PA Template Performance Dashboard

### 4.1 Backend Changes

#### Performance Aggregation Endpoint

New endpoint: `GET /platform/agent-templates/{id}/performance`

Response:

```json
{
  "template_id": "tmpl_hr_v1",
  "adoption_count": 12,
  "active_instances": 9,
  "avg_satisfaction_pct": 84.2,
  "avg_confidence_score": 0.78,
  "guardrail_violation_count": 23,
  "guardrail_violation_rate_pct": 1.4,
  "queries_trailing_30d": 4821,
  "period": "trailing_30d"
}
```

Aggregation source: conversation metadata (satisfaction ratings, confidence scores, guardrail violation flags) JOIN agent instances pinned to this template. All data is anonymized -- no per-tenant breakdown, no per-user data, no system prompt exposure. Platform admin sees aggregate metrics only.

### 4.2 Frontend Changes

#### New Components

| Component | Description |
|-----------|-------------|
| `TemplatePerformanceTab.tsx` | New tab in `TemplateStudioPanel` (between Instances and Version History). 4 KPI cards: Adoption Count, Avg Satisfaction %, Avg Confidence Score, Guardrail Violation Count. Time-series chart (trailing 30d) for satisfaction and confidence trends. Table of top guardrail violations by rule name |

**KPI card tokens** (per design system):
- Card: `rounded-card bg-bg-elevated border border-border-faint p-5`
- Metric value: `font-mono text-page-title text-accent` (or `text-warn`/`text-alert` based on threshold)
- Metric label: `text-label-nav uppercase text-text-faint`
- KPI card gap: `12px` (design system standard)

### 4.3 Acceptance Criteria

- [ ] Performance tab visible in TemplateStudioPanel for published templates
- [ ] KPI cards show adoption count, satisfaction %, confidence score, violation count
- [ ] Metrics are aggregated across all tenant instances (no per-tenant data exposed)
- [ ] Performance data updates on page load (no real-time streaming needed)
- [ ] Empty state when template has zero instances: "No deployments yet. Performance metrics will appear after tenants adopt this template."

### 4.4 Dependency Ordering Within Phase

```
Week 9:  Performance aggregation endpoint + query optimization (backend)
          TemplatePerformanceTab with KPI cards (frontend)
Week 10: Trend chart + violation breakdown table (frontend)
          Integration testing with sample data
```

---

## Data Model Changes (Schema Delta)

### Migration v045: agent_templates Extension

| Column | Type | Nullable | Default | Purpose |
|--------|------|----------|---------|---------|
| `required_credentials` | `JSONB` | NOT NULL | `'[]'` | Credential schema for tenant input |
| `auth_mode` | `VARCHAR(32)` | NOT NULL | `'none'` | `none` / `tenant_credentials` / `platform_credentials` |
| `plan_required` | `VARCHAR(32)` | NULL | NULL | `starter` / `professional` / `enterprise` / NULL (no gate) |

### Migration v046: agent_template_versions (if not using JSONB array)

| Column | Type | Nullable | Purpose |
|--------|------|----------|---------|
| `id` | `UUID` | NOT NULL | Primary key |
| `template_id` | `UUID` | NOT NULL | FK to agent_templates |
| `version_label` | `VARCHAR(20)` | NOT NULL | Semver string (e.g., "1.0.0") |
| `change_type` | `VARCHAR(10)` | NOT NULL | `initial` / `patch` / `minor` / `major` |
| `changelog` | `TEXT` | NOT NULL | Required changelog entry |
| `published_by` | `UUID` | NOT NULL | Admin user ID |
| `published_at` | `TIMESTAMPTZ` | NOT NULL | Publication timestamp |
| `snapshot` | `JSONB` | NULL | Full template snapshot at publish time (for diff) |

### No Changes to agent_cards

KB bindings, tool assignments, and guardrails remain in the existing `capabilities` JSONB column per ADR in doc 52 (no join tables needed for low-cardinality data).

---

## API Contract Changes

### New Endpoints

| Method | Path | Phase | Auth | Description |
|--------|------|-------|------|-------------|
| `POST` | `/platform/agent-templates/{id}/publish` | 1 | PA | Publish with version label + changelog |
| `GET` | `/platform/agent-templates/{id}/versions` | 1 | PA | Version history with changelog entries |
| `GET` | `/platform/agent-templates/{id}/performance` | 4 | PA | Aggregated performance metrics |

### Modified Endpoints

| Method | Path | Phase | Change |
|--------|------|-------|--------|
| `POST` | `/platform/agent-templates` | 1 | Accept `auth_mode`, `required_credentials`, `plan_required`, `capabilities`, `cannot_do`, `recommended_kb_categories` |
| `PUT` | `/platform/agent-templates/{id}` | 1 | Accept all above + `ETag` concurrency. Run `SystemPromptValidator` |
| `POST` | `/admin/agents/adopt` | 2 | Validate required credentials, store via vault, INSERT access control, return credential test result |
| `GET` | `/agents` | 2 | Filter by `agent_access_control` for requesting user. Return `icon`, `name`, `description` per agent |
| `PUT` | `/admin/agents/studio/{id}` | 3 | Run `SystemPromptValidator` on tenant prompts |

### Unchanged Endpoints (verify behavior)

| Method | Path | Phase | Verification |
|--------|------|-------|-------------|
| `POST` | `/admin/agents/studio/create` | 3 | Persists KB bindings in capabilities JSONB |
| `POST` | `/admin/agents/studio/{id}/test` | 3 | Writes audit log with `mode: "test"` |
| `POST` | `/admin/agents/studio/{id}/publish` | 3 | INSERTs into `agent_access_control` |

---

## Component Inventory

### New Components (16)

| Component | Phase | Surface |
|-----------|-------|---------|
| `TemplateStudioPanel.tsx` | 1 | PA |
| `SystemPromptEditor.tsx` | 1 | PA, TA (Phase 3) |
| `CredentialSchemaEditor.tsx` | 1 | PA |
| `GuardrailsEditor.tsx` | 1 | PA, TA (Phase 3) |
| `PlanCapabilitiesEditor.tsx` | 1 | PA |
| `KBToolsEditor.tsx` | 1 | PA |
| `IconPicker.tsx` | 1 | PA, TA (Phases 2, 3) |
| `PublishFlow.tsx` | 1 | PA |
| `VersionHistoryTab.tsx` | 1 | PA |
| `TestHarnessTab.tsx` | 1 | PA |
| `AgentDeployWizard.tsx` | 2 | TA |
| `AgentLibraryPage.tsx` | 2 | TA |
| `DeployConfirmation.tsx` | 2 | TA |
| `CustomAgentStudioPanel.tsx` | 3 | TA |
| `TemplatePerformanceTab.tsx` | 4 | PA |
| `useTemplateVersion.ts` | 1 | PA |

### Deprecated Components (3)

| Component | Replaced By | Phase |
|-----------|-------------|-------|
| `TemplateAuthoringForm.tsx` | `TemplateStudioPanel.tsx` | 1 |
| `VersionHistoryDrawer.tsx` | `VersionHistoryTab.tsx` | 1 |
| `TestHarnessPanel.tsx` | `TestHarnessTab.tsx` | 1 |

### Extended Components (2)

| Component | Change | Phase |
|-----------|--------|-------|
| `useAgentTemplatesAdmin.ts` | New fields + ETag concurrency | 1 |
| `LifecycleActions.tsx` | Version bump on publish | 1 |

---

## Security Checklist

| # | Concern | Mitigation | Phase | Status |
|---|---------|-----------|-------|--------|
| SEC-01 | Prompt injection in PA-authored templates | `SystemPromptValidator` server-side on every save. Blocked patterns from doc 33 Section 4.2 | 1 | Required |
| SEC-02 | Prompt injection in TA-authored custom agents | Same `SystemPromptValidator` wired to `/admin/agents/studio/{id}` PUT handler | 3 | Required |
| SEC-03 | ReDoS via guardrail regex patterns | Regex complexity check at save time. 50ms evaluation timeout per pattern. Reject patterns with catastrophic backtracking potential | 1 | Required |
| SEC-04 | Credential exposure in browser | Credentials NEVER returned to browser after save. Stored via VaultClient server-side. Sensitive fields masked in UI. Test connection runs server-side only | 2 | Required |
| SEC-05 | Test-mode RBAC bypass | `test_as_user_id` restricted to requesting admin's own ID or synthetic test role. Test queries write audit log with `mode: "test"`. Cannot impersonate arbitrary users | 1, 3 | Required |
| SEC-06 | Access control enforcement gap | Deploy endpoint must INSERT into `agent_access_control`. Chat agent list must JOIN on access control. Agent resolution checks access before pipeline execution | 2 | Required (Plan 14 overlap) |
| SEC-07 | Cache invalidation on security-relevant changes | Redis pub/sub invalidation on ALL mutation paths: deploy, update access rules, update guardrails, pause, archive, credential update. 5-min TTL is fallback only | 2 | Required |
| SEC-08 | Optimistic concurrency on template edit | `ETag` / `If-Match` header on PUT. Return 409 on conflict. Prevents silent overwrite by concurrent admins | 1 | Required |
| SEC-09 | Tenant data sovereignty in Instances tab | PA sees tenant name and aggregate usage only. Cannot see system prompt contents, KB bindings, access rules, or credentials of any tenant instance | 1 | Required |

---

## Risk Register

| # | Risk | Probability | Impact | Mitigation | Owner |
|---|------|-------------|--------|-----------|-------|
| R-01 | Plan 14 backend Phase A (guardrails, access control, KB bindings) not complete before Phase 2 starts | Medium | HIGH -- deployment wizard creates agents with silently dropped config | Track Plan 14 sprint progress. Phase 2 backend work overlaps with Plan 14 Phase A. If Plan 14 is delayed, Phase 2 backend becomes Phase 2's responsibility | Backend lead |
| R-02 | 800px slide-in panel causes layout issues on smaller desktop screens (1280px width) | Low | MEDIUM -- admin cannot see full form content | Test at 1280px minimum. At `< 1024px`, show desktop-recommended banner. Sidebar collapses to icon-only (60px) when panel is open, giving 800px + 60px + padding = ~900px minimum | Frontend lead |
| R-03 | Progressive disclosure hides critical sections (auth, credentials) that PA forgets to configure | Medium | MEDIUM -- incomplete templates published | Pre-publish checklist explicitly calls out unconfigured sections. "Auth mode: None" shown in summary. If template has tool assignments but auth_mode = None, show warning: "Tools assigned but no credentials configured" | UX |
| R-04 | Credential test timeout (15s) makes wizard step 4 feel slow for tenants | Medium | LOW -- UX frustration but not blocking | Show progress indicator with elapsed time. Allow "Skip test, save credentials" option with warning. Async credential health check runs daily to catch failures | Frontend lead |
| R-05 | `SystemPromptValidator` blocked patterns are too aggressive -- rejects legitimate prompts | Low | MEDIUM -- PA cannot author templates | Log all rejections. Review blocked patterns quarterly. Allow PA override with explicit acknowledgment and audit log entry ("This prompt triggered a security warning. I confirm this is intentional.") | Security lead |

---

## Success Metrics

### Phase 1
- Platform admin can create and publish a structurally complete template (all 7 dimensions) within 15 minutes
- `SystemPromptValidator` blocks 100% of known injection patterns (test against OWASP LLM Top 10 prompt injection corpus)
- Zero regression in existing template CRUD operations (backward compatibility with 4 seed templates)

### Phase 2
- Tenant admin can deploy a template agent in under 5 minutes (from catalog browse to active agent in chat)
- End users see deployed agent with correct icon, name, and description in chat agent selector
- KB binding resolution works: agent searches all bound KBs, not just agent-scoped index
- Access control enforced: unauthorized users do not see agent in chat selector

### Phase 3
- Tenant admin can create and publish a custom agent in under 10 minutes
- `SystemPromptValidator` catches injection patterns in tenant-authored prompts
- Custom agent test harness produces audit log entry for every test query

### Phase 4
- Platform admin can view adoption count, satisfaction %, confidence score, and violation count for any published template
- Performance data available within 24 hours of first tenant deployment (no real-time requirement)

---

## Design Decisions Log

| Decision | Chosen | Alternatives Rejected | Rationale |
|----------|--------|----------------------|-----------|
| PA authoring surface | 800px slide-in panel | Full-page overlay (doc 02 original proposal) | Maintains spatial relationship with template list table. Avoids layout precedent break. 800px provides sufficient horizontal space for all 7 sections. Consistent with existing PA slide-in patterns (expanded width) |
| Agent type model | Progressive complexity (Option C from red team) | Uniform 7-section form (Option A), Two explicit types (Option B) | Preserves architectural simplicity (one data model) while providing lightweight experience for RAG-only agents. Sections reveal dynamically based on auth_mode selection |
| Tab layout | 4 tabs: Edit, Test, Instances, Version History | 5-tab (add Compliance), 3-tab (merge Test into Edit) | Compliance tab deferred (no violation log aggregation endpoint yet). Test as separate tab keeps Edit tab focused on configuration |
| TA custom agent versioning | Not versioned in v1 | Full versioning like templates | Custom agents are tenant-specific instances, not reusable artifacts. Versioning adds complexity without clear value for single-tenant usage. Can be added later if demand emerges |
| Tenant-to-platform promotion | Not supported (design decision) | Allow promotion with approval workflow | Tenant custom agents contain tenant-specific KB bindings and access rules that do not generalize. Platform templates are designed for reuse; tenant agents are designed for specificity. PA who sees a successful pattern should recreate it as a new template |
| Additive tenant guardrails on template agents | Not supported in v1 | Allow tenant admins to add guardrails on top of template guardrails | Guardrail evaluation order and conflict resolution (tenant guardrail blocks what template guardrail allows) is complex. Defer to post-v1 with explicit architecture decision |

---

**Document Version**: 1.0
**Last Updated**: 2026-03-21
