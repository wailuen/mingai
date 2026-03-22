# Agent Studio — Frontend Requirements Breakdown

> **Status**: Requirements Analysis
> **Date**: 2026-03-21
> **Analyst**: requirements-analyst
> **Source Documents**: `04-conceptual-model.md`, `02-ux-design-spec.md`, `15-agent-studio-plan.md`, `01-gap-and-risk-analysis.md`

---

## Critical Discrepancy: Phase Definitions

The user's request defines Phase 1 as **TA surfaces first** (Agent Library, Deploy Wizard, Tenant Skills, Tenant MCP Tools, Custom Agent Studio, A2A Registration). Plan 15 defines Phase 1 as **PA Template Studio first** (Option B).

Plan 15 is the authoritative implementation plan. This requirements breakdown follows Plan 15's phasing (PA first, then TA) but ensures ALL surfaces from the conceptual model are captured, including the three surfaces NOT yet in Plan 15:

- **Tenant Skills** (browse/adopt platform skills, author private skills)
- **Tenant MCP Tools** (register private MCP servers)
- **A2A Registration** (register external A2A agents, tenant-scoped)
- **PA Skills Library Management**
- **PA MCP Integration Builder**
- **PA Tool Catalog Management**
- **PA A2A Registry**

These require a **Phase 5** (or expansion of existing phases) in the implementation plan.

---

## 1. Complete Page/Route Inventory

### Existing Routes (Require Modification)

| Route | File | Current State | Required Changes |
|-------|------|---------------|------------------|
| `/platform/agent-templates` | `app/(platform)/platform/agent-templates/page.tsx` | Template list with `TemplateAuthoringForm` slide-in | Replace with `AgentStudioOverlay` full-page. Add [+ New Template] entry point |
| `/admin/agents` | `app/(admin)/admin/agents/page.tsx` | Agent list with `AgentDeployForm` | Add [+ New Agent] selector (From Template / Custom Agent), replace deploy form with wizard |
| `/settings/agents` | `app/settings/agents/page.tsx` | Settings agents page | Wire to TA agent management |

### New Routes Required

| Route | Page Component | Role | Phase | Surface |
|-------|---------------|------|-------|---------|
| `/platform/agent-templates/[id]` | `AgentStudioOverlay` | PA | 1 | Full-page overlay for template authoring (could be overlay rather than route) |
| `/platform/skills` | `PlatformSkillsPage` | PA | 5A | Skills Library management |
| `/platform/tools` | `PlatformToolCatalogPage` | PA | 5A | Tool Catalog + MCP Integration Builder |
| `/platform/a2a-registry` | `PlatformA2ARegistryPage` | PA | 5B | Platform-level A2A agent registry |
| `/admin/skills` | `TenantSkillsPage` | TA | 5A | Browse/adopt platform skills, author private skills |
| `/admin/mcp-tools` | `TenantMCPToolsPage` | TA | 5A | Register private MCP servers, view tools |
| `/admin/a2a-agents` | `TenantA2ARegistrationPage` | TA | 5B | Register external A2A agents (tenant-scoped) |

**Decision needed**: The full-page overlay for PA Template Studio may be implemented as a route (`/platform/agent-templates/[id]`) or as an overlay that does not change the URL. Plan 15 and the UX spec call it a "full-page overlay." Recommend URL-based routing for bookmarkability and browser back button support.

---

## 2. Complete Component Inventory

### Phase 1: PA Agent Template Studio (16 new + 3 deprecated)

#### New Components

