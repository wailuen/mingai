# mingai — Executive Summary

> **Document Status**: Post-Analysis Summary (supersedes initial architecture snapshot of 2026-03-04)
> **Date**: 2026-03-05
> **Scope**: Consolidates findings from the full analysis corpus (docs 01–28) into a single reference document
> **Audience**: Product owners, engineering leads, stakeholders

---

## 1. What We Are Building

**mingai** is an enterprise multi-tenant SaaS platform that provides a single AI-powered conversational interface to all of an organization's knowledge — internal documents, enterprise systems, financial terminals, ERP data, and internet sources — with the access controls, compliance boundaries, and data sovereignty guarantees that regulated enterprises require.

**Current state**: Single-tenant MVP deployed on Azure OpenAI with functional RAG, RBAC, SharePoint sync, and 9 A2A agent integrations. PostgreSQL migration underway as Phase 1 of the multi-tenant conversion.

**Target state (after 6 phases, ~30 weeks)**: A fully multi-tenant SaaS platform with per-tenant LLM provider selection, cloud-agnostic deployment (AWS/Azure/GCP), enterprise A2A multi-agent orchestration, marketplace-extensible agent catalog, and GA self-service onboarding.

---

## 2. Architecture Decisions Made

The analysis phase produced the following binding architecture decisions. These supersede any earlier references to Cosmos DB, Azure-only infrastructure, or single-IdP authentication.

| Decision                   | Choice Made                                                                                | Rationale                                                                     |
| -------------------------- | ------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| **Database**               | PostgreSQL (RDS Aurora) with Row-Level Security                                            | Partition key constraint eliminated; RLS is first-class; cloud-portable       |
| **Multi-tenant isolation** | `tenant_id` column + RLS on all 21 tables                                                  | Additive migration, no container recreation, engine-enforced                  |
| **Auth strategy**          | Pluggable IdP: direct Entra ID, Google, Okta, SAML; Auth0 optional for managed SSO         | No mandatory Auth0 dependency; direct IdP supported at Professional+          |
| **LLM abstraction**        | `LLMProvider` interface with per-provider adapters                                         | 7 providers at Phase 4 GA; BYOLLM for Enterprise                              |
| **Agent architecture**     | Kaizen multi-agent + Google A2A v0.3; `AgentDispatcher` abstraction                        | Wire protocol isolated from orchestrator internals                            |
| **Cloud agnostic**         | `CLOUD_PROVIDER` env drives adapter selection; no cloud-specific imports in app code       | Phase 1 on AWS; Azure + GCP certified in Phase 5                              |
| **Caching**                | Semantic cache with tenant namespace isolation; 35–50% hit rate target                     | Context window budget + margin protection                                     |
| **BYOMCP sandboxing**      | Cilium FQDN egress policy + resource quotas + runtime monitoring + platform admin approval | Defense-in-depth; enterprise extensibility without shared-infrastructure risk |
| **Marketplace consent**    | Three-level consent (platform verification → tenant policy → per-query user disclosure)    | GDPR/MiFID II/SOX compliant; Enterprise-tier only                             |

---

## 3. Product Focus: 80/15/5 Framework

### 80% — Platform-Managed (Every Tenant Gets This)

The core platform provides enterprise-grade capability that requires no per-tenant configuration:

- Multi-tenant PostgreSQL with RLS-enforced data isolation
- JWT v2 with `tenant_id`, `scope`, and `plan` claims
- Platform LLM Library with approved providers per plan tier
- RAG pipeline: intent detection → index routing → hybrid search → synthesis → source attribution
- A2A agent orchestration: DAG planner, parallel dispatch, partial failure policy, synthesis context management
- Three-layer guardrail enforcement on all A2A agent responses
- Per-agent extraction schemas for all 9 agents (Bloomberg, CapIQ, Oracle Fusion, Perplexity, Azure AD, iLevel, PitchBook, AlphaGeo, Teamworks)
- OpenTelemetry distributed tracing and DAG replay infrastructure
- Platform RBAC (platform_admin, platform_operator, platform_support, platform_security)
- Billing, usage tracking, and SLA monitoring

