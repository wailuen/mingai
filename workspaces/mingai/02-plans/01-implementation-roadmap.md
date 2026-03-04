# Implementation Roadmap: AIHub2 Multi-Tenant SaaS Conversion

## Summary Table

| Phase | Name             | Duration | Key Deliverable                                             | Kailash SDK                                                                      | Risk                               |
| ----- | ---------------- | -------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------- | ---------------------------------- |
| 1     | Foundation       | 8 weeks  | tenant_id isolation across all data stores                  | DataFlow (PostgreSQL models, Alembic migrations)                                 | HIGH — touches every query path    |
| 2     | LLM Library      | 4 weeks  | Platform LLM Library + Tenant LLM Setup (Library or BYOLLM) | Kaizen (LLMProvider, instrumented client), DataFlow (tenant_config, llm_library) | MEDIUM — cost modeling uncertainty |
| 3     | Auth Flexibility | 3 weeks  | Tenant-selectable SSO (Entra, Google, Okta, SAML)           | Nexus (auth middleware)                                                          | MEDIUM — token migration window    |
| 4     | Agentic Upgrade  | 5 weeks  | Kaizen multi-agent + A2A + per-tenant MCP routing           | Kaizen (orchestration, A2A), MCP (registry)                                      | HIGH — 9 MCP servers to isolate    |
| 5     | Cloud Agnostic   | 4 weeks  | Azure + GCP certification, CLOUD_PROVIDER config            | Core SDK (workflow nodes), Nexus (deployment)                                    | MEDIUM — abstraction leakage       |
| 6     | GA               | 3 weeks  | Billing, self-service onboarding, SLA monitoring            | Nexus (billing API), DataFlow (usage tracking)                                   | LOW — polish phase                 |

**Total estimated duration: 27 weeks (~7 months)**

**80/15/5 Rule Applied Throughout:**

- 80% of effort on proven patterns (tenant isolation, JWT claims, provider abstraction)
- 15% on targeted innovation (agentic RAG, A2A protocol, MCP routing)
- 5% on exploratory work (cloud-agnostic abstraction, advanced billing models)

---

## Phase 1: Foundation (Weeks 1-8)

### Goals

- Deploy on AWS with PostgreSQL (RDS Aurora) as the primary database
- Inject `tenant_id` into every data path: PostgreSQL (with RLS), Redis, search indexes
- Build platform admin portal for tenant CRUD operations
- Implement basic tenant provisioning workflow
- Extend JWT tokens with tenant claims
- Zero new features — isolation only

### Key Deliverables

1. **PostgreSQL schema setup** — Alembic migrations: add `tenant_id` columns to all 19 tables, create `tenants` and `tenant_configs` tables, enable Row-Level Security (RLS) policies (full table list in `12-database-architecture-analysis.md` Section 2)
2. **Tenant middleware** — FastAPI middleware that extracts `tenant_id` from JWT and sets `app.tenant_id` on every database connection via `SET app.tenant_id`
3. **RLS policies** — PostgreSQL Row-Level Security on all tenant-scoped tables: `USING (tenant_id = current_setting('app.tenant_id'))`
4. **Redis namespace migration** — Key pattern changed from `mingai:{key}` to `mingai:{tenant_id}:{key}`
5. **Search index isolation** — Per-tenant search indexes with naming convention `{index_name}_{tenant_id}`
6. **Platform admin portal** — Minimal Next.js pages: tenant list, create, edit, deactivate
7. **Tenant provisioning workflow** — Kailash workflow that creates database records, Redis namespace, search indexes, and default admin user for a new tenant
8. **JWT v2** — Token now includes `tenant_id`, `scope` (tenant|platform), and `plan` (starter|professional|enterprise)
9. **AWS RDS Aurora PostgreSQL deployment** — Production database on AWS RDS Aurora PostgreSQL; DATABASE_URL-driven connection abstraction

### Kailash SDK Components

- **DataFlow**: PostgreSQL model definitions for `Tenant`, `TenantConfig`; Alembic migration scripts for backfilling `tenant_id` and enabling RLS
- **Nexus**: Platform admin API endpoints (tenant CRUD); tenant middleware for request scoping and `SET app.tenant_id`
- **Core SDK**: Provisioning workflow orchestrating database setup, index creation, and admin user creation

### Dependencies

- AWS account with RDS Aurora PostgreSQL provisioned
- Search service with index management permissions (Azure AI Search or OpenSearch)
- Alembic configured with DATABASE_URL from `.env`
- Decision on RLS policy strategy (see Technical Migration Plan Section 1)

