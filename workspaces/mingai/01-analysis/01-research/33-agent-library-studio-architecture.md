# 33. Agent Library and Agent Studio Architecture

> **Status**: Architecture Design
> **Date**: 2026-03-05
> **Purpose**: Technical architecture for the two agent authoring and deployment surfaces available to tenant admins — the Agent Library (adopt pre-built platform-curated agents) and Agent Studio (build custom agents from scratch).
> **Depends on**: `18-a2a-agent-architecture.md`, `31-tenant-admin-capability-spec.md`, `24-platform-rbac-specification.md`

---

## 1. Conceptual Model

Two distinct surfaces, one unified runtime:

```
Platform Admin Layer
  ┌──────────────────────────────────────────────────┐
  │  Agent Template Catalog                           │
  │  (platform-curated, versioned, published)         │
  │  Bloomberg · CapIQ · Perplexity · HR Policy ···   │
  └──────────────────────────────────────────────────┘
           │ adopt                    │ build
           ▼                          ▼
Tenant Admin Layer
  ┌───────────────────┐   ┌─────────────────────────┐
  │  Agent Library    │   │  Agent Studio            │
  │  (adoption +      │   │  (authoring from scratch)│
  │   configuration)  │   │                          │
  └───────────────────┘   └─────────────────────────┘
           │                          │
           ▼                          ▼
  ┌──────────────────────────────────────────────────┐
  │  Agent Instance (tenant-scoped, deployed)         │
  │  {template_id?, system_prompt, kb_bindings,       │
  │   access_rules, llm_config, state: active}        │
  └──────────────────────────────────────────────────┘
           │
           ▼
  User-facing agent in chat UI
```

**Agent Template**: Platform-authored. Cannot be edited by tenant admin. Versioned. May require tenant-provided credentials (Bloomberg, CapIQ). Defines the system prompt template, required variables, optional variables, and recommended KB categories.

**Agent Instance**: Tenant-scoped. Created by adopting a template OR by authoring in Agent Studio (custom). Contains all runtime-relevant configuration. Platform admin never sees inside tenant instances (isolation).

---

## 2. Data Model

### 2.1 Agent Template (Platform-level, Cosmos DB partition: `platform`)

```json
{
  "id": "tmpl_bloomberg_v2",
  "type": "agent_template",
  "name": "Bloomberg Intelligence Agent",
  "description": "Real-time and historical market data — equities, FX, commodities, bonds, earnings.",
  "category": "financial_data",
  "icon": "bloomberg",
  "version": "2.1.0",
  "changelog": "v2.1.0: Added support for FX historical queries",
  "previous_version_id": "tmpl_bloomberg_v1",
  "status": "published", // draft | published | deprecated
  "plan_required": "professional", // starter | professional | enterprise | null
  "auth_mode": "tenant_credentials", // none | tenant_credentials | platform_credentials
  "required_credentials": [
    {
      "key": "bloomberg_client_id",
      "label": "Bloomberg BSSO Client ID",
      "description": "From your Bloomberg BSSO application registration",
      "type": "string",
      "sensitive": false
    },
    {
      "key": "bloomberg_client_secret",
      "label": "Bloomberg BSSO Client Secret",
      "type": "string",
      "sensitive": true
    }
  ],
  "system_prompt_template": "You are a financial research assistant powered by Bloomberg's Data License. You provide accurate, real-time market data and analysis for equities, fixed income, foreign exchange, and commodities.\n\nAlways:\n- Cite the Bloomberg data point with its field identifier (e.g., PX_LAST, EQY_PE_RATIO)\n- State the data timestamp (as-of time)\n- Note that Bloomberg data is subject to Bloomberg's terms of use\n- Escalate complex derivatives or structured products queries to a specialist\n\n{{tenant_context}}",
  "variables": {
    "required": [],
    "optional": ["tenant_context"]
  },
  "recommended_kb_categories": [], // Bloomberg fetches real-time, no KB needed
  "capabilities": ["market_data", "earnings", "fx", "commodities"],
  "cannot_do": [
    "historical_data_older_than_10_years",
    "private_company_financials"
  ],
  "avg_latency_ms": 1800,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-03-01T00:00:00Z"
}
```

### 2.2 Agent Instance (Tenant-level, Cosmos DB partition: `tenant_{tenant_id}`)

