# 17 — Role-Based First Login: What Each Role Sees and Can Access

**Date**: 2026-03-07
**Scope**: Complete first-login experience for all five roles across two scopes (platform + tenant)
**Design reference**: `.claude/rules/design-system.md` — Obsidian Intelligence design system
**Architecture rule**: End User / Tenant Admin / Platform Admin NEVER share a layout. Each role gets a completely different navigation structure, not the same nav with items locked.

---

## Roles Covered

| Role              | Scope    | First Login Trigger                            |
| ----------------- | -------- | ---------------------------------------------- |
| Platform Admin    | Platform | Internal credential provisioned by engineering |
| Platform Operator | Platform | Invite from platform admin                     |
| Tenant Admin      | Tenant   | Invitation email from platform admin           |
| Analyst           | Tenant   | Invitation email from tenant admin             |
| Reader            | Tenant   | Invitation email from tenant admin             |
| Viewer (default)  | Tenant   | Invitation email from tenant admin             |

---

## 1. Platform Admin — First Login

**Role**: `platform_admin`
**URL**: `admin.mingai.io` (separate from tenant-facing URLs — never `{slug}.mingai.io`)
**Authentication**: Credentials provisioned by engineering team. MFA enforced (TOTP). No SSO — platform admin identity is isolated.

---

### 1a. Authentication

```
Start: Platform admin opens admin.mingai.io
  |
  v
[Login page — platform admin variant]
  |-- Logo: mingai Platform Administration
  |-- Email + Password fields
  |-- "This is a restricted administrative interface."
  |-- NO SSO option shown (platform admin auth is always internal)
  |
  v
[MFA challenge — always required]
  |-- TOTP code entry (Google Authenticator / Authy)
  |-- "Authenticator app required for all admin sessions"
  |
  v
[Authenticated → land on Operations Dashboard]
```

**Error paths**:

- Wrong credentials → "Invalid credentials. 3 failed attempts will lock this account for 30 minutes."
- MFA code expired → "Code expired. Enter the current 6-digit code."
- Account locked → "Account locked. Contact platform engineering to unlock."

---

### 1b. What They See: Bootstrap State (No Tenants Yet)