| # | Component | File Path | Width/Layout | Purpose | Key Behaviors | Reuse |
|---|-----------|-----------|-------------|---------|---------------|-------|
| 1 | `AgentStudioOverlay` | `(platform)/platform/agent-templates/elements/AgentStudioOverlay.tsx` | 100vw - sidebar (collapses to 60px icon mode). Content max-width 860px centered. Header 56px sticky. Footer 56px sticky. | Full-page container with 4-tab layout (Edit, Compliance, Instances, Version History) and sticky header/footer | Open: sidebar collapses, fade-in 260ms. Close: sidebar restores, fade-out 200ms. Unsaved changes guard on close. Tab switching. Read-only mode for published templates. | -- |
| 2 | `AccordionSection` | `components/shared/AccordionSection.tsx` | Full width within parent | Collapsible section with header label, validation dot (green/warn/alert), collapsed summary line | Toggle on header click. Height transition via CSS grid-template-rows 0fr/1fr, 220ms ease. On create: all expanded. On edit: only modified + S1 expanded. Keyboard: Enter/Space to toggle. | PA S1-S7, TA Custom Studio S1-S5 |
| 3 | `SystemPromptEditor` | `(platform)/platform/agent-templates/elements/SystemPromptEditor.tsx` | Full width | DM Mono textarea with live `{{variable}}` detection, character counter, edit/preview toggle | Keystroke scanning (300ms debounce) for `{{var}}` patterns. Auto-populates variable schema. Counter: normal < 1600, warn 1600-1799, alert 1800-1999, block at 2000. Preview mode: read-only, accent-colored variables. | PA S2, TA Custom S2 (without variable schema) |
| 4 | `VariableSchemaTable` | `(platform)/platform/agent-templates/elements/VariableSchemaTable.tsx` | Full width | Editable table: key (font-mono), label, required toggle | Auto-synced from `SystemPromptEditor` detected variables. Rows for removed variables grayed with "Not in prompt" note. [+ Add Variable] for server-injected variables. Inline editing on focus, save on blur. | PA S2 only |
| 5 | `CredentialSchemaEditor` | `(platform)/platform/agent-templates/elements/CredentialSchemaEditor.tsx` | Full width | Editable table: key (auto-generated from label), label, type (string/secret), sensitive toggle | Key auto-slugifies from label. Add/remove rows. Delete icon on hover (text-faint, hover text-alert). Inline editing on focus, save on blur. | PA S3 only |
| 6 | `GuardrailRuleEditor` | `(platform)/platform/agent-templates/elements/GuardrailRuleEditor.tsx` | Full width | Rule cards with name, type dropdown, regex textarea, violation action radio, user message | Regex syntax validation on blur. Rule type: keyword_block / regex_match / content_filter. Violation action: block / redact / warn (inline horizontal radio). [+ Add Rule] button. Delete rule via X on card header. Expandable/collapsible rule cards. | PA S6, TA Custom S4 |
| 7 | `ConfidenceSlider` | `components/shared/ConfidenceSlider.tsx` | Inline | Range slider with DM Mono value readout | Native `<input type="range">` with ARIA attributes. Track: h-1 bg-border. Filled: h-1 bg-accent. Thumb: w-4 h-4 bg-accent. Value: font-mono text-accent. | PA S6, TA Custom S4, TA Deploy Wizard S3 (read-only) |
| 8 | `PlanCapabilitiesEditor` | `(platform)/platform/agent-templates/elements/PlanCapabilitiesEditor.tsx` | Full width | Plan dropdown + capabilities chip input + cannot_do chip input (alert-dim styling) | Plan select: None / Starter / Professional / Enterprise. Chip inputs: type + Enter to add, X to remove. Cannot_do chips use alert-dim bg. | PA S4 only |
| 9 | `ChipInput` | `components/shared/ChipInput.tsx` | Full width | Generic type-and-enter chip input with variants (default, alert) | Enter to add chip. X icon per chip to remove. Announce chip count to screen readers. Supports chip variant prop for styling (default = elevated/border, alert = alert-dim/alert). | PA S4, PA S5, TA Skills, TA MCP Tools |
| 10 | `KBToolsEditor` | `(platform)/platform/agent-templates/elements/KBToolsEditor.tsx` | Full width | Recommended KB categories (chip input) + tool assignment checkbox list with classification and health badges | KB categories: same chip input as capabilities. Tools: checkbox list from Tool Catalog. Each tool row: checkbox, name (font-medium), classification badge (Read-Only=accent, Write=warn, Execute=alert), health badge (Healthy=accent, Degraded=warn, Down=alert, Unknown=faint). Counter: "N of M available" in mono. | PA S5 only |
| 11 | `IconPicker` | `components/shared/IconPicker.tsx` | Inline grid | 6-option icon grid (HR, Finance, Legal, IT, Search, Custom), 40x40px buttons | Selected: accent border + accent-dim bg. Unselected: border-faint, bg-elevated. Rounded-control radius. | PA S1, TA Deploy Wizard, TA Custom S1 |
| 12 | `PrePublishChecklist` | `(platform)/platform/agent-templates/elements/PrePublishChecklist.tsx` | Full width | Validation checklist with pass/warn/fail icons + version label input + changelog textarea | Expands when [Publish] clicked, accordion sections collapse. Pass: accent check. Warn: warn triangle. Fail: alert X. Version label: font-mono input. Changelog: required, min 10 chars. [Cancel] + [Confirm Publish]. | PA only |
| 13 | `VersionHistoryTab` | `(platform)/platform/agent-templates/elements/VersionHistoryTab.tsx` | Full width (tab panel) | Vertical timeline of published versions | Timeline: 2px vertical line (--border). Dot: 8px, accent for latest, bg-elevated for older. Version: font-mono. Date: font-mono 11px faint. Type badge: rounded-badge 11px (Initial/Patch/Minor/Major). Changelog: text-body-default muted. Publisher: 11px faint. | PA Version History tab |
| 14 | `TestHarnessTab` | `(platform)/platform/agent-templates/elements/TestHarnessTab.tsx` | 400px slide-in from right | Query input, run button, result display with confidence, sources, KB queries, guardrail events, latency | Slide-in: animate-slide-in-right 200ms. Close: animate-slide-out-right 200ms. Running state: pulsing badge. Result: font-mono metrics. Guardrail triggered: alert styling. Multiple test queries supported (guardrail test section). | PA test, TA Custom test |
| 15 | `PublishFlow` | `(platform)/platform/agent-templates/elements/PublishFlow.tsx` | Full width (inline within edit tab) | Pre-publish review, version label, changelog, confirm/cancel | Delegates to `PrePublishChecklist` for rendering. Handles the [Confirm Publish] mutation. Version bump modal for breaking changes (prompt, guardrails, credentials, tools changed). Diff display: [changed] / [added] badges. | PA only |
| 16 | `InstancesTab` | `(platform)/platform/agent-templates/elements/InstancesTab.tsx` | Full width (tab panel) | Table of tenant deployments: tenant name, version, status badge, deployed date, usage count | Status badges: Active=accent, Pending=warn, Paused=faint. Version: warn text if older than current. Usage: DM Mono, trailing 30d. Data sovereignty: PA sees tenant name + aggregate only, never config/KB/prompt/credentials. | PA Instances tab |

#### Deprecated Components

| Component | File | Replaced By |
|-----------|------|-------------|
| `TemplateAuthoringForm.tsx` | `(platform)/platform/agent-templates/elements/` | `AgentStudioOverlay` |
| `VersionHistoryDrawer.tsx` | `(platform)/platform/agent-templates/elements/` | `VersionHistoryTab` |
| `TestHarnessPanel.tsx` | `(platform)/platform/agent-templates/elements/` | `TestHarnessTab` |

#### Extended Components

| Component | Change |
|-----------|--------|
| `LifecycleActions.tsx` | Refactor: version bump on publish delegates to `PublishFlow` |
| `TemplateList.tsx` | Add [+ New Template] button, row click opens overlay |

---

### Phase 2: TA Agent Deployment Wizard (7 new)

| # | Component | File Path | Width/Layout | Purpose | Key Behaviors | Reuse |
|---|-----------|-----------|-------------|---------|---------------|-------|
| 17 | `AgentCreationSelector` | `(admin)/admin/agents/elements/AgentCreationSelector.tsx` | Popover ~200px | [From Template] / [Custom Agent] selection popover | Triggered by [+ New Agent] button. Popover with two options. Rounded-card, bg-surface, border. | TA agents page |
| 18 | `AgentDeployWizard` | `(admin)/admin/agents/elements/AgentDeployWizard.tsx` | 640px modal, centered | 4-step wizard container with progress bar, step navigation, conditional step 4 | Progress bar: 4px accent fill. Step label: "Step N of M -- Step Name". Footer: [< Back] ghost + [Next: Step Name >] accent. Final step: [Deploy Agent]. Close button top-right. Backdrop: bg-deep/60. Step transition: fade + 8px translateX, 220ms. | TA agents page |
| 19 | `WizardStep1TemplateSelect` | `(admin)/admin/agents/elements/WizardStep1TemplateSelect.tsx` | Full wizard width | Card list of published templates with search and plan filtering | Card: rounded-card, border, hover border-accent-ring. Icon + name (section-heading) + version (mono 11px) + description (2 lines ellipsis) + auth note + capability chips + [Select] button. Plan-gated: bg-deep opacity-60, lock icon, no Select. Search input at top. | TA wizard step 1 |
| 20 | `WizardStep2KBTools` | `(admin)/admin/agents/elements/WizardStep2KBTools.tsx` | Full wizard width | KB checkbox list (recommended sorted top with accent dot) + tool toggle list | KB rows: checkbox, accent dot for recommended, name (font-medium), source path (11px faint), doc count (mono 11px). Search mode radio: parallel / priority. Tool rows: same as PA KBToolsEditor tool list pattern, filtered to template-assigned tools only. | TA wizard step 2 |
| 21 | `WizardStep3Access` | `(admin)/admin/agents/elements/WizardStep3Access.tsx` | Full wizard width | Access mode radio + role/user multi-select + rate limit + guardrail summary (read-only) | Access mode: workspace_wide / role_restricted / user_list. Role chips: rounded-badge bg-elevated. Rate limit: font-mono w-24 input + plan-max reference (mono 11px faint). Guardrail section: rounded-control bg-deep border-faint, italic note "Set by template. Contact platform admin to modify." | TA wizard step 3 |
| 22 | `WizardStep4Credentials` | `(admin)/admin/agents/elements/WizardStep4Credentials.tsx` | Full wizard width | Dynamic credential form from template schema + test connection + variable fill | Credential inputs: standard input styling. Sensitive: type=password + eye toggle (16px). [Test Connection]: ghost button, 15s timeout. States: Idle (ghost), Testing (spinner + "Validating..."), Passed (accent check + connected identity), Failed (alert X + error). Variable fill inputs for template variables. | TA wizard step 4 |
| 23 | `DeployConfirmation` | `(admin)/admin/agents/elements/DeployConfirmation.tsx` | Full wizard width | Success overlay: checkmark (44px), agent name, binding summary, [Go to Agents] / [Deploy Another] | Accent checkmark icon. Summary: KB count, tool count, access mode. Two CTAs: [Go to Agents] accent primary, [Deploy Another] ghost. | TA wizard final |

