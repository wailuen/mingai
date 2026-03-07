# 31. Tenant Admin Capability Specification

> **Status**: Architecture Design
> **Date**: 2026-03-05
> **Purpose**: Comprehensive specification of all capabilities available to a tenant administrator — the person responsible for setting up, configuring, and operating their organization's mingai workspace.
> **Depends on**: `19-sharepoint-sync-architecture.md`, `22-google-drive-sync-architecture.md`, `23-glossary-management-architecture.md`, `24-platform-rbac-specification.md`

---

## Overview

The tenant admin is the **organizational operator** of a mingai workspace. They are responsible for everything inside their tenant boundary: who can access what, which documents are indexed, how the AI behaves for their users, and whether their users are getting value. Unlike the platform admin (who manages all tenants), the tenant admin manages exactly one tenant — their own organization.

### Seven Capability Domains

| Domain                                   | Description                                                  | Setup or Ongoing                      |
| ---------------------------------------- | ------------------------------------------------------------ | ------------------------------------- |
| 1. Workspace Setup & Administration      | Configure the tenant workspace, branding, basic settings     | One-time setup                        |
| 2. Identity & Document Store Integration | SSO, SharePoint, Google Drive — connect identity and content | One-time setup + periodic maintenance |
| 3. Document Sync Monitoring              | Monitor RAG index health, sync status, re-indexing           | Ongoing                               |
| 4. Glossary Management                   | Maintain the organization's AI terminology dictionary        | Ongoing                               |
| 5. User & Agent RBAC                     | Control who accesses which knowledge bases and agents        | Ongoing                               |
| 6. Agent Workspace                       | Adopt from library, build new agents in agent studio         | Ongoing                               |
| 7. User Feedback & Resolution            | Monitor satisfaction signals, resolve reported issues        | Ongoing                               |

---

## Domain 1: Workspace Setup and Administration

### 1.1 Initial Setup Wizard

When a tenant is provisioned by the platform admin, the tenant admin receives an invite email and completes a guided setup wizard:

**Step 1: Account Activation**

- Tenant admin sets their password / completes SSO-linked account setup
- Accepts terms of service

**Step 2: Workspace Identity**

- Display name: e.g., "Acme Corp AI Workspace"
- Workspace logo upload (used in header, email templates)
- Default timezone (used for reports, scheduled syncs)
- Locale / language preference (English, future: multilingual)

**Step 3: Choose Authentication Mode**

- Option A: Platform-managed authentication (email/password, MFA)
- Option B: SSO — configure in Domain 2

**Step 4: Choose LLM Profile** (selection from platform-published profiles)

- Cost-Optimized, Balanced, Premium, Vision-Enabled
- Description shown for each: "Best for..." guidance written by platform admin
- Selection can be changed later

**Step 5: Connect Your First Document Store** (optional at setup)

- Skip: "I'll connect documents later"
- SharePoint: guided connection wizard
- Google Drive: guided connection wizard

**Step 6: Invite Your Users**

- Add email addresses for first batch of users (optional)
- Choose default role for invited users

Wizard completes → Workspace is live.

### 1.2 Ongoing Administration

| Task                     | Description                                                            |
| ------------------------ | ---------------------------------------------------------------------- |
| Workspace settings       | Display name, logo, timezone, locale                                   |
| LLM profile change       | Switch from Balanced to Premium when budget allows                     |
| Plan and quota status    | View current token consumption, days remaining in period               |
| Billing view             | Invoice history, plan details (cannot modify — contact platform admin) |
| Notification preferences | Which alerts come to the tenant admin email vs dashboard-only          |
| API key management       | Generate/revoke API keys for programmatic access                       |
| Audit log access         | View all actions taken within the tenant by all users                  |

---

## Domain 2: Identity and Document Store Integration

### 2.1 SSO Configuration (One-Time Setup)

**Supported protocols**: SAML 2.0, OIDC

**SAML 2.0 Setup Flow**:

1. Tenant admin navigates to Settings → Authentication → SSO
2. Downloads mingai's SAML Service Provider metadata XML
3. In their IdP (Entra ID / Okta / Google Workspace), creates a new SAML application:
   - Entity ID: `https://{tenant-slug}.mingai.io/saml/metadata`
   - ACS URL: `https://{tenant-slug}.mingai.io/saml/acs`
   - Attribute mappings: `email` → `NameID`, `displayName` → `display_name`, `groups` → `groups`