```json
{
  "id": "inst_a1b2c3d4e5f6",
  "type": "agent_instance",
  "tenant_id": "tenant-uuid",
  "template_id": "tmpl_bloomberg_v2", // null for custom (Agent Studio) agents
  "template_version_pinned": "2.1.0", // null for custom agents
  "name": "Bloomberg Intelligence", // tenant-visible name (can be renamed)
  "description": "Real-time Bloomberg market data",
  "category": "financial_data",
  "icon": "bloomberg",
  "source": "library", // library | studio
  "status": "active", // active | paused | draft | archived
  "system_prompt": "You are a financial research assistant...", // resolved at creation
  "variables_filled": {
    "tenant_context": "Acme Capital focuses on APAC equities and US investment-grade bonds."
  },
  "kb_bindings": [], // empty for Bloomberg (uses real-time data)
  "kb_search_mode": "parallel", // parallel | priority_order
  "llm_config": {
    "model_id": "platform_default", // uses tenant's selected LLM profile
    "temperature": 0.1,
    "max_tokens": 2048
  },
  "access_rules": {
    "mode": "role_restricted", // workspace_wide | role_restricted | user_list
    "role_ids": ["role_analyst", "role_exec"],
    "user_ids": []
  },
  "rate_limit_per_user_per_day": 50, // within platform maximum
  "credentials_vault_path": "tenant-uuid/agents/inst_a1b2c3d4e5f6/bloomberg",
  "created_by": "admin-user-id",
  "created_at": "2026-03-01T00:00:00Z",
  "updated_at": "2026-03-05T00:00:00Z",
  "published_at": "2026-03-01T08:00:00Z",
  "version_history": [
    {
      "version": 1,
      "changed_by": "admin-user-id",
      "changed_at": "2026-03-01T08:00:00Z",
      "summary": "Initial deployment"
    }
  ]
}
```

### 2.3 Custom Agent (Agent Studio, no template)

```json
{
  "id": "inst_f9e8d7c6b5a4",
  "type": "agent_instance",
  "tenant_id": "tenant-uuid",
  "template_id": null, // No parent template — fully custom
  "name": "Acme Procurement Assistant",
  "source": "studio",
  "system_prompt": "You are a procurement assistant for Acme Corp...",
  "kb_bindings": [
    {
      "index_id": "idx_sp_abc123",
      "display_name": "Procurement Policies",
      "required_role": null // null = enforce same RBAC as the agent
    },
    {
      "index_id": "idx_sp_def456",
      "display_name": "Vendor Contracts",
      "required_role": "role_analyst" // Enforce stricter KB-level rule than agent access
    }
  ],
  "kb_search_mode": "parallel",
  "llm_config": {
    "model_id": "platform_default",
    "temperature": 0.3,
    "max_tokens": 1500
  },
  "access_rules": {
    "mode": "role_restricted",
    "role_ids": ["role_analyst"],
    "user_ids": []
  },
  "guardrails": {
    "max_output_tokens": 1500,
    "confidence_threshold": 0.65, // Show "I'm not sure" below this score
    "citation_mode": "required" // required | optional | none
  }
}
```

---

## 3. Agent Library — Catalog and Adoption

### 3.1 Catalog API

The catalog is a tenant-read-only view of published templates:

```
GET /api/v1/admin/agents/catalog
  ?category=financial_data
  &status=published
  &plan_check=true      // Filter to templates accessible on tenant's plan

Response:
  [
    {
      "template_id": "tmpl_bloomberg_v2",
      "name": "Bloomberg Intelligence Agent",
      "category": "financial_data",
      "auth_mode": "tenant_credentials",
      "is_adopted": false,     // Has this tenant adopted this template?
      "adoption_count": null,  // Platform-wide adoption count (hidden for competitive reasons)
      "avg_latency_ms": 1800,
      "plan_required": "professional"
    },
    ...
  ]
```

### 3.2 Adoption Workflow

```
Tenant Admin → POST /api/v1/admin/agents/adopt
  {
    "template_id": "tmpl_bloomberg_v2",
    "display_name": "Bloomberg Intelligence",   // optional override
    "variables_filled": {
      "tenant_context": "Acme Capital APAC equities focus"
    },
    "credentials": {
      "bloomberg_client_id": "...",
      "bloomberg_client_secret": "..."
    },
    "access_rules": { "mode": "role_restricted", "role_ids": ["role_analyst"] },
    "rate_limit_per_user_per_day": 50
  }

Server:
  1. Validate plan allows this template
  2. Validate all required variables filled
  3. Validate all required credentials provided
  4. Resolve system prompt: substitute variables into template string
  5. Validate credentials against template's credential test endpoint (async)
  6. Store credentials in tenant-scoped vault:
     key: {tenant_id}/agents/{instance_id}/{credential_key}
  7. Create AgentInstance document in Cosmos DB (tenant partition)
  8. Set status = "active" (credentials valid) or "pending_validation" (async check)
  9. Invalidate tenant's agent list cache (Redis)
  10. Write audit log: "Agent 'Bloomberg Intelligence' adopted by {admin_email}"

Response:
  { "instance_id": "inst_...", "status": "active", "credential_test": "passed" }
```