This is the screen immediately after the very first platform admin login — before any tenants are provisioned.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TOPBAR                                                                       │
│  ≡  mingai Platform Admin                    [Platform Admin] [⚙] [Log Out]  │
└─────────────────────────────────────────────────────────────────────────────┘
│                                                                               │
│ SIDEBAR (--sidebar-w: 216px)              MAIN CONTENT AREA                  │
│ ─────────────────────────                                                     │
│  OPERATIONS                               ┌────────────────────────────────┐ │
│   ● Dashboard         ← ACTIVE             │  Welcome to mingai Platform    │ │
│   · Tenants                                │  Administration                │ │
│   · Issue Queue                            │                                │ │
│                                            │  Get started:                  │ │
│  INTELLIGENCE                              │                                │ │
│   · LLM Profiles                           │  [1] Configure LLM Profiles    │ │
│   · Agent Templates                        │      Set up model configurations│ │
│   · Analytics                              │      before onboarding tenants  │ │
│   · Tool Catalog                           │      → [Configure Now]          │ │
│                                            │                                │ │
│  FINANCE                                   │  [2] Provision First Tenant     │ │
│   · Cost Analytics                         │      → [New Tenant]             │ │
│                                            │                                │ │
│                                            │  Setup checklist:              │ │
│                                            │  ○ LLM Profiles created (0)    │ │
│                                            │  ○ First tenant provisioned    │ │
│                                            │  ○ Tool catalog populated      │ │
│                                            └────────────────────────────────┘ │
```

**Navigation available on first login**:

| Section      | Nav Item        | State     | What Loads                        |
| ------------ | --------------- | --------- | --------------------------------- |
| OPERATIONS   | Dashboard       | Active    | Setup checklist (empty state)     |
| OPERATIONS   | Tenants         | Available | Empty table with "New Tenant" CTA |
| OPERATIONS   | Issue Queue     | Available | Empty — no issues yet             |
| INTELLIGENCE | LLM Profiles    | Available | Empty — "Create First Profile"    |
| INTELLIGENCE | Agent Templates | Available | Empty — "Create First Template"   |
| INTELLIGENCE | Analytics       | Available | No data yet — blank charts        |
| INTELLIGENCE | Tool Catalog    | Available | Empty — "Register First Tool"     |
| FINANCE      | Cost Analytics  | Available | $0 baseline — no tenants          |

---

### 1c. What They See: Operational State (Tenants Active)

Once tenants are provisioned and using the platform:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR: mingai Platform Admin                [⚠ 1 P1] [Platform Admin] [⚙]  │
└─────────────────────────────────────────────────────────────────────────────┘

SIDEBAR                            MAIN: Operations Dashboard
───────                            ──────────────────────────
OPERATIONS                         KPI CARDS (top row)
 ● Dashboard                       ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
 · Tenants            [24]         │ TENANTS  │ │ PLATFORM │ │ OPEN P0/ │ │ QUOTA    │
 · Issue Queue   ● [3 new]         │ 24 Active│ │ SAT 78%  │ │ P1 ISSUES│ │ WARNINGS │
                                   │ 3 At Risk│ │ ↑ +4%    │ │    1     │ │    2     │
INTELLIGENCE                       └──────────┘ └──────────┘ └──────────┘ └──────────┘
 · LLM Profiles
 · Agent Templates                 TENANT HEALTH TABLE
 · Analytics                       Tenant         Plan  Health  Queries/wk  Status
 · Tool Catalog                    Acme Corp      Pro   ████ 82  1,240      Active ●
                                   BetaCo         Pro   ██░░ 41  180    ⚠  At Risk ⚠
FINANCE                            Initech        Ent   ████ 76  3,100      Active ●
 · Cost Analytics
```

---

### 1d. Platform Admin Accessibility Matrix

| Capability            | platform_admin | platform_operator | platform_support | platform_security |
| --------------------- | :------------: | :---------------: | :--------------: | :---------------: |
| Provision tenant      |       ✓        |         ✓         |        ✗         |         ✗         |
| Suspend/delete tenant |       ✓        |   With approval   |        ✗         |         ✗         |
| View all tenants      |       ✓        |         ✓         |        ✓         |         ✓         |
| Manage billing        |       ✓        |     View only     |        ✗         |         ✗         |
| Create LLM profiles   |       ✓        |         ✗         |        ✗         |         ✗         |
| Publish templates     |       ✓        |         ✗         |        ✗         |         ✗         |
| Register tools        |       ✓        |         ✗         |        ✗         |         ✗         |
| Issue queue triage    |       ✓        |         ✓         |    View only     |     View only     |
| Create GitHub issue   |       ✓        |         ✓         |        ✗         |         ✗         |
| Cost analytics        |       ✓        |     View only     |        ✗         |         ✓         |
| Security audit log    |       ✓        |         ✗         |        ✗         |         ✓         |

---

### 1e. Platform Operator — First Login Differences

Same URL and MFA requirement. Sidebar looks identical but:

- "New Tenant" button visible and usable
- LLM Profiles: read-only (no Create/Edit)
- Agent Templates: read-only
- Tool Catalog: read-only
- Issue Queue: full triage + GitHub creation rights
- Billing: view-only (no overrides, no plan changes)
- Locked items show lock icon on hover with "Platform Admin only"

---

## 2. Tenant Admin — First Login

**Role**: `tenant_admin`
**URL**: `{slug}.mingai.io` — the tenant's unique workspace URL
**Authentication**: Invitation email link → account creation (email+password or SSO if org has it configured)

---

### 2a. Invitation to Activation

