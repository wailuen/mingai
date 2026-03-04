# Tenant Admin User Flows

**Persona**: Tenant Admin (Organization IT Administrator)
**Scope**: Single-tenant management
**Role**: `tenant_admin` (scope: tenant)
**Date**: March 4, 2026

---

## Phase Mapping

| Flow | Flow Name                         | Built in Phase | Notes                                               |
| ---- | --------------------------------- | -------------- | --------------------------------------------------- |
| 01   | Tenant Onboarding (First Login)   | Phase 1        | Workspace setup wizard, part of tenant provisioning |
| 02   | SSO Configuration                 | Phase 3        | Auth0 integration, multi-provider SSO               |
| 03   | BYOLLM (Bring Your Own LLM)       | Phase 2        | Tenant LLM Setup, Enterprise BYOLLM                 |
| 04   | User Management                   | Phase 1        | Invite users, role assignment, deactivation         |
| 05   | Knowledge Base Setup              | Phase 1        | Index registration, SharePoint sync, MCP enablement |
| 06   | Cost Analytics                    | Phase 2        | Per-tenant cost tracking, budget alerts             |
| 07   | Role and Permission Customization | Phase 1        | Custom roles with index and MCP access control      |

---

## 1. Tenant Onboarding (First Login)

**Trigger**: Tenant admin receives welcome email after platform admin provisions tenant.

```
Start
  |
  v
[Tenant admin receives welcome email]
  |-- Subject: "Welcome to mingai -- Set up your organization"
  |-- Contains: one-time setup link with embedded tenant context
  |
  v
[Click setup link]
  |
  v
[Account creation / password setup]
  |-- If SSO pre-configured: redirect to identity provider
  |-- If local auth: set password (12+ chars, complexity enforced)
  |-- MFA enrollment (recommended for admins, required on Enterprise)
  |
  +-- ERROR: Link expired (72h TTL)
  |     |-> Contact platform admin to resend
  |     |-> Platform admin: POST /platform/tenants/{id}/resend-welcome
  |
  v
[First login successful]
  |
  v
[Workspace Setup Wizard -- Step 1: Organization Profile]
  |-- Organization display name (pre-filled from provisioning)
  |-- Logo upload (optional)
  |-- Primary color / theme (optional)
  |-- Time zone
  |-- Default language
  |
  v
[Step 2: Identity Provider Setup]
  |-- "How will your users sign in?"
  |   |-- Option A: Azure AD (Entra ID) -- most common
  |   |-- Option B: Google Workspace
  |   |-- Option C: Okta
  |   |-- Option D: SAML 2.0 (Enterprise only)
  |   |-- Option E: Email/password only (Starter plans)
  |
  +-- If SSO selected: redirect to SSO configuration flow (see Flow 2)
  +-- If password only: skip to Step 3
  |
  v
[Step 3: Create First Knowledge Index]
  |-- "Connect your first data source"
  |   |-- Option A: Azure AI Search index (enter endpoint + key)
  |   |-- Option B: SharePoint library (authorize connection)
  |   |-- Option C: Skip for now (configure later)
  |
  +-- If index configured: test connection
  |     |-- SUCCESS: "Connected! Found 12,450 documents"
  |     |-- FAILURE: "Cannot connect. Check endpoint URL and API key."
  |
  v
[Step 4: Invite First Users]
  |-- "Add team members to get started"
  |-- Bulk email input (comma-separated or one per line)
  |-- Assign initial role (default: "User")
  |-- Option: "I'll do this later"
  |
  v
[Step 5: Review & Launch]
  |-- Summary of configuration
  |-- "Launch AI Hub for your organization" button
  |
  v
[Wizard complete]
  |-- Redirect to Organization Dashboard
  |-- Checklist sidebar shows remaining setup items
  |   |-- [ ] Complete SSO configuration
  |   |-- [ ] Add more indexes
  |   |-- [ ] Configure roles and permissions
  |   |-- [ ] Review default settings
  |
  v
End
```

**Outcome**: Tenant operational with at least basic configuration.

**Error Paths**:

- Welcome email in spam -> platform admin can resend or provide direct link
- SSO misconfiguration -> fallback to password auth while fixing
- No data sources ready -> tenant operational but chat returns "no indexes configured"

---

## 2. SSO Configuration

**Trigger**: Tenant admin navigates to Settings > Authentication, or during onboarding wizard.

### Azure AD (Entra ID) Flow

