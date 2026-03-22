# 51. Agent Template A2A Compliance Gaps — COC Fault-Line Analysis

> **Status**: Architecture Analysis
> **Date**: 2026-03-21
> **Purpose**: Apply COC (Cognitive Orchestration for Codegen) methodology to the 10 compliance gaps in the agent template A2A system. Identify amnesia, convention drift, and security blindness risks. Capture institutional knowledge as explicit CLAUDE.md-style rules.
> **Depends on**: `33-agent-library-studio-architecture.md`, `25-a2a-guardrail-enforcement.md`
> **Source code examined**: `app/modules/agents/routes.py`, `app/modules/chat/orchestrator.py`, `app/modules/registry/a2a_routing.py`

---

## COC Framework Applied Here

COC identifies three failure modes that afflict AI-assisted codegen on production systems:

- **Amnesia**: The "why" behind a decision is not encoded anywhere in the codebase. The next codegen session (or junior engineer) sees the "what" but not the reason. They change it. The system breaks.
- **Convention drift**: AI defaults to internet patterns instead of established project conventions. The codebase has `job_run_context`, `DistributedJobLock`, RLS via `tenant_id`, and a specific 8-stage pipeline. Codegen that doesn't know these will introduce parallel conventions that undermine isolation guarantees.
- **Security blindness**: AI takes the shortest path. Shortest path for credentials is to accept them and store them (or drop them silently). Shortest path for a public discovery endpoint is to return everything. Shortest path for an outbound HTTP call is to make it without SSRF validation.

The 10 gaps in the agent template system are not random — they cluster precisely along these three fault lines.

---

## 1. Amnesia Risks

### 1.1 The "Why" Behind Guardrail 3-Layer Ordering

**What is known** (documented in `25-a2a-guardrail-enforcement.md`):
Layer 1 (system prompt positioning) places guardrails last. Layer 2 (output filter) provides hard enforcement. Layer 3 (registration audit) is a one-time pre-production gate.

**What will be forgotten**:

The ordering is not arbitrary aesthetics. The specific rationale that will be lost on re-implementation:

- Layer 1 is a **soft drift-reducer only** — the architecture document states explicitly that "the entire hard enforcement burden rests on Layer 2." If a future codegen session sees Layer 1 working and assumes it is sufficient, it will skip Layer 2. The platform then has zero hard enforcement with the appearance of compliance. This is the most dangerous amnesia scenario because the system will appear to work in normal operation and fail only under adversarial conditions.

- The ordering Base → Glossary → Tenant Extension → Guardrails is not negotiable. Reversing it (putting guardrails before the tenant extension) reduces guardrail effectiveness because later content in LLM system prompts exerts stronger positional influence. Codegen that does not know this will naturally write the "readable" order (identity → constraints → customisation) and inadvertently reduce enforcement probability.

- The `semantic_check` rule type is a **required gap-closer** for regulated deployments. The `keyword_block` rules in `BLOOMBERG_GUARDRAILS` are bypassable via paraphrase. A future codegen session implementing a simpler version of the filter will include only the keyword rules, log them as "guardrails implemented," and ship an enforcement gap that the Bloomberg financial services contracts require to be closed.

**Encoding location for this knowledge**: The `AgentOutputFilter.__init__` docstring and the guardrail rule compiler must contain the explicit statement that `keyword_block` alone is insufficient for financial services use cases and that `semantic_check` must be implemented and calibrated before any regulated agent goes to production.

### 1.2 Token Budget Constraints That Affect Prompt Positioning

**What is known**: The orchestrator (`orchestrator.py`) calls `get_tenant_token_budget()` at Stage 6 before building the system prompt. The canonical token budget is 550 tokens of overhead (org context 100, team working memory 150, profile 200, working memory 100), leaving 1,450 tokens for RAG at the 2K limit.

**What will be forgotten**:

The guardrail block is added last in `build_agent_system_prompt()` — which means it competes for the tail of the token budget. If the RAG retrieval is large or the tenant extension is verbose, the guardrail block may be truncated by the model's context window. The architecture currently has no explicit token reservation for the guardrail block.

