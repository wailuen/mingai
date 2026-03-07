# 10-04 — Platform Admin: Platform Model & AAA Framework

**Date**: 2026-03-05

---

## 1. Platform Model Analysis

### 1.1 Role Identification

**Producers** — create value that others consume:

- **Platform Admins**: curate LLM profiles, author agent templates, register and govern tools, set billing policies. Every configuration action they take produces value that tenant admins and end users consume.
- **Tool Providers** (external MCP server operators): build and maintain tools that agents invoke. They produce tool capability; agents consume it.

**Consumers** — receive and use the value:

- **Tenant Admins**: consume LLM profiles (selecting AI configuration), agent templates (deploying pre-built agents), tools (enabling agents to act), and billing transparency (understanding their usage)
- **End Users**: consume the AI output produced by the agent and model configurations the admin curated

**Partners** — facilitate transactions:

- **LLM Providers** (Azure OpenAI, Anthropic, etc.): supply inference; the platform routes to them based on profile selection
- **Cloud Infrastructure** (Azure, AWS): supplies compute, storage, search — the platform runs on it
- **Billing Infrastructure** (Stripe): processes payments; the platform reports usage, Stripe bills tenants
- **Identity Providers** (Auth0, Entra): authenticate users; the platform delegates auth

### 1.2 Core Transactions

Three transactions occur in this platform:

**Transaction 1: Intelligence Configuration**

```
Admin (producer) CONFIGURES LLM profile
→ Platform STORES + ENFORCES the configuration
→ Tenant Admin SELECTS the profile
→ End User RECEIVES AI responses shaped by that profile
```

Value created: tested, documented AI behavior without per-tenant manual setup. The admin's one-time configuration effort is consumed by many tenants.

**Transaction 2: Agent Capability Distribution**

```
Admin (producer) CREATES agent template
→ Admin PUBLISHES to template library
→ Tenant Admin INSTANTIATES the template (fills config variables)
→ End User INTERACTS with the deployed agent
→ Satisfaction data FLOWS BACK to admin for template improvement
```

Value created: working, governed, improving agents without per-tenant development. Feedback loop closes transaction cycle — admin improves template → all tenant instances improve.

**Transaction 3: Tool Enablement**

```
Tool Provider (producer) BUILDS MCP server
→ Admin REGISTERS + TESTS + CLASSIFIES tool in catalog
→ Tenant Admin ENABLES tool for specific agents
→ Agent INVOKES tool during task execution
→ Tool usage data FLOWS BACK to admin (frequency, health, error rate)
```

Value created: safe, governed access to external capabilities. Admin acts as quality gate between tool provider and tenant agent deployments.

### 1.3 Network Effects

**Cross-side (admin curation → tenant quality)**:
More curation effort by one admin → better profiles, templates, tools → more value for all tenants. The admin's investment scales across the tenant base without per-tenant cost. This is asymmetric: 1 admin action × N tenants = N × value delivered.

**Same-side (more tenants → better templates)**:
More tenants running the same template → more performance data → more accurate template improvement signals → better templates for all tenants. This is the multi-tenant template intelligence flywheel (USP 4).

**Data network effect (strongest moat)**:
Each query processed → satisfaction signal collected → health score updated → roadmap signal generated. The platform accumulates operational intelligence at a rate proportional to tenant count. Operators with 100 tenants have 100× the improvement signal of operators with 1 tenant — making the platform demonstrably better for everyone as it scales.

### 1.4 Network Behavior Coverage

#### Accessibility

**How easily can the admin complete operational transactions?**

- Tenant provisioning: one wizard form, automated resource creation, < 10 minutes
- LLM profile creation: slot-by-slot model selection, test before publish
- Template authoring: structured form with {{variable}} placeholders, built-in testing
- Tool registration: standardized form, automated health checking
- Issue review: single queue view with pre-classified items and one-click actions
- Cost monitoring: auto-calculated from usage telemetry + cloud billing API

**Assessment**: HIGH. Core operations achievable with minimal friction. Most frequent actions (review issue queue, check tenant health, monitor costs) are passive — the system surfaces them; admin acts.

#### Engagement

**What information helps the admin complete operations effectively?**

- Daily alert digest: at-risk tenants, approaching quotas, SLA-at-risk issues, tool health degradations
- LLM profile performance: satisfaction rate per profile, latency, cost per query
- Template analytics: satisfaction, guardrail triggers, failure patterns by template
- Margin dashboard: running gross margin per tenant vs plan revenue
- Roadmap signal board: top feature requests, feature adoption gaps, satisfaction by area

