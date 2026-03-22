# 52 — Agent Template A2A Compliance: Implementation Approach

> **Status**: DRAFT
> **Date**: 2026-03-21

## Context

Concrete implementation recommendations for 6 architectural decisions needed to bring agent templates and agent cards into A2A compliance. All recommendations are grounded in existing codebase patterns (migration chain v001–v044, 8-stage orchestrator pipeline, established RLS conventions).

---

## 1. KB Bindings: Keep JSONB in capabilities — No Join Table

### Recommendation: Keep kb_ids inside capabilities JSONB. Do NOT create a join table.

**Rationale:**

1. **RLS alignment.** `agent_cards` uses tenant-scoped RLS (`app.tenant_id`). A join table (`agent_kb_bindings`) would need its own RLS policies and coordinated reads. The existing JSONB approach inherits RLS from the parent row automatically.
2. **Query-time performance.** The orchestrator never queries KB bindings at chat time — it uses `agent_id` directly to construct the search index name (`f"{tenant_id}-{agent_id}"` in `vector_search.py:464`). A join table would add a query that is never executed in the hot path.
3. **Low cardinality.** An agent has at most 5–10 KB bindings. Join tables are justified at hundreds+ per parent. A GIN index on `capabilities->'kb_ids'` is sufficient for reverse-lookup queries.
4. **Consistency.** `tool_ids`, `guardrails`, `kb_mode`, and `access_mode` are all in the same `capabilities` JSONB column. Extracting only `kb_ids` to a join table creates an inconsistent storage pattern.

**Action items:**

- Add GIN index on `capabilities->'kb_ids'` in a future migration if "which agents reference this KB?" queries are needed.
- Validate `kb_ids` entries against `search_index_registry` at API write time.
- Fix the runtime gap: `VectorSearchService.search()` must resolve `kb_ids` from capabilities and query multiple KB indexes at chat time.
- No schema migration needed for storage structure.

---

## 2. Tool Assignments: Keep JSONB + Batched Query in Orchestrator

### Recommendation: Keep tool_ids inside capabilities JSONB. Resolve available tools via a single batched query at orchestrator init, NOT per-query.

**Rationale:** Same arguments as KB bindings (low cardinality, RLS inheritance, consistency). An agent will have 0–5 tool assignments.

**How to avoid N+1 at query time:**

```python
# Stage 0 (pre-pipeline, runs once per request):
# 1. Load agent_cards row (already happens in prompt_builder._get_agent_prompt)
# 2. Extract tool_ids from capabilities JSONB in the same query
# 3. If tool_ids is non-empty, batch-fetch in a single UNION query:

SELECT id, name, mcp_endpoint, auth_type, safety_classification
FROM tool_catalog WHERE id = ANY(:tool_ids) AND health_status = 'healthy'
UNION ALL
SELECT id, name, endpoint, auth_type, NULL
FROM mcp_servers WHERE id = ANY(:tool_ids) AND status = 'active'
  AND tenant_id = :tenant_id
```

One DB round-trip per chat request regardless of tool count. The result feeds into a future "Stage 2.5: Tool Resolution" step.

**Action items:**

- Extend `_get_agent_prompt` (or its caller) to SELECT `capabilities` in the same DB round-trip.
- Create `app/modules/chat/tool_resolver.py` with `ToolResolver` class accepting `tool_ids: list[str]` and returning hydrated tool configs.
- No schema migration needed.

---

## 3. Guardrail Enforcement: Stage 7.5 — Inline, Strip-and-Flag

### Recommendation: Insert output guardrail checking as Stage 7.5, inline (not async), between LLM streaming completion and post-processing persistence.

### Pipeline location

```
Stage 7:   LLM streaming → response_text assembled
Stage 7.5: OUTPUT GUARDRAIL CHECK (new)   ← insert here
Stage 8:   Post-processing (persistence, memory update)
```

**Why inline, not async:**

- You must not persist a violating response. If guardrail checking is async, the violating response is already saved and streamed before checking.
- Latency is acceptable. Pattern-matching operations (`blocked_topics`, `max_response_length`, `confidence_threshold`) execute in <1ms.
- Fail-closed: better to be slow than to deliver harmful content.

### Violation behavior: Strip and flag (not reject)

1. **Strip**: Replace violating response with safe fallback: `"I cannot provide that information. Please rephrase your question or contact your administrator."`
2. **Flag**: Emit SSE event `{"event": "guardrail_triggered", "data": {"rule": "blocked_topic", "action": "stripped"}}` before `done`.
3. **Persist the flag**: Store `guardrail_violations: [{rule, action, timestamp}]` in conversation message metadata (not the response text).
4. **Do NOT hard reject** (no HTTP 4xx). The user has already seen streaming chunks — a hard reject after partial streaming is broken UX.