Codegen implementing the prompt assembly will not know to reserve a fixed token allocation for the guardrail block before allocating tokens to RAG context. The natural implementation is: "fill everything else, then append guardrails." Under load with a large knowledge base, this is the equivalent of having no guardrails at all for verbose queries.

**Critical decision to preserve**: The guardrail block must be token-budget-exempt — it is subtracted from the available overhead before any other allocation. This is a platform compliance requirement, not a performance optimisation.

### 1.3 SSRF Protection Logic for A2A Endpoints

**What is known**: `a2a_routing.py` implements `_validate_ssrf_safe_url()` which resolves the hostname via DNS and checks it against `_BLOCKED_NETWORKS` before making any outbound HTTP call. The design comment says this is "defence-in-depth applied before outbound HTTP requests in the A2A routing and health-check pipelines."

**What will be forgotten**:

The DNS-resolution check is deliberately performed at request time, not at endpoint registration time. The reason: a hostile agent operator could register a safe-looking public IP, then change its DNS record to point to an internal metadata endpoint after registration passes. The check must happen on every outbound call, not once at registration.

Any codegen that "optimises" this by moving SSRF validation to registration time will introduce a DNS rebinding attack surface. Future sessions will read the `_validate_ssrf_safe_url()` call, see it on every request, judge it "wasteful," and move it to a one-time setup check. The system will then be vulnerable to operators who control their own DNS.

**Encoding location**: The `_validate_ssrf_safe_url()` docstring must state explicitly that the per-request check is mandatory and that moving it to registration time is a known vulnerability pattern.

### 1.4 `CredentialTestResult.passed = None` Semantics

**What is known** (documented in `33-agent-library-studio-architecture.md` §8 and the R23 changelog): When no credential test class is registered for a template, `passed` defaults to `None` — not `True`. The comment states "untested is not the same as valid."

**What will be forgotten**:

Any codegen checking `if result.passed:` will treat `None` as falsy and route to the failure branch — correctly rejecting the integration. But any codegen checking `if result.passed is True:` will accept only verified credentials, and any codegen checking `if not result.passed:` will also treat `None` as a failure and block the adoption flow entirely.

The semantics are: `None` means "untested — proceed but surface the ambiguity to the user." The UI must distinguish three states (passed / failed / untested) not two. Codegen that binary-treats this field will either silently block valid untested integrations or silently pass invalid ones.

---

## 2. Convention Drift Risks

### 2.1 The `job_run_context` / `DistributedJobLock` Pattern

The codebase uses `DistributedJobLock` (via Redis) for all scheduled background jobs, with `job_run_context` providing idempotency tokens. These patterns exist in the distributed job scheduling infrastructure (`47-background-job-scheduling-architecture.md`).

**Gap**: The daily credential health check (`run_daily_credential_health_check()` in `33-agent-library-studio-architecture.md` §8.1) is specified as a "daily scheduled job" but the implementation pattern is undefined. Codegen implementing this will use whatever job scheduling pattern it knows from the internet (Celery, APScheduler, cron) rather than the project's established `DistributedJobLock` pattern.

**What breaks if conventions drift**: The credential health check runs once per tenant per day. Without `DistributedJobLock`, if multiple worker instances are running (which they are in production), all instances will run the check simultaneously, multiplying the vault read load and the notification volume — admins will receive duplicate alerts for every expired credential.

**Convention to enforce**: All scheduled per-tenant jobs must use `DistributedJobLock(f"cred_health:{tenant_id}", ttl_seconds=86000)` before executing. If the lock is already held, the worker exits silently. This is the pattern established by all other background jobs in the codebase.

### 2.2 RLS via `tenant_id` in All Agent Queries

The codebase enforces multi-tenant isolation through explicit `tenant_id` predicates on all database queries. The agent routes file (`routes.py`) follows this pattern throughout — every query against `agent_cards` includes `AND tenant_id = :tenant_id`.

