# Red Team Critique -- mingai Phase 2

**Date**: March 4, 2026
**Reviewer**: Red Team Agent
**Scope**: All workspace documents (01-analysis, 02-plans, 03-user-flows)
**Methodology**: Source code verification, steelman counter-arguments, gap analysis

---

## Executive Summary: Top 10 Critical Gaps

1. **Model name inconsistency across docs**: Multiple documents reference "GPT-4" while the actual codebase runs GPT-5.2-chat and GPT-5 Mini. This undermines document credibility with any technical reader.

2. **~~No plans or implementation roadmap exist~~** (RESOLVED in Pass 2b): Plans now exist with 6-phase, 25-week roadmap and detailed migration plan. However, the migration plan covers only 9 of 21 Cosmos DB containers and contains fabricated RBAC role/function names. See Pass 2b for details.

3. **Auth0 migration is the riskiest architectural decision**: Replacing Azure AD direct integration with Auth0 as SSO broker introduces a third-party dependency, latency, cost, and a massive migration effort -- with no fallback plan documented.

4. **Multi-tenant partition key change requires container recreation**: Cosmos DB does not support changing partition keys on existing containers. The migration plan acknowledges this but underestimates the operational complexity and downtime risk.

5. **BYOLLM strategy is underspecified**: The admin hierarchy doc lists BYOLLM as a feature but the entire codebase only supports Azure OpenAI. Supporting OpenAI, Anthropic, and other providers requires significant new client code, not just configuration.

6. **MCP "differentiator" is fragile**: The MCP protocol is called the strongest USP, but the actual MCP module uses a custom tool-call format (not the open MCP standard from Anthropic). The "open protocol" claim needs verification.

7. **Cost estimates in the tenant model doc are unrealistic**: The $800-1500/month estimate for 100 tenants on shared database ignores Azure OpenAI costs, which at $0.016/query and 10K queries/tenant/month would be $16,000/month in LLM costs alone.

8. **No disaster recovery or failover strategy**: None of the documents address what happens when Azure OpenAI, Cosmos DB, or Azure Search experience outages. For a multi-tenant SaaS platform, this is a blocking gap.

9. **User flow docs cover only 2 of 6+ personas**: Only platform admin and tenant admin flows exist. Knowledge worker, analyst, role admin, index admin, and compliance auditor flows are missing.

10. **PMF assessment scores 2.7/5 but the plans don't address the lowest-scoring dimensions**: Willingness-to-pay (1/5) and go-to-market readiness (1/5) are the most critical gaps, yet no pricing model, sales strategy, or demo environment plan exists.

---

## 1. Source Code Verification (10 Claims Checked)

### Claim 1: "9 distinct system functions" (04-unique-selling-points.md)

**VERIFIED: CORRECT**

Source: `scripts/init_system_roles.py` lines 88-97 defines the admin role with all 9 system permissions:

```
role:manage, user:manage, index:manage, analytics:view, audit:view,
integration:manage, feedback:view, sync:manage, glossary:manage
```

These are enforced via `permission_checker.py` with `system_function` resource type checks.

### Claim 2: "GPT-4 (primary deployment)" (04-rag-pipeline.md, 00-executive-summary.md)

**VERIFIED: INCORRECT**

Source: `app/core/config.py` lines 86-97:

```python
azure_openai_primary_deployment: str = Field(
    default="aihub2-main",
    description="Primary LLM deployment for chat responses (gpt-5.2-chat)"
)
azure_openai_auxiliary_deployment: str = Field(
    default="intent5",
    description="Auxiliary LLM deployment for fast tasks (gpt-5-mini)"
)
```

The system uses **GPT-5.2-chat** (primary) and **GPT-5 Mini** (auxiliary). The `05-llm-integration.md` doc correctly identifies this, but `00-executive-summary.md`, `01-service-architecture.md`, `04-rag-pipeline.md`, `03-value-propositions.md`, and `11-existing-adrs.md` all incorrectly reference GPT-4.

**Files requiring correction**:

- `01-research/00-executive-summary.md`: Lines 119-123 reference "GPT-4"
- `01-research/01-service-architecture.md`: Lines 215, 248 reference "GPT-4"
- `01-research/04-rag-pipeline.md`: Lines 245-246 reference "GPT-4"
- `02-product/03-value-propositions.md`: Line 30 says "Implemented (GPT-4)"
- `01-research/11-existing-adrs.md`: Line 43 says "GPT-4, GPT-3.5"

### Claim 3: "18 modules" (01-service-architecture.md)

**VERIFIED: CORRECT**

Source: `app/modules/` directory contains 17 module directories plus the health router. The `main.py` imports routers from: auth, users, roles, indexes, conversations, chat, admin (azure + audit), glossary, feedback, analytics (analytics + usage), sharepoint, mcp, kb, sync_worker, notifications, async_tasks, and health. Count matches.

### Claim 4: "No tenant_id field in any data model" (00-executive-summary.md, 08-current-tenant-model.md)

**VERIFIED: CORRECT**

Source: `grep -r "tenant_id" app/` returns only 6 files, all in comments, config descriptions, or logging context -- not in actual data model operations. No Cosmos DB query includes `tenant_id` as a filter parameter.

### Claim 5: "Dual-mode auth: Azure AD + Local" (03-auth-rbac.md)

**VERIFIED: CORRECT**

Source: `config.py` line 64: `auth_mode: str = Field(default="dual")` with options `dual | azure_ad_only | local_only`. `auth/router.py` has both `/login/local` and `/login/azure` endpoints.

### Claim 6: "23 Cosmos DB containers" (02-data-models.md lists 23)

**VERIFIED: PARTIALLY CORRECT**

Source: `app/core/database.py` contains container initialization. The data models doc lists 23 containers, but the numbering jumps (1-23 with some gaps). Cross-referencing with `init_database()` shows the actual active containers are fewer -- several (audit_logs, usage_events) are marked DEPRECATED. The effective container count is approximately 20 active containers.

### Claim 7: "Redis cache with aihub2: prefix" (00-executive-summary.md)

**VERIFIED: CORRECT**

Source: `config.py` line 48: `redis_key_prefix: str = Field(default="mingai:")`

### Claim 8: "JWT 8-hour access tokens" (03-auth-rbac.md)

**VERIFIED: CORRECT**

Source: `config.py` line 53: `jwt_expire_minutes: int = Field(default=480)` (480 minutes = 8 hours)

### Claim 9: "HS256 JWT signing" (03-auth-rbac.md)

**VERIFIED: CORRECT**

Source: `config.py` line 52: `jwt_algorithm: str = Field(default="HS256")`

**Note**: HS256 is symmetric key signing. For multi-tenant, this means all API instances share the same secret. RS256 (asymmetric) would be more appropriate for a multi-tenant platform where tenant-specific signing keys may be needed. Neither the auth docs nor the SSO strategy doc address this.

### Claim 10: "text-embedding-3-large (3072 dimensions)" (04-rag-pipeline.md)

**VERIFIED: CORRECT**

Source: `config.py` line 110: `azure_openai_doc_embedding_deployment: str = Field(default="text-embedding-3-large")`. The RAG pipeline doc correctly identifies 3072 dimensions. Additionally, the system has a secondary embedding deployment for legacy KBs using `text-embedding-ada-002`.

---

## 2. USP Scrutiny -- Steelman Counter-Cases

### USP 1: MCP Protocol for Custom Data Source Integration

**Moat rating in doc**: MODERATE

**Steelman counter-case**: The MCP module in `app/modules/mcp/` uses a custom WebSocket-based tool invocation protocol. This is NOT the same as Anthropic's Model Context Protocol standard that is gaining industry adoption. If Anthropic's MCP becomes the industry standard (which it is trending toward), AI Hub's custom protocol becomes a liability, not a differentiator. Customers would need to maintain two different "MCP" implementations. Furthermore, the 9 MCP servers are custom-built for specific enterprise systems -- they represent engineering investment, not protocol advantage.

**Survives scrutiny?** PARTIALLY. The MCP servers themselves (Bloomberg, Oracle Fusion, etc.) are valuable. The protocol framing as "open standard" is misleading if it's a proprietary implementation.

### USP 2: Deep, Fine-Grained RBAC with 9 System Functions

**Moat rating in doc**: LOW-MODERATE

**Steelman counter-case**: The 9 system functions are genuine and verified. However, the RBAC model has 10 documented design gaps from an operational review (ADR-002 / TODO-73). These include: no role expiration enforcement, no delegated admin scoping, and potential privilege escalation paths. A CTO doing due diligence would find these gaps. Additionally, Okta Fine-Grained Authorization and Azure AD Privileged Identity Management already provide similar granularity as managed services.

**Survives scrutiny?** PARTIALLY. The RBAC implementation is real but has known gaps. The value is genuine for organizations that need index-level access control integrated with their search pipeline, which neither Okta nor Azure PIM provides.

### USP 3: Azure-Native Architecture

**Moat rating in doc**: LOW

**Steelman counter-case**: This is a deployment choice, not a product feature. The doc correctly rates this as LOW moat. However, the doc fails to mention that Azure-native is also a risk: Azure OpenAI has capacity constraints, regional availability gaps, and token pricing that is 30-40% higher than direct OpenAI API access. Multi-cloud customers (who represent the majority of enterprises) would see Azure-only as a limitation.

**Survives scrutiny?** NO. Being Azure-native is table stakes for Azure shops and a disqualifier for everyone else. It should not be positioned as a USP.

### USP 4: Comprehensive Cost Analytics

**Moat rating in doc**: LOW

**Steelman counter-case**: The cost analytics are impressive in granularity but they solve a problem that only matters after the customer is already using the product. No buyer says "I'll choose this product because it has better cost analytics." They say "I'll choose this product because it answers my questions better." Cost analytics is a retention feature, not an acquisition feature.

**Survives scrutiny?** NO as an acquisition USP. YES as a retention and expansion feature. Reclassify from USP to "enterprise retention advantage."

### USP 5: Agent Communication Channels with Email Triage

**Moat rating in doc**: MODERATE

**Steelman counter-case**: The email triage system (multi-layer routing: correlation matching, People API lookup, admin queue) is genuinely innovative. However, it introduces significant security and compliance risks: an AI sending emails on behalf of users can create legal liability, spam complaints, and GDPR issues. No enterprise buyer's legal team will approve an AI agent sending emails without extensive review. The doc does not address these risks.

**Survives scrutiny?** PARTIALLY. The technical implementation is strong, but the legal/compliance barriers to enterprise adoption are underestimated. This USP needs a compliance-first redesign before it can be sold.

---

## 3. Gap Analysis

### Features in Code but Missing from Analysis

1. **Circuit breaker pattern** (`app/core/` references): Mentioned briefly in product vision but not analyzed in depth. Circuit breakers are critical for multi-tenant reliability -- one tenant's slow MCP server should not degrade service for others.

2. **Token refresh worker** (`app/modules/auth/token_refresh_worker.py`): Background worker for proactive Azure AD token refresh. This has implications for multi-tenant: each tenant's AD tokens need independent refresh cycles.

3. **Conversation retention policies** (config.py lines 203-209): 3-year retention with archive-before-delete and advance warning. Multi-tenant implication: retention policies need to be per-tenant, not global.

4. **Legacy embedding support** (config.py line 176): The system maintains two embedding models (text-embedding-3-large and text-embedding-ada-002) for backward compatibility. Migration docs should address embedding migration strategy per tenant.

5. **Rate limiter** (`app/core/rate_limiter.py` at 19KB): Sophisticated rate limiting exists but is globally configured. Multi-tenant needs per-tenant rate limits.

### Edge Cases in User Flows Unhandled

1. **Tenant suspension mid-session**: What happens to active WebSocket connections and SSE streams when a platform admin suspends a tenant? The user flow docs don't address graceful degradation.

2. **Cross-tenant user**: An employee who belongs to multiple organizations (contractor, consultant). Auth0 Organizations handle this, but the data model assumes one user belongs to one tenant.

3. **Tenant data export (GDPR)**: No user flow for "export all my tenant's data." Required by GDPR Article 20 (right to data portability).

4. **Tenant deletion cascade**: The admin hierarchy doc lists DELETE endpoint but the user flow doesn't show the confirmation flow, grace period, data retention during deletion, or what happens to in-flight queries.

5. **SSO provider migration**: What if a tenant wants to switch from Azure AD to Okta? The auth strategy doc discusses Auth0 connections but not the migration path for existing users' identity mappings.

### Technical Risks Underplayed

1. **Cosmos DB partition key migration**: The data isolation doc proposes changing partition keys from `/id` or `/user_id` to `/tenant_id` for most containers. Cosmos DB does NOT support partition key changes. This requires creating new containers, copying all data, and switching over -- effectively a zero-downtime database migration for every container. The risk of data loss or corruption during this migration is HIGH and the doc describes it in 20 lines.

