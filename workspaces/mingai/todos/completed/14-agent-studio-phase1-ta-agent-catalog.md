# TODO-14: Agent Studio Phase 1 — TA Agent Library Page

**Status**: ACTIVE
**Priority**: HIGH
**Estimated Effort**: 2 days
**Phase**: Phase 1 — Tenant Admin Surfaces

---

## Description

Tenant admins need a dedicated page to browse all available platform agent templates, filter by category, understand capabilities and requirements (plan gate, auth mode, skills, tools), and initiate deployment. This replaces the flat agent list on the existing `ta-panel-agents` surface with a proper catalog card grid experience.

Existing `GET /agents/templates` endpoint returns seed + DB templates. It needs extension to return the new template fields from TODO-13 schema (template_type, llm_policy, kb_policy, attached_skills, attached_tools, plan_required, auth_mode).

---

## Acceptance Criteria

- [ ] TA navigates to Workspace > Agents > Agent Library tab and sees a card grid of all published platform templates
- [ ] Each card shows: icon (40x40), name, template_type badge, category, one-line description, skill count, tool count, auth_mode indicator, plan gate badge (if gated)
- [ ] Plan-gated templates show locked state (lock icon, plan name) — [Deploy] button disabled with upgrade tooltip
- [ ] Tenant's current plan is read from their JWT/tenant config to determine gating
- [ ] Search by name/description (client-side filter, no debounce needed — catalog is small)
- [ ] Category filter chips: All, HR, IT, Procurement, Finance, Legal, Custom + any category returned by API
- [ ] "Already deployed" indicator on templates the tenant has deployed (check against `admin/agents` list)
- [ ] Clicking [Deploy] opens `AgentDeployWizard` (TODO-15) with this template pre-selected
- [ ] Clicking a card (not [Deploy] button) opens a template detail slide-in (280px right panel) showing full description, all 7 dimension summaries, version, changelog
- [ ] Template detail panel shows "N instances deployed by your workspace" count
- [ ] Empty state: "No templates match your filters" with reset button
- [ ] Loading skeleton: 6 placeholder cards while fetching
- [ ] Backend: `GET /agents/templates` returns all new fields from v049 migration

---

## Backend Changes

### Extend GET /agents/templates

File: `src/backend/app/modules/agents/routes.py`

Add to response per template:
- `template_type`: from `agent_cards.template_type` (default `rag` for existing seed templates)
- `llm_policy`: from `agent_cards.llm_policy`
- `kb_policy`: from `agent_cards.kb_policy`
- `attached_skills`: array of `{skill_id, skill_name, version}` — JOIN skills table to resolve names
- `attached_tools`: array of `{tool_id, tool_name}` — JOIN tools table to resolve names
- `plan_required`: from `agent_cards.plan_required`
- `auth_mode`: from `agent_cards.auth_mode` (existing column)
- `a2a_interface`: from `agent_cards.a2a_interface`
- `instance_count`: subquery count of deployed instances for requesting tenant (not platform-wide)

For seed templates (hardcoded), return safe defaults: `template_type='rag'`, empty skills/tools arrays, `plan_required=null`, `auth_mode='none'`.

### New endpoint: GET /agents/templates/{template_id}

Returns full template detail for single template. Same fields as list plus:
- `variable_schema`: array of `{name, type, description, required}` parsed from system_prompt `{{variable}}` tokens
- `guardrails`: full guardrails object
- `changelog`: last 5 changelog entries from `agent_template_versions`

---

## Frontend Changes

### New Page

File: `src/web/app/settings/agent-templates/page.tsx` — extend or replace with proper TA library.

Note: There is already a stub page at this path. Evaluate whether it serves TA or PA — if PA, create a new TA-specific page route. Preferred: add `AgentLibraryPage` as a tab within the TA agents section.

### New Components

#### `AgentLibraryPage.tsx`

Location: `src/web/app/settings/agents/elements/AgentLibraryPage.tsx`

