# TODO-18: Agent Studio Phase 1 — TA Custom Agent Studio

**Status**: ACTIVE
**Priority**: MEDIUM
**Estimated Effort**: 3 days
**Phase**: Phase 1 — Tenant Admin Surfaces

---

## Description

Tenant admins can build their own agents from scratch using platform skills, their own tenant skills, and available tools. Custom agents are not derived from platform templates — they are fully tenant-owned. They are NOT versioned (v1 design decision). They DO go through SystemPromptValidator for injection protection.

This todo delivers the `CustomAgentStudioPanel` — a 560px slide-in panel with 5 accordion sections — and the backend verification/wiring needed to make custom agent create/update/test/publish work correctly.

The 4 studio endpoints already exist in `routes.py`:
- `POST /admin/agents/studio/create`
- `PUT /admin/agents/studio/{id}`
- `POST /admin/agents/studio/{id}/test`
- `POST /admin/agents/studio/{id}/publish`

This todo verifies and fixes these endpoints where necessary, then builds the frontend.

---

## Acceptance Criteria

- [ ] TA clicks [+ New Agent] in workspace agents page and gets a 560px slide-in panel
- [ ] Section 1 — Identity: name, description, category, icon picker (6 options: HR, Finance, Legal, IT, Search, Custom)
- [ ] Section 2 — System Prompt + Knowledge: DM Mono prompt textarea with `{{variable}}` detection (literal variables, not typed schema like PA templates); KB multi-select (tenant KBs only)
- [ ] Section 3 — Skills + Tools: multi-select list of skills available to tenant (platform adopted + tenant-authored published); multi-select list of tools (platform + tenant MCP); no credential schema declaration in custom agents (v1 restriction)
- [ ] Section 4 — Access Control: same three-mode radio + role/user multi-select as deploy wizard Step 3
- [ ] Section 5 — Guardrails: fully editable (tenant owns guardrails for their custom agents); blocked topics chip input, confidence threshold slider, max response length input; no rule regex editor in v1 (reserved for PA)
- [ ] [Save Draft] always available; auto-saves on section blur after 2s
- [ ] [Test Agent] opens inline test pane within panel (not a separate drawer): query input, run button, output display
- [ ] Test runs write audit log with `mode='test'`, `test_as_user_id` = requesting admin's own ID
- [ ] [Publish] transitions draft to active; agent appears in end-user chat selector
- [ ] Custom agents are NOT versioned — no version history section
- [ ] Custom agents have no credential schema section (v1 restriction)
- [ ] Editing a published custom agent: changes saved immediately to active state (no draft/publish cycle for edits)
- [ ] Custom agents appear in agent list page alongside deployed template instances
- [ ] SystemPromptValidator runs on every save

---

## Backend Changes

### Verify and Fix Studio Endpoints

File: `src/backend/app/modules/agents/routes.py`

**POST /admin/agents/studio/create:**
- Verify KB bindings in `capabilities` JSONB are persisted (not silently dropped)
- Accept `attached_skills: list[str]` and `attached_tools: list[str]` in request body
- Validate all skill IDs are accessible to the tenant (platform-adopted or tenant-authored published)
- Validate all tool IDs are accessible to the tenant (platform-scoped or tenant-scoped matching tenant_id)
- Run `SystemPromptValidator` on `system_prompt` field before INSERT
- Set `template_type = 'rag'` if no skills/tools; `'skill_augmented'` if skills only; `'tool_augmented'` if tools present

**PUT /admin/agents/studio/{id}:**
- Wire `SystemPromptValidator` — reject request if system_prompt triggers violation
- Return `ETag` header based on `updated_at`; accept `If-Match` header; return 409 on conflict
- Validate tenant_id in WHERE clause (existing `_AGENT_UPDATE_SQL` pattern must be followed)

**POST /admin/agents/studio/{id}/test:**
- Verify audit log is written with `mode: "test"` and `test_as_user_id = requesting_user.id`
- Execute query against draft configuration (use chat orchestration pipeline in test mode)
- Return: `{ response, confidence, sources, skill_invocations, tool_calls, guardrail_events, latency_ms }`

**POST /admin/agents/studio/{id}/publish:**
- INSERT into `agent_access_control` based on `access_rules` from request
- Transition `status: draft → active`
- Publish Redis cache invalidation

### Extended Request Schema

```python
class CreateCustomAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    icon: Optional[str] = Field(None)
    system_prompt: str = Field(..., max_length=3000)
    kb_ids: list[str] = Field(default_factory=list)
    attached_skills: list[str] = Field(default_factory=list)  # skill IDs
    attached_tools: list[str] = Field(default_factory=list)   # tool IDs
    guardrails: Optional[GuardrailsSchema] = None
    access_rules: Optional[dict] = None  # used on publish

class UpdateCustomAgentRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    system_prompt: Optional[str] = Field(None, max_length=3000)
    kb_ids: Optional[list[str]] = None
    attached_skills: Optional[list[str]] = None
    attached_tools: Optional[list[str]] = None
    guardrails: Optional[GuardrailsSchema] = None
```

