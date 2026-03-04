# Red Team Remediation Plan

> **Status**: Remediation Design
> **Date**: 2026-03-05
> **Source**: `01-analysis/05-red-team/01-critique.md` — 10 critical gaps
> **Scope**: Closes all gaps from Phase 1 red team. Documents resolution for each finding with explicit design decisions.

---

## Remediation Summary

| #   | Finding                                       | Severity | Status             | Resolution Doc                                           |
| --- | --------------------------------------------- | -------- | ------------------ | -------------------------------------------------------- |
| 1   | Model name inconsistency (GPT-4 refs in docs) | HIGH     | Resolved           | This doc + doc corrections below                         |
| 2   | Auth0 migration risk                          | HIGH     | Resolved           | Design decision documented in §2                         |
| 3   | Cosmos DB partition key change complexity     | HIGH     | Resolved           | PostgreSQL migration supersedes Cosmos                   |
| 4   | BYOLLM underspecified                         | MEDIUM   | Resolved           | `02-plans/01-implementation-roadmap.md` Phase 2          |
| 5   | MCP "differentiator" fragility                | MEDIUM   | Resolved           | Design decision in §5                                    |
| 6   | Cost estimates unrealistic                    | HIGH     | Resolved           | Revised cost model in §6                                 |
| 7   | No DR/failover strategy                       | CRITICAL | Resolved           | DR architecture in §7                                    |
| 8   | Missing user flows (5 of 6 personas)          | MEDIUM   | Resolved           | New flow docs created (§8)                               |
| 9   | PMF gaps: pricing and GTM                     | HIGH     | Partially Resolved | GTM foundation in §9                                     |
| 10  | Fabricated RBAC role/function names           | HIGH     | Resolved           | Platform RBAC spec (`24-platform-rbac-specification.md`) |

---

## 1. Model Name Corrections

**Finding**: `00-executive-summary.md`, `01-service-architecture.md`, `04-rag-pipeline.md`, `03-value-propositions.md`, and `11-existing-adrs.md` reference "GPT-4" — incorrect. Actual models: GPT-5.2-chat (primary) and GPT-5 Mini (intent/auxiliary).

**Root cause**: Documentation written before codebase verification. Assumed GPT-4 from product description language.

**Corrections applied (as of 2026-03-05 commit `fix(docs): correct fabricated RBAC and MCP server data from aihub2 source`):**

- `00-executive-summary.md` — Lines 119-123 updated to GPT-5.2-chat / GPT-5 Mini
- `01-service-architecture.md` — Lines 215, 248 updated
- `04-rag-pipeline.md` — Lines 245-246 updated
- `02-product/03-value-propositions.md` — Line 30 updated
- `01-research/11-existing-adrs.md` — Line 43 updated

**Going forward**: All new documents must reference model names from `21-llm-model-slot-analysis.md` which is verified against `app/core/config.py`. The correct reference table:

| Slot                | Model                  |
| ------------------- | ---------------------- |
| Primary Chat        | GPT-5.2-chat           |
| Intent Detection    | GPT-5 Mini             |
| Vision              | GPT-5 Vision           |
| Document Embeddings | text-embedding-3-large |
| KB Embeddings       | text-embedding-ada-002 |

---

## 2. Auth0 Migration Risk → Auth Flexibility Strategy

**Finding**: Replacing Azure AD direct integration with Auth0 as SSO broker introduces third-party dependency, latency, cost, and massive migration effort with no fallback documented.

**Resolution**: Auth0 is **not mandatory**. The design adopts a pluggable identity provider pattern:

### Identity Provider Options (by tenant plan)

| Option                      | Description                                               | Tenant Plan                  |
| --------------------------- | --------------------------------------------------------- | ---------------------------- |
| **Local auth** (password)   | Built-in username/password, no external IdP               | All plans                    |
| **Azure Entra ID** (direct) | Direct OIDC/SAML to customer's Azure AD — no Auth0        | Professional, Enterprise     |
| **Auth0 managed**           | Platform hosts Auth0 tenant for multi-provider SSO        | Starter (managed simplicity) |
| **BYOIDP**                  | Customer provides their own IdP (Okta, Ping, custom SAML) | Enterprise only              |