#### Extended Components

| Component | Change |
|-----------|--------|
| `AgentCard.tsx` | Add template version badge (mono 11px). Template update banner ("v1.1.0 available") when stale. Icon display from template. |
| `AgentFilterBar.tsx` | Add template version filter, status filter |
| Chat agent selector (in `ChatInterface` or `ChatEmptyState`) | Show icon, name, one-line description per agent (not just name) |

---

### Phase 3: TA Custom Agent Studio (2 new)

| # | Component | File Path | Width/Layout | Purpose | Key Behaviors | Reuse From |
|---|-----------|-----------|-------------|---------|---------------|------------|
| 24 | `CustomAgentPanel` | `(admin)/admin/agents/elements/CustomAgentPanel.tsx` | 560px slide-in (existing TA pattern) | 5-section accordion: Identity, System Prompt, KB Bindings, Guardrails, Access Control. Footer: [Test] [Save Draft] [Publish] | Reuses: `AccordionSection`, `IconPicker`, `SystemPromptEditor` (without variable schema), `GuardrailRuleEditor`, `ConfidenceSlider`. KB picker from `WizardStep2KBTools`. Access controls from `WizardStep3Access`. No auth section. No plan section. No versioning. Test harness as nested 400px slide-in. | Phase 1+2 components |
| 25 | `CustomAgentTestPanel` | `(admin)/admin/agents/elements/CustomAgentTestPanel.tsx` | 400px slide-in from right | Same as PA test harness but adapted for custom agent context | Same layout as `TestHarnessTab` but triggered from custom panel [Test] button. Writes audit log with mode=test. | `TestHarnessTab` pattern |

---

### Phase 4: PA Template Performance Dashboard (1 new)

| # | Component | File Path | Width/Layout | Purpose | Key Behaviors |
|---|-----------|-----------|-------------|---------|---------------|
| 26 | `TemplatePerformanceTab` | `(platform)/platform/agent-templates/elements/TemplatePerformanceTab.tsx` | Full width (tab panel between Instances and Version History) | 4 KPI cards (adoption count, avg satisfaction %, avg confidence, violation count) + trend chart + violation breakdown table | KPI cards: rounded-card bg-elevated border-faint p-5. Value: font-mono text-page-title text-accent (or warn/alert by threshold). Label: text-label-nav uppercase faint. Gap: 12px. Chart: trailing 30d, satisfaction + confidence lines. Table: top violations by rule name. Empty state: "No deployments yet." |

---

### Phase 5A: Skills + Tools Surfaces (NOT IN PLAN 15 — REQUIRES PLAN AMENDMENT)

These surfaces are defined in the conceptual model (doc 04) but have NO implementation plan, NO UX design spec, and NO user flow documentation. This is a significant gap.

#### TA Tenant Skills (5 new)

| # | Component | File Path | Purpose | Key Behaviors |
|---|-----------|-----------|---------|---------------|
| 27 | `TenantSkillsPage` | `(admin)/admin/skills/page.tsx` | Two-tab layout: Platform Skills (browse/adopt) + My Skills (authored) | Tab bar (12px/500). Platform tab: card grid of available skills. My Skills tab: list of tenant-authored skills. |
| 28 | `PlatformSkillCard` | `(admin)/admin/skills/elements/PlatformSkillCard.tsx` | Browse card for platform skills: name, category, version, execution pattern badge, tool deps, plan gate, [Adopt] / [Adopted] button | Card: rounded-card border bg-surface. Execution pattern: prompt / tool_composing / sequential_pipeline badge. Mandatory skills: grayed, locked icon, "Required by platform" note. Plan-gated: locked if plan insufficient. Adopted: accent outline "Adopted" with version pin option. |
| 29 | `SkillAdoptionPanel` | `(admin)/admin/skills/elements/SkillAdoptionPanel.tsx` | Slide-in (560px) for adoption config: version pin toggle, preview prompt (read-only), tool dependency check | Version pin: toggle + version selector dropdown. If unpinned: auto-updates with platform changes. Preview: read-only prompt template, read-only tool deps. [Adopt Skill] accent primary. |
| 30 | `TenantSkillEditor` | `(admin)/admin/skills/elements/TenantSkillEditor.tsx` | Slide-in (560px) for authoring private skills: name, description, category, execution pattern, prompt template, tool selection, input/output schema, LLM config | 3 execution pattern tabs/modes: Pure Prompt (textarea only), Tool-Composing (prompt + tool picker), Sequential Pipeline (ordered step list). Prompt template with `{{input.field}}` variable highlighting. Tool picker: checkbox list filtered by tenant plan. Input/output schema: JSON Schema editor (simplified key/type/required table). LLM config: model (inherit from agent default), temperature slider, max_tokens input. |
| 31 | `PipelineStepEditor` | `(admin)/admin/skills/elements/PipelineStepEditor.tsx` | Ordered step list for sequential pipeline skills | Drag-to-reorder step cards. Each step: step number, tool selector OR prompt textarea, input mapping (from previous step output). [+ Add Step] button. Delete step via X. |

#### TA Tenant MCP Tools (3 new)

| # | Component | File Path | Purpose | Key Behaviors |
|---|-----------|-----------|---------|---------------|
| 32 | `TenantMCPToolsPage` | `(admin)/admin/mcp-tools/page.tsx` | List registered private MCP servers + their tools | Table: server name, endpoint URL, tool count, health status, last ping, actions. Expand row to show individual tools. [+ Register MCP Server] button. |
| 33 | `MCPServerRegistrationForm` | `(admin)/admin/mcp-tools/elements/MCPServerRegistrationForm.tsx` | Slide-in (560px) for registering a private MCP server | Fields: name, endpoint URL, auth type (none/api_key/oauth2), description. [Test Connection] with 15s timeout. On success: platform reads available tools from MCP endpoint, displays tool list for confirmation. [Register] saves server + tools. |
| 34 | `MCPServerDetailPanel` | `(admin)/admin/mcp-tools/elements/MCPServerDetailPanel.tsx` | Slide-in showing server details + tool list with health badges | Server: name, endpoint, auth type, status, last ping. Tools: name, description, input/output schema preview, invocation count, health. Actions: [Refresh Tools], [Edit], [Remove]. |

