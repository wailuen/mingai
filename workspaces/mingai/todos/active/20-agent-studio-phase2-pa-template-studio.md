# TODO-20: Agent Studio Phase 2 — PA Full Template Authoring Studio

**Status**: ACTIVE
**Priority**: HIGH (Phase 2 — depends on Phase 1 foundation)
**Estimated Effort**: 5 days
**Phase**: Phase 2 — Platform Admin Authoring Studio

---

## Description

Platform admins need a complete template authoring surface covering all 7 configuration dimensions. This replaces the existing `TemplateAuthoringForm.tsx` (which covers only 3 dimensions) with `TemplateStudioPanel.tsx` — an 800px slide-in panel with 4 tabs (Edit, Test, Instances, Version History) and 7 progressive-disclosure sections.

This is the PA counterpart to the TA surfaces shipped in Phase 1. After this todo, PAs can author structurally complete templates (Types 1-4) and register external A2A agents (Type 5). All 7 dimensions are configurable. The pre-publish checklist ensures completeness.

---

## Acceptance Criteria

- [ ] PA opens template studio via [+ New Template] or clicking any existing template row
- [ ] 800px slide-in panel opens without layout disruption; sidebar collapses to 60px when panel is open
- [ ] Panel has 4 tabs: Edit, Test, Instances, Version History
- [ ] Edit tab: 7 progressive-disclosure sections
- [ ] Section visibility: default state (RAG) shows sections 1, 2, 6, 7; sections 3, 4, 5 show collapsed one-line summary; expand when auth_mode changes to non-none
- [ ] SystemPromptValidator runs server-side on every save; client shows validation error inline if rejected
- [ ] `{{variable}}` tokens auto-detected from system prompt and synced to variable schema table
- [ ] Character counter: warn at 1600, alert at 1800, blocks save at 2000
- [ ] Guardrail rule editor: regex validation on blur, ReDoS detection enforced server-side
- [ ] Credential schema editor: add/remove/edit rows; sensitive toggle; key auto-generated from label
- [ ] LLM Policy section: required model dropdown, allowed providers, tenant override toggle, temperature/max_tokens defaults
- [ ] KB Policy section: ownership mode radio, recommended categories chip input, required KB IDs (platform_managed mode only)
- [ ] Publish flow: pre-publish checklist (inline), required version label, required changelog, breaking-change auto-detection
- [ ] Version History tab: vertical timeline with version label, date, change type badge, changelog, publisher
- [ ] Test tab: embedded test harness (query input, response, confidence, sources, KB queries, guardrail events, latency)
- [ ] Instances tab: list tenant deployments with tenant name (not data), version pinned, status, last-active date
- [ ] Optimistic concurrency: 409 returned when two admins edit simultaneously
- [ ] **FIRST ACTION — delete before building**: `TemplateAuthoringForm.tsx`, `VersionHistoryDrawer.tsx`, `TestHarnessPanel.tsx` removed from `src/web/app/(platform)/platform/agent-templates/elements/` before any new component is written. No code should reference these files after deletion.
- [ ] Agent Templates table is empty (seed data already cleared 2026-03-22 — confirm 0 rows before starting)

---

## Backend Changes

### Alembic Migration v045: agent_templates Extension

**Note**: This migration may already exist from pre-existing work (check `src/backend/app/db/migrations/versions/`). If `v045_agent_templates_required_credentials.py` exists and adds `required_credentials`, `auth_mode`, `plan_required`, verify it is already applied. If not, create it.

File: `src/backend/app/db/migrations/versions/v045_agent_templates_required_credentials.py`

```sql
ALTER TABLE agent_cards
    ADD COLUMN IF NOT EXISTS required_credentials JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS auth_mode VARCHAR(32) NOT NULL DEFAULT 'none'
        CHECK (auth_mode IN ('none', 'tenant_credentials', 'platform_credentials')),
    ADD COLUMN IF NOT EXISTS plan_required VARCHAR(32)
        CHECK (plan_required IN ('starter', 'professional', 'enterprise'));
```

This overlaps with TODO-13's v049. Coordinate: v045 adds auth/plan columns (legacy plan); v049 adds template_type and new capability columns. Both must apply cleanly.

### SystemPromptValidator

File: `src/backend/app/modules/agents/prompt_validator.py`

(If created in TODO-16 for skills, extend; otherwise create here.)

Full implementation:

- Regex-based blocked pattern detection (OWASP LLM Top 10 prompt injection corpus):
  - "ignore (all |previous |your )?(instructions|directives|system|prompt)"
  - "disregard (your|the) system"
  - "act as (DAN|DAN-|jailbroken|an? (unfiltered|unrestricted|uncensored))"
  - "you are now (a|an|DAN)"
  - Unicode homoglyph patterns (Cyrillic а vs Latin a in system-prompt-bypass patterns)
  - "respond to (me |the user )?as if"
  - "pretend (that |you are )"
- 2000-char limit enforcement (hard block)
- ReDoS detection: regex patterns in guardrail rules evaluated with 50ms timeout (use `asyncio.wait_for` wrapping re.compile + test match)
- Returns `ValidationResult(valid: bool, reason: str | None, blocked_patterns: list[str])`
- PA override: if PA explicitly sends `override_validation: true` with `override_reason: str`, allow save but write audit log entry ("Prompt validation override by {admin_id}: {reason}")

### Version Bump Logic

File: `src/backend/app/modules/agents/versioning.py`

```python
def detect_breaking_changes(old: dict, new: dict) -> ChangeType:
    """
    Compare two template snapshots.
    Returns: 'patch' | 'minor' | 'major'
    Rules:
    - major: required_credentials changed, auth_mode changed
    - minor: system_prompt changed, guardrails changed, llm_policy changed
    - patch: name, description, icon, tags, recommended_categories changed
    """

def bump_version(current: str, change_type: str) -> str:
    """Semver increment: major.minor.patch"""
```

### Extended Platform Admin Template API

File: `src/backend/app/modules/agents/routes.py` or new `platform_templates_routes.py`

```python
POST /platform/agent-templates
    # Accept all 7 dimensions
    # Run SystemPromptValidator
    # Insert with status='draft'

PUT  /platform/agent-templates/{id}
    # Accept all 7 dimensions
    # Run SystemPromptValidator + ReDoS check on guardrail regexes
    # ETag/If-Match concurrency (If-Match must match updated_at)
    # Return 409 on stale ETag

POST /platform/agent-templates/{id}/publish
    # Required: version_label (semver), changelog (non-empty)
    # Run pre-publish validation: all required sections filled
    # detect_breaking_changes → determine change_type
    # INSERT into agent_template_versions (snapshot of template)
    # UPDATE status = 'published', version = version_label

GET  /platform/agent-templates/{id}/versions
    # Return all versions from agent_template_versions ordered by published_at DESC

GET  /platform/agent-templates/{id}/instances
    # Return tenant instances pinned to this template
    # ONLY: tenant_name (not ID), pinned_version, status, last_active_at
    # NEVER return: system_prompt contents, KB IDs, access rules, credentials
```

### Security: Tenant Data Sovereignty in Instances Tab

The instances endpoint must NOT expose:

- `tenant_id` (return tenant name only, from tenant settings)
- System prompt of deployed instance
- KB bindings or access rules
- Credentials

---

## Frontend Changes

### Deprecated Components to Remove

After `TemplateStudioPanel` is complete and all references updated:

- `src/web/app/(platform)/platform/agent-templates/elements/TemplateAuthoringForm.tsx` — DELETE
- `src/web/app/(platform)/platform/agent-templates/elements/VersionHistoryDrawer.tsx` — DELETE
- `src/web/app/(platform)/platform/agent-templates/elements/TestHarnessPanel.tsx` — DELETE

Do not delete until new components are wired in.

### New Components

#### `TemplateStudioPanel.tsx`

Location: `src/web/app/(platform)/platform/agent-templates/elements/TemplateStudioPanel.tsx`

- 800px slide-in from right (wider than standard 560px TA panels)
- At 1280px viewport: sidebar collapses to 60px icon-only when panel open
- 4 tabs: Edit | Test | Instances | Version History
- Active tab indicator: 2px accent underline (same as design system tab pattern)

**Edit Tab — 7 Progressive Sections**

Section 1 — Identity:

- `IconPicker` (reuse from TODO-18)
- Name, Description, Category, Tags (chip input)
- Agent Type badge display (auto-detected from config)

Section 2 — System Prompt + Variables:

- `SystemPromptEditor` component: DM Mono textarea, 2000-char counter (warn 1600 alert 1800), `{{variable}}` detection with yellow highlight
- Variable Schema table (below prompt): auto-synced from detected tokens; columns: Variable Name, Type (string/number/boolean), Required toggle, Description; rows editable inline
- "Auto-detect variables" button
- Validation error display (inline red banner below editor when validator rejects)

