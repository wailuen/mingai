# Implementation Roadmap: AIHub2 Multi-Tenant SaaS Conversion

## Summary Table

| Phase | Name             | Duration | Key Deliverable                                                                                                  | Kailash SDK                                                                      | Risk                                   |
| ----- | ---------------- | -------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | -------------------------------------- |
| 1     | Foundation       | 8 weeks  | tenant_id isolation, platform RBAC, glossary v1                                                                  | DataFlow (PostgreSQL models, Alembic migrations)                                 | HIGH — touches every query path        |
| 2     | LLM Library      | 4 weeks  | Platform LLM Library + Tenant LLM Setup (Library or BYOLLM)                                                      | Kaizen (LLMProvider, instrumented client), DataFlow (tenant_config, llm_library) | MEDIUM — cost modeling uncertainty     |
| 3     | Auth Flexibility | 3 weeks  | Tenant-selectable SSO (Entra, Google, Okta, SAML) + Google Drive credential groundwork                           | Nexus (auth middleware)                                                          | MEDIUM — token migration window        |
| 4     | Agentic Upgrade  | 6 weeks  | Kaizen multi-agent + A2A + guardrail enforcement + synthesis context management + DAG failure policy + fast-path | Kaizen (orchestration, A2A), MCP (internal agent protocol)                       | HIGH — 9 A2A agents + guardrail system |
| 5     | Cloud Agnostic   | 5 weeks  | Azure + GCP certification, OTel tracing, DAG replay UI, CloudStorageConnector abstraction                        | Core SDK (workflow nodes), Nexus (deployment)                                    | MEDIUM — abstraction leakage           |
| 6     | GA               | 4 weeks  | Billing, self-service onboarding, BYOMCP sandboxing, marketplace consent model, DR runbooks                      | Nexus (billing API), DataFlow (usage tracking)                                   | MEDIUM — enterprise security gates     |

**Total estimated duration: 30 weeks (~7.5 months)**

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

1. **PostgreSQL schema setup** — Alembic migrations: add `tenant_id` columns to all 21 tables, create `tenants` and `tenant_configs` tables, enable Row-Level Security (RLS) policies (full table list in `12-database-architecture-analysis.md` Section 2)
2. **Tenant middleware** — FastAPI middleware that extracts `tenant_id` from JWT and sets `app.tenant_id` on every database connection via `SET app.tenant_id`
3. **RLS policies** — PostgreSQL Row-Level Security on all tenant-scoped tables: `USING (tenant_id = current_setting('app.tenant_id'))`
4. **Redis namespace migration** — Key pattern changed from `mingai:{key}` to `mingai:{tenant_id}:{key}`
5. **Search index isolation** — Per-tenant search indexes with naming convention `{index_name}_{tenant_id}`
6. **Platform admin portal** — Minimal Next.js pages: tenant list, create, edit, deactivate
7. **Tenant provisioning workflow** — Kailash workflow that creates database records, Redis namespace, search indexes, and default admin user for a new tenant
8. **JWT v2** — Token now includes `tenant_id`, `scope` (tenant|platform), and `plan` (starter|professional|enterprise)
9. **AWS RDS Aurora PostgreSQL deployment** — Production database on AWS RDS Aurora PostgreSQL; DATABASE_URL-driven connection abstraction
10. **Response feedback system** — Thumb up/down on every AI response. Feedback stored with tenant_id, message_id, rating, tags, comment. Tenant admin feedback review panel with flagging for messages with 3+ negative ratings. Records used for future model improvement signals.
11. **Platform RBAC** — Platform admin roles (`platform_admin`, `platform_operator`, `platform_support`, `platform_security`) with full permission matrix, separate `platform_members` table (no tenant_id), platform JWT with `scope: platform`, and impersonation flow for cross-tenant support. See `01-analysis/01-research/24-platform-rbac-specification.md`.
12. **Glossary v1** — Tenant-level glossary with CRUD API, CSV import/export, Redis cache, and RAG pipeline integration (query enrichment + LLM prompt injection). Full schema in `01-analysis/01-research/23-glossary-management-architecture.md`.

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

- All 21 PostgreSQL tables have `tenant_id` on 100% of rows with RLS enabled
- Redis keys follow new namespace pattern; old keys cleaned up
- Platform admin can create a tenant and the provisioning workflow completes in <30s
- Existing single-tenant functionality unchanged (regression test suite green)
- Zero cross-tenant data leakage (verified by RLS isolation test suite)

