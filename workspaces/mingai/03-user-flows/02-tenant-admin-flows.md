# Tenant Admin User Flows

**Persona**: Tenant Admin (Organization IT Administrator)
**Scope**: Single-tenant management
**Role**: `tenant_admin` (scope: tenant)
**Date**: March 4, 2026

---

## Phase Mapping

| Flow | Flow Name                         | Built in Phase | Notes                                                     |
| ---- | --------------------------------- | -------------- | --------------------------------------------------------- |
| 01   | Tenant Onboarding (First Login)   | Phase 1        | Workspace setup wizard, part of tenant provisioning       |
| 02   | SSO Configuration                 | Phase 3        | Auth0 integration, multi-provider SSO                     |
| 03   | BYOLLM (Bring Your Own LLM)       | Phase 2        | Tenant LLM Setup, Enterprise BYOLLM                       |
| 04   | User Management                   | Phase 1        | Invite users, role assignment, deactivation               |
| 05   | Knowledge Base Setup              | Phase 1        | Index registration, SharePoint sync, A2A agent enablement |
| 06   | Cost Analytics                    | Phase 2        | Per-tenant cost tracking, budget alerts                   |
| 07   | Role and Permission Customization | Phase 1        | Custom roles with index and A2A agent access control      |
| 08   | SSO Group → RBAC Role Mapping     | Phase 3        | IdP group → tenant role auto-assignment on login          |
| 09   | Plan Upgrade / Downgrade          | Phase 1        | Self-service plan change, downgrade impact resolution     |
| 10   | Quota Warning — Tenant Response   | Phase 1        | Admin acts on quota alert: throttle, request increase     |

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
  |-- "Launch mingai for your organization" button
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
  |   2. Set redirect URI to: https://{tenant-slug}.mingai.ai/auth/callback
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
  |-- Optional: User.Read.All (for org chart via Azure AD Directory Agent)
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
  |-- System roles (checkboxes — cannot delete, read-only names):
  |   |-- [x] Viewer (default, cannot remove — basic chat access)
  |   |-- [ ] Reader (read access to assigned indexes)
  |   |-- [ ] Analyst (advanced features: research mode, analytics)
  |   |-- [ ] Tenant Admin (full workspace administration)
  |-- Custom roles:
  |   |-- [ ] Finance Access
  |   |-- [ ] Engineering Access
  |   |-- [x] Finance Team (currently assigned)
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

### Enable A2A Agents

```
Start
  |
  v
[Navigate to Admin > Agent Catalog]
  |
  v
[View available A2A agents]
  |-- Agents available on plan: Bloomberg Intelligence, CapIQ Intelligence,
  |   Perplexity Web Search, Oracle Fusion, AlphaGeo, Teamworks, PitchBook,
  |   Azure AD Directory, iLevel Portfolio
  |-- Status: Enabled/Disabled per agent
  |
  v
[Toggle "Enable" on Bloomberg Intelligence Agent]
  |
  +-- Platform credentials: auto-configured (if platform-managed)
  +-- Tenant credentials required: prompt for credentials
  |     |-- Bloomberg: "Enter your Bloomberg OAuth2 BSSO client credentials"
  |     |-- CapIQ: "Enter your S&P Capital IQ API key"
  |     |-- Oracle Fusion: "Enter your Oracle Cloud JWT assertion details"
  |
  v
[Validate credentials]
  +-- SUCCESS: "Bloomberg Intelligence Agent connected"
  +-- FAILURE: "Invalid credentials. Verify Bloomberg BSSO setup."
  |
  v
[Configure tenant-specific settings]
  |-- Access control: which roles can invoke this agent?
  |-- Rate limits: override default? (within platform maximums)
  |
  v
[POST /api/v1/admin/a2a-agents/{id}/enable]
  |-- Agent available in chat for authorized users
  |-- Platform enforces agent guardrails and credential isolation
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
  |   |-- Agent costs: $130 (5%)
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
  |-- System roles (read-only, canonical names — cannot rename or delete):
  |   |-- Viewer (default — basic chat access only)
  |   |-- Reader (access to assigned indexes, no admin functions)
  |   |-- Analyst (research mode, analytics view, knowledge base queries)
  |   |-- Tenant Admin (full workspace administration)
  |
  |-- Custom roles:
  |   |-- Finance Team (3 indexes, 2 A2A agents)
  |   |-- Engineering (2 indexes, 0 A2A agents)
  |   |-- Executive (all indexes, all A2A agents)
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
  +-- A2A Agent Access (checkboxes)
  |   |-- [x] Bloomberg Intelligence Agent
  |   |-- [ ] Oracle Fusion Agent
  |   |-- [x] Perplexity Web Search Agent
  |
  +-- System Functions (checkboxes, plan-limited)
  |   |-- [ ] user:manage (User Management)
  |   |-- [ ] role:manage (Role Management)
  |   |-- [ ] index:manage (Index Management)
  |   |-- [ ] analytics:view_all (Analytics)
  |   |-- [ ] audit:view (Audit Logs)
  |   |-- [ ] kb:manage (Knowledge Base)
  |   |-- [ ] agent:configure (Agent Configuration)
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

## 8. SSO Group → RBAC Role Mapping

**Trigger**: Tenant admin wants IdP groups to automatically assign tenant roles on login, eliminating manual role assignment for each new user.

```
Start
  |
  v