#### PA Skills Library Management (4 new)

| # | Component | File Path | Purpose | Key Behaviors |
|---|-----------|-----------|---------|---------------|
| 35 | `PlatformSkillsPage` | `(platform)/platform/skills/page.tsx` | Table of all platform skills with [+ New Skill] | Columns: name, category, version, execution pattern, plan gate, mandatory toggle, adoption count, status. Row click opens editor. |
| 36 | `PlatformSkillEditor` | `(platform)/platform/skills/elements/PlatformSkillEditor.tsx` | Full slide-in (800px) for PA skill authoring | Same editor capabilities as `TenantSkillEditor` plus: plan gate selector, mandatory toggle, version management (semver + changelog), publish flow. PA can see adoption metrics. |
| 37 | `SkillVersionManager` | `(platform)/platform/skills/elements/SkillVersionManager.tsx` | Version timeline + publish flow for skills | Same pattern as template `VersionHistoryTab` + `PublishFlow` adapted for skills. Breaking change detection on prompt/tool/schema changes. |
| 38 | `MandatorySkillBanner` | `components/shared/MandatorySkillBanner.tsx` | Inline banner showing mandatory status with lock icon | "This skill is enforced on all tenant agents and cannot be removed." Alert-dim bg, lock icon, faint text. |

#### PA MCP Integration Builder (4 new)

| # | Component | File Path | Purpose | Key Behaviors |
|---|-----------|-----------|---------|---------------|
| 39 | `PlatformToolCatalogPage` | `(platform)/platform/tools/page.tsx` | Table of all tools (built-in + MCP + tenant) with [+ Import API] | Extends existing `useToolCatalog`. Columns: name, source (built-in/MCP/tenant), provider, safety class, health, plan gate, invocation count. Filter by source, health, plan. |
| 40 | `MCPIntegrationWizard` | `(platform)/platform/tools/elements/MCPIntegrationWizard.tsx` | 640px modal, 4-step: upload API doc, select endpoints, configure tools, publish | Step 1: File upload (OpenAPI JSON/YAML, Postman collection, raw docs). Step 2: Parsed endpoint list with checkboxes. Step 3: Per-tool config (name, description, credential schema, rate limit, plan gate). Step 4: Review + [Publish to Catalog]. |
| 41 | `APIDocUploader` | `(platform)/platform/tools/elements/APIDocUploader.tsx` | Drag-drop file upload for API documentation | Supported formats: OpenAPI 3.x JSON/YAML, Postman Collection v2.1, raw markdown/text. File validation on drop. Parse progress indicator. |
| 42 | `EndpointSelector` | `(platform)/platform/tools/elements/EndpointSelector.tsx` | Checkbox list of parsed API endpoints with method/path/description | Each row: checkbox, HTTP method badge (GET=accent, POST=warn, PUT=warn, DELETE=alert), path (font-mono), description. Select all / deselect all. |

#### PA Tool Catalog Management (1 new)

| # | Component | File Path | Purpose | Key Behaviors |
|---|-----------|-----------|---------|---------------|
| 43 | `ToolConfigPanel` | `(platform)/platform/tools/elements/ToolConfigPanel.tsx` | Slide-in for viewing/editing tool config: credential schema, rate limit, plan gate, health history | Tool details: name, provider, endpoint, safety class. Credential schema table (same as template credential editor). Rate limit: requests_per_minute input. Plan gate: dropdown. Health history: mini timeline of health checks. |

---

### Phase 5B: A2A Registration Surfaces (NOT IN PLAN 15)

#### TA A2A Registration (3 new)

| # | Component | File Path | Purpose | Key Behaviors |
|---|-----------|-----------|---------|---------------|
| 44 | `TenantA2ARegistrationPage` | `(admin)/admin/a2a-agents/page.tsx` | List of tenant-registered external A2A agents | Table: name, card URL, status, operations count, last invoked, actions. [+ Register A2A Agent] button. |
| 45 | `A2ARegistrationForm` | `(admin)/admin/a2a-agents/elements/A2ARegistrationForm.tsx` | Slide-in (560px) for registering an external A2A agent | Fields: agent card URL (validated), name override, description override. On URL entry: fetch card, display operations contract preview. Guardrails overlay config: topic restrictions, PII masking. [Register] button. |
| 46 | `A2ACardPreview` | `(admin)/admin/a2a-agents/elements/A2ACardPreview.tsx` | Read-only display of an imported A2A agent card | Shows: name, description, operations list (name + input/output schema), authentication requirements, capabilities. Rendered from fetched card data. |

#### PA A2A Registry (2 new)

| # | Component | File Path | Purpose | Key Behaviors |
|---|-----------|-----------|---------|---------------|
| 47 | `PlatformA2ARegistryPage` | `(platform)/platform/a2a-registry/page.tsx` | List of platform-registered external A2A agents | Table: name, card URL, status, plan gate, assigned tenants count, operations count. [+ Register Platform A2A] button. |
| 48 | `PlatformA2ARegistrationForm` | `(platform)/platform/a2a-registry/elements/PlatformA2ARegistrationForm.tsx` | Slide-in (800px) for platform-level A2A registration | Same as TA form plus: plan gate selector, tenant assignment (multi-select), guardrails overlay, wrapper configuration. |

---

## 3. Complete Hook Inventory

### Existing Hooks (Require Extension)

| Hook | File | Current State | Required Changes | Phase |
|------|------|---------------|------------------|-------|
| `useAgentTemplatesAdmin` | `lib/hooks/useAgentTemplatesAdmin.ts` | CRUD for templates with basic fields | Add `ETag` support (send `If-Match` on PUT, handle 409). Extend mutation payloads: `auth_mode`, `required_credentials`, `plan_required`, `capabilities`, `cannot_do`, `recommended_kb_categories`, `attached_skills`, `attached_tools`, `credential_schema`. Add icon field. | 1 |
| `useAgentTemplates` | `lib/hooks/useAgentTemplates.ts` | TA template browsing | Add plan filtering, search, template version check for update banner | 2 |
| `useToolCatalog` | `lib/hooks/useToolCatalog.ts` | Platform tool list + register | Add plan gate field, health history query, tool assignment for templates | 1 |

### New Hooks Required

