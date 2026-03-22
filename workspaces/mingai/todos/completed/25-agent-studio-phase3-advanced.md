# TODO-25: Agent Studio Phase 3 — Mandatory Skills Enforcement, Orchestrator, Performance Dashboard

**Status**: ACTIVE
**Priority**: LOW (Phase 3 — depends on Phases 1 and 2 complete)
**Estimated Effort**: 5 days
**Phase**: Phase 3 — Advanced Capabilities

---

## Description

Phase 3 delivers three advanced capabilities that depend on Phases 1 and 2 being operational:

1. **Mandatory Skills Enforcement** — skills marked mandatory (TODO-21) must actually run as pipeline post-processors on every agent response. This requires changes to the chat orchestration pipeline.

2. **Orchestrator Routing** — the system orchestrator agent auto-provisioned per tenant that routes queries to the correct agent. Currently routing is manual (user selects agent). This todo makes it automatic: orchestrator reads deployed agent A2A cards, routes queries via lightweight LLM, falls back to general RAG.

3. **Performance Dashboard** — cross-tenant aggregated metrics per platform template: adoption count, satisfaction %, confidence score, guardrail violation rate. PA uses this to understand template effectiveness.

---

## Acceptance Criteria

### Mandatory Skills Enforcement

- [ ] Skills marked `mandatory=true` in the skills table execute as post-processors on every agent response, regardless of tenant configuration
- [ ] Mandatory skills run AFTER the main agent response is generated, not before
- [ ] Mandatory skills cannot be disabled by tenant admins (TA skills panel shows them locked)
- [ ] Mandatory skill execution is logged in the conversation audit log with `skill_id`, `invocation_type='mandatory'`, `latency_ms`
- [ ] If a mandatory skill fails: agent response is returned without skill output; failure logged; does not block response
- [ ] Mandatory skill execution does NOT increase user-visible response latency by more than 500ms (skills run in parallel where possible)
- [ ] PA can view per-skill mandatory execution failure rate in the skills library

### Orchestrator Routing

- [ ] Every tenant has an orchestrator system agent auto-provisioned at tenant creation
- [ ] Orchestrator reads the A2A cards of all deployed agents in the tenant (status=active)
- [ ] Incoming queries routed to best-matching agent based on description + A2A card operations
- [ ] Routing uses a lightweight LLM (GPT-5 Mini class) with structured output: `{ agent_id, confidence, reasoning }`
- [ ] If confidence < threshold (platform setting, default 0.7): fall back to general RAG (no specific agent)
- [ ] Routing decision logged: agent_id selected, confidence, fallback flag
- [ ] End-user chat in "Auto" mode uses orchestrator routing (existing "mode selector" UI — Auto is already a mode option)
- [ ] Orchestrator routing cache: cache routing decisions per (query_hash, tenant_agent_list_hash) for 5 minutes; invalidate on agent deploy/undeploy
- [ ] Two global platform settings in PA Platform > Settings: routing_model, confidence_threshold
- [ ] No per-tenant orchestrator configuration surface — it is a system agent

### Performance Dashboard (PA)

- [ ] PA Template Studio `TemplateStudioPanel` gains a 5th tab: Performance (between Instances and Version History)
- [ ] Performance tab shows: Adoption Count, Active Instances, Avg Satisfaction %, Avg Confidence Score, Guardrail Violation Count, Queries (trailing 30d)
- [ ] All data aggregated across all tenant instances (no per-tenant breakdown)
- [ ] Empty state when template has zero instances: "No deployments yet."
- [ ] Backend: `GET /platform/agent-templates/{id}/performance` aggregation endpoint
- [ ] Data sources: conversation metadata (satisfaction ratings, confidence scores, guardrail violation flags) JOINed with agent instances pinned to this template

---

## Backend Changes

### Mandatory Skills Enforcement in Chat Orchestration

File: `src/backend/app/modules/chat/routes.py` (or `orchestrator.py` if it exists)

Add `MandatorySkillExecutor` as a post-processing stage after main agent response:

```python
class MandatorySkillExecutor:
    """
    Stage: runs after main LLM response is generated.
    Fetches all platform skills where mandatory=True and status='published'.
    For each: executes skill against the agent response content.
    Collects outputs; merges into final response per skill output_schema.
    Runs skills in parallel where invocation_mode allows.
    Hard timeout: 500ms total for all mandatory skills combined.
    On timeout/failure: returns original response; logs failure.
    Never blocks or delays the SSE stream more than 500ms.
    """

    async def execute(
        self,
        agent_response: str,
        conversation_context: dict,
        tenant_id: str,
        agent_id: str
    ) -> MandatorySkillResult:
        ...
```

**Redis cache for mandatory skills list:**
```
Key: mandatory_skills:platform
TTL: 5 minutes
Invalidate on: skill mandate/unmandate
```

Fetch list once per request (not per message) via cache.

### Orchestrator System Agent

File: `src/backend/app/modules/agents/orchestrator.py` (new)

```python
class TenantOrchestrator:
    """
    System agent per tenant. Auto-provisioned at tenant creation.
    No TA configuration surface.

    Core method: route(query, tenant_id, user_id) -> RoutingDecision

    1. Load active agent list from cache (agent_id, name, description, a2a_operations)
    2. Build routing prompt: query + agent capability summaries
    3. Call lightweight LLM with structured output schema
    4. Check confidence vs threshold
    5. Return RoutingDecision(agent_id | None, confidence, fallback)
    """

    ROUTING_PROMPT = """
    You are a query router for an enterprise AI assistant platform.
    Available agents and their capabilities:
    {agent_summaries}

    User query: {query}

    Return JSON: {"agent_id": "...", "confidence": 0.0-1.0, "reasoning": "..."}
    If no agent is clearly appropriate, set agent_id to null.
    """
```

**Routing cache:**
```
Key: routing:{tenant_id}:{query_hash}:{agent_list_hash}
TTL: 5 minutes
Invalidate on: agent deploy/undeploy/status change
```

**Tenant provisioning hook:**
File: `src/backend/app/modules/admin/workspace.py` (modify tenant creation flow)
- After tenant creation: provision orchestrator record in `agent_cards` with `is_orchestrator=TRUE`, `scope=system`
- Add column `is_orchestrator BOOLEAN NOT NULL DEFAULT FALSE` to `agent_cards` (migration v056)

**Auto mode integration:**
File: `src/backend/app/modules/chat/routes.py`
- When `mode = 'auto'` (already exists in chat request): invoke `TenantOrchestrator.route()`
- If routing returns `agent_id`: use that agent's config (system_prompt, KB bindings, guardrails)
- If routing returns `None` (fallback): use general RAG with no agent context

### Platform Orchestrator Settings

New endpoint: `GET/PUT /platform/settings/orchestrator`
```json
{
  "routing_model": "gpt-4o-mini",
  "confidence_threshold": 0.7
}
```

Stored in platform settings table (existing or new, depending on what exists).

### Performance Aggregation Endpoint

File: `src/backend/app/modules/agents/routes.py`

```python
GET /platform/agent-templates/{id}/performance
```

Response:
```json
{
  "template_id": "...",
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

Data aggregation:
```sql
SELECT
    COUNT(DISTINCT ac.id) FILTER (WHERE ac.status = 'active') AS active_instances,
    COUNT(DISTINCT ac.tenant_id) AS adoption_count,
    AVG(cm.satisfaction_rating) * 100 AS avg_satisfaction_pct,
    AVG(cm.confidence_score) AS avg_confidence_score,
    COUNT(ge.id) FILTER (WHERE ge.was_triggered = TRUE) AS guardrail_violation_count,
    COUNT(cm.id) FILTER (WHERE cm.created_at > NOW() - INTERVAL '30 days') AS queries_trailing_30d
FROM agent_cards ac
JOIN conversation_metadata cm ON cm.agent_id = ac.id
LEFT JOIN guardrail_events ge ON ge.conversation_id = cm.conversation_id
WHERE ac.template_id = :template_id
  AND cm.created_at > NOW() - INTERVAL '30 days'