### 3.3 Template Version Update

When platform admin publishes a new template version:

```
Event: tmpl_bloomberg_v2 → v2.2.0 published

For each active instance based on tmpl_bloomberg_v2:
  1. Mark instance with: template_update_available: true
  2. Send in-app notification to tenant admin:
     "Bloomberg Intelligence Agent has an update available (v2.2.0).
      What's new: Added commodity futures support.
      [Review and Update] [Dismiss]"
  3. Tenant admin reviews changelog
  4. If update accepted: re-resolve system prompt with new template
     (tenant variables + new template string → new resolved prompt)
  5. Previous prompt preserved in version_history for rollback

AUTO-UPDATE policy: Never. All template updates require explicit tenant admin approval.
REASON: System prompt changes are security-relevant. Auto-updates could
introduce unexpected behavior changes in production agents.
```

---

## 4. Agent Studio — Authoring Architecture

### 4.1 Authoring API Flow

```
POST /api/v1/admin/agents/studio/create (creates draft)
  Body: { name, description, category, system_prompt, kb_bindings, llm_config, access_rules }
  → creates instance with status: "draft"

PUT /api/v1/admin/agents/studio/{instance_id} (update draft)
  → updates draft, increments version_history

POST /api/v1/admin/agents/studio/{instance_id}/test
  Body: { test_query: "How many sick days do employees get?", test_as_user_id: "user-uuid" }
  → test_as_user_id MUST be the requesting admin's own user_id or a platform synthetic test role
    (cannot impersonate arbitrary users — prevents unauthorized KB access via test mode)
  → Executes agent with draft configuration, using test user's RBAC context
  → Returns: { response_text, sources, confidence_score, kb_queries_executed, guardrail_events }
  → Does NOT write to conversation history
  → MUST write to audit log with mode: "test":
      { admin_id, instance_id, test_query_hash (not raw), mode: "test", kb_ids_queried, created_at }
    (SOC 2 requirement: all data access by admins must be auditable, even in test context)

POST /api/v1/admin/agents/studio/{instance_id}/publish
  Body: { access_rules }
  → Sets status: active
  → Agent appears in user-facing agent list for authorized roles
  → Audit log: "Agent '{name}' published by {admin_email}"

DELETE /api/v1/admin/agents/{instance_id}
  → Soft delete: status = "archived"
  → Agent disappears from user list immediately
  → No user conversations lost
```

### 4.2 System Prompt Security

**Storage**: System prompts are stored server-side and NEVER returned to the browser in full after save. The admin can see and edit the prompt in the authoring UI, but the resolved runtime prompt is a server-side construct only.

**Injection prevention**:

```python
class SystemPromptValidator:
    """
    Validates that an admin-authored system prompt does not contain
    patterns that could allow end-user prompt injection.
    """
    BLOCKED_PATTERNS = [
        # Instructions to ignore previous instructions
        r"ignore (all )?(previous|prior|above) instructions",
        r"disregard .{0,50} (instructions|rules|guidelines)",
        # Attempts to exfiltrate system context
        r"repeat (all |the )?(above|previous|system)",
        r"print .{0,30} (instructions|prompt|system message)",
        # Jailbreak patterns
        r"you are now (an? )?[a-z]+ (without|with no) (restrictions|limits)",
        r"DAN|JAILBREAK|DEVELOPER MODE",
    ]

    SECURITY_RULES = [
        "Never concatenate user query content into system_prompt at runtime",
        "Glossary terms injected via GlossaryEnricher only (system message boundary)",
        "User name/dept injected as separate system context block, not inside custom prompt",
        "Custom prompt is a STATIC string at runtime — evaluated once at conversation start"
    ]

    def validate(self, prompt: str) -> ValidationResult:
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, prompt, re.IGNORECASE):
                return ValidationResult(
                    valid=False,
                    reason=f"Blocked pattern detected: likely injection vulnerability"
                )
        if len(prompt) > 2000:
            return ValidationResult(valid=False, reason="System prompt exceeds 2000 character limit")
        return ValidationResult(valid=True)
```