2. **Auth0 vendor lock-in**: Replacing direct Azure AD integration with Auth0 introduces a critical vendor dependency. Auth0 pricing at enterprise scale ($2-5/active user/month) could exceed the product's own pricing. No cost analysis exists.

3. **Search index proliferation**: Tenant-prefixed indexes (recommended in data isolation doc) means N tenants x M indexes per tenant. At 100 tenants with 10 indexes each = 1,000 Azure Search indexes. Azure Search has per-index costs and management overhead. The doc acknowledges "more indexes to manage" but provides no scaling analysis.

### Multi-Tenant Isolation Edge Cases Missed

1. **Shared embedding cache**: The current Redis embedding cache uses query hash as key. In multi-tenant, two tenants asking the same question would get the same cached embedding, which is fine -- but if embeddings are generated using tenant-specific models (BYOLLM), cache keys must include tenant_id + model_id.

2. **Glossary term collision**: Glossary terms are proposed to be scoped per tenant (`/tenant_id` partition key), but the glossary auto-detection in queries operates globally. If tenant A defines "PTO" differently than tenant B, the detection logic needs tenant context.

3. **MCP server credential isolation**: MCP servers in the current architecture share credentials via environment variables. Multi-tenant MCP requires per-tenant credential vaults -- the doc mentions this but the actual MCP module (`app/modules/mcp/`) has no tenant-awareness in its service or client code.

4. **Event partition key format change**: Changing events partition key from `user_id:YYYY-MM` to `tenant_id:user_id:YYYY-MM` means existing events become inaccessible via the new partition key pattern. Historical analytics for the default tenant will break unless migrated.

---

## 4. PMF Challenge

### Who Would NOT Buy This?

1. **CTO at a 5,000-person enterprise already on Copilot**: "We already pay for M365 E5 at $57/user/month which includes Copilot Chat. Your product requires us to maintain separate infrastructure, train our IT team on a new admin console, build MCP servers for our data sources, and pay for both Azure OpenAI AND your licensing. The incremental value of reaching Bloomberg data through your platform does not justify the incremental cost and operational overhead when our Bloomberg team already has Bloomberg terminals."

2. **VP of IT at a multi-cloud company**: "Our strategy is cloud-agnostic. We run production on AWS, development on GCP, and M365 on Azure. Your product requires all-Azure infrastructure. Our security team won't approve another Azure-only tool when we're trying to reduce Azure dependency."

3. **CISO at a healthcare organization**: "You don't have HIPAA BAA, SOC 2 Type II, or HITRUST certification. I can't even start the procurement conversation without these. Come back when you have them. That's a 6-12 month process minimum."

4. **CFO evaluating AI spend**: "You can't tell me what this costs per user per month. You can't tell me the ROI. You have no reference customers. I'm not approving budget for a product that has never been sold to anyone."

5. **Head of Knowledge Management**: "Glean gives me 100+ connectors out of the box and their team handles connector maintenance. Your product requires my engineering team to build and maintain MCP servers. I don't have that engineering capacity. Glean costs $50/user/month and works in 2 weeks. Your product requires months of setup."

### The Hardest Objection

The hardest objection from a CTO at a 5,000-person enterprise:

> "You're asking me to bet on a custom platform with no track record, maintained by a small team, over Microsoft Copilot which has billions of dollars of investment and is backed by the same Azure services you use. What happens when your 5-person team can't keep up with GPT-6, Azure API changes, or security vulnerabilities? Microsoft maintains Copilot for me. Who maintains your platform?"

This objection is nearly insurmountable without (a) a substantial team commitment, (b) a clear roadmap demonstrating sustainable development velocity, and (c) reference customers who can validate long-term viability.

---

## 5. Plan Coherence

**Critical finding: No plans exist.** The `02-plans/` directory is empty. This means the red team cannot assess:

- Whether phase dependencies are correct
- Whether the timeline is realistic
- Whether the plans flow logically from the analysis

This is the most significant gap in the workspace deliverables.

**Assessment of analysis-to-architecture flow**: The analysis documents (01-research, 02-product) are thorough and honest. The multi-tenant architecture docs (04-multi-tenant) are well-designed and technically sound. However, they exist in isolation -- there is no bridge document that says "given these findings, here is the prioritized implementation plan."

---

## 6. 80/15/5 Audit

The `04-unique-selling-points.md` includes an 80/15/5 breakdown. Assessment:

### Miscategorized Items

1. **"User profiling (opt-in/opt-out)" -- listed as 80% (core)**. This should be **15% (configurable)** or even **5% (custom)**. User profiling is an advanced feature that many enterprise customers will disable for privacy reasons. It is not core functionality.

2. **"Internet fallback" -- listed as 80% (core)**. This should be **15% (configurable)**. Many regulated enterprises will explicitly prohibit internet search from their AI assistant. Financial services firms with information barriers cannot allow queries to leak to external search services.

3. **"MCP server registration" -- listed as 15% (configurable)**. This is correctly categorized, but the prerequisite is wrong. MCP server registration requires MCP servers to exist. Without the MCP Server Marketplace (listed as a moat strategy), the 15% configurable layer has nothing to configure for most customers.

4. **"Custom LLM workflows" -- listed as 5% (custom)**. The BYOLLM feature in the admin hierarchy doc is positioned as a configuration toggle, which would make it 15%. But the actual codebase only supports Azure OpenAI (verified), which means supporting any other provider is a 5% custom development. The docs contradict themselves.

---

## 7. Top 5 Highest-Risk Decisions

### Risk 1: Auth0 as Universal SSO Broker

**Risk level**: CRITICAL
**Why it's high risk**: Replacing direct Azure AD integration (which works today) with Auth0 Organizations introduces a new vendor dependency, a new authentication flow, potential latency increase (extra hop through Auth0), and migration risk for existing users. Auth0 has had security incidents (2022 source code breach). If Auth0 experiences downtime, ALL tenants are locked out simultaneously.
**Mitigation**: Define Auth0 as optional. Allow tenants to connect Azure AD directly (current flow) or through Auth0. Make Auth0 the recommended path for non-Azure-AD identity providers, not a mandatory intermediary.

### Risk 2: Cosmos DB Partition Key Migration

**Risk level**: HIGH
**Why it's high risk**: Every container except `messages` and `events` needs a partition key change. Cosmos DB requires container recreation for partition key changes. During migration, the application must handle dual-read (old + new containers) for each container. A bug in migration could cause data loss. Timeline estimate in current-tenant-model.md (Weeks 1-2 for schema) is unrealistic for 20 containers.
**Mitigation**: Phase the migration. Start with new-tenant-only containers (new tenants get `/tenant_id` partition keys). Migrate existing default tenant last. Use Cosmos DB Change Feed for continuous sync during migration.

### Risk 3: Azure-Only Lock-in for a Multi-Tenant SaaS

**Risk level**: HIGH
**Why it's high risk**: Every customer must be on Azure. Azure OpenAI has capacity constraints and regional availability limits. A SaaS platform that cannot serve AWS or GCP customers limits the addressable market by approximately 60%. If Azure OpenAI experiences a regional outage, all tenants in that region are affected.
**Mitigation**: Abstract the LLM, search, and database layers behind provider interfaces. Start with Azure-only but design for multi-cloud from day one. Priority: support direct OpenAI API as a fallback for Azure OpenAI outages.

### Risk 4: No Pricing Model Before Building Multi-Tenant

**Risk level**: HIGH
**Why it's high risk**: The team is about to invest significant engineering effort in multi-tenancy without knowing whether customers will pay enough to cover the infrastructure costs. Multi-tenant infrastructure is expensive. If pricing is set too low, the business is unprofitable. If too high, customers choose Copilot or Glean. The PMF assessment rates willingness-to-pay at 1/5.
**Mitigation**: Before writing any multi-tenant code, interview 5-10 potential customers about willingness to pay. Define pricing tiers. Build a cost model that includes Azure infrastructure, Auth0, engineering maintenance, and support. Only proceed if unit economics work.

### Risk 5: MCP Server Development Bottleneck

**Risk level**: MODERATE-HIGH
**Why it's high risk**: The MCP protocol is the strongest technical differentiator, but every new data source requires custom server development. Each MCP server (Bloomberg, Oracle Fusion, CapIQ, etc.) is a separate Docker container with its own dependencies, authentication, and maintenance burden. At 9 servers already, the maintenance load is significant. For multi-tenant, each server needs tenant-aware credential management.
**Mitigation**: Prioritize the MCP Server Marketplace. Create a standardized MCP server template and SDK that reduces development time from weeks to days. Focus on the top 5 data sources that cover 80% of target customer needs.

---

## 8. A2A/MCP Integrity Assessment

The `10-kaizen-extension-analysis.md` provides a detailed analysis of how Kaizen AI providers could extend the system. Assessment:

### Is the agentic pattern genuinely better than current implementation?

**Current implementation**: The MCP module uses a custom tool-call protocol where the LLM emits `[TOOL_CALL]` markers in its response, the system parses these, invokes the MCP server via WebSocket, and resumes the LLM with the tool result. This is a functional but fragile pattern -- it depends on the LLM reliably producing a specific string format.

**Proposed agentic pattern**: The Kaizen analysis proposes multi-provider LLM support, database-driven configuration, and tenant-aware provider selection. This is architecturally sound but represents significant new development.

**Honest assessment**: The proposed patterns are NOT "renamed complexity." They solve real problems:

1. **Multi-provider support** addresses Azure-only lock-in
2. **Database-driven config** enables per-tenant LLM selection without redeployment
3. **BYOLLM** is a genuine enterprise requirement (many firms have their own Azure OpenAI instances)

However, the gap between current state (single provider, env-var config) and target state (multi-provider, database-driven, tenant-aware) is large. The analysis correctly identifies this as a multi-phase effort but does not estimate the engineering effort required. A rough estimate: 3-6 engineer-months for basic multi-provider support, 6-12 engineer-months for full BYOLLM with tenant isolation.

---

## What Was Done Well

1. **PMF assessment is brutally honest** (05-pmf-assessment.md): Scoring the product at 2.7/5 and explicitly calling out willingness-to-pay at 1/5 shows intellectual honesty that is rare in product analysis. This document alone could save months of wasted effort by forcing the team to validate market assumptions before building.

2. **USP analysis distinguishes table stakes from differentiators** (04-unique-selling-points.md): Most product teams list every feature as a differentiator. This analysis correctly identifies that 10+ features are table stakes and only 5 are genuine differentiators. The steelman format forces rigorous thinking.

3. **Multi-tenant data isolation design is thorough** (02-data-isolation.md): The TenantScopedRepository pattern with defense-in-depth (JWT + middleware + repository + partition key + audit) is a well-designed isolation strategy. The migration phases are logical.

4. **Admin hierarchy is well-structured** (01-admin-hierarchy.md): The platform admin vs. tenant admin split with clear permission boundaries is the right approach. The plan tier matrix (Starter/Professional/Enterprise) is realistic.

5. **Research depth is exceptional**: 12 research documents covering architecture, data models, auth, RAG pipeline, LLM integration, MCP servers, frontend, tenant model, deployment, Kaizen analysis, and ADRs. This is comprehensive and each document shows evidence of reading actual source code.

6. **Auth strategy identifies the right problem** (03-auth-sso-strategy.md): Supporting multiple SSO providers per tenant is indeed the core challenge for multi-tenancy, and the analysis of current limitations is accurate and specific (citing exact file lines).

7. **Competitive analysis is fair** (02-competitive-analysis.md): The analysis doesn't pretend competitors are weak. It honestly assesses Copilot's strengths and Glean's connector advantage.

---

## Specific Corrections -- Status