[Navigate to Admin > Settings > SSO > Group Mapping]
  |
  v
[View current mappings table]
  |-- Columns: IdP Group Name | Mapped Role | Users Affected | Last Synced
  |-- (empty if no mappings configured)
  |
  v
[Click "Add Mapping"]
  |
  v
[Mapping Form]
  |-- IdP Group Name: [type or browse — shows groups from SSO provider]
  |   |-- For Azure AD / SAML: group name or group Object ID
  |   |-- For Auth0: exact group claim value (e.g. "finance-team")
  |-- Mapped Tenant Role: [dropdown — system and custom roles]
  |   |-- Viewer (default)
  |   |-- Reader
  |   |-- Analyst
  |   |-- Tenant Admin
  |   |-- [any custom roles]
  |-- Priority: mapping order matters when user is in multiple groups
  |   |-- Higher priority mapping wins (e.g. Analyst > Viewer)
  |
  v
[Save Mapping]
  |-- POST /api/v1/admin/sso/group-mappings
  |-- Takes effect on next user login (JWT re-issued on re-auth)
  |
  v
[Example result after mapping setup]
  |-- Group "finance-team" → Role: Analyst
  |-- Group "hr-managers" → Role: Tenant Admin
  |-- Group "all-staff" → Role: Viewer (default, lowest priority)
  |
  v
[User logs in via SSO]
  |-- JWT contains groups: ["finance-team", "all-staff"]
  |-- System evaluates: finance-team → Analyst (higher priority wins)
  |-- User assigned Analyst role automatically
  |-- No manual invitation required
  |
  v
End
```

**Error Paths**:

- Group not found in IdP -> "Group name not recognized. Verify exact group name in your IdP."
- Circular priority conflict -> system uses alphabetical order to break ties
- User in no mapped groups -> falls back to Viewer (default)
- Mapping to Tenant Admin requires secondary confirmation: "Admin role mappings grant full workspace access. Confirm?"

---

## 9. Plan Upgrade / Downgrade

**Trigger**: Tenant admin navigates to billing settings, or receives quota warning prompting upgrade.

```
Start
  |
  v
[Navigate to Admin > Settings > Billing]
  |
  v
[Current Plan Summary]
  |-- Plan: Professional ($25/user/month)
  |-- Users: 147 / 500 (plan limit)
  |-- LLM Budget: $3,200 / $5,000 this month
  |-- Custom Roles: 12 / 50
  |-- Storage: 42 GB / 100 GB
  |-- Billing cycle: monthly, renews 2026-04-01
  |
  v
[Click "Change Plan"]
  |
  v