```
Start
  |
  v
[Select "Azure AD (Entra ID)" as provider]
  |
  v
[Step 1: Azure App Registration]
  |-- Instructions displayed:
  |   1. Go to Azure Portal > App registrations > New registration
  |   2. Set redirect URI to: https://{tenant-slug}.aihub.com/auth/callback
  |   3. Enable ID tokens
  |   4. Create client secret
  |   5. Note: Application (client) ID, Directory (tenant) ID, Client secret
  |
  v
[Step 2: Enter Azure AD Details]
  |-- Azure AD Tenant ID (Directory ID)
  |-- Client ID (Application ID)
  |-- Client Secret (masked after save, stored in vault)
  |-- Redirect URI (auto-generated, read-only)
  |
  v
[Step 3: Configure Scopes]
  |-- Default scopes: openid, profile, email
  |-- Optional: Group.Read.All (for group-based role sync)
  |-- Optional: User.Read.All (for org chart in Azure AD MCP)
  |
  v
[Step 4: Group Mapping (Optional)]
  |-- Map Azure AD groups to tenant roles
  |   |-- Azure AD Group "Finance Team" -> Role "finance_access"
  |   |-- Azure AD Group "Engineering" -> Role "engineering_access"
  |   |-- Azure AD Group "IT Admins" -> Role "tenant_admin"
  |-- Sync interval: 24 hours (configurable)
  |
  v
[Click "Test Connection"]
  |
  +-- SUCCESS: Opens Azure AD login in popup
  |     |-- Admin logs in with their Azure AD credentials
  |     |-- Returns: "Connection successful. User: admin@acmecorp.com"
  |     |-- Group sync test: "Found 12 groups, 3 mapped to roles"
  |
  +-- FAILURE: Test fails
  |     |-- "Invalid client ID" -> verify App Registration
  |     |-- "Redirect URI mismatch" -> check Azure AD config
  |     |-- "Client secret expired" -> generate new secret in Azure
  |     |-- "Insufficient permissions" -> grant admin consent in Azure
  |     |-> Show specific error with remediation steps
  |     |-> Do NOT activate SSO on failure
  |
  v
[Click "Activate SSO"]
  |-- PUT /api/v1/admin/sso
  |-- Warning: "Activating SSO will require all users to sign in via Azure AD"
  |-- Confirm action
  |
  v
[SSO Active]
  |-- Login page shows "Sign in with Microsoft" button
  |-- Password login disabled (unless fallback configured)
  |-- Existing sessions remain valid until expiry
  |
  v
End
```

### Auth0-based Providers (Google, Okta)

```
[Select Google Workspace or Okta]
  |
  v
[System uses Auth0 as identity broker]
  |-- Auto-creates Auth0 connection for selected provider
  |-- Admin provides: domain, client credentials from provider
  |
  v
[Test -> Activate] (same as Azure AD flow)
```

### SAML 2.0 (Enterprise Only)

```
[Select SAML 2.0]
  |
  +-- Plan check: Is tenant on Enterprise plan?
  |     |-- NO: "SAML is available on Enterprise plans. Contact sales."
  |     |-- YES: Continue
  |
  v
[Configure SAML]
  |-- Identity Provider Metadata URL (or upload XML)
  |-- Entity ID
  |-- ACS URL (auto-generated)
  |-- Attribute mapping (email, name, groups)
  |
  v
[Test -> Activate] (same flow)
```

**Error Paths**:

- Admin locks themselves out via SSO misconfiguration -> platform admin can reset auth to password mode
- Group sync fails -> roles revert to direct assignments, alert tenant admin
- SSO provider outage -> users cannot log in; platform admin can enable temporary password fallback

---

## 3. BYOLLM (Bring Your Own LLM)

**Trigger**: Tenant admin navigates to Settings > LLM Providers.

