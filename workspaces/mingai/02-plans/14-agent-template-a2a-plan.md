# 14. Agent Template A2A Compliance Implementation Plan

> **Status**: Implementation Plan (v1.1 — Red-Team Validated)
> **Date**: 2026-03-21
> **Priority**: P0 — 4 CRITICAL gaps are active security boundaries today
> **Effort**: 10 sprints across 3 phases (Weeks 1–10)
> **Source documents**: 49 (gap analysis), 50 (requirements), 51 (COC fault lines), 52 (implementation approach), 16/01 (enterprise buyer audit), 16/02 (UX spec)

---

## Executive Summary

The agent template system has a working deployment pipeline — templates resolve, system prompts substitute, and agents insert into `agent_cards`. But ten gaps exist between the architecture specifications and the running code. The blast radius is severe: a tenant admin who configures an agent with KB bindings, access restrictions, tool assignments, and guardrails receives a `201 Created` response while none of those configurations take effect at runtime.

Four gaps are CRITICAL by COC fault-line analysis:

| Gap                                                            | Fault Line         | Active Risk Today                                                                 |
| -------------------------------------------------------------- | ------------------ | --------------------------------------------------------------------------------- |
| Guardrails stored but never enforced                           | Security Blindness | Bloomberg agent will provide investment advice on demand                          |
| `agent_access_control` never populated on deploy               | Security Blindness | All agents accessible to all workspace users regardless of configured restriction |
| KB bindings silently dropped                                   | Security Blindness | All agents query the same index; KB configuration is cosmetic                     |
| `# NOTE: kb_ids/tool_ids are intentionally not stored` comment | Convention Drift   | Accepted security config is silently discarded with no client feedback            |

The enterprise buyer audit (doc 16/01) frames the stakes directly: without guardrail enforcement, KB binding resolution, and vault-backed credentials, this is a RAG chatbot with a nice admin panel — not a regulated-industry platform. A financial services firm will discover all three failures in the first hour of a POC.

**Phase sequencing**: Phase A (Weeks 1–3) breaks the silent data loss pattern and enforces real security boundaries. Phase B (Weeks 4–6) completes A2A protocol compliance and adds guardrail runtime enforcement. Phase C (Weeks 7–10) builds the MCP tool ecosystem. This ordering ensures the platform is defensible before it is feature-complete.

---

## Architecture Decision Records (Confirmed)

These ADRs are already decided. They are recorded here as reference — do not re-litigate them during implementation.

### ADR-01: JSONB for KB/Tool Bindings — No Join Tables

**Decision**: `kb_ids` and `tool_ids` remain in the `capabilities` JSONB column on `agent_cards`. No `agent_kb_bindings` or `agent_tool_assignments` join tables.

**Rationale**: RLS policies on `agent_cards` cover JSONB columns automatically — a join table requires its own RLS policies and coordinated reads. Low cardinality (5–10 bindings per agent). A GIN index on `capabilities->'kb_ids'` covers the reverse-lookup query ("which agents reference this KB?"). Consistency: `tool_ids`, `guardrails`, `kb_mode`, and `access_mode` are all in the same `capabilities` JSONB — extracting only `kb_ids` to a join table creates an inconsistent storage pattern.

**Implementation consequence**: The runtime fix is in the orchestrator and vector search service, not in the schema. No migration needed for storage structure. Migration v046a adds only the GIN index.

### ADR-02: Stage 7.5 Inline Guardrail — Conditional Buffering, Not Post-Stage-8

**Decision**: The output guardrail checker runs as Stage 7b of the `ChatOrchestrationService` pipeline — after LLM streaming completes, before `_persistence.save_exchange()` is called.

**Rationale**: If guardrail checking runs after Stage 8 persistence, a blocked response is already written to conversation history before it is blocked. This is a SOC 2 and MiFID II violation — regulated content reaches the data store even when the user never sees it. For guardrail-enabled agents, the orchestrator must buffer all LLM chunks rather than yielding them live. The buffer is then passed to Stage 7b, and the (potentially modified or replaced) response is yielded only after the check completes. Fail-closed: any filter exception must return a canned error, never the unfiltered response.

**Strip-and-flag behavior**: Do NOT hard-reject (HTTP 4xx). Instead: (1) replace violating response with safe fallback text, (2) emit `guardrail_triggered` SSE event before `done`, (3) persist `guardrail_violations: [{rule, action, timestamp}]` in message metadata JSONB only — never the blocked original text.

**Streaming behavior by agent type**:

- Default agents (no guardrails configured, `capabilities.guardrails` is absent or empty): stream chunks live as today — no buffering, no latency addition.
- Guardrail-enabled agents (`capabilities.guardrails` is non-empty): buffer the entire LLM response, run Stage 7b, then yield all buffered chunks at once (or the replacement canned message). Latency implication: adds ~1–2s because the full LLM response must complete before any token is delivered to the client.

### ADR-03: v045 Migration — `server_default='[]'`, No Backfill

**Decision**: Add `required_credentials JSONB NOT NULL DEFAULT '[]'`, `auth_mode VARCHAR(32) NOT NULL DEFAULT 'none'`, `plan_required VARCHAR(32) NULL` to `agent_templates` via a single `ALTER TABLE` in migration v045. No data backfill script needed for the 4 existing seed templates.

**Rationale**: The 4 seed templates (HR, IT Helpdesk, Procurement, Onboarding) are RAG-only agents. Empty `required_credentials` and `auth_mode='none'` are semantically correct defaults. `server_default='[]'` fills all existing rows automatically at migration time. `NOT NULL` prevents accidental nulls in future inserts.

---

## COC Institutional Rules (Must Be Encoded in Source)

The following rules encode institutional decisions that will be lost across codegen sessions. Each must be placed in the specified file location during implementation — not in a separate document.

### RULE A2A-01: Output Filter Is Stage 7b — Before Persistence

**Location**: `orchestrator.py` class docstring Stage list + `OutputGuardrailChecker` class docstring

```
CRITICAL: The guardrail output filter runs at Stage 7b — after LLM streaming
completes and BEFORE _persistence.save_exchange() is called.

WRONG placement: post-Stage-8 (blocked content already in DB, SOC 2 violation).
CORRECT pipeline: Stage 7 → Stage 7b (filter) → Stage 8 (persist filtered/canned text).

For guardrail-enabled agents, Stage 7 MUST buffer all chunks (not yield them live)
so Stage 7b operates on the complete response. Only after Stage 7b clears does the
orchestrator yield the (filtered or canned) response to the SSE stream.

On FilterResult.action="block": yield error SSE event, DO NOT call save_exchange.
On FilterResult.action="redact": pass redacted text to save_exchange.
On filter exception: fail closed — return canned error, never the original.
```

### RULE A2A-02: Guardrail Config in DB Is Not Enforcement

**Location**: `GuardrailsSchema` Pydantic class docstring + `create_agent` endpoint inline comment

```
CRITICAL: Storing guardrails in agent_cards does nothing unless
ChatOrchestrationService reads and applies them on every request.

blocked_topics → compiled into keyword_block rules in OutputGuardrailChecker
confidence_threshold → if retrieval_confidence < threshold after Stage 4,
                        return canned low-confidence response; do NOT call LLM
max_response_length → truncate at word boundary after Stage 7; log truncation
```

### RULE A2A-03: No Silent Credential/Access Discard

**Location**: `deploy_agent_template_db()` docstring

```
CRITICAL: Until Phase A access control enforcement is live, the deploy endpoint
MUST return HTTP 422 for any request where access_control != "workspace_wide"
OR kb_ids is non-empty, with message:
"Access-restricted and KB-bound agent deployment requires enforcement to be active."

Silent acceptance of security config that is discarded is worse than rejection.
The admin believes the restriction is active. It is not.
```

### RULE A2A-04: SSRF Check Is Per-Request, Not Per-Registration

**Location**: `_validate_ssrf_safe_url()` docstring in `a2a_routing.py`

```
CRITICAL: DNS resolution check MUST happen on every outbound HTTP call.
Moving this check to registration time introduces DNS rebinding attacks:
an operator registers a safe public IP, then changes DNS to point to
169.254.169.254 (cloud metadata) after registration passes.

ALL outbound HTTP calls (A2A endpoints, MCP endpoints, credential test URLs,
webhook URLs) must call _validate_ssrf_safe_url() immediately before the request.
Import from app.modules.registry.a2a_routing — never reimplement inline.
```

### RULE A2A-05: DistributedJobLock for Per-Tenant Scheduled Jobs

**Location**: `run_daily_credential_health_check()` function docstring

```
CONVENTION: All scheduled per-tenant jobs MUST acquire
DistributedJobLock(f"cred_health:{tenant_id}", ttl_seconds=86000) before executing.
Without this, multi-worker deployments run duplicate checks, multiplying vault read
load and generating duplicate admin notifications for every expired credential.
```

### RULE A2A-06: `tenant_id` Predicate on All `agent_cards` Writes

**Location**: `_AGENT_UPDATE_SQL` comment block in `agents/routes.py`

```
CONVENTION: Every UPDATE to agent_cards MUST include tenant_id = :tenant_id
in the WHERE clause — not only the initial INSERT. Missing tenant_id on the
UPDATE path allows a crafted request to overwrite a different tenant's agent
access control configuration (cross-tenant RLS bypass via application layer).
```

---

## Phase A — Foundation (Weeks 1–3): Break Silent Data Loss

**Objective**: Every field a tenant admin configures on an agent deploy must either be enforced or rejected with a 422. No silent discard.

**Must ship as a unit**: All four Sprint 1–2 items share a migration dependency chain. Deploying access control enforcement without the warning-to-422 fix would leave the existing silent discard behavior. Deploy all four together or deploy none.

---

### Sprint 1 (Week 1–2): Schema + Enforcement Gates

#### Item A1: v045 Migration — `required_credentials`, `auth_mode`, `plan_required` on `agent_templates`

**Gap**: Gap 10 from doc 49. Schema designed before credential architecture was specified (v020 predates doc 33).

**Files to create**:

- `src/backend/alembic/versions/v045_agent_templates_required_credentials.py`

**Migration content**:

```python
revision = "045"
down_revision = "044"

def upgrade() -> None:
    op.add_column(
        "agent_templates",
        sa.Column("required_credentials", postgresql.JSONB, nullable=False, server_default="'[]'"),
    )
    op.add_column(
        "agent_templates",
        sa.Column("auth_mode", sa.String(32), nullable=False, server_default="'none'"),
    )
    op.add_column(
        "agent_templates",
        sa.Column("plan_required", sa.String(32), nullable=True),
    )
    op.create_check_constraint(
        "ck_agent_templates_auth_mode",
        "agent_templates",
        "auth_mode IN ('none', 'tenant_credentials', 'platform_credentials')",
    )
    op.create_check_constraint(
        "ck_agent_templates_plan_required",
        "agent_templates",
        "plan_required IS NULL OR plan_required IN ('starter', 'professional', 'enterprise')",
    )

def downgrade() -> None:
    op.drop_constraint("ck_agent_templates_plan_required", "agent_templates")
    op.drop_constraint("ck_agent_templates_auth_mode", "agent_templates")
    op.drop_column("agent_templates", "plan_required")
    op.drop_column("agent_templates", "auth_mode")
    op.drop_column("agent_templates", "required_credentials")
```

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`
  - `CreateAgentTemplateRequest` Pydantic schema: add `required_credentials: List[Dict] = Field(default_factory=list)`, `auth_mode: str = Field("none", pattern="^(none|tenant_credentials|platform_credentials)$")`, `plan_required: Optional[str] = Field(None, pattern="^(starter|professional|enterprise)$")`
  - `UpdateAgentTemplateRequest` Pydantic schema: same three fields, all Optional
  - `_TEMPLATE_UPDATE_ALLOWLIST`: add `"required_credentials"`, `"auth_mode"`, `"plan_required"`
  - `_create_agent_template_db()` INSERT statement: include three new columns
  - `_patch_agent_template_db()` UPDATE path: these fields are in the allowlist, handled by existing dynamic SET builder
  - `GET /agents/templates` response: include three new fields in the template catalog response

**Dependencies**: None. This is the first in the chain.

**Success criteria**:

- `python -m pytest tests/unit/test_agent_templates.py -k "test_template_create_with_auth_mode"` passes
- `GET /api/v1/agents/templates` returns `auth_mode`, `plan_required`, `required_credentials` for all templates
- `POST /api/v1/platform/agent-templates` with invalid `auth_mode="invalid"` returns 422
- Existing 4 seed templates have `auth_mode="none"`, `required_credentials=[]`, `plan_required=null` after migration

**Tests required**:

- `tests/integration/test_agent_deploy_access_control.py` — covers all three deploy paths and the access control INSERT

---

#### Item A2: Access Control Population on Deploy — `deploy_from_template` Handler

**Gap**: Gap 9 from doc 49 (COC fault line: Security Blindness). `agent_access_control` table exists (v028) but is never populated on any deploy path. The comment at `routes.py` lines 639–651 currently logs a warning and discards the configuration.

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Access control enum mapping** — add this constant at module level before all deploy functions:

```python
# C2: Map DeployAgentRequest.access_control API values to agent_access_control.visibility_mode
# DB column uses CHECK constraint values: 'workspace_wide', 'role_restricted', 'user_specific'.
# API uses shorter human-readable values. This mapping is required in ALL three deploy paths.
_ACCESS_CONTROL_MAP = {
    "workspace": "workspace_wide",
    "role": "role_restricted",
    "user": "user_specific",
}
```

**Specific changes**:

1. In `deploy_agent_template_db()` — after the `agent_cards` INSERT, add:

```python
# INSERT into agent_access_control immediately after agent_cards row is created.
# This must happen in the same transaction. No row in agent_access_control means
# no access enforcement — treat absence-of-row as workspace_wide as a fallback,
# but always insert explicitly for auditability.
visibility_mode = _ACCESS_CONTROL_MAP.get(body.access_control, "workspace_wide")
await db.execute(
    text("""
        INSERT INTO agent_access_control
            (agent_id, tenant_id, visibility_mode, allowed_roles, allowed_user_ids)
        VALUES
            (:agent_id, :tenant_id, :visibility_mode, :allowed_roles, :allowed_user_ids)
        ON CONFLICT (agent_id, tenant_id) DO NOTHING
    """),
    {
        "agent_id": new_agent_id,
        "tenant_id": tenant_id,
        "visibility_mode": visibility_mode,
        "allowed_roles": list(body.allowed_roles or []),
        "allowed_user_ids": list(body.allowed_user_ids or []),
    },
)
```

Note: `list(row.allowed_roles or [])` pattern is used here and in all access control reads because asyncpg returns PostgreSQL `VARCHAR[]` as Python list — the explicit `list()` coercion is added for safety.

2. Remove the warning-and-discard comment block (lines 639–651). Replace with actual implementation. The 422 gate from RULE A2A-03 is the interim behavior for non-workspace requests:

```python
# RULE A2A-03: Return 422 for access-restricted deploys until KB runtime
# enforcement is confirmed active (Phase A Item A3 must be deployed first).
# Check git blame for the commit that removes this guard — that is the moment
# enforcement is live.
if body.access_control not in ("workspace", None) or body.kb_ids:
    raise HTTPException(
        status_code=422,
        detail=(
            "Access-restricted and KB-bound agent deployment requires runtime "
            "enforcement to be active. Deploy with access_control='workspace' "
            "and no kb_ids until enforcement is confirmed."
        ),
    )
```

3. Apply the same `_ACCESS_CONTROL_MAP` mapping and `agent_access_control` INSERT to `deploy_from_library_db()` and `create_agent_studio_db()`. The mapping constant must be used in all three paths without duplication.

4. Data migration for existing `agent_cards` that have no `agent_access_control` row — add to migration v046b (see Item A4 below).

**Success criteria**:

- Deploy a template with default `access_control`: `SELECT * FROM agent_access_control WHERE agent_id = :new_id` returns exactly one row with `visibility_mode = 'workspace_wide'`
- Deploy a template with `access_control = 'role'`: returns HTTP 422 with message containing "enforcement"
- No `logger.warning("agent_deploy_config_not_persisted", ...)` call exists anywhere in routes.py after this change
- `python -m pytest tests/integration/test_agent_deploy_access_control.py -k "test_access_control_populated_on_deploy"` passes

---

#### Item A3: KB Bindings Runtime Resolution in `VectorSearchService`

**Gap**: Gap 1 from doc 49 (COC fault line: Security Blindness). `vector_search.py` uses `index_id = f"{tenant_id}-{agent_id}"` — the agent's own index only. KB IDs stored in `capabilities.kb_ids` are never read at search time.

**Files to modify**:

- `src/backend/app/modules/chat/vector_search.py`
- `src/backend/app/modules/chat/prompt_builder.py`

**Sub-task A3.0 (prerequisite): Refactor `VectorSearchService.search()`**

The existing `search()` method at line ~434 has signature `(query_vector, tenant_id, agent_id, top_k, query_text, conversation_id, user_id)`. Before adding multi-index fan-out, extract the single-index search body (lines ~464–489) into a new private method:

```python
async def _search_single_index(
    self,
    index_id: str,
    query_vector: list[float],
    top_k: int,
    query_text: str,
    conversation_id: str | None,
    user_id: str,
) -> list[SearchResult]:
    """
    Search a single named vector index.
    Raises on index not found — caller (the fan-out gather) must handle exceptions.
    """
    # Extract lines ~464-489 from current search() body here.
    # Returns list[SearchResult] for this index only.
