# Platform Admin User Flows

**Persona**: Platform Admin (SaaS Operator)
**Scope**: Cross-tenant platform management
**Role**: `platform_admin` (scope: platform)
**Date**: March 4, 2026

---

## Phase Mapping

| Flow | Flow Name                            | Built in Phase | Notes                                                        |
| ---- | ------------------------------------ | -------------- | ------------------------------------------------------------ |
| 01   | Platform Admin Bootstrapping         | Phase 1        | Core platform setup, part of tenant provisioning workflow    |
| 02   | Tenant Provisioning Wizard           | Phase 1        | Key Phase 1 deliverable: tenant CRUD + provisioning workflow |
| 03   | LLM Provider Configuration           | Phase 2        | Platform LLM Library management                              |
| 04   | Global A2A Agent Management          | Phase 4        | A2A agent registry and per-tenant routing                    |
| 05   | Billing and Quota Management         | Phase 6        | Billing integration with Stripe, usage-based pricing         |
| 06   | Platform Monitoring                  | Phase 6        | Per-tenant dashboards, SLA monitoring                        |
| 07   | Tenant Suspension and Deprovisioning | Phase 1        | Tenant lifecycle management, part of tenant CRUD             |
| 08   | Platform Admin Onboarding            | Phase 1        | Platform team management                                     |

---

## 1. Platform Admin Bootstrapping (First Admin)

**Trigger**: Initial platform deployment completes.

```
Start
  |
  v
[Deploy platform infrastructure]
  |-- PostgreSQL platform database created (RDS Aurora / Azure Flexible Server / Cloud SQL)
  |-- Auth0 tenant provisioned
  |-- Redis cluster online
  |-- Platform API healthy at /api/v1/platform/health
  |
  v
[Run bootstrap CLI command]
  platform-cli bootstrap --email admin@mingai-platform.com
  |
  v
[System creates platform_admin record]
  |-- Generates one-time setup token
  |-- Sends email with setup link
  |
  v
[Admin opens setup link]
  |
  v
[Set password + MFA enrollment]
  |-- Password: minimum 16 chars, complexity enforced
  |-- MFA: TOTP required for all platform admins
  |
  +-- ERROR: Email delivery fails
  |     |-> Retry via CLI: platform-cli resend-bootstrap --email ...
  |     |-> Fallback: generate link directly from CLI output
  |
  v
[Login to Platform Dashboard]
  |
  v
[Guided setup wizard]
  |-- Step 1: Configure platform name, logo, domain
  |-- Step 2: Add LLM providers (at least one required)
  |-- Step 3: Register global A2A agents (optional)
  |-- Step 4: Create first tenant (optional, can skip)
  |
  v
[Platform operational]
  |
  v
End
```

**Outcome**: Platform is ready to provision tenants.

**Error Paths**:

- Bootstrap fails due to database not ready -> verify infrastructure, retry
- Email service not configured -> CLI fallback with direct link output
- MFA device unavailable -> provide recovery codes during enrollment

---

## 2. Tenant Provisioning Wizard

**Trigger**: Platform admin clicks "New Tenant" on Platform Dashboard.

