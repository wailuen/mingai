# TODO-16: Agent Studio Phase 1 — TA Skills Catalog + Authoring

**Status**: ACTIVE
**Priority**: MEDIUM
**Estimated Effort**: 4 days
**Phase**: Phase 1 — Tenant Admin Surfaces

---

## Description

Tenant admins need two capabilities:
1. Browse the platform skills library and adopt skills into their tenant catalog
2. Author their own private skills (prompt-based or tool-composing) using the same editor patterns as PA

This todo delivers the full TA skills surface: the Tenant Skills page (browse + adopt platform skills, view tenant-authored skills), and the Skill Authoring panel (create/edit private tenant skills). Backend routes for skills CRUD, skill adoption, and skill versioning are also created here.

Skills authored by tenants are private by default and never visible to other tenants. PAs can later promote tenant skills to the platform library (handled in TODO-21).

---

## Acceptance Criteria

- [ ] TA navigates to Workspace > Skills and sees two tabs: "Platform Skills" and "My Skills"
- [ ] Platform Skills tab: card list of all published platform skills with name, category, description, execution pattern badge, invocation mode, plan gate indicator, and "Adopted" status if already in tenant catalog
- [ ] TA can adopt a platform skill by clicking [Adopt] — adds to tenant catalog with latest version pinning by default
- [ ] TA can pin to a specific skill version (dropdown with available versions after adoption)
- [ ] Mandatory skills shown with lock icon — cannot be unadopted; visible in "My Skills" as locked entries
- [ ] "My Skills" tab: list of adopted platform skills (showing referenced version) + tenant-authored skills (showing full editable record)
- [ ] TA can author a new skill via [+ New Skill] button — opens `TenantSkillAuthoringPanel`
- [ ] Skill authoring panel: Name, Description, Category (free text), Execution Pattern (prompt / tool_composing — sequential_pipeline not offered to tenants in v1), Invocation Mode, pipeline_trigger (shown when pipeline mode)
- [ ] Prompt template editor: DM Mono textarea, `{{input.field_name}}` variable detection, 3000-char limit
- [ ] Input/Output schema editor: JSON Schema builder — add fields with name, type, required toggle
- [ ] Tool selector (tool_composing only): checkbox list of tools available to tenant (platform tools + tenant's own MCP tools)
- [ ] Tenant skill prompt template passes through SystemPromptValidator on every save
- [ ] TA can test a skill: enter sample input values, see output from LLM
- [ ] TA can publish a skill (draft → published), making it available for attachment to their custom agents
- [ ] Published tenant skills appear in tool selector when building custom agents (TODO-18)
- [ ] Tenant skill delete: only drafts deletable; published skills can only be deprecated

---

## Backend Changes

### New Module: skills_routes.py

File: `src/backend/app/modules/agents/skills_routes.py`

All routes registered on `admin_router` (require `require_tenant_admin`) or a new `skills_router`.

```python
# Platform skills — PA-authored, read by any tenant
GET  /skills                          # List platform published skills + tenant's adopted skills
GET  /skills/{skill_id}               # Skill detail + versions
POST /skills/{skill_id}/adopt         # Adopt platform skill into tenant catalog
DELETE /skills/{skill_id}/adopt       # Remove adoption (not allowed for mandatory skills)
PUT  /skills/{skill_id}/pin           # Pin/unpin to specific version

# Tenant skills — private CRUD
GET  /admin/skills                    # List tenant-authored skills
POST /admin/skills                    # Create new tenant skill (draft)
GET  /admin/skills/{skill_id}         # Get tenant skill detail
PUT  /admin/skills/{skill_id}         # Update tenant skill (runs SystemPromptValidator)
POST /admin/skills/{skill_id}/publish # Publish draft (draft → published)
DELETE /admin/skills/{skill_id}       # Delete (drafts only; 409 if published)
POST /admin/skills/{skill_id}/test    # Test skill with sample input values
```

### Request Schemas

```python
class CreateSkillRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    execution_pattern: Literal["prompt", "tool_composing"] = "prompt"
    invocation_mode: Literal["llm_invoked", "pipeline"] = "llm_invoked"
    pipeline_trigger: Optional[str] = None
    prompt_template: str = Field(..., max_length=3000)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    tool_dependencies: list[str] = Field(default_factory=list)  # tool IDs
    llm_config: dict = Field(default_factory=lambda: {"temperature": 0.3, "max_tokens": 2000})

class AdoptSkillRequest(BaseModel):
    pinned_version: Optional[str] = None  # None = always latest
```

### SystemPromptValidator Integration

Import and call `SystemPromptValidator` (to be built in TODO-20, but anticipated here). For Phase 1: implement a basic version in `src/backend/app/modules/agents/prompt_validator.py` with:
- Pattern detection for jailbreak phrases: "ignore previous instructions", "disregard your system prompt", "act as DAN", "you are now", common Unicode bypass patterns
- 3000-char limit for skill prompts (higher than template prompts since skills are less exposed)
- Return `ValidationResult(valid: bool, reason: str | None, blocked_patterns: list[str])`
- Called on `POST /admin/skills` and `PUT /admin/skills/{id}`

### Skill Test Endpoint

`POST /admin/skills/{skill_id}/test`

Input: `{ "input_values": dict }`

Process:
1. Load skill record
2. Interpolate `input_values` into `prompt_template` (replace `{{input.field_name}}` tokens)
3. Resolve tool_dependencies — load tool records
4. If `execution_pattern = 'tool_composing'`: run tool-calling loop with LLM (use agent LLM config or platform default)
5. If `execution_pattern = 'prompt'`: single LLM call
6. Write audit log: `mode='skill_test'`, skill_id, tenant_id (not user input content)
7. Return: `{ output: any, latency_ms: int, tokens_used: int, tool_calls: list }`

---

## Frontend Changes

### New Page

File: `src/web/app/settings/skills/page.tsx`

Two-tab layout: "Platform Skills" | "My Skills"

Register in sidebar navigation under Workspace section.

### New Components

#### `PlatformSkillsTab.tsx`

Location: `src/web/app/settings/skills/elements/PlatformSkillsTab.tsx`

- Card list (not grid — skills need description space)
- Card: name + execution_pattern badge + invocation_mode badge + plan badge + category chip
- Description: 2 lines max
- Tool dependencies: chip list if tool_composing
- Right side: [Adopt] button or "Adopted ✓" badge + version pin dropdown
- Mandatory skills: lock icon, cannot be unadopted, shown with "Platform Required" badge
- Filter: All, Adopted, Not Adopted, Mandatory | Category filter chips | Search input

#### `TenantSkillsTab.tsx`

Location: `src/web/app/settings/skills/elements/TenantSkillsTab.tsx`

- Two sub-sections: "Adopted Platform Skills" (compact list, read-only name/version/pin controls) and "My Skills" (full card list with edit/delete/publish actions)
- [+ New Skill] button in top-right, opens `TenantSkillAuthoringPanel`
- Status badges: Draft (bg-elevated), Published (accent-dim), Deprecated (alert-dim)

#### `TenantSkillAuthoringPanel.tsx`

Location: `src/web/app/settings/skills/elements/TenantSkillAuthoringPanel.tsx`

- Slides in from right, 560px wide
- Header: "New Skill" or skill name + status badge + × close
- 5 accordion sections:

**Section 1 — Identity**
- Name input, Description textarea, Category input (free text with autocomplete from existing categories)

**Section 2 — Execution**
- Execution Pattern radio: "Pure Prompt" / "Tool-Composing"
- Invocation Mode radio: "LLM decides when to call" / "Auto-trigger at pipeline stage"
- Pipeline Trigger input (shown when pipeline mode): text field, placeholder "e.g. response_length > 500"

**Section 3 — Prompt Template**
- `SkillPromptEditor` component: DM Mono textarea, `{{input.field_name}}` highlighting (like SystemPromptEditor but for skills), 3000-char counter (warn at 2400, alert at 2800)
- Variable detection: auto-detect `{{input.*}}` tokens and offer to add to Input Schema

**Section 4 — Input / Output Schema**
- `SchemaBuilder` component: table of fields; each row: field name, type (string/number/boolean/array/object), required toggle, description; Add row / remove row
- Two sub-sections: Input Schema and Output Schema
- "Auto-detect from prompt" button for Input Schema

**Section 5 — Tools (shown only when execution_pattern = tool_composing)**
- Checkbox list of available tools (platform tools available to tenant's plan + tenant's own MCP tools)
- Shows tool name, description, executor type badge

**Footer**
- [Save Draft] (always available), [Test Skill] (opens test drawer), [Publish] (only when draft is valid)

#### `SkillTestDrawer.tsx`

Location: `src/web/app/settings/skills/elements/SkillTestDrawer.tsx`

- 400px drawer from right
- Dynamically renders input form from skill's `input_schema`
- [Run Test] button
- Output section: rendered output value, token count, latency, tool calls timeline (if tool_composing)

### New Hooks

File: `src/web/hooks/useSkills.ts`

```typescript
// Platform skills
usePlatformSkills(filters?)  → { skills, isLoading }
useSkillAdoptions()           → { adoptedSkillIds: Set<string>, isLoading }
adoptSkill(skillId, pinnedVersion?)  → mutation
unadoptSkill(skillId)                → mutation
pinSkillVersion(skillId, version)    → mutation

// Tenant skills
useTenantSkills()             → { skills, isLoading }
createSkill(data)             → mutation
updateSkill(id, data)         → mutation
publishSkill(id)              → mutation
deleteSkill(id)               → mutation
testSkill(id, inputValues)    → mutation → TestResult
```

---

## Dependencies

- TODO-13 (DB schema) — `skills`, `tenant_skill_adoptions` tables
- TODO-17 (MCP Tools) — tools available in tool selector for tool_composing skills

---

## Risk Assessment

- **HIGH**: SystemPromptValidator for skill prompts — tenant injection risk is higher than PA templates; ensure validator is wired before publishing Phase 1
- **MEDIUM**: JSON Schema builder UX — complex for non-technical users; provide examples and clear field descriptions
- **LOW**: Version pinning UX — most tenants won't use it; hide behind "Advanced" toggle initially

---

## Testing Requirements

- [ ] Unit test: `POST /admin/skills` with injection pattern returns 422 with `blocked_patterns` in response
- [ ] Unit test: `POST /admin/skills/{id}/publish` transitions status from draft → published
- [ ] Unit test: DELETE published skill returns 409
- [ ] Unit test: mandatory platform skill adoption cannot be removed (409)
- [ ] Integration test: tenant-authored skill with `scope = tenant_id` not visible to other tenants
- [ ] Integration test: adopted platform skill with pinned version stays pinned after platform skill update
- [ ] E2E test: TA creates skill, publishes, verifies it appears in custom agent skill selector

---

## Definition of Done

- [ ] Platform Skills tab renders all 11 seeded skills
- [ ] Adopt/unadopt works; mandatory skills locked
- [ ] Tenant skill CRUD fully functional
- [ ] SystemPromptValidator wired to all save paths
- [ ] Skill test endpoint works end-to-end
- [ ] Published tenant skills available in custom agent builder (TODO-18)
- [ ] All acceptance criteria met

---

## Gap Patches Applied

### Gap 3: Skill Executor runtime module

Add the following backend module to the implementation scope:

**New module: `src/backend/app/modules/skills/executor.py`**

The `SkillExecutor` dispatches skill calls based on `execution_pattern` and manages token budgeting:

```python
class SkillExecutor:
    async def execute(
        self,
        skill_id: str,
        input_data: dict,
        context: ExecutionContext
    ) -> SkillResult:
        skill = await self.skills.get(skill_id)
        if skill.execution_pattern == "prompt":
            return await self._execute_prompt_skill(skill, input_data, context)
        elif skill.execution_pattern == "tool_composing":
            return await self._execute_tool_composing_skill(skill, input_data, context)
        elif skill.execution_pattern == "sequential_pipeline":
            return await self._run_pipeline(skill, input_data, context)
```

**Token budget enforcement (non-negotiable):**
- Each skill invocation has a configurable max token budget; default 2000 tokens
- Track cumulative token usage per query across all skill invocations in `ExecutionContext`
- When `context.tokens_used + estimated_skill_tokens > context.token_budget`: return `SkillError(code='budget_exceeded')` immediately — do NOT continue the call chain
- Fail-closed on budget: partial results are not returned; the skill is skipped
- `max_tool_calls_per_skill = 5` is a hard limit for tool-composing skills; exceed this and the skill returns `SkillError(code='tool_call_limit_exceeded')` with partial results discarded

**Invocation mode behaviour:**
- `llm_invoked`: Skill is registered as a function definition in the agent's LLM system prompt / function calling schema. When the LLM decides to call the skill, `SkillExecutor.execute()` is invoked and the result is injected back into the function call response message.
- `pipeline`: `SkillExecutor` evaluates `pipeline_trigger` after the LLM response is generated. If the trigger condition evaluates to true (e.g., `response_length > 500`), the skill runs as a post-processor. Pipeline trigger expressions support: `response_length`, `confidence_score`, `contains_keyword(word)`.

**`ExecutionContext` data class:**
```python
@dataclass
class ExecutionContext:
    tenant_id: str
    agent_id: str
    conversation_id: str
    token_budget: int = 2000
    tokens_used: int = 0
    tool_calls_made: int = 0
    llm_response: str = ""  # populated before pipeline trigger evaluation
    confidence_score: float = 0.0
```

**Wire into `POST /admin/skills/{skill_id}/test`:**
- Instantiate `ExecutionContext` with `token_budget` from skill's `llm_config.max_tokens` (or 2000 default)
- After test run, return `tokens_used` and `budget_remaining` in response

**Add to Testing Requirements:**
- [ ] Unit test: `SkillExecutor` fails closed when token budget is exceeded — returns `SkillError`, no LLM call made
- [ ] Unit test: tool-composing skill aborts after 5 tool calls regardless of task completion state
- [ ] Unit test: `llm_invoked` skill registered as function definition in agent LLM call
- [ ] Unit test: `pipeline` skill with `response_length > 500` trigger — fires when response is long, skips when response is short

---

### Gap 5: Plan-gate validation on skill adoption

Add the following to the `POST /skills/{skill_id}/adopt` endpoint implementation:

**Plan-gate checks at adoption time:**

```python
async def adopt_skill(skill_id: str, tenant_id: str, pinned_version: str | None):
    skill = await db.get(skill_id)
    tenant = await db.get_tenant(tenant_id)

    # 1. Check skill's own plan gate
    if skill.plan_required and not tenant_meets_plan(tenant.plan, skill.plan_required):
        raise HTTPException(403, detail=f"Skill requires plan '{skill.plan_required}'")

    # 2. Check each tool dependency's plan gate
    tool_deps = await db.get_skill_tool_dependencies(skill_id)
    for dep in tool_deps:
        tool = await db.get_tool(dep.tool_id)
        if tool.plan_required and not tenant_meets_plan(tenant.plan, tool.plan_required):
            raise HTTPException(
                403,
                detail=f"Skill depends on tool '{tool.name}' which requires plan '{tool.plan_required}'"
            )

    # 3. Proceed with adoption
    await db.insert_tenant_skill(tenant_id, skill_id, pinned_version)
```

**Plan-gate check at skill EXECUTION time:**

The `SkillExecutor.execute()` method must re-check plan gates before running:

```python
async def execute(self, skill_id, input_data, context):
    skill = await self.skills.get(skill_id)
    tenant = await self.tenants.get(context.tenant_id)

    # Re-validate plan gate (tenant may have downgraded since adoption)
    if skill.plan_required and not tenant_meets_plan(tenant.plan, skill.plan_required):
        return SkillError(code='plan_gate_violation',
                          detail=f"Tenant plan '{tenant.plan}' does not meet skill requirement '{skill.plan_required}'")
    ...
```

This double-check (adoption + execution) prevents plan downgrades from silently unlocking gated capabilities.

**`tenant_meets_plan()` helper:**
```python
PLAN_ORDER = {"starter": 0, "professional": 1, "enterprise": 2}

def tenant_meets_plan(tenant_plan: str, required_plan: str) -> bool:
    return PLAN_ORDER.get(tenant_plan, -1) >= PLAN_ORDER.get(required_plan, 999)
```

**Add to Testing Requirements:**
- [ ] Unit test: adopt skill with `plan_required='enterprise'` as `starter` tenant returns 403
- [ ] Unit test: adopt skill whose tool dependency has `plan_required='professional'` as `starter` tenant returns 403 with tool name in error detail
- [ ] Unit test: `SkillExecutor` returns `SkillError(code='plan_gate_violation')` when tenant downgrades plan after adoption — skill does not execute
- [ ] Integration test: adoption succeeds when tenant plan meets both skill and all tool dependency plan gates