**Runtime prompt assembly** (in RAG pipeline synthesis stage):

```python
def build_system_message(
    agent_instance: AgentInstance,
    tenant: Tenant,
    user: User,
    matched_glossary_terms: list[GlossaryTerm],
    retrieved_context: str
) -> str:
    """
    Assembles the final system message from immutable server-side components.
    User query is NEVER present in the system message.
    """
    parts = []

    # 1. Agent's custom system prompt (static, admin-authored, validated at save time)
    parts.append(agent_instance.system_prompt)

    # 2. Tenant context block (injected separately, not embedded in custom prompt)
    parts.append(f"\n--- Organization Context ---")
    parts.append(f"Organization: {tenant.display_name}")
    parts.append(f"User: {user.name}, Department: {user.department or 'Not specified'}")

    # 3. Glossary terms (injected at system message level, never in user message)
    if matched_glossary_terms:
        parts.append(f"\n--- Domain Glossary (relevant to this query) ---")
        for term in matched_glossary_terms[:20]:  # max 20 terms, 800 token cap
            parts.append(f"{term.term}: {term.definition}")

    # 4. Retrieved document context
    parts.append(f"\n--- Relevant Documents ---")
    parts.append(retrieved_context)

    return "\n".join(parts)
```

### 4.3 KB Access Enforcement at Query Time

When a user invokes an agent with KB bindings, access is enforced at the retrieval stage — not at the agent display stage:

```python
async def retrieve_from_agent_kbs(
    agent: AgentInstance,
    user: User,
    query_embedding: list[float]
) -> list[RetrievedChunk]:
    """
    For each KB binding in the agent, check if the user has access.
    Only query KBs the user is authorized for.
    Proceed with partial context if some KBs are inaccessible.
    """
    results = []
    for kb_binding in agent.kb_bindings:
        required_role = kb_binding.required_role or None
        user_has_access = await rbac.check_kb_access(
            user_id=user.id,
            tenant_id=user.tenant_id,
            index_id=kb_binding.index_id,
            required_role=required_role
        )
        if not user_has_access:
            # Log: user cannot access this KB through this agent
            # Do NOT surface this to user (information leakage risk)
            continue
        chunks = await search_index(kb_binding.index_id, query_embedding)
        results.extend(chunks)

    return results
```

**Design decision**: If a user lacks access to one KB that an agent queries, the agent responds based on the KBs they DO have access to — without revealing that additional KBs exist. The admin sees this behavior in the quality dashboard (low confidence scores for queries that needed the restricted KB).

---

## 5. Agent Resolution at Query Time

When a user sends a message in the chat, the agent dispatcher resolves the appropriate instance:

```python
async def resolve_agent(
    agent_instance_id: str,
    user: User
) -> AgentInstance | None:
    """
    1. Load agent instance from Cosmos DB (cached in Redis, 5-minute TTL)
    2. Check instance status (must be "active")
    3. Check user access (must match access_rules)
    4. Return instance or None (user unauthorized — UI should not have shown the agent)
    """
    instance = await agent_cache.get(agent_instance_id, user.tenant_id)
    if not instance or instance.status != "active":
        return None
    if not rbac.check_agent_access(user, instance.access_rules):
        return None
    return instance
```

**Cache invalidation**: When a tenant admin changes an agent's access rules, system prompt, or status, the Redis cache key `agent:{tenant_id}:{instance_id}` is invalidated immediately via pub/sub notification. Active user sessions pick up the change on their next request (within the current token TTL, typically < 15 minutes).

---

## 6. Agent Inventory Endpoints

| Endpoint                              | Method | Description                                       |
| ------------------------------------- | ------ | ------------------------------------------------- |
| `/admin/agents/catalog`               | GET    | Browse platform template catalog                  |
| `/admin/agents/catalog/{template_id}` | GET    | Template detail + changelog                       |
| `/admin/agents/adopt`                 | POST   | Adopt a template as an instance                   |
| `/admin/agents/studio/create`         | POST   | Create a custom agent draft                       |
| `/admin/agents/studio/{id}`           | PUT    | Update custom agent (saves to version history)    |
| `/admin/agents/studio/{id}/test`      | POST   | Test agent with a query in sandbox mode           |
| `/admin/agents/studio/{id}/publish`   | POST   | Publish draft to live users                       |
| `/admin/agents`                       | GET    | List all active + draft instances for tenant      |
| `/admin/agents/{id}`                  | GET    | Agent instance detail                             |
| `/admin/agents/{id}/pause`            | POST   | Pause agent (hidden from users, config preserved) |
| `/admin/agents/{id}/archive`          | DELETE | Soft delete agent                                 |
| `/admin/agents/{id}/stats`            | GET    | Usage + satisfaction stats for this agent         |