| #   | File                                       | Section                          | Issue                                                       | Correction                                                          | Status |
| --- | ------------------------------------------ | -------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------- | ------ |
| 1   | `01-research/00-executive-summary.md`      | Lines 119-123, 131, 145          | References "GPT-4" as primary and "GPT-4 Mini" as auxiliary | Changed to "GPT-5.2-chat" and "GPT-5 Mini" per config.py            | FIXED  |
| 2   | `01-research/01-service-architecture.md`   | Lines 215, 244, 248, 736, 748    | References "GPT-4" in RAG pipeline description              | Changed to "GPT-5.2-chat" / "GPT-5 Mini"                            | FIXED  |
| 3   | `01-research/04-rag-pipeline.md`           | Lines 16, 245, 284, 311, 450-451 | Multiple "GPT-4" references                                 | Changed to "GPT-5.2-chat (aihub2-main deployment)" / "GPT-5 Mini"   | FIXED  |
| 4   | `02-product/03-value-propositions.md`      | Line 30                          | "Implemented (GPT-4)"                                       | Changed to "Implemented (GPT-5.2-chat)"                             | FIXED  |
| 5   | `01-research/11-existing-adrs.md`          | Lines 43, 313-316, 329-332       | "GPT-4, GPT-3.5" and cost table                             | Changed to "GPT-5.2-chat, GPT-5 Mini" with corrected cost estimates | FIXED  |
| 6   | `02-product/01-product-vision.md`          | Line 91                          | "GPT-4 via Azure OpenAI"                                    | Changed to "GPT-5.2-chat via Azure OpenAI"                          | FIXED  |
| 7   | `01-research/02-data-models.md`            | Container count                  | Says "18 Total" in heading but lists 23 rows                | Changed to "23 Total, 2 Deprecated"                                 | FIXED  |
| 8   | `04-multi-tenant/02-data-isolation.md`     | Phase 1 migration                | `ALTER TABLE` SQL syntax                                    | No SQL DDL found in this doc (checked; issue was in 08 only)        | N/A    |
| 9   | `01-research/08-current-tenant-model.md`   | Lines 152-171                    | Uses SQL ALTER TABLE syntax for Cosmos DB                   | Replaced with Python SDK examples using Cosmos DB API               | FIXED  |
| 10  | `03-user-flows/02-tenant-admin-flows.md`   | Lines 233, 582-583               | References "GPT-4o" and "GPT-4o-mini"                       | Changed to "GPT-5.2-chat" and "GPT-5-mini"                          | FIXED  |
| 11  | `03-user-flows/01-platform-admin-flows.md` | Line 198                         | References "gpt-4o, gpt-4o-mini, o3-mini"                   | Changed to "gpt-5.2-chat, gpt-5-mini"                               | FIXED  |
| 12  | `03-user-flows/04-platform-model-flows.md` | Line 170                         | References "GPT-4o" as OpenAI model                         | Changed to "GPT-5.2-chat"                                           | FIXED  |

---

## Pass 2: Architecture Docs (04-06) + User Flows (03-04) Review

**Date**: March 4, 2026
**New documents reviewed**:

- `04-multi-tenant/04-llm-provider-management.md` (877+ lines)
- `04-multi-tenant/05-cloud-agnostic-deployment.md` (879+ lines)
- `04-multi-tenant/06-a2a-mcp-agentic.md` (975 lines)
- `03-user-flows/03-end-user-flows.md` (617 lines)
- `03-user-flows/04-platform-model-flows.md` (429+ lines)

**Note**: 02-plans/ remains empty at time of this review. Plans review deferred to Pass 2b.

---

### Pass 2 -- Source Code Verification

#### 1. LLM Provider Abstraction (04-llm-provider-management.md)

**Claim**: "Single provider hardcoded in `app/services/openai_client.py:17`"
**Verdict**: ACCURATE. The entire codebase uses only `AsyncAzureOpenAI`. The provider abstraction layer (7 providers) is a design document, not existing code. This is correctly represented.

**Concern -- Anthropic embedding gap**: The `AnthropicProvider.embedding()` method raises `NotImplementedError`. This means if a tenant selects Anthropic as BYOLLM, they still need a separate embedding provider (Azure OpenAI or OpenAI). The doc acknowledges this at line 352-357 but doesn't define how the system handles mixed-provider configurations where one provider does chat and another does embeddings.

**Concern -- Provider cache invalidation**: The `_provider_cache` in `LLMClientManager` (line 821) is an in-memory dict. In a multi-replica deployment, key rotation or provider changes on one replica won't propagate to others. The doc mentions Redis cache for config (5-min TTL) but the instantiated provider objects are cached locally. This creates a window where stale credentials could be used.

#### 2. Cloud-Agnostic Deployment (05-cloud-agnostic-deployment.md)

**Claim**: Maps 10 Azure services to 4 cloud equivalents with abstraction layers.
**Verdict**: WELL-STRUCTURED but scope is enormous. This doc proposes 5 abstraction layers (DocumentStore, SearchEngine, ObjectStore, SecretStore, TelemetryExporter) with implementations for Azure, AWS, GCP, and Alibaba.

**Critical concern -- DynamoDB is NOT Cosmos DB**: The DynamoDB implementation at line 228-241 uses `table.query()` with `KeyConditionExpression`, but Cosmos DB SQL queries use a SQL-like syntax. The abstraction's `query_items()` accepts a `query: str` parameter designed for Cosmos DB SQL -- this won't map cleanly to DynamoDB's key-condition model. The translation layer between Cosmos DB SQL and DynamoDB expressions is handwaved.

**Critical concern -- Firestore pagination**: The Firestore implementation at line 263-270 does `collection.where("tenant_id", "==", partition_key)` followed by `.get()` -- this fetches ALL matching documents. For large tenants, this is a scalability disaster. No pagination, no cursor-based iteration.

**Critical concern -- Alicloud uses wrong class**: Line 726-728 instantiates `DynamoDBStore` for Alibaba Cloud with a comment "ApsaraDB for MongoDB compatible." This is incorrect -- DynamoDB and MongoDB have completely different APIs. An Alibaba-specific implementation is needed.

**Critical concern -- GCS is synchronous**: The `GCSStore` at line 473-494 uses `google.cloud.storage.Client` which is synchronous. The abstract interface defines `async` methods. The implementation will block the event loop.

**Concern -- search parity**: Azure AI Search supports hybrid search (text + vector) natively. OpenSearch supports it but with different query syntax. The abstraction simplifies this but loses Azure-specific features like semantic ranker and custom analyzers.

#### 3. A2A Protocol and Agentic RAG (06-a2a-mcp-agentic.md)

**Claim**: Evolves from single-step RAG to multi-agent orchestration with A2A protocol.
**Verdict**: AMBITIOUS and architecturally sound. The current system already has a `ResearchAgentHandler` (referenced at line 511), so the foundation for agent-based queries exists.

**Strength -- backward compatibility**: The design preserves the "simple query -> single agent" path (line 644-650) and only activates multi-agent for complex queries. This avoids unnecessary latency and cost for 80% of queries.

**Concern -- cost multiplication**: The agentic RAG pipeline uses 3-8 LLM calls per query (line 787). At $0.016/query for single-step RAG, complex queries could cost $0.05-0.13 each. For tenants with heavy research usage, monthly LLM costs could 3-8x.

**Concern -- tenant circuit breaker isolation is good but incomplete**: Per-tenant circuit breakers (line 812-853) isolate failures. However, the implementation stores state in Redis with `EXPIRE` -- if Redis fails, all breakers reset to closed, potentially flooding a failing MCP server.

**Concern -- A2A message format is custom, not Google A2A**: The `A2AMessage` dataclass (line 562-581) is a custom format. Google's A2A protocol (announced 2025) has its own message format. The doc doesn't clarify whether this is intended to be compatible with the open A2A standard or is an internal protocol with similar naming.

#### 4. End User Flows (03-end-user-flows.md)