**Assessment**: HIGH. Admin has multiple engagement surfaces — all action-oriented. Every metric connects to a decision.

#### Personalization

**Is the admin experience tailored to their specific platform state?**

- Dashboard prioritizes alerts by urgency (P0/P1 issues first, at-risk tenants, quota warnings)
- Tenant table sorted by health score (worst-performing surfaces to top)
- Cost view defaults to current billing period with comparison to prior period
- Template analytics defaults to lowest-satisfaction templates first
- Alert thresholds configurable per admin's priorities

**Assessment**: MEDIUM-HIGH. Personalization is alert-driven rather than preference-driven. Opportunity to improve: admin "focus mode" that hides areas that are healthy and surfaces only items requiring attention.

#### Connection

**What data flows connect to the platform?**

- LLM providers: API calls tracked per slot per tenant (bidirectional: invoke + track cost)
- Cloud billing APIs: Azure Cost Management + AWS Cost Explorer (pull actual cost data)
- GitHub: issue creation (push), PR/release webhooks (pull for status updates)
- Stripe: plan management + invoice generation (bidirectional)
- MCP tool servers: health monitoring (pull), invocation routing (push)
- End-user satisfaction signals: thumbs up/down on AI responses (internal, real-time)

**Assessment**: HIGH. Multiple external connections, bidirectional where it matters (billing, GitHub). Cloud billing integration surfaces real cost data rather than estimates.

#### Collaboration

**Can admins and tenants work together through the platform?**

- Issue queue: admin routes tenant issues to GitHub or back to tenant support
- Template library: admin publishes improvements, tenant admin controls when to upgrade their instances
- Tool catalog: admin classifies and publishes, tenant admin enables per-agent
- Quota management: admin can pre-emptively adjust quota based on tenant growth signal
- LLM profile recommendations: admin can push "we recommend upgrading to Balanced" notification to tenants on Cost-Optimized

**Assessment**: MEDIUM. Collaboration is largely admin-initiated. Tenant-admin-initiated collaboration is thin — tenants request quota increases, report issues, select profiles, but cannot propose template changes or request new tools. This is by design (governance) but limits collaboration richness.

---

## 2. AAA Framework

### 2.1 Automate — Reduce Operational Costs

| Manual Process Today                                              | Automated Replacement                                                           | Cost Saved                      |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------- | ------------------------------- |
| Manually provision cloud resources for each new tenant            | Automated provisioning workflow (Cosmos DB, Blob, AI Search, Redis, PostgreSQL) | 1-3 days → < 10 minutes         |
| Read token usage from Azure portal, attribute to tenants manually | Automatic token attribution pipeline with per-tenant aggregation                | 2-4 hours/month → 0             |
| Monitor each tenant's usage manually to detect approaching quota  | Automated quota monitoring with threshold alerts                                | Daily manual review → automated |
| Send status update emails to issue reporters                      | Automated via GitHub webhooks + notification system                             | 5-10 min/issue → 0              |
| Check which tenants are at churn risk by reviewing CRM notes      | Automated health score with at-risk signal                                      | Weekly analysis → real-time     |
| Set up LLM configuration for each new tenant individually         | LLM profile assignment at onboarding (single selection)                         | 2-4 hours/tenant → < 2 minutes  |
| Test each tool integration before giving tenants access           | Automated tool testing + health monitoring                                      | Ad-hoc testing → systematic     |

**Automation score**: 9/10 — operational work in this domain is highly structured and repetitive. Almost every task can be automated or made zero-effort through data collection.

### 2.2 Augment — Reduce Decision-Making Costs

| Decision                                                         | Without Console                     | With Console                                                                                        | Quality Improvement                         |
| ---------------------------------------------------------------- | ----------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| "Should I upgrade this tenant's quota?"                          | Guess based on sales conversation   | See: current consumption vs quota, growth trend, satisfaction score, expected month-end token count | Data-driven, not relationship-driven        |
| "Which LLM profile should I recommend to this tenant?"           | Manual assessment of their use case | See: tenant's query patterns, document types, satisfaction on current profile, cost comparison      | Matched recommendation                      |
| "Which agent template is underperforming and needs improvement?" | Unknown until tenants complain      | Template analytics: satisfaction rate, guardrail trigger rate, failure patterns                     | Proactive, not reactive                     |
| "Is this reported issue a platform bug or tenant config issue?"  | Manual investigation per case       | See: cross-tenant occurrence count, AI triage result, session context                               | 80%+ correctly routed without investigation |
| "Is my platform profitable at current pricing?"                  | Spreadsheet from memory             | Real-time gross margin per tenant, platform P&L                                                     | Accurate, current, no manual calculation    |
| "Which features should we build next quarter?"                   | Based on loudest customer voices    | Ranked feature requests from issue reports, filtered by plan tier and tenure                        | Systematic, not anecdotal                   |