[Plan Comparison]
  |
  |-- Starter ($15/user/month)
  |   |-- 100 user limit
  |   |-- 5 custom roles
  |   |-- 10 GB storage
  |   |-- No BYOLLM
  |
  |-- Professional ($25/user/month) [CURRENT]
  |   |-- 500 user limit
  |   |-- 50 custom roles
  |   |-- 100 GB storage
  |   |-- BYOLLM: 1 provider
  |
  |-- Enterprise (custom pricing)
  |   |-- Unlimited users
  |   |-- Unlimited custom roles
  |   |-- Custom storage
  |   |-- Multi-BYOLLM, dedicated support
  |
  +-- UPGRADE (Professional → Enterprise)
  |     |
  |     v
  |   [Contact Sales]
  |   |-- Form: org size, use case, timeline
  |   |-- Sales team follows up within 1 business day
  |
  +-- DOWNGRADE (Professional → Starter)
        |
        v
      [Downgrade Warning]
        |-- "Downgrading will:
        |    ✗ Reduce user limit to 100 (you have 147 users — 47 will lose access)
        |    ✗ Reduce custom role limit to 5 (you have 12 — 7 roles will be deactivated)
        |    ✗ Remove BYOLLM access
        |    ✓ Existing data retained
        |
        |    Effective at end of current billing cycle (2026-04-01)."
        |
        |-- [Select which 47 users to deactivate] — admin must resolve over-limit
        |-- [Select which 7 custom roles to deactivate]
        |
        v
      [Confirm Downgrade]
        |-- Scheduled for 2026-04-01
        |-- Email confirmation sent
        |-- Admin reminded 7 days before effective date
        |
        v
      End
```

**Error Paths**:

- Downgrade would leave tenant over-limit with no resolution -> "Resolve over-limit users and roles before downgrading."
- Payment method on file expired -> prompt to update payment before plan change
- Enterprise downgrade requires sales team approval -> cannot self-serve

---

## 10. Quota Warning — Tenant Admin Response

**Trigger**: Tenant admin receives an in-app notification and email: "Your workspace has used 85% of its monthly token quota."

```
Start
  |
  v
[Tenant admin receives quota warning]
  |-- In-app notification banner (orange, top of all pages):
  |   "Token quota at 85%. Estimated to run out by March 22 at current usage."
  |   [View Usage] [Request More]
  |-- Simultaneous email to tenant admin(s):
  |   Subject: "mingai quota warning — action may be required"
  |   Body: current usage, projected exhaustion date, links to actions
  |
  v
[Admin clicks "View Usage"]
  |
  v
[Analytics > Cost (usage detail)]
  |-- Summary:
  |   |-- Tokens used this month: 425,000 / 500,000 (85%)
  |   |-- Days remaining in billing cycle: 8
  |   |-- Projected usage at current rate: 550,000 tokens
  |   |-- Projected overage: 50,000 tokens (~$1.05 at overage rate)
  |
  |-- Per-user usage table (sorted by tokens consumed):
  |   |-- j.smith@acme.com: 68,000 tokens (16%)
  |   |-- m.jones@acme.com: 54,000 tokens (13%)
  |   |-- ...
  |
  |-- Usage spike annotation (if any):
  |   "2026-03-01: 42,000 tokens (5x daily average) — bulk session"
  |
  v