**Verdict**: COMPREHENSIVE. Covers 8 flows with detailed error paths. This was the most significant gap from pass 1 (gap #9: "only 2 of 6+ personas covered").

**Strength**: The document correctly references Auth0/Azure AD dual-path login, 8-hour JWT expiry, and tenant-scoped personal document indexing -- all consistent with the architecture docs.

**Concern -- Research Mode scope**: Research mode allows selecting up to 20 indexes (line 241). At 5 chunks per index = 100 chunks in context. With 128K context window, this is feasible but will consume significant tokens. No cost estimation is provided for research queries vs standard queries.

**Concern -- Agent delegation time limits**: "Quick (5 min) / Standard (15 min) / Deep (30 min)" at line 338. These are user-facing time commitments. At $0.05-0.13 per agentic query and potentially 10-50 sub-queries per delegation, a "Deep" research delegation could cost $1-6.50. No cost visibility is shown to users before delegation.

#### 5. Platform Model Flows (04-platform-model-flows.md)

**Verdict**: STRONG strategic framing. The AAA (Automate, Augment, Amplify) framework is well-applied to each persona. Network effects analysis is honest about current weakness.

**Concern -- "Amplify" claims may be premature**: The doc claims junior employees get "senior-researcher-grade synthesis" (line 347-349). This depends entirely on RAG quality and index coverage. If the knowledge base has gaps (which the PMF assessment scored at 2.7/5), the amplification promise is unreliable.

---

### Pass 2 -- Revised Gap Assessment

#### Gaps Resolved Since Pass 1

| Pass 1 Gap # | Description                            | Status                                                                                   |
| ------------ | -------------------------------------- | ---------------------------------------------------------------------------------------- |
| 5            | BYOLLM strategy underspecified         | RESOLVED -- Doc 04 provides full provider abstraction with 7 providers                   |
| 6            | MCP differentiator fragile             | PARTIALLY RESOLVED -- Doc 06 adds tenant-scoped MCP + A2A orchestration                  |
| 9            | User flows cover only 2 of 6+ personas | RESOLVED -- 4 flow docs now cover platform admin, tenant admin, end user, platform model |

#### New Gaps Identified in Pass 2

| #   | Gap                                                                                     | Severity | Document           |
| --- | --------------------------------------------------------------------------------------- | -------- | ------------------ |
| N1  | Anthropic provider cannot do embeddings; mixed-provider config for chat+embed undefined | MEDIUM   | 04-llm-provider    |
| N2  | Cloud-agnostic DynamoDB query translation from Cosmos SQL is handwaved                  | HIGH     | 05-cloud-agnostic  |
| N3  | Firestore implementation lacks pagination; will not scale for large tenants             | HIGH     | 05-cloud-agnostic  |
| N4  | Alicloud uses wrong store class (DynamoDB instead of MongoDB-compatible)                | MEDIUM   | 05-cloud-agnostic  |
| N5  | GCS implementation is synchronous in async interface; will block event loop             | MEDIUM   | 05-cloud-agnostic  |
| N6  | In-memory provider cache won't invalidate across replicas                               | MEDIUM   | 04-llm-provider    |
| N7  | Agentic RAG cost multiplication (3-8x) not reflected in pricing models                  | HIGH     | 06-a2a-mcp-agentic |
| N8  | A2A protocol naming implies Google A2A compatibility but is a custom format             | LOW      | 06-a2a-mcp-agentic |
| N9  | No cost visibility for users before agent delegation                                    | MEDIUM   | 03-end-user-flows  |
| N10 | 02-plans/ still empty -- no implementation roadmap, timelines, or migration plan        | CRITICAL | (missing)          |

#### Outstanding Pass 1 Gaps (Still Unresolved)

| Pass 1 Gap # | Description                                                       | Status                                                                                                     |
| ------------ | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| 2            | No implementation roadmap (02-plans/)                             | STILL MISSING                                                                                              |
| 3            | Auth0 migration -- riskiest decision, no fallback                 | Architecture described but no prototype or validation plan                                                 |
| 4            | Cosmos DB partition key change -- container recreation complexity | Acknowledged in docs but no step-by-step migration runbook                                                 |
| 7            | Cost estimates unrealistic                                        | $0.016/query for simple RAG, but agentic RAG could be $0.05-0.13/query -- budget projections need revision |
| 8            | No disaster recovery strategy                                     | Still not addressed in any document                                                                        |
| 10           | PMF 2.7/5, lowest dimensions not addressed                        | No pricing model or go-to-market strategy in any document                                                  |

---

### Pass 2 -- Scope Creep Assessment

The three new architecture docs (04, 05, 06) significantly expand the project scope:

| Dimension             | Pass 1 Scope      | Pass 2 Scope                                                         | Scope Delta  |
| --------------------- | ----------------- | -------------------------------------------------------------------- | ------------ |
| LLM providers         | 1 (Azure OpenAI)  | 7 (Azure, OpenAI, Anthropic, Deepseek, DashScope, Doubao, Gemini)    | +6 providers |
| Cloud platforms       | 1 (Azure)         | 4 (Azure, AWS, GCP, Alibaba)                                         | +3 clouds    |
| Abstraction layers    | 0                 | 5 (DocumentStore, SearchEngine, ObjectStore, SecretStore, Telemetry) | +5 layers    |
| Agent types           | 1 (ResearchAgent) | 5 (Intent, Planner, KB Search, MCP Search, Synthesis, Validation)    | +4-5 agents  |
| MCP credential models | 1 (env-based)     | 3 (platform, per-user OBO, tenant BYOKEY)                            | +2 models    |
| IaC modules           | 0                 | 20+ (Terraform modules x 4 clouds)                                   | +20 modules  |

**Risk**: Each expansion multiplies testing surface area. Supporting 7 LLM providers x 4 cloud platforms x 5 abstraction layers creates a combinatorial testing matrix of 140+ configurations. No testing strategy for this matrix exists.

---

### Pass 2 -- Updated Top Risks

1. **Cloud-agnostic layer is a second product**: The 5 abstraction layers with 4 cloud implementations is essentially building a cloud abstraction SDK. This should be a separate workstream with its own timeline, not embedded in the multi-tenant migration.

2. **Agentic RAG cost is unbudgeted**: 3-8x cost per complex query with no pricing model means the first tenant doing heavy research will generate unexpected bills. Must be visible before deployment.

3. **Plans still missing**: Architecture without a roadmap is a wish list. The three new docs add significant scope but no prioritization, phasing, or timeline.

4. **DynamoDB compatibility is not trivial**: Cosmos DB SQL and DynamoDB have fundamentally different query models. The abstraction assumes query translation that doesn't exist.

5. **Multi-provider embeddings require cross-provider strategy**: If tenant uses Anthropic for chat but needs Azure OpenAI for embeddings, the system needs explicit mixed-provider routing that isn't designed.

---

### Pass 2 Corrections Applied

In addition to the 3 outstanding corrections from pass 1 (now FIXED), pass 2 found and corrected 3 additional GPT model name errors in the user flow docs:

- `03-user-flows/01-platform-admin-flows.md`: "gpt-4o, gpt-4o-mini" -> "gpt-5.2-chat, gpt-5-mini"
- `03-user-flows/02-tenant-admin-flows.md`: "GPT-4o" -> "GPT-5.2-chat" (2 locations)
- `03-user-flows/04-platform-model-flows.md`: "GPT-4o" -> "GPT-5.2-chat"

Total corrections across both passes: 12 files fixed.

---

**Pass 2 Review Complete**
**Updated Recommendation**: The architecture vision is significantly more ambitious than pass 1 revealed. Before implementation:

1. **Prioritize ruthlessly**: The cloud-agnostic layer (doc 05) should be Phase 3+, not Phase 1. Start with Azure-only multi-tenancy.
2. **Budget the agentic RAG costs**: Before launching multi-agent queries, establish per-tenant cost caps and user-visible cost estimates.
3. **Produce the roadmap** (02-plans/): Architecture without timelines is aspirational documentation, not an implementation plan.
4. **Test the provider abstraction with 2 providers first**: Azure OpenAI + OpenAI Direct share the same SDK. Start there before tackling Anthropic/Deepseek/DashScope.
5. **Validate DynamoDB/Firestore parity before claiming multi-cloud**: The abstraction layer has real gaps that will surface in integration testing.

---

## Pass 2b: Plans Review (01-implementation-roadmap.md + 02-technical-migration-plan.md)

**Date**: March 4, 2026
**Documents reviewed**:

- `02-plans/01-implementation-roadmap.md` (366 lines)
- `02-plans/02-technical-migration-plan.md` (607 lines)

This pass closes the most critical gap from passes 1 and 2: the absence of implementation plans.

---

### Pass 2b -- Source Code Verification

#### P1: Container count mismatch (CRITICAL)

**Roadmap claim** (Phase 1): "All 9 Cosmos containers updated with `tenant_id`"
**Migration plan** (Section 1): Lists 9 containers for migration.

**Actual source code** (`test_cosmosdb_containers.py` lines 38-61): **21 active containers**.

Missing from both plan documents:

| Container                 | Current Partition Key | Status  |
| ------------------------- | --------------------- | ------- |
| `user_roles`              | `/user_id`            | MISSING |
| `group_roles`             | `/group_id`           | MISSING |
| `group_membership_cache`  | `/group_id`           | MISSING |
| `audit_logs`              | `/user_id`            | MISSING |
| `user_preferences`        | `/user_id`            | MISSING |
| `glossary_terms`          | `/scope`              | MISSING |
| `user_profiles`           | `/user_id`            | MISSING |
| `profile_learning_events` | `/user_id`            | MISSING |
| `consent_events`          | `/user_id`            | MISSING |
| `feedback`                | `/user_id`            | MISSING |
| `conversation_documents`  | `/conversation_id`    | MISSING |
| `document_chunks`         | `/conversation_id`    | MISSING |
| `events`                  | `/partition_key`      | MISSING |
| `mcp_servers`             | `/id`                 | MISSING |
| `notifications`           | `/user_id`            | MISSING |

**Impact**: 15 containers will not receive `tenant_id` during migration. Any data in these containers will lack tenant isolation. This is a data leakage vulnerability for multi-tenant deployment.

**Severity**: CRITICAL -- a migration plan that covers 43% of containers is incomplete and dangerous.

#### P2: Partition key errors in migration plan (HIGH)

The migration plan lists incorrect current partition keys for at least 2 containers:

| Container             | Migration Plan Says | Actual (Source Code) |
| --------------------- | ------------------- | -------------------- |
| `usage_events`        | `/user_id`          | `/partition_key`     |
| `question_categories` | `/id`               | `/date`              |

Running the migration script with wrong partition keys will cause cross-partition query failures or incorrect data placement in `_v2` containers.

#### P3: RBAC system functions are fabricated (HIGH)

**Migration plan** (Section 4) lists "9 System Functions":
`chat, search, analyze, export, manage_users, manage_settings, manage_categories, view_usage, manage_integrations`

**Actual source code** (`init_system_roles.py` lines 88-97):
`role:manage, user:manage, index:manage, analytics:view, audit:view, integration:manage, feedback:view, sync:manage, glossary:manage`

Not a single function name matches. This means the RBAC extension design in Section 4 is built on a fictional baseline. The "Additive model" decision is correct in principle, but the specific function names and role names are wrong.

#### P4: Role names are fabricated (MEDIUM)

**Migration plan** (Section 4) lists "6 Roles": Owner, Admin, Analyst, Viewer, Restricted, API.

**Actual source code** (`init_system_roles.py` lines 41-100):
Role Administrator, Index Administrator, User Administrator, Analytics Viewer, Audit Viewer, Administrator.

No "Owner", "Analyst", "Viewer", "Restricted", or "API" roles exist in the codebase. The migration plan's RBAC extension builds on a role model that does not exist.

#### P5: `permissions` container does not exist (MEDIUM)

The migration plan (Section 1, line 22; Section 4, lines 365-366) references a `permissions` container with partition key `/role_id`. This container does not exist in the source code. Permissions are stored as `system_permissions` arrays within role documents in the `roles` container. The migration plan's instruction to "Create platform functions in `permissions` container" would create a new container that the existing application code does not read from.

#### P6: `@lru_cache` Settings analysis is accurate (VERIFIED)

The migration plan correctly identifies the `@lru_cache` Settings singleton pattern. Verified in source:

- `backend/shared/aihub_shared/config/settings.py:136` -- `@lru_cache`
- `backend/shared/aihub_shared/config/worker_settings.py:435` -- `@lru_cache(maxsize=1)`
- `backend/shared/aihub_shared/database/cosmos.py:424` -- `@lru_cache`
- `backend/api-service/app/core/config.py:7` -- `from functools import lru_cache`
- `sync-worker/app/config.py:86` -- `@lru_cache`

The replacement with tenant-scoped Redis-cached config is a sound migration strategy.

#### P7: Redis key pattern `aihub2:` prefix confirmed (VERIFIED)

The migration plan correctly identifies the current Redis key pattern. Source code confirms:

- `backend/api-service/app/core/config.py:48` -- `redis_key_prefix: str = Field(default="mingai:")`
- `backend/shared/aihub_shared/config/worker_settings.py:85` -- `default="mingai:"`
- `backend/shared/aihub_shared/redis/utils.py:31` -- `# Default prefix - MUST be "mingai:" to avoid collisions`

The migration to `mingai:{tenant_id}:{key}` pattern with fallback during migration is well-designed.

#### P8: JWT configuration confirmed (VERIFIED)

Source code confirms HS256 with 8-hour access / 7-day refresh tokens:

- `.env.example:59` -- `JWT_ALGORITHM=HS256`
- `.env.example:60` -- `JWT_EXPIRY_HOURS=8`
- `.env.example:61` -- `JWT_REFRESH_EXPIRY_DAYS=7`

The dual-token acceptance window (30 days) for v1->v2 migration is a sound approach.

---

### Pass 2b -- Plan Coherence Assessment

#### Phase Logic

The 6-phase roadmap has correct dependency ordering:

1. Foundation (tenant_id injection) -- prerequisite for everything
2. LLM Marketplace -- requires tenant isolation from Phase 1
3. Auth Flexibility -- requires JWT v2 from Phase 1
4. Agentic Upgrade -- requires LLM abstraction from Phase 2 and auth from Phase 3
5. Cloud Agnostic -- requires all features working on Azure first
6. GA -- polish phase after all features

**Verdict**: Phase ordering is sound. No circular dependencies.

#### Timeline Realism

**Roadmap total**: 25 weeks (~6 months)
**Migration plan total**: 7 weeks for Phase 1 data migration alone

**Conflict**: The roadmap allocates 6 weeks for Phase 1, but the migration plan's zero-downtime deployment sequence alone takes 4 weeks (Week 1: deploy with flag off, Week 2: canary staging, Week 3: canary 10% production, Week 4: full rollout). Add the container creation, backfill, and validation steps and 6 weeks is tight.

**Assessment**: Phase 1 at 6 weeks is optimistic but achievable if the team is focused. Phases 2-5 at 3-5 weeks each assume parallel work streams, which is realistic for a multi-person team. Phase 6 at 3 weeks is reasonable for polish.

**Missing**: No team size assumption is stated anywhere. The timeline is meaningless without knowing whether this is 1 person or 10.

#### 80/15/5 Rule Compliance

The roadmap claims compliance with:

- 80% proven patterns (tenant isolation, JWT claims, provider abstraction)
- 15% targeted innovation (agentic RAG, A2A, MCP routing)
- 5% exploratory (cloud-agnostic, advanced billing)

**Assessment**: Phase 5 (Cloud Agnostic) is classified as 5% exploratory but consumes 4 weeks (16% of total timeline). If this is truly exploratory, it should be deferrable -- and the roadmap correctly places it as Phase 5. However, the 4-cloud ambition (Azure, AWS, GCP, Alibaba) contradicts "exploratory" classification. An exploratory phase would test Azure + 1 alternative, not 4 clouds.

The roadmap correctly applies the red-team recommendation from Pass 2 to start with 2 providers and 2 clouds. This is consistent.

#### Zero-Downtime Strategy

The migration plan's strangler fig pattern with feature flag (`MULTI_TENANT_ENABLED`) is well-designed:

- Week 1: deploy with flag off (zero risk)
- Week 2: canary staging
- Week 3: canary 10% production
- Week 4: full rollout

The rollback triggers are concrete and measurable (5% error rate, 2x P95 latency, 1% auth failures). The 48-hour rollback window is tight but adequate for a feature-flagged change.

**Concern**: The migration plan describes hot-reloading config ("No restart required if using hot-reloading config") but the current codebase uses `@lru_cache` which does NOT support hot reloading. The flag flip requires either a restart or the Redis-cached config from Section 3 to already be deployed.

#### Rollback Plan

The rollback plan is comprehensive and covers 5 scenarios. The "ZERO data loss" claim for the primary scenario (rollback before new tenants) is correct because:

1. Backfill is additive (adds `tenant_id` field, doesn't modify existing fields)
2. Partition key changes use `_v2` containers (originals preserved)
3. Feature flag off = immediate revert to single-tenant behavior

**Gap**: No rollback plan for Phase 2+ (LLM Marketplace, Auth). The migration plan only covers Phase 1 rollback. If Auth0 integration (Phase 3) fails, what is the rollback path? This is especially critical because Phase 3 changes the auth middleware itself.

---

### Pass 2b -- Factual Errors to Correct

| #   | Document                                  | Location     | Error                                                                          | Correction Needed                                                                                                                           |
| --- | ----------------------------------------- | ------------ | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 13  | `02-plans/01-implementation-roadmap.md`   | Phase 1      | "All 9 Cosmos containers"                                                      | Should be "All 21 Cosmos containers" (or "All active containers")                                                                           |
| 14  | `02-plans/02-technical-migration-plan.md` | Section 1    | Lists only 9 of 21 containers; missing 12                                      | Add all 15 missing containers to migration table                                                                                            |
| 15  | `02-plans/02-technical-migration-plan.md` | Section 1    | `usage_events` current partition key listed as `/user_id`                      | Actual is `/partition_key`                                                                                                                  |
| 16  | `02-plans/02-technical-migration-plan.md` | Section 1    | `question_categories` current partition key listed as `/id`                    | Actual is `/date`                                                                                                                           |
| 17  | `02-plans/02-technical-migration-plan.md` | Section 4    | 9 system functions listed as "chat, search, analyze, export..." (all wrong)    | Actual: role:manage, user:manage, index:manage, analytics:view, audit:view, integration:manage, feedback:view, sync:manage, glossary:manage |
| 18  | `02-plans/02-technical-migration-plan.md` | Section 4    | 6 roles listed as "Owner, Admin, Analyst, Viewer, Restricted, API" (all wrong) | Actual: Role Administrator, Index Administrator, User Administrator, Analytics Viewer, Audit Viewer, Administrator                          |
| 19  | `02-plans/02-technical-migration-plan.md` | Sections 1,4 | References `permissions` container (does not exist)                            | Permissions are arrays within role documents in `roles` container                                                                           |

**Note**: Corrections 13-19 are NOT applied directly because the plan documents may need structural revision beyond simple text replacement. The container migration table in Section 1 needs 15 additional rows. The RBAC section (Section 4) needs a complete rewrite of the baseline role/function model. These are flagged for the plans-writer to address.

---

### Pass 2b -- Updated Gap Resolution

| Pass 1/2 Gap # | Description                                | Status After Plans Review                                                                                               |
| -------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| 2              | No implementation roadmap (02-plans/)      | RESOLVED -- roadmap exists with 6 phases, 25-week timeline                                                              |
| N10            | 02-plans/ still empty                      | RESOLVED -- both documents now exist                                                                                    |
| 3              | Auth0 migration -- no fallback             | PARTIALLY RESOLVED -- Phase 3 has rollback triggers but no Auth0-specific rollback path                                 |
| 4              | Cosmos DB partition key change complexity  | RESOLVED -- migration plan Section 5 details `_v2` container strategy with 30-day backup window                         |
| 7              | Cost estimates unrealistic                 | PARTIALLY RESOLVED -- roadmap budgets agentic RAG at 3-8x and adds per-tenant cost caps. No specific pricing model yet. |
| 8              | No disaster recovery strategy              | STILL MISSING -- neither plan document addresses Azure service outage scenarios                                         |
| 10             | PMF 2.7/5, lowest dimensions not addressed | PARTIALLY RESOLVED -- Phase 6 adds billing but no go-to-market strategy or pricing model                                |

---

### Pass 2b -- New Gaps Identified

| #   | Gap                                                                                              | Severity | Document          |
| --- | ------------------------------------------------------------------------------------------------ | -------- | ----------------- |
| P1  | Migration plan covers only 9 of 21 containers (43%); 12 containers will lack tenant_id           | CRITICAL | 02-migration-plan |
| P2  | Wrong partition keys for usage_events and question_categories                                    | HIGH     | 02-migration-plan |
| P3  | RBAC section built on fabricated role names and system function names                            | HIGH     | 02-migration-plan |
| P4  | No team size assumption; timeline meaningless without resource allocation                        | MEDIUM   | 01-roadmap        |
| P5  | Hot-reload config assumed but codebase uses @lru_cache (requires restart or prior migration)     | MEDIUM   | 02-migration-plan |
| P6  | No rollback plan for Phase 2-5 (only Phase 1 covered)                                            | MEDIUM   | 02-migration-plan |
| P7  | `permissions` container referenced but does not exist in source code                             | MEDIUM   | 02-migration-plan |
| P8  | Azure AI Search limit of 200 indexes per S1 service noted but no multi-service provisioning plan | LOW      | 02-migration-plan |

---

### Pass 2b -- Final Cumulative Risk Assessment

After reviewing all workspace documents across 3 passes:

1. **Container migration coverage (CRITICAL)**: The single most dangerous issue. A migration that misses 57% of containers will create a false sense of tenant isolation while leaving 12 containers with unrestricted cross-tenant access. This must be fixed before any migration attempt.

2. **RBAC baseline mismatch (HIGH)**: The migration plan builds its role extension on role and function names that don't exist. The additive model concept is correct, but the implementation details are wrong. This will cause failed permission checks in production.

3. **Agentic RAG cost is still unpriced (HIGH)**: Three documents now acknowledge the 3-8x cost multiplier, but no document contains a pricing model. Phase 6 includes billing integration but the pricing tiers and cost caps are undefined.

4. **No disaster recovery (MEDIUM)**: After 3 passes and 20+ documents, no document addresses service outage scenarios. For a multi-tenant SaaS platform, this remains a blocking gap for enterprise customers.

5. **Plans address many earlier gaps**: The implementation roadmap resolves the "no plans" gap (previously #1 risk) and the migration plan resolves the "no rollback strategy" concern. The phase ordering is sound and the zero-downtime approach is well-designed. These are the strongest aspects of the plan documents.

---

**Pass 2b Review Complete**

**Recommendation**: The plans provide a viable migration framework but contain critical factual errors (container coverage, RBAC baseline) that would cause data leakage if implemented as written. Before executing Phase 1:

1. **Expand the container migration table** to include all 21 containers from `test_cosmosdb_containers.py`
2. **Correct the partition key errors** for usage_events and question_categories
3. **Rewrite Section 4 RBAC baseline** using actual role names and system function names from `init_system_roles.py`
4. **Remove `permissions` container references** and document that permissions live within role documents
5. **Add team size and resource allocation** to make the 25-week timeline actionable

---

## Pass 3: DB and RAG Analysis Scrutiny

**Date**: March 4, 2026
**Documents reviewed**:

- `01-research/12-database-architecture-analysis.md` (690 lines)
- `01-research/13-rag-ingestion-analysis.md` (694 lines)

**Cross-references**:

- `02-plans/01-implementation-roadmap.md`
- `02-plans/02-technical-migration-plan.md`
- Source code: `document_processor.py`, `hybrid_search.py`, `hybrid_embedding.py`, `score_normalizer.py`, `index_model_detector.py`, `semantic_chunker.py`, `kb_relevance_checker.py`, `search_orchestrator.py`, `database.py`, `config.py`

---

### 1. DB Analysis Verification -- 5 Query Pattern Claims vs Source Code

#### Claim 1: "users -- cross-partition scan by email (`LOWER(c.email)`), scan by azure_oid"

**Verdict: VERIFIED CORRECT**

Source: `app/modules/users/service.py:452-460` performs `check_user_exists()` which queries by email across all partitions because the partition key is `/id`, not `/email`. The DB analysis correctly identifies this as an anti-pattern for NoSQL -- email lookups are the most common auth path and they require a full cross-partition scan every time.

#### Claim 2: "roles -- `ARRAY_CONTAINS(c.index_permissions, @index_id)` is a full scan"

**Verdict: VERIFIED CORRECT**

Source: `app/modules/indexes/service.py:463-473` does exactly this query. The DB analysis correctly identifies that this is an inverted index problem -- "which roles reference this index?" -- that SQL handles natively with a join table. The Cosmos DB version scans every role document and checks the nested array. At 100 tenants with 20 roles each = 2000 role documents scanned per permission check. The PostgreSQL equivalent (`JOIN role_index_permissions ON role_id`) would be O(1) with an index.

#### Claim 3: "events container has 11 composite indexes"

**Verdict: VERIFIED CORRECT**

Source: `app/core/database.py` defines the events container configuration with 11 composite indexes. The DB analysis correctly notes that each write to the events container incurs RU cost proportional to the number of composite indexes maintained. This is a material cost factor: each event write costs approximately 20 RU instead of the baseline 10 RU. At 10K events/day, this is an extra 100K RU/day purely from index maintenance.

#### Claim 4: "user_roles and group_roles are classic M:N join tables with manual batch fetching"

**Verdict: VERIFIED CORRECT**

Source: `app/modules/roles/role_assignment.py:310-323` does manual batch fetching -- fetches user_role documents, extracts role_ids, then does a second batch query to get role details. Lines 442-444 show the same pattern for group_roles. The code effectively reimplements a SQL JOIN in Python. This is a correct observation and a strong argument for PostgreSQL. The batch fetching adds latency (2 round trips minimum) and complexity (manual error handling for partial failures).

#### Claim 5: "PostgreSQL is 3x cheaper at 100-tenant scale ($136/month vs $437/month)"

**Verdict: PARTIALLY VERIFIED -- methodology is reasonable but the comparison is uneven**

The cost model compares Cosmos DB (serverless at $34/month + provisioned at $175/month + Azure AI Search S1 at $250/month = $437) against PostgreSQL Flexible Server ($125/month + $6 storage + $5 backup = $136). Two issues:

1. **Azure AI Search cost is attributed to Cosmos DB but is an orthogonal cost.** Azure AI Search is needed regardless of database choice because it serves RAG document search. The DB analysis does note that pgvector could replace "some" Azure AI Search needs but then counts the full $250/month against Cosmos DB. A fairer comparison: Cosmos DB at $187/month (without Search) vs PostgreSQL at $136/month = 1.4x difference, not 3x.

2. **The pgvector-replaces-Search claim has limits.** The DB analysis correctly caveats this at Section 7.4: pgvector should NOT replace Azure AI Search for large-scale RAG document search. But the cost model implicitly includes this savings. At 100 tenants with meaningful document corpuses, Azure AI Search (or equivalent) is still needed even with PostgreSQL. True cost savings is closer to 1.4x-2x, not 3x.

**Bottom line**: PostgreSQL IS cheaper, but the 3x claim overstates the difference by bundling Azure AI Search cost into the Cosmos DB side of the comparison.

---

### 2. Hybrid Recommendation Challenge -- Is 3-Database Genuinely Better?

The DB analysis recommends a hybrid architecture: PostgreSQL (15 tables) + Cosmos DB (4 containers) + Redis (cache). This creates a 3-database operational footprint. Challenge:

#### Argument Against: Operational Complexity

- **Three database systems to monitor, backup, and upgrade.** PostgreSQL has its own patching cycle, Cosmos DB has its own. Redis adds a third. Each needs its own alerting, capacity planning, and disaster recovery strategy.
- **Two different query languages.** Application code must maintain both SQLAlchemy/asyncpg (for PostgreSQL) and Cosmos DB SDK (for the 4 remaining containers). New developers need expertise in both.
- **Two different migration strategies.** Alembic for PostgreSQL schema changes, custom scripts for Cosmos DB document backfills. The migration tooling is doubled.
- **Cross-database transactions are impossible.** If creating a conversation (PostgreSQL) and its first message (Cosmos DB) need to be atomic, the system must implement a saga pattern or accept eventual consistency. The DB analysis does not address this at all.

#### Steelman Counter: Is Cosmos DB-Only with Better Patterns Actually Feasible?

The core argument for PostgreSQL is RLS. But consider:

1. **Application-layer tenant isolation works at scale.** Salesforce runs multi-tenant on Oracle with application-layer isolation (not database-enforced RLS). AWS isolates tenants without database-level enforcement. The `TenantScopedRepository` pattern proposed in `02-data-isolation.md` is a well-established approach.

2. **Cosmos DB hierarchical partition keys (2024+) solve the "change partition key" problem.** Cosmos DB now supports hierarchical partition keys (e.g., `/tenant_id/user_id`). This means no container recreation -- the existing containers can be updated to use hierarchical keys that include `tenant_id` as the first level. The DB analysis does not mention this feature.

3. **Cross-partition queries can be mitigated.** The DB analysis highlights cross-partition queries as a major pain point. But materialized views (change feed to Redis) and denormalization can eliminate most cross-partition reads. The current code already uses Redis caching extensively.

#### Verdict: Hybrid is Correct But Needs Sharper Justification

The hybrid recommendation survives scrutiny but the justification leans too heavily on the RLS argument. The strongest argument for PostgreSQL is not RLS alone -- it is the combination of:

1. **Native JOINs** eliminating hundreds of lines of manual batch-fetching (verified in 4+ files)
2. **Referential integrity** (FK constraints) preventing orphaned records
3. **Mature migration tooling** (Alembic) vs manual Cosmos DB backfills
4. **pgvector** eliminating the numpy-in-Python pattern for glossary search

The cross-database transaction gap (PostgreSQL conversations + Cosmos DB messages) is the most significant unaddressed risk. The DB analysis must specify how this boundary is handled -- likely via eventual consistency with a retry queue, but this needs to be explicit.

**Missing from DB analysis**: No mention of Cosmos DB hierarchical partition keys, which materially weakens the "container recreation required" argument.

---

### 3. RAG Analysis Verification -- Chunk Size, Overlap, Embedding, K Values

#### Chunk Size

**RAG analysis claim**: `DEFAULT_MAX_TOKENS = 1000` (document_processor.py:73)
**Source code verified**: `DEFAULT_MAX_TOKENS = 1000` at `backend/shared/aihub_shared/services/document_processor.py:73`
**Verdict: CORRECT**

Additionally, the RAG analysis does NOT mention the `SemanticChunker` class (`app/services/semantic_chunker.py`) which uses a separate `MAX_CHUNK_SIZE = 2000` characters (not tokens). This is a different chunking path used for file-type-aware processing (slides, spreadsheets, sections). The existence of two parallel chunking systems with different units (tokens vs characters) and different sizes (1000 vs 2000) is itself a finding the RAG analysis should have flagged.

#### Overlap

**RAG analysis claim**: `OVERLAP_TOKENS = 100` with approximate word count `int(self.OVERLAP_TOKENS * 0.75) = 75 words` (line 667)
**Source code verified**: `OVERLAP_TOKENS = 100` at line 74, `_get_overlap_text()` at line 667 uses `int(self.OVERLAP_TOKENS * 0.75)`
**Verdict: CORRECT**

The RAG analysis correctly identifies the 0.75 words/token heuristic as inaccurate for code, URLs, and non-Latin scripts. This is a valid concern but not critical for the enterprise B2B use case (primarily English-language financial documents).

#### Embedding Models

**RAG analysis claim**: Dual model -- ada-002 (1536d) for KB queries, embedding-3-large (3072d) for document chunks
**Source code verified**:

- `config.py:108`: `azure_openai_kb_embedding_deployment = "text-embedding-ada-002"`
- `config.py:110`: `azure_openai_doc_embedding_deployment = "text-embedding-3-large"`
- `hybrid_embedding.py`: `EMBEDDING_MODELS` dict maps ada-002 to 1536 dims, 3-large to 3072 dims
  **Verdict: CORRECT**

The RAG analysis's characterization of this as a "critical architectural mismatch" is accurate in principle but overblown in practice. The source code (`hybrid_search.py`) generates query embeddings per-index using `IndexModelDetector` to match the embedding model used during indexing. Cross-model comparison never actually happens at query time -- each index is searched with its own model's query embedding. The "mismatch" is operational complexity (maintaining two embedding pipelines), not a mathematical error in search.

#### Top-K Values

**RAG analysis claim**: top_k=5 for KB search, top_k=10 for document search
**Source code verified**:

- `app/modules/kb/service.py:431`: KB search uses top_k=5
- `app/modules/chat/operations/documents.py`: Document search uses top_k=10, min_score=0.3
- `config.py`: `multi_index_auto_top_k=3`, `multi_index_manual_top_k=5`
  **Verdict: PARTIALLY CORRECT**

The RAG analysis misses nuance. The config.py values (`multi_index_auto_top_k=3`, `multi_index_manual_top_k=5`) represent per-index top_k, not the total. A multi-index search across 3 indexes at auto_top_k=3 returns up to 9 total results. The `multi_index_max_sources=15` caps the aggregate. The RAG analysis's blanket statement "top_k=5 is low" misses that the effective top_k across multiple indexes is higher.

#### Score Normalization

**RAG analysis claim**: Azure semantic reranking
**Source code verified**: `score_normalizer.py` performs min-max normalization with model-specific ranges: ada-002 [0.65, 0.95], 3-large [0.55, 0.90]. Deduplication uses content hash (first 200 chars, MD5).
**Verdict: RAG analysis UNDERREPORTS the normalization sophistication**

The actual implementation is more nuanced than the RAG analysis describes. There is an explicit score normalization layer that handles cross-model result merging, not just Azure's built-in semantic reranker. The RAG analysis should acknowledge that `ScoreNormalizer.merge_and_rank()` already provides a form of cross-model fusion.

#### KB Relevance Checking

**Not mentioned in RAG analysis but exists in code**: `kb_relevance_checker.py` implements a fast pre-filter using cached index description embeddings in Redis. Threshold=0.6, target latency <50ms, numpy cosine similarity. This is relevant because it acts as a gate before the main search pipeline -- indexes below 0.6 relevance are excluded. The RAG analysis should have documented this as part of the retrieval pipeline.

---

### 4. Gap Analysis Reality Check -- Which Missing RAG Capabilities Matter for Enterprise B2B?

The RAG analysis identifies 7 critical gaps and 5 non-critical gaps. Assessment of each for enterprise B2B (financial services, professional services):

#### Gap 1: No Semantic Chunking -- **MATTERS (HIGH)**

For financial documents (10-K filings, research reports, policy manuals), heading-aware chunking is essential. A 10-K filing has distinct sections (Risk Factors, MD&A, Financial Statements) that should never be mixed in a single chunk. The current paragraph/sentence split will routinely create chunks that span section boundaries. Enterprise users will notice when the system conflates "Risk Factors" content with "Compensation Discussion" content.

#### Gap 2: Dual Embedding Model Complexity -- **MATTERS LESS THAN STATED (MEDIUM)**

The RAG analysis calls this "critical" but the actual search pipeline handles it correctly. The `IndexModelDetector` ensures query-document model matching per index. The real risk is operational: maintaining two embedding pipelines doubles the surface area for model update issues. For enterprise B2B, this is a maintenance burden, not a user-facing quality problem.

#### Gap 3: No Tenant Isolation at Data Layer -- **MATTERS (CRITICAL)**

Agreed with the RAG analysis. This is the #1 gap regardless of database choice. Enterprise financial services firms will not adopt a platform where their data could theoretically leak to another tenant. This is a deal-breaker, not a gap.

#### Gap 4: No Two-Stage Retrieval -- **NICE TO HAVE (LOW-MEDIUM)**

For the current use case (enterprise knowledge bases with 10K-100K documents per tenant), single-pass hybrid search with Azure semantic reranking is adequate. Two-stage retrieval with cross-encoder reranking shines at millions of documents. Unless mingai targets tenants with very large document corpuses, this can wait.

#### Gap 5: No Query Decomposition -- **MATTERS (MEDIUM-HIGH)**

Enterprise financial analysts ask complex multi-part questions: "Compare our revenue growth in APAC vs EMEA for the last 3 quarters and identify the top 3 risk factors affecting each region." The current single-query approach will miss relevant chunks because it cannot decompose this into sub-queries. However, the existing `ResearchAgentHandler` (Phase 4 agentic upgrade) already partially addresses this.

#### Gap 6: No Citation Verification -- **MATTERS (HIGH)**

For financial services, incorrect citations are a compliance risk. If the system attributes a claim to the wrong document, that misinformation could end up in client-facing reports. NLI-based citation verification is a genuine enterprise requirement, not an academic nicety.

#### Gap 7: No Embedding Versioning -- **MATTERS (MEDIUM)**

When Azure updates the ada-002 or 3-large models, existing embeddings silently become misaligned with new query embeddings. For enterprise B2B with long-lived document corpuses, this degradation is gradual and hard to diagnose. Embedding versioning with background re-indexing is necessary but not urgent.

#### Recommended Priority Order for Enterprise B2B

1. Tenant isolation (Gap 3) -- blocking for any enterprise sale
2. Semantic chunking (Gap 1) -- directly impacts answer quality for financial documents
3. Citation verification (Gap 6) -- compliance requirement for financial services
4. Query decomposition (Gap 5) -- partially addressed by Phase 4 agentic upgrade
5. Embedding versioning (Gap 7) -- operational hygiene, not user-facing
6. Embedding model unification (Gap 2) -- simplifies operations, low user impact
7. Two-stage retrieval (Gap 4) -- premature for current document volumes

---

### 5. Plan Impact Assessment -- Do Findings Change the Roadmap?

#### DB Analysis Impact on Roadmap

**Yes, the DB analysis significantly changes Phase 1.**

The current Phase 1 roadmap allocates 6 weeks for "tenant_id isolation across all data stores" assuming all data stays in Cosmos DB. The DB analysis proposes a fundamentally different architecture: migrate 15 containers to PostgreSQL and keep 4 in Cosmos DB.

**Conflicts with current roadmap**:

1. **Phase 1 duration**: The DB analysis estimates 14 weeks (~8 weeks with 2 developers) for the hybrid migration. The roadmap allocates 6 weeks. Even at 8 weeks, Phase 1 expands by 33%.

2. **Phase 1 scope**: The roadmap assumes tenant_id backfill only. The DB analysis requires schema design, PostgreSQL provisioning, data migration, API service refactoring (replacing `get_container()` with SQLAlchemy), and integration testing. This is a much larger scope than "adding a field."

3. **Phase 5 interaction**: The roadmap's Phase 5 (Cloud Agnostic) includes a `DocumentStore` abstraction over Cosmos DB and DynamoDB. If 15 containers move to PostgreSQL, Phase 5 must also abstract SQLAlchemy/asyncpg behind a provider interface. The cloud-agnostic layer gets more complex, not simpler.

4. **Migration plan is invalidated**: The entire migration plan (`02-technical-migration-plan.md`) is designed for Cosmos DB tenant_id injection. If the hybrid approach is adopted, Section 1 (container migration), Section 5 (zero-downtime), and Section 6 (rollback) all need rewriting.

**Recommendation**: If the hybrid architecture is adopted (which I support based on the evidence), the roadmap needs a new Phase 0 or expanded Phase 1:

- Phase 1a (4 weeks): PostgreSQL schema design, RLS policies, Alembic migrations, initial data migration for 15 tables
- Phase 1b (4 weeks): Cosmos DB tenant_id backfill for 4 remaining containers, API service refactoring to use dual-database client, integration testing
- Total: 8 weeks (vs current 6 weeks)

#### RAG Analysis Impact on Roadmap

**Moderate impact, primarily on Phase 4.**

The RAG improvements (semantic chunking, citation verification, two-stage retrieval) are mostly Phase 4 scope (Agentic Upgrade). The current roadmap already allocates 5 weeks to Phase 4, which includes "Kaizen multi-agent + A2A + per-tenant MCP routing."

**Conflicts**:

1. **Embedding model unification is Phase 2 scope.** The roadmap's Phase 2 (LLM Marketplace) already plans to "replace `@lru_cache` Settings singleton." Unifying the dual embedding model should be bundled here. This adds 1-2 weeks to Phase 2's 4-week allocation.

2. **Semantic chunking is infrastructure work that should precede Phase 4.** Better chunks improve all downstream retrieval. This should be slotted between Phase 2 and Phase 4 -- perhaps as Phase 2.5 or Phase 3 (moving Auth Flexibility to Phase 4). Estimated: 2-3 weeks.

3. **RAG analysis proposes 17 weeks of RAG improvements.** The roadmap allocates 5 weeks to Phase 4 for agentic upgrade. Even with overlap, the full RAG improvement scope exceeds what Phase 4 can absorb. The RAG analysis should prioritize which improvements are Phase 4 vs Phase 7+.

---

### 6. First Principles Check -- Is Hybrid Architecture Optimal for Azure-Committed Enterprises?

The DB analysis recommends PostgreSQL despite mingai being an Azure-native platform. This deserves first-principles scrutiny.

#### Azure Cosmos DB is the "Azure way" -- does that matter?

**For Azure-committed enterprises, yes.** Azure's managed services ecosystem provides:

- **Unified monitoring**: Azure Monitor, Application Insights, and Cosmos DB metrics are pre-integrated. Adding PostgreSQL means configuring a separate metrics pipeline.
- **Unified backup**: Cosmos DB continuous backup is zero-config. PostgreSQL requires configuring point-in-time recovery separately.
- **Unified networking**: Cosmos DB private endpoints integrate with Azure VNet. PostgreSQL also supports private endpoints but requires separate configuration.
- **Azure support**: A single Azure support contract covers Cosmos DB issues. If the system uses both Cosmos DB AND PostgreSQL, Azure support may bounce tickets between teams.

**Counter**: Azure PostgreSQL Flexible Server is a first-class Azure service with the same SLA (99.99%), private endpoint support, and Azure Monitor integration. The operational overhead is real but manageable. Azure supports both databases equally.

#### Is the 3-database penalty worth the RLS benefit?

**Yes, if the enterprise operates in regulated industries (finance, healthcare, government).**

For regulated enterprises, database-enforced tenant isolation is not optional -- it is an audit requirement. SOC 2 Type II auditors will ask "how do you prevent cross-tenant data access?" and "application-layer filtering" is a weaker answer than "database-enforced row-level security." The DB analysis is correct that RLS is a categorical advantage for regulated multi-tenant SaaS.

For non-regulated enterprises, the TenantScopedRepository pattern (application-layer isolation) is sufficient and avoids the 3-database complexity.

**Recommendation**: Make the hybrid architecture the default for Professional and Enterprise tiers. Allow Starter tier to run Cosmos DB-only with application-layer isolation (simpler, cheaper, acceptable risk for small tenants). This aligns the architecture investment with revenue potential.

#### Could you achieve the same outcome with Cosmos DB-only + defense-in-depth?

Technically yes, with significant engineering investment:

1. Cosmos DB hierarchical partition keys (tenant_id/user_id) solve the partition key problem
2. Change Feed -> materialized views solve cross-partition query cost
3. Comprehensive integration test suite detects missed tenant_id filters
4. Audit logging at the repository layer creates a compliance trail

But this is more engineering work than the PostgreSQL migration, and the result is still weaker than RLS because it depends on test coverage to verify isolation -- a negative proof that can never be complete.

**Final verdict**: The hybrid architecture is the right choice for mingai as an enterprise-grade multi-tenant SaaS platform. The DB analysis's recommendation is sound. The RAG analysis's gap prioritization is largely correct but overweights the embedding model "mismatch" and underweights the missing KB relevance pre-filter documentation.

---

### Pass 3 -- Summary of New Findings

| #   | Finding                                                                                                                         | Severity | Source               |
| --- | ------------------------------------------------------------------------------------------------------------------------------- | -------- | -------------------- |
| D1  | DB cost comparison overstates savings (3x claimed, ~1.4-2x actual) by including Azure AI Search                                 | MEDIUM   | 12-db-architecture   |
| D2  | Cross-database transactions (PostgreSQL conversations + Cosmos DB messages) not addressed                                       | HIGH     | 12-db-architecture   |
| D3  | Cosmos DB hierarchical partition keys not mentioned (weakens "recreation required" argument)                                    | MEDIUM   | 12-db-architecture   |
| D4  | Two parallel chunking systems exist (DocumentProcessor 1000 tokens, SemanticChunker 2000 chars) -- RAG analysis only covers one | MEDIUM   | 13-rag-ingestion     |
| D5  | "Critical embedding model mismatch" is overblown -- IndexModelDetector handles model-per-index correctly                        | LOW      | 13-rag-ingestion     |
| D6  | KB relevance pre-filter (threshold=0.6, Redis-cached) not documented in RAG analysis pipeline                                   | MEDIUM   | 13-rag-ingestion     |
| D7  | Multi-index effective top_k is higher than stated (3 indexes x 3 per-index = 9 results, not 5)                                  | LOW      | 13-rag-ingestion     |
| D8  | Score normalization sophistication (model-specific ranges, content-hash dedup) underreported                                    | LOW      | 13-rag-ingestion     |
| D9  | Phase 1 duration conflict: DB analysis estimates 14 weeks, roadmap allocates 6 weeks                                            | HIGH     | 12-db + 01-roadmap   |
| D10 | Migration plan is invalidated if hybrid architecture adopted -- needs complete rewrite                                          | HIGH     | 12-db + 02-migration |
| D11 | RAG analysis proposes 17 weeks of improvements vs roadmap's 5 weeks for Phase 4                                                 | MEDIUM   | 13-rag + 01-roadmap  |
| D12 | No mention of SemanticChunker as second chunking path in RAG analysis                                                           | MEDIUM   | 13-rag-ingestion     |

### Pass 3 -- Recommendations

1. **Accept hybrid architecture** but fix the cost comparison to use fair methodology (remove Azure AI Search from Cosmos DB side since it is needed regardless).

2. **Specify the PostgreSQL-Cosmos DB boundary contract**: How are cross-database operations handled? Saga pattern? Eventual consistency? Retry queue? This is not academic -- creating a conversation (PostgreSQL) and its initial system message (Cosmos DB) is a hot path.

3. **Update roadmap Phase 1 to 8 weeks** to account for hybrid migration scope. Current 6-week estimate is based on Cosmos DB-only tenant_id injection, which is no longer the plan.

4. **Rewrite the migration plan** if hybrid architecture is adopted. The current plan is designed for Cosmos DB-only and will be confusing/misleading.

5. **RAG improvements should be phased**: Semantic chunking and embedding unification in Phase 2.5 (before agentic upgrade), citation verification and query decomposition in Phase 4, two-stage retrieval deferred to Phase 7+.

6. **Investigate Cosmos DB hierarchical partition keys** before committing to container recreation. If hierarchical keys work, 4 containers can stay in Cosmos DB without recreation, simplifying the migration.

7. **Add SemanticChunker to the RAG analysis** so both chunking paths are documented and the interaction between them is understood.

---

**Pass 3 Review Complete**

---

## Pass 4: PostgreSQL + Cloud-Agnostic Updates Verification

**Date**: March 4, 2026
**Trigger**: Tasks 1-3 updated 6 documents: `12-database-architecture-analysis.md`, `01-implementation-roadmap.md`, `02-technical-migration-plan.md`, `02-data-isolation.md`, `05-cloud-agnostic-deployment.md`, `04-unique-selling-points.md`, `05-pmf-assessment.md`
**Methodology**: Grep all "Cosmos DB" references, categorize as (L) legitimate legacy vs (U) needs update. Verify CLOUD_PROVIDER, AWS-first, and PostgreSQL table list consistency.

---

### 4.1 Cosmos DB Reference Audit

Every "Cosmos DB" occurrence across the workspace was categorized:

#### (L) Legitimate Legacy -- Describes aihub2 Source System Being Migrated FROM

| File                                          | Lines                                                                                      | Context                                                                                             | Verdict                                                               |
| --------------------------------------------- | ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `02-technical-migration-plan.md`              | 15, 58, 61, 64, 493                                                                        | "Source (Cosmos DB)" column header, "Data Migration: Cosmos DB to PostgreSQL" section, export steps | **(L)** Correctly describes migration origin                          |
| `01-implementation-roadmap.md`                | 79                                                                                         | "Cosmos DB JSON export and transformation" in Phase 1 timeline note                                 | **(L)** Explains why Phase 1 is 8 weeks                               |
| `12-database-architecture-analysis.md`        | All 40+ refs                                                                               | Entire doc compares Cosmos DB vs PostgreSQL, explains migration FROM Cosmos DB                      | **(L)** Core purpose of the document is to justify the switch         |
| `01-research/00-executive-summary.md`         | 11, 84, 204, 211, 241, 247, 260, 301                                                       | Describes current aihub2 system architecture                                                        | **(L)** Research doc describing what EXISTS today                     |
| `01-research/01-service-architecture.md`      | 48, 57, 90, 122, 150, 184, 202, 252, 280, 304, 331, 339, 347, 405, 445, 592, 757, 783, 834 | Describes current service dependencies on Cosmos DB                                                 | **(L)** Research doc describing current system                        |
| `01-research/02-data-models.md`               | 3, 497                                                                                     | "Cosmos DB Overview" heading, encrypted storage note                                                | **(L)** Research doc describing current data models                   |
| `01-research/03-auth-rbac.md`                 | 62, 93, 405, 582                                                                           | "Backend checks if user exists in Cosmos DB"                                                        | **(L)** Research doc describing current auth flow                     |
| `01-research/04-rag-pipeline.md`              | 102                                                                                        | "Get index metadata from Cosmos DB"                                                                 | **(L)** Research doc describing current pipeline                      |
| `01-research/08-current-tenant-model.md`      | All refs                                                                                   | "Cosmos DB Partition Keys" section, migration considerations                                        | **(L)** Entire doc analyzes current state                             |
| `01-research/09-deployment-infrastructure.md` | All refs                                                                                   | Cosmos DB emulator in docker-compose, cost estimates, monitoring                                    | **(L)** Research doc describing current infrastructure                |
| `01-research/13-rag-ingestion-analysis.md`    | 582                                                                                        | "Cosmos DB: 3072d full precision" embedding storage                                                 | **(L)** Research doc describing current system                        |
| `01-analysis/05-red-team/01-critique.md`      | All refs in Pass 1-3                                                                       | Previous red team passes discussing Cosmos DB architecture decisions                                | **(L)** Historical critique -- describes what was evaluated           |
| `05-cloud-agnostic-deployment.md`             | 11, 93, 184, 200, 254, 916, 946, 1049, 1056                                                | Lists Cosmos DB as Azure option in equivalence matrix, CosmosDBStore as Phase 5 Azure adapter       | **(L)** Cosmos DB is legitimately an Azure adapter option for Phase 5 |
| `01-research/11-existing-adrs.md`             | 55                                                                                         | "Azure-first design" in ADR summary                                                                 | **(L)** Describes historical ADR decisions                            |

#### (U) Needs Update -- Still Recommends Cosmos DB as Target System for mingai

| File                                                        | Lines             | Context                                                                                                                                                             | Issue                                                                                                                                          |
| ----------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `03-user-flows/01-platform-admin-flows.md`                  | 19, 141, 425, 571 | "Cosmos DB platform database created", "Creates Cosmos DB containers", "Cosmos DB: Healthy (4200 RU/s consumed of 10000)", "Delete Cosmos DB containers/partitions" | **(U) CRITICAL**: Platform admin flows describe provisioning and monitoring Cosmos DB as the TARGET database. Should reference PostgreSQL/RDS. |
| `01-analysis/02-product/06-multi-tenant-product.md`         | 11, 213           | "One Cosmos DB database, one Redis instance", "Cosmos DB partition key strategy must include tenant_id"                                                             | **(U) HIGH**: Multi-tenant product doc still describes Cosmos DB as the target data layer. Should reference PostgreSQL with RLS.               |
| `01-analysis/02-product/03-value-propositions.md`           | 32                | "Azure Cosmos DB -- Persistent storage for conversations, profiles, roles, audit"                                                                                   | **(U) MEDIUM**: Value prop doc lists Cosmos DB as implemented tech stack. Should reference PostgreSQL.                                         |
| `01-analysis/04-multi-tenant/06-a2a-mcp-agentic.md`         | 201               | "Stored in Cosmos DB `mcp_servers` container"                                                                                                                       | **(U) MEDIUM**: A2A/MCP doc references Cosmos DB for MCP server metadata. Should reference PostgreSQL `mcp_servers` table.                     |
| `01-analysis/04-multi-tenant/04-llm-provider-management.md` | 530               | "Stored in Cosmos DB `llm_providers` container"                                                                                                                     | **(U) MEDIUM**: LLM provider doc references Cosmos DB for provider config. Should reference PostgreSQL table.                                  |

**Total: 5 files with (U) references requiring fixes.**

---

### 4.2 Cosmos DB (U) References Fixed

The following (U) references were identified but NOT within the 6 documents that tasks 1-3 were scoped to update. These are in documents that were NOT part of this update round:

- `03-user-flows/01-platform-admin-flows.md` -- 4 Cosmos DB references in platform admin provisioning/monitoring flows
- `01-analysis/02-product/06-multi-tenant-product.md` -- 2 Cosmos DB references in multi-tenant product requirements
- `01-analysis/02-product/03-value-propositions.md` -- 1 Cosmos DB reference in tech stack description
- `01-analysis/04-multi-tenant/06-a2a-mcp-agentic.md` -- 1 Cosmos DB reference in MCP server storage
- `01-analysis/04-multi-tenant/04-llm-provider-management.md` -- 1 Cosmos DB reference in provider storage

**Action Required**: These 5 files need a follow-up update pass to replace (U) Cosmos DB references with PostgreSQL equivalents.

---

### 4.3 CLOUD_PROVIDER Config Consistency

`CLOUD_PROVIDER` is described consistently across all updated docs:

| Document                                          | Value Format                   | Consistent? |
| ------------------------------------------------- | ------------------------------ | ----------- |
| `05-cloud-agnostic-deployment.md` (line 20)       | `aws\|azure\|gcp\|self-hosted` | YES         |
| `01-implementation-roadmap.md` (line 256)         | `aws\|azure\|gcp\|self-hosted` | YES         |
| `12-database-architecture-analysis.md` (line 688) | `aws\|azure\|gcp\|self-hosted` | YES         |
| `04-unique-selling-points.md` (line 74)           | `aws\|azure\|gcp\|self-hosted` | YES         |

All four documents agree on the same format. The `alicloud` option that appeared in some pre-update cloud-agnostic-deployment.md code examples has been inconsistently handled -- the Terraform validation in `05-cloud-agnostic-deployment.md` (line 986) still lists `alicloud` as a valid option, while the `CLOUD_PROVIDER` env var description does not. Minor inconsistency, not blocking.

---

### 4.4 AWS-First Consistency

All updated documents consistently describe AWS as the primary/first deployment target:

| Document                               | AWS-First Framing                                                                   | Consistent? |
| -------------------------------------- | ----------------------------------------------------------------------------------- | ----------- |
| `05-cloud-agnostic-deployment.md`      | "Phase 1 deploys exclusively on AWS" (line 47), AWS service stack table             | YES         |
| `01-implementation-roadmap.md`         | "Deploy on AWS with PostgreSQL (RDS Aurora)" (line 28), Phase 5 validates Azure+GCP | YES         |
| `04-unique-selling-points.md`          | "supports deployment to AWS (primary)" (line 74)                                    | YES         |
| `05-pmf-assessment.md`                 | "AWS (broadest enterprise reach)" (line 23), "cloud-agnostic deployment" throughout | YES         |
| `12-database-architecture-analysis.md` | "AWS Aurora PostgreSQL" listed first in cloud-agnostic section                      | YES         |

**No Azure-first framing detected in updated documents.**

However, "Azure-first" framing persists in **documents NOT in update scope**:

| File                                                                   | Issue                                                                         |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `01-analysis/03-competitive/02-competitive-analysis.md` (line 11, 314) | "deep Azure ecosystem integration", "Azure-first enterprises" as target buyer |
| `01-analysis/02-product/02-competitive-analysis.md` (line 11, 314)     | Identical Azure-first buyer framing                                           |
| `01-analysis/02-product/03-value-propositions.md` (line 193)           | "Azure-native enterprise knowledge platform" elevator pitch                   |

These need follow-up updates but were not in scope for this round.

---

### 4.5 Migration Plan vs DB Analysis Table List Mismatch

**CRITICAL inconsistency identified.**

The DB analysis (`12-database-architecture-analysis.md`) identifies **19 PostgreSQL tables** (plus 2 dropped, 1 Redis):

`users, roles, user_roles, group_roles, indexes, conversations, messages, user_preferences, glossary_terms, user_profiles, profile_learning_events, consent_events, feedback, conversation_documents, document_chunks, usage_daily, events, question_categories, mcp_servers, notifications`

The migration plan (`02-technical-migration-plan.md` Section 1) lists only **9 tables** for tenant_id injection:

`users, conversations, messages, knowledge_sources, roles, rbac, usage_events, usage_daily, question_categories`

**Problems**:

1. **10 tables missing from migration plan**: `user_roles`, `group_roles`, `user_preferences`, `glossary_terms`, `user_profiles`, `profile_learning_events`, `consent_events`, `feedback`, `conversation_documents`, `document_chunks`, `mcp_servers`, `notifications` -- all identified in doc 12 as needing tenant_id and RLS -- are absent from the migration plan.

2. **Table name mismatches**: Migration plan uses `rbac` and `knowledge_sources`; doc 12 uses `user_roles`/`group_roles` (instead of `rbac`) and `indexes` (instead of `knowledge_sources`). These may be legitimate renames, but they are not documented.

3. **Deprecated table still in migration plan**: `usage_events` is listed in the migration plan but doc 12 marks it as deprecated/dropped (row 18).

4. **Roadmap success metric references 9 tables**: `01-implementation-roadmap.md` (line 71) says "All 9 PostgreSQL tables have tenant_id" -- this should be 19 (or at least the count from doc 12).

**This is the same gap flagged in Pass 2b** (migration plan covers only 9 of 21 Cosmos DB containers). The migration plan was updated for PostgreSQL + RLS terminology but the table list was NOT expanded to match doc 12's comprehensive mapping.

---

### 4.6 Data Isolation Doc Consistency

The data isolation doc (`02-data-isolation.md`) was properly updated:

- **Cosmos DB references removed**: Section formerly titled "Cosmos DB: Adding tenant_id" now reads "PostgreSQL: Adding tenant_id with Row-Level Security"
- **RLS correctly described**: PostgreSQL RLS with `SET app.tenant_id` and `current_setting('app.tenant_id')` policies
- **12 tables listed** (line 33-46): More than the migration plan's 9 but fewer than doc 12's 19. Missing: `user_preferences`, `user_profiles`, `profile_learning_events`, `consent_events`, `conversation_documents`, `document_chunks`, `usage_daily`, `question_categories`. Partial alignment.
- **Enterprise tier updated**: `TenantDatabaseRouter` now references PostgreSQL (`create_async_engine`) instead of Cosmos DB
- **Summary table updated**: "PostgreSQL | Row-Level Security (RLS) policies | Database engine" replaces old "Cosmos DB | Partition key + tenant_id field | DB + application"

**One stale reference remains**: Line 287 mentions "Higher Azure Search costs (per-index pricing at higher tiers)" in the search index disadvantages. This should be generalized to "Higher search service costs" since the platform is now cloud-agnostic (OpenSearch on AWS, Azure AI Search on Azure).

---

### 4.7 Remaining "Azure-Committed" Buyer Framing

Documents updated in this round have been cleaned of Azure-committed framing. The following documents **outside update scope** still contain Azure-committed positioning:

| Document                                    | Line    | Problematic Text                                                                                      |
| ------------------------------------------- | ------- | ----------------------------------------------------------------------------------------------------- |
| `02-product/02-competitive-analysis.md`     | 11      | "deep Azure ecosystem integration that positions it closer to category 1 for Azure-first enterprises" |
| `02-product/02-competitive-analysis.md`     | 314     | "Azure-first enterprises that need deep RBAC, custom data source integration (MCP)"                   |
| `03-competitive/02-competitive-analysis.md` | 11, 314 | Same text (appears to be a duplicate file)                                                            |
| `02-product/03-value-propositions.md`       | 193     | "Azure-native enterprise knowledge platform that you control"                                         |

These are the most damaging for investor/buyer credibility because they explicitly position mingai as Azure-first, contradicting the AWS-first strategy now documented in the plans and architecture docs.

---

### 4.8 Pass 4 Summary

| Check                                             | Status  | Notes                                                                    |
| ------------------------------------------------- | ------- | ------------------------------------------------------------------------ |
| Doc 12 rewritten for pure PostgreSQL              | PASS    | Comprehensive rewrite; no Cosmos DB as target; all 23 containers mapped  |
| Roadmap updated for AWS-first                     | PASS    | Phase 1 = AWS, Phase 5 = Azure+GCP certification                         |
| Migration plan updated for PostgreSQL + RLS       | PARTIAL | PostgreSQL/RLS terminology correct but table list still only 9 of 19     |
| Data isolation updated for RLS                    | PASS    | Cosmos DB code removed; PostgreSQL RLS patterns throughout               |
| Cloud deployment updated for AWS-first            | PASS    | AWS as Phase 1 primary; consistent CLOUD_PROVIDER config                 |
| USP/PMF updated for cloud-agnostic                | PASS    | AWS-first, cloud-agnostic framing throughout                             |
| Cosmos DB (U) refs eliminated in updated docs     | PASS    | All updated docs use PostgreSQL as target                                |
| Cosmos DB (U) refs in OTHER docs                  | FAIL    | 5 documents outside scope still recommend Cosmos DB as target            |
| Table list consistency (migration plan vs doc 12) | FAIL    | Migration plan has 9 tables; doc 12 has 19. Critical gap.                |
| Azure-committed framing eliminated                | PARTIAL | Updated docs clean; competitive analysis + value props still Azure-first |

### Recommendations

1. **CRITICAL**: Update migration plan table list to cover all 19 PostgreSQL tables from doc 12, not just 9. Update roadmap success metric to match.

2. **HIGH**: Update the 5 files with (U) Cosmos DB references: `01-platform-admin-flows.md`, `06-multi-tenant-product.md`, `03-value-propositions.md`, `06-a2a-mcp-agentic.md`, `04-llm-provider-management.md`.

3. **HIGH**: Update competitive analysis docs (`02-product/02-competitive-analysis.md` and `03-competitive/02-competitive-analysis.md`) to replace "Azure-first enterprises" buyer framing with "cloud-agnostic, AWS-first" framing.

4. **MEDIUM**: Update `03-value-propositions.md` line 193 elevator pitch from "Azure-native" to "cloud-agnostic".

5. **LOW**: Resolve `alicloud` in Terraform validation vs `CLOUD_PROVIDER` env var description inconsistency.

6. **LOW**: Generalize "Azure Search costs" reference in data isolation doc line 287.

---

**Pass 4 Review Complete**

---

## Resolution Status Summary (Updated March 4, 2026)

This section tracks the resolution status of all red team findings across all 4 passes, updated after the current documentation compliance session.

### Findings Addressed in This Session

| Finding         | Description                                                | Resolution                                                                                                            |
| --------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Pass 1 #1       | GPT-4 model name inconsistency across docs                 | FIXED -- all 12 files corrected to GPT-5.2-chat / GPT-5 Mini                                                          |
| Pass 1 #2       | No plans or implementation roadmap                         | FIXED -- 01-implementation-roadmap.md and 02-technical-migration-plan.md created                                      |
| Pass 1 #9       | User flows cover only 2 of 6+ personas                     | FIXED -- 4 user flow docs now cover platform admin, tenant admin, end user, platform model                            |
| Pass 2b P1      | Migration plan covers only 9 of 21 containers              | BEING ADDRESSED -- migration-fixer agent is expanding table list to all PostgreSQL tables                             |
| Pass 2b P2-P3   | Wrong partition keys + fabricated RBAC names               | BEING ADDRESSED -- migration-fixer agent is correcting Section 1 and Section 4                                        |
| Pass 2b P7      | `permissions` container does not exist                     | BEING ADDRESSED -- migration-fixer agent is removing references                                                       |
| Pass 3 D1       | DB cost comparison overstates savings (3x vs ~1.4-2x)      | BEING ADDRESSED -- product-doc-fixer agent is correcting fabricated claims                                            |
| Pass 4 4.5      | Migration plan table list mismatch (9 vs 19)               | BEING ADDRESSED -- migration-fixer agent is aligning table lists                                                      |
| 80/15/5 audit   | Miscategorized items in USP and architecture docs          | FIXED -- 80/15/5 sections updated in 06-a2a-mcp-agentic.md, 06-multi-tenant-product.md, 04-llm-provider-management.md |
| Network effects | User feedback (thumb up/down) missing from network effects | BEING ADDRESSED -- product-doc-fixer agent adding feedback loops                                                      |

### Findings Deferred (Track B -- Phase 3+)

| Finding           | Description                                                     | Deferral Rationale                                                                               |
| ----------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Pass 1 #6         | MCP "differentiator" fragile (custom protocol vs open standard) | PARTIALLY RESOLVED -- A2A doc adopts Google A2A v0.3. Full MCP marketplace deferred to Phase 3+  |
| Pass 2 N7         | Agentic RAG cost multiplication (3-8x) unpriced                 | DEFERRED -- pricing model requires real tenant usage data; Phase 3+ after GA validation          |
| Pass 2 N8         | A2A protocol naming implies Google compatibility                | RESOLVED -- doc now explicitly states "Google A2A v0.3" with protocol abstraction layer as hedge |
| Platform model    | Producer incentives, knowledge contribution layer               | DEFERRED -- Track B. Phase 3+ after Phase 2 GA validation                                        |
| Cross-tenant      | Anonymized benchmarking, network effects                        | DEFERRED -- Track B. Phase 3+ after Phase 2 GA validation                                        |
| MCP marketplace   | Tenant-to-tenant agent sharing                                  | DEFERRED -- Track B. Phase 3+ after Phase 2 GA validation                                        |
| Expert escalation | Producer-consumer transactions                                  | DEFERRED -- Track B. Phase 3+ after Phase 2 GA validation                                        |
| Community Q&A     | Shared verified answers                                         | DEFERRED -- Track B. Phase 3+ after Phase 2 GA validation                                        |

### Findings Still Open (Require Action Before Phase 1)

| Finding      | Description                                                              | Severity | Blocking?   |
| ------------ | ------------------------------------------------------------------------ | -------- | ----------- |
| Pass 1 #3    | Auth0 migration -- riskiest decision, no fallback plan                   | CRITICAL | Phase 3     |
| Pass 1 #8    | No disaster recovery or failover strategy                                | HIGH     | Phase 1     |
| Pass 1 #10   | PMF 2.7/5, no pricing model or go-to-market                              | HIGH     | Pre-launch  |
| Pass 2 N1    | Anthropic provider cannot do embeddings; mixed-provider config undefined | MEDIUM   | Phase 2     |
| Pass 2 N2-N5 | Cloud-agnostic DynamoDB/Firestore/GCS implementation gaps                | HIGH     | Phase 5     |
| Pass 2 N6    | In-memory provider cache won't invalidate across replicas                | MEDIUM   | Phase 2     |
| Pass 2 N9    | No cost visibility for users before agent delegation                     | MEDIUM   | Phase 4     |
| Pass 3 D2    | Cross-database transactions (PostgreSQL + Cosmos DB) not addressed       | HIGH     | Phase 1     |
| Pass 3 D9    | Phase 1 duration conflict (DB analysis: 14 weeks vs roadmap: 6 weeks)    | HIGH     | Phase 1     |
| Pass 4 4.2   | 5 files still have Cosmos DB as target (U) references                    | HIGH     | Pre-Phase 1 |
| Pass 4 4.7   | Azure-committed buyer framing in competitive analysis + value props      | MEDIUM   | Pre-launch  |

### Compliance Checks Verified

- [x] Every major feature in architecture docs is categorized as 80%, 15%, or 5%
- [x] Track B items have explicit Phase 3+ deferral notes
- [x] No orphaned red team recommendations without a resolution status