```

---

## Frontend Changes

### Performance Tab in TemplateStudioPanel

Extend `TemplateStudioPanel.tsx` (TODO-20) to add 5th tab.

#### `TemplatePerformanceTab.tsx`

Location: `src/web/app/(platform)/platform/agent-templates/elements/TemplatePerformanceTab.tsx`

- 4 KPI cards in a 2x2 grid:
  - Adoption Count — number in `DM Mono text-page-title`; if ≥10 use `text-accent`; if <3 `text-warn`
  - Avg Satisfaction % — thresholds: ≥80 `text-accent`, 60-79 `text-warn`, <60 `text-alert`
  - Avg Confidence Score — same thresholds (≥0.80, 0.60-0.79, <0.60)
  - Guardrail Violations — if violation_rate > 5% use `text-alert`; else `text-text-primary`
- Card styling: `rounded-card bg-bg-elevated border border-border-faint p-5`
- Metric label: `text-label-nav uppercase text-text-faint`
- Below KPIs: "Queries in last 30 days: N" in `text-body-default`
- Empty state: "No deployments yet. Performance metrics will appear after tenants adopt this template." in `text-text-faint`

### Orchestrator Routing Mode (Chat)

No new UI needed for orchestrator — "Auto" mode in the chat mode selector already exists. This todo wires the backend routing to it.

Verify that when `mode = 'auto'` is selected in chat, the correct agent context is applied (agent icon, name, and description shown in response header should reflect the routed agent — currently "Auto" mode may show generic context).

### PA Platform Settings: Orchestrator Config

Add to Platform Admin > Settings page:

**Orchestrator section:**
- Routing Model dropdown (populated from `GET /platform/llm-library` filtered to small/fast models)
- Confidence Threshold slider: 0.0–1.0, label "Minimum routing confidence (queries below this use general RAG)"
- [Save] button

---

## Dependencies

- TODO-13 (DB schema) — agent_cards orchestrator flag
- TODO-16 (Skills) — mandatory skills authored and published
- TODO-21 (PA Skills Library) — mandatory flag management
- TODO-20 (PA Template Studio) — Performance tab extends TemplateStudioPanel
- Phases 1 and 2 must be complete (orchestrator needs deployed agents to route to)

---

## Risk Assessment

- **HIGH**: Mandatory skill latency — 500ms total budget for all mandatory skills; if a platform has multiple mandatory skills, budget per skill decreases; monitor execution time in audit log from day 1
- **HIGH**: Orchestrator routing LLM cost — every query in Auto mode now makes an additional LLM call; use cheapest capable model; cache routing decisions aggressively
- **MEDIUM**: Orchestrator cold start — new tenant with no agents gets only general RAG; ensure graceful fallback is smooth (no error, no "no agents found" message to user)
- **LOW**: Performance aggregation query cost — this query may be expensive on large tenants; add materialized view or scheduled aggregation job if p95 query time exceeds 2s

---

## Testing Requirements

### Mandatory Skills
- [ ] Unit test: mandatory skills run after main LLM response on every chat request
- [ ] Unit test: mandatory skill failure does NOT block response delivery
- [ ] Unit test: mandatory skills parallel execution completes within 500ms total
- [ ] Unit test: mandatory skill list cached in Redis; invalidated on unmandate

### Orchestrator
- [ ] Unit test: `TenantOrchestrator.route` returns correct agent for unambiguous query
- [ ] Unit test: low-confidence query triggers fallback (returns `agent_id=None`)
- [ ] Unit test: routing cache hit returns cached decision (no LLM call)
- [ ] Unit test: cache invalidated on agent deploy
- [ ] Integration test: auto mode end-to-end — query arrives, orchestrator routes, correct agent system_prompt used

### Performance Dashboard
- [ ] Unit test: `GET /platform/agent-templates/{id}/performance` returns correct aggregates
- [ ] Unit test: no per-tenant data in performance response (no tenant_id, no user IDs)
- [ ] Integration test: performance endpoint returns empty-state response when template has 0 instances
- [ ] E2E test: PA opens template with instances; performance tab shows non-zero values

---

## Definition of Done

### Mandatory Skills
- [ ] `MandatorySkillExecutor` integrated into chat orchestration pipeline
- [ ] Execution logged with skill_id and latency
- [ ] 500ms timeout enforced
- [ ] Failure does not block response

### Orchestrator
- [ ] `TenantOrchestrator` provisioned for every tenant on creation
- [ ] Auto mode routes via orchestrator
- [ ] Routing cache working with correct invalidation
- [ ] Platform settings for routing model + confidence threshold

### Performance Dashboard
- [ ] `GET /platform/agent-templates/{id}/performance` returns all 6 metrics
- [ ] `TemplatePerformanceTab` renders KPI cards with correct thresholds
- [ ] Empty state handled
- [ ] All acceptance criteria met

---

## Gap Patches Applied

### Gap 9: Mandatory skill enforcement — precise pipeline stage and failure contract

The existing `MandatorySkillExecutor` spec was correct in broad strokes but underspecified in three critical areas: the exact pipeline stage, the failure contract, and the scope of enforcement across agent types. This patch tightens all three.

**Enforcement stage: Post-processor (Stage 8.5)**

Mandatory skills execute at Stage 8.5 in the query pipeline:

```
Stage 1:  JWT validation
Stage 2:  Intent detection
Stage 3:  Embedding generation
Stage 4:  Vector search
Stage 5:  Context building
Stage 6:  LLM synthesis (main agent response)
Stage 7:  Guardrail evaluation
Stage 8:  Confidence scoring
Stage 8.5: MANDATORY SKILLS EXECUTION  ← insertion point
Stage 9:  Response streaming to client
```

Rationale for placing after guardrails (Stage 7): mandatory skills may annotate or transform the response. If they ran before guardrails, a mandatory skill could introduce content that then fails guardrail evaluation, causing the response to be blocked. Running after ensures guardrails have cleared the main response first.

**Enforcement hook in `QueryOrchestrator`:**

```python
# In QueryOrchestrator.post_process(response, context):
async def post_process(self, response: AgentResponse, context: QueryContext) -> AgentResponse:
    # Stage 7: guardrails (already implemented)
    response = await self.guardrail_engine.evaluate(response, context)

    # Stage 8: confidence scoring (already implemented)
    response = await self.confidence_scorer.score(response, context)

    # Stage 8.5: mandatory skills
    mandatory_skills = await self._get_mandatory_skills(context.tenant_id)
    if mandatory_skills:
        response = await self.mandatory_skill_executor.execute(
            response=response,
            skills=mandatory_skills,
            context=context
        )

    return response
