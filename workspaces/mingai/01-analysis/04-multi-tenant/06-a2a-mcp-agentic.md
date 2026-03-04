# A2A Agent Platform: Architecture & Product Design

**Date**: March 4, 2026
**Status**: Architecture Design v2.0
**Scope**: A2A agent platform, agent template system, DAG orchestration, tool catalog, credential management, marketplace

---

## Executive Summary

mingai's agent platform is built on three architectural principles that differentiate it from classical RAG and from every enterprise AI competitor:

1. **All 9 data integrations are autonomous A2A agents** — each agent takes a natural language task, reasons internally with its own LLM, calls its assigned MCP server, and returns a structured Artifact. The orchestrator delegates tasks; it never micromanages tool calls.

2. **The orchestrator owns the DAG, not the agents** — complex queries decompose into a dependency graph of agent tasks. Each agent receives only its atomic assignment. Parallel DAG execution collapses multi-source financial research from minutes to seconds.

3. **Platform builds templates; tenants bring credentials** — Bloomberg agent template ships with the platform (prompt, guardrails, MCP config, AgentCard skills). Tenant provides their Bloomberg account credentials. Zero engineering to deploy enterprise-grade agents.

---

## The Problem This Solves

### Current aihub2 Limitations (What We Leave Behind)

In aihub2's `ResearchAgentHandler`, the orchestrator acts as a god object:

- `ToolPlanner` (LLM) selects which tools to call and constructs the query
- `ToolExecutor` calls MCP servers directly as dumb data endpoints
- The orchestrator sends a flat tool call list per iteration — MCP servers have no autonomy
- Credentials live in per-server `.env` files, not tenant-scoped
- One Bloomberg account serves all users — no tenant isolation
- `INTERNET_SEARCH_TOOL` (Tavily) is baked in as a one-off, not a governed catalog entry
- No multi-agent coordination; no parallel agent execution
- Custom `A2AMessage` dataclass — not compatible with the emerging Google A2A standard

This works for a single-tenant internal system. It cannot scale to multi-tenant SaaS.

### What mingai Fixes

