# Platform Model and AAA Framework Flows

**Scope**: Platform economics, persona interactions, network effects, and automation analysis
**Date**: March 4, 2026

---

## Phase Mapping

| Flow | Flow Name                                      | Built in Phase | Notes                                                                        |
| ---- | ---------------------------------------------- | -------------- | ---------------------------------------------------------------------------- |
| 01   | Platform Model: Producers, Consumers, Partners | Phase 4-6      | Marketplace dynamics emerge as platform scales                               |
| 02   | AAA Framework Analysis                         | Phase 1-6      | Automation grows with each phase; augment/amplify from Phase 4+              |
| 03   | Network Effects Analysis                       | Phase 4-6      | Cross-tenant effects require multi-tenant scale                              |
| 04   | Platform Value Creation and Capture            | Phase 6        | Billing integration, revenue model active at GA                              |
| 05   | Competitive Moat Analysis                      | Phase 4-6      | Moat layers build across phases: data (P1), MCP ecosystem (P4), pricing (P6) |

---

## 1. Platform Model: Producers, Consumers, Partners

### Core Transaction

**"A knowledge seeker gets an accurate, cited answer from proprietary enterprise data."**

This is the atomic unit of value. Every feature, integration, and optimization exists to make this transaction faster, more accurate, and more trusted.

### Persona Map

```
                    +-------------------+
                    |   Platform Admin   |
                    |  (SaaS Operator)   |
                    +---------+---------+
                              |
                    provisions & monitors
                              |
            +----------------+----------------+
            |                                  |
   +--------v--------+              +---------v--------+
   |   PRODUCERS      |              |   CONSUMERS       |
   | (IT/Data Teams)  |              | (Knowledge Workers)|
   +--------+---------+              +---------+---------+
            |                                  |
     configure                           query & consume
     knowledge sources                   synthesized answers
            |                                  |
            +---------->  PLATFORM  <----------+
            |          (AI Hub Core)           |
            |               ^                  |
            |               |                  |
            +-----+---------+---------+--------+
                  |                   |
         +-------v--------+  +-------v--------+
         |   PARTNERS       |  |   PARTNERS       |
         | (Data Providers)  |  | (Infra Providers)|
         +------------------+  +------------------+
         Bloomberg, CapIQ,      Azure, Auth0,
         PitchBook, Oracle,     OpenAI, Anthropic,
         iLevel, Teamworks      Google, Deepseek
```

---

### Producers: IT / Data Teams

**Who**: Tenant administrators, index administrators, integration admins, sync admins.

**What they produce**: Configured, indexed, searchable enterprise knowledge.

**Value chain**:

```
Raw Enterprise Data
  |
  v
[Producer: Configure data source]
  |-- Register Azure AI Search index
  |-- Connect SharePoint library
  |-- Enable MCP server (Bloomberg, Oracle, etc.)
  |-- Upload and index documents
  |
  v
[Platform: Process and index]
  |-- Text extraction, chunking, embedding
  |-- Metadata enrichment (glossary, categories)
  |-- Access control tagging
  |
  v
Searchable Knowledge Asset
  |
  v
[Available to Consumers via RAG pipeline]
```

**Producer flows**:

| Flow                 | Steps                                              | Output                       |
| -------------------- | -------------------------------------------------- | ---------------------------- |
| Index registration   | Connect -> test -> map fields -> set RBAC          | Searchable index             |
| SharePoint sync      | Authorize -> select library -> schedule sync       | Auto-updated index           |
| MCP enablement       | Enable server -> configure access -> test          | Real-time data tool          |
| Glossary maintenance | Add terms -> associate with indexes                | Improved query understanding |
| Role configuration   | Create role -> assign index access -> assign users | Access-controlled knowledge  |

**Key metric**: Time from "raw data exists" to "users can query it" (target: <2 hours for new index, <5 minutes for SharePoint sync update).

---

### Consumers: Knowledge Workers

**Who**: Any employee authorized to use the platform -- analysts, managers, engineers, support staff.

**What they consume**: AI-synthesized answers with source attribution from enterprise data.

**Value chain**:

```
Information Need
  |
  v
[Consumer: Ask question]
  |-- Natural language query
  |-- Select indexes (optional)
  |-- Choose mode: standard / research
  |
  v
[Platform: RAG Pipeline]
  |-- Intent detection
  |-- Index routing
  |-- Multi-index search
  |-- Source ranking
  |-- LLM synthesis
  |
  v
Cited, Trustworthy Answer
  |
  v
[Consumer: Act on answer]
  |-- Make decision
  |-- Write report
  |-- Share with team
  |-- Provide feedback
```

**Consumer flows**:

| Flow                     | Input                 | Output                                 |
| ------------------------ | --------------------- | -------------------------------------- |
| Quick Q&A                | Simple question       | Direct answer with 1-2 citations       |
| Cross-domain research    | Complex question      | Synthesized analysis with multi-source |
| Personal document query  | Uploaded doc + query  | Answer from personal + enterprise data |
| Agent-assisted research  | Complex task          | Detailed report with iterative depth   |
| Internet-augmented query | KB-insufficient query | Answer blending enterprise + web data  |

**Key metric**: Queries answered satisfactorily per session (target: >85% thumbs-up rate).

---

### Partners: Data Providers and Infrastructure Providers

**Data Partners** (MCP server providers):

| Partner       | Data Type           | Integration     | Value to Platform          |
| ------------- | ------------------- | --------------- | -------------------------- |
| Bloomberg     | Financial markets   | MCP server      | Real-time market data      |
| CapIQ         | Credit intelligence | MCP server      | Company and deal analytics |
| PitchBook     | M&A intelligence    | MCP server      | Transaction and valuation  |
| Oracle Fusion | ERP data            | MCP server      | Operational data access    |
| iLevel        | Investment data     | MCP server      | Portfolio analytics        |
| AlphaGeo      | Geospatial          | MCP server      | Location intelligence      |
| Teamworks     | Project management  | MCP server      | Project and resource data  |
| Tavily        | Web search          | API integration | Internet fallback          |
| Perplexity    | Advanced web search | MCP server      | Deep web research          |

**Infrastructure Partners**:

| Partner   | Service             | Integration      | Value to Platform        |
| --------- | ------------------- | ---------------- | ------------------------ |
| Microsoft | Azure, AD, OneDrive | Core infra + SSO | Compute, auth, storage   |
| Auth0     | Identity federation | SSO broker       | Multi-provider auth      |
| OpenAI    | LLM (GPT-5.2-chat)  | API              | Primary synthesis engine |
| Anthropic | LLM (Claude)        | API (BYOLLM)     | Alternative synthesis    |
| Google    | LLM (Gemini)        | API              | Additional LLM choice    |
| Deepseek  | LLM                 | API (BYOLLM)     | Cost-effective option    |

**Partner value exchange**:

```
Partner provides data/service
  |
  v
Platform integrates via MCP / API
  |
  v
Consumers access through unified interface
  |
  v
Platform tracks usage -> Partner gets:
  |-- Usage metrics (API call volume)
  |-- Revenue (if paid integration)
  |-- Customer reach (distribution through platform)
```

---

## 2. AAA Framework Analysis

### Automate: Manual Steps Eliminated

For each persona, what manual work does the platform automate?

#### Consumer Automation

```
BEFORE (Manual)                          AFTER (Automated)
-----------------                        -----------------
Search SharePoint -> no results          Single query searches all sources
  |                                        |
Search file share -> partial answer        v
  |                                      Platform auto-routes to relevant indexes
Email colleague -> wait for response       |
  |                                        v
Check Bloomberg terminal manually        MCP tools called automatically
  |                                        |
Cross-reference multiple sources           v
  |                                      Synthesized answer with citations
Write summary for manager
  |                                      Time: 30 seconds vs 2 hours
  v
2+ hours per research task
```

**Automated steps**:

| Manual Step                         | Automated By                      | Time Saved       |
| ----------------------------------- | --------------------------------- | ---------------- |
| Identify correct data source        | Intent detection + index routing  | 5-15 min/query   |
| Search each source individually     | Multi-index parallel search       | 10-30 min/query  |
| Switch to Bloomberg/Oracle terminal | MCP tool invocation               | 5-10 min/query   |
| Cross-reference and deduplicate     | RAG re-ranking + deduplication    | 15-30 min/query  |
| Synthesize findings into answer     | LLM synthesis with citations      | 20-60 min/query  |
| Translate between languages         | Auto-detect + respond in language | 5-15 min/query   |
| File and organize research          | Conversation history + search     | 5-10 min/session |