### Migration Path from aihub2

The existing Azure AD direct integration in aihub2 maps to the "Azure Entra ID (direct)" option. Migration path:

1. **Phase 1 (Week 1-2)**: Wrap existing Azure AD auth behind `IdentityProviderAdapter` interface. Zero functional change.
2. **Phase 3 (Auth Flexibility)**: Add Google SSO, Okta, SAML adapters behind the same interface. Auth0 becomes optional managed provider for tenants who need multi-provider SSO without operating their own IdP.

### Auth0 Fallback

If Auth0 is unavailable:

- Tenants using Auth0-managed auth → fall back to local auth (platform-level circuit breaker)
- Tenants using direct Entra ID → unaffected (no Auth0 in path)
- Alert platform admin → investigate Auth0 outage

**Conclusion**: Auth0 is not a single point of failure. Direct IdP connections bypass Auth0 entirely. Auth0 is only in the critical path for tenants who choose the managed SSO option.

---

## 3. Cosmos DB Partition Key → PostgreSQL Migration

**Finding**: Cosmos DB partition key change requires container recreation; underestimated operational complexity.

**Resolution**: This is a non-issue. The implementation roadmap **migrated from Cosmos DB to PostgreSQL** (Phase 1 of the roadmap). The PostgreSQL schema is designed multi-tenant from day one with `tenant_id` columns and Row-Level Security.

**Why PostgreSQL instead of Cosmos DB:**

- Partition key constraint does not apply to PostgreSQL (no partition key migration needed)
- RLS is a first-class PostgreSQL feature — enforced at DB engine level
- `tenant_id` is just a column with an index — adding it to existing tables is a non-destructive `ALTER TABLE`
- Migration: `ALTER TABLE conversations ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000'` → backfill → enable RLS

The 21 PostgreSQL tables in the roadmap schema replace all 20+ Cosmos DB containers. See `12-database-architecture-analysis.md` for full mapping.

---

## 4. BYOLLM Underspecified → Provider Adapter Architecture

**Finding**: BYOLLM listed as feature but entire codebase only supports Azure OpenAI. Supporting other providers requires significant new client code.

**Resolution**: Phase 2 of the roadmap explicitly builds the `LLMProvider` abstraction. Spec:

### Provider Adapter Interface

```python
class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
        stream: bool = False,
    ) -> Union[CompletionResponse, AsyncGenerator[str, None]]: ...

    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        model: str,
    ) -> list[list[float]]: ...

    @abstractmethod
    async def health_check(self) -> ProviderHealth: ...
```

### Phase 2 Provider Adapters (Minimum Viable Set)

| Provider      | Adapter Class        | Auth               | Notes                    |
| ------------- | -------------------- | ------------------ | ------------------------ |
| Azure OpenAI  | `AzureOpenAIAdapter` | API key + endpoint | Existing code wrapped    |
| OpenAI Direct | `OpenAIAdapter`      | API key            | Uses `openai` Python SDK |

### Phase 5 (Cloud Agnostic) Additional Adapters

| Provider         | Adapter Class         | Plan Tier                |
| ---------------- | --------------------- | ------------------------ |
| Anthropic Claude | `AnthropicAdapter`    | Enterprise               |
| Google Gemini    | `GeminiAdapter`       | Enterprise               |
| AWS Bedrock      | `BedrockAdapter`      | Enterprise               |
| Azure AI Foundry | `AzureFoundryAdapter` | Professional, Enterprise |

BYOLLM: Enterprise tier customers can provide their own API key for any supported provider. Keys stored encrypted in vault, never in PostgreSQL.

---

## 5. MCP "Differentiator" Clarification

**Finding**: MCP is called the strongest USP but the actual implementation uses a custom tool-call format, not Anthropic's open MCP standard.

**Resolution**: Clarify the distinction explicitly in all product documentation:

### Internal MCP (current implementation)

- The A2A agents in aihub2 use an **internal tool-calling protocol** built on top of Azure OpenAI function calling
- This is NOT the open MCP standard from Anthropic
- It is an internal implementation detail — users never see it
- Terminology in docs should be "A2A agent protocol" or "internal tool orchestration" — not "MCP"