```
[User receives invite email]
  Subject: "You've been invited to set up [Org Name] on mingai"
  From: no-reply@mingai.io
  Body:
    "Hi [Name],
     [Platform Admin] has provisioned a mingai workspace for [Org Name].
     You've been designated as the workspace administrator.

     [Set Up Your Workspace →]  (link expires in 72 hours)"
  |
  v
[User clicks link → lands on activation page]
  |
  v
[Account Activation]
  |-- Email: pre-filled (from invite)
  |-- Set password: [          ] [Confirm: ]
  |-- Accept terms of service: [✓ checkbox] (required)
  |-- [Activate Account]
  |
  +-- If tenant has SSO already configured (rare on first admin invite):
  |     → "Continue with [SSO Provider]" shown as primary option
  |
  v
[Account activated → Setup Wizard launches automatically]
```

---

### 2b. Setup Wizard (6 Steps)

The wizard launches on first login. Progress bar at top. Cannot be skipped (core steps). Can return to any completed step.

```
STEP 1/6: Workspace Identity

  [Workspace Setup — Step 1 of 6]

  Workspace name: [Acme Corp Knowledge AI       ]
  Logo:           [drag PNG/SVG here · max 2MB  ] or [Browse]
  Timezone:       [Asia/Singapore ▼] (auto-detected from browser)

  [Next →]

──────────────────────────────────────────────────────────────────────────────

STEP 2/6: Authentication

  How will your team log in?

  (•) Email + Password + MFA
      Platform-managed accounts. Recommended for teams < 20.

  ( ) Single Sign-On (SSO)
      Use your organization's existing identity provider.
      Protocol: [SAML 2.0] or [OIDC]
      ↳ Opens inline SSO wizard on selection (see 02-tenant-admin-flows.md Flow 1)

  [← Back]  [Next →]

──────────────────────────────────────────────────────────────────────────────

STEP 3/6: AI Model

  Select your AI profile:

  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
  │ Cost-Optimized       │  │ Balanced  ⭐RECOMMENDED│  │ Premium              │
  │ Fast responses       │  │ Best for most         │  │ Complex reasoning    │
  │ High query volume    │  │ organizations         │  │ Legal, analysis      │
  │ $0.003/query est.    │  │ $0.008/query est.     │  │ $0.018/query est.    │
  └──────────────────────┘  └──────────────────────┘  └──────────────────────┘

  [← Back]  [Next →]

──────────────────────────────────────────────────────────────────────────────

STEP 4/6: Connect Documents (Optional)

  Where are your organization's documents?

  [SharePoint]      → Inline wizard (Steps 2-7 in 12-tenant-admin-flows.md)
  [Google Drive]    → Inline wizard (Phase 4 — available after launch)
  [Upload Files]    → File picker opens
  [Skip for now]    → Move to Step 5

──────────────────────────────────────────────────────────────────────────────

STEP 5/6: Invite Your Team (Optional)

  Add team members:

  user1@acme.com   Role: [Reader ▼]   [✕]
  user2@acme.com   Role: [Analyst ▼]  [✕]
  [+ Add another email]

  Bulk option: [Upload CSV] (columns: email, role)

  [Skip — invite later]  [← Back]  [Send Invites →]

──────────────────────────────────────────────────────────────────────────────

STEP 6/6: Setup Complete

  Your workspace is ready.

  ✓ Workspace: Acme Corp Knowledge AI
  ✓ Authentication: Email + Password + MFA
  ✓ AI model: Balanced
  ✓ Documents: SharePoint connected (sync in progress — check back in 30 minutes)
  ✓ Users: 2 invites sent

  What to do next:
  [ ] Add glossary terms (help the AI understand your jargon)
  [ ] Deploy your first AI agent from the library
  [ ] Review document sync status

  [Go to Dashboard →]
```

---

### 2c. Tenant Admin Dashboard — First View

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR: Acme Corp Knowledge AI    [Sync ⟳ In Progress]  [J. Smith ▾] [⚙]   │
└─────────────────────────────────────────────────────────────────────────────┘