### 15% — Tenant-Configurable (Self-Service)

Tenant admins configure the platform to their organizational requirements without engineering:

- SSO provider selection (Entra ID, Google, Okta, SAML) within platform-enabled options
- LLM selection from Platform Library, or BYOLLM API key entry (Enterprise only)
- A2A agent enablement and credential entry per agent
- Prompt extension per agent instance (audited at registration time)
- Knowledge base connections (SharePoint, Google Drive, document upload)
- Glossary management (terms, definitions, CSV import/export)
- Role customization (permission bundles, index access assignments)
- Consent policy per marketplace agent (always allow / notify / always prompt)
- DAG run retention tier selection per plan

### 5% — Custom Extension (Enterprise Engineering)

Enterprise tenants invest in custom integrations that create platform lock-in:

- Custom MCP server (BYOMCP) development for proprietary internal data sources
- Custom extraction schema contribution (if BYOMCP returns non-standard artifact shapes)
- Industry-specific compliance extension (additional guardrail rules submitted to platform)

---

## 4. Platform Model Analysis

| Role          | Who                                                                                                    | Transaction                                                  | Platform Value Created                                                          |
| ------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| **Producers** | Enterprise knowledge workers, analysts, document owners; A2A data providers (Bloomberg, Reuters, etc.) | Contribute queries, documents, knowledge; provide data feeds | Platform aggregates dispersed knowledge into a unified retrievable corpus       |
| **Consumers** | Knowledge workers seeking answers; managers needing synthesis across systems                           | Natural-language queries, research requests                  | Receive synthesized multi-source answers with RBAC-enforced access              |
| **Partners**  | Bloomberg, CapIQ, Oracle, PitchBook, AlphaGeo, Teamworks, iLevel, Azure AD, Perplexity                 | Provide specialized data via A2A agents                      | Access enterprise buyers who already trust the platform; DPA-covered data flows |

**Transaction enabled**: An analyst issues one natural-language query; the platform orchestrates 3–9 agents across proprietary financial, ERP, and web sources; delivers a synthesized, cited, compliance-filtered answer in <10 seconds — replacing a process that previously took 30–60 minutes of manual research across disconnected systems.

**Network effects that strengthen the platform over time**:

- More agents enrolled → richer responses → more user queries → more usage data → better intent model routing
- More tenants → larger violation pattern corpus → better guardrail calibration → lower false-positive rates → safer for all tenants
- More BYOMCP registrations from enterprise tenants → marketplace receives more publisher submissions → marketplace grows → more agents available → higher tenant retention

---

## 5. AAA Framework Evaluation

### Automate — Reduce Operational Costs

| Capability                                    | Automation Delivered                                                                                                          |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| A2A DAG execution                             | 3–9 parallel agent calls orchestrated automatically; no human coordination                                                    |
| Guardrail enforcement (Layer 2 output filter) | Every agent response validated at infrastructure level; zero compliance team review for routine queries                       |
| Three-layer prompt injection defense          | Registration-time audit, positional guardrail ordering, output filter — all automated                                         |
| Tenant provisioning workflow                  | New tenant database records, Redis namespace, search indexes, default admin: all created in <30s with zero human intervention |
| Semantic cache                                | 35–50% of queries answered from cache; LLM calls eliminated automatically                                                     |
| SharePoint / Google Drive sync                | Incremental delta sync, change detection, index update — fully background                                                     |
| DAG failure recovery                          | Partial failure policy executes automatically: retry, proceed with disclosure, or block — per pre-defined rules               |

### Augment — Reduce Decision-Making Costs

| Capability                                     | Augmentation Delivered                                                                                                           |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Multi-source synthesis with source attribution | Analyst sees synthesized answer + contributing sources + confidence — makes better decisions than with raw data                  |
| DAG replay and artifact inspection             | Tenant admin sees exactly which agent contributed which data to each answer — diagnoses quality issues without platform support  |
| Guardrail violation audit trail                | Compliance team sees every filter event with rule ID, action, and masked content — makes informed regulatory reporting decisions |
| Cost dashboard with per-tenant budget tracking | Platform admin and tenant admin make informed LLM budget decisions with real-time usage data                                     |
| Intent detection confidence scoring            | Planner fast-path routes high-confidence single-agent queries immediately — users get fast answers for obvious queries           |