Section 3 — LLM Policy (collapsed by default for RAG agents):

- Required Model dropdown: None (any), model list from `GET /platform/llm-library`
- Allowed Providers checkboxes: OpenAI, Azure OpenAI, Anthropic, Google
- Tenant Override toggle: "Tenants can change model within policy"
- Defaults: temperature slider (0.0–2.0), max_tokens numeric input

Section 4 — Knowledge:

- KB Ownership mode radio: "Tenant-managed", "Platform-managed", "Dedicated"
- Recommended Categories: chip input (type + Enter)
- Required KB IDs: shown only when platform_managed; text input list

Section 5 — Capabilities (collapsed by default for RAG agents):

- Skills: checkbox list from `GET /skills` (platform published); shows skill name + version + execution_pattern badge
- Tools: checkbox list from `GET /tools` (platform-scoped); shows tool name + credential_source badge
- `CredentialSchemaEditor`: table of credential fields; columns: Key (auto-gen from label), Label, Type, Sensitive toggle; add/remove rows; shown when tools with tenant_managed credentials are selected or auth_mode is non-none

Section 6 — A2A Interface:

- A2A Enabled toggle
- Operations table: add/remove operation rows; each row: operation name, description, input schema (JSON), output schema (JSON)
- Auth Required toggle
- Caller Requires Plan dropdown

Section 7 — Guardrails:

- Rule cards: add/remove; each rule: name, rule_type dropdown (keyword_block / regex_match / content_filter), pattern textarea with syntax validation, violation_action radio (block/redact/warn), user message textarea
- Confidence threshold slider
- Citation mode dropdown (inline / footnote / none)
- Max response length input
- PII masking toggle

Progressive disclosure logic:

- Default: Sections 1, 2, 6, 7 open; Sections 3, 4, 5 show collapsed one-line summaries
- When `auth_mode` changes from none: Section 3 expands (LLM policy), Section 5 expands (capabilities + credentials)
- Transition: 220ms ease

Section visibility summary cards:

- "LLM Policy: Any model (tenant override enabled)" — clickable to expand
- "Knowledge: Tenant-managed (3 recommended categories)" — clickable to expand
- "Capabilities: No skills, no tools" — clickable to expand

#### `SystemPromptEditor.tsx`

Location: `src/web/components/shared/SystemPromptEditor.tsx`

(Shared between PA template studio and TA custom agent studio — move from PA-only location.)

- DM Mono textarea
- `{{variable}}` token highlighting: background `rgba(79,255,176,0.12)`, `rounded-badge`
- Character counter: green below 1600, warn-yellow 1600-1800, alert-orange 1800+
- Validation error: red banner showing `ValidationResult.reason` + `blocked_patterns`

#### `CredentialSchemaEditor.tsx`

Location: `src/web/app/(platform)/platform/agent-templates/elements/CredentialSchemaEditor.tsx`

- Inline editable table
- Columns: Key (auto-generated from label, `DM Mono`, read-only after creation), Label (editable), Type (string/secret dropdown), Sensitive (toggle)
- Add row: button at bottom; new row auto-generates key from label (spaces → underscores, lowercase)
- Remove row: trash icon, confirmation tooltip

#### `GuardrailsEditor.tsx`

Location: `src/web/components/shared/GuardrailsEditor.tsx`

(Shared between PA and TA — used in TODO-18 Section 5 and here.)

- Rule cards: `bg-bg-elevated rounded-card p-4 mb-3`
- Rule type dropdown, pattern textarea with regex syntax validation on blur
- Violation action: radio group (Block / Redact / Warn) inline
- Add rule button at bottom

#### `PlanCapabilitiesEditor.tsx`

Location: `src/web/app/(platform)/platform/agent-templates/elements/PlanCapabilitiesEditor.tsx`

- Plan dropdown: None / Starter / Professional / Enterprise
- Capabilities chip input: type capability name, press Enter
- Cannot-do chip input: alert-dim styled chips (red-tinted)

#### `PublishFlow.tsx`

Location: `src/web/app/(platform)/platform/agent-templates/elements/PublishFlow.tsx`

- Pre-publish checklist (inline expansion, not modal):
  - Identity complete (name + description)
  - System prompt passes validation
  - Guardrails configured
  - Breaking changes reviewed