**Gap**: The adoption flow creates `AgentInstance` records from platform templates. The `deploy_agent_template_db()` call in routes.py line 627 passes `tenant_id=current_user.tenant_id`. But the `access_control` and `kb_ids` fields from the `DeployAgentRequest` body are **silently discarded** (lines 639-651 contain the explicit warning comment: "values would be silently discarded").

**What breaks if conventions drift**: Codegen implementing the missing schema migration for `access_control` and `kb_ids` on `agent_cards` will add columns and an update statement. If it follows the pattern carelessly, it may write a query without the `tenant_id` WHERE clause on the UPDATE path — allowing a tenant admin to overwrite access control for a different tenant's agent via a crafted request.

**Convention to enforce**: Every write to `agent_cards` must include `tenant_id = :tenant_id` in the WHERE clause, not just in the initial INSERT. The update path in `_AGENT_UPDATE_SQL` currently omits `access_control` and `kb_mode` from the column map — adding them without the tenant isolation predicate is the specific failure mode to prevent.

### 2.3 Redis Cache Key Namespace

The project uses a strict Redis key namespace pattern: `agent:{tenant_id}:{instance_id}`. The orchestrator code, the agent cache, and the pub/sub invalidation all rely on this prefix structure for tenant-scoped isolation.

**Gap**: The credential health check will need to cache its results (to avoid re-checking credentials for agents that were just verified). Codegen implementing this cache will likely use a key like `cred_health:{instance_id}` — omitting the `tenant_id` prefix.

**What breaks**: Without the tenant prefix, a cache collision becomes possible between two tenants whose agent IDs share the same UUID collision space (extremely unlikely but architecturally unsound). More practically, the cache invalidation on agent archival will not clear the credential health cache if the keys have different namespaces.

**Convention to enforce**: All Redis keys for agent-scoped data must follow `agent:{tenant_id}:{instance_id}:{qualifier}`. Credential health cache keys must be `agent:{tenant_id}:{instance_id}:cred_health`.

### 2.4 The 8-Stage Pipeline Is a Sealed Boundary

The `ChatOrchestrationService` in `orchestrator.py` is an 8-stage pipeline. The guardrail output filter (Layer 2) is specified to run "after the agent produces its response and before the Artifact is returned to the orchestrator."

**Gap**: There is no output filter stage in the current 8-stage orchestrator. Stage 7 is LLM streaming; Stage 8 is post-processing (persistence, memory update, profile learning). The output filter must be inserted as Stage 7.5 — between streaming completion and persistence. Codegen implementing the output filter will likely add it as a post-Stage-8 check, after the response has already been persisted to the conversation history.

**What breaks**: If the output filter runs after Stage 8 persistence, a blocked response has already been written to the conversation history before it is blocked. The conversation history will contain the unfiltered LLM output that the compliance system blocked. This is a SOC 2 and MiFID II violation — regulated content reaches the data store even when the user never sees it.

**Convention to enforce**: The output filter is Stage 7b. It runs after all response chunks are collected from streaming (Stage 7) and before `_persistence.save_exchange()` is called (Stage 8). If the filter blocks the response, the save_exchange call must not be made (or must be called with the redacted/canned response, never the blocked original).

---

## 3. Security Blindness Risks

### 3.1 Silent Credential Data Loss (the Warning Comment)

**The specific code** (`routes.py` lines 639-651):

```python
# Log access_control and kb_ids received — these fields are not yet fully persisted
# to the agent_cards schema (columns pending in next migration). They are accepted
# in the API contract so the frontend deploy form works without changes once the
# schema is extended. Without this log, the values would be silently discarded.
if body.kb_ids or body.access_control != "workspace":
    logger.warning(
        "agent_deploy_config_not_persisted",
        ...
        note="access_control and kb_ids require schema migration before they are enforced",
    )
```

**The security risk**: A tenant admin deploys a template and sets `access_control = "role_restricted"` expecting that only certain roles can use the agent. The API accepts the configuration, the UI shows success, and the agent appears with the expected settings. But the access control is not persisted. The deployed agent is accessible to all workspace users.