SIDEBAR (216px)                    MAIN: Admin Dashboard
──────────────────                 ─────────────────────
WORKSPACE                          SETUP CHECKLIST (shown until all complete)
 ● Dashboard      ← ACTIVE         ┌────────────────────────────────────────────┐
 · Documents     ⟳ syncing         │ Complete your workspace setup              │
 · Users         [3 users]         │                                            │
 · Agents        [0 deployed]      │ ✓ Workspace configured                     │
 · Glossary      [0 terms]         │ ✓ Authentication set (Email + MFA)         │
                                   │ ✓ AI model selected (Balanced)             │
INSIGHTS                           │ ○ Document store connected       [Connect →]│
 · Analytics                       │   SharePoint sync in progress (est. 45 min)│
 · Issues        [0 open]          │ ○ Add glossary terms             [Add →]    │
 · Settings                        │ ○ Deploy first agent             [Browse →] │
                                   │ ○ Invite your team               [Invite →] │
                                   └────────────────────────────────────────────┘

                                   KPI CARDS (greyed/baseline until data exists)
                                   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
                                   │ USERS        │ │ QUERIES      │ │ SATISFACTION │
                                   │ 3 total      │ │ 0 this month │ │ No data yet  │
                                   │ 1 active     │ │              │ │              │
                                   └──────────────┘ └──────────────┘ └──────────────┘
```

---

### 2d. Tenant Admin Navigation — Full Map

| Section   | Nav Item  | What Loads                                                          | Empty State                                                    |
| --------- | --------- | ------------------------------------------------------------------- | -------------------------------------------------------------- |
| WORKSPACE | Dashboard | Setup checklist → KPI cards                                         | Setup checklist                                                |
| WORKSPACE | Documents | KB list + sync status                                               | "No document stores connected. [Connect →]"                    |
| WORKSPACE | Users     | User directory                                                      | "1 user (you). [Invite Users →]"                               |
| WORKSPACE | Agents    | Deployed agent list                                                 | "No agents deployed. [Browse Library →]"                       |
| WORKSPACE | Glossary  | Term list                                                           | "No terms. [Add Term →] or [Import CSV →]"                     |
| INSIGHTS  | Analytics | Usage charts                                                        | "No query data yet. Check back after users start querying."    |
| INSIGHTS  | Issues    | Issue queue                                                         | "No issues reported. This is where user-reported bugs appear." |
| INSIGHTS  | Settings  | Settings tabs (General, Auth, Integrations, Billing, Notifications) | All settings accessible                                        |

---

### 2e. What Tenant Admin Can and Cannot Do

| Capability                                 |                   tenant_admin                   |
| ------------------------------------------ | :----------------------------------------------: |
| View + manage all users                    |                        ✓                         |
| Invite users, assign roles                 |                        ✓                         |
| Configure SSO                              |                        ✓                         |
| Connect SharePoint / Google Drive          |                        ✓                         |
| Create + manage glossary                   |                        ✓                         |
| Deploy agents from library                 |                        ✓                         |
| Build agents in Agent Studio               |                        ✓                         |
| View analytics (own tenant)                |                        ✓                         |
| View + triage issue queue                  |                        ✓                         |
| Change plan / billing                      |        View only — contact platform admin        |
| Access other tenants' data                 |                ✗ (hard boundary)                 |
| Access platform admin console              |                        ✗                         |
| Modify LLM profile configuration           | ✗ — select from platform-published profiles only |
| Create new agent templates for the library |     ✗ — submit suggestion to platform admin      |

---

## 3. End User — Viewer (Default Role)

**Role**: `viewer`
**Privilege level**: Lowest — chat access only
**URL**: `{slug}.mingai.io` — same tenant URL
**Authentication**: Invitation email → SSO (if configured) or email+password

---

### 3a. Invitation to First Login

```
[User receives invite email]
  Subject: "You're invited to Acme Corp Knowledge AI"
  Body:
    "Hi [Name],
     Your team has set up an AI assistant for Acme Corp.
     Click below to accept your invitation and get started.

     [Accept Invitation →]  (link expires in 7 days)"
  |
  v
[User clicks link]
  |
  +-- SSO configured for tenant:
  |     → "Continue with Microsoft / Google / [SSO Provider]"
  |     → SSO login completes → JWT issued → land on chat
  |
  +-- Email + Password:
        → "Set your password: [    ] [Confirm: ]"
        → [Accept and Set Password]
        → Land on chat