- Version label input: semver string (validated pattern)
- Changelog textarea: required, min 20 chars
- Breaking change warning: auto-detected change type shown as badge (Major / Minor / Patch)
- [Confirm Publish] button (accent)

#### `VersionHistoryTab.tsx`

Location: `src/web/app/(platform)/platform/agent-templates/elements/VersionHistoryTab.tsx`

- Vertical timeline
- Each entry: version number (`DM Mono`), date, change_type badge, changelog text, publisher avatar + name
- Change type badge colors: Initial (bg-elevated), Patch (accent-dim), Minor (warn-dim), Major (alert-dim)

#### `TestHarnessTab.tsx`

Location: `src/web/app/(platform)/platform/agent-templates/elements/TestHarnessTab.tsx`

- Query input (full width)
- [Run Test] button
- Variable fill section: render inputs for each `variable_schema` entry
- Results: response text, confidence bar, sources list, KB queries timeline, guardrail events (if any), latency in `DM Mono`

#### `InstancesTab.tsx`

Location: `src/web/app/(platform)/platform/agent-templates/elements/InstancesTab.tsx`

- Table: Tenant Name, Version, Status, Last Active
- Tenant name shown, NOT tenant ID (data sovereignty)
- Status badges: Active, Paused, Outdated (when newer version available)
- "Outdated" instances: accent warning "Using v1.0.0 — v1.1.0 available"

### Extended Hooks

File: `src/web/hooks/useAgentTemplatesAdmin.ts`

Extend mutation payloads: `auth_mode`, `required_credentials`, `plan_required`, `capabilities`, `cannot_do`, `recommended_kb_categories`, `llm_policy`, `kb_policy`, `attached_skills`, `attached_tools`, `a2a_interface`

Add ETag support: send `If-Match` header on PUT requests; handle 409 responses with "modified by another admin" error message.

File: `src/web/hooks/useTemplateVersion.ts` (NEW)

```typescript
publishTemplate(id, versionLabel, changelog) → mutation
useVersionHistory(id) → { versions, isLoading }
useBreakingChangeDetection(old, new) → { changeType }
```

---

## Dependencies

- TODO-13 (DB schema) — v049/v050 migrations for new template columns and versions table
- TODO-16 (Skills) — skills list in capabilities section
- TODO-17 (Tools) — tools list in capabilities section
- TODO-18 (Custom Agent) — IconPicker, SystemPromptEditor, GuardrailsEditor components built there first

---

## Risk Assessment

- **HIGH**: Progressive disclosure hides credential/auth sections — pre-publish checklist must explicitly flag if tools assigned but auth_mode = none
- **HIGH**: ReDoS in guardrail regex patterns — 50ms server-side timeout enforcement is critical; test with known catastrophic patterns (e.g., `(a+)+`)
- **MEDIUM**: 800px panel on 1280px viewport — sidebar must collapse to icon-only; test at 1280px minimum

---

## Testing Requirements

- [ ] Unit test: SystemPromptValidator blocks all patterns from OWASP LLM Top 10 test corpus
- [ ] Unit test: ReDoS pattern detection rejects `(a+)+` within 50ms
- [ ] Unit test: `detect_breaking_changes` classifies changes correctly (auth_mode change = major)
- [ ] Unit test: `bump_version` increments semver correctly for all three change types
- [ ] Unit test: Instances endpoint does NOT expose tenant_id, KB IDs, or system prompt contents
- [ ] Unit test: 409 returned when ETag does not match
- [ ] Integration test: PA creates template → all 7 dimensions saved → publish → version history record created
- [ ] Integration test: progressive disclosure triggers correctly when auth_mode changes
- [ ] E2E test: PA creates new template with skills + credentials; TA sees it in catalog with correct capability badges

---

## Definition of Done

- [ ] TemplateStudioPanel renders 4 tabs with all 7 sections
- [ ] Progressive disclosure works with 220ms transitions
- [ ] All new sub-components built and wired
- [ ] Deprecated components removed after migration
- [ ] SystemPromptValidator and ReDoS detection wired server-side
- [ ] Publish flow with semver, changelog, and breaking-change detection
- [ ] Version history tab populates from agent_template_versions
- [ ] Instances tab respects tenant data sovereignty
- [ ] Optimistic concurrency (ETag/409) working
- [ ] All acceptance criteria met