4. Downloads IdP metadata XML → uploads to mingai SSO config
5. Tests SSO login → confirms attributes are received correctly
6. Enables SSO → existing email/password login optionally disabled

**OIDC Setup Flow**:

1. Tenant admin creates OIDC app in their IdP
2. Provides: `client_id`, `client_secret`, `issuer_url`
3. mingai auto-discovers configuration from `{issuer_url}/.well-known/openid-configuration`
4. Tests flow → enables

**JIT Provisioning**: When a user SSO-authenticates for the first time, a mingai account is automatically created with the default role. Subsequent logins use the existing account.

**Group-to-Role Sync** (optional): If the IdP sends a `groups` claim, tenant admin can map IdP groups to mingai roles:

- `SSO_Group: "Engineering"` → mingai role: `analyst`
- `SSO_Group: "HR_Admins"` → mingai role: `tenant_admin`
  Mapping UI: table with IdP group name → mingai role selector.

### 2.2 SharePoint Connection

**Auth Model**: Azure Entra ID App Registration with application-level permissions (no interactive user consent required for sync).

**Step-by-Step Permission Provisioning (tenant admin guidance)**:

**In Azure Portal (Entra ID)**:

1. Navigate to `portal.azure.com` → Entra ID → App Registrations → New Registration
   - Name: "mingai SharePoint Connector — [Tenant Name]"
   - Supported account types: "Accounts in this organizational directory only"
   - Redirect URI: leave blank (not needed for app-only auth)

2. After creation, note the **Application (client) ID** and **Directory (tenant) ID**

3. Create a client secret:
   - Certificates & Secrets → Client Secrets → New Client Secret
   - Expiry: 24 months (recommended; set a calendar reminder to rotate before expiry)
   - Copy the **Value** immediately — it is not shown again

4. Add Microsoft Graph API permissions:
   - API Permissions → Add a Permission → Microsoft Graph → Application Permissions
   - Add: `Sites.Read.All` (read-only access to all SharePoint sites)
   - If write-back features needed in future: `Sites.ReadWrite.All`
   - **Grant Admin Consent**: requires a Global Administrator to click "Grant admin consent for {tenant}"

5. (Optional, for SharePoint app-only access without Graph):
   - Some older SharePoint sites require PnP SharePoint app-only permissions in addition to Graph
   - Navigate to: `https://{tenant}.sharepoint.com/_layouts/15/appregnew.aspx`
   - Register app with same client ID, generate client secret
   - Then at: `https://{tenant}.sharepoint.com/_layouts/15/appinv.aspx`
   - Grant site collection access with permission XML:
     ```xml
     <AppPermissionRequests AllowAppOnlyPolicy="true">
       <AppPermissionRequest Scope="http://sharepoint/content/tenant"
                            Right="Read"/>
     </AppPermissionRequests>
     ```

**In mingai (entering credentials)**:

- Tenant ID: Directory (tenant) ID from Azure
- Client ID: Application (client) ID from Azure
- Client Secret: the secret value copied in step 3

**Testing**: After saving, click "Test Connection" → system calls `GET /v1.0/sites` to verify permissions → shows accessible sites list.

**Credential Storage**: Client secret encrypted at rest using AES-256, stored in Azure Key Vault scoped to the tenant. Credentials are used only by the sync worker, never exposed in API responses.

**Scope Limitation**: `Sites.Read.All` grants read access to ALL SharePoint sites in the Microsoft 365 tenant. If the organization wants to limit mingai to specific sites only:

- Use `Sites.Selected` permission (Graph API limited-scope access)
- Requires additional configuration: grant access to specific site collections via SharePoint admin center or PnP PowerShell
- Recommended for enterprise tenants with sensitive sites

**Token Refresh**: Client credentials tokens expire every 1 hour. The sync worker automatically refreshes tokens 60 seconds before expiry (see `19-sharepoint-sync-architecture.md`).

### 2.3 Google Drive Connection

**Auth Model A: Service Account + Domain-Wide Delegation (Google Workspace customers)**

**Step-by-Step Permission Provisioning**:

**In Google Cloud Console**:

1. Create or select a Google Cloud Project
   - `console.cloud.google.com` → New Project → "mingai-connector-{company}"

2. Enable APIs:
   - Library → Search "Google Drive API" → Enable
   - Library → Search "Admin SDK API" → Enable (needed for Workspace user directory)

3. Create a Service Account:
   - IAM & Admin → Service Accounts → Create Service Account
   - Name: "mingai-drive-sync"
   - Grant no roles at project level (DWD provides access, not IAM roles)
   - Create and download JSON key file

4. Note the **client_email** and **private_key** from the JSON file

**In Google Workspace Admin Console** (`admin.google.com`):

5. Security → API Controls → Domain-Wide Delegation → Add New
   - Client ID: the numeric client ID from the service account JSON (the `client_id` field)
   - OAuth Scopes:
     ```
     https://www.googleapis.com/auth/drive.readonly
     https://www.googleapis.com/auth/drive.metadata.readonly
     ```
   - Note: `drive.readonly` grants read access to ALL files the impersonated user can access

6. Create a **dedicated sync service account** in Google Workspace:
   - Admin Console → Users → Add New User
   - Name: "mingai Sync Service" / Email: `mingai-sync@{company-domain}.com`
   - This is a real Workspace user, NOT the service account email
   - Grant this user access to the folders/Shared Drives to be indexed
   - **IMPORTANT**: The service account impersonates this user. If the sync user does not have access to a folder, it will not be indexed.

**In mingai**: 7. Upload the service account JSON key file 8. Enter the sync user email: `mingai-sync@{company-domain}.com` 9. System verifies: lists accessible drives/folders as the sync user

**Why a real Workspace user, not the service account email**:
The Google Drive API impersonation requires impersonating a real user in the domain. The service account email (`mingai-drive-sync@{project}.iam.gserviceaccount.com`) is not a Workspace user and cannot be impersonated via DWD. A real Workspace user acts as the "sync identity" — Google Drive access is determined by what this user can see.

**Auth Model B: OAuth 2.0 (non-Workspace or simpler setups)**

For tenants without Google Workspace Admin access:

1. Tenant admin clicks "Connect Google Drive" → redirected to Google OAuth consent
2. Signs in as their Google account → grants drive.readonly access
3. Tokens stored (access + refresh) per tenant
4. **Limitation**: syncs only files the consenting user owns or has explicit access to (no organizational-level access)

**Scope Limitation**: `drive.readonly` reads all files the sync user can access. For tighter control:

- Remove access from the sync user to sensitive folders in Drive
- mingai does not support folder-level exclusions yet (planned: folder exclusion list in sync config)

### 2.4 Connection Health Monitoring

After initial connection setup, the system monitors connection health:

- Daily credential validation check (token refresh / OAuth token renewal)
- Alert to tenant admin if credentials expire or are revoked:
  - SharePoint: client secret expiry warning 30 days before, hard failure after expiry
  - Google Drive: OAuth token refresh failure (refresh token may expire if user revokes access)
- Re-connection wizard available in Settings → Integrations → [Provider] → Reconnect

---

## Domain 3: Document Sync Monitoring

### 3.1 Sync Dashboard

The tenant admin sees a unified sync dashboard across all connected document stores.

**Status Panel per Source**:

```
SharePoint: "Contoso HR Portal"
  Status: Healthy
  Last sync: 5 minutes ago
  Documents: 1,247 indexed | 23 pending | 0 failed
  Next full scan: 2026-03-06 02:00 UTC

Google Drive: "Finance Team Drive"
  Status: Warning ⚠️
  Last sync: 2 hours ago (scheduled: every 30 minutes)
  Documents: 834 indexed | 0 pending | 12 failed
  Error: "Permission denied on 12 files — sync user lacks access"
  Action: [View Failed Files] [Fix Permissions]
```

### 3.2 Manual Sync Controls

| Control                 | Description                                                                               |
| ----------------------- | ----------------------------------------------------------------------------------------- |
| Trigger immediate sync  | Force sync of a specific source now (do not wait for schedule)                            |
| Pause sync              | Temporarily stop syncing a source (maintenance mode)                                      |
| Re-index specific files | Select failed/stale files → force re-index                                                |
| Full re-index           | Wipe and rebuild the entire index for a source (expensive operation, shows cost estimate) |
| Delete source           | Remove source and all indexed documents                                                   |

