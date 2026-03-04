# Multi-Tenant Product Implications

## How Multi-Tenancy Changes the Product

Moving from single-tenant to multi-tenant is not a technical migration -- it is a product transformation. Every layer of the product changes: data model, security boundaries, admin experience, pricing, and go-to-market.

### What Changes

| Dimension            | Single-Tenant (Current)                     | Multi-Tenant (Target)                                                                      |
| -------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------ |
| **Data isolation**   | One PostgreSQL database, one Redis instance | PostgreSQL RLS (Row-Level Security) per tenant, or dedicated databases for enterprise tier |
| **Authentication**   | One Azure AD tenant                         | Federated identity -- each customer's Azure AD tenant                                      |
| **RBAC**             | One role hierarchy                          | Per-tenant role hierarchy + platform-level roles                                           |
| **Search indexes**   | All indexes in one Azure AI Search service  | Per-tenant index isolation or namespace-scoped indexes                                     |
| **MCP servers**      | Global registration                         | Per-tenant MCP server registrations with tenant-scoped credentials                         |
| **Configuration**    | Single .env / config                        | Per-tenant configuration with inheritance from platform defaults                           |
| **Billing**          | N/A                                         | Per-tenant usage tracking and billing                                                      |
| **Admin experience** | One admin panel                             | Platform admin + tenant admin (separate scopes)                                            |
| **Deployment**       | One instance per customer                   | Shared infrastructure with logical isolation                                               |
| **Onboarding**       | Manual setup                                | Self-service or guided provisioning                                                        |

---

## New User Personas

Multi-tenancy introduces personas that do not exist in single-tenant:

### Platform Admin (New persona)

**Who**: The team that operates the multi-tenant platform itself.

**Responsibilities**:

- Provision and deprovision tenants
- Monitor platform health across all tenants
- Set platform-wide policies (rate limits, storage quotas, feature flags)
- Manage platform-level MCP server marketplace
- Handle tenant billing and usage reports
- Manage platform infrastructure (scaling, upgrades, incidents)
- Enforce platform security policies (minimum RBAC requirements, audit retention)

**UI needs**:

- Platform dashboard showing all tenants with health/usage metrics
- Tenant provisioning wizard
- Cross-tenant usage and cost analytics
- Platform configuration management
- Incident management and tenant communication tools

### Tenant Admin (Evolution of current admin)

**Who**: The IT administrator at each customer organization.

**Responsibilities**:

- Configure their organization's RBAC (roles, permissions, groups)
- Register and manage their Azure AI Search indexes
- Configure MCP server connections for their data sources
- Manage their organization's users and groups
- View tenant-scoped analytics and audit logs
- Manage billing and usage within their allocation

**UI needs**:

- Tenant-scoped admin panel (identical to current admin UI, but scoped)
- Tenant onboarding wizard for first-time setup
- Azure AD integration setup (connect their Azure AD tenant)
- Index registration and validation tools
- Usage dashboard with cost visibility

**Key difference from current admin**: The tenant admin should never see data from other tenants. The current admin UI needs a tenant context filter that restricts all data operations.

### Tenant End User (Same as current Knowledge Worker)

**Who**: Employees at customer organizations.

**Responsibilities**: Same as current knowledge workers -- query enterprise content, upload personal documents, provide feedback.

**UI needs**: Identical to current UI. The multi-tenancy should be invisible to end users. They should not know (or care) that other tenants exist.

---

## Self-Service Features by Persona

### Platform Admin Self-Service

| Feature                        | Description                                                                         | Priority |
| ------------------------------ | ----------------------------------------------------------------------------------- | -------- |
| Tenant provisioning            | Create new tenant with Azure AD integration, initial config, and storage allocation | P0       |
| Tenant deprovisioning          | Safely remove tenant with data export option and grace period                       | P0       |
| Platform monitoring            | Real-time dashboard with tenant health, error rates, and resource utilization       | P0       |
| Cross-tenant analytics         | Aggregated (anonymized) usage patterns, common queries, feature adoption            | P1       |
| Feature flag management        | Enable/disable features per tenant (MCP, notifications, agent channels)             | P1       |
| Tenant billing                 | Usage-based billing with invoicing and payment tracking                             | P1       |
| MCP marketplace management     | Publish, review, and manage shared MCP servers                                      | P2       |
| Platform upgrade orchestration | Rolling upgrades across tenants with rollback capability                            | P2       |

### Tenant Admin Self-Service

| Feature                | Description                                                                   | Priority |
| ---------------------- | ----------------------------------------------------------------------------- | -------- |
| Onboarding wizard      | Step-by-step setup: connect Azure AD, register first index, create first role | P0       |
| Azure AD integration   | Self-service configuration of OIDC/SAML with their Azure AD tenant            | P0       |
| Index registration     | Register Azure AI Search indexes with validation and metadata                 | P0       |
| Role management        | Create/edit/delete roles with index permissions and system functions          | P0       |
| User management        | Assign roles to users/groups, view activity, manage access                    | P0       |
| MCP server connection  | Connect to platform MCP marketplace servers or register custom servers        | P1       |
| Analytics dashboard    | Tenant-scoped query analytics, usage, costs, and content gaps                 | P1       |
| Audit log viewer       | Tenant-scoped audit logs with search and export                               | P1       |
| Glossary management    | Manage domain-specific terminology                                            | P2       |
| SharePoint connection  | Connect SharePoint libraries for background indexing                          | P2       |
| Branding/customization | Custom logo, colors, welcome message                                          | P3       |

---

## The 80/15/5 Rule Applied to Multi-Tenant Features

### 80% Reusable (Same for every tenant)