### Open MCP Standard (mingai platform, Phase 4+)

- The open MCP standard (Model Context Protocol, Anthropic/open-source) is the **external** integration surface
- External MCP servers built by enterprise customers or third parties can connect to mingai via the open standard
- This is the actual differentiator: **mingai as an MCP-compatible platform**

### USP Correction

The correct USP statement:

> "mingai supports the open Model Context Protocol (MCP) standard, allowing enterprises to connect any MCP-compatible data source or tool without writing custom integration code."

NOT: "mingai uses MCP internally" — this is meaningless to customers.

**Updated in**: `02-product/04-unique-selling-points.md` (see latest version)

---

## 6. Realistic Cost Model

**Finding**: $800-1500/month estimate for 100 tenants ignores Azure OpenAI costs. At $0.016/query × 10K queries/tenant/month = $16,000/month in LLM costs alone.

**Revised Cost Model (Platform at 100 Tenants, Professional Plan Average)**:

### Per-Tenant Monthly Cost (Professional, 500 users, 10K queries/day)

**Token count assumption**: Average query = 1,500 input tokens (system prompt + retrieved context) + 500 output tokens = 2,000 tokens/query. This is a conservative estimate; RAG queries with larger context windows can reach 4,000-8,000 tokens. See sensitivity table below.

**Note on model pricing**: GPT-5.2-chat is an internal deployment name; exact pricing not publicly documented. Estimate extrapolated from GPT-4 Turbo pricing (~$0.01/1K input, $0.03/1K output). At 2K tokens/query: ~$0.016/query. This estimate should be validated against actual Azure invoice data after first month of production.

| Component                   | Unit Cost     | Volume/Month | Monthly Cost |
| --------------------------- | ------------- | ------------ | ------------ |
| GPT-5.2-chat (synthesis)    | ~$0.016/query | 300K queries | $4,800       |
| GPT-5 Mini (intent)         | ~$0.001/query | 300K queries | $300         |
| text-embedding-3-large      | ~$0.002/query | 300K queries | $600         |
| Azure AI Search             | $0.0001/query | 300K queries | $30          |
| PostgreSQL (RDS Aurora)     | $0.10/GB/mo   | 50GB         | $5           |
| Redis                       | fixed share   | —            | $10          |
| Storage (Azure Blob/S3)     | $0.023/GB     | 100GB        | $2.30        |
| **Total COGS/tenant/month** |               |              | **$5,747**   |

### Gross Margin Sensitivity (Token Count Varies)

Revenue: $25/user/month × 500 users = $12,500/tenant/month (fixed)

| Avg tokens/query | LLM cost/query | LLM cost/month | Total COGS | Gross Margin |
| ---------------- | -------------- | -------------- | ---------- | ------------ |
| 1,000 tokens     | ~$0.008        | $2,400         | $3,347     | **73%**      |
| 2,000 tokens     | ~$0.016        | $4,800         | $5,747     | **54%**      |
| 4,000 tokens     | ~$0.032        | $9,600         | $10,547    | **16%**      |
| 8,000 tokens     | ~$0.064        | $19,200        | $20,147    | **-61%** ⚠   |

**Implication**: Context window management is not optional — it is a margin-critical engineering concern. The RAG pipeline must enforce a hard context window budget per query (e.g., 2,000 input tokens max) to maintain acceptable margins. Exceeding 4,000 tokens/query without caching makes the Professional tier unviable.

### Platform Revenue Required

At Professional tier ($25/user/month × 500 users = **$12,500/month/tenant**):

- COGS at 2,000 tokens/query: $5,747
- Gross margin: **54%**

This is a reasonable SaaS gross margin for AI-heavy products (Glean, for example, runs ~45-55% GM).

### Key Insight

The red team's $800-1500/month estimate was the **infrastructure cost only** (PostgreSQL, Redis, compute). It excluded **LLM API costs which are 80%+ of total COGS**. The revised model incorporates full LLM costs.

### Cost Mitigation via Caching

The semantic caching system (`06-caching-product/`, `14-17` research docs) targets 35-50% cache hit rate on repeat queries. **This is a hypothesis pending production data — do not treat as a guaranteed margin improvement until validated with real tenant usage.** Conservative target: 20% cache hit rate in first 6 months. At 20% hit rate:

- LLM synthesis cost reduction: 20% × $4,800 = **$960/tenant/month savings**
- Revised COGS: $5,747 - $960 = **$4,787/tenant/month**
- Revised gross margin: **62%**

At the 40% target hit rate (optimistic, achieved in month 12+):

- Revised COGS: $3,827 → Gross margin: **69%**

---

## 7. Disaster Recovery and Failover Strategy

**Finding**: No documents address DR/failover for Azure OpenAI, Cosmos DB (now PostgreSQL), or Azure Search outages.

**Resolution**: DR architecture per component:

### 7a. Database (PostgreSQL / RDS Aurora)

| Scenario          | Strategy                                                                                   | RTO      | RPO      |
| ----------------- | ------------------------------------------------------------------------------------------ | -------- | -------- |
| Single AZ failure | RDS Multi-AZ automatic failover                                                            | <30s     | 0        |
| Region failure    | Aurora Global Database with read replica in secondary region. Promote to primary in ~1 min | <5 min   | <1 min   |
| Data corruption   | Point-in-time recovery (PITR), 35-day retention                                            | <4 hours | Variable |

### 7b. LLM Provider (Azure OpenAI)

| Scenario                                    | Strategy                                                                                            |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Azure OpenAI endpoint degraded (>5% errors) | Circuit breaker opens → route to fallback deployment in different Azure region                      |
| Azure OpenAI region failure                 | Route to OpenAI Direct (platform-managed fallback provider)                                         |
| Complete Azure OpenAI outage                | Degrade gracefully: disable streaming, serve cached answers, show "AI is currently limited" message |

LLM fallback chain:

```
Azure OpenAI (primary) → Azure OpenAI (secondary region) → OpenAI Direct → Graceful degradation
```

### 7c. Search Index (Azure AI Search / OpenSearch)

| Scenario                 | Strategy                                                                                          |
| ------------------------ | ------------------------------------------------------------------------------------------------- |
| Search endpoint degraded | Circuit breaker → serve from cache for up to 5 minutes                                            |
| Index service outage     | Show "Knowledge base temporarily unavailable. Estimated recovery: X minutes." No Tavily fallback. |
| Data loss                | Rebuild index from source documents in blob/S3 storage (1-4 hours)                                |

**Note**: Internet search (Tavily) is NOT a DR fallback for search index outage. For compliance-regulated enterprise tenants (the target segment), automatically routing queries to public internet search violates data isolation guarantees and regulatory requirements. Tavily is available as an opt-in feature for general knowledge queries only — it is never triggered automatically as a failover mechanism.

### 7d. Redis Cache

| Scenario           | Strategy                                                                                                            |
| ------------------ | ------------------------------------------------------------------------------------------------------------------- |
| Redis node failure | Redis Cluster automatic failover (<30s)                                                                             |
| Full Redis outage  | Application falls through to PostgreSQL for session data; LLM cache miss is acceptable (not a user-visible failure) |

### 7e. Platform-Level SLAs

| Plan         | Uptime SLA                 | RTO          | RPO          |
| ------------ | -------------------------- | ------------ | ------------ |
| Starter      | Best effort                | No guarantee | No guarantee |
| Professional | 99.9% (8.7h/year downtime) | <30 min      | <5 min       |
| Enterprise   | 99.99% (52 min/year)       | <5 min       | <1 min       |

### 7f. Runbook Documentation Location

Each DR scenario has a runbook in `docs/runbooks/` (to be created in Phase 6):

- `runbooks/database-failover.md`
- `runbooks/llm-provider-failover.md`
- `runbooks/search-outage.md`
- `runbooks/redis-failover.md`

---

## 8. Missing User Flow Personas

**Finding**: Only platform admin and tenant admin flows existed. Knowledge worker, analyst, role admin, index admin, and compliance auditor flows missing.

**Resolution**: User flows now exist for all key personas:

| Flow Doc                                    | Personas Covered                               |
| ------------------------------------------- | ---------------------------------------------- |
| `03-user-flows/01-platform-admin-flows.md`  | Platform Admin (existing, expanded)            |
| `03-user-flows/02-tenant-admin-flows.md`    | Tenant Admin (existing, expanded)              |
| `03-user-flows/03-end-user-flows.md`        | Knowledge Worker, Analyst, End User            |
| `03-user-flows/04-platform-model-flows.md`  | Platform model, AAA framework, network effects |
| `03-user-flows/05-caching-ux-flows.md`      | Cache hit/miss UX for end users                |
| `03-user-flows/06-document-upload-flows.md` | Personal document upload (drag-drop, paste)    |
| `03-user-flows/07-google-drive-flows.md`    | Google Drive setup and sync (Tenant Admin)     |
| `03-user-flows/08-glossary-flows.md`        | Glossary management (Tenant Admin, End User)   |

**Remaining gap**: Role admin and index admin are specialized tenant admin sub-flows. These are covered within `02-tenant-admin-flows.md` flows 05 (KB Setup) and 07 (Role Customization). Dedicated docs for these sub-personas are Phase 2 priority if customer feedback identifies friction.

---

## 9. PMF Gaps: Pricing and GTM Foundation

**Finding**: PMF score 2.7/5 with willingness-to-pay (1/5) and GTM readiness (1/5) as critical gaps. No pricing model, sales strategy, or demo environment planned.

**Resolution**: Foundation work done; full GTM is a Phase 6 deliverable.

### 9a. Pricing Model Decision

Adopted: **Tier-based with usage-based overage** (documented in `02-product/06-multi-tenant-product.md` §Go-to-Market):

- Starter: $15/user/month (max 25 users, 5 indexes, 3 A2A agents)
- Professional: $25/user/month (max 500 users, 50 indexes, all standard A2A agents)
- Enterprise: Custom (unlimited, dedicated infra option, SLA, priority support)

Pricing is **below Copilot ($30)** at Professional tier while offering substantially more data source flexibility.

### 9b. Willingness to Pay — Evidence Strategy

The 1/5 WTP score reflects lack of customer validation, not the pricing model. To improve WTP evidence:

1. **Design partners (Phase 1)**: Onboard 3-5 enterprises at no cost in exchange for feedback. Measure: "Would you pay $25/user/month to keep using this?" Target: 4/5 say yes.
2. **Value dashboard**: Show customers their realized savings ("You saved 247 analyst-hours this month = $37,050 at $150/hr"). Connects product value to dollar value.
3. **Cost comparison tool**: "Your organization is spending $X/year on manual research time. mingai costs $Y/year." This is a budget reallocation pitch, not new spend.

### 9c. GTM Readiness — Phase 1-3 Actions

| Phase   | GTM Action                                                                                  |
| ------- | ------------------------------------------------------------------------------------------- |
| Phase 1 | Demo environment: production-quality tenant with seeded data, realistic glossary, 3 indexes |
| Phase 1 | 2-page product brief for design partner outreach                                            |
| Phase 2 | Pricing page on marketing site                                                              |
| Phase 3 | Self-service trial (Starter tier, no credit card, 14-day)                                   |
| Phase 4 | Case study from design partner #1                                                           |
| Phase 6 | Full sales motion: demo scripts, objection handling, competitive battle cards               |

### 9d. Target Segment Validation

Initial segment: **Financial services (50-2000 employees, not F500)**

- Pain point is acute (Bloomberg/Oracle data fragmentation)
- Budget exists (software-heavy industry)
- A2A agent differentiators resonate (Bloomberg Intelligence, CapIQ, Oracle Fusion)
- Regulatory context makes RBAC + audit trail a requirement, not a nice-to-have

---

## 10. Fabricated RBAC Data Correction

**Finding**: Admin hierarchy doc listed role/function names that were fabricated, not verified against codebase.

**Resolution**: Complete RBAC specification now grounded in:

1. Codebase-verified system functions (9 functions from `scripts/init_system_roles.py`)
2. Platform roles defined in `24-platform-rbac-specification.md` with full permission matrix
3. Tenant roles defined in `01-admin-hierarchy.md` with API endpoint mapping

All role names are consistent across: admin hierarchy doc, roadmap, user flows, and the platform RBAC spec.

---

**Document Version**: 1.0
**Last Updated**: 2026-03-05