```
Start
  |
  v
[Platform Admin clicks "Create Tenant"]
  |
  v
[Step 1: Organization Details]
  |-- Tenant name (required, unique)
  |-- Slug (auto-generated, editable, URL-safe)
  |-- Custom domain (optional, Professional+ plans)
  |-- Primary contact email
  |
  +-- VALIDATION: Slug already taken
  |     |-> Suggest alternatives: acme-corp-1, acme-corporation
  |
  v
[Step 2: Plan Selection]
  |-- Starter: $15/user/mo, 25 users, 5 indexes, 3 A2A agents
  |-- Professional: $25/user/mo, 500 users, 50 indexes, all standard A2A agents
  |-- Enterprise: Custom, unlimited, dedicated DB option
  |
  v
[Step 3: SSO Pre-configuration]
  |-- Select identity provider type
  |   |-- Azure AD (Entra ID)
  |   |-- Google Workspace (via Auth0)
  |   |-- Okta (via Auth0)
  |   |-- SAML 2.0 (Enterprise only)
  |   |-- Local/password only (Starter)
  |
  +-- NOTE: Full SSO config done by Tenant Admin later
  |
  v
[Step 4: Initial Admin]
  |-- Admin email address (required)
  |-- Admin display name
  |-- Send welcome email checkbox (default: on)
  |
  v
[Step 5: Quotas & Limits]
  |-- Pre-filled from plan defaults
  |-- Overridable by platform admin
  |   |-- Max users
  |   |-- Max indexes
  |   |-- Max queries/day
  |   |-- LLM monthly budget (USD)
  |   |-- Storage allocation (GB)
  |
  v
[Step 6: Review & Confirm]
  |-- Summary of all settings
  |-- "Create Tenant" button
  |
  v
[POST /api/v1/platform/tenants]
  |
  +-- ERROR: Provisioning fails (DB creation error)
  |     |-> Show error details to platform admin
  |     |-> Automatic cleanup of partial resources
  |     |-> Log incident, suggest retry
  |
  v
[System executes provisioning]
  |-- Creates tenant record (status: "pending")
  |-- Creates PostgreSQL tables with RLS policies (tenant-scoped isolation)
  |-- Creates default roles (tenant_admin, tenant_manager, tenant_analyst, default)
  |-- Creates initial admin user record
  |-- Configures Auth0 connection stub
  |-- Sets quota limits
  |-- Sends welcome email to tenant admin
  |-- Updates tenant status to "active"
  |
  v
[Platform Dashboard updates]
  |-- New tenant appears in tenant list
  |-- Status: Active
  |-- Admin: awaiting first login
  |
  v
End
```

**Outcome**: Tenant provisioned, tenant admin receives welcome email.

**Decision Points**:

- Plan selection determines feature availability (BYOLLM, custom domain, SAML)
- SSO type constrains later configuration options
- Enterprise plan triggers manual approval workflow for dedicated DB

---

## 3. LLM Provider Configuration

**Trigger**: Platform admin navigates to Provider Management.

```
Start
  |
  v
[Navigate to Platform > Providers]
  |
  v
[View provider list]
  |-- Azure OpenAI: [Status] [Models] [Actions]
  |-- OpenAI: [Status] [Models] [Actions]
  |-- Anthropic Claude: [Status] [Models] [Actions]
  |-- Deepseek: [Status] [Models] [Actions]
  |-- Alibaba DashScope: [Status] [Models] [Actions]
  |-- Bytedance Ark: [Status] [Models] [Actions]
  |-- Google Gemini: [Status] [Models] [Actions]
  |
  v
[Click "Configure" on a provider]
  |
  v
[Provider Configuration Form]
  |-- API endpoint URL
  |-- API key (stored in vault, masked after save)
  |-- API version (provider-specific)
  |-- Available models (multi-select from provider catalog)
  |   |-- e.g., gpt-5.2-chat, gpt-5-mini for Azure OpenAI
  |-- Default model for new tenants
  |-- Rate limits (requests/minute, tokens/minute)
  |-- Cost tracking (cost-per-1K-tokens input/output)
  |
  v
[Click "Test Connection"]
  |
  +-- SUCCESS: Green checkmark, model list confirmed
  |     |
  |     v
  |   [Save Configuration]
  |     |
  |     v
  |   [PUT /api/v1/platform/providers/{id}]
  |     |-> Credentials encrypted and stored in vault
  |     |-> Provider status set to "active"
  |     |-> Audit log: "Provider configured by {admin}"
  |
  +-- FAILURE: Connection test fails
  |     |-- Invalid API key -> "Authentication failed. Verify API key."
  |     |-- Endpoint unreachable -> "Cannot reach endpoint. Check URL and network."
  |     |-- Model not available -> "Model X not available on this endpoint."
  |     |-> Do NOT save. Show error. Allow correction.
  |
  v
[Set Plan Tier Availability]
  |-- Which plans can access this provider?
  |   |-- Starter: Azure OpenAI only (cost control)
  |   |-- Professional: Azure OpenAI + OpenAI + Claude + Gemini
  |   |-- Enterprise: All providers
  |
  v
End
```

**Outcome**: LLM provider available for tenants on eligible plan tiers.

**Error Paths**:

- API key rotation needed -> update key, test, save; old key grace period 1 hour
- Provider outage -> circuit breaker activates, tenants fall back to secondary provider
- Cost overage on provider -> alert platform admin, optionally auto-throttle

---

## 4. Global A2A Agent Management

**Trigger**: Platform admin navigates to A2A Agents.

**Architecture note**: The 9 data integrations (Bloomberg, CapIQ, etc.) are **A2A agents** — autonomous LLM-powered agents. Each agent internally uses MCP to call its data source, but users never configure MCP directly. Platform admin registers agent templates; tenants configure credentials.