### Risks

| Risk                                            | Likelihood | Impact   | Mitigation                                                                                |
| ----------------------------------------------- | ---------- | -------- | ----------------------------------------------------------------------------------------- |
| Migration corrupts existing data                | Low        | Critical | Backfill is additive (new column), not destructive. Rollback = disable RLS                |
| RLS policy misconfiguration leaks data          | Medium     | Critical | Extensive integration tests for cross-tenant isolation; RLS tested in staging first       |
| Query performance degradation with RLS overhead | Low        | Medium   | PostgreSQL RLS overhead is minimal; load test with 10x current data volume before cutover |
| JWT v2 breaks existing sessions                 | Medium     | Medium   | 30-day dual-token acceptance window (see Migration Plan Section 2)                        |

### Success Metrics

- All 9 PostgreSQL tables have `tenant_id` on 100% of rows with RLS enabled
- Redis keys follow new namespace pattern; old keys cleaned up
- Platform admin can create a tenant and the provisioning workflow completes in <30s
- Existing single-tenant functionality unchanged (regression test suite green)
- Zero cross-tenant data leakage (verified by RLS isolation test suite)

### Timeline Note

Phase 1 expanded from 6 to 8 weeks to account for PostgreSQL migration complexity: Cosmos DB JSON export and transformation, Alembic migration script development, RLS policy setup and testing.

---

## Phase 2: LLM Library & Tenant Setup (Weeks 9-12)

### Goals

- Build Platform LLM Library: curated set of approved providers and models, managed by platform admin, available per plan tier
- Build Tenant LLM Setup: tenant admin selects from the LLM Library OR brings their own API key (BYOLLM — Enterprise only)
- All agents in a tenant use the tenant's single LLM configuration — no per-agent model selection
- Abstract LLM provider behind a clean interface; launch with 2 providers: Azure OpenAI and OpenAI Direct
- Support BYOLLM for Enterprise tier
- Replace `@lru_cache` Settings singleton with tenant-scoped, Redis-cached config

### Key Deliverables

1. **LLMProvider abstraction interface** — Common interface: `complete(messages, model, **kwargs) -> CompletionResponse` with provider-specific adapters
2. **Azure OpenAI adapter** — Wraps existing Azure OpenAI integration
3. **OpenAI Direct adapter** — New adapter for direct OpenAI API access
4. **Platform LLM Library** — Platform admin UI: add/remove providers, configure available models per plan tier (Starter/Professional/Enterprise), set recommended models. Library is the single source of truth for which LLMs tenants can select.
5. **Tenant LLM Setup UI** — Tenant Admin → Settings → LLM Configuration:
   - Option A: Select provider + model from Platform LLM Library (tokens billed at markup)
   - Option B: BYOLLM — provide own API key + endpoint (Enterprise only; tokens tracked, billing skipped)
   - One active LLM config per tenant; changing it takes effect for all subsequent agent calls
6. **BYOLLM support** — Enterprise tenants supply their own API keys, stored encrypted in `tenant_config`
7. **Tenant config migration** — `@lru_cache` Settings replaced with PostgreSQL `tenant_configs` table, Redis-cached with 15-min TTL
8. **Instrumented LLM client** — Platform wrapper around provider SDKs that reads tenant's `model_source` flag at request time; routes billing vs. observability-only tracking accordingly
9. **Cost tracking per tenant** — Token usage logged to `usage_events` with `tenant_id`, `provider`, `model`, `tokens_in`, `tokens_out`, `model_source` (library | byollm)

### Kailash SDK Components

- **Kaizen**: LLMProvider interface and adapter pattern; model registry; instrumented client wrapper
- **DataFlow**: `tenant_configs` and `usage_events` PostgreSQL models; cost aggregation queries; `llm_library` table for platform-managed model catalog
- **Nexus**: Platform LLM Library admin API; Tenant LLM Setup API; provider management endpoints

### Dependencies

- Phase 1 complete (tenant_id in all data stores)
- OpenAI API account provisioned for testing
- Cost modeling complete (agentic RAG = 3-8x classic RAG — budget accordingly)

### Risks