#### Producer Automation

| Manual Step                        | Automated By                     | Time Saved  |
| ---------------------------------- | -------------------------------- | ----------- |
| Extract text from documents        | Document processing pipeline     | Hours/batch |
| Create search indexes manually     | Auto-indexing with embedding gen | Days/index  |
| Update indexes on document change  | SharePoint sync workers          | Continuous  |
| Manage user permissions per system | Unified RBAC with SSO group sync | Hours/week  |
| Monitor system health individually | Centralized analytics dashboard  | Hours/week  |
| Generate usage reports             | Automated cost analytics         | Hours/month |

#### Platform Admin Automation

| Manual Step                        | Automated By                       | Time Saved      |
| ---------------------------------- | ---------------------------------- | --------------- |
| Provision tenant infrastructure    | Tenant provisioning wizard         | Days -> minutes |
| Configure LLM endpoints per tenant | Platform-level provider management | Hours/tenant    |
| Monitor tenant health individually | Cross-tenant health dashboard      | Hours/day       |
| Calculate billing manually         | Automated usage tracking + billing | Days/month      |
| Rotate API keys across tenants     | Centralized credential vault       | Hours/rotation  |

---

### Augment: Decisions Aided

The platform does not replace human judgment. It augments it.

#### Consumer Augmentation

```
Decision: "Which source should I trust?"
  |
  v
Platform augments with:
  |-- Source quality scores (recency, authority, relevance)
  |-- Confidence indicators (high / medium / low)
  |-- Contradiction detection ("Source A and B disagree on...")
  |-- Gap identification ("No data found for Q4 projections")
  |
  v
Human decides: which source to prioritize, what action to take

Decision: "Is this answer complete?"
  |
  v
Platform augments with:
  |-- Citation list (see all sources used)
  |-- "Based on N sources from M indexes"
  |-- Research mode: exhaustive search with completeness assessment
  |-- Internet fallback: "Additional context from web sources"
  |
  v
Human decides: sufficient for my purpose, or need to dig deeper

Decision: "Who in the organization knows about this?"
  |
  v
Platform augments with:
  |-- Azure AD MCP: org chart, team membership
  |-- Expert identification from document authorship
  |-- Escalation path suggestion
  |
  v
Human decides: contact the expert or proceed with available info
```

#### Producer Augmentation

```
Decision: "Which indexes should this role access?"
  |
  v
Platform augments with:
  |-- Query analytics: which indexes does this department use most?
  |-- Content gap reports: what queries go unanswered?
  |-- Usage patterns: which roles access which indexes?
  |
  v
Admin decides: optimal role-to-index mapping

Decision: "Is our knowledge base adequate?"
  |
  v
Platform augments with:
  |-- Unanswered query log (85 queries about "remote work policy" with no results)
  |-- Low-confidence response patterns
  |-- Feedback analytics (thumbs-down trends by topic)
  |
  v
Admin decides: create new content, add new data source, or accept gap
```

---

### Amplify: Expertise Democratized

```
BEFORE: Expertise concentrated            AFTER: Expertise distributed
------------------------------            ----------------------------

[Analyst with Bloomberg access]           [Any employee with AI Hub access]
  knows market data                         asks: "What's Apple's P/E ratio?"
                                            -> Bloomberg MCP returns data
[HR specialist]                             -> LLM contextualizes
  knows policies                            -> Employee gets analyst-grade answer

[Finance controller]                      [Any manager]
  knows budget details                      asks: "What's Q3 budget status?"
                                            -> Finance index searched
[IT admin]                                  -> Oracle Fusion MCP queried
  knows system access                       -> Manager gets controller-grade view

[Senior researcher]                       [Junior employee]
  knows how to cross-reference              asks complex research question
  multiple databases                        -> Research agent runs multi-index search
                                            -> Delivers senior-researcher-grade synthesis
```

**Amplification by persona**:

| Expertise Previously Held By | Now Available To         | Through                           |
| ---------------------------- | ------------------------ | --------------------------------- |
| Financial analysts           | All authorized employees | Bloomberg + CapIQ MCP integration |
| HR specialists               | All employees            | HR knowledge base + RAG           |
| IT administrators            | Managers (self-service)  | Admin dashboard + analytics       |
| Research analysts            | All knowledge workers    | Research mode + agent delegation  |
| Cross-domain experts         | Anyone in organization   | Multi-index search + synthesis    |
| Legal/compliance team        | Managers                 | Legal knowledge base + citations  |

---

## 3. Network Effects Analysis

### Platform Network Effects

```
More Tenants
  |
  +-> More revenue -> More R&D investment -> Better platform
  |
  +-> Shared MCP server costs spread across tenants -> Lower per-tenant cost
  |
  +-> More usage data (anonymized) -> Better index routing algorithms
  |
  +-> Platform becomes industry standard -> Easier vendor approval for new tenants
```

### MCP Provider Network Effects

```
More MCP Providers on Platform
  |
  +-> More data sources per tenant -> More value per query
  |
  +-> Each new MCP server benefits ALL tenants on eligible plans
  |
  +-> Platform becomes distribution channel -> Attracts more MCP providers
  |
  +-> Indirect network effect: MCP providers compete on quality
```

### Within-Tenant Network Effects

```
More Users Within Tenant
  |
  +-> More queries -> Better understanding of knowledge gaps
  |
  +-> More feedback -> Improved response quality
  |
  +-> More document uploads -> Richer personal knowledge base
  |
  +-> More diverse query patterns -> Better index routing
  |
  +-> Institutional knowledge captured -> Less knowledge loss on turnover
```

---

### Network Effect Criteria Assessment

#### Accessibility

| Criterion             | Current State (Single-Tenant)     | Gap in Multi-Tenant               | Target State                              |
| --------------------- | --------------------------------- | --------------------------------- | ----------------------------------------- |
| User onboarding       | Manual setup by IT admin          | Need self-service, multi-IdP      | SSO auto-provision, <5 min to first query |
| Data source access    | Pre-configured by admin           | Need per-tenant isolation         | Tenant admin self-service, marketplace    |
| Platform availability | Single deployment, manual scaling | Need multi-region, per-tenant SLA | 99.9% (Pro) / 99.99% (Enterprise)         |
| Mobile access         | Desktop web only                  | Need responsive/mobile            | Progressive web app                       |
| API access            | Internal API only                 | Need tenant-scoped external API   | REST API with tenant API keys             |

#### Engagement

| Criterion        | Current State                    | Gap                               | Target State                       |
| ---------------- | -------------------------------- | --------------------------------- | ---------------------------------- |
| Query frequency  | 50-100 queries/user/month        | Need engagement loops             | 150+ queries/user/month            |
| Feature adoption | Chat only for most users         | Research, upload, agent underused | 40%+ users using advanced features |
| Feedback rate    | ~10% of responses get feedback   | Low feedback hurts improvement    | 30%+ feedback rate                 |
| Return visits    | Daily active: 60% of total users | Need sticky features              | 80%+ DAU/MAU ratio                 |
| Session depth    | 2-3 queries per session          | Shallow engagement                | 5+ queries per session             |

#### Personalization

| Criterion             | Current State                   | Gap                                | Target State                           |
| --------------------- | ------------------------------- | ---------------------------------- | -------------------------------------- |
| User profiling        | Basic department/role context   | Need learning from query patterns  | Personalized index ranking per user    |
| Response style        | Uniform for all users           | Need adaptation to seniority/role  | Adjust depth/detail by user preference |
| Index prioritization  | Manual selection or LLM routing | Need user-specific routing weights | Learn preferred indexes per user       |
| Proactive suggestions | None                            | Need "you might want to know"      | Content recommendations based on role  |
| Language preference   | Auto-detect per query           | Need persistent preference         | Remember language + formality level    |

#### Connection

| Criterion             | Current State                 | Gap                                  | Target State                          |
| --------------------- | ----------------------------- | ------------------------------------ | ------------------------------------- |
| Conversation sharing  | Basic link sharing            | Need team collaboration on research  | Shared workspaces, collaborative chat |
| Expert identification | Azure AD org chart only       | Need content-aware expert suggestion | "Ask {expert} who authored this doc"  |
| Team knowledge        | Individual conversations only | No shared team insights              | Team knowledge feeds                  |
| Cross-team insights   | None                          | Silos persist within tenant          | Cross-team query pattern visibility   |