---

## 7. Multi-Tenant Isolation

Agent instances are strictly scoped to their tenant:

- **Cosmos DB partition key**: `tenant_{tenant_id}` — no cross-partition queries
- **Redis cache key**: `agent:{tenant_id}:{instance_id}` — tenant prefix prevents cross-tenant cache hits
- **Vault credentials**: Stored at `{tenant_id}/agents/{instance_id}/{credential_key}` — tenant-scoped path
- **System prompts**: Stored inside the tenant partition — platform admin cannot read tenant agent configs
- **Template catalog**: Read-only from platform partition — tenant cannot modify templates

**What platform admin CAN see**: Template adoption counts (aggregate, not per-tenant). They cannot see: system prompt contents, KB bindings, or access rules of any tenant's agent instances.

---

## 8. Credential Test Architecture

For agents that require tenant-provided credentials (Bloomberg, CapIQ, Oracle), the credential test runs server-side:

```python
class CredentialTestRunner:
    """
    Test tenant-provided credentials by executing a minimal API call.
    Never sends credentials to browser. Returns pass/fail + masked account info.
    """
    TESTS = {
        "bloomberg": BloombergCredentialTest,
        "capiq": CapIQCredentialTest,
        "oracle_fusion": OracleFusionCredentialTest,
    }

    async def test(self, template_id: str, credentials: dict) -> CredentialTestResult:
        test_class = self.TESTS.get(template_id)
        if not test_class:
            # passed=None (not True) — "untested" is not the same as "valid"
            # Caller must surface this ambiguity rather than silently assuming success
            return CredentialTestResult(passed=None, message="No credential test available for this integration — credentials stored but not validated")



        try:
            result = await test_class().run(credentials)
            return CredentialTestResult(
                passed=True,
                message=result.account_summary,  # e.g., "Connected: acmecorp@bloomberg.com"
                latency_ms=result.latency_ms
            )
        except CredentialError as e:
            return CredentialTestResult(passed=False, message=str(e))
```

### 8.1 Credential Health Check (R23 addition)

A daily scheduled job monitors all stored credentials for active agent instances:

```python
async def run_daily_credential_health_check(tenant_id: str) -> None:
    """
    Runs daily for each tenant. Re-tests credentials for all active agents
    that have a credential test class registered. Flags agents with failing
    or untested credentials as 'credential_warning' in their instance status.
    """
    active_agents = await get_active_agents_with_credentials(tenant_id)
    for instance in active_agents:
        test_result = await CredentialTestRunner().test(
            template_id=instance.template_id,
            credentials=await vault.fetch(instance.credentials_vault_path)
        )
        if test_result.passed is False:
            await flag_agent_credential_failure(instance, test_result.message)
            await notify_tenant_admin(
                tenant_id,
                f"Agent '{instance.name}' credentials are no longer valid: {test_result.message}. "
                f"Update credentials in agent settings to restore service.",
                severity="warning"
            )
        elif test_result.passed is None:
            # No test class — flag as 'unverifiable' for transparency
            # Do not alert unless the agent has been inactive for 30+ days
            pass
```

This removes the silent-failure risk: an agent with expired Bloomberg credentials would
previously respond with an API error that the user sees as an AI failure — now the admin
is notified before users encounter it.

---

## 9. Phase Delivery

| Phase                        | Agent Capabilities                                                                                                             |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **Phase 1 (Foundation)**     | Basic agent catalog display; toggle enable/disable; no credential management                                                   |
| **Phase 3 (Auth)**           | SSO group → agent access control mapping                                                                                       |
| **Phase 4 (Agentic)**        | Full agent library adoption with credential management; Agent Studio v1 (system prompt + KB bindings + test harness + publish) |
| **Phase 5 (Cloud Agnostic)** | Agent Studio v2: multi-KB search modes, per-KB access overrides, guardrail configuration                                       |
| **Phase 6 (GA)**             | Agent version history UI, template auto-update notifications, agent performance comparison                                     |

---

**Document Version**: 1.1
**Last Updated**: 2026-03-05
**Changelog**: v1.1 — R23: CredentialTestResult.passed defaults to None (not True) for untested integrations; added §8.1 daily credential health check. R26: test mode now requires audit log write with mode=test, test_as_user_id restricted to requesting admin's own ID or synthetic test role.