| Hook | File | Queries/Mutations | Cache Key | Phase |
|------|------|-------------------|-----------|-------|
| `useTemplateVersion` | `lib/hooks/useTemplateVersion.ts` | `publishTemplate(id, version_label, changelog)` mutation. `useVersionHistory(id)` query. | `["template-versions", id]` | 1 |
| `useTemplateTest` | `lib/hooks/useTemplateTest.ts` | `runTest(id, query)` mutation. Returns response, confidence, sources, guardrail_events, latency. | No cache (mutation only) | 1 |
| `useTemplatePerformance` | `lib/hooks/useTemplatePerformance.ts` | `usePerformanceMetrics(id)` query: adoption_count, avg_satisfaction, avg_confidence, violation_count, violation_rate, queries_30d. | `["template-performance", id]` | 4 |
| `useAgentDeploy` | `lib/hooks/useAgentDeploy.ts` | `deployAgent(template_id, kb_ids, tool_ids, access_rules, credentials, variables)` mutation. `testCredentials(template_id, credentials)` mutation. | Invalidates `["tenant-agents"]` on deploy | 2 |
| `useSkills` | `lib/hooks/useSkills.ts` | `usePlatformSkills(filters)` query. `useTenantSkills(tenant_id)` query. `createSkill(payload)` mutation. `updateSkill(id, payload)` mutation. `deleteSkill(id)` mutation. `publishSkill(id, version, changelog)` mutation. | `["platform-skills"]`, `["tenant-skills"]` | 5A |
| `useSkillAdoption` | `lib/hooks/useSkillAdoption.ts` | `adoptSkill(skill_id, version_pin?)` mutation. `unadoptSkill(skill_id)` mutation. `pinVersion(skill_id, version)` mutation. | Invalidates `["tenant-skills"]` | 5A |
| `useMCPServers` | `lib/hooks/useMCPServers.ts` | `useTenantMCPServers()` query. `registerMCPServer(payload)` mutation. `removeMCPServer(id)` mutation. `refreshTools(server_id)` mutation. `testMCPConnection(endpoint, auth)` mutation. | `["tenant-mcp-servers"]` | 5A |
| `useMCPIntegrationBuilder` | `lib/hooks/useMCPIntegrationBuilder.ts` | `parseAPIDoc(file)` mutation (returns endpoints). `publishTools(config)` mutation. | No cache (wizard flow) | 5A |
| `useA2ARegistration` | `lib/hooks/useA2ARegistration.ts` | `useTenantA2AAgents()` query. `registerA2AAgent(card_url, config)` mutation. `removeA2AAgent(id)` mutation. `fetchA2ACard(url)` mutation. | `["tenant-a2a-agents"]`, `["platform-a2a-agents"]` | 5B |
| `useCustomAgent` | `lib/hooks/useCustomAgent.ts` | `createCustomAgent(payload)` mutation. `updateCustomAgent(id, payload)` mutation. `publishCustomAgent(id)` mutation. `testCustomAgent(id, query)` mutation. | Invalidates `["tenant-agents"]` | 3 |

---

## 4. Shared Components (Cross-Surface Reuse Map)

| Component | Used In | Variant/Config |
|-----------|---------|----------------|
| `AccordionSection` | PA Template Studio (7 sections), TA Custom Agent (5 sections), PA Skill Editor (sections), TA Skill Editor (sections) | Props: `title`, `validationState` (valid/warn/error/untouched), `defaultExpanded`, `collapsedSummary` |
| `IconPicker` | PA S1, TA Deploy Wizard (card display), TA Custom S1 | Props: `value`, `onChange`, `icons` (default 6-set) |
| `ChipInput` | PA S4 (capabilities, cannot_do), PA S5 (KB categories), Skill editor (tool deps), MCP tool capabilities | Props: `value`, `onChange`, `variant` (default/alert), `placeholder` |
| `ConfidenceSlider` | PA S6, TA Custom S4, TA Deploy S3 (read-only) | Props: `value`, `onChange`, `readOnly`, `min`, `max`, `step` |
| `SystemPromptEditor` | PA S2 (with variable schema), TA Custom S2 (without variable schema), PA Skill editor (prompt template), TA Skill editor | Props: `value`, `onChange`, `maxLength`, `showVariableSchema`, `variablePrefix` (`{{` for templates, `{{input.` for skills) |
| `GuardrailRuleEditor` | PA S6, TA Custom S4 | Props: `rules`, `onChange`, `readOnly` (for deploy wizard guardrail display) |
| `CredentialSchemaEditor` | PA S3, PA Tool config | Props: `schema`, `onChange` |
| `CredentialEntryForm` | TA Deploy Wizard S4, TA A2A registration (if needed) | Props: `schema` (from template), `values`, `onChange`, `onTest`, `testState` |
| `KBBindingPicker` | TA Deploy Wizard S2, TA Custom S3 | Props: `kbs`, `selectedIds`, `onChange`, `recommendedCategories`, `searchMode` |
| `AccessControlSelector` | TA Deploy Wizard S3, TA Custom S5. Already exists at `(admin)/admin/agents/elements/AccessControlSelector.tsx` | Extend with rate limit input, plan-max reference |
| `ToolAssignmentList` | PA S5, TA Deploy S2 (filtered to template tools), Skill editor (tool deps) | Props: `tools`, `selectedIds`, `onChange`, `readOnly`, `filterToIds` |
| `MandatorySkillBanner` | TA Skills page (on mandatory skills), TA Custom Agent (on attached mandatory skills) | Props: `skillName` |

---

## 5. State Management Requirements

### React Query (Server State)

All data that comes from the backend uses `@tanstack/react-query`. This is the existing pattern in the codebase.

| Data | Cache Key | Stale Time | Invalidation Triggers |
|------|-----------|------------|----------------------|
| Template list (PA) | `["platform-templates"]` | 30s | Create, update, publish, deprecate |
| Template detail (PA) | `["platform-templates", id]` | 0 (always fresh on focus) | Update, publish |
| Template versions | `["template-versions", id]` | 5m | Publish |
| Template performance | `["template-performance", id]` | 5m | -- (server-aggregated) |
| Template instances | `["template-instances", id]` | 1m | Deploy (from TA side) |
| Tenant agent list | `["tenant-agents"]` | 30s | Deploy, publish custom, update, pause, archive |
| Published templates (TA) | `["published-templates"]` | 5m | -- (PA publishes are infrequent) |
| Platform skills | `["platform-skills"]` | 5m | PA publishes |
| Tenant skills | `["tenant-skills"]` | 30s | Adopt, create, update, delete |
| Platform tools | `["platform-tools"]` | 5m | Register, update health |
| Tenant MCP servers | `["tenant-mcp-servers"]` | 1m | Register, remove, refresh |
| Tenant A2A agents | `["tenant-a2a-agents"]` | 1m | Register, remove |
| Platform A2A agents | `["platform-a2a-agents"]` | 5m | Register, remove |

### Local State (Component-Level)

| State | Scope | Storage | Reason |
|-------|-------|---------|--------|
| Form draft (all editors) | Component tree | `useState` / `useReducer` | Complex nested form with unsaved changes tracking. Not persisted to server until explicit save. |
| Accordion expanded/collapsed | `AccordionSection` | `useState` per section | UI-only state |
| Active tab (Edit/Compliance/Instances/History) | `AgentStudioOverlay` | `useState` | UI-only, could be URL param for bookmarkability |
| Wizard current step | `AgentDeployWizard` | `useState` | Linear flow, no need to persist |
| Unsaved changes flag | Form containers | `useState` (derived from form dirty check) | Controls unsaved changes guard modal |
| ETag for concurrency | `useAgentTemplatesAdmin` | `useRef` (updated on every GET/PUT response) | Must persist across re-renders, not trigger re-render |
| Test harness open/closed | `AgentStudioOverlay`, `CustomAgentPanel` | `useState` | UI-only |
| Chip input draft text | `ChipInput` | `useState` | Controlled input before Enter |
| Publish flow active | `AgentStudioOverlay` | `useState` | Controls accordion collapse + checklist expansion |