```

---

### 3b. What They See: Empty Chat State (First Visit)

The viewer lands directly in the chat interface — **no admin navigation, no onboarding wizard**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR: Acme Corp Knowledge AI                      [Sarah Chen ▾]  [⚙]     │
└─────────────────────────────────────────────────────────────────────────────┘

SIDEBAR (216px)                    MAIN: Empty Chat State (Centered Layout)
──────────────────
HISTORY                                         ┌─────────────────────────┐
 [+ New Chat]                                   │  ⬡                      │
                                                │  General Assistant      │
 (empty — no conversations yet)                 │  Acme Corp Knowledge AI │
 "Start a conversation to see                   │                         │
  your history here."                           │  How can I help you     │
                                                │  today?                 │
                                                │                         │
                                                │  ┌─────────────────┐   │
                                                │  │ Ask anything... │   │
                                                │  └─────────────────┘   │
                                                │  ⊕ Attach    ⚐ Report  │
                                                │                         │
                                                │  SharePoint · 2,081 docs│
                                                └─────────────────────────┘

                                                Suggestion chips (if tenant configured):
                                                [What is our travel policy?]
                                                [How many vacation days do I get?]
                                                [Who approves expense claims?]
```

**What the viewer sees**:

- History sidebar (empty on first visit) with "+ New Chat" button
- Centered chat empty state (agent icon, greeting, input bar)
- KB hint below input: which knowledge bases are indexed
- Suggestion chips (if configured by tenant admin)
- Mode selector in input bar: shows available agents (viewer: typically "General Assistant" only)
- Settings (⚙) in topbar: links to Profile, Notifications, Privacy

**What the viewer does NOT see** (hidden entirely, not locked):

- Admin menu of any kind
- Documents section
- Users section
- Agents management
- Glossary management
- Analytics
- Issues queue (reporting a bug via the ⚐ Report button still works — routes to admin)
- Billing or settings tabs beyond Profile/Notifications/Privacy

---

### 3c. Viewer Settings — What's Accessible

When viewer clicks ⚙ (Settings):

```
SETTINGS (Viewer role — 3 tabs only)
  Profile      → Name, email, avatar, language preference
  Notifications → Email alert preferences, in-app notification settings
  Privacy      → Profile learning on/off, memory notes, GDPR export/erase

  (No Admin Settings, no Integrations, no Billing tabs visible)
```

---

### 3d. What Viewer Can and Cannot Do

| Capability                             |              viewer               |
| -------------------------------------- | :-------------------------------: |
| Chat with General Assistant            |                 ✓                 |
| View their own conversation history    |                 ✓                 |
| Share a conversation (link within org) |                 ✓                 |
| Export conversation (PDF/Markdown)     |                 ✓                 |
| Upload documents to a conversation     | ✓ (personal uploads only, not KB) |
| Give thumbs up/down feedback           |                 ✓                 |
| Report an issue (⚐ button)             |                 ✓                 |
| View profile/privacy settings          |                 ✓                 |
| Access restricted agents (Finance, HR) |      ✗ — can request access       |
| Use Research Mode                      |         ✗ (Analyst+ only)         |
| View analytics                         |                 ✗                 |
| Manage documents or indexes            |                 ✗                 |
| Invite users                           |                 ✗                 |
| Admin console (any part)               |          ✗ — not visible          |

---

## 4. End User — Reader

**Role**: `reader`
**Privilege level**: Standard access — same chat UI as Viewer, with expanded knowledge base access.

---

### 4a. First Login Experience

Identical to Viewer (Section 3a–3b). The Reader lands on the same chat empty state with the same centered layout.

**What's different from Viewer**:

```
SIDEBAR — History only (same as Viewer)

CHAT — Mode selector shows more agents (those the Reader role grants access to):

  [Agent Picker]
  ● General Assistant   (all roles)
  · HR Policy Agent     (Reader+ — Reader has access)
  · Finance Analyst     (Analyst only — locked, shows "Request Access")
  · Legal Assistant     (Analyst only — locked)
```