| Risk                                               | Likelihood | Impact   | Mitigation                                                                                          |
| -------------------------------------------------- | ---------- | -------- | --------------------------------------------------------------------------------------------------- |
| Agentic RAG costs 3-8x higher than budgeted        | High       | High     | Hard per-tenant token limits in Phase 2; cost dashboard before enabling agentic features in Phase 4 |
| Provider API differences cause abstraction leakage | Medium     | Medium   | Test abstraction with both providers before shipping; keep interface minimal                        |
| BYOLLM key storage security                        | Low        | Critical | Encrypt at rest with Azure Key Vault; keys never logged or returned in API responses                |

### Success Metrics

- Both providers pass identical integration test suite
- Tenant admin can switch providers without code changes
- BYOLLM works for Enterprise tier with customer-supplied keys
- Cost tracking accurate to within 1% of provider invoices
- Config cache miss rate <5% after warm-up

### Red-Team Recommendation Applied

- Start Azure-only for Phase 1 (done — Phase 2 is first time we add a second provider)
- Test abstraction with exactly 2 providers before adding more (Azure OpenAI + OpenAI Direct)
- Budget agentic RAG costs explicitly: per-tenant hard limits, cost dashboard, alerting

---

## Phase 3: Auth Flexibility (Weeks 13-15)

### Goals

- Integrate Auth0 as the identity broker
- Support tenant-selectable SSO: Azure Entra (existing), Google Workspace, Okta, generic SAML
- Provide migration path from current Azure Entra-only auth
- Maintain local JWT fallback for development and tenants without SSO

### Key Deliverables

1. **Auth0 integration** — Auth0 as identity broker; Azure Entra becomes one of many upstream providers
2. **Tenant SSO configuration** — Tenant admin selects SSO provider from platform-enabled list; platform admin enables providers per plan tier
3. **SSO provider adapters** — Azure Entra, Google Workspace, Okta, generic SAML 2.0
4. **Migration tooling** — Script to migrate existing users from direct Entra tokens to Auth0-brokered tokens
5. **Local auth fallback** — Username/password auth for development environments and tenants without SSO
6. **Session management** — Token refresh, session invalidation, concurrent session limits per plan tier

### Kailash SDK Components

- **Nexus**: Auth middleware refactored for multi-provider; session management API
- **DataFlow**: User identity mapping model (user_id <-> external_provider_id)
- **Core SDK**: Auth migration workflow

### Dependencies

- Phase 1 complete (JWT v2 with tenant claims)
- Auth0 tenant provisioned and configured
- SSO provider test accounts (Google Workspace, Okta sandbox)

### Risks

| Risk                                   | Likelihood | Impact | Mitigation                                                    |
| -------------------------------------- | ---------- | ------ | ------------------------------------------------------------- |
| Token migration breaks active sessions | Medium     | High   | 30-day dual-token window; gradual rollout per tenant          |
| Auth0 adds latency to auth flow        | Low        | Medium | Cache Auth0 tokens; measure P95 latency before/after          |
| SSO misconfiguration causes lockout    | Medium     | High   | Local auth fallback always available; platform admin override |

### Success Metrics

- Login works with all 4 SSO providers + local auth
- Token migration completes for existing users with zero lockouts
- Auth latency P95 <500ms (including SSO redirect)
- Platform admin can enable/disable SSO providers per tenant

---

## Phase 4: Agentic Upgrade (Weeks 16-20)

### Goals

- Replace single-agent RAG with Kaizen multi-agent orchestration
- Implement A2A (Agent-to-Agent) protocol for inter-agent communication
- Build per-tenant MCP server routing with registry and access control
- Add remaining 5 LLM providers: Anthropic, Deepseek, DashScope, Doubao, Gemini
- Implement tenant-scoped agent memory and tool access

### Key Deliverables

1. **Kaizen multi-agent orchestration** — Supervisor agent delegates to specialist agents (research, analysis, synthesis) per conversation
2. **A2A protocol** — Standardized inter-agent communication; agents can delegate sub-tasks
3. **MCP server registry** — Central registry of all 9 MCP servers (Bloomberg, CapIQ, Perplexity, Oracle Fusion, AlphaGeo, Teamworks, PitchBook, Azure AD, iLevel)
4. **Per-tenant MCP routing** — Tenant admin configures which MCP servers are available; access control enforced at registry level
5. **5 additional LLM providers added to LLM Library** — Anthropic, Deepseek, DashScope (Qwen), Bytedance Ark (Doubao), Google Gemini adapters added to LLMProvider abstraction and published in Platform LLM Library per plan tier
6. **Agent memory isolation** — Conversation context and agent state scoped to tenant_id
7. **Cost controls for agentic RAG** — Per-tenant budget limits, circuit breakers for runaway agent loops

