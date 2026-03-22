# Agent Studio — Conceptual Model
*Derived from design discussion, March 2026*

## The Foundational Hierarchy

Three tiers of capability, each building on the one below:

```
Tools      — atomic operations (API calls, platform functions)
Skills     — reusable LLM-powered capability patterns
Agents     — full governed runtime entities
```

Tools do one thing. Skills compose tools into reusable reasoning patterns. Agents are complete entities with identity, knowledge, capabilities, interface, and safety.

---

## Tier 1: Tool Catalog

Atomic operations. Each tool does exactly one thing and returns a structured result. No LLM reasoning involved.

### Three sources

**Built-in tools** — live inside the platform backend as direct functions. Web search, document OCR, calculator, data formatter, file reader. No external call, no credential needed. Available to any agent.

**MCP Integrations** — built via the MCP Integration Builder. PA uploads an API doc (OpenAPI spec, Postman collection, or raw documentation). Platform parses it, presents endpoints, PA selects which become tools, names them, defines credential schema, sets rate limits and plan gate. Platform generates thin HTTP wrappers. No separate container — the Tool Executor inside the backend handles outbound calls with credential injection at runtime.

```
PitchBook integration → 6 tools:
  pitchbook_search_companies
  pitchbook_get_company_profile
  pitchbook_search_investors
  pitchbook_get_deal_history
  pitchbook_get_investor_portfolio
  pitchbook_search_funds
```

**Tenant MCP servers** — TA registers their own MCP endpoint. Private to their org. Tools available only within that tenant's agent instances.

### MCP Integration Builder flow
1. PA uploads API doc (OpenAPI JSON/YAML, Postman, or raw docs)
2. Platform parses → presents endpoint list
3. PA selects endpoints, names tools, writes descriptions
4. PA defines credential schema (what tenants must provide)
5. PA sets rate limits and plan gate
6. Platform registers thin HTTP wrapper in Tool Executor
7. Tools appear in catalog, available for skill and agent authoring

### Tool record structure
```
Tool {
  id, name, description
  input_schema: JSONSchema
  output_schema: JSONSchema
  executor: "builtin" | "http_wrapper" | "mcp_sse"
  endpoint_url?: string
  credential_schema: CredentialField[]
  credential_source: "none" | "platform_managed" | "tenant_managed"
  rate_limit: { requests_per_minute: int }
  plan_required: "starter" | "professional" | "enterprise"
  scope: "platform" | tenant_id
}
```

---

## Tier 2: Skills Library

Skills sit between tools and agents. A skill is a **reusable, versioned, LLM-powered capability pattern** — higher-level than a tool, lighter than a full agent. No identity, no KB, no A2A card. A composable unit of intelligence that agents draw from.

### What a skill contains
- Name, description, category, version, changelog
- Input schema / output schema (JSON Schema)
- Internal prompt template (references input variables)
- Optional tool dependencies (tools the skill calls internally)
- LLM config (temperature, model preference — or inherit from agent)
- Invocation mode: `llm_invoked` (agent LLM decides when) or `pipeline` (runs automatically at a declared stage/trigger)

### The key distinction from tools
Tools do not involve LLM reasoning. Skills always involve LLM reasoning, even if simple. A tool returns data; a skill returns intelligence.

### Skill scoping — two levels

```
Platform Skills Library (PA-authored)
  ├── Available for all tenants to adopt
  ├── Plan-gated skills (Professional+, Enterprise only)
  └── Mandatory skills (PA-enforced on all tenant agents — cannot be removed)

Tenant Skills Catalog (per tenant)
  ├── Adopted platform skills (referenced, not copied — version-pinnable)
  └── Tenant-authored skills (private to this tenant)
```

**Adopt vs author distinction:**
- **Adopt** = tenant references a platform skill. Updates propagate unless tenant pins a version.
- **Author** = tenant creates their own skill. They own it entirely. Never visible to other tenants.