```
Start
  |
  v
[Navigate to Settings > LLM Providers]
  |
  v
[View available providers]
  |-- Platform-provided providers (included in plan):
  |   |-- Azure OpenAI (GPT-5.2-chat, GPT-5-mini) -- Active
  |   |-- Google Gemini (Pro, Flash) -- Active
  |
  +-- Plan check: BYOLLM allowed?
  |     |-- Starter: NO -> "Upgrade to Professional for BYOLLM"
  |     |-- Professional / Enterprise: YES -> Show BYOLLM section
  |
  v
[Click "Add Your Own LLM Key"]
  |
  v
[Select Provider]
  |-- OpenAI (direct, not Azure)
  |-- Anthropic Claude
  |-- Deepseek
  |-- Alibaba DashScope
  |-- Bytedance Ark
  |-- Other (custom endpoint)
  |
  v
[Enter Configuration]
  |-- API key (encrypted, stored in tenant-scoped vault)
  |-- API endpoint (if custom)
  |-- Available models (auto-discovered or manually entered)
  |-- Monthly budget limit (optional, tenant self-imposed)
  |
  v
[Click "Test Connectivity"]
  |-- System sends a test prompt: "Respond with OK"
  |
  +-- SUCCESS: "Connected. Model: claude-3.5-sonnet. Latency: 240ms"
  |     |
  |     v
  |   [Save Configuration]
  |   |-- PUT /api/v1/admin/providers/byollm
  |   |-- Key encrypted and stored
  |   |-- Provider appears in tenant's model list
  |
  +-- FAILURE:
  |     |-- "Invalid API key" -> check key in provider dashboard
  |     |-- "Model not available" -> verify model access on provider side
  |     |-- "Rate limited" -> key may have insufficient quota
  |     |-> Do NOT save invalid configuration
  |
  v
[Set as Default (Optional)]
  |-- "Use this model as default for all users?"
  |   |-- Yes: All new conversations use BYOLLM model
  |   |-- No: Users can select in chat settings
  |
  v
End
```

**Error Paths**:

- BYOLLM key expires -> chat falls back to platform-provided LLM, alert tenant admin
- BYOLLM provider outage -> automatic fallback to platform provider, cost charged to platform allocation
- Budget exceeded -> switch to platform provider, notify admin

---

## 4. User Management

**Trigger**: Tenant admin navigates to Users section.

### Invite Users Flow

```
Start
  |
  v
[Navigate to Admin > Users]
  |
  v
[View user list]
  |-- Table: Name | Email | Role(s) | Last Active | Status
  |-- Filters: role, status, activity
  |-- Search by name or email
  |
  v
[Click "Invite Users"]
  |
  v
[Invitation Form]
  |-- Email addresses (bulk: comma-separated, paste from spreadsheet)
  |-- Assign roles (multi-select from tenant roles)
  |   |-- Default: "User" (chat access only)
  |   |-- Optional: custom roles with index access
  |-- Welcome message (optional custom text)
  |
  v
[Quota check]
  |-- Current users: 147 / 500 (Professional plan)
  |
  +-- Within quota: proceed
  +-- Over quota: "User limit reached. Remove inactive users or upgrade plan."
  |
  v
[POST /api/v1/admin/users/invite]
  |-- System sends invitation emails
  |-- Creates pending user records
  |
  +-- ERROR: Some emails invalid
  |     |-> Show which emails failed validation
  |     |-> Proceed with valid emails
  |     |-> "3 of 5 invitations sent. 2 invalid emails."
  |
  v
[Track invitations]
  |-- Pending invitations tab
  |-- Resend option for unaccepted invitations
  |-- Expiry: 7 days
  |
  v
End
```

### Role Assignment Flow

```
Start
  |
  v
[Click user row in user list]
  |
  v
[User Detail Panel]
  |-- Profile: name, email, department (from SSO)
  |-- Current roles: [default, finance_team]
  |-- Activity: last login, query count, feedback given
  |
  v
[Click "Manage Roles"]
  |
  v
[Role Assignment Interface]
  |-- Available roles (checkboxes):
  |   |-- [x] User (default, cannot remove)
  |   |-- [ ] Finance Access
  |   |-- [ ] Engineering Access
  |   |-- [x] Finance Team (currently assigned)
  |   |-- [ ] Tenant Manager
  |   |-- [ ] Analytics Viewer
  |
  v
[Save role changes]
  |-- POST /api/v1/admin/users/{user_id}/roles
  |-- Permission cache invalidated immediately (Redis pub/sub)
  |-- User's next request uses new permissions
  |-- Audit log: "Role changed for {user} by {admin}"
  |
  v
End
```

### Deactivation Flow

```
[Click "Deactivate User"]
  |
  v
[Confirm: "This will prevent {user} from logging in"]
  |-- Option: "Transfer conversations to another user" (optional)
  |-- Option: "Retain user data for audit purposes" (default: yes)
  |
  v
[POST /api/v1/admin/users/{user_id}/deactivate]
  |-- User status set to "inactive"
  |-- Active sessions revoked
  |-- User cannot log in
  |-- Data preserved
  |-- License freed (user count decreases)
  |
  v
End
```