#### Collaboration

| Criterion             | Current State             | Gap                                 | Target State                                  |
| --------------------- | ------------------------- | ----------------------------------- | --------------------------------------------- |
| Shared research       | Export and email manually | Need real-time collaboration        | Shared research sessions                      |
| Knowledge curation    | Admin-driven only         | Need user-contributed refinements   | Community glossary, verified answers          |
| Feedback loops        | Thumbs up/down only       | Need structured correction workflow | User corrections -> admin review -> KB update |
| Cross-tenant learning | N/A (single tenant)       | Privacy-safe cross-tenant insights  | Anonymized query pattern sharing (opt-in)     |

---

## 4. Platform Model: Value Creation and Capture

### Value Creation Flow

```
[Producers configure knowledge sources]
  |
  v
[Platform indexes, embeds, and makes searchable]
  |
  v
[Consumers query and receive synthesized answers]
  |
  v
[Feedback loops improve quality]
  |
  +-> Content gaps identified -> Producers add content
  +-> Query patterns analyzed -> Routing improved
  +-> User preferences learned -> Personalization enhanced
  +-> MCP usage tracked -> Partner value demonstrated
```

### Value Capture (Revenue Model)

```
Tenant pays subscription
  |
  +-> Per-user/month fee (primary revenue)
  |     |-- Starter: $15/user
  |     |-- Professional: $25/user
  |     |-- Enterprise: custom
  |
  +-> Usage-based overage (secondary revenue)
  |     |-- LLM tokens above plan budget
  |     |-- Storage above plan allocation
  |     |-- MCP calls above plan limits
  |
  +-> Platform captures margin between:
        |-- Revenue: subscription + overage fees
        |-- Cost: LLM API calls + search infra + MCP fees + storage
        |-- Target gross margin: 60-70%
```

### Flywheel Effect

```
Better Platform (more MCP servers, better RAG, faster responses)
  |
  +-> More Tenants adopt
  |     |
  |     +-> More Revenue
  |     |     |
  |     |     +-> More R&D Investment
  |     |           |
  |     |           +-> Better Platform (cycle repeats)
  |     |
  |     +-> More Usage Data (anonymized)
  |           |
  |           +-> Better Index Routing
  |           |
  |           +-> Better Intent Detection
  |           |
  |           +-> Better Platform (cycle repeats)
  |
  +-> More MCP Providers want distribution
        |
        +-> More Data Sources Available
        |
        +-> More Value Per Tenant
        |
        +-> Better Platform (cycle repeats)
```

---

## 5. Competitive Moat Analysis

### Moat Layers

```
Layer 1: Data Network Effects
  Enterprise data stays in platform -> queries improve routing
  -> more accurate answers -> more usage -> stronger data advantage

Layer 2: MCP Ecosystem
  9 MCP servers today -> platform becomes distribution hub
  -> MCP providers prefer platform listing -> more servers
  -> harder for competitors to replicate ecosystem

Layer 3: Switching Costs
  SSO configured + roles set up + indexes registered + history accumulated
  -> migration cost increases with usage duration
  -> estimated switching cost: 3-6 months of productivity loss

Layer 4: Pricing Below Copilot
  $25/user vs Copilot $30/user with MORE data source flexibility
  -> price competition advantage
  -> value competition advantage (MCP servers Copilot doesn't have)
```

---

## Summary

| Dimension       | Current                   | Multi-Tenant Target              | Moat Contribution    |
| --------------- | ------------------------- | -------------------------------- | -------------------- |
| Producers       | IT admins (single org)    | Per-tenant IT teams              | Configuration depth  |
| Consumers       | <50 concurrent            | 1000s across tenants             | Usage data           |
| Partners        | 9 MCP servers             | 20+ MCP marketplace              | Ecosystem lock-in    |
| Automate        | Search + synthesis        | + provisioning, billing, scaling | Operational leverage |
| Augment         | Source scoring, citations | + personalization, team insights | Decision quality     |
| Amplify         | Expert knowledge to all   | Cross-tenant best practices      | Expertise reach      |
| Network Effects | Within-tenant only        | Cross-tenant + ecosystem         | Compounding value    |

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