```

The new public `search()` method calls `_search_single_index` for the primary agent index, or fans out via `asyncio.gather` across all `kb_ids` when non-empty. Note: `query_vector: list[float]` — embedding happens before this call; `search()` does not accept a raw `query: str`.

**Specific changes in `vector_search.py`**:

The `search()` method signature must be extended to accept `kb_ids: list[str]`:

```python
async def search(
    self,
    query_vector: list[float],
    tenant_id: str,
    agent_id: str,
    top_k: int = 5,
    query_text: str = "",
    conversation_id: str | None = None,
    user_id: str = "",
    kb_ids: list[str] | None = None,
) -> list[SearchResult]:
    """
    Search vector indexes. If kb_ids is non-empty, fan-out to each KB index
    in addition to the agent's own index via asyncio.gather.

    Index naming convention:
    - Agent's own index: f"{tenant_id}-{agent_id}"
    - KB binding index:  kb_id directly (the integration's index_id)

    RULE: kb_ids entries must be validated against the tenant's accessible
    integrations at the route handler layer before reaching here. This method
    trusts that kb_ids have been pre-validated.

    Calls _search_single_index() for each index. Exceptions from individual
    indexes are logged and skipped — never raised (resilient fan-out).
    """
    indexes_to_search: list[str] = []

    # Always include the agent's own index if it exists
    agent_index = f"{tenant_id}-{agent_id}"
    indexes_to_search.append(agent_index)

    # Fan out to each KB binding
    if kb_ids:
        for kb_id in kb_ids:
            # kb_id is the index_id from the integrations table
            if kb_id not in indexes_to_search:
                indexes_to_search.append(kb_id)

    # Execute parallel search across all indexes
    search_tasks = [
        self._search_single_index(
            index_id=index_id,
            query_vector=query_vector,
            top_k=top_k,
            query_text=query_text,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        for index_id in indexes_to_search
    ]
    all_results = await asyncio.gather(*search_tasks, return_exceptions=True)

    # Merge results, skip failed indexes (log but do not raise)
    merged: list[SearchResult] = []
    for idx, result in enumerate(all_results):
        if isinstance(result, Exception):
            logger.warning(
                "kb_search_index_failed",
                index_id=indexes_to_search[idx],
                tenant_id=tenant_id,
                agent_id=agent_id,
                error=str(result),
            )
        else:
            merged.extend(result)

    # Re-rank merged results by score, return top_k
    merged.sort(key=lambda r: r.score, reverse=True)
    return merged[:top_k]
```

**Specific changes in `prompt_builder.py`**:

In `_get_agent_prompt()`, extract `kb_ids` from the `capabilities` JSONB in the same DB round-trip that fetches the agent record:

```python
async def _get_agent_prompt(
    self,
    agent_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> tuple[str, dict, list[str]]:
    """
    Returns (system_prompt, capabilities_dict, kb_ids_list).
    kb_ids_list is extracted from capabilities["kb_ids"] for use by VectorSearchService.
    """
    result = await db.execute(
        text("""
            SELECT system_prompt, capabilities
            FROM agent_cards
            WHERE id = :agent_id AND tenant_id = :tenant_id AND status = 'active'
        """),
        {"agent_id": agent_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return ("", {}, [])

    capabilities = row.capabilities or {}
    kb_ids = capabilities.get("kb_ids", [])
    # Ensure it is a list of strings — guard against malformed JSONB
    if not isinstance(kb_ids, list):
        kb_ids = []

    return (row.system_prompt or "", capabilities, [str(k) for k in kb_ids if k])
```

**Orchestrator wiring**: In `orchestrator.py` Stage 4 (vector search), pass `kb_ids` returned from `_get_agent_prompt()` to `VectorSearchService.search()`. The orchestrator already calls `_get_agent_prompt()` in Stage 3. Extract `kb_ids` from the return value and forward it.

**Remove the 422 gate from Item A2** once this item is deployed and verified in staging. The gate exists to prevent access-restricted deploys while enforcement is pending. Once KB binding resolution is live and verified, lift the gate.

**Success criteria**:

- Create two agents: Agent A with `kb_ids=["integration-1"]`, Agent B with `kb_ids=["integration-2"]`
- Upload doc1 to integration-1, doc2 to integration-2
- Query Agent A about doc2 content: result must not appear
- Query Agent B about doc1 content: result must not appear
- Query Agent A about doc1 content: result must appear with correct source citation
- `python -m pytest tests/integration/test_kb_binding_resolution.py` passes

**Risk flag**: `_search_single_index` must handle "index not found" without raising — log and skip. An agent may have `kb_ids` referencing an integration that has been removed (orphaned reference in JSONB since there is no FK constraint). The fan-out logic must be resilient.

**Tests required**:

- `tests/integration/test_kb_binding_resolution.py` — two-agent doc isolation test as described above

---

### Sprint 2 (Week 3): Access Control Enforcement at Chat Time + v046 Migrations

#### Item A4: Access Control Check in Chat Pipeline

**Gap**: Gap 9 enforcement side. The `agent_access_control` table is now populated (Item A2), but the chat orchestrator does not check it before running the pipeline.

**Files to modify**:

- `src/backend/app/modules/chat/orchestrator.py`
- `src/backend/app/modules/agents/routes.py` (end-user agent list endpoint)

**Specific changes in `orchestrator.py`**:

Add access check at the start of `stream_response()`, before Stage 1:

```python
async def _check_agent_access(
    self,
    agent_id: str,
    tenant_id: str,
    user_id: str,
    user_roles: list[str],
    db: AsyncSession,
) -> bool:
    """
    Returns True if the calling user can access this agent.
    Must be called before any pipeline stage runs.

    Rule: query agent_access_control table, not agent_cards. Absence of a row
    is treated as workspace_wide (backward compat for agents without access
    control rows — see data migration in v046b).
    """
    result = await db.execute(
        text("""
            SELECT visibility_mode, allowed_roles, allowed_user_ids
            FROM agent_access_control
            WHERE agent_id = :agent_id AND tenant_id = :tenant_id
        """),
        {"agent_id": agent_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return True  # No row → workspace_wide (backward compat)

    if row.visibility_mode == "workspace_wide":
        return True
    if row.visibility_mode == "role_restricted":
        return bool(set(user_roles) & set(list(row.allowed_roles or [])))
    if row.visibility_mode == "user_specific":
        return user_id in list(row.allowed_user_ids or [])
    return False
```

Note: `list(row.allowed_roles or [])` and `list(row.allowed_user_ids or [])` coercions are added for safety — asyncpg returns PostgreSQL `VARCHAR[]` as Python list, but explicit coercion guards against edge cases.

If `_check_agent_access` returns False, raise `HTTPException(status_code=403, detail="Agent not available")`. Do NOT disclose the caller's roles or the agent's access configuration in the error (403 security rule from platform architecture).

**End-user agent list** (`GET /api/v1/agents`): The query must JOIN `agent_access_control` and apply a WHERE predicate filtering by the calling user's roles and ID. This prevents restricted agents from appearing in the sidebar for unauthorized users (information disclosure via enumeration).

**Files to create**:

- `src/backend/alembic/versions/v046a_gin_index_capabilities_kb_ids.py`
- `src/backend/alembic/versions/v046b_agent_access_control_backfill.py`

v046 is split into two migrations (v046a and v046b) because `CREATE INDEX CONCURRENTLY` cannot run inside an Alembic transaction, and mixing DDL with DML in a single transactional migration is error-prone.

**Migration v046a content** — GIN index only, no DML:

```python
revision = "046a"
down_revision = "045"

def upgrade() -> None:
    # GIN index for reverse-lookup: "which agents reference this KB?"
    # Used by admin/kb_sources.py when detaching a KB source.
    #
    # NOTE (H1): CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    # Two options:
    #   Option A (recommended — table is small, lock is acceptable at migration time):
    #     Use plain CREATE INDEX without CONCURRENTLY. Lock is brief.
    #   Option B (large tables): set connection to autocommit before executing CONCURRENTLY.
    # This migration uses Option A.
    op.create_index(
        "ix_agent_cards_capabilities_kb_ids",
        "agent_cards",
        ["capabilities"],
        postgresql_using="gin",
        postgresql_ops={"capabilities": "jsonb_path_ops"},
    )

def downgrade() -> None:
    op.drop_index("ix_agent_cards_capabilities_kb_ids", table_name="agent_cards")
```

**Migration v046b content** — data backfill only, no DDL:

```python
revision = "046b"
down_revision = "046a"

def upgrade() -> None:
    # Data migration: insert workspace_wide access control row for all existing
    # agent_cards that have no agent_access_control entry.
    #
    # NOTE (M3): Before deploying Stage 7.5 guardrail enforcement, audit agents
    # for non-zero max_response_length values — those will start truncating responses
    # after Item B2 deploys. Run the pre-deploy audit query documented below.
    # The OutputGuardrailChecker treats max_response_length=0 as 'no limit'.
    #
    # FIX (HIGH — V1): Do NOT inject a default guardrails object for existing agents.
    # The previous version of this migration set capabilities ||
    # '{"guardrails": {"max_response_length": 0}}' for all agents where the
    # guardrails key was absent. That caused _has_active_guardrails() to see a
    # non-None dict and — under the old bool() check — triggered 1-2s buffering
    # latency for EVERY agent. The OutputGuardrailChecker already handles absent
    # guardrails correctly (returns pass with no violations). Leave the key ABSENT
    # for agents that were never configured with guardrails.
    op.execute("""
        INSERT INTO agent_access_control
            (agent_id, tenant_id, visibility_mode, allowed_roles, allowed_user_ids)
        SELECT ac.id, ac.tenant_id, 'workspace_wide', '{}', '{}'
        FROM agent_cards ac
        LEFT JOIN agent_access_control aac
            ON aac.agent_id = ac.id AND aac.tenant_id = ac.tenant_id
        WHERE aac.agent_id IS NULL
    """)

def downgrade() -> None:
    # Do not reverse the data migration — access control rows are safe to leave.
    # The guardrails default is also safe to leave.
    pass
```

**Data audit prerequisite before deploying Item B2**: Run this query to identify agents with guardrail defaults that will affect response length after Stage 7.5 deploys:

```sql
SELECT id, capabilities->'guardrails' AS guardrails
FROM agent_cards
WHERE capabilities->'guardrails' IS NOT NULL
  AND (capabilities->'guardrails'->>'max_response_length')::int > 0;
```

Any agent with `max_response_length > 0` will start truncating responses. Confirm this is intentional before deploying Item B2.

**Success criteria**:

- Create agent with `visibility_mode = 'role_restricted'`, `allowed_roles = ['hr_manager']`
- User with `roles = ['analyst']` sends chat request to that agent: receives 403, no pipeline runs
- User with `roles = ['hr_manager']` sends same request: receives SSE response
- `GET /api/v1/agents` for analyst user does not include the role-restricted agent in the list
- `python -m pytest tests/integration/test_agent_deploy_access_control.py` passes

**Risk flag (COC Convention Drift)**: Every `UPDATE` to `agent_access_control` must include `AND tenant_id = :tenant_id` in the WHERE clause. The existing `PATCH /admin/agents/{id}/access` endpoint in `agent_access_control.py` already has this predicate — verify it is present before closing this item.

**Tests required**:

- `tests/integration/test_agent_deploy_access_control.py` — role-restricted 403, role-matching 200, enumeration prevention

---

## Phase B — A2A Compliance (Weeks 4–6): Platform Discovery + Guardrail Enforcement

**Objective**: The platform is discoverable via the A2A standard. Guardrail enforcement is live and passing the Bloomberg golden test set. Credential deploy validation blocks deployments with missing required credentials.

---

### Sprint 3 (Weeks 4–5): `/.well-known/agent.json` + Guardrail Runtime Enforcement

#### Item B1: `/.well-known/agent.json` Discovery Endpoint

**Gap**: Gap 6 from doc 49. `a2a_routing.py` handles outbound A2A routing but there is no inbound discovery endpoint. External agents cannot discover mingai via the A2A standard.

**Rate limit**: 60 requests per minute per IP using slowapi or equivalent middleware. Configure in the router registration in `main.py`. This endpoint is unauthenticated and therefore exposed to enumeration; rate limiting is required.

**Files to create**:

- `src/backend/app/modules/discovery/__init__.py` (empty)
- `src/backend/app/modules/discovery/routes.py`

**Implementation in `routes.py`**:

```python
"""
A2A v0.3 platform-level discovery endpoint.

SECURITY: This endpoint is unauthenticated by A2A protocol spec.
MUST NOT return any of:
  - system_prompt (enables prompt injection calibration)
  - credentials_vault_path (reduces vault attack search space)
  - kb_bindings with index IDs (enables targeted extraction attacks)
  - access_rules with role IDs (maps tenant RBAC structure)
  - tenant_id (must not be discoverable via public endpoint)

Returns only: platform name, supported protocols, auth method, endpoint paths.
Per-agent capability data (authenticated) is served from /api/v1/agents/{id}.
This is NOT the per-agent AgentCard endpoint.
"""
import os
from fastapi import APIRouter

well_known_router = APIRouter(tags=["a2a-discovery"])

@well_known_router.get("/.well-known/agent.json")
async def platform_agent_discovery():
    """
    A2A v0.3 platform discovery. No authentication required.
    Returns platform-level AgentCard only. Individual agent cards
    require authentication via /api/v1/agents/{agent_id}.
    """
    return {
        "name": "mingai",
        "description": "Enterprise RAG platform with agent template system",
        "url": os.environ.get("PUBLIC_BASE_URL", ""),
        "version": "1.0",
        "provider": {
            "organization": "mingai",
            "url": os.environ.get("PUBLIC_BASE_URL", ""),
        },
        "capabilities": {
            "streaming": True,
            "a2a": True,
            "mcp": True,
        },
        "authentication": {
            "schemes": ["bearer"],
            "token_url": "/api/v1/auth/login",
        },
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "endpoints": {
            "chat": "/api/v1/chat",
            "agents": "/api/v1/agents",
        },
    }
```

**Files to modify**:

- `src/backend/app/main.py`: mount `well_known_router` at application root (no prefix):

```python
from app.modules.discovery.routes import well_known_router
# Mount at root — A2A spec requires /.well-known/agent.json at the domain root,
# NOT under /api/v1/. Include BEFORE the /api/v1 router.
app.include_router(well_known_router)
```

- `src/backend/.env.example`: add `PUBLIC_BASE_URL=https://your-domain.com`

**Dependencies**: None. Fully independent.

**Success criteria**:

- `GET /.well-known/agent.json` returns HTTP 200 with `Content-Type: application/json` — no auth required
- Response contains `name`, `url`, `capabilities`, `authentication`, `endpoints`
- Response does NOT contain `system_prompt`, `tenant_id`, `kb_bindings`, `credentials_vault_path`, `access_rules`
- Endpoint is NOT mounted under `/api/v1/` prefix
- Rate limit: 61st request within 60s from same IP returns 429
- `python -m pytest tests/integration/test_a2a_discovery.py` passes
- A2A v0.3 AgentCard schema validation passes against the response (use the test fixture from `test_har_a2a_integration.py` as a reference for the schema validator)

**Tests required**:

- `tests/integration/test_a2a_discovery.py` — schema validation, no-auth access, field exclusion assertions

---

#### Item B2: Stage 7.5 Output Guardrail Enforcement

**Gap**: Gap 5 from doc 49 (COC fault line: Security Blindness + Convention Drift). Guardrails exist in two JSONB formats but neither is read by the orchestrator, prompt builder, or any middleware. This is the single highest-priority engineering investment from the enterprise buyer perspective.

**Prerequisites before deploying this item**:

1. Run the data audit query specified in Item A4 to identify agents with non-zero `max_response_length`. Confirm all are intentional before proceeding.
2. v046b migration must be deployed (ensures agents without explicit guardrails get `max_response_length: 0`).

**Files to create**:

- `src/backend/app/modules/chat/guardrails.py`

**Implementation structure for `guardrails.py`**:

```python
"""
OutputGuardrailChecker — Stage 7b of ChatOrchestrationService pipeline.

PLACEMENT RULE (RULE A2A-01):
Must run AFTER LLM streaming completes (Stage 7) and BEFORE
_persistence.save_exchange() is called (Stage 8).

BUFFERING RULE:
For guardrail-enabled agents (capabilities.guardrails is non-empty),
the orchestrator MUST buffer all LLM chunks — do NOT yield them to the
SSE stream until Stage 7b completes. Then yield the (filtered or replaced)
response. This adds ~1-2s to first-token latency for guardrail-enabled agents
because the full LLM response must complete before delivery.

Default agents (guardrails absent or empty dict): stream chunks live as
today — no buffering, no latency impact.

If action="block": do NOT call save_exchange. Yield guardrail_triggered
SSE event and return canned error. The blocked text must never reach the DB.

If action="redact": replace response_text with redacted version.
Pass redacted text to save_exchange (never the original blocked text).

If filter raises any exception: fail closed. Return canned error.
Never return the unfiltered response on exception.

ENFORCEMENT GAP (acknowledged):
keyword_block rules are bypassable via paraphrase for sophisticated adversaries.
semantic_check rules (embedding similarity against violation exemplar index)
are required for regulated deployments (Bloomberg, CapIQ, Oracle Fusion).
semantic_check is deferred to Phase B follow-up sprint — see TODO-SEMANTIC-CHECK.
Bloomberg guardrail enforcement is INCOMPLETE until semantic_check is calibrated.
Do not communicate Bloomberg agent as fully compliant until TODO-SEMANTIC-CHECK
is resolved.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import structlog

logger = structlog.get_logger(__name__)

_CANNED_BLOCK_RESPONSE = (
    "I cannot provide that information. "
    "Please rephrase your question or contact your administrator."
)

@dataclass
class GuardrailRule:
    rule_id: str
    rule_type: str  # "keyword_block" | "citation_required" | "max_length" | "confidence_threshold"
    patterns: List[str] = field(default_factory=list)
    on_violation: str = "block"  # "block" | "redact" | "warn"
    user_message: Optional[str] = None
    replacement: Optional[str] = None

@dataclass
class FilterResult:
    passed: bool
    rule_id: Optional[str] = None
    reason: Optional[str] = None
    action: str = "pass"  # "pass" | "block" | "redact" | "warn"
    filtered_text: Optional[str] = None
    violation_metadata: Optional[dict] = None

class OutputGuardrailChecker:
    """
    Applies guardrail rules to LLM output text.

    Initialization:
        checker = OutputGuardrailChecker(agent_capabilities, retrieval_confidence)

    Usage:
        result = await checker.check(response_text)
        if not result.passed:
            # Handle based on result.action

    ASYNC SIGNATURE: check() is async from day one to accommodate future
    semantic_check rules that require embedding comparison (async I/O).
    The current implementation is synchronous pattern matching but the async
    interface is required for forward compatibility.
    """

    def __init__(
        self,
        agent_capabilities: dict,
        retrieval_confidence: float = 1.0,
    ):
        guardrails_config = agent_capabilities.get("guardrails", {})
        self._rules = self._compile_rules(guardrails_config)
        self._retrieval_confidence = retrieval_confidence
        self._confidence_threshold = guardrails_config.get("confidence_threshold", 0.0)
        self._max_response_length = guardrails_config.get("max_response_length", 0)

    def _compile_rules(self, guardrails_config: dict) -> List[GuardrailRule]:
        rules: List[GuardrailRule] = []
        for topic in guardrails_config.get("blocked_topics", []):
            rules.append(GuardrailRule(
                rule_id=f"blocked_topic_{topic}",
                rule_type="keyword_block",
                patterns=[r"\b" + re.escape(topic) + r"\b"],
                on_violation="block",
                user_message=_CANNED_BLOCK_RESPONSE,
            ))
        # Template-level guardrails JSONB uses [{pattern, action, reason}] format
        for rule_dict in guardrails_config.get("rules", []):
            rules.append(GuardrailRule(
                rule_id=rule_dict.get("id", "unknown"),
                rule_type=rule_dict.get("type", "keyword_block"),
                patterns=rule_dict.get("patterns", []),
                on_violation=rule_dict.get("action", "block"),
                user_message=rule_dict.get("user_message", _CANNED_BLOCK_RESPONSE),
                replacement=rule_dict.get("replacement"),
            ))
        return rules

    async def check(self, response_text: str) -> FilterResult:
        """
        Async check — synchronous pattern matching today, async I/O in future
        for semantic_check rules. Must complete in <5ms for keyword rules.
        Raises no exceptions — all exceptions are caught and result in fail-closed behavior.
        """
        try:
            # Confidence threshold check
            if (
                self._confidence_threshold > 0
                and self._retrieval_confidence < self._confidence_threshold
            ):
                return FilterResult(
                    passed=False,
                    rule_id="confidence_threshold",
                    reason=f"retrieval_confidence {self._retrieval_confidence:.2f} < threshold {self._confidence_threshold:.2f}",
                    action="redact",
                    filtered_text=(
                        "I was not able to find sufficiently relevant information to answer your question. "
                        "Please try rephrasing or check that the relevant documents have been indexed."
                    ),
                    violation_metadata={"confidence": self._retrieval_confidence, "threshold": self._confidence_threshold},
                )

            # Max response length enforcement
            if self._max_response_length > 0 and len(response_text) > self._max_response_length:
                truncated = self._truncate_at_word_boundary(response_text, self._max_response_length)
                return FilterResult(
                    passed=False,
                    rule_id="max_response_length",
                    reason=f"response length {len(response_text)} exceeds max {self._max_response_length}",
                    action="redact",
                    filtered_text=truncated + " [Response truncated by policy]",
                    violation_metadata={"original_length": len(response_text), "max": self._max_response_length},
                )

            # Keyword block rules
            for rule in self._rules:
                if rule.rule_type != "keyword_block":
                    continue
                for pattern in rule.patterns:
                    if re.search(pattern, response_text, re.IGNORECASE):
                        if rule.on_violation == "redact" and rule.replacement:
                            filtered = re.sub(pattern, rule.replacement, response_text, flags=re.IGNORECASE)
                            return FilterResult(
                                passed=False,
                                rule_id=rule.rule_id,
                                reason=f"pattern matched: {pattern}",
                                action="redact",
                                filtered_text=filtered,
                                violation_metadata={"pattern": pattern},
                            )
                        return FilterResult(
                            passed=False,
                            rule_id=rule.rule_id,
                            reason=f"pattern matched: {pattern}",
                            action=rule.on_violation,
                            filtered_text=rule.user_message or _CANNED_BLOCK_RESPONSE,
                            violation_metadata={"pattern": pattern},
                        )

            return FilterResult(passed=True, action="pass")

        except Exception as exc:
            # Fail closed — never return the unfiltered response on exception
            logger.error(
                "guardrail_checker_exception",
                error=str(exc),
                exc_info=True,
            )
            return FilterResult(
                passed=False,
                rule_id="internal_error",
                reason="guardrail checker raised exception — fail closed",
                action="block",
                filtered_text=_CANNED_BLOCK_RESPONSE,
            )

    @staticmethod
    def _truncate_at_word_boundary(text: str, max_length: int) -> str:
        if len(text) <= max_length:
            return text
        truncated = text[:max_length]
        last_space = truncated.rfind(" ")
        if last_space > max_length * 0.9:
            return truncated[:last_space]
        return truncated
```

**Files to modify**:

- `src/backend/app/modules/chat/orchestrator.py`

**Orchestrator wiring** — conditional buffering based on guardrail config:

The orchestrator must determine at Stage 3 (agent load) whether this agent has guardrails configured. Use this flag to control streaming behavior in Stage 7:

```python
def _has_active_guardrails(guardrails: dict) -> bool:
    """Return True only if at least one enforcement rule is configured.

    v046b previously injected {"guardrails": {"max_response_length": 0}} into
    every agent_cards row, causing bool(capabilities.get("guardrails")) to
    evaluate True for ALL agents and adding 1-2s buffering latency universally.
    This helper guards against that: a guardrails dict with only zero/absent
    values is treated as inactive, keeping the default live-streaming path.
    """
    if not guardrails:
        return False
    return bool(
        guardrails.get("blocked_topics")                       # non-empty list
        or guardrails.get("rules")                             # future rules list
        or guardrails.get("confidence_threshold", 0) > 0      # non-zero threshold
        or guardrails.get("max_response_length", 0) > 0       # non-zero length limit
    )

# Determined after loading agent capabilities in Stage 3:
guardrail_enabled = _has_active_guardrails(capabilities.get("guardrails", {}))

# Stage 7: LLM streaming
if guardrail_enabled:
    # Buffer all chunks — do NOT yield to SSE stream yet.
    # Guardrail check (Stage 7b) requires the complete response.
    # Latency implication: client receives no tokens until full LLM
    # response completes (~1-2s additional wait).
    response_chunks = []
    async for chunk in llm_stream:
        response_chunks.append(chunk)
    response_text = "".join(response_chunks)
else:
    # Default path: stream chunks live as today.
    response_chunks = []
    async for chunk in llm_stream:
        response_chunks.append(chunk)
        yield _format_sse_event("message", {"content": chunk})
    response_text = "".join(response_chunks)
```

After Stage 7, insert Stage 7b before Stage 8:

```python
# Stage 7b: Output guardrail enforcement (RULE A2A-01)
# MUST run before save_exchange. A violation that reaches the DB is a
# compliance incident regardless of what the user sees.
guardrail_result = await OutputGuardrailChecker(
    agent_capabilities=capabilities,
    retrieval_confidence=retrieval_confidence,
).check(response_text)

if not guardrail_result.passed:
    logger.info(
        "guardrail_triggered",
        agent_id=agent_id,
        tenant_id=tenant_id,
        rule_id=guardrail_result.rule_id,
        action=guardrail_result.action,
    )
    # Emit guardrail event before done
    yield _format_sse_event("guardrail_triggered", {
        "rule": guardrail_result.rule_id,
        "action": guardrail_result.action,
    })

    if guardrail_result.action == "block":
        # Yield the safe canned response and stop — do NOT call save_exchange
        yield _format_sse_event("message", {"content": guardrail_result.filtered_text})
        yield _format_sse_event("done", {})
        # Write violation audit log entry
        await _write_guardrail_violation_audit(
            db, agent_id, tenant_id, user_id, guardrail_result
        )
        return  # Exit generator — save_exchange NOT called

    # action == "redact" or "warn": replace response_text and continue to Stage 8
    response_text = guardrail_result.filtered_text or response_text

# For guardrail-enabled agents: now yield the buffered (possibly filtered) response.
# For default agents: chunks were already yielded live above; this block is a no-op.
if guardrail_enabled:
    yield _format_sse_event("message", {"content": response_text})

# Stage 8: persist response_text (which is now filtered/redacted if violation occurred)
await _persistence.save_exchange(
    ...,
    response=response_text,
    guardrail_violations=[guardrail_result.violation_metadata] if not guardrail_result.passed else [],
)
```

**Audit log write** — add helper function:

```python
async def _write_guardrail_violation_audit(
    db: AsyncSession,
    agent_id: str,
    tenant_id: str,
    user_id: str,
    result: FilterResult,
) -> None:
    """
    Writes a guardrail violation to the audit_log table.
    Called only when action="block" — violation was blocked, not stored in conversation.
    The violation_metadata is stored; the original blocked response text is NOT stored
    (it must not reach the DB — RULE A2A-01).
    """
    await db.execute(
        text("""
            INSERT INTO audit_log (tenant_id, user_id, action, resource_type, resource_id, metadata)
            VALUES (:tenant_id, :user_id, 'guardrail_violation', 'agent', :agent_id, CAST(:metadata AS jsonb))
        """),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "metadata": json.dumps({
                "rule_id": result.rule_id,
                "action": result.action,
                "reason": result.reason,
                "violation_metadata": result.violation_metadata,
            }),
        },
    )
    await db.commit()
```

**Conversation persistence extension**: In `_persistence.save_exchange()` (or wherever messages are persisted to `conversation_messages`), extend the metadata JSONB to include:

```python
"guardrail_violations": [violation_metadata, ...]  # list, empty if no violations
```

No schema migration needed — this goes into an existing JSONB column.

**Success criteria**:

- Create agent with `guardrails.blocked_topics = ["investment advice"]`
- Ask agent "give me investment advice" — response must be the canned block message, not LLM output
- `SELECT guardrail_violations FROM conversation_messages WHERE ...` — blocked responses must NOT appear; redacted responses must show `guardrail_violations` with `action="redact"`
- `SELECT action FROM audit_log WHERE action='guardrail_violation'` — one row per blocked response
- Create agent with `guardrails.confidence_threshold = 0.9`. Use a query with low retrieval confidence. Response must be the low-confidence canned message, not the LLM output
- Agent with empty `guardrails` config: chunks stream live (no buffering), latency unchanged
- Agent with non-empty `guardrails` config: no token delivered until full response complete
- `python -m pytest tests/integration/test_guardrail_enforcement.py` passes (including the fail-closed test: a guardrail exception must return the canned error, not raise)

**Risk flag (COC Amnesia)**: The `semantic_check` rule type is required before any Bloomberg/regulated agent is deployed. `keyword_block` rules are bypassable via paraphrase ("the risk/reward asymmetry favors accumulation at current levels" bypasses "investment advice" keyword). Add `TODO-SEMANTIC-CHECK` comment in `OutputGuardrailChecker.__init__` — this is a tracked gap, not an oversight.

**Tests required**:

- `tests/integration/test_guardrail_enforcement.py` — blocked topic, confidence threshold, fail-closed, buffering vs. live streaming behavior

---

### Sprint 4 (Week 6): Guardrail Registration Validation + Credential Deploy Validation

#### Item B3: Guardrail Registration Validation at Template Create/Update

**Gap**: Gap 5 from doc 49. Template create/update endpoints store any string in guardrails JSONB without validating that configured guardrail config keys are recognized.

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Specific changes**:

Add validation to `CreateAgentTemplateRequest` and `UpdateAgentTemplateRequest`:

```python
_VALID_GUARDRAIL_RULE_TYPES = frozenset({
    "keyword_block",
    "citation_required",
    "max_length",
    "confidence_threshold",
    "semantic_check",  # deferred — accepted but logged as TODO-SEMANTIC-CHECK
})

_VALID_GUARDRAIL_ACTIONS = frozenset({"block", "redact", "warn"})

class GuardrailsSchema(BaseModel):
    """
    RULE A2A-02: Storing guardrails in this schema does nothing unless
    ChatOrchestrationService reads and applies them on every request.
    This schema validates structure at write time only.
    Runtime enforcement is in app/modules/chat/guardrails.py Stage 7b.
    """
    blocked_topics: List[str] = Field(default_factory=list, max_items=50)
    confidence_threshold: float = Field(0.0, ge=0.0, le=1.0)
    max_response_length: int = Field(0, ge=0, le=10000)
    rules: List[Dict[str, Any]] = Field(default_factory=list, max_items=20)

    @validator("rules", each_item=True)
    def validate_rule_structure(cls, rule: Dict) -> Dict:
        if "type" not in rule:
            raise ValueError("guardrail rule missing required field 'type'")
        if rule["type"] not in _VALID_GUARDRAIL_RULE_TYPES:
            raise ValueError(
                f"unrecognized guardrail rule type '{rule['type']}'. "
                f"Valid types: {sorted(_VALID_GUARDRAIL_RULE_TYPES)}"
            )
        if "action" in rule and rule["action"] not in _VALID_GUARDRAIL_ACTIONS:
            raise ValueError(
                f"unrecognized guardrail action '{rule['action']}'. "
                f"Valid actions: {sorted(_VALID_GUARDRAIL_ACTIONS)}"
            )
        if "patterns" in rule and not isinstance(rule["patterns"], list):
            raise ValueError("guardrail rule 'patterns' must be a list")
        # Validate each pattern compiles as a regex
        for pattern in rule.get("patterns", []):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid regex pattern '{pattern}': {exc}") from exc
        return rule
```

**Success criteria**:

- `POST /api/v1/platform/agent-templates` with `guardrails.rules=[{"type": "invalid_type"}]` returns 422
- `POST` with `guardrails.rules=[{"type": "keyword_block", "patterns": ["[unclosed"]}]` returns 422 (invalid regex)
- `POST` with valid `keyword_block` rule returns 201
- `python -m pytest tests/unit/test_agent_template_validation.py -k "test_guardrail_validation"` passes

---

#### Item B4: Credential Deploy Validation Against Vault

**Gap**: Gap 3 and 4 from doc 49. `deploy_from_template` must check vault for `required_credentials` when the template's `auth_mode = 'tenant_credentials'` and `required_credentials` is non-empty.

**Note on `platform_credentials` auth mode**: `auth_mode = 'platform_credentials'` is deferred to Phase C. At Phase B, if `auth_mode == 'platform_credentials'` is submitted in a deploy request, return HTTP 422 with message: "platform_credentials auth mode is not yet available. Use tenant_credentials or none." Do not silently accept and discard.

**Files to modify**:

- `src/backend/app/modules/agents/routes.py`

**Files to reference**:

- `src/backend/app/core/secrets/vault_client.py` — `VaultClient.get_secret(path)` and `VaultClient.store_secret(path, value)`

**Specific changes in `deploy_from_template` handler**:

```python
async def _validate_and_store_credentials(
    body: DeployFromTemplateRequest,
    template: AgentTemplate,
    tenant_id: str,
    agent_id: str,
    vault: VaultClient,
) -> Optional[str]:
    """
    Validates that credentials supplied in the deploy request match the
    template's required_credentials schema, then stores each credential
    in vault at path {tenant_id}/agents/{agent_id}/{key}.

    Returns the vault_path_prefix if successful, raises HTTPException(422) if not.

    SSRF note: credential test endpoint URLs in required_credentials must be
    validated via _validate_ssrf_safe_url() before any outbound call is made
    (RULE A2A-04). This function stores credentials only — it does not make
    outbound calls. Credential testing is a separate step.
    """
    if template.auth_mode == "platform_credentials":
        raise HTTPException(
            status_code=422,
            detail=(
                "platform_credentials auth mode is not yet available. "
                "Use tenant_credentials or none."
            ),
        )
    if template.auth_mode != "tenant_credentials":
        return None
    if not template.required_credentials:
        return None

    required_keys = {c["key"] for c in template.required_credentials if c.get("required", True)}
    provided_keys = set(body.credentials.keys()) if body.credentials else set()
    missing = required_keys - provided_keys

    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required credentials: {sorted(missing)}. "
                   f"Template '{template.name}' requires these fields to be provided at deploy time.",
        )

    vault_path_prefix = f"{tenant_id}/agents/{agent_id}"
    for key, value in (body.credentials or {}).items():
        if key in {c["key"] for c in template.required_credentials}:
            await vault.store_secret(f"{vault_path_prefix}/{key}", value)

    return vault_path_prefix
```

Call `_validate_and_store_credentials()` in the deploy handler after the `agent_cards` INSERT. Store the returned `vault_path_prefix` as `credentials_vault_path` on the agent card.

This requires `credentials_vault_path TEXT` column on `agent_cards`. Add to migration v047 (separate from v046a/v046b to avoid migration ordering conflicts).

**Files to create**:

- `src/backend/alembic/versions/v047_agent_cards_vault_path.py`

```python
revision = "047"
down_revision = "046b"

def upgrade() -> None:
    op.add_column(
        "agent_cards",
        sa.Column("credentials_vault_path", sa.Text, nullable=True),
    )

def downgrade() -> None:
    op.drop_column("agent_cards", "credentials_vault_path")
```

**`DeployFromTemplateRequest` schema addition**:

```python
credentials: Optional[Dict[str, str]] = Field(
    None,
    description=(
        "Credential values keyed by the credential 'key' field from the template's "
        "required_credentials schema. Required when template.auth_mode='tenant_credentials'. "
        "Values are stored in vault and never returned by any GET endpoint."
    ),
)
```

**GET endpoint guard**: `get_agent_by_id_db()` must return `has_credentials: bool = credentials_vault_path is not None` — never return the vault path or credential values.

**Success criteria**:

- Deploy template with `auth_mode='tenant_credentials'` and `required_credentials=[{key: "api_key"}]` without providing `credentials`: returns 422 with "Missing required credentials: ['api_key']"
- Deploy with credentials provided: returns 201. `SELECT credentials_vault_path FROM agent_cards WHERE id = :id` returns non-null path
- `GET /api/v1/admin/agents/{id}` returns `has_credentials: true` — no vault path in response
- Deploy with `auth_mode='platform_credentials'`: returns 422 with "not yet available" message
- `python -m pytest tests/integration/test_credential_deploy_validation.py` passes

**Tests required**:

- `tests/integration/test_credential_deploy_validation.py` — missing credentials 422, full credentials 201, platform_credentials 422, GET field exclusion

---

## Phase C — Tool Ecosystem (Weeks 7–10): MCP + Tool Catalog

**Objective**: MCP tool assignments are resolved and injected into the orchestrator context. Tool catalog integration is live. UX authoring surfaces KB bindings, tools, guardrails, and credentials in both the platform template authoring panel and the tenant deploy wizard.

---

### Sprint 5 (Weeks 7–8): Tool Resolver + MCP Redis Cache

#### Item C1: `ToolResolver` — Batched Single Query, No N+1

**Gap**: Gap 2 from doc 49. `tool_ids` stored in `capabilities` JSONB are never read at chat time.

**Note on RLS and degraded tools (H4)**: The existing RLS policy on `tool_catalog` (v026) restricts tenant sessions to `health_status = 'healthy'` only. `ToolResolver` must be able to surface degraded tools (so the orchestrator can warn the user or degrade gracefully). Two options:

1. Run the `tool_catalog` leg of the UNION query with elevated session context (`SET app.is_platform_admin = 'true'` for this specific query).
2. Update the RLS policy in migration v048 to allow tenant `SELECT` of tools where `health_status IN ('healthy', 'degraded')`.

**Decision**: Update RLS in v048 to allow `health_status IN ('healthy', 'degraded')` for tenant sessions. This is cleaner than per-query privilege escalation and matches the intent — tenants should know their tools are degraded, not silently lose them. v048 is added to Phase C scope.

**Files to create**:

- `src/backend/app/modules/chat/tool_resolver.py`

**Implementation**:

```python
"""
ToolResolver — resolves tool_ids from agent capabilities to hydrated tool configs.
Called once per chat request at Stage 0 (pre-pipeline initialization).

Query strategy: single UNION ALL query across tool_catalog and mcp_servers.
One DB round-trip regardless of tool count (max 5 tools per agent in practice).

RLS note: tool_catalog RLS (v026) allows 'healthy' status only by default.
v048 migration extends this to include 'degraded' so degraded tools are visible
to ToolResolver. Without v048, degraded tools are invisible and silently dropped.

SSRF: MCP server endpoint URLs retrieved from mcp_servers are NOT used for
outbound calls in this module. ToolResolver returns configs only. Any outbound
call to an MCP endpoint in a future tool execution layer MUST call
_validate_ssrf_safe_url() from app.modules.registry.a2a_routing before the
HTTP call. This module does not make outbound calls. (RULE A2A-04)
"""
from dataclasses import dataclass
from typing import List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

logger = structlog.get_logger(__name__)

@dataclass
class ResolvedTool:
    tool_id: str
    name: str
    source: str  # "tool_catalog" | "mcp_server"
    endpoint: Optional[str]
    auth_type: Optional[str]
    status: str  # "healthy" | "degraded" | "inactive"

class ToolResolver:
    """
    Resolves tool_ids from agent capabilities to ResolvedTool instances.

    Usage:
        resolver = ToolResolver(db, tenant_id)
        tools = await resolver.resolve(tool_ids)
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        self._db = db
        self._tenant_id = tenant_id

    async def resolve(self, tool_ids: List[str]) -> List[ResolvedTool]:
        if not tool_ids:
            return []

        # Single UNION ALL query — one round-trip for all tools.
        # tool_catalog leg: RLS allows 'healthy' and 'degraded' after v048 migration.
        result = await self._db.execute(
            text("""
                SELECT
                    id::text AS tool_id,
                    name,
                    'tool_catalog' AS source,
                    NULL AS endpoint,
                    NULL AS auth_type,
                    COALESCE(health_status, 'unknown') AS status
                FROM tool_catalog
                WHERE id = ANY(:tool_ids)
                  AND health_status != 'inactive'

                UNION ALL

                SELECT
                    id::text AS tool_id,
                    name,
                    'mcp_server' AS source,
                    endpoint,
                    auth_type,
                    COALESCE(status, 'unknown') AS status
                FROM mcp_servers
                WHERE id = ANY(:tool_ids)
                  AND tenant_id = :tenant_id
                  AND status = 'active'
            """),
            {"tool_ids": tool_ids, "tenant_id": self._tenant_id},
        )

        rows = result.fetchall()
        resolved = []
        for row in rows:
            resolved.append(ResolvedTool(
                tool_id=row.tool_id,
                name=row.name,
                source=row.source,
                endpoint=row.endpoint,
                auth_type=row.auth_type,
                status=row.status,
            ))

        # Log tools that were in tool_ids but not found in either table
        found_ids = {r.tool_id for r in resolved}
        missing = set(tool_ids) - found_ids
        if missing:
            logger.warning(
                "tool_resolution_missing",
                missing_tool_ids=list(missing),
                tenant_id=self._tenant_id,
            )

        return resolved
```

**Orchestrator wiring**: Extend `_get_agent_prompt()` to return `tool_ids` alongside `kb_ids`. In Stage 0 (before the pipeline starts), call `ToolResolver.resolve(tool_ids)` and store resolved tools. Pass them into a future tool execution stage. For Phase C, the resolved tools are injected into the system prompt context as available tool descriptions — actual tool invocation (MCP client calls) is deferred to a follow-on sprint.

**System prompt injection for available tools**: In `prompt_builder.py`, after assembling the base system prompt, if `resolved_tools` is non-empty, append a tools context block:

```
Available tools (use when the query requires real-time data or external actions):
- {tool.name}: {tool.source}, status={tool.status}
```

This is Layer 1 tool awareness — the LLM knows what tools are available. Actual MCP invocation is the Phase C follow-on.

**Success criteria**:

- Create agent with `tool_ids=["tool-abc", "tool-xyz"]` where both exist in `tool_catalog` or `mcp_servers`
- Agent's resolved system prompt includes tool names in the tools context block
- `tool_ids` referencing a non-existent tool: logged as warning, no 500 error
- Degraded tool in `tool_catalog`: visible to ToolResolver (after v048 migration), shown in tools context with `status=degraded`
- `python -m pytest tests/integration/test_tool_resolver.py` passes

**Tests required**:

- `tests/integration/test_tool_resolver.py` — healthy tool visible, degraded tool visible, inactive tool excluded, missing tool logged (no 500)

---

#### Item C2: MCP Tool Config Redis Cache with Invalidation

**Gap**: Gap 4 from doc 49. MCP server configs change rarely (admin action only) but are currently queried from DB on every potential tool resolution path.

**Files to create**:

- `src/backend/app/modules/chat/mcp_resolver.py`

**Implementation**:

```python
"""
MCPToolResolver — Redis-cached MCP server configuration resolver.

Cache key: mingai:{tenant_id}:mcp_tool:{tool_id}
TTL: 300 seconds (5 minutes)
Pattern: build_redis_key(tenant_id, "mcp_tool", tool_id)

Cache invalidation: call invalidate_mcp_tool_cache(tenant_id, tool_id) from
admin/mcp_servers.py on POST (create), DELETE, and status toggle endpoints.
Without cache invalidation, a disabled tool may continue to appear active
for up to 5 minutes after admin action.

Redis key follows established namespace convention (RULE from 51):
All Redis keys for agent-scoped data: mingai:{tenant_id}:{key_type}:{qualifier}
"""
import json
from typing import Optional
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.redis_client import build_redis_key
import structlog

logger = structlog.get_logger(__name__)

_MCP_TOOL_CACHE_TTL = 300  # 5 minutes

async def get_mcp_tool_config(
    tool_id: str,
    tenant_id: str,
    redis: Redis,
    db: AsyncSession,
) -> Optional[dict]:
    """
    Returns MCP server config for tool_id scoped to tenant_id.
    Cache-first. DB fallback on cache miss with 300s TTL write-back.
    Returns None if tool not found or inactive.
    """
    cache_key = build_redis_key(tenant_id, "mcp_tool", tool_id)

    cached = await redis.get(cache_key)
    if cached is not None:
        return json.loads(cached)

    result = await db.execute(
        text("""
            SELECT id::text AS id, name, endpoint, auth_type, status
            FROM mcp_servers
            WHERE id = :tool_id AND tenant_id = :tenant_id AND status = 'active'
        """),
        {"tool_id": tool_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        # Cache the miss to avoid repeated DB queries for non-existent tools
        await redis.setex(cache_key, _MCP_TOOL_CACHE_TTL, json.dumps(None))
        return None

    config = {
        "id": row.id,
        "name": row.name,
        "endpoint": row.endpoint,
        "auth_type": row.auth_type,
        "status": row.status,
    }
    await redis.setex(cache_key, _MCP_TOOL_CACHE_TTL, json.dumps(config))
    return config


async def invalidate_mcp_tool_cache(
    tenant_id: str,
    tool_id: str,
    redis: Redis,
) -> None:
    """
    Called by admin/mcp_servers.py on create, delete, and status toggle.
    Delete (not expire) for immediate invalidation.
    """
    cache_key = build_redis_key(tenant_id, "mcp_tool", tool_id)
    await redis.delete(cache_key)
    logger.info("mcp_tool_cache_invalidated", tenant_id=tenant_id, tool_id=tool_id)
```

**Files to modify**:

- `src/backend/app/modules/admin/mcp_servers.py`

Add `invalidate_mcp_tool_cache()` calls after:

1. `POST /admin/mcp-servers` create handler (after DB commit)
2. `DELETE /admin/mcp-servers/{id}` handler (after DB commit)
3. `PATCH /admin/mcp-servers/{id}/status` toggle handler (after DB commit)

**Success criteria**:

- Create MCP server. First `get_mcp_tool_config()` call: DB hit, cache miss logged. Second call within 300s: cache hit, no DB query
- Delete MCP server. Immediate subsequent `get_mcp_tool_config()` call: returns None (cache invalidated, DB confirms deletion)
- Redis key follows `mingai:{tenant_id}:mcp_tool:{tool_id}` exactly — verified against `build_redis_key()` output
- `python -m pytest tests/integration/test_mcp_resolver.py` passes

**Tests required**:

- `tests/integration/test_mcp_resolver.py` — cache hit path, cache miss + write-back, delete invalidation, key format assertion

---

### Sprint 6 (Weeks 9–10): UX — Platform Template Authoring Panel + Tenant Deploy Wizard

#### Item C3: Platform Admin Template Authoring Slide-In Panel (UX)

**Gap**: UX spec from doc 16/02 Section 2. The existing `pa-panel-templates` table has edit rows but the slide-in panel is missing Sections 3 (Authentication), 4 (Plan & Access Gate), and 5 (Tool Assignments) from the spec.

**File to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Sections to add to the template authoring slide-in panel** (follow existing slide-in panel pattern in prototype):

**Section 3 — Authentication** (new):

- `auth_mode` radio group: None / Tenant Credentials / Platform Credentials
- When `auth_mode = none`: credential schema table hidden entirely
- When `auth_mode = tenant_credentials`: credential schema table visible with columns Key, Label, Type, Sensitive, and `[+ Add Credential Field]` inline add button
- Credential field rows: `key` slug (auto-generated from label), `label`, `type` (string/url/oauth2), `sensitive` boolean toggle
- Data: DM Mono 12px for key slugs; Plus Jakarta Sans for labels

**Section 4 — Plan & Access Gate** (new):

- `plan_required` dropdown: None / Starter / Professional / Enterprise
- Informational `capabilities` chip input (what the agent can do)
- Informational `cannot_do` chip input (what the agent is restricted from)

**Section 5 — Tool Assignments** (new):

- Checkbox list of tools from tool catalog
- Each row: checkbox, tool name, classification badge (Read-Only = accent dot, Write = warn lightning icon), health status colored per design system rules
- Degraded tools: `--warn` health label, still assignable
- Info note: "Tools must be registered in Tool Catalog first."

**Design rules** (from design-system.md and doc 16/02):

- Section headings: 11px, uppercase, letter-spacing .06em, `--text-faint`
- Credential schema table: same `th` / `td` rules as admin tables — `th` 11px uppercase, `td` 13px, row hover `accent-dim`
- Radio group: standard form radio, `--accent` on selected state
- All section content uses card padding: `20px` internal, `--border` separator lines between sections
- Chip input for capabilities/cannot_do: outlined neutral style (never filled with accent-dim at idle)

**State transitions** (from doc 16/02 Section 2.4):

- Draft → Published: "Publish" button is primary CTA (accent green)
- Published → "Publish New Version": opens version metadata modal, then triggers push notifications to affected tenants
- Published → Deprecated: grayed-out row, no Edit action, only View/Restore

**Success criteria**:

- Platform admin can create a template with `auth_mode = tenant_credentials` and add credential fields inline
- Platform admin can assign tools from the checkbox list in Section 5
- Plan gate dropdown persists selection and displays it in the template catalog
- Deprecated templates show `status-suspended` badge style (not primary/accent)

---

#### Item C4: Tenant Admin 4-Step Deploy Wizard (UX)

**Gap**: UX spec from doc 16/02 Section 3. The existing deploy flow is a single form. The spec requires a 4-step wizard that adapts its step count based on `auth_mode` and template properties.

**File to modify**:

- `workspaces/mingai/99-ui-proto/index.html`

**Wizard structure** (from doc 16/02 Section 3.2):

The wizard uses the existing wizard/step modal pattern: `max-width: 640px`, `border-radius: var(--r-lg)`, progress bar top with accent fill, "Step N of M" label, footer [Back ghost] + [Next primary] + [x close].

**Step 1 — Identity & Context**:

- Pre-filled display name from template (editable)
- Tenant context textarea for `{{tenant_context}}` variable (if template has it)
- If template has no variables: display name only, step collapses to minimal form
- Dynamic step count displayed in "Step 1 of N" based on template properties

**Step 2 — Credentials** (only when `auth_mode = tenant_credentials`):

- Fields rendered dynamically from `template.required_credentials` array
- Sensitive fields (`sensitive: true`): `<input type="password">` with show/hide eye toggle
- "Test Connection" button: idle (outlined neutral) → testing (spinner + "Validating...") → passed (accent check + masked account info) → failed (alert X + error message + "Retry")
- Untested state: warn-colored note permanently visible (no test button)
- Note: this step is skipped for `auth_mode = none` and `auth_mode = platform_credentials`
- Wizard step count and progress bar update accordingly

**Step 3 — Knowledge Bases & Tools**:

- KB checkbox list: KB name (Plus Jakarta Sans 13px/500), source path (11px faint), doc count (DM Mono 11px)
- Search Mode radio: Parallel / Priority Order
- Tools subsection: only shown if template has assigned tools. Toggle checkboxes per tool. Degraded tools show `--warn` health label
- Empty KB state: "No knowledge bases configured. [Go to Documents]"
- Empty tools state: tools section hidden entirely

**Step 4 — Access & Limits** (final step, CTA changes to "Deploy Agent"):

- Access control radio: All workspace users / Specific roles (chip input) / Specific users (search input)
- Rate limits: DM Mono input, inline error if exceeds plan max
- Guardrails (custom agents only): confidence threshold, citation mode, max output tokens — read-only for library agents with note "Guardrails are managed by the platform template"

**Wizard adaptation table** (from doc 16/02 Section 3.3):

| Template Property                 | Step Count | Skipped Steps                                   |
| --------------------------------- | ---------- | ----------------------------------------------- |
| `auth_mode: none`, no variables   | 2 steps    | Identity context collapsed, credentials skipped |
| `auth_mode: none`, has variables  | 3 steps    | Credentials skipped                             |
| `auth_mode: tenant_credentials`   | 4 steps    | None                                            |
| `auth_mode: platform_credentials` | 3 steps    | Credentials skipped                             |

**Success criteria**:

- Tenant adopts a template with `auth_mode = none`: wizard shows 2–3 steps (no credentials step)
- Tenant adopts a template with `auth_mode = tenant_credentials`: wizard shows 4 steps, Step 2 is credentials
- Credential "Test Connection" button transitions through all 4 states (idle, testing, passed, failed)
- Deploy button on final step triggers deployment with `guardrail_triggered` SSE handling (show canned message instead of raw LLM output when guardrail fires)
- Agent card after deploy shows KB count badge, tool count badge (if tools > 0), credential health badge (if `auth_mode != none`)

---

## Migration Summary

| Migration                                 | Tables Affected                                                             | Type                                          | Phase | Sprint   |
| ----------------------------------------- | --------------------------------------------------------------------------- | --------------------------------------------- | ----- | -------- |
| v045_agent_templates_required_credentials | `agent_templates`                                                           | ALTER TABLE (3 columns + 2 CHECK constraints) | A     | Sprint 1 |
| v046a_gin_index_capabilities_kb_ids       | `agent_cards` (GIN index only)                                              | CREATE INDEX (no CONCURRENTLY — table small)  | A     | Sprint 2 |
| v046b_agent_access_control_backfill       | `agent_access_control` (data backfill) + `agent_cards` (guardrails default) | DML only                                      | A     | Sprint 2 |
| v047_agent_cards_vault_path               | `agent_cards`                                                               | ALTER TABLE (1 column)                        | B     | Sprint 4 |
| v048_tool_catalog_rls_degraded            | `tool_catalog` (RLS policy update)                                          | RLS policy update                             | C     | Sprint 5 |

**v046 split rationale**: `CREATE INDEX CONCURRENTLY` cannot run inside an Alembic transaction (DDL). Mixing DDL with DML in a single transactional migration is error-prone. v046a contains DDL only; v046b contains DML only. This is the correct pattern for any future migration that combines index creation with data backfill.

**Migration ordering rule**: v045 → v046a → v046b → v047 → v048. v047 depends on v046b (same sequential chain). v048 is independent of v047 but must follow it to maintain sequence.

**Rollback safety**: All migrations are reversible via `downgrade()`. v046b's data migration (inserting `workspace_wide` access control rows and guardrail defaults) is left in place on downgrade — the rows are safe to leave.

---

## Dependency Graph

```
Item A1 (v045 migration) ──────────────────────── (independent, first in chain)
Item A2 (access control population) ────────────── (independent of A1 schema)
Item A3 (KB bindings runtime) ──────────────────── (independent of A1 schema)
Item A4 (access control enforcement) ── depends on A2 (rows must exist to check)

Item B1 (/.well-known/agent.json) ──────────────── (independent)
Item B2 (guardrail enforcement) ── depends on A1 (auth_mode + capabilities), v046b (guardrail defaults)
Item B3 (guardrail validation) ── depends on B2 (needs OutputGuardrailChecker types)
Item B4 (credential deploy validation) ── depends on A1 (required_credentials columns)

Item C1 (ToolResolver) ── depends on A3 (capabilities extracted in same round-trip), v048 (RLS for degraded)
Item C2 (MCP Redis cache) ── depends on C1 (MCPToolResolver is used by ToolResolver)
Item C3 (platform authoring UX) ── depends on A1 (auth_mode/plan_required fields)
Item C4 (deploy wizard UX) ── depends on B2 (guardrail SSE handling), B4 (credentials step)
```

**Critical path**: A1 → A2 → A4 → B2 → B3 → B4 → C1 → C2 (all sequential) is the main chain. A3 and B1 can be developed in parallel with any of the above items.

---

## Success Criteria by Phase

### Phase A Complete (end of Week 3)

- [ ] `POST /api/v1/agents/templates` returns 201 with `auth_mode`, `plan_required`, `required_credentials` fields persisted — verified by GET
- [ ] Every agent deploy creates an `agent_access_control` row — verified by direct DB SELECT after deploy
- [ ] Deploy with `access_control != 'workspace'` or `kb_ids` non-empty returns HTTP 422 — no silent discard
- [ ] Two KB-bound agents query different indexes — verified by doc isolation test (HR agent does not surface procurement docs)
- [ ] User without required role cannot invoke a role-restricted agent (403 from orchestrator)
- [ ] `SELECT action FROM audit_log WHERE action='guardrail_violation'` is populated after triggering a blocked topic
- [ ] v045, v046a, and v046b migrations run cleanly on a fresh DB and roll back cleanly
- [ ] All 4 existing seed templates retain `auth_mode='none'`, `required_credentials=[]` after v045
- [ ] `tests/integration/test_agent_deploy_access_control.py` passes
- [ ] `tests/integration/test_kb_binding_resolution.py` passes

### Phase B Complete (end of Week 6)

- [ ] `GET /.well-known/agent.json` returns HTTP 200 without auth; response contains no `system_prompt`, `tenant_id`, `kb_bindings`
- [ ] Agent with `blocked_topics=["investment advice"]`: asking about investment advice returns canned block message — verified end-to-end
- [ ] Guardrail violation with `action=block`: message NOT in `conversation_messages`; violation IS in `audit_log`
- [ ] Guardrail violation with `action=redact`: redacted text IS in `conversation_messages`; `guardrail_violations` metadata populated
- [ ] OutputGuardrailChecker exception: returns canned error, never original LLM output
- [ ] Agent with empty guardrails: SSE streams live (no buffering), latency unchanged
- [ ] Agent with non-empty guardrails: no token delivered until full LLM response completes
- [ ] Invalid guardrail rule type in template create/update: returns 422 with the unrecognized type name
- [ ] Deploy template with `auth_mode=tenant_credentials` and missing required credential: returns 422
- [ ] Deploy template with all required credentials: `credentials_vault_path` set on agent card; GET response shows `has_credentials=true`, not the path value
- [ ] Deploy with `auth_mode=platform_credentials`: returns 422 with "not yet available" message
- [ ] v047 migration runs cleanly
- [ ] `tests/integration/test_a2a_discovery.py` passes
- [ ] `tests/integration/test_guardrail_enforcement.py` passes
- [ ] `tests/integration/test_credential_deploy_validation.py` passes

### Phase C Complete (end of Week 10)

- [ ] Agent with `tool_ids` assigned: resolved tool names appear in system prompt context block
- [ ] Non-existent `tool_id` in capabilities: logged as warning, no 500 error, pipeline continues
- [ ] Degraded tool visible to ToolResolver (v048 RLS update deployed)
- [ ] MCP server create → immediate cache population. MCP server delete → immediate cache invalidation verified by `redis.get(key)` returning None
- [ ] Redis key format is `mingai:{tenant_id}:mcp_tool:{tool_id}` — verified by key inspection
- [ ] Platform admin slide-in panel: can save template with `auth_mode`, `required_credentials`, `plan_required`, tool assignments
- [ ] Tenant deploy wizard: 4 steps for `auth_mode=tenant_credentials`, 3 steps for `auth_mode=none` with variables
- [ ] Credential test button transitions: idle → testing → passed/failed with correct visual states
- [ ] `tests/integration/test_tool_resolver.py` passes
- [ ] `tests/integration/test_mcp_resolver.py` passes

---

## Risk Register

| Risk                                                          | Probability                               | Impact                                            | Phase | Mitigation                                                                                                                           |
| ------------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------ |
| KB binding fan-out hits non-existent index                    | High (orphaned JSONB references possible) | Medium (500 during search)                        | A     | `_search_single_index` catches exceptions and logs; never raises on missing index                                                    |
| Guardrail `keyword_block` bypassed via paraphrase             | High (any sophisticated user)             | High (compliance gap for Bloomberg)               | B     | `TODO-SEMANTIC-CHECK` comment in code; do not communicate Bloomberg as fully compliant until semantic_check is calibrated            |
| Credential health check duplicate runs on multi-worker deploy | Medium                                    | Medium (duplicate notifications)                  | C     | `DistributedJobLock(f"cred_health:{tenant_id}", ttl_seconds=86000)` (RULE A2A-05) — implement before any credential health job lands |
| Output filter placement drifts to post-Stage-8 on refactor    | Low (convention drift)                    | Critical (SOC 2 violation)                        | B     | RULE A2A-01 encoded in `orchestrator.py` Stage list docstring + `AgentOutputFilter` class docstring                                  |
| `agent_cards` UPDATE missing `tenant_id` predicate            | Low (convention drift)                    | Critical (cross-tenant access control override)   | A     | RULE A2A-06 encoded as comment block in `_AGENT_UPDATE_SQL`                                                                          |
| v046a GIN index creation blocks table during migration        | Low (small table, no CONCURRENTLY)        | Low (brief lock at migration time, acceptable)    | A     | Plain `CREATE INDEX` without CONCURRENTLY — lock duration is brief for small table at migration time                                 |
| A2A discovery endpoint enumerated for agent IDs               | Low (requires knowing agent IDs)          | Low (platform-level card only, no per-agent data) | B     | Platform-level card only, no agent enumeration. Per-agent discovery requires auth. Rate limit: 60 req/min per IP.                    |
| Agents with non-zero max_response_length truncated after B2   | Medium (schema default was 2000)          | High (unintended behavior change)                 | B     | v046b sets max_response_length=0 for agents with absent guardrails key. Pre-deploy audit query documented in Item A4.                |
| tool_catalog degraded tools invisible to ToolResolver         | Medium (RLS blocks by default)            | Medium (silent tool drop)                         | C     | v048 extends RLS to allow 'degraded' status. Documented in Item C1.                                                                  |

---

## Files Created / Modified Summary

### New Files

| File                                                                        | Purpose                                                                        | Phase |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ----- |
| `src/backend/alembic/versions/v045_agent_templates_required_credentials.py` | Adds `required_credentials`, `auth_mode`, `plan_required` to `agent_templates` | A     |
| `src/backend/alembic/versions/v046a_gin_index_capabilities_kb_ids.py`       | GIN index on `capabilities->'kb_ids'` (DDL only, no CONCURRENTLY)              | A     |
| `src/backend/alembic/versions/v046b_agent_access_control_backfill.py`       | Access control backfill + guardrail defaults DML                               | A     |
| `src/backend/alembic/versions/v047_agent_cards_vault_path.py`               | Adds `credentials_vault_path` to `agent_cards`                                 | B     |
| `src/backend/alembic/versions/v048_tool_catalog_rls_degraded.py`            | Extends tool_catalog RLS to allow 'degraded' health_status for tenants         | C     |
| `src/backend/app/modules/discovery/__init__.py`                             | Package init                                                                   | B     |
| `src/backend/app/modules/discovery/routes.py`                               | `/.well-known/agent.json` root-level router                                    | B     |
| `src/backend/app/modules/chat/guardrails.py`                                | `OutputGuardrailChecker`, `GuardrailRule`, `FilterResult`                      | B     |
| `src/backend/app/modules/chat/tool_resolver.py`                             | `ToolResolver` — batched UNION ALL query                                       | C     |
| `src/backend/app/modules/chat/mcp_resolver.py`                              | `MCPToolResolver` — Redis cache + DB fallback                                  | C     |

### Modified Files

| File                                             | Changes                                                                                                                                                                                                                       | Phase |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| `src/backend/app/modules/agents/routes.py`       | v045 schema fields in Pydantic models + allowlists; `_ACCESS_CONTROL_MAP` constant; access control INSERT in all 3 deploy paths; 422 gate; guardrail validation; credential deploy validation; platform_credentials 422 guard | A + B |
| `src/backend/app/modules/chat/vector_search.py`  | `_search_single_index()` private method extracted; `search()` accepts `kb_ids`, fan-out to multiple indexes, parallel execution, merge                                                                                        | A     |
| `src/backend/app/modules/chat/prompt_builder.py` | `_get_agent_prompt()` returns `kb_ids` + `tool_ids` in same DB round-trip                                                                                                                                                     | A + C |
| `src/backend/app/modules/chat/orchestrator.py`   | Stage 7b insertion with conditional buffering (`guardrail_enabled` flag), `_check_agent_access()`, pass `kb_ids` to VectorSearchService                                                                                       | A + B |
| `src/backend/app/main.py`                        | Mount `well_known_router` at root level (before `/api/v1` router)                                                                                                                                                             | B     |
| `src/backend/app/modules/admin/mcp_servers.py`   | `invalidate_mcp_tool_cache()` calls on create/delete/status toggle                                                                                                                                                            | C     |
| `src/backend/.env.example`                       | Add `PUBLIC_BASE_URL`                                                                                                                                                                                                         | B     |
| `workspaces/mingai/99-ui-proto/index.html`       | Template authoring slide-in Sections 3–5; 4-step deploy wizard                                                                                                                                                                | C     |

---

## Red-Team Validation (2026-03-21)

**Status**: Reviewed by deep-analyst. 4 CRITICAL, 6 HIGH, 5 MEDIUM findings — all addressed in v1.1.

### Findings addressed in this revision

| ID  | Severity | Finding                                         | Resolution                                                                                                                                                                                                                                  |
| --- | -------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1  | CRITICAL | Stage 7.5 guardrail runs after chunks yielded   | Conditional buffering added — guardrail-enabled agents buffer full response before first token delivered; `_has_active_guardrails()` helper controls streaming mode (guards against zero-value dicts injected by migration artifacts)       |
| C2  | CRITICAL | `access_control` enum mismatch with DB CHECK    | `_ACCESS_CONTROL_MAP` constant added at module level; applied in all three deploy paths                                                                                                                                                     |
| C3  | CRITICAL | `_search_single_index` method didn't exist      | Sub-task A3.0 added: refactor `VectorSearchService.search()` to extract `_search_single_index()` first; public `search()` signature corrected to accept `query_vector: list[float]`, not `query: str`                                       |
| C4  | CRITICAL | 422 guard used `body.access_mode` (wrong field) | Corrected to `body.access_control` throughout Item A2                                                                                                                                                                                       |
| H1  | HIGH     | `CREATE INDEX CONCURRENTLY` inside transaction  | v046 split into v046a (DDL, no CONCURRENTLY) + v046b (DML). `op.create_index()` without CONCURRENTLY used in v046a                                                                                                                          |
| H2  | HIGH     | v046 mixed DDL and DML                          | Split into v046a + v046b; migration summary and dependency graph updated                                                                                                                                                                    |
| H3  | HIGH     | No test files specified                         | "Tests required" subsection added to each Phase A, B, and C item with exact file paths                                                                                                                                                      |
| H4  | HIGH     | `tool_catalog` RLS hides degraded tools         | v048 migration added to Phase C; ToolResolver docstring documents the RLS issue and fix                                                                                                                                                     |
| H5  | HIGH     | `VARCHAR[]` type coercion safety                | `list(row.allowed_roles or [])` and `list(row.allowed_user_ids or [])` coercions added in `_check_agent_access()` and access control INSERT                                                                                                 |
| H6  | HIGH     | `OutputGuardrailChecker.check()` sync signature | Changed to `async def check(...)` with comment explaining forward-compatibility rationale                                                                                                                                                   |
| M1  | MEDIUM   | No rate limit on well-known endpoint            | Rate limit (60 req/min per IP) added to Item B1 and success criteria                                                                                                                                                                        |
| M2  | MEDIUM   | `platform_credentials` mode silently accepted   | 422 guard added in `_validate_and_store_credentials()` for Phase B; deferred full implementation to Phase C                                                                                                                                 |
| M3  | MEDIUM   | Existing agents with default guardrail values   | Pre-deploy audit query documented in Item A4; v046b leaves the `guardrails` key ABSENT for agents never explicitly configured — injecting `{"max_response_length": 0}` was the root cause of the V1 latency regression and has been removed |
| M5  | MEDIUM   | Gap number cross-references incorrect           | B1 → Gap 6, B2 → Gap 5, B4 → Gap 3+4 corrected throughout                                                                                                                                                                                   |

### Outstanding deferred items

- **Gap 7 (template update notifications)**: Push notifications to affected tenants when a template publishes a new version — deferred to Phase B Sprint 5. Referenced in Item C3 state transitions but not yet implemented.
- **Gap 8 (credential health check job)**: Scheduled per-tenant job to verify stored credentials against vault — deferred to Phase C Sprint 8. RULE A2A-05 (DistributedJobLock) is documented in anticipation.
- **`platform_credentials` auth_mode**: Full implementation deferred to Phase C. Phase B returns 422 with "not yet available" message.
- **v048 RLS update for degraded tool visibility**: Added to Phase C Sprint 5 scope. Required before ToolResolver can surface degraded tools to tenant sessions.
- **`TODO-SEMANTIC-CHECK`**: Semantic guardrail rules (embedding similarity against violation exemplars) deferred to Phase B follow-up sprint. Bloomberg agent must not be communicated as fully compliant until this is resolved.

---

**Document Version**: 1.1
**Last Updated**: 2026-03-21
**Sources**: docs 49, 50, 51, 52, 16/01, 16/02
**Next action**: Sprint 1 — Item A1 (v045 migration) unblocks Items A2, A4, B4. Item A3 (KB runtime resolution, beginning with Sub-task A3.0 refactor of `_search_single_index`) can start in parallel on day 1.