---

## 5. Knowledge Base Setup

**Trigger**: Tenant admin navigates to Knowledge Base management.

### Create Azure AI Search Index

```
Start
  |
  v
[Navigate to Admin > Knowledge Base > Indexes]
  |
  v
[Click "Add Index"]
  |
  v
[Step 1: Connection Details]
  |-- Index name (display name for users)
  |-- Azure AI Search endpoint URL
  |-- API key (admin key for indexing, query key for search)
  |-- Index name in Azure (technical name)
  |
  v
[Step 2: Test Connection]
  |
  +-- SUCCESS: "Connected. Found index 'hr-policies' with 3,240 documents"
  |     |-- Displays: document count, fields detected, last updated
  |
  +-- FAILURE:
  |     |-- "Cannot reach endpoint" -> check URL, network
  |     |-- "Authentication failed" -> check API key
  |     |-- "Index not found" -> verify index name
  |     |-> Do NOT proceed until connection succeeds
  |
  v
[Step 3: Field Mapping]
  |-- Content field (required): which field contains document text
  |-- Title field: document title
  |-- URL field: source document link
  |-- Metadata fields: author, date, category
  |-- Embedding field: vector field for semantic search
  |
  v
[Step 4: Access Control]
  |-- Which roles can search this index?
  |   |-- All users (default)
  |   |-- Specific roles only (select from list)
  |-- This controls index-level RBAC in chat queries
  |
  v
[Step 5: Metadata]
  |-- Description (shown to users in index selector)
  |-- Category: HR, Finance, Engineering, Legal, General
  |-- Language: auto-detect / specific
  |-- Glossary terms associated with this index
  |
  v
[Save Index]
  |-- POST /api/v1/admin/indexes
  |-- Index available for chat queries immediately
  |-- Audit log: "Index '{name}' created by {admin}"
  |
  v
End
```

### SharePoint Sync Configuration

```
Start
  |
  v
[Click "Connect SharePoint Library"]
  |
  v
[Authorize SharePoint access]
  |-- OAuth flow to Microsoft Graph
  |-- Scopes: Sites.Read.All, Files.Read.All
  |
  v
[Select SharePoint site and library]
  |-- Browse sites: "HR Team Site", "Finance Portal", ...
  |-- Select library: "Policies", "Reports", ...
  |-- Select folders (optional: sync specific folders only)
  |
  v
[Configure sync schedule]
  |-- Frequency: hourly / daily / weekly
  |-- Initial sync: start immediately?
  |
  v
[Save and start sync]
  |-- Background worker picks up sync job
  |-- Progress shown: "Indexing... 240 of 1,200 documents"
  |
  +-- ERROR: Sync fails
  |     |-- Permission denied -> re-authorize with correct scopes
  |     |-- Document too large -> skip, log, notify admin
  |     |-- Rate limited by SharePoint -> auto-retry with backoff
  |
  v
End
```

### Enable MCP Servers

```
Start
  |
  v
[Navigate to Admin > Knowledge Base > External Sources]
  |
  v
[View available MCP servers]
  |-- Servers available on plan: Bloomberg, CapIQ, Perplexity, ...
  |-- Status: Enabled/Disabled per server
  |
  v
[Toggle "Enable" on Bloomberg MCP]
  |
  +-- Platform credentials: auto-configured
  +-- Tenant credentials required: prompt for API key
  |
  v
[Configure tenant-specific settings]
  |-- Access control: which roles can trigger Bloomberg tools?
  |-- Rate limits: override default? (within platform maximums)
  |
  v
[POST /api/v1/admin/mcp-servers/{id}/enable]
  |-- MCP tools available in chat for authorized users
  |
  v
End
```

---

## 6. Cost Analytics

**Trigger**: Tenant admin navigates to Analytics > Costs.