### Kailash SDK Components

- **Kaizen**: Multi-agent orchestration framework; agent registry; A2A protocol implementation
- **MCP**: Server registry; per-tenant routing middleware; access control
- **DataFlow**: Agent state models; MCP access control models
- **Core SDK**: Agent orchestration workflows

### Dependencies

- Phase 2 complete (LLM abstraction in place)
- Phase 3 complete (auth handles agent-to-service tokens)
- MCP server access credentials for all 9 servers
- Cost modeling validated from Phase 2 usage data

### Risks

| Risk                                       | Likelihood | Impact   | Mitigation                                                                      |
| ------------------------------------------ | ---------- | -------- | ------------------------------------------------------------------------------- |
| Agentic RAG costs blow budget              | High       | High     | Hard per-tenant token limits; circuit breakers; cost dashboard with alerts      |
| Agent loops (infinite delegation)          | Medium     | High     | Max depth limit on A2A delegation (default: 5); timeout per agent turn          |
| MCP server isolation failure               | Low        | Critical | Each tenant gets isolated MCP client instances; no shared state between tenants |
| 9 MCP servers have different auth patterns | High       | Medium   | Normalize auth at registry level; credential vault per tenant                   |

### Success Metrics

- Multi-agent conversations produce higher-quality answers than single-agent (measured by user feedback)
- Agent loop circuit breaker triggers <1% of conversations
- All 9 MCP servers accessible with tenant-scoped credentials
- 7 LLM providers in LLM Library pass integration test suite; tenant LLM Setup supports all 7
- Per-tenant cost tracking accurate; no tenant exceeds budget without alert

### Red-Team Recommendation Applied

- Address lowest-scoring PMF dimension (cost predictability) with hard limits and circuit breakers
- Budget agentic RAG explicitly: dashboard shows per-tenant cost in real-time

---

## Phase 5: Cloud Agnostic (Weeks 21-24)

### Goals

- Validate and certify the same codebase for Azure and GCP deployments (AWS is already live from Phase 1)
- Build remaining abstraction layers to decouple from AWS-specific services where needed
- Implement `CLOUD_PROVIDER` config parameter for cloud-specific adapter selection
- Implement Terraform IaC for AWS, Azure, and GCP; shared module structure

### Key Deliverables

1. **CLOUD_PROVIDER config** — Environment variable `CLOUD_PROVIDER=aws|azure|gcp|self-hosted` drives adapter selection for all cloud-specific services
2. **SearchEngine abstraction** — Interface over OpenSearch (AWS), Azure AI Search, and GCP Vertex AI Search
3. **ObjectStore abstraction** — Interface over S3 (AWS), Azure Blob Storage, and GCS (GCP)
4. **SecretStore abstraction** — Interface over AWS Secrets Manager, Azure Key Vault, and GCP Secret Manager
5. **TelemetryExporter abstraction** — Interface over CloudWatch (AWS), Azure Monitor, and Cloud Logging (GCP)
6. **Azure deployment** — Full stack deployed on Azure (Azure Database for PostgreSQL, Azure AI Search, Azure Blob Storage); integration tests passing
7. **GCP deployment** — Full stack deployed on GCP (Cloud SQL for PostgreSQL, Vertex AI Search, GCS); integration tests passing
8. **Terraform IaC** — Infrastructure as code for AWS, Azure, and GCP; shared module structure

**Note:** PostgreSQL is the database on all clouds — no DocumentStore abstraction needed. The `DATABASE_URL` connection string handles cloud-specific PostgreSQL endpoints (RDS Aurora, Azure Database for PostgreSQL, Cloud SQL).

### Kailash SDK Components

- **Core SDK**: Abstraction layer workflow nodes (e.g., ObjectStore nodes that dispatch to cloud-specific adapter based on `CLOUD_PROVIDER`)
- **Nexus**: Deployment configuration for multi-cloud; health check endpoints per cloud
- **DataFlow**: PostgreSQL model definitions are already cloud-agnostic (same schema across all clouds)

### Dependencies

- Phases 1-4 complete (all features working on AWS)
- Azure account provisioned with equivalent services
- GCP account provisioned with equivalent services
- Terraform state backend configured per cloud

### Risks