---

## Frontend Changes

### Entry Point

Add [+ New Agent] button to the workspace agents management page. Opens `CustomAgentStudioPanel` in slide-in mode.

Also add [Edit] action to existing custom agent rows in the agent list — opens panel with agent data pre-loaded.

### New Components

#### `CustomAgentStudioPanel.tsx`

Location: `src/web/components/agents/CustomAgentStudioPanel.tsx`

- Slides in from right, 560px wide, `bg-bg-surface`
- Header: "New Agent" / agent name + status badge + × close
- Auto-save indicator: "Saved" / "Saving..." in `text-text-faint text-label-nav` below header
- 5 accordion sections (all open by default for new agents):

**Section 1 — Identity**
Reuses `IconPicker` (6-option grid from TODO-20 or built here first):
- IconPicker: 6 40x40 buttons (HR, Finance, Legal, IT, Search, Custom icons)
- Name input: `bg-bg-elevated rounded-control`
- Description textarea: 3 lines, max 1000 chars
- Category input: free text with suggestions

**Section 2 — System Prompt + Knowledge**
- `SystemPromptEditor` (lite version — no variable schema table; literal `{{variable}}` tokens visible but not structured): DM Mono textarea, 3000-char counter (warn 2400, alert 2800)
- KB selector: checkbox list fetched from `GET /admin/kb-sources`; search input; selected count badge

**Section 2b — Skills** (between System Prompt and KB Bindings — insert here)
- Skill picker: renders `SkillPickerPanel` (shared component — see below)
- Browse all skills available to the tenant: platform skills the tenant has adopted + tenant-authored skills with `status='published'`
- Search/filter by skill category (category chips across top of panel)
- Each skill listed with: name, execution pattern badge, invocation mode indicator
- Toggle (checkbox) to add/remove skill from this agent
- Per-skill: clicking skill name opens a read-only detail popover showing description, tool dependencies, and execution pattern
- If skill has `invocation_mode='pipeline'`, show an "Override trigger" link — expands inline to allow setting a custom `pipeline_trigger` value for this agent-skill pairing (stored in `agent_template_skills.invocation_override` JSONB)
- Selected skills shown as chip list below the picker heading; × on chip removes skill

**Section 3 — Capabilities**
- Skills subsection: checkbox list; split into "Platform Skills (Adopted)" and "My Skills (Published)"; each item shows skill name + execution pattern badge; search input
- Tools subsection: checkbox list; split into "Platform Tools" and "My Tools"; shows tool name + executor badge; empty state if no tools available with link to Tools page (TODO-17)

**Section 4 — Access Control**
Reuse `WizardStep3Access` component (or extract shared `AccessControlEditor` component):
- Workspace / Role / User radio
- Role/user multi-select
- Rate limit input

**Section 5 — Guardrails**
- Blocked topics: chip input (type topic, press Enter to add, × to remove)
- Confidence threshold: horizontal slider 0.0–1.0, value label `text-data-value`
- Max response length: number input, 100–10000 range, helper text

**Test Pane (inline, within panel)**
Collapses/expands via [Test Agent] button in footer:
- Query input: single-line with [Run] button
- Results section (below input): response text, confidence bar, sources count, skill invocations list, tool calls list, guardrail events, latency `DM Mono`
- Results appear in place without navigation

**Panel Footer**
- [Save Draft] (ghost) — always active
- [Test Agent] (ghost with icon) — toggles inline test pane
- [Publish] (accent) — disabled if required fields missing; shows tooltip listing missing fields

---

## Shared Component: SkillPickerPanel

Since the skill picker is needed in both TODO-18 (custom agent studio) and TODO-20 (PA template studio), build it as a shared component here first.

File: `src/web/components/shared/SkillPickerPanel.tsx`

Props:
```typescript
interface SkillPickerPanelProps {
  tenantId: string
  selectedSkillIds: string[]
  onChange: (selectedIds: string[], invocationOverrides: Record<string, string>) => void
  readOnly?: boolean  // PA template studio uses read-only view of skill selections
}
```

Rendering:
- Category filter chips row (All, Summary, Extraction, Analysis, Research, Custom) — chips use outlined-neutral style per design system
- Search input (filters skill name and description)
- Skill list: each row has checkbox, name, execution pattern badge (`DM Mono text-[11px]`), invocation mode indicator
- Selected count badge above list: "N skills selected" in `text-label-nav`
- Selected skills chip summary below the list heading: each chip shows skill name + × remove button
- Empty state (no skills adopted/authored): "No skills available. Go to Skills to adopt platform skills." with link