### Cross-Component Communication

| Communication | Pattern | Implementation |
|---------------|---------|----------------|
| SystemPromptEditor -> VariableSchemaTable | Callback prop | `onVariablesDetected(variables: string[])` from editor to parent, parent passes to schema table |
| Wizard step data flow | Lifted state | `AgentDeployWizard` holds all step data in a single `useReducer`. Each step reads/writes to this shared state. |
| Template update -> Agent card banner | React Query invalidation | When PA publishes new version, TA's `["published-templates"]` cache becomes stale. Agent cards compare `instance.template_version` to `template.current_version`. |
| Deploy -> Chat agent list | React Query invalidation | `useAgentDeploy` mutation `onSuccess` invalidates chat agent list cache |

---

## 6. Empty States, Loading States, Error States

### Empty States (Every List/Table)

| Surface | Empty State | Icon | Headline | Subtext |
|---------|------------|------|----------|---------|
| PA Template list | No templates | Document icon (24px, faint) | "No agent templates" | "Create your first template to get started." + [+ New Template] accent button |
| PA Version History | No versions | Clock icon | "No versions published" | "Save as draft and publish when ready." |
| PA Instances tab | No deployments | Users icon | "No deployments yet" | "Performance metrics will appear after tenants adopt this template." |
| PA Compliance tab | No violations | Shield icon | "No violations recorded" | "Guardrail compliance data will appear as agents are used." |
| PA Performance tab | No data | Chart icon | "No deployments yet" | "Performance metrics will appear after tenants adopt this template." |
| TA Agent library | No agents | Bot icon | "No agents deployed" | "Deploy a template or create a custom agent." + [+ New Agent] button |
| TA Template catalog (wizard S1) | No templates available | Search icon | "No templates available" | "Your platform admin has not published any templates yet." |
| TA Custom agent list | No custom agents | Wrench icon | "No custom agents" | "Create a custom agent with your own prompt and knowledge base." |
| TA Skills - Platform | No skills available | Lightbulb icon | "No platform skills available" | "Platform skills will appear here when published by your admin." |
| TA Skills - My Skills | No tenant skills | Lightbulb icon | "No skills created" | "Author your first skill to add reusable intelligence to your agents." + [+ New Skill] button |
| TA MCP Tools | No servers | Plug icon | "No MCP servers registered" | "Register a private MCP server to make external tools available to your agents." + [+ Register MCP Server] button |
| TA A2A Agents | No A2A agents | Globe icon | "No external agents registered" | "Register an external A2A agent to make it available in your workspace." + [+ Register A2A Agent] button |
| PA Skills Library | No skills | Lightbulb icon | "No platform skills" | "Author your first platform skill." + [+ New Skill] button |
| PA Tool Catalog | No tools (unlikely — built-ins exist) | Wrench icon | "No tools registered" | "Import an API or wait for built-in tools to initialize." |
| PA A2A Registry | No platform A2A | Globe icon | "No platform A2A agents" | "Register external agents to make them available to tenants." |

### Loading States

| Surface | Loading Pattern |
|---------|----------------|
| All tables/lists | Skeleton rows: 5 rows with pulsing bg-elevated blocks matching column widths. Use existing `LoadingState` component adapted for table context. |
| All slide-in panels | Skeleton content: pulsing blocks for form fields. Panel chrome (header, close button) renders immediately. |
| Full-page overlay | Skeleton tabs + skeleton accordion headers. Content loads progressively. |
| Wizard steps | [Next] button disabled + spinner while step data loads. Content area shows skeleton. |
| Credential test | Spinner (16px) + "Validating..." text. 15s timeout with progress indicator showing elapsed time. |
| Template test | Pulsing "Running Test..." badge in test harness. Response area shows "Processing..." |
| MCP connection test | Same as credential test pattern. |
| A2A card fetch | Spinner + "Fetching agent card..." in card preview area. |

### Error States

| Error | Surface | Display | Recovery |
|-------|---------|---------|----------|
| 409 Conflict (concurrent edit) | PA Template Studio | Modal: "Conflict Detected. This template was modified by another admin." [Reload] button. Local edits preserved in form state until explicit reload. | [Reload] refetches template, discards local |
| 403 Forbidden (plan gate) | TA Template Catalog | Card locked: bg-deep opacity-60, lock icon, "Upgrade to {plan} to access this template" | Link to plan upgrade (or contact admin) |
| 422 Validation error | All forms | Inline field errors: text-alert below field. First error section auto-expands and scrolls into view. Section header shows alert dot. | Fix field, error clears on valid input |
| 400 Prompt injection blocked | PA/TA prompt editors | Inline error below textarea: "Blocked pattern detected: {pattern}. This prompt contains content that violates security policy." text-alert | Admin revises prompt. PA override: "I confirm this is intentional" + audit log (SEC-05) |
| 500 Server error | All surfaces | Toast notification: "Something went wrong. Please try again." + [Retry] in context | Toast auto-dismisses 6s, [Retry] attempts same operation |
| Network error | All surfaces | Toast: "Connection lost. Changes will save when connection restores." | Auto-retry on reconnect (react-query built-in) |
| Credential test failure | TA Deploy Wizard S4 | Inline: alert X + error message from server (e.g., "Invalid API key" or "Connection refused") | Admin corrects credentials, retries |
| Credential test timeout | TA Deploy Wizard S4 | Inline: warn clock + "Connection test timed out (15s). You can skip and test later." [Skip Test] option | [Skip] saves credentials without validation, daily async health check runs |
| MCP connection failure | TA MCP Tools | Inline error in registration form: "Could not connect to {endpoint}. Verify the URL and authentication." | Admin corrects URL/auth, retries |
| A2A card fetch failure | A2A Registration | Inline error: "Could not fetch agent card from {url}. Verify the URL is accessible." | Admin corrects URL, retries |
| Regex validation error | Guardrail editor | Inline below regex textarea: "Invalid regex: {detail}" text-alert | Admin fixes regex pattern |

---

## 7. Interaction Flows

### Adopt Platform Skill (TA)

1. TA navigates to `/admin/skills`, Platform Skills tab
2. Browse cards or search by name/category
3. Click [Adopt] on skill card
4. `SkillAdoptionPanel` opens: version pin toggle, preview prompt (read-only), tool dependency check
5. If unpinned: "This skill will auto-update when the platform publishes new versions"
6. If pinned: version selector dropdown shows available versions
7. [Adopt Skill] -> POST `/admin/skills/adopt`
8. Skill appears in "My Skills" tab with "Adopted" badge
9. Skill now available for attachment in Custom Agent Studio