PA can browse tenant-authored skills and promote them to the platform library with tenant consent. Promotion is a manual PA action — skills never auto-publish upward.

### Skill execution patterns

**Pattern A: Pure prompt skill**
PA or TA writes a prompt template. At runtime, platform calls LLM with the prompt + injected input values. Output parsed against declared schema. No tool dependencies.

```
Skill: Summarization
Prompt: "Summarize the following content. Return: executive_summary
         (2-3 sentences), key_points (bullet list).
         Content: {{input.content}}
         Max words: {{input.max_words}}"
Input:  { content: string, max_words: int }
Output: { executive_summary: string, key_points: string[] }
```

**Pattern B: Tool-composing skill**
PA or TA selects tools from catalog. Writes an orchestration prompt. LLM decides when to call which tool, in what order. Platform runs the tool-calling loop.

```
Skill: Company Intelligence
Tools: [pitchbook_search_companies, web_search]
Prompt: "Build a comprehensive company profile using PitchBook for
         funding data and web_search for recent news. Synthesize into:
         company_overview, funding_history, key_investors, recent_news"
```

**Pattern C: Sequential pipeline skill**
PA or TA defines a fixed step sequence — deterministic, not LLM-decided. Step 1 always calls tool A, Step 2 always calls tool B with output from Step 1, Step 3 runs a prompt on combined data. Useful for compliance, legal, and financial workflows where the execution path must be auditable.

### Tenant skill authoring — constraints

Tenants can author skills with the same editor as PA, subject to three boundaries:

1. **Tool access is bounded by plan** — tenant can only use tools their subscription unlocks. Enterprise-gated tools (Bloomberg, CapIQ) unavailable to Professional-tier tenants. Tenant can use their own private MCP tools (unavailable to PA or other tenants).

2. **Scope is always tenant-private** — tenant-authored skills never auto-publish to the platform library. PA must explicitly promote them.

3. **Same injection validation** — prompt templates pass through SystemPromptValidator. Tenants cannot author skills that bypass guardrail constraints.

### Mandatory skills

PA can mark platform skills as mandatory — they run as enforced pipeline post-processors on every agent response in all tenants, or in specific plan tiers. Tenant cannot remove them. They appear grayed out in the skill attachment list — visible but locked. Used for platform-wide guarantees: PII masking, compliance watermarking, output audit logging.

### Platform built-in skills

| Skill | What it does | Tool dependencies |
|---|---|---|
| Summarization | Structured summary from any content | None |
| Entity Extraction | Names, dates, amounts, organizations from text | None |
| Sentiment Analysis | Tone and sentiment classification | None |
| Document Q&A | Answer a question from a specific document | None |
| Comparison | Compare N items against configurable criteria | None |
| Citation Formatter | Format sources into consistent citations | None |
| Translation | Multilingual content rendering | None |
| Risk Assessment | Evaluate content against risk criteria | None |
| Market Research | Research a topic across multiple sources | web_search |
| Financial Summary | Compute and narrate financial metrics | calculator |
| Company Intelligence | Full company profile synthesis | pitchbook_search_companies, web_search |

### PA-authored skills (examples)
- "Regulatory Compliance Check" — applies jurisdiction-specific rules to content
- "Contract Risk Scanner" — evaluates contract clauses against risk criteria
- "Earnings Call Analyst" — extracts key signals from earnings transcript

Skills are versioned independently of agents. Agents pin to a skill version; updates are opt-in.

### Skill record structure
```
Skill {
  id, name, description, category
  version: semver, changelog: string
  input_schema: JSONSchema
  output_schema: JSONSchema
  prompt_template: string          // references {{input.field_name}}
  execution_pattern: "prompt" | "tool_composing" | "sequential_pipeline"
  tool_dependencies: ToolRef[]
  pipeline_steps?: PipelineStep[]  // sequential_pipeline only
  invocation_mode: "llm_invoked" | "pipeline"
  pipeline_trigger?: string        // e.g. "response_length > 500"
  llm_config: {
    model?: string                 // null = inherit from agent
    temperature: float
    max_tokens: int
  }
  plan_required: "starter" | "professional" | "enterprise"
  scope: "platform" | tenant_id
  mandatory: boolean               // if true, tenant cannot remove
}
```