### 3.3 Index Health Indicators

- **Total documents indexed** across all sources
- **Last indexed per source**: timestamp with freshness indicator (green < 1 hour, yellow < 24 hours, red > 24 hours)
- **Failed documents**: count + list with error reason per file
- **Document type breakdown**: PDF / DOCX / XLSX / PPTX / other (pie chart)
- **Index size**: storage consumed (informs platform quota usage)

### 3.4 Sync Schedule Configuration

Per source, tenant admin can configure:

- Sync frequency: Real-time (webhook-driven), every 15 min, every 30 min, every 1 hour, every 6 hours, daily (at a specific time)
- Full scan frequency: Daily, weekly, monthly (detects deletions in source — incremental sync misses deletes)
- Notification preferences: "Notify me when sync fails for > 2 hours"

**Platform constraint**: Minimum sync frequency is plan-tier limited:

- Starter: minimum 1 hour
- Professional: minimum 15 minutes
- Enterprise: minimum real-time (webhook)

---

## Domain 4: Glossary Management

### 4.1 Glossary Purpose

The organizational glossary teaches the AI the organization's proprietary terminology, abbreviations, and domain-specific concepts. Without it, the AI may misinterpret company-specific terms.

Example:

- "EMEA" → "Europe, Middle East, and Africa — our largest revenue region"
- "Project Falcon" → "Internal codename for our digital transformation program, launched Q1 2026"
- "PO" → "Purchase Order in financial contexts; Product Owner in engineering contexts"

### 4.2 Glossary Entry Structure

| Field        | Description                                               | Example                               |
| ------------ | --------------------------------------------------------- | ------------------------------------- |
| Term         | The word or phrase                                        | "QBR"                                 |
| Full form    | Expansion of abbreviation (optional)                      | "Quarterly Business Review"           |
| Definition   | What it means in organizational context                   | "Monthly executive review meeting..." |
| Context tags | When this definition applies                              | ["finance", "sales"]                  |
| Scope        | Who can see it: All users / specific roles / specific KBs | All users                             |

### 4.3 Glossary Operations

**Add entry**: Individual form or bulk import via CSV
**Edit entry**: Change definition, add context, change scope
**Delete entry**: Removes from AI context immediately
**Search**: Full-text search of term + definition
**Import**: CSV upload (term, full_form, definition columns minimum)
**Export**: CSV download of all glossary entries (for backup/review)
**Versioning**: Each edit creates a revision with timestamp + editor — can roll back

### 4.4 Prompt Injection Protection

Glossary terms are injected into the system message of every AI query (not user message). This prevents prompt injection attacks — a malicious user cannot override glossary by crafting a query that says "ignore the glossary." The system message is platform-controlled and not visible to end users.

**Character limits enforced**: Maximum 200 characters per definition (to prevent glossary from consuming the context window). Maximum 500 glossary entries per tenant.

### 4.5 Glossary Analytics

- **Usage**: Which terms appear in AI responses (track when a glossary term was referenced)
- **Misses**: Terms that appear in user queries but have no glossary entry (signals for new entries)
- **Quality signals**: Satisfaction rate of responses containing glossary terms vs not (did glossary help?)

---

## Domain 5: User and Agent RBAC

### 5.1 User Role Model (Tenant-Level)

mingai has a tenant-level user role model separate from the platform RBAC:

| Role           | Description                  | Default Capabilities                                                        |
| -------------- | ---------------------------- | --------------------------------------------------------------------------- |
| `tenant_admin` | Full workspace control       | All settings, all KBs, all agents, user management                          |
| `analyst`      | Power user with broad access | Query all assigned KBs, use all assigned agents, create agent conversations |
| `reader`       | Standard user                | Query assigned KBs, use assigned agents, read-only                          |
| `viewer`       | Restricted user              | Query only (no agent interaction), no history export                        |

### 5.2 Knowledge Base (KB / RAG) Access Control

Each knowledge base (document source index) can be access-controlled independently.

**KB visibility modes**:

- **Workspace-wide**: All users can query this KB
- **Role-restricted**: Only users with specific roles (e.g., `analyst` only)
- **User-specific**: Specific named users have access (for sensitive KBs like HR, Legal)
- **Agent-only**: KB not directly queryable by users; only accessible by specific agents