```
Start
  |
  v
[Navigate to Admin > Analytics > Cost]
  |
  v
[Cost Dashboard]
  |
  +-- Summary Cards
  |   |-- This month total: $2,340
  |   |-- LLM costs: $1,890 (81%)
  |   |-- Search costs: $320 (14%)
  |   |-- MCP costs: $130 (5%)
  |   |-- Budget remaining: $2,660 of $5,000
  |
  +-- Per-User Breakdown
  |   |-- Table: User | Queries | LLM Tokens | Cost | Avg/Query
  |   |-- Sort by: cost (descending)
  |   |-- Top user: j.smith@acme.com -- $89.20 (472 queries)
  |
  +-- Per-Index Breakdown
  |   |-- Table: Index | Queries | Avg Latency | Cost
  |   |-- "HR Policies": 1,240 queries, $340
  |   |-- "Finance Reports": 890 queries, $520
  |
  +-- Per-Model Breakdown
  |   |-- GPT-5.2-chat: 2,100 queries, $1,400
  |   |-- GPT-5-mini: 800 queries, $190
  |   |-- Claude 3.5 (BYOLLM): 400 queries, $300
  |
  +-- Trend Charts
  |   |-- Daily cost trend (30 days)
  |   |-- Weekly query volume
  |   |-- Cost per query trend
  |
  v
[Export options]
  |-- Download CSV (date range selector)
  |-- Schedule email report (weekly/monthly)
  |
  +-- ALERT: Budget threshold reached
  |     |-- "LLM budget at 85%. At current rate, budget exhausted by March 22."
  |     |-- Actions: increase budget, restrict usage, switch to cheaper model
  |
  v
End
```

---

## 7. Role and Permission Customization

**Trigger**: Tenant admin navigates to Roles.

```
Start
  |
  v
[Navigate to Admin > Roles & Permissions]
  |
  v
[View role list]
  |-- System roles (read-only):
  |   |-- User (default)
  |   |-- Tenant Admin
  |   |-- Tenant Manager
  |   |-- Analytics Viewer
  |
  |-- Custom roles:
  |   |-- Finance Team (3 indexes, 2 MCP servers)
  |   |-- Engineering (2 indexes, 0 MCP servers)
  |   |-- Executive (all indexes, all MCP servers)
  |
  v
[Click "Create Custom Role"]
  |
  v
[Role Builder]
  |-- Role name (required)
  |-- Description
  |
  +-- Index Access (checkboxes)
  |   |-- [x] HR Policies
  |   |-- [x] Finance Reports
  |   |-- [ ] Engineering Docs
  |   |-- [ ] Legal Contracts
  |
  +-- MCP Server Access (checkboxes)
  |   |-- [x] Bloomberg
  |   |-- [ ] Oracle Fusion
  |   |-- [x] Perplexity (web search)
  |
  +-- System Functions (checkboxes, plan-limited)
  |   |-- [ ] user:manage (User Management)
  |   |-- [ ] role:manage (Role Management)
  |   |-- [ ] index:manage (Index Management)
  |   |-- [ ] analytics:view_all (Analytics)
  |   |-- [ ] audit:view (Audit Logs)
  |   |-- [ ] kb:manage (Knowledge Base)
  |   |-- [ ] mcp:configure (MCP Configuration)
  |   |-- [ ] sso:configure (SSO Setup)
  |   |-- [ ] billing:view (Billing)
  |
  +-- Plan limit check
  |     |-- Starter: max 5 custom roles
  |     |-- Professional: max 50 custom roles
  |     |-- Enterprise: unlimited
  |
  v
[Save Role]
  |-- POST /api/v1/admin/roles
  |-- Role available for assignment immediately
  |
  v
[Assign to users/groups]
  |-- Direct assignment: select users
  |-- Group assignment: map to SSO group
  |
  v
End
```

**Error Paths**:

- Role in use and admin tries to delete -> "Cannot delete: 12 users assigned. Reassign first."
- Permission removed from role -> all affected users lose access immediately (cache invalidated)
- Plan downgrade removes custom roles -> roles marked "over-limit", no new assignments allowed

---

## Flow Summary

| Flow               | Trigger                   | Primary API                 | Key Failure Mode               |
| ------------------ | ------------------------- | --------------------------- | ------------------------------ |
| Onboarding         | Welcome email             | Wizard (multi-step)         | Expired link, no data sources  |
| SSO configuration  | Admin action / onboarding | PUT /admin/sso              | Misconfiguration, lockout      |
| BYOLLM             | Admin action              | PUT /admin/providers/byollm | Invalid key, provider outage   |
| User management    | Admin action              | POST /admin/users/invite    | Quota exceeded, invalid emails |
| Knowledge base     | Admin action              | POST /admin/indexes         | Connection failure, sync error |
| Cost analytics     | Admin action / alerts     | GET /admin/analytics/cost   | Budget overage                 |
| Role customization | Admin action              | POST /admin/roles           | Plan limits, deletion conflict |

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