- Core chat interface and AI pipeline
- Authentication framework (the flow, not the tenant-specific config)
- RBAC engine and permission evaluation
- Search pipeline (index routing, multi-index search, result aggregation)
- Conversation management
- User profiling engine
- Feedback system
- Analytics computation engine
- Audit logging framework
- Cache management and invalidation
- Notification delivery engine
- Agent communication channel framework

### 15% Configurable (Tenant sets via admin UI)

- Azure AD tenant connection (OIDC/SAML endpoints)
- Role hierarchy and permission matrix
- Index registrations and metadata
- MCP server connections and credentials
- Glossary terms
- SharePoint library connections
- Sync worker schedules
- Feature flags (which capabilities are enabled)
- Retention policies
- Rate limits (within platform-set maximums)
- Branding (logo, colors)
- LLM parameters (system prompts, model selection if multiple models offered)

### 5% Custom (Requires development or platform team involvement)

- Custom MCP server implementations for unique data sources
- Custom authentication flows (non-Azure AD identity providers)
- Custom compliance integrations (specific regulatory reporting)
- Data migration from existing knowledge platforms
- Custom embedding models or search strategies
- Enterprise API integrations not covered by standard MCP servers

---

## Go-to-Market for Multi-Tenant Platform

### Pricing Model Options

| Model                         | Description                                                  | Best For                                              | Risk                                        |
| ----------------------------- | ------------------------------------------------------------ | ----------------------------------------------------- | ------------------------------------------- |
| **Per-user/month**            | Flat fee per active user                                     | Simple, predictable, easy to compare to Copilot ($30) | Punishes adoption -- more users = more cost |
| **Per-index + per-user**      | Base fee per index connected + per-user for access           | Aligns cost with value (more indexes = more value)    | Complex to explain                          |
| **Usage-based**               | Pay per query, per LLM call, per search                      | Aligns cost with actual usage                         | Unpredictable costs scare enterprise buyers |
| **Tier-based**                | Starter / Professional / Enterprise tiers with feature gates | Simple to understand, encourages upgrades             | Requires careful tier design                |
| **Platform fee + per-tenant** | Annual platform fee + per-tenant subscription                | Ensures platform economics work                       | High initial cost barrier                   |

**Recommended model**: **Tier-based with usage-based overage**

- **Starter** ($15/user/month, max 5 indexes, max 2 MCP servers, basic analytics)
- **Professional** ($25/user/month, unlimited indexes, 10 MCP servers, full analytics, audit logs)
- **Enterprise** (Custom pricing, dedicated infrastructure option, unlimited everything, SLA, priority support)

This prices below Copilot ($30) at Professional tier while offering more data source flexibility, creating a compelling comparison.

### Competitive Positioning for Multi-Tenant

**Against Copilot**: "AI search that reaches beyond Microsoft 365. Connect Bloomberg, Oracle, SAP, and any proprietary data source via MCP -- with the enterprise RBAC your compliance team requires."

**Against Glean**: "Enterprise AI search you control. Deploy on your Azure, use your LLM, integrate your data sources -- at a fraction of Glean's cost and without vendor lock-in to their infrastructure."

**Against Custom RAG**: "Stop building. mingai gives you everything a custom RAG solution would -- RBAC, analytics, audit, MCP protocol -- in weeks instead of months, with ongoing updates instead of maintenance burden."

### Sales Motion

**Land**: Financial services firm (Segment 1) deploys for one business unit (100-200 users) with 3-5 Azure AI Search indexes and 1-2 MCP servers.

**Expand**: Success drives adoption to other business units. More indexes connected, more MCP servers, more users.

**Platform**: Multi-tenant deployment enables serving multiple enterprises from shared infrastructure, reducing per-customer cost.

### Key Success Metrics for Multi-Tenant Launch

| Metric                                  | Target            | Timeframe   |
| --------------------------------------- | ----------------- | ----------- |
| Tenants onboarded                       | 5 design partners | Month 0-6   |
| Self-service onboarding completion rate | >80%              | Month 6-12  |
| Time to first query (new tenant)        | <2 hours          | Month 6-12  |
| Tenant retention (12-month)             | >90%              | Month 12-24 |
| MCP marketplace servers available       | 10+               | Month 12-18 |
| Revenue per tenant (ARR)                | $50K-$200K        | Month 12-24 |
| Platform uptime                         | 99.9%             | Ongoing     |

---

## Technical Implications Summary

The multi-tenant transformation requires changes across every layer:

1. **Data layer**: PostgreSQL Row-Level Security (RLS) enforces tenant isolation at the database engine level. Every table includes `tenant_id` column with RLS policies using `current_setting('app.tenant_id')`. Cross-tenant data leakage is a critical security risk.

2. **Auth layer**: Federated identity supporting multiple Azure AD tenants. Tenant identification from auth token. Platform admin vs. tenant admin authorization.

3. **Search layer**: Tenant-scoped index isolation in Azure AI Search. Per-tenant search quotas. Tenant-aware index routing.

4. **MCP layer**: Tenant-scoped MCP server registrations. Shared marketplace servers with per-tenant credentials. Circuit breakers per tenant.

5. **Cache layer**: Tenant-scoped Redis keys. Cache invalidation must be tenant-aware. No cross-tenant cache leakage.

6. **Analytics layer**: Tenant-scoped analytics with platform aggregation for platform admin. Per-tenant cost tracking for billing.

7. **Infrastructure layer**: Tenant provisioning automation. Resource allocation and quotas. Scaling policies per tenant. Monitoring and alerting per tenant.

This is a 6-12 month engineering effort for a team of 3-5 engineers, assuming the current codebase is well-structured for the transition (which it appears to be, given the modular architecture).