**Setting KB access**:

```
Settings → Knowledge Bases → [KB Name] → Access Control
  Visibility: [Role-Restricted]
  Roles with access: [analyst] [tenant_admin]
  Or: specific users: [user@company.com] [user2@company.com]
```

### 5.3 Agent Access Control

Each agent deployed in the workspace can be access-controlled independently.

**Agent visibility modes**:

- **Workspace-wide**: All users see and can interact with this agent
- **Role-restricted**: Only specific roles
- **User-specific**: Named users only
- **Hidden**: Not visible in agent list (for internal/system agents)

**Setting agent access**:

```
Settings → Agents → [Agent Name] → Access Control
  Visibility: [Role-Restricted]
  Roles: [analyst]
  Note: Users without access do not see this agent in the UI
```

### 5.4 User Management

**Invite users**:

- Enter email address, select initial role, optionally assign to specific KBs
- Invitation email sent with setup link
- Invited users appear as "Pending" until they accept

**Bulk invite**: CSV upload with email, role, KB assignments

**Edit user**:

- Change role (immediate effect — JWT invalidated, new token issued on next request)
- Change KB/agent assignments
- Suspend: user cannot login but data is preserved
- Delete: user removed, conversations anonymized

**User directory**: Table of all users with role, last login, status, KB/agent count

**SSO sync** (if SSO + group mapping configured):

- Role changes via IdP group changes reflected within 1 login cycle
- Tenant admin can also override SSO-assigned roles manually

### 5.5 Access Request Workflow (optional)

When enabled, users can request access to a KB or agent they do not have access to:

1. User sees agent/KB with "Request Access" button
2. User submits request with reason
3. Tenant admin receives notification
4. Approve/Deny with optional message to user
5. If approved: access granted immediately

---

## Domain 6: Agent Workspace

### 6.1 Agent Library (Adopt)

The agent library contains platform-published agent templates. The tenant admin can browse and deploy them.

**Library browser**:

- Filter by: category (HR, Finance, Legal, Customer Support, Technical), plan tier eligibility, tag
- Each template shows: name, description, version, satisfaction score (aggregate across all tenants, anonymized), variables required

**Adopt workflow**:

1. Tenant admin selects a template
2. Views: system prompt (read-only), required variables, example conversations
3. Clicks "Deploy Agent"
4. Fills required variables:
   - `{{company_name}}` → "Acme Corp"
   - `{{jurisdiction}}` → "US Federal + California"
   - `{{focus_areas}}` → "employment contracts, IP clauses"
5. Sets agent name (visible to end users): "Acme Legal Assistant"
6. Sets access control: who can see this agent
7. Click "Deploy" → agent is live in the workspace

**Template upgrades**: When the platform admin publishes a new template version, the tenant admin sees an upgrade notification. They control when (or whether) to upgrade their deployed instance.

### 6.2 Agent Studio (Create)

The agent studio allows tenant admins to build custom agents specific to their organization's needs. Unlike templates, these are fully custom agents that the tenant admin owns and maintains.

**Agent Studio components**:

**A) Identity**

- Agent name (shown to users)
- Description (shown in agent list)
- Avatar/icon
- Category tag

**B) Intelligence Configuration**

- System prompt (free-form): the tenant admin writes the full agent persona and instructions
- Contrast with templates: in templates, the system prompt is platform-controlled; in Agent Studio, the tenant admin controls the full prompt
- Prompt suggestions: AI-assisted prompt improvement ("Your prompt might perform better with...") — optional, user-controlled
- Example conversations: add 3-5 example user-agent exchanges to guide the model

**C) Knowledge Sources**

- Attach knowledge bases: select from available KBs in the workspace
- The agent answers from the selected KBs only
- "Grounded mode": agent only answers from KB context (refuses if no supporting documents)
- "Extended mode": agent can use general knowledge + KB context

**D) Tools** (if tenant is on Professional/Enterprise plan)

- Enable MCP tools from the platform catalog
- Tool access is per-agent
- Write/Destructive tools require explicit enablement + admin confirmation
- Tenant admin provides tool-specific configuration (e.g., Jira workspace URL, credentials)

**E) Guardrails**