**For `max_response_length`:** Truncate + append `"[Response truncated by policy]"`.
**For `confidence_threshold`:** Prepend disclaimer if retrieval confidence is below threshold.

### Implementation sketch

```python
# In orchestrator.py, after response_text = "".join(response_chunks)

violations = await self._check_output_guardrails(
    response_text=response_text,
    agent_capabilities=capabilities,
    retrieval_confidence=retrieval_confidence,
)
if violations:
    response_text, guardrail_events = self._apply_guardrail_actions(
        response_text, violations
    )
    for evt in guardrail_events:
        yield evt
```

**Action items:**

- Create `app/modules/chat/guardrails.py` with `OutputGuardrailChecker`.
- Wire into orchestrator between stages 7 and 8.
- Extend conversation persistence to store guardrail violation metadata.
- No migration needed (metadata goes into existing JSONB columns).

---

## 4. /.well-known/agent.json: Separate Root-Level Router, No Auth

### Recommendation: Mount a dedicated FastAPI router at the application root (not under /api/v1). No authentication required for the base discovery endpoint.

```python
# app/modules/discovery/routes.py
well_known_router = APIRouter(tags=["a2a-discovery"])

@well_known_router.get("/.well-known/agent.json")
async def agent_discovery():
    """A2A Agent Card discovery endpoint. No auth required."""
    return {
        "name": "mingai",
        "description": "Enterprise RAG platform",
        "url": os.environ.get("PUBLIC_BASE_URL", ""),
        "version": "1.0",
        "capabilities": {"streaming": True, "a2a": True, "mcp": True},
        "authentication": {
            "type": "bearer",
            "token_url": "/api/v1/auth/token",
        },
        "endpoints": {
            "chat": "/api/v1/chat",
            "agents": "/api/v1/agents",
        },
    }
```

```python
# app/main.py
from app.modules.discovery.routes import well_known_router
app.include_router(well_known_router)  # No prefix — mounts at root
```

**Why separate root-level router:**

- A2A spec compliance: `/.well-known/agent.json` MUST be at root, not under `/api/v1/`.
- No auth on discovery — the entire point of `.well-known` is zero-auth service discovery.
- No sensitive data in response: only public metadata (platform name, supported protocols, auth method, endpoint paths). NO individual agent cards, system prompts, KB bindings, or tool configurations.

**Per-agent capability data** (authenticated) is served from the existing `/api/v1/agents/{agent_id}` endpoint. This is NOT the `.well-known` endpoint.

**Action items:**

- Create `app/modules/discovery/routes.py`.
- Mount in `app/main.py` at root level.
- Add `PUBLIC_BASE_URL` to `.env.example`.
- No migration needed.

---

## 5. MCP Server Resolution: Redis Cache, 5-Minute TTL, Lazy Load

### Recommendation: Cache resolved MCP tool configurations in Redis with a 5-minute TTL. Lazy-load from DB on cache miss.

### Resolution flow

```
1. Orchestrator extracts tool_ids from agent capabilities
2. For each tool_id referencing mcp_servers (not tool_catalog):
   a. Check Redis: key = "mingai:{tenant_id}:mcp_tool:{tool_id}"
   b. Cache HIT → use cached config (endpoint, auth_type, status)
   c. Cache MISS → query mcp_servers table → write to Redis with 300s TTL
3. Filter out inactive/unhealthy servers
4. Pass resolved MCP configs to tool execution layer
```

**Why Redis cache, not pure DB or in-memory:**

- DB on every request: MCP configs change rarely (admin action only), querying per-chat wastes a round-trip.
- Application in-memory cache (`lru_cache`): breaks in multi-process deployments — workers don't share memory, invalidation doesn't propagate.
- Redis is already in the stack (working memory, semantic cache, circuit breaker). Zero infrastructure cost.
- 5-minute TTL: MCP server config changes tolerate a 5-minute propagation delay. Admin PATCH endpoint can explicitly delete Redis key for instant invalidation.

**Cache key namespace** (follows established convention):

```
mingai:{tenant_id}:mcp_tool:{tool_id}  →  JSON: {endpoint, auth_type, status, name}
```

**Cache invalidation:** DELETE the Redis key on `POST /admin/mcp-servers`, `DELETE /admin/mcp-servers/{id}`, and status toggle.

**Action items:**