This is not a UI bug — it is a security boundary violation. An admin who sets role restriction expects it to be enforced. The silent discard creates an illusion of security that is worse than no access control at all, because the admin has no signal that the restriction is not active.

**The fix is not just a migration**: The schema migration adds the columns. But the security fix also requires: (1) the `deploy_agent_template_db()` function must receive and persist `access_control` and `kb_ids`, (2) the `resolve_agent()` function in the runtime path must check `access_control` against the user's roles before serving the agent, and (3) the agent list endpoint must filter by `access_control` so restricted agents do not appear in the UI for unauthorized users.

**Rule**: Until the schema migration is deployed and the `resolve_agent()` access check is implemented, the `/agents/templates/{template_id}/deploy` endpoint must return a 503 with message "Agent deployment is temporarily unavailable — access control enforcement is pending" for any request where `access_control != "workspace"` or `kb_ids` is non-empty. Silent acceptance of security configuration that will be discarded is not permissible.

### 3.2 Guardrails Stored but Not Enforced

**The specific code** (`routes.py` lines 140-144, 155, 173):

```python
class GuardrailsSchema(BaseModel):
    blocked_topics: List[str] = Field(default_factory=list)
    confidence_threshold: float = Field(0.5, ge=0.0, le=1.0)
    max_response_length: int = Field(2000, ge=100, le=10000)
```

The `create_agent` and `update_agent` endpoints store guardrails via `capabilities["guardrails"] = body.guardrails.model_dump()`. These are persisted to the `agent_cards` table as a JSONB column.

**The security risk**: The `ChatOrchestrationService` does not read or enforce the `guardrails` field from the `agent_cards` record. Stage 6 builds the system prompt from `prompt_builder.build()`. Stage 7 streams the LLM response. No stage checks the agent's `blocked_topics`, `confidence_threshold` (as a block condition), or `max_response_length`.

This means: an admin who configures `blocked_topics: ["competitor pricing", "legal advice"]` on an agent receives a UI confirmation that guardrails are set. In production, a user can ask about those topics and receive a response. The guardrail configuration is a false security boundary — it exists in the data store but nowhere in the request path.

**The attack scenario**: A regulated enterprise tenant configures a Finance Agent with `blocked_topics: ["investment advice", "specific stock recommendations"]` because their compliance team requires it. The tenant receives a SOC 2 audit finding that the AI system has documented compliance controls. An audit later discovers that users received investment advice responses from the agent. The compliance boundary was documented but never enforced.

**The fix requires two things**: (1) The orchestrator must load the agent's `guardrails` configuration at the start of `stream_response()`, alongside the agent resolution. (2) The output filter (Stage 7b) must implement `blocked_topics` as a `keyword_block` rule checked against the response before it is returned. The `confidence_threshold` must gate the response on `retrieval_confidence` — if confidence is below threshold, the canned low-confidence message must be returned instead of the LLM output.

### 3.3 `/.well-known/agent.json` — What Must Be Excluded

The A2A protocol specifies that agents publish an AgentCard at `/.well-known/agent.json` for discovery. The architecture in `33-agent-library-studio-architecture.md` describes agent instances with rich configuration including `kb_bindings`, `access_rules`, `credentials_vault_path`, and `system_prompt`.

**The security risk**: The `/.well-known/agent.json` endpoint is a public discovery mechanism — it is intended to be reachable without authentication by any agent that wants to invoke this agent. If the endpoint returns the full agent instance record, it will expose:

- `system_prompt`: The admin-authored behavioral instructions. An adversary who reads the system prompt can craft targeted prompt injection attacks calibrated to the specific prompt structure.
- `credentials_vault_path`: The vault path for tenant credentials (Bloomberg, CapIQ API keys). Knowing the vault path prefix reduces the search space for credential extraction attacks.
- `kb_bindings`: The specific knowledge base index IDs the agent queries. An adversary who knows which indices are queried can craft queries designed to extract specific documents via the agent's retrieval path.
- `access_rules`: The specific role IDs required to invoke the agent — directly maps to the tenant's RBAC structure.