---

### 4b. What Reader Adds Over Viewer

| Capability                                 | viewer | reader |
| ------------------------------------------ | :----: | :----: |
| Chat with General Assistant                |   ✓    |   ✓    |
| Access indexed KBs assigned to Reader role |   ✗    |   ✓    |
| Use role-specific agents (e.g. HR Policy)  |   ✗    |   ✓    |
| Research Mode                              |   ✗    |   ✗    |
| Analytics Viewer                           |   ✗    |   ✗    |

---

## 5. End User — Analyst

**Role**: `analyst`
**Privilege level**: Advanced — unlocks Research Mode, advanced agents, and analytics access.

---

### 5a. First Login Experience

Same entry as Viewer and Reader. Lands on the same chat empty state.

**What's visually different**:

```
CHAT INPUT BAR — mode selector shows Research Mode toggle:

  Agent: [Finance Analyst ▾]   Mode: [Standard | Research]

  (Research Mode is EXCLUSIVE to Analyst role — not shown to Viewer/Reader)

SIDEBAR — may have an extra section if tenant admin granted Analytics Viewer:

  HISTORY
   [+ New Chat]
   ...conversations...

  ANALYTICS (if tenant admin granted analytics:view_all)
   · My Usage Stats    ← only the analyst's own stats
```

---

### 5b. What Analyst Adds Over Reader

| Capability                                           | reader | analyst |
| ---------------------------------------------------- | :----: | :-----: |
| Research Mode                                        |   ✗    |    ✓    |
| Access to Analyst-restricted agents                  |   ✗    |    ✓    |
| A2A multi-agent queries (Bloomberg, CapIQ, etc.)     |   ✗    |    ✓    |
| Upload and query personal documents                  |   ✓    |    ✓    |
| Analytics Viewer access (if granted)                 |   ✗    |    ✓    |
| Manage own memory notes                              |   ✓    |    ✓    |
| Teams collaboration (send queries with team context) |   ✓    |    ✓    |

---

## 6. Cross-Role Comparison — First Login Summary

### What Each Role Sees on Landing

| Element                              | Platform Admin |  Tenant Admin  | Analyst | Reader | Viewer |
| ------------------------------------ | :------------: | :------------: | :-----: | :----: | :----: |
| Platform operations dashboard        |       ✓        |       ✗        |    ✗    |   ✗    |   ✗    |
| Tenant admin dashboard               |       ✗        |       ✓        |    ✗    |   ✗    |   ✗    |
| Setup wizard                         |       ✗        | ✓ (first time) |    ✗    |   ✗    |   ✗    |
| Chat interface                       |       ✗        |       ✗        |    ✓    |   ✓    |   ✓    |
| Research Mode toggle                 |       ✗        |       ✗        |    ✓    |   ✗    |   ✗    |
| Admin sidebar (Workspace/Insights)   |       ✗        |       ✓        |    ✗    |   ✗    |   ✗    |
| Platform sidebar (Ops/Intel/Finance) |       ✓        |       ✗        |    ✗    |   ✗    |   ✗    |
| History-only sidebar                 |       ✗        |       ✗        |    ✓    |   ✓    |   ✓    |
| Mode selector (agent picker)         |       ✗        |       ✗        |    ✓    |   ✓    |   ✓    |
| Settings → Profile/Privacy           |       ✗        |       ✓        |    ✓    |   ✓    |   ✓    |
| Settings → Admin (SSO, Integrations) |       ✗        |       ✓        |    ✗    |   ✗    |   ✗    |

### What Each Role's Sidebar Contains