- Topic restrictions: "Never discuss competitor pricing"
- Tone settings: formal / neutral / friendly
- Confidence threshold: if below X, say "I don't have enough information"
- Max response length

**F) Testing**

- Test chat interface within Agent Studio
- Test with different user queries
- Preview how KB retrieval works ("Show sources" toggle)

**G) Publish**

- Save as Draft (not visible to users)
- Publish (live, visible to assigned users)
- Unpublish (returns to draft — does not delete conversation history)

### 6.3 Agent Management

Deployed agents (from library or studio):

| Action           | Description                                                                 |
| ---------------- | --------------------------------------------------------------------------- |
| Edit             | Modify agent config (studio agents only — template system prompt is locked) |
| Duplicate        | Clone agent as starting point for a new one                                 |
| Disable          | Hide from users without deleting                                            |
| Version history  | View previous configurations (audit)                                        |
| Usage analytics  | Queries per day, satisfaction, most common topics                           |
| Upgrade template | For library agents: apply new platform template version                     |

---

## Domain 7: User Feedback and Resolution

### 7.1 Feedback Monitoring Dashboard

The tenant admin views all feedback generated by their users.

**Summary view**:

- 7-day rolling satisfaction rate (thumbs up / total rated)
- Response ratings by agent (which agents are performing well/poorly)
- Response ratings by KB source (which KBs produce better answers)
- Unresolved issue reports (submitted by users via in-app reporter)

### 7.2 Issue Reports Queue

When users submit issue reports (via the in-app reporter from Plan 04), tenant admins see a queue of reports for their workspace.

**Issue report types visible to tenant admin**:

- Reports routed to them by the platform admin ("tenant config issue")
- Reports submitted by their users that have been auto-triaged as "configuration" rather than "platform bug"

**Actions tenant admin can take**:

- View report: full context (screenshot, user, query, AI response)
- Respond to user: send a message via in-app notification ("We're looking into this")
- Resolve with note: "Fixed — we updated the HR glossary to include this term"
- Escalate to platform admin: "This seems like a platform issue, not our config"

**Visibility limit**: Tenant admin sees ONLY their own tenant's reports. Cross-tenant data is never shown.

### 7.3 Agent Performance Insights

Per deployed agent:

- Satisfaction rate over time (chart)
- Most common query topics (word cloud or ranked list from AI-extracted themes)
- Low-confidence responses: list of responses where confidence score < threshold
- Guardrail trigger events: when did the agent invoke a guardrail (with anonymized query context)
- Comparison: satisfaction before vs after an agent configuration change

### 7.4 User Engagement Signals

- Active users: DAU / WAU / MAU per agent
- Feature usage: which KBs are queried most, which agents are used most
- Drop-off: users who logged in but did not submit queries (engagement gap)
- Power users: top 10% of users by query volume (adoption champions to engage)
- Inactive users: not logged in for 14+ days (candidates for outreach or license review)

---

## Design Decisions

### D1: Tenant Admin Cannot Modify Agent Template System Prompts

Templates from the platform library have platform-controlled system prompts. The tenant admin fills variables only. This preserves quality assurance and governance — the platform has tested and validated the template behavior. Allowing system prompt modification would break the feedback loop (template analytics would be measuring a modified version, not the original).

### D2: Agent Studio Agents Are Fully Tenant-Owned

Agents built in Agent Studio are outside the template governance model. The tenant admin has full control (system prompt, guardrails, everything). These agents do not contribute to platform-level template analytics and are not visible to other tenants. The tradeoff: full flexibility, but no platform quality guarantee.

### D3: KB Access Control Is Additive, Not Subtractive

Access rights are granted explicitly. Users have no default access to KBs unless granted. This is safer than an "access to all unless restricted" model, especially for sensitive KBs (HR, Legal, Finance).

### D4: SSO Group Sync Is Optional, Not Required

Not all organizations have clean IdP group structures. The tenant admin can always manage roles manually if group sync adds complexity. Group sync is an optimization for large organizations.

### D5: The Tenant Admin Has No Access to Cross-Tenant Data

A tenant admin can see everything in their own workspace but nothing from other tenants. Even if they are curious about how other organizations use the platform, this data is structurally inaccessible. This is enforced at the API layer via tenant_id scoping on all queries.