**What the endpoint MUST include** (for valid A2A protocol discovery):

- `name`, `description`, `version`
- `capabilities` (functional capabilities list, not RBAC capabilities)
- `a2a_endpoint` (the URL to send A2A messages to)
- `public_key` (the Ed25519 public key for signature verification — already implemented at `/templates/{agent_id}/public-key`)
- `supported_protocols` and `auth_requirements` (what auth is needed to invoke)

**What the endpoint MUST exclude**:

- `system_prompt` (any form — resolved, template, or partial)
- `credentials_vault_path` or any vault reference
- `kb_bindings` with index IDs (may include a human-readable KB category list only)
- `access_rules` with role IDs (may include a boolean `requires_authentication: true`)
- `tenant_id` (must not be discoverable via public endpoint)

**Authentication status of the endpoint**: The `/.well-known/agent.json` must be unauthenticated (by A2A protocol spec — discovery is pre-auth). This means the strict exclusion list above is a hard requirement, not a best practice. Any field not in the include list above is excluded. Default-deny.

### 3.4 MCP Endpoint SSRF — Same Vector as `a2a_routing.py`

`a2a_routing.py` implements `_validate_ssrf_safe_url()` with DNS-resolution-based SSRF protection. The same attack vector exists anywhere the platform makes an outbound HTTP call based on a user-controlled URL.

**The MCP endpoint gap**: Agent templates that use MCP servers store the MCP server endpoint URL in configuration. When a user invokes a tool call through an MCP-enabled agent, the platform makes an outbound HTTP request to that URL. If the MCP endpoint URL is not validated with the same `_validate_ssrf_safe_url()` logic used in `a2a_routing.py`, a malicious tenant admin can register an MCP server pointing to `169.254.169.254` (cloud metadata endpoint) and exfiltrate instance credentials via tool calls.

**The specific gap**: `a2a_routing.py` correctly implements SSRF protection for A2A message routing. But there is no evidence in `routes.py` or the agent creation flow that MCP endpoint URLs submitted via `tool_ids` or any MCP configuration field are validated against `_validate_ssrf_safe_url()` before being stored or before outbound calls are made.

**The rule**: Any URL submitted to the platform that will be used for outbound HTTP calls — A2A endpoints, MCP server endpoints, credential test endpoints, webhook URLs — must be validated with `_validate_ssrf_safe_url()` from `app.modules.registry.a2a_routing`. This function is the canonical SSRF check for this codebase. It must not be reimplemented inline. Import it.

---

## 4. Institutional Knowledge to Capture

### Three Most Dangerous Failure Modes — Explicit Rules

The following rules are written in CLAUDE.md format. They address the three failure modes most likely to cause production security incidents.

---

#### RULE A2A-01: The Output Filter Is Not Optional and Must Run Before Persistence

```
RULE: agent-template/output-filter-placement
SEVERITY: CRITICAL — SOC 2 and MiFID II compliance

The guardrail output filter (Layer 2 in 25-a2a-guardrail-enforcement.md) MUST run
at Stage 7b of the ChatOrchestrationService pipeline — after LLM streaming completes
and BEFORE _persistence.save_exchange() is called.

CORRECT pipeline order:
  Stage 7: LLM streaming → collect all response_chunks
  Stage 7b: OutputFilter.check(response_text) against agent's guardrail rules
    - If FilterResult.passed=False and action="block":
        yield error SSE event to user
        return WITHOUT calling _persistence.save_exchange()
    - If FilterResult.passed=False and action="redact":
        replace response_text with redacted version
        continue to Stage 8 with redacted text
    - If FilterResult is an exception:
        fail closed — return canned error, do not persist original
  Stage 8: _persistence.save_exchange(response=response_text)

INCORRECT placement (do not do this):
  Stage 8: save_exchange(response=original_unfiltered_text)
  Stage 9: output filter (too late — blocked content already in DB)

WHY: If a guardrail violation (e.g., investment advice from Bloomberg agent)
is persisted to conversation history before being filtered, the regulated content
exists in the data store even if the user never sees it. This is a compliance
violation regardless of what the user received.

FAILURE MODE: Output filter placed after Stage 8. Bloomberg agent produces
investment advice. Response is blocked for the user. But the blocked text
is already in conversation_messages. An e-discovery request or regulatory
audit finds it. Platform is liable despite the user never seeing it.
```