---

## Tier 3: Agent Templates

A complete governed runtime entity. The template is the PA-authored blueprint. The instance is what the tenant deploys, configures, and operates.

### Seven configuration dimensions

1. **Identity** — name, description, icon, category, tags
2. **LLM Policy** — required model, allowed providers, tenant override permission, defaults (temperature, max_tokens)
3. **System Prompt + Variables** — authored prompt, typed variable schema, injection-validated at authoring time
4. **Knowledge** — KB ownership mode (tenant_managed / platform_managed / dedicated), required/recommended categories
5. **Capabilities** — skills from library, tools from catalog, credential schema declaration
6. **A2A Interface** — operations contract, input/output schema, caller plan requirements
7. **Guardrails** — input filters, output filters, topic restrictions, PII masking, caller restrictions (floor — tenant cannot relax)

### The five agent types

**Type 1: RAG Agent**
Prompt + KB + LLM. No skills, no external tools. Most common type in the template library.
Examples: HR Policy Bot, IT Helpdesk, Procurement Assistant, Onboarding Guide.
Tenant adoption: bind KBs, fill variables, deploy.

**Type 2: Skill-Augmented Agent**
RAG + skills from the Skills Library. Inherits reusable capability patterns.
Example: Legal Research Agent attaches Document Q&A + Summarization + Citation Formatter skills.
Tenant gets sophisticated behavior without PA encoding all logic into one monolithic prompt.

**Type 3: Tool-Augmented Agent**
Skills + MCP tools. Agent can act externally, not just reason internally.
Example: PitchBook Research Agent attaches Company Intelligence skill (which internally uses pitchbook_search + web_search).
The skill provides the reasoning pattern; tools provide the data access.

**Type 4: Credentialed Integration Agent**
Type 3 where tools require tenant-provided credentials. Template declares credential schema.
Tenant provides OAuth tokens or API keys at deployment. Credentials stored in tenant vault, injected at call time.
Examples: Salesforce Agent, Jira Agent, Confluence Agent.