- Grid layout: 3 columns at 1280px+, 2 columns at 900-1279px
- Card gap: 16px
- Filter chips row above grid (All, HR, IT, Procurement, Finance, Legal, Custom)
- Search input with magnifier icon, `bg-bg-elevated`, `rounded-control`
- "N templates available" count in `text-text-faint text-label-nav`

#### `AgentTemplateCard.tsx`

Location: `src/web/app/settings/agents/elements/AgentTemplateCard.tsx`

```
Card layout (rounded-card bg-bg-surface border border-border p-5):

[icon 40x40]  [name text-section-heading]    [plan badge if gated]
              [category + type badge row]

[description text-body-default text-text-muted — 2 lines max, truncate]

[skills chip: N skills]  [tools chip: N tools]  [auth chip if auth_mode != none]

[separator]

[Already deployed indicator OR [Deploy] button]
```

- Icon: render from template `icon` field or fallback to category emoji/icon map
- `template_type` badge: RAG (bg-bg-elevated), Skill-Augmented (accent-dim), Tool-Augmented (warn-dim), Credentialed (alert-dim), A2A (purple-ish — use bg-elevated + border)
- Plan gate: lock icon + `text-text-faint` with tooltip "Requires {plan} plan"
- [Deploy] button: `bg-accent text-black rounded-control text-body-default px-4 py-2`
- "Deployed" badge: accent-dim background, checkmark, `text-accent`

#### `AgentTemplateDetailPanel.tsx`

Location: `src/web/app/settings/agents/elements/AgentTemplateDetailPanel.tsx`

- Slides in from right, 360px wide (standard TA detail panel width)
- Header: icon + name + type badge + × close
- Sections (accordion, default open):
  - Identity: category, tags, description
  - LLM Policy: required model (if any), tenant override permission
  - Knowledge: kb_policy.ownership mode, recommended categories
  - Capabilities: skills list, tools list, auth mode
  - A2A Interface: enabled/disabled, operations list
  - Guardrails: summary of active rules
  - Version: current version, changelog last entry
- Footer: [Deploy this template] button (full width, accent)

### New Hook

File: `src/web/hooks/useAgentTemplates.ts`

```typescript
// Queries
useAgentTemplates(filters?: { category?: string; search?: string })
  → { templates: AgentTemplate[], isLoading, error }

useAgentTemplate(templateId: string)
  → { template: AgentTemplateDetail, isLoading, error }

// Types
interface AgentTemplate {
  id: string
  name: string
  description: string
  icon: string
  category: string
  template_type: 'rag' | 'skill_augmented' | 'tool_augmented' | 'credentialed' | 'registered_a2a'
  attached_skills: SkillRef[]
  attached_tools: ToolRef[]
  plan_required: string | null
  auth_mode: string
  a2a_interface: A2AInterface
  instance_count: number
  version: string
  status: string
}
```

Cache key: `['agent-templates', filters]`. Stale time: 5 minutes (catalog changes infrequently).

---

## Dependencies

- TODO-13 (DB schema) — `attached_skills`, `attached_tools` fields require skills and tools tables

---

## Testing Requirements

- [ ] Unit test: `GET /agents/templates` returns `template_type`, `attached_skills`, `attached_tools` for all templates
- [ ] Unit test: `GET /agents/templates/{id}` returns `variable_schema` and `changelog`
- [ ] Unit test: plan-gated template not deployable by tenant on lower plan (403 on deploy attempt)
- [ ] Integration test: TA can load catalog, filter by category, search by name
- [ ] E2E test: TA sees 4 seed templates in catalog, clicks Deploy on HR template, deploy wizard opens

---

## Definition of Done

- [ ] AgentLibraryPage renders card grid for all published platform templates
- [ ] Category filter and search work correctly
- [ ] Plan-gated templates show locked state
- [ ] Template detail panel shows all 7 dimension summaries
- [ ] [Deploy] opens wizard from TODO-15
- [ ] Backend returns all new fields without breaking existing API consumers
- [ ] All acceptance criteria met