### Publish Platform Skill (PA)

1. PA navigates to `/platform/skills`, clicks [+ New Skill]
2. `PlatformSkillEditor` opens (800px slide-in)
3. Author: name, description, category, execution pattern selection
4. If Pure Prompt: write prompt template with `{{input.field}}` variables
5. If Tool-Composing: select tools from catalog + write orchestration prompt
6. If Sequential Pipeline: add ordered steps (tool call or prompt per step)
7. Define input/output JSON Schema
8. Set LLM config (model, temperature, max_tokens)
9. Set plan gate
10. Optional: mark as mandatory
11. [Save Draft] -> persists draft
12. [Publish] -> version label + changelog required -> published to platform library
13. Skill appears in TA Platform Skills catalog

### Delete / Unpublish Platform Skill (PA)

1. PA clicks skill row, opens editor
2. If skill has adopted tenants: deprecate (not hard delete). Show adoption count.
3. Deprecation: status changes, TA sees "Deprecated" badge, existing adoptions continue working
4. If no adoptions: [Delete] available with confirmation modal

### Register Tenant MCP Server (TA)

1. TA navigates to `/admin/mcp-tools`, clicks [+ Register MCP Server]
2. `MCPServerRegistrationForm` opens (560px slide-in)
3. Enter: name, endpoint URL, auth type, credentials (if needed)
4. [Test Connection] -> 15s timeout
5. On success: platform reads tool list from MCP endpoint, displays for confirmation
6. Review discovered tools (name, description, input/output)
7. [Register] -> saves server + tools
8. Server appears in MCP Tools table
9. Tools from this server now available in Custom Agent Studio tool picker

### Register A2A Agent (TA)

1. TA navigates to `/admin/a2a-agents`, clicks [+ Register A2A Agent]
2. `A2ARegistrationForm` opens (560px slide-in)
3. Enter agent card URL
4. On URL blur: fetch card, render `A2ACardPreview` (operations, capabilities, auth)
5. Optional overrides: name, description
6. Configure guardrails overlay: topic restrictions, PII masking
7. [Register] -> wraps external agent, appears in tenant agent catalog
8. Orchestrator includes this agent in routing decisions

### Version Pin / Unpin Skill (TA)

1. TA navigates to "My Skills" tab, clicks adopted skill
2. `SkillAdoptionPanel` opens showing current state
3. Toggle version pin on -> version selector appears, defaults to current version
4. Select specific version -> PATCH to pin
5. Platform publishes new version -> TA skill stays at pinned version, "Update available" badge appears
6. TA unpins -> skill auto-updates to latest

### Promote Tenant Skill to Platform (PA)

1. PA navigates to tenant skill (visibility depends on PA admin tools, not yet designed)
2. Reviews tenant-authored skill
3. [Promote to Platform Library] -> creates copy in platform scope
4. Original tenant skill remains owned by tenant
5. Promoted skill: new ID, PA-owned, version starts at 1.0.0

---

## 8. Responsive Requirements

| Surface | Desktop (>= 1024px) | Tablet (768-1024px) | Mobile (< 768px) |
|---------|---------------------|---------------------|-------------------|
| PA Template Studio (full-page overlay) | Full layout. Content 860px centered. Sidebar collapses to 60px. Test harness 400px. | Content fills width. Test harness reduces to 320px. Accordion sections full-width. Footer actions may wrap to 2 rows. | Desktop-recommended banner shown. Content renders with reduced padding. Regex textarea and variable table may need horizontal scroll. |
| TA Deploy Wizard (640px modal) | 640px centered modal with backdrop | 640px modal, may touch edges with 16px margin | Full-screen modal (100vw, rounded-none) |
| TA Custom Agent Panel (560px slide-in) | 560px from right, content visible behind | 560px, may overlap most of content | Full-screen slide-in (100vw) |
| TA Skills Page (table + cards) | Card grid 3-across or table | Card grid 2-across or table with horizontal scroll | Card grid 1-column, stacked |
| TA MCP Tools (table) | Full table | Table with horizontal scroll | Card list instead of table |
| A2A Registration (560px slide-in) | 560px from right | 560px, overlaps content | Full-screen |
| PA Skills Library (table) | Full table | Table with horizontal scroll | Desktop-recommended banner |
| PA MCP Builder (640px wizard) | 640px centered modal | Same behavior as deploy wizard | Full-screen modal |
| PA Tool Catalog (table) | Full table | Table with horizontal scroll | Desktop-recommended banner |

---

## 9. Ambiguities and Conflicts

### AMB-01: Plan 15 vs. Conceptual Model Scope

**Issue**: Plan 15 covers 4 phases (PA Template Studio, TA Deploy Wizard, TA Custom Agent Studio, PA Performance Dashboard). The conceptual model (doc 04) defines 6 additional surfaces (Tenant Skills, Tenant MCP Tools, TA A2A Registration, PA Skills Library, PA MCP Builder, PA A2A Registry) that have no implementation plan, no UX design spec, and no user flow documentation.

**Impact**: 14 new components and 5 new hooks have no plan coverage.

**Recommendation**: Create Plan 15 Phase 5A (Skills + Tools) and Phase 5B (A2A) with UX design specs and user flows before implementation.

### AMB-02: Full-Page Overlay vs. 800px Slide-In

**Issue**: UX spec (doc 02) specifies full-page overlay for PA Template Studio. Plan 15 specifies 800px slide-in panel. The plan's Design Decisions Log acknowledges this: "800px slide-in panel chosen over full-page overlay."

**Resolution**: Follow Plan 15 (800px slide-in). The UX spec Section 2.1 was the initial proposal; the plan represents the final decision. However, the 7-section accordion with 4 tabs in an 800px panel is extremely dense. Flag for UX validation during implementation.

### AMB-03: Compliance Tab Existence

**Issue**: UX spec defines 4 tabs (Edit, Compliance, Instances, History). Plan 15 also lists 4 tabs (Edit, Test, Instances, Version History) -- replacing Compliance with Test. The plan's Design Decisions Log says "Compliance tab deferred."

**Resolution**: Follow Plan 15. Phase 1 ships with 4 tabs: Edit, Test, Instances, Version History. Compliance tab is a future addition (requires violation log aggregation endpoint).

### AMB-04: Test Harness as Tab vs. Slide-In

**Issue**: Plan 15 lists `TestHarnessTab` as a tab within the panel. UX spec Section 3.14 defines it as a 400px slide-in from right triggered by footer [Test] button.

**Resolution**: Use the slide-in approach per UX spec. This keeps the test harness accessible without losing the edit view. The "tab" in Plan 15 refers to it being part of the panel's UX (as opposed to the old separate `TestHarnessPanel`), not a literal tab-bar tab.

### AMB-05: Skill Editor for Sequential Pipeline

**Issue**: The conceptual model defines 3 execution patterns (Pure Prompt, Tool-Composing, Sequential Pipeline). The pipeline pattern requires an ordered step editor (`PipelineStepEditor`) with drag-to-reorder. No UX spec exists for this component.