---

#### RULE A2A-02: Guardrail Configuration Stored in DB Is Not Enforcement

```
RULE: agent-template/guardrails-are-not-stored-they-are-enforced
SEVERITY: CRITICAL — Security boundary

The `guardrails` JSONB field stored on agent_cards records is a configuration
specification. It is NOT enforcement. Storing guardrails does nothing unless
the ChatOrchestrationService reads and applies them on every request.

WHAT THE DB STORES (in capabilities->guardrails):
  blocked_topics: ["investment advice", "competitor pricing"]
  confidence_threshold: 0.65
  max_response_length: 2000

WHAT MUST HAPPEN AT RUNTIME for each of these fields:
  blocked_topics → must be compiled into keyword_block rules in AgentOutputFilter
                   and applied at Stage 7b before persistence
  confidence_threshold → if retrieval_confidence < threshold after Stage 4,
                          return canned low-confidence response; do NOT call
                          LLM at Stage 7 at all (wasted token spend + wrong output)
  max_response_length → applied to response_text after Stage 7; truncate at
                         word boundary if exceeded; log truncation event

DETECTION: If you can create an agent with blocked_topics=["legal advice"]
and then ask the agent a legal question and receive a legal answer,
the guardrails are stored but not enforced. This is a BROKEN state
regardless of what the admin UI shows.

HOW TO VERIFY enforcement is active:
  1. Create agent with blocked_topics=["banana"]
  2. Ask agent "tell me about bananas"
  3. Response must be blocked or redirected
  4. If response contains banana content, enforcement is not wired
```

---

#### RULE A2A-03: Credential Acceptance Without Persistence Is a Security Theater Bug

```
RULE: agent-template/no-silent-credential-discard
SEVERITY: CRITICAL — Security boundary and audit integrity

The /agents/templates/{template_id}/deploy endpoint CURRENTLY accepts
access_control and kb_ids in the request body and SILENTLY DISCARDS them
(routes.py lines 639-651). This is a known temporary state documented
with a warning log.

THIS MUST BE RESOLVED BEFORE agent templates are available to any tenant
that has been told their agent has access restrictions.

RESOLUTION REQUIRES (all three, not just the migration):

  Step 1: Schema migration
    ALTER TABLE agent_cards ADD COLUMN access_control VARCHAR(50) DEFAULT 'workspace';
    ALTER TABLE agent_cards ADD COLUMN kb_ids JSONB DEFAULT '[]';

  Step 2: Update deploy_agent_template_db() to persist both fields

  Step 3: Update resolve_agent() in the runtime path to enforce access_control:
    - access_control = "workspace": any authenticated workspace member
    - access_control = "role": check user's roles against agent's role_ids
    - access_control = "user": check user is in agent's user_ids list
    This check must happen at QUERY TIME from JWT claims, not at assignment time.
    (See 11-tenant-admin/05-red-team-critique.md R01 — RBAC enforced at query time)

INTERIM MITIGATION (until Step 3 is implemented):
  The deploy endpoint MUST return HTTP 422 if access_control != "workspace"
  OR if kb_ids is non-empty, with message:
  "Access-restricted agent deployment is not yet available. Deploy with
  access_control='workspace' until enforcement is confirmed active."

AUDIT REQUIREMENT: The warning log at lines 644-651 must be converted
to a structured alert that triggers a platform admin notification
if any deployment with non-workspace access control is accepted.
Currently it is a logger.warning that goes to logs only — it is
invisible to platform operators monitoring tenant activity.

WHY SILENT DISCARD IS WORSE THAN REJECTION:
  If the endpoint returned 422, the admin would know the restriction
  is not active and take compensating action. With silent acceptance,
  the admin believes the agent is restricted. Users bypass the intended
  access control. The admin has a false security belief backed by a
  successful API response.
```