```
Start
  |
  v
[Navigate to Platform > A2A Agents]
  |
  v
[View A2A agent registry]
  |-- Bloomberg Intelligence Agent: Active | v2.1 | 8 tenants using
  |-- CapIQ Intelligence Agent: Active | v1.4 | 5 tenants using
  |-- Perplexity Web Search Agent: Active | v3.0 | 12 tenants using
  |-- Oracle Fusion Agent: Active | v1.2 | 3 tenants using
  |-- PitchBook Intelligence Agent: Beta | v0.9 | 1 tenant using
  |-- ... (9 agents total)
  |
  v
[Action: Register New A2A Agent Template]
  |
  v
[Step 1: Agent Registration]
  |-- Agent name (display name for tenants)
  |-- AgentCard URL (auto-discovers capabilities from /.well-known/agent.json)
  |-- Description
  |-- Category (Financial Data, HR, Project Management, Web Search)
  |-- Version
  |
  v
[Step 2: Agent Capabilities Discovery (from AgentCard)]
  |-- System fetches agent's AgentCard
  |-- Displays published skills (e.g., get_company_data, get_financials)
  |-- Verifies EATP trust attestation (for marketplace agents)
  |
  +-- ERROR: Cannot reach AgentCard endpoint
  |     |-> Verify agent URL and network access
  |     |-> Check EATP certificate validity
  |
  v
[Step 3: Access Control]
  |-- Plan tier availability (Starter / Pro / Enterprise)
  |-- Which roles can invoke this agent (platform-level default)
  |-- Rate limits per agent (invocations/min, invocations/day)
  |
  v
[Step 4: Credential Schema]
  |-- Define what credentials tenants must provide
  |   |-- Bloomberg: OAuth2 BSSO credentials (tenant-owned)
  |   |-- CapIQ: API key (tenant-owned)
  |   |-- Perplexity: API key (platform-managed shared OR tenant-owned)
  |-- OR: platform-level credentials (shared across tenants — e.g., Perplexity)
  |-- Credential validation rule (format, required fields)
  |
  v
[Step 5: Health Check Setup]
  |-- Health check interval (default: 60s — ping agent's health endpoint)
  |-- Timeout threshold (default: 10s — A2A task timeout)
  |-- Failure threshold before circuit break (default: 3)
  |
  v
[Register and Enable]
  |-- POST /api/v1/platform/a2a-agents
  |-- Health check begins immediately
  |-- Status: Active (or Degraded if health check marginal)
  |-- Agent appears in tenant agent catalog for eligible plan tiers
  |
  v
End
```

**Additional A2A Agent Management Flows**:

```
[Agent Version Update]
  Platform admin registers new agent version
  -> System performs rolling update (new AgentCard published)
  -> Old version remains available for 24h rollback window
  -> Tenant invocations automatically route to new version
  -> ERROR: New version incompatible -> auto-rollback, alert admin

[Access Control Change]
  Platform admin modifies plan tier access
  -> Tenants on removed tiers lose agent access at next session
  -> Active sessions: graceful degradation (agent returns "unavailable")
  -> Notification sent to affected tenant admins

[Agent Decommission]
  Platform admin marks agent for removal
  -> 30-day deprecation notice to all tenant admins using it
  -> Agent enters read-only mode at day 15
  -> Full removal at day 30
  -> ERROR: Tenant still actively using -> block removal, escalate
```

---

## 5. Billing and Quota Management

**Trigger**: Platform admin navigates to Billing.