Invocation override UI:
- Only shown for `invocation_mode='pipeline'` skills
- Collapsed by default with "Override trigger" link in `text-text-faint text-[12px]`
- When expanded: text input pre-filled with skill's default `pipeline_trigger`; placeholder `e.g. response_length > 500`; saved into `invocationOverrides` map

---

## Shared Component: IconPicker

Since IconPicker is needed in both TODO-18 (custom agents) and TODO-20 (PA template studio), build it here first.

File: `src/web/components/shared/IconPicker.tsx`

- 6-option grid of 40x40 clickable buttons
- Icons: HR (person+document), Finance (chart), Legal (scales), IT (computer), Search (magnifier), Custom (sparkle/star)
- Selected state: `border-2 border-accent bg-accent-dim`
- Default state: `border border-border bg-bg-elevated`
- Props: `value: string`, `onChange: (icon: string) => void`

---

## Dependencies

- TODO-13 (DB schema) — agent_cards extended columns
- TODO-16 (Skills) — tenant skills available in selector
- TODO-17 (MCP Tools) — tenant tools available in selector

---

## Risk Assessment

- **HIGH**: SystemPromptValidator must be wired before Phase 1 ships — tenant prompts are highest injection risk surface
- **MEDIUM**: Auto-save can overwrite in-progress edits — debounce 2s, show "Saving..." only when network call is in flight
- **LOW**: Skill/tool lists may be empty for new tenants who haven't adopted anything — provide clear empty states with links to adopt/register

---

## Testing Requirements

- [ ] Unit test: `POST /admin/agents/studio/create` persists KB bindings, skills, tools in capabilities JSONB
- [ ] Unit test: `POST /admin/agents/studio/{id}/test` writes audit log with `mode='test'`
- [ ] Unit test: `PUT /admin/agents/studio/{id}` returns 422 when system_prompt triggers validator
- [ ] Unit test: `POST /admin/agents/studio/{id}/publish` inserts access_control row
- [ ] Unit test: attached skills validated against tenant's adopted/authored skills (403 for unowned skills)
- [ ] Integration test: create → update → test → publish cycle end-to-end
- [ ] Integration test: published custom agent appears in `GET /agents` for authorized users
- [ ] E2E test: TA creates custom agent with Summarization skill, publishes, end user sees agent in chat

---

## Definition of Done

- [ ] CustomAgentStudioPanel renders all 5 sections (plus Section 2b Skills)
- [ ] Inline test pane works
- [ ] All 4 studio endpoints verified/fixed
- [ ] SystemPromptValidator wired on create and update
- [ ] Audit log written on test
- [ ] Access control inserted on publish
- [ ] Cache invalidation fires on publish
- [ ] Custom agent appears in end-user chat selector after publish
- [ ] `SkillPickerPanel` shared component built and used in Section 2b
- [ ] Invocation override saves correctly to `agent_template_skills.invocation_override`
- [ ] All acceptance criteria met

---

## Gap Patches Applied

### Gap 4: Section 2b — Skills picker in Custom Agent Studio

The original `CustomAgentStudioPanel` spec had skills in Section 3 (Capabilities) as a simple checkbox list without invocation override support or category filtering. This has been corrected above.

Key changes from original spec:
1. Skills are promoted to their own section (2b) between System Prompt and KB Bindings — this matches the logical authoring flow: system prompt defines agent persona → skills define what it can do → KBs define what it knows
2. The skill picker uses a dedicated `SkillPickerPanel` shared component (see above) rather than a bare checkbox list
3. Per-skill invocation override for pipeline-mode skills is now supported
4. Section 3 (Capabilities) retains the Tools subsection but the Skills subsection is removed from it (moved to 2b)

**Backend changes required by Gap 4:**

The `CreateCustomAgentRequest` and `UpdateCustomAgentRequest` schemas must be extended to carry invocation overrides:

```python
class SkillAttachment(BaseModel):
    skill_id: str
    invocation_override: Optional[str] = None  # custom pipeline_trigger, or None to use skill default

class CreateCustomAgentRequest(BaseModel):
    ...
    attached_skills: list[SkillAttachment] = Field(default_factory=list)  # was: list[str]
    attached_tools: list[str] = Field(default_factory=list)
    ...
```

When persisting, write `invocation_override` into the `agent_template_skills.invocation_override` JSONB column: `{"pipeline_trigger": "<override value>"}`.

**Add to Testing Requirements:**
- [ ] Unit test: `POST /admin/agents/studio/create` with `SkillAttachment(skill_id=..., invocation_override="response_length > 200")` persists override in `agent_template_skills.invocation_override`
- [ ] Unit test: `GET /admin/agents/studio/{id}` returns `attached_skills` as `SkillAttachment` list with `invocation_override` populated
- [ ] E2E test: TA opens custom agent studio; Section 2b shows adopted skills; TA selects a pipeline skill and overrides trigger; publishes agent; override is active in chat