**User Flows**: Platform Admin: 01-Bootstrapping, 02-Tenant Provisioning, 07-Suspension/Deprovisioning, 08-Admin Onboarding | Tenant Admin: 01-Onboarding, 04-User Management, 05-Knowledge Base Setup, 07-Role Customization | End User: 01-First Login, 02-Standard Chat, 03-Research Mode, 04-Document Upload, 06-Internet Fallback, 07-Conversation History, 08-Failure Paths, 09-Response Feedback

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

**User Flows**: Platform Admin: 03-LLM Provider Configuration | Tenant Admin: 03-BYOLLM, 06-Cost Analytics

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

**User Flows**: Tenant Admin: 02-SSO Configuration

---

## Phase 4: Agentic Upgrade (Weeks 16-20)

### Goals

- Replace single-agent RAG with Kaizen multi-agent orchestration
- Implement A2A (Agent-to-Agent) protocol for inter-agent communication
- Build per-tenant A2A agent registry with access control and credential management
- Add remaining 5 LLM providers: Anthropic, Deepseek, DashScope, Doubao, Gemini
- Implement tenant-scoped agent memory and access control

### Key Deliverables

1. **Kaizen multi-agent orchestration** — Supervisor agent delegates to specialist agents (research, analysis, synthesis) per conversation
2. **A2A protocol** — Standardized inter-agent communication using Google A2A v0.3; agents publish AgentCards at `/.well-known/agent.json`; `AgentDispatcher` abstraction layer isolates wire protocol from orchestrator internals
3. **A2A agent registry** — Central registry of all 9 A2A agents (Bloomberg Intelligence, CapIQ Intelligence, Perplexity Web Search, Oracle Fusion, AlphaGeo, Teamworks, PitchBook Intelligence, Azure AD Directory, iLevel Portfolio); agents internally use MCP — not user-facing; health tracking and credential verification per tenant
4. **Per-tenant A2A agent routing** — Tenant admin configures which agents are enabled; tenant provides credentials; platform enforces agent guardrails and credential isolation
5. **Three-layer guardrail enforcement** — (a) Positional system prompt ordering (guardrails injected last), (b) Output filter with per-agent rule sets (keyword_block, citation_required, semantic_check), (c) Registration-time LLM audit of tenant prompt extensions. Golden test sets per agent template as CI gate. See `01-analysis/01-research/25-a2a-guardrail-enforcement.md`.
6. **Synthesis context management** — Per-agent extraction schemas (all 9 agents) convert raw Artifacts to 300–1,500 token synthesis-ready summaries. ExtractionService runs in parallel before synthesis LLM call using intent-tier model. Multi-pass synthesis for 8+ agent DAGs. Context budget enforced at 4,000 tokens/agent cap. See `01-analysis/01-research/26-a2a-synthesis-context-management.md`.
7. **DAG partial failure policy** — Node criticality classification (CRITICAL/SUPPLEMENTARY); per-failure-class propagation rules (auth_failure blocks critical agents, soft-fails supplementary; infra_failure retries once; rate_limited queues with user notification); partial result disclosure in user-facing responses. See `01-analysis/01-research/27-a2a-execution-hardening.md`.
8. **Planning LLM fast-path** — Single-agent queries (intent confidence ≥ 0.92, no cross-agent dependency) bypass DAG planner, reducing P50 latency by ~42% for 55-70% of query volume. See `01-analysis/01-research/27-a2a-execution-hardening.md`.
9. **5 additional LLM providers added to LLM Library** — Anthropic, Deepseek, DashScope (Qwen), Bytedance Ark (Doubao), Google Gemini adapters added to LLMProvider abstraction and published in Platform LLM Library per plan tier
10. **Agent memory isolation** — Conversation context and agent state scoped to tenant_id
11. **Cost controls for agentic RAG** — Per-tenant budget limits, circuit breakers for runaway agent loops
12. **Google Drive sync worker** — Full sync worker with folder browser API, incremental sync via `changes.list`, push notification channels, OAuth2 and Service Account auth, admin UI for setup and schedule. See `01-analysis/01-research/22-google-drive-sync-architecture.md`.
13. **Glossary RAG integration** — Wire approved glossary terms into the RAG pipeline: query enrichment (GlossaryEnricher), LLM prompt injection (system prompt glossary section), and source attribution tooltips. Analytics tracking for term match rates.

### Kailash SDK Components

- **Kaizen**: Multi-agent orchestration framework; agent registry; A2A protocol implementation
- **MCP**: Server registry; per-tenant routing middleware; access control
- **DataFlow**: Agent state models; MCP access control models
- **Core SDK**: Agent orchestration workflows

### Dependencies

- Phase 2 complete (LLM abstraction in place)
- Phase 3 complete (auth handles agent-to-service tokens)
- A2A agent credentials (Bloomberg, CapIQ, etc.) available for integration testing
- Cost modeling validated from Phase 2 usage data