```
Start
  |
  v
[Navigate to Platform > Billing]
  |
  v
[Billing Overview Dashboard]
  |-- Total platform revenue (MRR, ARR)
  |-- Revenue by plan tier (Starter / Pro / Enterprise)
  |-- Cost breakdown: LLM costs, search costs, storage costs
  |-- Margin analysis: revenue minus infrastructure costs
  |-- Month-over-month growth chart
  |
  v
[Click specific tenant]
  |
  v
[Tenant Billing Detail]
  |-- Current plan: Professional ($25/user/mo)
  |-- Active users this period: 147
  |-- Estimated bill: $3,675
  |-- LLM usage: $1,240 of $5,000 budget
  |-- Search queries: 4,200 of 10,000/day limit
  |-- Storage: 42 GB of 100 GB
  |-- A2A agent invocations: 12,400 this month
  |
  v
[Quota Management]
  |-- Adjust quotas per tenant
  |   |-- PUT /api/v1/platform/tenants/{id}/quotas
  |   |-- Can increase beyond plan defaults (override)
  |   |-- Can decrease (takes effect next billing cycle)
  |
  v
[Overage Alerts Configuration]
  |-- Set thresholds: 80%, 90%, 100% of each quota
  |-- Alert channels: email, webhook, SSE notification
  |-- Auto-action at 100%:
  |   |-- Option A: Block (hard limit)
  |   |-- Option B: Allow overage with per-unit charge
  |   |-- Option C: Alert only (soft limit)
  |
  +-- ALERT TRIGGERED: Tenant hits 90% LLM budget
  |     |-> Email to tenant admin: "You have used 90% of your LLM budget"
  |     |-> Platform admin notification: "Tenant X approaching limit"
  |     |-> Dashboard warning indicator on tenant card
  |
  v
End
```

**Error Paths**:

- Payment failure -> tenant enters grace period (7 days), then suspension
- Quota exceeded with hard limit -> tenant users see "Usage limit reached" message
- Billing data discrepancy -> audit trail available for reconciliation

---

## 6. Platform Monitoring

**Trigger**: Platform admin views health dashboard (also auto-triggers on alerts).

```
Start
  |
  v
[Platform Health Dashboard]
  |
  +-- Top-level metrics (real-time)
  |   |-- Active tenants: 23 / 23 healthy
  |   |-- Total active users (last 24h): 1,247
  |   |-- API latency P50/P95/P99: 120ms / 450ms / 1.2s
  |   |-- Error rate: 0.3%
  |   |-- LLM cost today: $342
  |
  +-- Per-tenant health cards
  |   |-- [Acme Corp] Active | 147 users | P95: 380ms | Healthy
  |   |-- [Globex Inc] Active | 52 users | P95: 1.8s | DEGRADED
  |   |-- [Initech] Suspended | 0 users | -- | Suspended
  |
  +-- Infrastructure status
  |   |-- PostgreSQL: Healthy (connections: 42/200, RLS active)
  |   |-- Redis: Healthy (2.1 GB of 6 GB)
  |   |-- Azure AI Search: Healthy (23 indexes)
  |   |-- A2A Agents: 8/9 healthy (PitchBook Intelligence: circuit open)
  |   |-- Auth0: Healthy
  |
  v
[Click degraded tenant: Globex Inc]
  |
  v
[Tenant Health Detail]
  |-- High latency cause: Large index (450K documents), slow queries
  |-- Recent errors: 12 timeout errors in last hour
  |-- LLM response times: elevated (Azure OpenAI region issue)
  |
  v
[Actions available]
  |-- Contact tenant admin (email)
  |-- Adjust tenant quotas
  |-- Suspend tenant (emergency)
  |-- View tenant audit logs
  |-- Open support ticket
  |
  v
End
```

**LLM Cost Aggregation Flow**:

```
[Daily cost aggregation job runs at 00:00 UTC]
  |
  v
[For each tenant]
  |-- Sum LLM token usage (input + output) by provider
  |-- Multiply by per-token cost rates
  |-- Sum search query costs
  |-- Sum A2A agent invocation costs
  |-- Sum storage costs
  |
  v
[Aggregate to platform level]
  |-- Total cost by provider
  |-- Total cost by tenant
  |-- Margin = tenant billing - infrastructure cost
  |
  v
[Store in analytics container]
  |-- Available on billing dashboard
  |-- Exported to billing system (Stripe)
  |
  v
[Alert if any tenant exceeds 80% budget]
```

---

## 7. Tenant Suspension and Deprovisioning

**Trigger**: Platform admin initiates suspension or deletion.

### Suspension Flow

```
Start
  |
  v
[Platform admin selects tenant, clicks "Suspend"]
  |
  v
[Confirm suspension]
  |-- Reason required (dropdown + free text)
  |   |-- Payment overdue
  |   |-- Terms of service violation
  |   |-- Security incident
  |   |-- Customer request
  |-- Suspension effective: Immediately / Scheduled
  |-- Notification: Send to tenant admin? (default: yes)
  |
  v
[POST /api/v1/platform/tenants/{id}/suspend]
  |
  v
[System actions]
  |-- Set tenant status to "suspended"
  |-- Active user sessions invalidated (JWT revocation broadcast)
  |-- New logins blocked (middleware returns 403: "Organization suspended")
  |-- Background jobs paused (sync workers, scheduled tasks)
  |-- Data preserved (no deletion)
  |-- Audit log entry created
  |-- Notification email sent to tenant admin
  |
  +-- ERROR: Suspension during active user sessions
  |     |-> Sessions terminated gracefully (SSE close event)
  |     |-> Users see: "Your organization's access has been suspended.
  |     |   Contact your administrator."
  |
  v
End (tenant suspended, data intact)
```