**Recommendation**: Design UX spec for `PipelineStepEditor` before Phase 5A implementation. This is the most complex skill authoring pattern.

### AMB-06: Skill Attachment to Agents

**Issue**: The conceptual model describes skills being "attached" to agents, but the Plan 15 template authoring form has no skill attachment section. The `AgentTemplate` TypeScript type has no `attached_skills` field.

**Impact**: Without skill attachment UI, Skill-Augmented Agents (Type 2) and Tool-Augmented Agents (Type 3) cannot be fully configured.

**Recommendation**: Add a "Skills" section (S5.5) to the PA Template Studio between KB/Tools and Guardrails. This should be a checkbox list of platform skills (similar to tool assignment) with mandatory skills shown as locked. This is a Plan 15 Phase 1 addition.

### AMB-07: Tenant Custom Agent Skill Attachment

**Issue**: The conceptual model says custom agents can use "platform + tenant skills," but the Custom Agent Studio (Phase 3) has no skill attachment section in Plan 15 or the UX spec.

**Recommendation**: Add a skill picker section to `CustomAgentPanel` showing adopted platform skills + tenant-authored skills.

---

## 10. TypeScript Type Additions Required

### New Types (to be added to hooks or a shared types file)

```typescript
// Skill types
interface Skill {
  id: string;
  name: string;
  description: string;
  category: string;
  version: string; // semver
  changelog: string;
  input_schema: JSONSchema;
  output_schema: JSONSchema;
  prompt_template: string;
  execution_pattern: "prompt" | "tool_composing" | "sequential_pipeline";
  tool_dependencies: ToolRef[];
  pipeline_steps?: PipelineStep[];
  invocation_mode: "llm_invoked" | "pipeline";
  pipeline_trigger?: string;
  llm_config: {
    model?: string;
    temperature: number;
    max_tokens: number;
  };
  plan_required: "starter" | "professional" | "enterprise" | null;
  scope: "platform" | string; // tenant_id
  mandatory: boolean;
  status: "draft" | "published" | "deprecated";
  adoption_count?: number; // PA only
}

interface SkillRef {
  skill_id: string;
  version_pin?: string; // null = latest
}

interface ToolRef {
  tool_id: string;
  name: string;
}

interface PipelineStep {
  order: number;
  type: "tool_call" | "llm_prompt";
  tool_id?: string;
  prompt?: string;
  input_mapping: Record<string, string>; // field -> "previous_step.output.field"
}

// MCP Server types
interface MCPServer {
  id: string;
  name: string;
  endpoint_url: string;
  auth_type: "none" | "api_key" | "oauth2";
  health_status: "healthy" | "degraded" | "unavailable";
  last_ping: string | null;
  tool_count: number;
  tools: MCPTool[];
  created_at: string;
  scope: "platform" | string; // tenant_id
}

interface MCPTool {
  id: string;
  name: string;
  description: string;
  input_schema: JSONSchema;
  output_schema: JSONSchema;
  server_id: string;
}

// A2A types
interface A2AAgent {
  id: string;
  name: string;
  description: string;
  card_url: string;
  imported_card: A2ACard;
  status: "active" | "inactive" | "error";
  guardrails_overlay: GuardrailConfig;
  scope: "platform" | string; // tenant_id
  plan_required?: string; // platform scope only
  operations_count: number;
  last_invoked: string | null;
  created_at: string;
}

interface A2ACard {
  name: string;
  description: string;
  operations: A2AOperation[];
  authentication: { type: string; required: boolean };
  capabilities: string[];
}

interface A2AOperation {
  name: string;
  description: string;
  input_schema: JSONSchema;
  output_schema: JSONSchema;
}

// Extended AgentTemplate (Plan 15 additions)
interface AgentTemplateExtended extends AgentTemplateAdmin {
  icon: string;
  capabilities_list: string[]; // informational
  cannot_do: string[];
  recommended_kb_categories: string[];
  attached_skills: SkillRef[];
  attached_tools: ToolRef[];
  credential_schema: CredentialField[];
  a2a_enabled: boolean;
  a2a_interface?: A2AInterface;
  version_label: string; // semver string
}

interface CredentialField {
  key: string;
  label: string;
  type: "string" | "secret";
  sensitive: boolean;
}

interface A2AInterface {
  operations: A2AOperation[];
  auth_required: boolean;
  caller_requires_plan?: string;
}

// Credential test result
interface CredentialTestResult {
  status: "idle" | "testing" | "passed" | "failed";
  message?: string;
  connected_identity?: string; // e.g., "acme@bloomberg"
}

// Version types
interface TemplateVersion {
  id: string;
  template_id: string;
  version_label: string;
  change_type: "initial" | "patch" | "minor" | "major";
  changelog: string;
  published_by: string;
  published_at: string;
}

// Performance types
interface TemplatePerformance {
  template_id: string;
  adoption_count: number;
  active_instances: number;
  avg_satisfaction_pct: number;
  avg_confidence_score: number;
  guardrail_violation_count: number;
  guardrail_violation_rate_pct: number;
  queries_trailing_30d: number;
  period: string;
}
```

---

## 11. Total Component Count Summary

| Phase | New Components | New Hooks | Deprecated | Extended |
|-------|---------------|-----------|------------|----------|
| Phase 1 (PA Template Studio) | 16 | 3 (useTemplateVersion, useTemplateTest, extend useAgentTemplatesAdmin) | 3 | 2 |
| Phase 2 (TA Deploy Wizard) | 7 | 1 (useAgentDeploy) | 0 | 3 |
| Phase 3 (TA Custom Agent) | 2 | 1 (useCustomAgent) | 0 | 0 |
| Phase 4 (PA Performance) | 1 | 1 (useTemplatePerformance) | 0 | 0 |
| Phase 5A (Skills + Tools) | 12 | 4 (useSkills, useSkillAdoption, useMCPServers, useMCPIntegrationBuilder) | 0 | 0 |
| Phase 5B (A2A) | 5 | 1 (useA2ARegistration) | 0 | 0 |
| **TOTAL** | **43** | **11** | **3** | **5** |

---

## 12. Sidebar Navigation Additions

### Tenant Admin Sidebar (Settings section)

Current items: Dashboard, Documents, Users, Agents, Glossary (under Workspace)

**Add**:
- **Skills** (after Agents) -> `/admin/skills` (Phase 5A)
- **MCP Tools** (after Skills) -> `/admin/mcp-tools` (Phase 5A)
- **A2A Agents** (after MCP Tools) -> `/admin/a2a-agents` (Phase 5B)

### Platform Admin Sidebar (Intelligence section)

Current items: LLM Profiles, Agent Templates, Analytics, Tool Catalog

**Add**:
- **Skills Library** (after Agent Templates) -> `/platform/skills` (Phase 5A)
- **A2A Registry** (after Tool Catalog) -> `/platform/a2a-registry` (Phase 5B)

---

**Document Version**: 1.0
**Last Updated**: 2026-03-21