### Amplify — Reduce Expertise Costs for Scaling

| Capability                | Expertise Amplification                                                                                                           |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Platform LLM Library      | Platform admin configures approved providers once; all tenants benefit with zero per-tenant LLM engineering                       |
| Agent template system     | Bloomberg/CapIQ/Oracle agents built once by platform team; deployed to any tenant with just their credentials — no re-engineering |
| Extraction schema library | 9 per-agent extraction schemas defined once; every multi-agent query benefits — no per-tenant context engineering                 |
| Glossary RAG integration  | Domain expert defines terminology once in glossary; query enrichment and prompt injection happen automatically for all users      |
| Platform RBAC             | Platform admin defines role model once; all tenants inherit the permission framework                                              |

---

## 6. Network Effects Coverage

| Behavior            | How Platform Achieves It                                                                                                                                                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Accessibility**   | Single natural-language interface to all authorized data; SSO login; mobile-responsive; fast-path reduces P50 latency to ~1s for single-agent queries                                                                          |
| **Engagement**      | Synthesized multi-source answers (not raw documents); source attribution with confidence scores; streaming responses; partial failure disclosure keeps users informed rather than confused                                     |
| **Personalization** | Per-tenant LLM selection; tenant glossary injected into all queries; agent roster configured per tenant; user conversation history maintained for context continuity                                                           |
| **Connection**      | 9 A2A agents connect to financial terminals, ERP systems, web search, org directories, portfolio analytics; BYOMCP enables connection to any proprietary system; SharePoint and Google Drive sync workers keep indexes current |
| **Collaboration**   | DAG run export for sharing with data vendors and compliance teams; tenant admin can re-run a specific DAG and compare results; analyst can share a conversation thread with guardrail violation context attached               |

---

## 7. Value Propositions & Unique Selling Points

### Value Propositions (What the platform delivers)