- Create `app/modules/chat/mcp_resolver.py` with `MCPToolResolver` class.
- Add Redis get/set/delete following the existing `SemanticCacheService` pattern.
- Wire invalidation into `app/modules/admin/mcp_servers.py` create/delete handlers.
- No migration needed.

---

## 6. required_credentials Migration: v045, Nullable=False, Default='[]'

### Recommendation: Add `required_credentials JSONB NOT NULL DEFAULT '[]'` to agent_templates in migration v045. No backfill needed for the 4 existing seed templates.

```python
"""v045_agent_templates_required_credentials.py

Adds required_credentials, auth_mode, and plan_required to agent_templates.
Default '[]' / 'none' / NULL means: no credentials required, no auth mode,
no plan gate. All 4 existing seed templates get safe defaults automatically.

Revision ID: 045
Revises: 044
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "045"
down_revision = "044"

def upgrade() -> None:
    op.add_column(
        "agent_templates",
        sa.Column(
            "required_credentials",
            postgresql.JSONB,
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "agent_templates",
        sa.Column(
            "auth_mode",
            sa.String(32),
            nullable=False,
            server_default="'none'",
        ),
    )
    op.add_column(
        "agent_templates",
        sa.Column("plan_required", sa.String(32), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("agent_templates", "plan_required")
    op.drop_column("agent_templates", "auth_mode")
    op.drop_column("agent_templates", "required_credentials")
```

**Why this is safe for the 4 existing seeds:**

- `server_default='[]'` fills all existing rows automatically. No data migration script.
- `NOT NULL` prevents accidental nulls in future inserts.
- The 4 seed templates (HR, IT Helpdesk, Procurement, Onboarding) are RAG-only agents — empty `required_credentials` is semantically correct.

**required_credentials schema:**

```json
[
  {
    "key": "api_key",
    "label": "API Key",
    "description": "Your Bloomberg Terminal API key",
    "type": "secret",
    "sensitive": true,
    "required": true
  }
]
```

When a tenant deploys a template with non-empty `required_credentials`, the deploy endpoint must validate that the tenant has stored the corresponding credentials via vault before allowing deployment. Validation is application-layer only.

**Action items:**

- Create `v045_agent_templates_required_credentials.py` with the migration above.
- Update `DeployFromTemplateRequest` handler to validate required credentials at deploy time.
- Update `CreateAgentTemplateRequest` in platform routes to accept all 3 new fields.
- Update the 4 seed templates dict in `routes.py` to include `auth_mode: "none"` and `required_credentials: []` (or omit to rely on defaults).

---

## Summary Table

| Decision                   | Approach                                              | Migration? | Redis? | Complexity |
| -------------------------- | ----------------------------------------------------- | ---------- | ------ | ---------- |
| 1. KB bindings             | JSONB in capabilities (keep) + fix runtime resolution | No         | No     | M          |
| 2. Tool assignments        | JSONB in capabilities + batched resolver              | No         | No     | L          |
| 3. Guardrail enforcement   | Stage 7.5 inline, strip-and-flag                      | No         | No     | XL         |
| 4. /.well-known/agent.json | Separate root router, no auth                         | No         | No     | S          |
| 5. MCP server resolution   | Redis cache 5-min TTL, lazy load                      | No         | Yes    | M          |
| 6. required_credentials    | v045 migration, NOT NULL, default='[]'                | Yes (v045) | No     | M          |

---

## Key Files Referenced

| File                                            | Role                                                                                 |
| ----------------------------------------------- | ------------------------------------------------------------------------------------ |
| `app/modules/agents/routes.py`                  | Agent templates API — kb_ids/tool_ids stored in capabilities JSONB                   |
| `app/modules/chat/orchestrator.py`              | 8-stage RAG pipeline — guardrail insertion at Stage 7.5                              |
| `app/modules/chat/prompt_builder.py`            | `_get_agent_prompt` — extend to SELECT capabilities same round-trip                  |
| `app/modules/chat/vector_search.py`             | `index_id = f"{tenant_id}-{agent_id}"` — must be extended to resolve kb_ids          |
| `app/modules/admin/mcp_servers.py`              | Tenant MCP server CRUD — add cache invalidation hooks                                |
| `app/modules/registry/a2a_routing.py`           | SSRF protection pattern — reuse `_validate_ssrf_safe_url()` for MCP URLs             |
| `app/core/secrets/vault_client.py`              | Vault abstraction — reuse for required_credentials validation at deploy time         |
| `alembic/versions/v020_agent_templates.py`      | Current schema — v045 extends this                                                   |
| `alembic/versions/v028_agent_access_control.py` | Join table pattern — the one case where a join table IS warranted (RBAC query needs) |