### Unsuspend Flow

```
[Platform admin clicks "Unsuspend"]
  -> POST /api/v1/platform/tenants/{id}/unsuspend
  -> Tenant status: "active"
  -> Logins re-enabled
  -> Background jobs resume
  -> Tenant admin notified
```

### Deprovisioning Flow

```
Start
  |
  v
[Platform admin clicks "Delete Tenant"]
  |
  v
[Safety checks]
  |-- Tenant must be suspended first (cannot delete active tenant)
  |-- Confirmation: type tenant name to confirm
  |-- Grace period: 30 days before permanent deletion
  |
  v
[Initiate deprovisioning]
  |-- Set status to "pending_deletion"
  |-- Schedule deletion job for 30 days out
  |-- Notify tenant admin: "Your data will be deleted on {date}"
  |-- Offer data export: "Download your data before {date}"
  |
  v
[Grace period: 30 days]
  |
  +-- Tenant admin requests cancellation
  |     |-> Platform admin unsuspends
  |     |-> Deletion cancelled
  |     |-> Status returns to "suspended" or "active"
  |
  +-- No cancellation: deletion proceeds
  |     |
  |     v
  |   [Permanent deletion job runs]
  |     |-- Export data archive (stored for 90 days)
  |     |-- Delete PostgreSQL tenant data (RLS-scoped DELETE + DROP tenant RLS policies)
  |     |-- Delete Azure AI Search indexes
  |     |-- Remove Auth0 connection
  |     |-- Purge Redis cache keys
  |     |-- Remove from billing system
  |     |-- Final audit log entry
  |     |-- Tenant record marked "deleted"
  |
  v
End
```

**Error Paths**:

- Deprovisioning fails mid-way -> partial deletion logged, manual cleanup flagged
- Data export exceeds size limits -> chunked export with download links
- Tenant admin disputes deletion -> grace period allows reversal

---

## 8. Platform Admin Onboarding (Additional Admins)

**Trigger**: Existing platform admin invites a new platform operator or admin.

```
Start
  |
  v
[Navigate to Platform > Team]
  |
  v
[Click "Invite Platform User"]
  |-- Email address
  |-- Role: Platform Admin / Platform Operator
  |-- Note: Platform Operator is read-only (monitoring, auditing)
  |
  v
[System sends invitation email]
  |-- Contains: one-time setup link
  |-- Expires in 72 hours
  |
  v
[Invitee clicks link]
  |
  v
[Account setup]
  |-- Set password (16+ chars required)
  |-- Enroll MFA (mandatory for platform roles)
  |-- Accept platform admin terms
  |
  +-- ERROR: Link expired
  |     |-> Existing admin resends invitation
  |
  v
[First login]
  |-- Dashboard tour (interactive walkthrough)
  |-- Quick reference: key actions, emergency procedures
  |
  v
End
```

---

## Flow Summary

| Flow                 | Trigger              | Primary API                         | Failure Mode                  |
| -------------------- | -------------------- | ----------------------------------- | ----------------------------- |
| Bootstrapping        | Deployment           | CLI + platform API                  | DB not ready, email failure   |
| Tenant provisioning  | Admin action         | POST /platform/tenants              | DB creation fail, email fail  |
| LLM provider config  | Admin action         | PUT /platform/providers/{id}        | Bad credentials, unreachable  |
| A2A agent management | Admin action         | POST /platform/a2a-agents           | Connection fail, incompatible |
| Billing & quotas     | Admin action / alert | PUT /platform/tenants/{id}/quotas   | Payment failure, overage      |
| Platform monitoring  | Continuous / alert   | GET /platform/health, /metrics      | Infrastructure degradation    |
| Suspension           | Admin action         | POST /platform/tenants/{id}/suspend | Active session disruption     |
| Deprovisioning       | Admin action         | DELETE /platform/tenants/{id}       | Partial deletion, disputes    |
| Admin onboarding     | Admin action         | POST /platform/team/invite          | Email failure, link expiry    |

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