**Augmentation score**: 9/10 — every major operational decision has corresponding data that the console surfaces. Decisions shift from judgment-under-uncertainty to judgment-with-data.

### 2.3 Amplify — Reduce Expertise Costs for Scaling

| Scaling Challenge                                             | Without Console                              | With Console                                                                                                             |
| ------------------------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| New operations hire needs 3 months to understand the platform | No structured operational knowledge base     | LLM profile notes encode best practices; template analytics encode what works; alert thresholds encode acceptable ranges |
| 50 tenants × 5 templates = 250 agent instances to manage      | Per-instance management required             | Template update → all 250 instances updated. 250-instance management at 1-instance cost.                                 |
| LLM model upgrade affects all tenants                         | Must contact each tenant, update each config | Update 1 LLM profile → all tenants on that profile get new model.                                                        |
| Churn risk requires dedicated account management at scale     | 1 account manager per 10-15 tenants          | Automated health scoring → 1 admin can manage 100+ tenants with targeted intervention only                               |
| New tool provider wants distribution to enterprise tenants    | Manual evaluation + per-tenant enablement    | Register in catalog → immediately available to all tenants (they opt-in per agent)                                       |

**Amplification score**: 10/10 — this is where the platform model generates the most value. The admin's one-time configuration actions scale to N tenants simultaneously. Every improvement the admin makes to a template, profile, or tool catalog compounds across the entire tenant base.

---

## 3. Synthesis: Platform Readiness Assessment

| Dimension                             | Score      | Rationale                                                                            |
| ------------------------------------- | ---------- | ------------------------------------------------------------------------------------ |
| Producer-consumer transaction clarity | 9/10       | Three clear transactions with feedback loops                                         |
| Network effects                       | 8/10       | Cross-side (curation × tenants) and data NE (template intelligence) both strong      |
| AAA — Automate                        | 9/10       | Almost all operational work is automatable                                           |
| AAA — Augment                         | 9/10       | Every key decision has supporting data                                               |
| AAA — Amplify                         | 10/10      | 1 admin action × N tenants = N × value                                               |
| Network behaviors                     | 7/10       | High accessibility + engagement + connection; medium personalization + collaboration |
| **Overall**                           | **8.7/10** | Exceptionally strong platform fit — the admin console IS the operational moat        |

### Critical Observation

The AAA scores (9/9/10) are among the highest possible for any product. This is because platform administration is fundamentally about coordination across repeated, structured transactions. AI augments these transactions with data that no individual could accumulate manually (cross-tenant performance signals, real-time token economics). The result: a single platform admin can do the work of a 5-person operations team.

This makes the admin console the scalability backbone of the entire business model. Platforms that fail to build this capability hit an operational ceiling at 20-30 tenants. Platforms that do build it scale to 100+ with the same team size.

### Gaps to Address

**Gap 1: Collaboration is admin-initiated only**
Tenant admins have no way to propose template improvements, suggest new tools, or contribute to the LLM profile library. A structured tenant-to-platform feedback channel (beyond issue reports) would strengthen the collaboration dimension.

**Gap 2: Personalization lacks admin preference learning**
The admin console does not learn what a specific admin cares about most. An admin focused on margin should see cost metrics first; one focused on quality should see satisfaction metrics first. A preference-aware layout would improve daily operational efficiency.

**Gap 3: Template collaboration between tenants**
Tenants who heavily customize an agent template have no way to share their customization back to the platform admin for potential incorporation into the base template. This would accelerate the template intelligence flywheel.

---

## 4. Phase-Gated AAA Realization

> **Note**: The scores in §3 reflect steady-state capability (post-Phase D). Actual AAA realization is phase-gated. See `10-05-red-team-critique.md` for phase-by-phase AAA score trajectory (Phase A: ~5/10 → Phase D: 8.7/10). The gap between Phase A and steady-state is primarily driven by data volume requirements for health scoring and template intelligence — both of which require 15-25 active tenants before the cross-tenant signals are meaningful.