```

**Mandatory skill execution order:**

Skills execute in sequence by `id` (stable ordering). Parallel execution is NOT used in v1 — sequential execution is simpler to reason about and the total budget is 500ms which is achievable sequentially for the expected number of mandatory skills (1-3 in practice).

**Failure contract (best-effort enforcer):**

- If any mandatory skill raises an exception or times out: log the error with `skill_id`, `error_type`, `latency_ms`; continue to next mandatory skill; do NOT abort the response
- If the entire mandatory skill stage exceeds 500ms wall-clock time: cancel remaining mandatory skills; log `mandatory_skills_timeout`; return response with only the mandatory skills that completed
- The user-visible response is NEVER blocked or delayed by mandatory skill failure
- A mandatory skill MAY annotate the response (e.g., add a citation block) but MUST NOT replace the main response text

**Enforcement scope — custom agents must also execute mandatory skills:**

This is the critical gap: mandatory skills must run for ALL agent types, not just template-derived agents. The `QueryOrchestrator.post_process()` method is called for every query regardless of whether the responding agent is:
- A deployed platform template instance
- A tenant-authored custom agent
- The orchestrator's fallback general RAG path

The `MandatorySkillExecutor` must be wired at the orchestrator level, NOT inside the template execution path. Any implementation that hooks mandatory skills only into template-derived query paths is incorrect.

**Verify in test:**
- [ ] Unit test: mandatory skill runs when query is handled by a custom agent (not a template-derived agent)
- [ ] Unit test: mandatory skill runs when orchestrator falls back to general RAG (no specific agent selected)
- [ ] Unit test: mandatory skill at Stage 8.5 receives the guardrail-cleared response, not the raw LLM output
- [ ] Unit test: first mandatory skill completes, second skill times out at 500ms — response is returned with first skill's annotation only; timeout logged
- [ ] Unit test: mandatory skill raises `SkillExecutionError` — response is returned unchanged; error logged with skill_id; user receives response without error message
- [ ] Integration test: PA marks Summarization skill as mandatory (via TODO-21 route); end user sends a query handled by a custom agent; audit log contains mandatory skill invocation record with `invocation_type='mandatory'`