### Risks

| Risk                                      | Likelihood | Impact   | Mitigation                                                                             |
| ----------------------------------------- | ---------- | -------- | -------------------------------------------------------------------------------------- |
| Agentic RAG costs blow budget             | High       | High     | Hard per-tenant token limits; circuit breakers; cost dashboard with alerts             |
| Agent loops (infinite delegation)         | Medium     | High     | Max depth limit on A2A delegation (default: 5); timeout per agent turn                 |
| A2A agent isolation failure               | Low        | Critical | Each tenant gets isolated agent instances with credential vault; no shared state       |
| 9 A2A agents have different auth patterns | High       | Medium   | Normalize credential injection at registry level; short-lived vault tokens per request |

### Success Metrics

- Multi-agent conversations produce higher-quality answers than single-agent (measured by user feedback)
- Agent loop circuit breaker triggers <1% of conversations
- All 9 A2A agents accessible with tenant-scoped credentials injected via vault tokens
- 7 LLM providers in LLM Library pass integration test suite; tenant LLM Setup supports all 7
- Per-tenant cost tracking accurate; no tenant exceeds budget without alert

**User Flows**: Platform Admin: 04-Global A2A Agent Management | End User: 05-Agent Delegation, 09-DAG Execution (fast-path, multi-agent, partial failure, guardrail block) | Tenant Admin: 07-Google Drive Setup, 08-Glossary Approval Workflow, 09-DAG Replay/Debug, 09-BYOMCP Registration | Platform Model: 01-Producers/Consumers/Partners, 03-Network Effects

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
9. **CloudStorageConnector abstraction** — Abstract interface covering SharePoint and Google Drive connectors; sync worker becomes connector-agnostic. Non-Microsoft enterprises can use Google Drive as their primary knowledge source without SharePoint. See `01-analysis/01-research/22-google-drive-sync-architecture.md` Section 9.
10. **OpenTelemetry distributed tracing** — W3C Trace Context propagation from orchestrator through all A2A agent containers and MCP calls. OTel collector exporting to Jaeger/Grafana Tempo. Platform admin trace explorer UI with DAG waterfall visualization. See `01-analysis/01-research/27-a2a-execution-hardening.md` Section 3.
11. **DAG replay and debug UI** — `dag_runs`, `dag_nodes`, `dag_synthesis` tables with per-plan retention policy (7/30/90 days). Tenant admin DAG run panel: artifact inspection, synthesis input/output view, re-run capability, export artifacts as JSON. See `01-analysis/01-research/27-a2a-execution-hardening.md` Section 4.

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

**User Flows**: No new user flows — infrastructure certification phase. Existing flows validated on Azure and GCP deployments.

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

1. **Observability stack** — Per-tenant dashboards: API latency, error rates, LLM usage, agent performance, A2A agent health
2. **Billing integration** — Usage-based billing: token consumption, API calls, storage, A2A agent invocation costs; Stripe integration for payment
3. **Self-service onboarding** — Starter tier: sign up, provision, start using in <5 minutes with no human intervention
4. **SLA monitoring** — Uptime tracking per tenant; automated alerts for SLA breaches; incident response runbooks
5. **Operations runbooks** — Tenant provisioning, deprovisioning, data export, incident response, scaling procedures
6. **Load testing** — Simulate 50 concurrent tenants with realistic workloads; identify bottlenecks
7. **DR runbooks** — Document and test disaster recovery procedures per component: database failover, LLM provider failover, search outage, Redis failover. SLA tiers per plan enforced. See `01-analysis/08-red-team-v2/01-remediation-plan.md` §7 for DR architecture.
8. **Demo environment** — Production-quality tenant with seeded data, realistic glossary, 3 search indexes, and 2 A2A agents enabled; used for design partner onboarding and sales demos
9. **BYOMCP sandboxing** — Kubernetes NetworkPolicy per tenant (ingress from own orchestrator only, egress to declared domains only), Envoy sidecar rate limiting, resource quotas per plan tier, registration-time capability audit, platform admin approval gate for write-capable agents. See `01-analysis/01-research/28-a2a-extensibility-security.md`.
10. **Marketplace data residency and consent model** — Publisher trust verification (domain + DPA + capability probe), three-level consent architecture (platform admin → tenant admin policy → per-query user disclosure), data egress audit log, GDPR data sovereignty filter, per-publisher blocklist for Enterprise tenants. See `01-analysis/01-research/28-a2a-extensibility-security.md`.

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

**User Flows**: Platform Admin: 05-Billing/Quota Management, 06-Platform Monitoring | Platform Model: 04-Value Creation/Capture, 05-Competitive Moat

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