```
Platform Admin sidebar:
  OPERATIONS
   · Dashboard
   · Tenants
   · Issue Queue
  INTELLIGENCE
   · LLM Profiles
   · Agent Templates
   · Analytics
   · Tool Catalog
  FINANCE
   · Cost Analytics

Tenant Admin sidebar:
  WORKSPACE
   · Dashboard
   · Documents
   · Users
   · Agents
   · Glossary
  INSIGHTS
   · Analytics
   · Issues
   · Settings

End User sidebar (all 3 roles):
  [+ New Chat]
  HISTORY
   · [conversation list]
  (+ ANALYTICS section for Analyst if granted)
```

---

## 7. Error Paths — First Login

### Expired Invitation Link

```
User clicks link older than 72h (tenant admin) or 7 days (end user)

[Error page]
  "This invitation has expired."

  For Tenant Admin: "Contact platform support to resend: support@mingai.io"
  For End User: "Contact your workspace administrator at [tenant_admin_email]"

  [Request New Invitation] → sends email request to appropriate admin
```

### Wrong Account Type (User Tries to Access Admin URL)

```
End user navigates to admin.mingai.io

[Login page shown]
  User enters their credentials

Auth check: user is NOT a platform_admin role
→ "Access denied. This interface is restricted to platform administrators."
→ [Go to your workspace → {slug}.mingai.io]
```

### Tenant Admin Tries to Access Another Tenant

```
Tenant admin navigates to a different tenant's URL (acme2.mingai.io)

[Login page shown]
  User enters their Acme Corp credentials

Auth check: JWT tenant_id does not match requested tenant
→ "Your account does not belong to this workspace."
→ [Go to your workspace → acme.mingai.io]
```

### SSO Fails on First Login (End User)

```
SSO redirect returns error

[Error page with context]
  "Sign-in failed. Your organization's SSO returned an error."
  Error details (for IT admin, not end user): [SAML assertion validation failed]

  User-facing message: "Contact your IT administrator."
  Link shown: "[Contact {tenant_admin_email}]" (if tenant has published support contact)
```

### End User Account Not Yet Provisioned

```
User accepts invite link but SSO auto-provisioning is disabled

[Error page]
  "Your account is not yet active."
  "Your administrator is setting up your access. Try again in a few minutes."
  [Try Again] button

System: sends notification to tenant admin "User {email} attempted login but account not provisioned"
```

---

## 8. Onboarding Completion Signals

Each role has a "first value" milestone that drives platform health metrics:

| Role           | First Value Event                                 | Target Time           |
| -------------- | ------------------------------------------------- | --------------------- |
| Platform Admin | First tenant provisioned                          | Day 1                 |
| Tenant Admin   | First successful KB query (test in admin console) | < 2 hours after setup |
| Analyst        | First Research Mode query                         | Day 1 of usage        |
| Reader         | First chat query with a response rating           | Day 1 of usage        |
| Viewer         | First chat query submitted                        | Day 1 of usage        |

These events are tracked in the platform analytics and surfaced in the platform admin's "Time to First Value" metric per tenant.

---

## 9. Post-First-Login: What Happens Next

### Platform Admin

After first login, the recommended sequence (surfaced in setup checklist):

1. Create at least one LLM Profile (Balanced) → publish it
2. Provision first tenant
3. Register core tools (Tavily web search — available in all plans)
4. Monitor: Platform Admin Dashboard updates in real time as tenants onboard

### Tenant Admin

After wizard completes, the dashboard shows a setup checklist. Recommended sequence:

1. Verify SharePoint sync completed (Documents → Sync Status)
2. Add 5–10 glossary terms for top company-specific acronyms
3. Deploy one agent from the library (HR Policy or Finance Analyst)
4. Test the agent in admin console (Agent Studio → Test Chat)
5. Invite the remaining team

### End User (all roles)

After first login, the chat empty state offers:

- Suggestion chips: pre-written common questions the tenant admin configured
- KB hint: "Ask about [Company] policies, HR guides, Finance docs"
- No tour or onboarding wizard — the chat UI is self-explanatory

---

**Document Version**: 1.0
**Last Updated**: 2026-03-07
**Covers**: All 6 roles (platform_admin, platform_operator, tenant_admin, analyst, reader, viewer)
**Design reference**: `.claude/rules/design-system.md` — role layout architecture section