[Admin decides on action]

  +-- ACTION A: Do nothing (overage auto-billed)
  |     |-- System continues allowing queries past quota
  |     |-- Each token above quota charged at overage rate ($0.021/1000)
  |     |-- Tenant admin notified of overage charges at end of billing cycle
  |     |-- Platform admin sees projected overage in Cost Monitoring
  |
  +-- ACTION B: Restrict usage to prevent overage
  |     |
  |     v
  |   [Settings > Usage Limits > Token Throttle]
  |   |-- Throttle mode: [Warn users | Block queries above daily limit]
  |   |-- Daily token budget: [set per-day cap]
  |     e.g. "14,000 tokens/day remaining budget ÷ 8 days = 1,750/day"
  |   |-- Warning message shown to end users:
  |     "Workspace is near its monthly limit. Some queries may be delayed."
  |   Admin saves → throttle active immediately
  |   Users exceeding daily budget see: "Your daily query limit has been
  |     reached. Queries resume tomorrow at midnight (UTC)."
  |
  +-- ACTION C: Request a quota increase from platform admin
  |     |
  |     v
  |   [Click "Request More Tokens"]
  |   |
  |   v
  |   [Quota Increase Request Form]
  |   |-- Requested additional tokens: [+50,000 | +100,000 | +250,000 | custom]
  |   |-- Justification (required for platform admin approval):
  |   |   [text box — "We ran a large document batch process on March 1st.
  |   |    Normal usage will resume. We need 50,000 additional tokens
  |   |    to finish the month without disruption."]
  |   |-- Urgency: [Not urgent | Urgent — queries will stop within 24h]
  |   |
  |   v
  |   [Submit Request]
  |   |-- POST /api/v1/admin/quota/increase-request
  |   |-- Platform admin receives alert in dashboard (see 11-platform-admin-ops-flows, Flow 9)
  |   |-- Tenant admin sees: "Request submitted. Platform team notified."
  |   |-- Status: "Pending Approval"
  |   |
  |   v
  |   BRANCH: Platform admin approves override
  |     |-- Tenant admin notified in-app + email:
  |     |   "Your quota has been increased by 50,000 tokens for this month.
  |     |    Our team may follow up to discuss your usage."
  |     |-- Quota banner updates: "500,000 + 50,000 override = 550,000 tokens"
  |     |-- Status: "Approved"
  |
  |   BRANCH: Platform admin denies request
  |     |-- Tenant admin notified:
  |     |   "Your quota increase request was not approved this month.
  |     |    [Reason: e.g. 'Usage spike appears resolved — remaining quota
  |     |    should be sufficient'] Contact support if you need assistance."
  |     |-- Status: "Declined"
  |     |-- Tenant admin may fall back to ACTION A or B
  |
  +-- ACTION D: Upgrade plan to get higher base quota
        |
        v
      [Click "Upgrade Plan" (from quota warning banner)]
        → Redirects to Plan Comparison screen (see Flow 9)
        Note: Enterprise plan has custom quota; upgrading from Professional
        starts a sales conversation for quota renegotiation
  |
  v
End
```

**Error Paths**:

- Quota exhausted mid-conversation -> current query completes (grace: 1 query), next query blocked with: "Monthly token quota reached. Contact your administrator."
- Throttle setting removes itself at billing cycle reset (1st of month) — admin must re-set each month if desired
- Multiple tenant admins submit duplicate increase requests → system deduplicates; platform admin sees one consolidated request

---

## Flow Summary

| Flow                   | Trigger                    | Primary API                        | Key Failure Mode                          |
| ---------------------- | -------------------------- | ---------------------------------- | ----------------------------------------- |
| Onboarding             | Welcome email              | Wizard (multi-step)                | Expired link, no data sources             |
| SSO configuration      | Admin action / onboarding  | PUT /admin/sso                     | Misconfiguration, lockout                 |
| BYOLLM                 | Admin action               | PUT /admin/providers/byollm        | Invalid key, provider outage              |
| User management        | Admin action               | POST /admin/users/invite           | Quota exceeded, invalid emails            |
| Knowledge base         | Admin action               | POST /admin/indexes                | Connection failure, sync error            |
| Cost analytics         | Admin action / alerts      | GET /admin/analytics/cost          | Budget overage                            |
| Role customization     | Admin action               | POST /admin/roles                  | Plan limits, deletion conflict            |
| SSO group → role map   | Admin action               | POST /admin/sso/group-mappings     | Group not found, circular priority        |
| Plan upgrade/downgrade | Admin action / quota alert | PATCH /admin/billing/plan          | Over-limit users/roles blocking downgrade |
| Quota warning response | System alert               | POST /admin/quota/increase-request | Request denied, quota exhausted mid-query |

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