**Type 5: Registered A2A Agent**
External agent imported by its A2A card. Platform wraps but does not own the runtime.
PA or TA provides card URL. Platform reads operations contract, PA configures wrapper (plan gate, guardrails overlay, tenant assignment).
Two scopes: platform-registered (PA-licensed, available to eligible tenants) and tenant-registered (TA's own internal services, private).

### Template record structure (abbreviated)
```
AgentTemplate {
  // Identity
  id, name, description, icon, category, tags
  type: "native" | "registered_a2a"

  // LLM (native only)
  llm_policy: { required_model?, allowed_providers?, tenant_can_override, defaults }

  // Prompt (native only)
  system_prompt: string
  variable_schema: VariableDef[]

  // Knowledge (native only)
  kb_policy: {
    ownership: "tenant_managed" | "platform_managed" | "dedicated"
    recommended_categories: string[]
    required_kb_ids: string[]        // platform_managed only
  }

  // Capabilities (native only)
  attached_skills: SkillRef[]
  attached_tools: ToolRef[]
  credential_schema: CredentialField[]

  // A2A
  a2a_enabled: boolean
  a2a_interface: { operations[], auth_required, caller_requires_plan? }

  // Registered A2A (registered_a2a only)
  source_card_url?: string
  imported_card?: AgentCard

  // Guardrails
  guardrails: { input_blocks[], output_filters[], pii_masking, topic_restrictions[], caller_restrictions[] }

  // Lifecycle
  version: semver
  status: "draft" | "published" | "deprecated"
  changelog: ChangelogEntry[]
  plan_required: "starter" | "professional" | "enterprise"
}
```

---

## The Orchestrator

**Not in the Agent Studio. Not a template. Not authored by PA.**

A platform-provisioned system agent automatically created for every tenant at provisioning. It:
- Maintains a live registry of all agent instances deployed in that tenant
- Reads their A2A cards to understand what each handles
- Routes incoming queries to the right agent via A2A using a lightweight routing model
- Falls back to general RAG when confidence is below threshold

Routing quality is determined by the quality of descriptions and capability declarations in each template's A2A card — which PA controls at authoring time.

**Two global platform settings only:**
- Routing model (lightweight, GPT-5 Mini class)
- Confidence threshold for fallback

No per-tenant configuration. No Agent Studio surface.

---

## Runtime Execution

How the layers connect at query time:

```
User: "Who are the top Series B fintech investors in Southeast Asia?"

Orchestrator (system agent)
  → reads tenant deployed agent registry
  → routes to "PitchBook Research Assistant" (confidence: 0.94)
  → calls agent via A2A

PitchBook Research Assistant
  → LLM invokes "Company Intelligence" skill

  Company Intelligence Skill
    → calls pitchbook_search_investors (tool)
      → Tool Executor resolves tenant vault credential
      → HTTP call to PitchBook API with injected key
      → returns structured investor list
    → calls web_search (tool)
      → returns recent news on top investors
    → synthesizes: ranked profiles with recent activity

  Agent
    → invokes "Citation Formatter" skill on sources
    → applies LLM policy (GPT-5.2-chat, temperature 0.2)
    → applies guardrails (PII masking, topic filter)
    → streams response via A2A → orchestrator → user
```

The tenant never sees: API credentials, internal routing decisions, skill invocation logic, raw tool responses.

---

## The Agent Studio Surfaces

### Platform Admin surfaces (PA)

| Surface | Purpose |
|---|---|
| **Agent Template Studio** | Author native templates (Types 1-4) and register A2A agents (Type 5) |
| **Skills Library** | Author, version, publish platform skills; mark mandatory skills |
| **Tool Catalog + MCP Builder** | Manage built-ins; import API docs → tools; plan-gate tools |
| **Orchestrator** | Not here — platform system, auto-provisioned |

### Tenant Admin surfaces (TA)

| Surface | Purpose |
|---|---|
| **Agent Catalog** | Browse platform templates; adopt and deploy instances |
| **Agent Deployment Wizard** | Configure adopted template → create instance (KB bindings, variables, credentials) |
| **Tenant Skills** | Browse + adopt platform skills; author private skills |
| **Tenant MCP Tools** | Register private MCP servers; browse tenant-scoped tools |
| **Custom Agent Studio** | Author own agent templates using platform skills + tenant skills + available tools |
| **A2A Registration** | Register own external A2A agents (tenant-scoped) |

### Phasing decision
**TA surfaces ship first.** TA can adopt platform templates, configure instances, author skills, and build custom agents before PA has a full authoring studio. PA authoring studio (and MCP Builder) follows in the next phase, building on the TA surface patterns.

---

## Governance Model

```
Platform Admin
├── Authors native templates (Types 1-4)
├── Registers external A2A agents (platform scope)
├── Authors skills → Platform Skills Library
│     └── Can mark skills as mandatory (tenant cannot remove)
│     └── Can promote tenant-authored skills to platform library
├── Builds MCP integrations → Tool Catalog (via MCP Builder)
├── Sets plan gates on templates, skills, and tools
└── Sets guardrail floors (tenant cannot relax)

Tenant Admin
├── Adopts platform templates → deploys instances
├── Configures instances (KB bindings, variables, credentials)
├── Adopts platform skills → Tenant Skills Catalog
├── Authors own skills (tenant-scoped, private)
│     └── Tool access bounded by plan
│     └── Can use own private MCP tools
├── Registers own MCP servers (tenant-scoped)
├── Registers own A2A agents (tenant-scoped, private)
└── Authors custom agents using platform + tenant skills

End User
├── Auto mode: orchestrator routes transparently
├── Direct mode: selects specific agent from catalog
└── Never sees: routing, tools, credentials, skill logic

Platform System
└── Orchestrator: auto-provisioned per tenant
    routing: lightweight LLM reads A2A cards, confidence-gated fallback
```

---

## Full Architecture

```
Platform Intelligence Layer
├── Tool Catalog
│     ├── Built-in tools (platform functions, no external calls)
│     ├── MCP Integrations (API doc → HTTP wrappers via MCP Builder)
│     └── [Tenant MCP servers — tenant-scoped, private]
│
├── Skills Library
│     ├── Platform built-in skills (summarization, extraction, analysis)
│     ├── PA-authored skills (domain patterns, independently versioned)
│     └── Mandatory skills (enforced on all agents, tenant cannot remove)
│
├── Agent Template Library
│     ├── Type 1: RAG Agents
│     ├── Type 2: Skill-Augmented Agents
│     ├── Type 3: Tool-Augmented Agents
│     ├── Type 4: Credentialed Integration Agents
│     └── Type 5: Registered A2A Agents
│
└── Orchestrator Engine
      └── System agent, per-tenant, auto-provisioned
          reads A2A cards, routes via lightweight LLM

Tenant Runtime Layer
├── Tenant Skills Catalog
│     ├── Adopted platform skills (referenced, version-pinnable)
│     └── Tenant-authored skills (private)
├── Tenant Tool Extensions
│     └── Tenant-registered MCP servers
├── Deployed Agent Instances (adopted + configured)
├── Tenant-registered A2A Agents (private)
├── Tenant Credential Vault (encrypted, per-tenant)
└── KB Catalog (SharePoint, Google Drive, dedicated indexes)
```

---

## What the Current Implementation Is Missing

The existing `TemplateAuthoringForm` covers identity + system prompt + guardrails only. It has no concept of:

- Skills layer (library, adoption, authoring, attachment, mandatory enforcement)
- Tool picker from catalog
- MCP Integration Builder (API doc → tools)
- LLM policy (required model, tenant override permission)
- KB ownership modes (tenant_managed / platform_managed / dedicated)
- Credential schema declaration
- A2A interface contract definition
- Version lifecycle (semver, changelog, deprecation, instance migration)
- Registration flow for external A2A agents (Type 5)
- Tenant Skills Catalog (adopt platform skills + author private skills)
- Tenant Custom Agent Studio (TA-authored agents with skill + tool composition)

The current form was designed for four RAG seed templates. The product vision requires a complete agent intelligence platform with a three-tier capability hierarchy.

---

## Implementation Phasing

### Phase 1 — Tenant Admin first
TA surfaces ship before PA authoring studio. Tenants can adopt platform templates, configure instances, manage their own skills, register their own MCP tools and A2A agents, and build custom agents.

- Agent Catalog (browse + adopt platform templates)
- Agent Deployment Wizard (configure instance: KB, variables, credentials)
- Tenant Skills (browse + adopt platform skills; author private skills)
- Tenant MCP Tools (register private MCP servers)
- Custom Agent Studio (author own agents)
- A2A Registration (register own external agents)

### Phase 2 — Platform Admin authoring
PA studio builds on TA surface patterns. Adds platform-wide publishing, plan gating, mandatory skill enforcement, and the MCP Integration Builder.

- Agent Template Studio (author + register platform templates)
- Skills Library management (publish, version, mandate)
- Tool Catalog + MCP Builder
- Platform-level A2A registry

### Phase 3 — Performance + Analytics
Cross-tenant skill performance, tool usage analytics, orchestrator routing quality dashboard, agent adoption metrics.