| aihub2 Problem                    | mingai Solution                               |
| --------------------------------- | --------------------------------------------- |
| Orchestrator selects tool queries | Agent reasons about its own tool calls        |
| MCP servers = dumb data endpoints | All 9 = autonomous A2A agents                 |
| Global `.env` credentials         | Platform template + tenant credential vault   |
| Flat tool iteration (sequential)  | DAG with parallel agent execution             |
| Custom A2AMessage protocol        | Google A2A v0.3 (Linux Foundation standard)   |
| Tavily baked in as a one-off      | Extensible Tool Catalog (Tavily is entry #1)  |
| No external agent support         | Open marketplace via EATP-verified AgentCards |

---

## Architecture Principles

### Principle 1: Agents Are Autonomous

An agent is autonomous when it can receive a natural language task and decide — without orchestrator intervention — which of its MCP tools to call and how to synthesize the result.

**aihub2**: Orchestrator decides tool → calls MCP → gets raw data
**mingai**: Orchestrator delegates task → Agent decides tools → Agent synthesizes → returns Artifact

CapIQ example: Query is "What are the comparable companies for Emerson Electric?" The CapIQ agent must reason: call `get_company_profile`? `search_deals`? `get_competitor_analysis`? All three? This is reasoning. Pushing that decision into the orchestrator requires the orchestrator to know every possible query pattern for every agent — which doesn't scale to 9 agents, let alone a marketplace of hundreds.

### Principle 2: Orchestrator Owns the DAG — Not the Agents

The DAG (Directed Acyclic Graph of agent tasks) is the orchestrator's private state machine. Agents are task-blind by design.

**What an agent receives**: "Get AAPL current P/E ratio and earnings news for the last 7 days"
**What an agent never receives**: "You are step 2 of 5. Step 1 was internet search. After you complete, step 4 will calculate ratios. Here is the full execution plan."

Sending the full plan to an agent is an anti-pattern from aihub2. It creates coupling, leaks orchestration logic into agents, and makes agents non-reusable across different orchestration contexts.

### Principle 3: Industry Standards, Not Custom Protocols

- Agent communication: **Google A2A v0.3** (Task/Artifact/AgentCard, HTTP+SSE+JSON-RPC 2.0, Linux Foundation July 2025)
- Agent capability declaration: **AgentCard** at `/.well-known/agent.json`
- Internal tool protocol (per agent): **Anthropic MCP** for each agent's data layer
- External agent trust: **EATP** (Enterprise Agent Trust Protocol) for marketplace verification

---

## Three-Layer Capability Model

```
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 1: A2A AGENTS (all 9 data integrations — autonomous, LLM-powered) │
│                                                                          │
│  Each agent: natural language Task in → internal LLM reasoning           │
│              → internal MCP tool calls → LLM synthesis → Artifact out    │
│                                                                          │
│  Bloomberg   CapIQ    Perplexity   Oracle Fusion   AlphaGeo              │
│  Teamworks   PitchBook   Azure AD   iLevel                               │
│                                                                          │
│  + Tenant custom agents (Enterprise plan, BYOMCP)                        │
│  + External A2A-compliant marketplace agents (EATP-verified)             │
├──────────────────────────────────────────────────────────────────────────┤
│  LAYER 2: TOOL CATALOG (deterministic, direct calls — no A2A, no LLM)   │
│                                                                          │
│  Tavily (internet search)  ·  Calculator  ·  Weather                     │
│  + extensible: currency converter, OCR, code execution, ...             │
│                                                                          │
│  Platform Admin registers tools. Tenant Admin enables per org.           │
├──────────────────────────────────────────────────────────────────────────┤
│  LAYER 3: ORCHESTRATOR (owns DAG, dispatches atomic tasks)               │
│                                                                          │
│  Plans execution graph → dispatches A2A Tasks to Layer 1 agents          │
│  → calls Layer 2 tools directly → collects Artifacts → synthesizes       │
└──────────────────────────────────────────────────────────────────────────┘
```

### Tool vs Agent: The Decision Rule

| Characteristic     | Tool (Layer 2)                                            | Agent (Layer 1)                                                    |
| ------------------ | --------------------------------------------------------- | ------------------------------------------------------------------ |
| Response type      | Deterministic, structured                                 | Reasoned, synthesized                                              |
| Internal reasoning | None                                                      | LLM decides which tools to call                                    |
| Response time      | < 1 second                                                | 2–30 seconds                                                       |
| Protocol           | Direct HTTP / function call                               | Google A2A Task/Artifact                                           |
| Example            | Tavily: `search("AAPL news")` → `[{title, url, snippet}]` | Bloomberg: "Analyze AAPL for earnings risk" → synthesized analysis |

**Why all 9 are agents**: Even CapIQ, iLevel, and AlphaGeo require an internal LLM to reason about which of their MCP tools to call based on the user's natural language task. Deterministic routing is only possible for tools with a single, well-defined input-output schema.

---

## Agent Inventory and Credential Model

All 9 agents follow the same internal architecture:

```
receive A2A Task (natural language)
  → internal LLM: which of MY MCP tools do I need?
  → call MY MCP tools (with MY credentials, injected at runtime)
  → LLM: synthesize results into coherent answer
  → return A2A Artifact
```

| Agent             | Internal MCP                     | Credential Type                                       | Credential Owner            |
| ----------------- | -------------------------------- | ----------------------------------------------------- | --------------------------- |
| **Bloomberg**     | Bloomberg DL API                 | OAuth2 BSSO (`client_id`, `client_secret`, `account`) | Tenant                      |
| **Perplexity**    | Perplexity API                   | API key                                               | Platform (shared) or Tenant |
| **Oracle Fusion** | Oracle Cloud REST (fin/proc/scm) | JWT assertion OAuth2 (`client_id`, `jwt_private_key`) | Tenant                      |
| **CapIQ**         | S&P Capital IQ                   | API key                                               | Tenant                      |
| **iLevel**        | iLevel API                       | API key                                               | Tenant                      |
| **AlphaGeo**      | AlphaGeo API                     | API key                                               | Tenant                      |
| **Teamworks**     | Teamworks API                    | API key                                               | Tenant                      |
| **PitchBook**     | PitchBook/Morningstar            | API key                                               | Tenant                      |
| **Azure AD**      | MS Graph API                     | OBO (user's delegated token)                          | User (auto at runtime)      |

### Credential Architecture

```
PLATFORM defines:   Agent template → credential SCHEMA (type + required fields)
TENANT provides:    Credential VALUES (Bloomberg account, Oracle JWT, CapIQ key...)
USER provides:      OBO token for Azure AD (auto-delegated at runtime, nothing stored)
EXTERNAL CALLER:    Provides their own MCP credentials in A2A Task metadata per call
```

### Supported Credential Types

| Type            | Description                                  | Operational Risk                                                          | Example                      |
| --------------- | -------------------------------------------- | ------------------------------------------------------------------------- | ---------------------------- |
| `api_key`       | Single secret string                         | Low — long-lived, tenant rotates when needed                              | CapIQ, PitchBook, Perplexity |
| `oauth2_bsso`   | OAuth2 client credentials via Bloomberg BSSO | Medium — session expiry, Bloomberg contract governs                       | Bloomberg                    |
| `jwt_assertion` | JWT private key assertion (RFC 7523)         | High — key rotation required every 90 days, vault must track expiry       | Oracle Fusion                |
| `obo`           | OAuth2 On-Behalf-Of (RFC 8693)               | Medium — requires admin consent per tenant, platform AAD app registration | Azure AD                     |
| `basic_auth`    | Username + password                          | High — password expires frequently, stored reversibly, rotate on schedule | Legacy/internal systems      |

`basic_auth` is accepted for home-grown and legacy systems but flagged in the UI as "legacy credential type — recommend API key or OAuth2 where available." The credential vault must track password expiry and notify the tenant.

### Credential Injection Pattern (Shared Docker Architecture)

Each agent Docker container is **shared across all tenants** (cost efficiency). Credentials are **never stored in the container**. The injection pattern:

```
Orchestrator:
  1. Resolves tenant credential from vault
  2. Generates a short-lived vault token (TTL = request timeout)
  3. Injects into A2A Task request as encrypted header:
     X-Agent-Credential: <vault-token>

Agent container (at request time):
  1. Extracts vault token from request header
  2. Exchanges for actual credential via vault sidecar (in-memory, not persisted)
  3. Calls MCP server with credential
  4. Credential is never written to disk or logged
  5. Vault token expires after request completes
```

This ensures a compromised container cannot exfiltrate tenant credentials — it only ever holds credentials for the duration of a single request.

### Self-Describing Agent Configuration

For home-grown and custom agents, the agent declares its own configuration schema in the AgentCard. Platform Admin UI renders the form dynamically — no hardcoded field definitions:

```json
"configuration_schema": {
  "required": [
    {"name": "api_key", "type": "secret", "label": "API Key"},
    {"name": "base_url", "type": "url", "label": "Service Base URL"}
  ],
  "optional": [
    {"name": "timeout_seconds", "type": "int", "label": "Request Timeout", "default": 30}
  ]
}
```

Platform Admin adds the agent URL → platform fetches AgentCard → renders configuration form. Tenant Admin fills in values. On every agent version update, the platform validates that existing tenant configurations satisfy the new schema — alerts for missing required fields before activating the update.

**Azure AD OBO — full prerequisites (corrected)**:

OBO (OAuth2 RFC 8693) is not "zero friction, nothing stored." The correct picture:

1. mingai must register as an Azure AD application in Microsoft Entra with appropriate MS Graph API permissions (`User.Read`, `Directory.Read.All`, `Group.Read.All`, etc.)
2. **Each tenant's Azure AD Global Administrator must grant admin consent** to mingai's registered app — this is a one-time tenant onboarding step, not runtime auto-delegation
3. mingai's platform stores its own `client_id` and `client_secret` for the AAD app registration (platform-level credentials, not tenant-level)
4. At runtime: user's access token → mingai exchanges it for a Graph token using its platform credentials → Graph API is called with the user's delegated permissions

**What this means for onboarding**: "Admin consent required" is a procurement-stage event, not a UI click. Many enterprise security teams require a formal approval workflow. This must appear in the tenant onboarding checklist and sales cycle. Describing it as transparent and frictionless is inaccurate.

**Why OBO still matters**: Once granted, the agent acts with the user's own Graph permissions — not a privileged service account. A restricted user cannot access HR data even if the agent has the capability. Enterprise security audits pass this; static API keys fail it.

**Why JWT assertion matters for Oracle Fusion**: Oracle Fusion enterprise SSO uses JWT private key assertion (OAuth2 RFC 7523). The tenant owns their Oracle Fusion instance and provides their JWT private key. The platform stores it encrypted in the tenant-scoped vault and injects it at agent invocation time — transparent to the user.

---

## Agent Template System

Platform Admin builds **templates**. Tenant Admin instantiates **instances** from templates. This is the core of the 80/15/5 model applied to agents.

### Template Components (Platform-Defined — 80%)

```
Agent Template:
├── identity
│   ├── id: "bloomberg"
│   ├── name: "Bloomberg Intelligence Agent"
│   ├── description: "Real-time financial market data via Bloomberg Data License API"
│   └── version: "1.0.0"
│
├── prompt                        ← Agent identity, expertise, reasoning style
│   └── "You are a Bloomberg financial intelligence specialist with access to
│          the Bloomberg Data License API. Your role is to provide accurate,
│          real-time financial market data and analysis..."
│
├── guardrails                    ← Behavioral constraints tenants CANNOT override
│   ├── "Only answer finance and market data questions"
│   ├── "Always cite Bloomberg Data License as data source"
│   ├── "Never speculate on forward-looking metrics without explicit disclaimer"
│   └── "Do not provide investment advice — provide data only"
│
│   ⚠️  ENFORCEMENT REQUIRED — strings alone are not enforceable:
│   Option A (recommended): Inject guardrails AFTER tenant extension in the
│              final system prompt so they take positional precedence.
│              Format: [base_prompt] + [tenant_extension] + [GUARDRAILS_BLOCK]
│   Option B: Run a lightweight LLM guardrail-audit pass on tenant extensions
│              at registration time (not at inference time — one-time check).
│   Option C: Output filter on all agent responses before returning Artifact.
│   All three should be layered. Design required before production.
│
├── mcp_url: "http://bloomberg-mcp:9000"    ← MCP server this agent uses
│
├── credential_schema             ← Defines WHAT tenant must provide
│   ├── type: "oauth2_bsso"
│   └── required_fields: [bloomberg_client_id, bloomberg_client_secret, bloomberg_account]
│
├── skills                        ← AgentCard skills array (A2A discovery)
│   ├── {id: "financial-data", tags: ["finance", "bloomberg", "market-data", "equity"]}
│   └── {id: "market-news", tags: ["news", "earnings", "bloomberg"]}
│
├── llm_config                    ← Agent inherits tenant's LLM selection (from Tenant Setup)
│   ├── use_case: "mcp_agent"
│   ├── temperature: 0.1
│   └── preferred_tier: "reasoning" | "standard"
│         reasoning → use tenant's reasoning-class model (for complex multi-tool orchestration)
│         standard  → use tenant's standard model (for straightforward single-tool agents)
│         Actual model resolved at runtime from Tenant LLM Setup — NOT specified per agent.
│
│   ─────────────────────────────────────────────────────────────────────────
│   Tenant LLM Setup (Tenant Admin → Settings → LLM Configuration):
│   ─────────────────────────────────────────────────────────────────────────
│   Platform maintains an LLM Library: curated set of approved providers and
│   models available per plan tier. Tenant admin selects ONE of:
│
│     Option A — Platform LLM Library (Starter / Professional / Enterprise):
│       Select provider + model from platform-approved list
│       Providers: Azure OpenAI, OpenAI, Anthropic, Google Gemini, Deepseek,
│                  Alibaba DashScope (Qwen), Bytedance Ark (Doubao)
│       Token usage tracked → billed at platform markup rate
│
│     Option B — BYOLLM (Enterprise only):
│       Tenant provides own API key + endpoint
│       Token usage tracked for observability only — billing SKIPPED
│       (tenant pays their provider directly; platform takes no cut)
│
│   All agents in the tenant use this single LLM configuration.
│   Platform admin curates which providers/models appear in the Library per tier.
│
└── plan_tier: "professional"     ← Minimum plan to access this agent
```

### Tenant Instance (15% Configurable)

```
Tenant Instance (Acme Corp → Bloomberg):
├── base_template: "bloomberg"
├── enabled: true
├── credential_values (encrypted, tenant-scoped vault)
│   ├── bloomberg_client_id: "acme-bloomberg-001"
│   ├── bloomberg_client_secret: "..."
│   └── bloomberg_account: "acme-catalog-id"
│
├── prompt_extension (optional — additive, cannot override guardrails)
│   └── "Our portfolio companies include: AAPL, MSFT, JPM, GS.
│          Prioritize analysis relevant to equity long/short strategies."
│
├── topic_scope (optional)
│   └── ["equity", "fixed-income", "fx"]   ← Tenant restricts to their use cases
│
└── user_rbac
    └── [role_ids permitted to invoke this agent]
```

### AgentCard (`/.well-known/agent.json`)

Each agent instance publishes its capabilities for A2A discovery:

```json
{
  "name": "Bloomberg Intelligence Agent",
  "description": "Real-time financial market data and analysis via Bloomberg Data License API",
  "version": "1.0.0",
  "url": "https://bloomberg-agent.{tenant}.mingai.io",
  "provider": { "organization": "mingai", "url": "https://mingai.io" },
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": true
  },
  "authentication": { "schemes": ["Bearer"] },
  "skills": [
    {
      "id": "financial-data",
      "name": "Financial Data Retrieval",
      "description": "Price, PE ratio, market cap, dividend yield, financial statements for any ticker",
      "tags": ["finance", "bloomberg", "market-data", "stocks", "equity"],
      "examples": [
        "What is Apple's current P/E ratio?",
        "Compare TSLA and RIVN on market cap and revenue TTM"
      ],
      "inputModes": ["text"],
      "outputModes": ["text", "data"]
    },
    {
      "id": "market-news",
      "name": "Market News",
      "description": "Latest news, earnings reports, analyst coverage via Bloomberg",
      "tags": ["news", "earnings", "bloomberg"],
      "examples": ["Latest news about Microsoft", "AAPL earnings risk factors"]
    }
  ]
}
```

---

## Google A2A v0.3 Wire Protocol

mingai implements the Google A2A v0.3 specification for all agent communication. A2A was open-sourced by Google in April 2025 and submitted to the Linux Foundation for incubation — it is an **emerging specification, not yet a ratified standard**.

**Protocol risk — mitigation required**: The DAG orchestration engine MUST sit behind a protocol abstraction layer. The `AgentDispatcher` interface is the only component that knows the wire format. Planner, DAG engine, Tool Catalog, and synthesis layer are all wire-protocol-agnostic. If A2A is superseded (by OpenAI Agent Protocol, Anthropic's own agent protocol, or a future IETF standard), only the dispatcher is re-implemented.

Building on A2A v0.3 today is still the right call: it has the broadest emerging adoption and Google's organizational weight behind it. The abstraction layer is the hedge.

### Task Dispatch (Orchestrator → Agent)

```http
POST https://bloomberg-agent.{tenant}.mingai.internal/tasks
Authorization: Bearer {tenant_scoped_jwt}
Content-Type: application/json

{
  "id": "task-{uuid}",
  "sessionId": "sess-{conversation_id}",
  "message": {
    "role": "user",
    "parts": [{
      "type": "text",
      "text": "Get AAPL and MSFT: current price, PE ratio, market cap, and revenue TTM"
    }]
  },
  "metadata": {
    "tenant_id": "tenant-abc123",
    "dag_node_id": "node-A",
    "parent_run_id": "run-xyz789"
  }
}
```

`dag_node_id` and `parent_run_id` are orchestrator-internal tracing metadata returned as-is in the response. The agent ignores them for execution purposes.

**Critical invariant**: The agent receives only its message content. It does not receive the full DAG, the execution plan, or what other agents are doing. Task-blind by design.

### Task Response (Agent → Orchestrator, SSE Stream)

```
data: {"id":"task-{uuid}","status":{"state":"submitted","timestamp":"..."},"final":false}

data: {"id":"task-{uuid}","status":{"state":"working"},"artifact":{"parts":[{"type":"text","text":"Querying Bloomberg for AAPL and MSFT..."}]},"final":false}

data: {"id":"task-{uuid}","status":{"state":"completed","timestamp":"..."},"artifact":{"name":"bloomberg-financials","parts":[{"type":"data","data":{"AAPL":{"price":192.30,"pe_ratio":28.5,"market_cap":"2.9T","revenue_ttm":"385B"},"MSFT":{"price":415.20,"pe_ratio":36.1,"market_cap":"3.1T","revenue_ttm":"245B"}}}]},"final":true}
```

The `Artifact` carries **typed structured data** alongside natural language. The orchestrator extracts `artifact.parts[0].data` and stores it against `node-A` in the DAG state for downstream synthesis.

### A2A Task Lifecycle

```
submitted → working → completed
                   ↘ failed        (agent internal error, e.g., Bloomberg API down)
                   ↘ canceled      (orchestrator timeout or upstream dep failed)
```

Each agent implements the full lifecycle and streams state transitions via SSE.

---

## DAG Orchestration: Orchestrator-Owned Execution

### How the DAG Is Built

When a user query arrives, the orchestrator's planning LLM produces an internal DAG. No agent ever sees this DAG.

**DAG planner — validation layer required**: The planning LLM output is non-deterministic. Before any node is dispatched, the generated DAG MUST be validated:

1. **Schema validation**: Planner must output strict JSON (`{nodes: [{id, type, agent_or_tool, task_text, deps: []}], ...}`). Reject malformed output, retry with error feedback.
2. **Cycle detection**: Run topological sort before execution. Cyclic dependencies cause infinite waits.
3. **Agent ID verification**: Every `agent_id` in the DAG is looked up in the registry with exact match. No partial matches, no LLM hallucination of agent names.
4. **Deterministic routing**: Agent selection at plan time is deterministic (registry lookup), not at dispatch time.
5. **Context budget**: Planner model context window must accommodate the query + registry summary + history. Use a lighter model (intent/planning tier) with a capped output schema to avoid runaway planning costs.

```
User: "Compare Apple vs Microsoft: financials, latest news, analyst sentiment,
       and check if our head of research Sarah Chen holds shares in either"

Orchestrator DAG:
─────────────────────────────────────────────────
Node A [AGENT:bloomberg]     → "Get AAPL and MSFT: price, PE ratio, market cap, revenue TTM"
                               deps: []

Node B [AGENT:perplexity]    → "Find analyst sentiment for AAPL and MSFT, last 30 days"
                               deps: []

Node C [TOOL:search_internet] → query: "AAPL MSFT stock news last 7 days"
                                deps: []

Node D [TOOL:azure_ad_mcp]   → get_user_info("sarah.chen@company.com")
                               deps: []

Node E [AGENT:capiq]         → "Get credit metrics and peer comparables for AAPL and MSFT"
                               deps: []

Node F [SYNTHESIZE]          → deps: [A, B, C, D, E]
```

### DAG Execution

```
Round 1 — All nodes with no deps dispatch in parallel:
  Orchestrator → POST bloomberg-agent/tasks    {"text": "Get AAPL and MSFT: price, PE..."}
  Orchestrator → POST perplexity-agent/tasks  {"text": "Find analyst sentiment..."}
  Orchestrator → call Tavily("AAPL MSFT news last 7 days")          [direct tool call]
  Orchestrator → call azure-ad-mcp → get_user_info("sarah.chen...")  [direct MCP call]
  Orchestrator → POST capiq-agent/tasks       {"text": "Get credit metrics..."}

  [All five execute independently and simultaneously]
  [SSE streams from A2A agents arrive as they complete]
  [Tool calls return synchronously]

Round 2 — Node F (all deps satisfied):
  Orchestrator collects all 5 Artifacts
  → synthesis LLM call with all artifacts as context
  → stream final answer to user
```

### What the DAG Enables vs aihub2

| Capability               | aihub2 (flat tool list, sequential)     | mingai (DAG, parallel)                       |
| ------------------------ | --------------------------------------- | -------------------------------------------- |
| Parallel agent execution | No — one tool call per iteration        | Yes — all independent nodes simultaneously   |
| Dependency tracking      | No                                      | Yes — downstream waits on upstream artifacts |
| Agent autonomy           | None — orchestrator decides every query | Full — agents decide their own tool calls    |
| Partial failure handling | Skip iteration, retry whole loop        | Retry failed node only; others continue      |
| Execution transparency   | Tool call logs                          | Full DAG state machine, auditable per run    |
| External agent support   | Not applicable                          | First-class — any A2A-compliant agent        |

---

## Tool Catalog

Tools are the orchestrator's direct-call capabilities. No A2A, no LLM reasoning, no delegation — deterministic input → output.

### Built-in Tools (Platform-Managed)

| Tool              | Source in aihub2                | Description                     | Credential       |
| ----------------- | ------------------------------- | ------------------------------- | ---------------- |
| `search_internet` | `INTERNET_SEARCH_TOOL` (Tavily) | Web search via Tavily REST API  | Platform API key |
| `calculate`       | None (new)                      | Safe math expression evaluation | None             |
| `get_weather`     | None (new)                      | Location weather via REST API   | Platform API key |

`search_internet` is the direct migration of aihub2's Tavily integration — elevated from a baked-in tool call to a first-class governed catalog entry.

### Extensible Registry

Platform Admin registers new tools via Admin UI:

```
Tool Registration:
  id:              "convert_currency"
  description:     "Convert between currencies using live exchange rates"
  endpoint:        "https://currency-api.internal/convert"
  input_schema:    {amount: number, from_currency: string, to_currency: string}
  output_schema:   {result: number, rate: number, timestamp: string}
  credential_type: api_key
  credential_ref:  vault://platform/currency-api-key
  plan_tier:       starter
```

New tools are immediately available to the orchestrator's DAG planner once registered.

---

## Platform Agent Registry

The registry is the central catalog of all agents available on the platform.

```
Platform Agent Registry
├── Platform Agents (built-in templates — platform-managed)
│   ├── bloomberg      (financial data — Professional+)
│   ├── perplexity     (web search — Starter+)
│   ├── oracle-fusion  (ERP data — Enterprise)
│   ├── capiq          (credit/deals — Professional+)
│   ├── ilevel         (investment analytics — Professional+)
│   ├── alphageo       (geospatial intelligence — Professional+)
│   ├── teamworks      (project management — Starter+)
│   ├── pitchbook      (M&A intelligence — Professional+)
│   └── azure-ad       (directory lookup — Starter+)
│
├── Tenant Agents (Enterprise plan — BYOMCP, tenant-built)
│   └── {tenant-id}-{agent-id}  (registered by Tenant Admin)
│
└── Marketplace Agents (external — EATP-verified, Google A2A compliant)
    ├── reuters-agent    (verified, signed AgentCard)
    └── refinitiv-agent  (verified, signed AgentCard)
```

### Orchestrator Agent Discovery

At planning time, the orchestrator queries the registry filtered by tenant + user context:

```
1. Registry query: get_available_agents(tenant_id, user_id)
   Returns: [{
     agent_id,
     skills,
     plan_tier_ok,
     credentials_configured,
     health: {
       state: "healthy" | "degraded" | "unavailable",
       reason: "ok" | "infra_failure" | "auth_failure" | "rate_limited",
       last_checked_ms: int
     }
   }]

2. Planner LLM: matches query requirements to agent skills
   Method: semantic similarity on skill descriptions + tag matching on AgentCard
   (Kaizen's select_worker_for_task() is used here)

3. Builds DAG using only: available + credentialed + healthy agents

4. Fallback if required agent unavailable:
   → "auth_failure": surface explicit error ("Bloomberg credentials expired") — no substitution
   → "infra_failure": retry once; if still unavailable, surface gap to user — no substitution for financial data
   → "rate_limited": queue and retry after Retry-After header; inform user of delay
   ⚠️  Domain-aware fallback: Bloomberg (market data) CANNOT be substituted with Perplexity
       (web search). Fallback substitution is only valid for generic research tasks.
   → Surface explicit gap to user if no valid alternative exists
```

---

## External Agent Marketplace

The marketplace is the long-term network effect moat. Any organization that implements Google A2A v0.3 can register their agent on the platform and serve mingai tenants.

### Onboarding Flow

```
External Agent Publisher:
1. Implement Google A2A v0.3 spec (Task/Artifact/AgentCard/SSE)
2. Publish AgentCard at /.well-known/agent.json with EATP signature
3. Submit registration to mingai marketplace

Platform Admin:
4. Register agent URL in Platform Agent Registry
5. Platform fetches and verifies AgentCard + EATP signature
6. Run capability probe (test Task → verify Artifact format)
7. Classify: {tier: "marketplace", verified: true, publisher: "Reuters News"}
8. Set plan_tier: "enterprise" (marketplace agents are Enterprise only)

Tenant Admin:
9. Browse marketplace, select Reuters agent
10. Configure required credentials (Reuters subscription key) if needed
11. Enable for org users per RBAC

Users:
12. Query platform → orchestrator discovers Reuters agent via registry
    → dispatches A2A Task automatically → Reuters agent answers
```

### EATP Trust Verification

External agents must present a signed AgentCard per EATP (Enterprise Agent Trust Protocol). Platform verifies:

- Publisher signature on AgentCard (cryptographic, not just claimed)
- Capability claims match actual implementation (live capability probe)
- No undisclosed write capabilities (read-only agents declared as such)
- Tenant data does not flow to publisher without explicit consent disclosure

---

## Prompt Library (Designed Gap)

The current design does not include a prompt management system. This is a **required component** before production, identified here as a scoped gap.

**What it must cover:**

| Component                | Description                                                                               |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| Base prompt versioning   | Platform-defined prompt per agent template, version-controlled and auditable              |
| Tenant prompt extensions | Additive only — tenants extend the base prompt but cannot override safety guardrails      |
| Prompt lifecycle         | draft → review → active → deprecated                                                      |
| Topic scoping            | Operator-defined topic boundaries (Bloomberg agent = finance topics only)                 |
| Safety guardrails        | Non-overridable constraints (content policy, citation requirements, no investment advice) |
| Evaluation hooks         | Automated prompt quality scoring against golden test sets                                 |

This maps to the **"Topics and prompts"** pillar in Oracle AI Agent Studio. Design scheduled for the Admin UI implementation phase.

---

## Oracle AI Agent Studio Mapping

Oracle AI Agent Studio (5 pillars) validates the product direction:

| Oracle Pillar                 | Oracle Items                                                                    | mingai Equivalent                                                                                          | Gap?                         |
| ----------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ---------------------------- |
| **Agent and agent teams**     | Templates, Custom agents, Agent teams, Workflow agents, Agent builder assistant | Platform Agent Registry: 9 templates + tenant custom + DAG teams                                           | None                         |
| **Tools**                     | Calculator, REST API, MCP, A2A, Deep link, Document                             | Tool Catalog (Tavily, Calculator, Weather + extensible). **Note: our 9 MCP servers are Agents, not tools** | None                         |
| **Topics and prompts**        | Agent instructions, Prompt libraries, Topics management                         | Prompt Library                                                                                             | **Designed gap — see above** |
| **Credentials**               | LLM providers, BYO LLM, 3rd party integrations                                  | Credential vault: OBO / JWT assertion / API key. BYOLLM.                                                   | None                         |
| **Monitoring and evaluation** | Tracing, Observability, HiTL, Evaluation                                        | Platform Analytics + per-tenant dashboards + A2A task tracing                                              | Partially designed           |

**Key divergence from Oracle**: Oracle lists MCP and A2A together as "Tools" in their UX. In mingai's architecture, MCP is the internal data layer each agent uses, and A2A is the communication protocol between orchestrator and agent. They are layered, not equivalent. The agent abstraction hides this from users — they see agents and tools, not protocols.

---

## Platform Model: Producers, Consumers, Partners

mingai's agent platform is a multi-sided marketplace. The network effects compound as each side grows.

### Three Sides

**Producers** (supply the intelligence):

- mingai platform team: builds and maintains the 9 agent templates and tool catalog
- Enterprise data vendors: Bloomberg, Oracle, CapIQ (their data surfaces through agents)
- Tenant engineering teams: build custom agents for proprietary data sources (Enterprise plan)
- External developers: build A2A-compliant agents for marketplace distribution

**Consumers** (demand the intelligence):

- Enterprise knowledge workers: analysts, researchers, operations staff querying via chat
- Tenant Admins: configure which agents serve their organization
- Orchestrator: consumes agent Artifacts to synthesize answers

**Partners** (facilitate the transaction):

- LLM providers: Azure OpenAI, Anthropic, Google Gemini (reasoning layer for agents + orchestrator)
- Auth providers: Auth0, Azure AD (credential delegation, OBO flows)
- Data platform vendors: Bloomberg DL, Oracle Cloud, CapIQ, PitchBook (the underlying data)

### Network Effect Compounding

```
More agents registered
    → richer query coverage
        → more user value per query
            → more enterprise tenants
                → larger tenant base = more attractive to marketplace publishers
                    → more marketplace agents register
                        → richer query coverage (loop compounds)
```

The Platform Agent Registry is the compounding asset. Every external agent added makes the platform more valuable to every existing tenant.

---

## AAA Framework Analysis

### Automate (Reduce Operational Costs)

- Orchestrator auto-selects agents from AgentCard skills — no user needs to know which agent to use
- Parallel DAG execution replaces sequential, manual multi-source research workflows
- Per-tenant circuit breakers auto-isolate failures — no ops intervention required
- Credential injection at runtime — no user manages API keys for Bloomberg/Oracle/CapIQ

### Augment (Reduce Decision-Making Costs)

- Bloomberg-grade financial analysis accessible without a Bloomberg Terminal or operator training
- Oracle Fusion ERP data surfaced in natural language — no ERP UI knowledge required
- Azure AD org chart and directory lookups embedded in conversational context
- Cross-source synthesis (Bloomberg + CapIQ + Perplexity + KB) that takes an analyst 45 minutes — produced in one parallel DAG execution

### Amplify (Reduce Expertise Costs for Scaling)

- One Bloomberg agent template deployed once → available to all tenants with valid credentials
- Custom agent built once by enterprise engineering team → accessible to all eligible users in the org
- Marketplace agents allow specialized expertise (Reuters, Refinitiv, domain-specific data) to scale beyond platform team capacity
- A new analyst at any tenant gets the same data access as a 10-year veteran on day one

---

## Unique Selling Points

### USP 1: Template-Driven Enterprise Agent Deployment

**What**: Platform ships Bloomberg/Oracle Fusion/CapIQ/etc. agent templates. Tenant provides their enterprise credentials. Zero engineering to deploy enterprise-grade data agents.

**Why it's unique**: Competitors require custom engineering to integrate enterprise data sources, or offer generic "bring your own tool" with no pre-built templates. The combination of pre-built enterprise agent templates + tenant credential injection is not available on any comparable platform.

**Moat depth**: Each agent template requires deep understanding of the external API (Bloomberg BSSO auth, Oracle Fusion JWT assertion, CapIQ rate limits) plus prompt engineering for that domain. The platform absorbs all this complexity once.

### USP 2: Credential-Aware Enterprise Authentication

**What**: The platform natively handles three enterprise auth patterns: OBO (Azure AD — user's own permissions), JWT assertion OAuth2 (Oracle Fusion), OAuth2 BSSO (Bloomberg). Not just API keys.

**Why it's unique**: Generic agent platforms treat all credentials as API keys. Enterprise deployments require auth flows that respect user identity and enterprise security policy. OBO means Azure AD agent acts as the user — not a service account — which passes enterprise security audits that static API keys fail.

**Moat depth**: Implementing Oracle Fusion JWT assertion OAuth2 correctly (RFC 7523, with proper key rotation) is non-trivial. Most platforms don't do it.

### USP 3: Open A2A Marketplace with EATP Trust Verification

**What**: External agents implementing Google A2A v0.3 plug into the platform. Trust verified via EATP-signed AgentCards before any tenant data flows to the external agent.

**Why it's unique**: Proprietary agent platforms lock tenants into their curated catalog. Our A2A-native + EATP architecture is the first enterprise RAG platform built around an open agent standard with verifiable trust.

**Moat depth**: First-mover on the A2A standard in the enterprise RAG space. External agent publishers prefer open-standard platforms over proprietary lock-in.

### USP 4: DAG-Native Parallel Multi-Agent Orchestration

**What**: The orchestrator decomposes queries into dependency graphs. Independent nodes execute in parallel. Multi-source research that would require sequential tool calls collapses to a single parallel round.

**Why it's unique**: LangGraph (LangChain) and CrewAI also support parallel DAG execution — the pattern alone is not the moat. The moat is the combination: **DAG orchestration over pre-built, enterprise-credentialed agents with complex auth flows (OBO, JWT assertion, OAuth2 BSSO)**. The orchestration pattern is the table stakes; the credentialed agent ecosystem is the moat.

**Performance implication**: A 5-agent parallel DAG where each agent takes 5 seconds completes in 5 seconds. Sequential: 25 seconds. At 3–8x LLM cost for agentic RAG (confirmed in doc 13), cutting latency is the primary lever for making agentic RAG feel responsive to enterprise users.

---

## Network Effects Coverage

| Network Behavior    | How mingai Achieves It                                                                                                                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Accessibility**   | A2A standard = any compliant agent plugs in with zero integration code. Admin UI = no-code agent configuration. OBO = zero-friction Azure AD auth — user never touches credentials                     |
| **Engagement**      | AgentCard skills expose capabilities in natural language. Orchestrator auto-selects agents based on query context. Users get the right expert agent without knowing it exists                          |
| **Personalization** | Tenant prompt extensions customize agent personality and focus. Tenant agent roster reflects their specific data subscriptions. User RBAC controls which agents each role can access                   |
| **Connection**      | MCP protocol connects each agent to any enterprise data source. A2A connects orchestrator to any compliant agent. EATP enables trusted external agent connections at marketplace scale                 |
| **Collaboration**   | DAG execution enables multi-agent joint research — artifacts flow between agents via dependency graph. Bloomberg Artifact feeds into synthesis alongside CapIQ and Perplexity Artifacts simultaneously |

---

## 80/15/5 Applied to the Agent Platform

### 80% — Platform Core (Agnostic, Reusable Across All Tenants)

- Google A2A v0.3 wire protocol implementation (Task/Artifact/AgentCard/SSE)
- Agent template system (5 components: prompt, guardrails, MCP URL, credential schema, skills)
- DAG orchestration engine (planner LLM, execution engine, Artifact collection, synthesis)
- Credential vault architecture (platform/tenant/user-OBO levels)
- All 9 agent templates (pre-built, platform-maintained)
- Tool Catalog engine (registration, routing, execution)
- Built-in tools: Tavily, Calculator, Weather
- Per-tenant circuit breakers
- Agent health monitoring and AgentCard verification
- EATP marketplace trust verification and capability probing

### 15% — Tenant-Configurable (Self-Service, No Engineering)

- Which agents are enabled per tenant (plan-gated)
- Credential values (Bloomberg account, Oracle JWT, CapIQ API key, etc.)
- Prompt extensions per agent instance
- User RBAC: which roles can invoke which agents
- Custom agent registration via Admin UI (Enterprise plan)
- Topic scoping per agent instance
- Tool catalog additions via Admin UI

### 5% — Custom (Requires Engineering)

- New MCP server development for a net-new data source
- Novel credential type not in the standard catalog
- Custom A2A agent for a highly proprietary internal workflow
- Bespoke agent coordination patterns not covered by DAG

---

## Plan Tier Feature Matrix

| Feature                           | Starter | Professional             | Enterprise               |
| --------------------------------- | ------- | ------------------------ | ------------------------ |
| Platform agents                   | 3 max   | All available            | All available            |
| Bloomberg / Oracle Fusion         | No      | Yes (tenant credentials) | Yes (tenant credentials) |
| CapIQ / PitchBook / iLevel        | No      | Yes (tenant credentials) | Yes (tenant credentials) |
| Azure AD / Perplexity / Teamworks | Yes     | Yes                      | Yes                      |
| Custom agents (BYOMCP)            | No      | No                       | Yes                      |
| Marketplace agents (external A2A) | No      | No                       | Yes                      |
| Multi-agent DAG execution         | No      | Yes (full DAG)           | Yes (full DAG)           |
| Concurrent DAG sessions           | 1       | 3                        | Unlimited                |
| Tenant prompt extensions          | No      | Yes                      | Yes                      |
| External A2A agent integration    | No      | No                       | Yes                      |
| Agent analytics                   | Basic   | Detailed                 | Detailed + export        |
| Per-tenant circuit breakers       | Yes     | Yes                      | Yes                      |

---

## Billing Model

### Core Principle: Token Markup Covers All Platform Costs

The platform does **not** own or pay for tenants' MCP data credentials (Bloomberg DL, CapIQ, Oracle Fusion, etc.). Tenants bring their own contracts and API keys. The platform's costs are:

- LLM inference (agent reasoning + orchestrator planning + synthesis)
- Docker hosting (agent containers, shared across tenants)
- Platform infrastructure (vault, registry, routing)

All these costs are recovered via **percentage markup on token usage**. No separate hosting line items — this keeps pricing simple and encourages usage.

### Billing by Scenario

| Scenario                            | LLM Billing                                                                  | MCP/Data Cost                                            | Hosting Recovery               |
| ----------------------------------- | ---------------------------------------------------------------------------- | -------------------------------------------------------- | ------------------------------ |
| In-house agent + platform LLM       | Track tokens → tenant billed at marked-up rate                               | Tenant's credential, tenant's contract                   | Bundled in token markup        |
| In-house agent + tenant BYOLLM      | Token tracking for observability only — billing skipped                      | Tenant's credential, tenant's contract                   | Bundled in base plan tier      |
| Orchestrator (planning + synthesis) | Always platform LLM → always tracked + billed                                | N/A                                                      | Bundled in token markup        |
| External caller → in-house agent    | Tracked → billed at **external API rate** (higher markup = hosting + profit) | External caller provides own MCP credentials per request | Bundled in external markup     |
| Tenant → external A2A agent         | Orchestrator tokens billed (planning + synthesis)                            | External agent's own cost, not platform's concern        | Bundled in orchestrator markup |

### External Caller Model (A2A as a Service)

External platforms that call mingai agents:

1. Register as an API caller on the platform (get API credentials)
2. Send A2A Tasks with their own MCP credentials in request metadata
3. Are billed at the **external API rate**: token cost × (1 + external_markup) where external_markup > tenant_markup
4. The external markup covers: Docker hosting amortization + profit margin for API-as-a-service usage
5. External callers pay for the platform LLM reasoning; their MCP API costs are their own

### Markup Rate Structure

```
Token rates (illustrative):
  actual_cost = LLM provider's cost per token (model-dependent)

  tenant_rate    = actual_cost × 1.3   (30% markup — hosting + margin)
  external_rate  = actual_cost × 1.6   (60% markup — higher margin for API service tier)

  BYOLLM tenants pay base plan tier only (no per-token billing from platform)
```

Markup rate is percentage-based, not flat-per-token — this correctly handles the wide cost spread between LLM models (GPT-4o at ~$5/M tokens vs. Gemini Flash at ~$0.075/M tokens).

### Instrumented LLM Client (Engineering Requirement)

Every platform-built agent must use a **platform-instrumented LLM client wrapper** — not raw provider SDKs. The wrapper:

- Always records: `{tenant_id, agent_id, model, input_tokens, output_tokens, latency_ms}`
- Emits to billing service only when tenant LLM source is platform LLM Library (skips billing for BYOLLM)
- Emits to observability pipeline always (for debugging, SLA monitoring, runaway usage detection)

Without this, the platform has no visibility into agent-level token consumption.

**LLM Source Resolution**:

```
Tenant LLM Setup → model_source flag
  "library" → tenant selected a model from Platform LLM Library
               → tokens tracked and billed at tenant markup rate
  "byollm"  → tenant brought their own API key/endpoint
               → tokens tracked for observability only (billing skipped)
```

The instrumented client reads the tenant's `model_source` flag from tenant config at request time — no agent-level configuration needed.

---

## Migration from aihub2

| aihub2 Component                     | Action    | mingai Target                                                      |
| ------------------------------------ | --------- | ------------------------------------------------------------------ |
| `research_agent.py` ToolPlanner      | Replace   | Orchestrator DAG planner (LLM builds dependency graph)             |
| `research_agent.py` ToolExecutor     | Replace   | DAG execution engine (dispatches A2A Tasks + tool calls)           |
| `research_tools.py` `query_mcp:{id}` | Replace   | A2A Task dispatch to the appropriate agent                         |
| `INTERNET_SEARCH_TOOL` (Tavily)      | Migrate   | Tool Catalog entry: `search_internet`                              |
| Per-server `.env` credentials        | Migrate   | Tenant credential vault per agent instance                         |
| Global circuit breakers              | Replace   | Per-tenant, per-agent circuit breakers                             |
| `MCPService._ensure_agents_loaded()` | Replace   | Platform Agent Registry (lazy load, tenant-scoped)                 |
| Custom `A2AMessage` dataclass        | Replace   | Google A2A v0.3 wire protocol                                      |
| `ExecutionPlan` sent to agents       | Eliminate | Orchestrator keeps plan internal; agents receive only atomic Tasks |

---

## Open Questions Before Implementation

Items marked **DECISION REQUIRED** block architecture finalization.

1. **Prompt Library design** — Required before any agent template is deployed. Guardrail enforcement mechanism (system prompt positional ordering + output filter) must be specified. See guardrails section for options.

2. **Cross-agent artifact dependencies (architecture clarification)** — Dependent nodes are NOT parallel. When Node E (CapIQ) needs data from Node A (Bloomberg), Node E has `deps: [A]` and dispatches only after Node A's Artifact arrives. The orchestrator injects the upstream data into Node E's Task message. The DAG examples in this document show `deps: []` for illustration; real DAG planning must model data dependencies explicitly. True parallel execution only applies to genuinely independent tasks.

3. **Agent LLM cost model — RESOLVED**: LLM selection is a **tenant-level setting** (Tenant Admin → Settings → LLM Configuration), not per-agent. Platform maintains an LLM Library (curated approved providers per plan tier). Tenant selects from Library or brings their own (BYOLLM). All agents in the tenant use this single LLM configuration. Token billing: library LLM → tracked + billed at markup; BYOLLM → tracking only. See Billing Model section.

4. **Bloomberg technical/legal review — OPEN**: Bloomberg DL API access from a SaaS intermediary may violate Bloomberg's data redistribution terms. The credential model shown (OAuth2 BSSO) requires validation against actual Bloomberg B-PIPE SDK or BEAP access patterns. A Bloomberg technical and legal review must occur before committing any Bloomberg agent implementation. Do not begin Bloomberg agent engineering without this.

5. **External marketplace trust — RESOLVED**: Drop EATP for marketplace. Use Google A2A v0.3 AgentCard mechanisms only — consistent with open marketplace commitment and bidirectional agent deployment. Platform trust verification is: domain verification + capability probe + admin approval workflow + UI disclosure of verification status.

6. **Data residency for marketplace agents** — When a user query is sent as an A2A Task to an externally-hosted agent, the Task message content leaves platform infrastructure. Required before any marketplace agent goes live: (a) explicit tenant admin consent at agent-enable time, (b) data egress logging, (c) GDPR/data sovereignty legal review per agent publisher. European tenants may be blocked from using US-hosted marketplace agents.

7. **Agent versioning** — Tenant instances pin to a template version. Platform notifies of available updates; Tenant Admin explicitly approves migration. Breaking template changes (new guardrails, new credential schema fields) require explicit tenant migration, not silent auto-update.

8. **JWT key rotation lifecycle (Oracle Fusion)** — The credential vault must track Oracle JWT key expiry, send tenant notifications at 30/15/7 days before expiry, gracefully queue in-flight calls during rotation, and return a clear error on expiry (not silent failure). This is an operational requirement, not optional.

9. **Synthesis context window** — For 5+ agent DAGs, the synthesis LLM call may receive Artifacts that collectively exceed its context window. A structured-extraction pass per Artifact (extract only the relevant answer fields, not full raw data) must run before synthesis. Define the extraction schema per agent Artifact type before the synthesis step is implemented.

---

**Document Version**: 2.3
**Replaces**: 06-a2a-mcp-agentic.md v1.0, v2.0, v2.1, v2.2
**Last Updated**: March 4, 2026
**Red-Team Pass**: v2.0 → v2.1 (25 findings addressed, 3 decisions flagged) → v2.2 (decisions resolved) → v2.3 (LLM selection clarified: tenant-level LLM Library)
**Status**: Architecture Design — 1 OPEN ITEM (Bloomberg legal/technical review required before agent implementation)