| Risk                                                     | Likelihood | Impact | Mitigation                                                                           |
| -------------------------------------------------------- | ---------- | ------ | ------------------------------------------------------------------------------------ |
| Abstraction leakage (AWS-specific behavior in interface) | Medium     | Medium | Define interfaces from requirements, not AWS API shapes; test on all three clouds    |
| Azure/GCP deployments have subtle behavior differences   | Medium     | Medium | Integration test suite runs on all clouds; parity dashboard                          |
| Terraform drift between clouds                           | Low        | Low    | Shared modules where possible; cloud-specific overrides documented                   |
| PostgreSQL feature differences across cloud providers    | Low        | Low    | Use standard PostgreSQL features only; RLS is supported on all major cloud providers |

### Success Metrics

- All integration tests pass on AWS, Azure, and GCP
- Switching cloud provider requires only `CLOUD_PROVIDER` and `DATABASE_URL` config changes, no code changes
- Terraform can stand up full environment in <30 minutes on any of the three clouds
- No AWS-specific imports outside of provider adapter modules

### Red-Team Recommendation Applied

- AWS deployed in Phase 1 as the primary cloud — production-proven before this phase begins
- Phase 5 validates Azure and GCP as deployment targets for the SAME codebase
- Cloud-agnostic certification phase, not a rewrite phase

---

## Phase 6: GA (Weeks 25-27)

### Goals

- Production-ready observability across all tenants
- Billing integration with usage-based pricing
- Tenant self-service onboarding (no platform admin intervention for Starter tier)
- SLA monitoring and alerting
- Documentation and runbooks for operations team

### Key Deliverables

1. **Observability stack** — Per-tenant dashboards: API latency, error rates, LLM usage, agent performance, MCP server health
2. **Billing integration** — Usage-based billing: token consumption, API calls, storage, MCP server usage; Stripe integration for payment
3. **Self-service onboarding** — Starter tier: sign up, provision, start using in <5 minutes with no human intervention
4. **SLA monitoring** — Uptime tracking per tenant; automated alerts for SLA breaches; incident response runbooks
5. **Operations runbooks** — Tenant provisioning, deprovisioning, data export, incident response, scaling procedures
6. **Load testing** — Simulate 50 concurrent tenants with realistic workloads; identify bottlenecks

### Kailash SDK Components

- **Nexus**: Billing API endpoints; self-service onboarding flow; SLA monitoring webhooks
- **DataFlow**: Billing models (invoices, line items, payments); SLA event tracking
- **Core SDK**: Onboarding workflow (tenant creation -> provisioning -> welcome email)

### Dependencies

- Phases 1-5 complete
- Stripe account configured
- Operations team briefed on runbooks

### Risks

| Risk                                 | Likelihood | Impact | Mitigation                                                               |
| ------------------------------------ | ---------- | ------ | ------------------------------------------------------------------------ |
| Billing calculation errors           | Medium     | High   | Reconcile automated billing against manual calculation for first 30 days |
| Self-service provisioning failures   | Low        | Medium | Fallback to manual provisioning; alert on failure                        |
| Load test reveals scaling bottleneck | Medium     | Medium | Budget 1 week buffer for performance fixes                               |

### Success Metrics

- Self-service onboarding completes in <5 minutes for Starter tier
- Billing accurate to within 0.1% of actual usage
- SLA monitoring detects outages within 60 seconds
- System handles 50 concurrent tenants with P95 latency <2s
- Zero data leakage across tenants (final isolation audit)

---

## Cross-Phase Concerns

### Testing Strategy (All Phases)

- **Unit tests**: Mocking allowed; run on every commit
- **Integration tests**: Real PostgreSQL (Docker for CI), real Redis, real search; run on every PR
- **E2E tests**: Full stack with Playwright; run before each phase completion
- **Isolation tests**: Cross-tenant data leakage detection; run nightly after Phase 1

### Security (All Phases)

- Security review before every commit (mandatory per CLAUDE.md)
- Penetration testing at Phase 1 completion (tenant isolation) and Phase 6 (GA)
- Secrets in Azure Key Vault / AWS Secrets Manager; never in code or config files

### Cost Tracking (Phases 2+)

- Per-tenant LLM token usage tracked from Phase 2 onward
- Weekly cost reports to platform admin
- Budget alerts at 80% and 100% of tenant limits
- Agentic RAG cost multiplier (3-8x) factored into all tier pricing

### Rollback Strategy (All Phases)

- Each phase has a documented rollback plan (see Technical Migration Plan)
- Feature flags control new functionality; off = old behavior
- Database migrations are additive (new columns/tables via Alembic); never destructive
- 48-hour rollback window after each phase cutover