1. **Unified knowledge access** — One conversational interface spanning enterprise documents, financial terminals, ERP systems, web search, and proprietary internal data
2. **Compliance-safe AI** — Infrastructure-level guardrail enforcement (output filter layer) ensures no agent response violates regulatory constraints, regardless of LLM behavior or tenant customization
3. **Cost-predictable AI** — Per-tenant hard budget limits, circuit breakers, and real-time cost dashboards prevent agentic RAG cost overruns (the #1 enterprise AI deployment risk)
4. **RBAC that matches enterprise permission models** — 9 system functions, custom role bundling, index-level access control, platform roles separate from tenant roles

### Genuine USPs (Verifiably differentiated from competitors)

See full analysis in `02-product/04-unique-selling-points.md`. Summary:

| USP                                                              | Why it is genuinely unique                                                                                                                                                                                                                                           |
| ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Platform-guaranteed compliance boundaries**                    | Infrastructure-level output filter enforces guardrails regardless of LLM version changes or tenant prompt customization. No competing enterprise RAG platform offers this. Competitors rely on prompt-only constraints.                                              |
| **Cloud-agnostic deployment with full pipeline control**         | `CLOUD_PROVIDER=aws\|azure\|gcp\|self-hosted` with no cloud-specific imports in application code. Copilot is Azure-locked; Glean is cloud-opaque. Full pipeline control — search parameters, prompt engineering, context window — is a black-box competitor blocker. |
| **Open MCP standard for custom data integration**                | Enterprises build BYOMCP servers connecting proprietary data to platform orchestration. No competitor offers an open standard integration surface with enterprise-grade sandboxing (network isolation, capability audit, runtime monitoring).                        |
| **Multi-agent DAG with per-agent extraction context management** | 9 specialized agents in parallel DAG execution with context window engineering built-in. Synthesis context budget prevents the silent truncation failure that plagues naive multi-agent implementations.                                                             |
| **Synthesis context extraction pipeline**                        | Raw financial API artifacts (50K tokens raw) compressed to 8K structured synthesis context per run. This is what makes 5-agent Bloomberg + CapIQ + Oracle queries reliable, not aspirational.                                                                        |

### What Does Not Differentiate (Table Stakes)

AI-powered chat, enterprise SSO, source attribution, conversation history, multi-language support, feedback, analytics. Every competitor has these. See `02-product/04-unique-selling-points.md` for the full table.

---

## 8. PMF Assessment

**Score**: 3.2/5 (up from 2.7/5 post-initial-red-team)

**Strongest dimensions**: Technical differentiation (4.5/5), RBAC depth (4/5), data source connectivity (4/5)

**Weakest dimensions**: WTP validation (2/5 — design partners required), GTM readiness (1.5/5 — Phase 6 deliverable)

**Target segment for Phase 1 design partners**: Financial services, 50–2,000 employees. Pain point is acute (Bloomberg/Oracle fragmentation), budget exists, A2A differentiators are directly relevant, RBAC + audit trail are compliance requirements.

**Pricing**: Starter $15/user/month (max 25 users), Professional $25/user/month (max 500 users), Enterprise custom. Professional gross margin at 2K tokens/query: ~54%. Semantic cache at 40% hit rate target: ~69% GM.

See full analysis: `02-product/05-pmf-assessment.md`, `08-red-team-v2/01-remediation-plan.md` §6 (cost model), §9 (GTM strategy).

---

## 9. Full Analysis Corpus Index

All research documents are in `01-analysis/01-research/`. Cross-reference by topic:

### Architecture Analysis (Current State)

| Doc | Title                     | Key Output                                                 |
| --- | ------------------------- | ---------------------------------------------------------- |
| 01  | Service Architecture      | FastAPI modules, port map, service boundaries              |
| 02  | Data Models               | 21 PostgreSQL tables, Alembic migration plan               |
| 03  | Auth & RBAC               | JWT v2 structure, 9 system functions, platform roles       |
| 04  | RAG Pipeline              | 4-stage pipeline, intent detection, hybrid search          |
| 05  | LLM Integration           | GPT-5.2-chat / GPT-5 Mini slots, token limits              |
| 06  | MCP Servers               | 9 A2A agents, internal vs. open MCP distinction            |
| 07  | Frontend Architecture     | Next.js 14, SSE streaming, TanStack Query                  |
| 08  | Current Tenant Model      | Single-tenant state, what breaks for multi-tenancy         |
| 09  | Deployment Infrastructure | Docker Compose, Azure services, health checks              |
| 10  | Kaizen Extension Analysis | Multi-agent upgrade path from current ResearchAgentHandler |
| 11  | Existing ADRs             | Architecture decisions recorded in codebase                |
| 12  | Database Architecture     | Full 21-table schema, RLS policy design                    |
| 13  | RAG Ingestion             | Chunking strategy, embedding pipeline, index management    |

### Caching System

| Doc | Title                         | Key Output                                       |
| --- | ----------------------------- | ------------------------------------------------ |
| 14  | Caching Architecture Overview | Redis + semantic cache architecture              |
| 15  | Semantic Caching Analysis     | Embedding similarity threshold, hit rate targets |
| 16  | Embedding Search Cache        | Vector cache index design                        |
| 17  | Multi-Tenant Cache Isolation  | `mingai:{tenant_id}:{key}` namespace migration   |

### A2A Agent Platform

| Doc    | Title                                | Key Output                                                                   |
| ------ | ------------------------------------ | ---------------------------------------------------------------------------- |
| 18     | A2A Agent Architecture               | 9-agent catalog, AgentCard spec, DAG planner design                          |
| 19     | SharePoint Sync Architecture         | Delta sync, change tracking, background worker                               |
| 20     | Document Upload Architecture         | OneDrive upload, personal index, private search                              |
| 21     | LLM Model Slot Analysis              | Verified model slots from `app/core/config.py`                               |
| 22     | Google Drive Sync Architecture       | OAuth2/Service Account, incremental sync, push notifications                 |
| 23     | Glossary Management Architecture     | CRUD API, CSV import, Redis cache, RAG integration                           |
| 24     | Platform RBAC Specification          | `platform_members` table, platform JWT, impersonation flow                   |
| **25** | **A2A Guardrail Enforcement**        | **Three-layer system: prompt position + output filter + registration audit** |
| **26** | **A2A Synthesis Context Management** | **9 extraction schemas; ExtractionService; multi-pass synthesis**            |
| **27** | **A2A Execution Hardening**          | **Partial failure policy; fast-path; OTel tracing; DAG replay UI**           |
| **28** | **A2A Extensibility Security**       | **BYOMCP sandboxing; marketplace consent model**                             |

**Docs 25–28 are P0/P1 architecture requirements for Phase 4 (Agentic Upgrade). None can be deferred.**

### Multi-Tenant Design Decisions

| Doc                | Title                     | Key Output                                                                  |
| ------------------ | ------------------------- | --------------------------------------------------------------------------- |
| 04-multi-tenant/01 | Admin Hierarchy           | Platform admin → Tenant admin → End user role hierarchy                     |
| 04-multi-tenant/02 | Data Isolation            | RLS policy design, Redis namespace, search index isolation                  |
| 04-multi-tenant/03 | Auth & SSO Strategy       | Pluggable IdP pattern, Auth0 as optional managed provider                   |
| 04-multi-tenant/04 | LLM Provider Management   | Library + BYOLLM model, per-tenant config cache                             |
| 04-multi-tenant/05 | Cloud-Agnostic Deployment | `CLOUD_PROVIDER` abstraction, Terraform IaC plan                            |
| 04-multi-tenant/06 | A2A & MCP Agentic         | Full A2A platform design (superseded by docs 25–28 for enforcement details) |

### Product Analysis

| Doc           | Title                 | Key Output                                                             |
| ------------- | --------------------- | ---------------------------------------------------------------------- |
| 02-product/01 | Product Vision        | Problem statement, personas, core value proposition                    |
| 02-product/02 | Competitive Analysis  | Copilot, Glean, Guru, Notion AI comparison                             |
| 02-product/03 | Value Propositions    | Unified access, compliance boundaries, cost predictability, RBAC depth |
| 02-product/04 | Unique Selling Points | Table stakes vs. genuine differentiators; moat analysis                |
| 02-product/05 | PMF Assessment        | Dimension scores, target segment, GTM foundation                       |
| 02-product/06 | Multi-Tenant Product  | Plan tiers, feature matrix, pricing model, go-to-market                |

### Red Team & Remediation

| Doc                    | Title            | Key Output                                                      |
| ---------------------- | ---------------- | --------------------------------------------------------------- |
| 05-red-team/01         | Phase 1 Critique | 10 critical gaps identified                                     |
| 07-red-team-caching/01 | Caching Critique | Cache invalidation risk, cost model accuracy                    |
| 08-red-team-v2/01      | Remediation Plan | All 10 gaps resolved; DR architecture; cost model; GTM strategy |

---

## 10. Implementation Roadmap Summary

| Phase                    | Weeks | Key Deliverable                                                                                                                                                            | Risk                               |
| ------------------------ | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| **1 — Foundation**       | 1–8   | tenant_id + RLS on all 21 tables, platform RBAC, glossary v1, response feedback                                                                                            | HIGH — touches every query path    |
| **2 — LLM Library**      | 9–12  | Platform LLM Library, Tenant LLM Setup, BYOLLM (Enterprise), cost tracking                                                                                                 | MEDIUM — cost modeling uncertainty |
| **3 — Auth Flexibility** | 13–15 | Pluggable IdP, Google Workspace, Okta, SAML; Auth0 optional managed SSO                                                                                                    | MEDIUM — token migration window    |
| **4 — Agentic Upgrade**  | 16–20 | Kaizen multi-agent, A2A protocol, guardrail enforcement, synthesis context management, DAG failure policy, fast-path, 5 new LLM providers, Google Drive sync, Glossary RAG | HIGH — docs 25–28 all P0/P1        |
| **5 — Cloud Agnostic**   | 21–24 | Azure + GCP certification, OTel tracing, DAG replay UI, CloudStorageConnector abstraction                                                                                  | MEDIUM — abstraction leakage risk  |
| **6 — GA**               | 25–27 | Billing, self-service onboarding, BYOMCP sandboxing, marketplace consent, DR runbooks, demo environment                                                                    | MEDIUM — enterprise security gates |

**Total: ~30 weeks (~7.5 months)**

Full roadmap: `02-plans/01-implementation-roadmap.md`

---

## 11. Key Technical Decisions Reference

| Aspect                       | Decision                                                                                                     | Rationale                                                           |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| **Database**                 | PostgreSQL (RDS Aurora) + Alembic                                                                            | Cloud-portable; RLS first-class; additive migration                 |
| **Tenant isolation**         | Row-Level Security (`SET app.tenant_id`)                                                                     | Engine-enforced; no application-layer bypass                        |
| **LLM routing**              | `use_case` param maps to tenant's intent-tier vs. synthesis-tier model                                       | Cost-conscious model tiering per call type                          |
| **A2A wire protocol**        | Google A2A v0.3 with `AgentDispatcher` abstraction                                                           | Wire protocol isolated; swap to v0.4+ without orchestrator changes  |
| **Extraction pipeline**      | Intent-tier LLM (10× cheaper) extracts synthesis context from raw artifacts                                  | 40–60% total cost saving on multi-agent queries                     |
| **Context window**           | Multi-pass synthesis triggered at 80% of context budget (token-based, not agent-count-based)                 | Prevents silent truncation; handles large-artifact agents correctly |
| **Guardrail enforcement**    | Three layers: positional prompt ordering + output filter + registration audit                                | Layer 2 (output filter) is the only hard enforcement layer          |
| **BYOMCP network isolation** | Cilium CiliumNetworkPolicy `toFQDNs` (not standard ipBlock)                                                  | Standard K8s ipBlock cannot perform DNS-aware FQDN filtering        |
| **Fast-path threshold**      | 0.92 intent confidence; empirical calibration required before production                                     | False positive rate target: ≤2%; per-tenant tuning is a v2 feature  |
| **DAG artifact storage**     | Extracted `SynthesisContext` stored (not raw artifacts); PII-scrubbed; no Bloomberg/CapIQ raw data persisted | Licensed data compliance; GDPR PII constraint                       |
| **Frontend**                 | Next.js 14, TanStack Query, SSE streaming                                                                    | SSR, optimistic updates, streaming response rendering               |
| **Secrets**                  | Azure Key Vault (Azure) / AWS Secrets Manager (AWS) — never in code or config files                          | CLAUDE.md directive; security review gate before every commit       |

---

## 12. Risk Register Summary

| Risk                                              | Phase | Likelihood | Impact   | Mitigation                                                                               |
| ------------------------------------------------- | ----- | ---------- | -------- | ---------------------------------------------------------------------------------------- |
| Agentic RAG costs blow budget                     | 4+    | HIGH       | HIGH     | Hard per-tenant token limits, circuit breakers, cost dashboard, 3–8× multiplier budgeted |
| RLS misconfiguration leaks data                   | 1     | MEDIUM     | CRITICAL | Extensive cross-tenant isolation tests; staging-first                                    |
| `semantic_check` guardrail uncalibrated at launch | 4     | MEDIUM     | HIGH     | Bloomberg agent blocked from production until 50-100 violation exemplars calibrated      |
| Fast-path routes to wrong agent                   | 4     | LOW        | MEDIUM   | ≤2% false positive target; production monitoring of fast-path quality scores             |
| BYOMCP capability spoofing                        | 6     | LOW        | HIGH     | Capability probe + Cilium network policy + runtime anomaly monitoring                    |
| Phase 5 abstraction leakage                       | 5     | MEDIUM     | MEDIUM   | Define interfaces from requirements, not AWS API shapes; test on all three clouds        |
| Cost model underestimates at 4K+ tokens/query     | All   | MEDIUM     | HIGH     | Hard context window budget; caching reduces average token count                          |

---

**Document Version**: 2.0
**Last Updated**: 2026-03-05
**Supersedes**: Initial architecture snapshot (`00-executive-summary.md` v1, 2026-03-04)