---

## 5. Summary: Gaps by COC Fault Line

| Gap                                                             | Fault Line         | Severity | Risk If Unfixed                                             |
| --------------------------------------------------------------- | ------------------ | -------- | ----------------------------------------------------------- |
| Guardrail block placement (after vs before persistence)         | Amnesia            | CRITICAL | Regulated content persisted to DB despite user-facing block |
| `semantic_check` not implemented for Bloomberg                  | Amnesia            | HIGH     | Investment advice bypasses guardrail via paraphrase         |
| Guardrail token budget not reserved                             | Amnesia            | HIGH     | Guardrail block truncated under token pressure              |
| SSRF check must be per-request, not per-registration            | Amnesia            | HIGH     | DNS rebinding attack via A2A endpoint                       |
| `CredentialTestResult.passed = None` binary misread             | Amnesia            | MEDIUM   | Untested integrations blocked or incorrectly passed         |
| Credential health check not using `DistributedJobLock`          | Convention Drift   | HIGH     | Duplicate notifications on multi-worker deploy              |
| `agent_cards` UPDATE missing `tenant_id` predicate              | Convention Drift   | CRITICAL | Cross-tenant access control override                        |
| Redis key namespace omitting `tenant_id`                        | Convention Drift   | MEDIUM   | Cache invalidation misses on agent archival                 |
| Output filter not inserted as Stage 7b                          | Convention Drift   | CRITICAL | Compliance content in DB before filter runs                 |
| Silent `access_control` + `kb_ids` discard                      | Security Blindness | CRITICAL | Agents deployed without intended access restrictions        |
| Guardrails stored but not enforced at runtime                   | Security Blindness | CRITICAL | Security configuration with zero enforcement effect         |
| `/.well-known/agent.json` field exclusion undefined             | Security Blindness | HIGH     | System prompt + vault path exposed to public discovery      |
| MCP endpoint URLs not validated via `_validate_ssrf_safe_url()` | Security Blindness | HIGH     | SSRF via tenant-controlled MCP server URL                   |

---

## 6. Encoding Locations

Each institutional decision identified in this document must be encoded in a location that survives context window compression — the COC anti-amnesia principle.

| Decision                                         | Encoding Location                                                                     |
| ------------------------------------------------ | ------------------------------------------------------------------------------------- |
| Output filter as Stage 7b                        | `orchestrator.py` docstring Stage list (update) + `AgentOutputFilter` class docstring |
| Guardrail block is not enforcement               | `GuardrailsSchema` Pydantic class docstring + `create_agent` endpoint comment         |
| `passed=None` semantics                          | `CredentialTestResult` dataclass docstring; three-state note                          |
| SSRF check per-request rationale                 | `_validate_ssrf_safe_url()` docstring                                                 |
| Guardrail token budget reservation               | `get_tenant_token_budget()` + `build_agent_system_prompt()`                           |
| `/.well-known/agent.json` include/exclude list   | Dedicated endpoint function docstring with explicit MUST EXCLUDE section              |
| `DistributedJobLock` for credential health check | `run_daily_credential_health_check()` function docstring                              |
| `tenant_id` predicate on all agent_cards writes  | `_AGENT_UPDATE_SQL` comment block                                                     |
| Redis key namespace pattern                      | Module-level constant with naming example                                             |
| Silent discard interim block                     | `deploy_agent_template_db()` docstring and inline TODO with migration reference       |

---

**Document Version**: 1.0
**Last Updated**: 2026-03-21
**Author**: COC Analysis (coc-expert)
**Next Action**: Priority order for implementation — RULE A2A-01, A2A-02, A2A-03 are P0 blockers before any A2A agent template reaches a regulated tenant.
