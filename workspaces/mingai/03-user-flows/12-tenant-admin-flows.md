# 12 — Tenant Admin: User Flows

**Date**: 2026-03-05
**Personas**: Tenant Admin (primary — IT admin, knowledge manager, or department head), End User (receiver of outcomes), IT Security (approver/observer)
**Domains**: Workspace Setup, Document Store Integration, Sync Monitoring, Glossary, RBAC, Agent Workspace, Feedback

---

## Flow 1: First-Time Workspace Setup (Onboarding Wizard)

**Trigger**: Tenant admin receives invite email from platform admin after tenant is provisioned.
**Persona**: Tenant Admin (typically IT admin or department head)
**Entry**: Email link → workspace URL → login → wizard auto-starts

```
STEP 1: Accept Invite and Activate Account
  Admin opens invite email link
  Sets password (or continues with SSO if org is SSO-first)
  Accepts terms of service
  → Lands in setup wizard (progress bar: 1/6)

STEP 2: Workspace Identity (1/6)
  Workspace display name: "Acme Corp Knowledge AI"
  Logo upload: drag and drop or file picker (PNG/SVG, max 2MB)
  Default timezone: [dropdown, auto-detected from browser]
  → Click "Next"

STEP 3: Authentication Setup (2/6)
  System shows two options:
    Option A: Platform-managed (email + password + MFA) — recommended for small teams
    Option B: Single Sign-On — recommended for organizations with existing IdP

  If SSO selected → inline mini-wizard:
    Protocol selection: [SAML 2.0] or [OIDC]
    SAML: System shows SP metadata (Entity ID, ACS URL) to copy into IdP
    Admin opens their IdP in another tab, creates SAML app, pastes back:
      → IdP metadata URL or XML upload
    Test SSO: "Send test login link"
    If test passes → SSO enabled
    If test fails → error details shown with resolution hints

STEP 4: Choose LLM Profile (3/6)
  Shows available profiles (published by platform admin) as cards:
    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
    │ Cost-Optimized  │  │    Balanced     │  │    Premium      │
    │                 │  │  ⭐ Recommended  │  │                 │
    │ Fast, efficient │  │ Best for most   │  │ Complex         │
    │ Use for: high   │  │ organizations   │  │ reasoning       │
    │ volume Q&A      │  │                 │  │ Use for: legal, │
    │                 │  │                 │  │ analysis        │
    └─────────────────┘  └─────────────────┘  └─────────────────┘
  Admin selects one (can change later)
  → Click "Next"

STEP 5: Connect Your First Document Store (4/6)
  Options: [SharePoint] [Google Drive] [Upload Files] [Skip for now]

  If Skip → moves to Step 6
  If SharePoint → inline wizard (see Flow 2)
  If Google Drive → inline wizard (see Flow 3)
  If Upload → file picker opens (see Domain 3 spec)

STEP 6: Invite Your Team (5/6)
  Admin adds email addresses:
    user1@acme.com → Role: [Reader ▼]
    user2@acme.com → Role: [Analyst ▼]
    + Add more
  Bulk option: "Upload CSV" (email, role columns)
  → Send invites (or skip and invite later)

STEP 7: Setup Complete (6/6)
  Summary:
    ✓ Workspace: Acme Corp Knowledge AI
    ✓ Authentication: SSO (Okta)
    ✓ LLM Profile: Balanced
    ✓ Document store: SharePoint connected (0 documents indexed — sync starting)
    ✓ Users: 3 invites sent
  → Button: "Go to Dashboard"
  Dashboard shows: setup checklist with remaining recommended steps
    [✓] Basic setup
    [ ] Deploy your first agent (from library)
    [ ] Add glossary terms
    [ ] Review sync status (check back in 30 minutes)
```

---

## Flow 2: Connect SharePoint (Permission Provisioning Wizard)

**Trigger**: Admin initiates SharePoint connection during setup or from Settings → Integrations.
**Persona**: IT Admin (has Azure portal access)
**Entry**: Settings → Integrations → Add → SharePoint

```
STEP 1: Introduction
  System shows:
    "You will need:
    ✓ Azure Portal access (Global Admin or Application Admin role)
    ✓ ~30-45 minutes for setup
    ✓ The ability to grant admin consent for API permissions"
  [Start Setup] button

STEP 2: Create an App Registration
  System shows side-by-side:
    LEFT: Step-by-step instructions with screenshots
    RIGHT: Form to enter the values after completing each step

  Instructions:
    1. Open Azure Portal → portal.azure.com → sign in as Global Admin
    2. Navigate: Entra ID → App Registrations → New Registration
    3. Name: "mingai SharePoint Connector — Acme Corp"
    4. Account types: "Accounts in this organizational directory only"
    5. Redirect URI: leave blank
    6. Click Register

  Form to fill (after completing above):
    Application (Client) ID: [                    ] (paste from Azure)
    Directory (Tenant) ID:   [                    ] (paste from Azure)

  → Click "Continue"

STEP 3: Create a Client Secret
  Instructions:
    1. Still in your App Registration → Certificates & Secrets
    2. New Client Secret → Description: "mingai connector" → Expiry: 24 months
    3. IMPORTANT: Copy the secret VALUE now — it cannot be shown again after leaving this page
    4. Set a calendar reminder for 22 months from now to rotate this secret

  Form:
    Client Secret:    [                    ] (paste from Azure)
    Secret Expiry:    [Date picker — optional, to enable rotation reminders]

  Security note shown: "This secret is encrypted at rest and never exposed in our API.
  It is used only by the sync worker to authenticate with Microsoft Graph."

STEP 4: Add API Permissions
  Instructions:
    1. In your App Registration → API Permissions → Add a Permission
    2. → Microsoft Graph → Application Permissions
    3. Search "Sites" → find "Sites.Read.All" → check it
    4. Click "Add Permissions"
    5. Click "Grant admin consent for Acme Corp" (requires Global Admin)
    6. Confirm: all permissions show green ✓ tick

  System confirms: "You've added the permissions. Verify: Sites.Read.All shows status 'Granted'"

  Advanced option (expandable):
    "Want to limit access to specific sites only? (Recommended for large organizations)"
    → Explains Sites.Selected alternative + links to setup instructions

STEP 5: Test Connection
  Admin clicks "Test Connection"
  System calls Microsoft Graph: GET /v1.0/sites?$top=10
  Success: Shows list of accessible SharePoint sites
    "✓ Connection successful — 47 sites found"
  Failure: Shows specific error with resolution guidance:
    "401 Unauthorized — admin consent may not have been granted. Return to Step 4."
    "403 Forbidden — Sites.Read.All permission may be missing. Return to Step 4."

STEP 6: Select Sites to Sync
  Admin sees site list from test connection:
    ☑ Contoso HR Portal (site.contoso.com/sites/HR)
    ☑ Finance Team Documents (site.contoso.com/sites/Finance)
    ☐ IT Infrastructure (excluded — not relevant to AI queries)
    ☐ Executive Leadership (excluded — access control handled separately)

  For each selected site: optionally select specific libraries or folders
  Sync schedule: [Every 30 minutes ▼]

STEP 7: Initial Sync
  "Starting initial sync — this may take 10-60 minutes depending on document volume.
  You'll receive a notification when complete."
  Admin sees progress: "Contoso HR Portal: scanning... 0/~450 documents"
  Admin can leave and check back later
```

---

## Flow 3: Connect Google Drive (DWD Setup Wizard)

**Trigger**: Admin initiates Google Drive connection.
**Persona**: IT Admin with Google Workspace Admin access + Google Cloud access
**Entry**: Settings → Integrations → Add → Google Drive

```
STEP 1: Choose Auth Mode
  System asks:
    Does your organization use Google Workspace (G Suite)?
    [Yes — use Service Account + Domain-Wide Delegation] (recommended for enterprise)
    [No — use OAuth 2.0 personal authorization]

  If OAuth selected → simplified 3-step OAuth flow (skip to STEP DWD-7)
  If DWD selected → continue below

STEP 2: Create Google Cloud Project and Service Account
  Instructions:
    1. Open Google Cloud Console → console.cloud.google.com
    2. Create Project: "mingai-drive-sync" (or use existing)
    3. Enable APIs:
       → Library → search "Google Drive API" → Enable
       → Library → search "Admin SDK API" → Enable
    4. IAM & Admin → Service Accounts → Create Service Account
       Name: "mingai-drive-sync"
       Description: "Service account for mingai document sync"
       (Do NOT grant any IAM roles — DWD provides access, not IAM)
    5. On the service account → Keys → Add Key → JSON → Create
    6. JSON key file downloads automatically — keep this secure

  Form:
    Upload JSON key file: [Drop file here or browse]
    → System extracts client_id and client_email, displays for verification

STEP 3: Grant Domain-Wide Delegation
  Instructions:
    1. Open Google Workspace Admin Console → admin.google.com
       (requires Workspace Super Admin access)
    2. Security → API Controls → Domain-Wide Delegation → Add New
    3. Client ID: [shows the numeric client_id extracted from JSON]
       (copy this number — NOT the email address)
    4. OAuth Scopes:
       https://www.googleapis.com/auth/drive.readonly
       https://www.googleapis.com/auth/drive.metadata.readonly
    5. Click Authorize

  System shows the Client ID prominently to copy into Admin Console

STEP 4: Create the Sync Service Account
  IMPORTANT — displayed with emphasis:
    "The service account impersonates a real Google Workspace user to access Drive.
    You need to create a dedicated Workspace user for this purpose."

  Instructions:
    1. In Google Workspace Admin Console → Users → Add New User
    2. Name: "mingai Sync Service"
    3. Email: "mingai-sync@acme.com" (use your actual domain)
    4. Note: This is a real Workspace user, NOT the service account
    5. Assign this user as a member of any Shared Drives to sync
    6. Grant this user read access to any folders/My Drive items to sync

  Why explanation (expandable):
    "Google's DWD works by impersonating a real Workspace user. The service account
    acts on behalf of this sync user to access files. If the sync user cannot see a file,
    neither can the sync service. This gives you full control: remove the sync user from
    a drive to stop syncing it."

  Form:
    Sync user email: [mingai-sync@acme.com]

STEP 5: Test Connection
  Admin clicks "Test Drive Access"
  System authenticates as sync user, calls Drive API: files.list
  Success: "✓ Connection successful — Drive accessible as mingai-sync@acme.com"
  Lists accessible drives and folders visible to the sync user

STEP 6: Select Drives/Folders to Sync
  Admin sees tree of drives and folders accessible to sync user:
    ☑ Finance Shared Drive (selected — 634 files)
    ☑ HR Policies (folder in HR Shared Drive — 89 files)
    ☐ Executive Reports (excluded — sync user should not have access)

  Sync schedule: [Every 30 minutes ▼]

STEP 7: Initial Sync Starts
  "Starting sync. The Finance Shared Drive sync will take approximately 20-40 minutes."
  Admin notified when complete.

  [OAuth path for non-Workspace]:
    Simplified: Click "Connect Google Drive" → Google OAuth screen → Grant drive.readonly
    Limitation notice: "This grants access to files owned by or shared with your personal account.
    For organization-wide access, use the Service Account setup above."
```

---

## Flow 4: Manage Sync Health and Fix Failures

**Trigger**: Sync failure alert arrives, or admin performs routine health check.
**Persona**: Tenant Admin (monitoring role)
**Entry**: Dashboard → sync failure notification → OR Documents → Sync Health tab

```
STEP 1: View Sync Status Dashboard
  Admin sees status cards per connected source:

  [SharePoint: Contoso HR Portal]          [Google Drive: Finance Team Drive]
  Status: ● Healthy                        Status: ⚠ Warning
  Last sync: 8 minutes ago                 Last sync: 2.5 hours ago (expected: 30 min)
  Indexed: 1,247 docs                      Indexed: 834 docs
  Pending: 0 | Failed: 0                   Pending: 0 | Failed: 12
  Next full scan: tomorrow 02:00           Error: Permission denied

STEP 2: Investigate Failed Documents
  Admin clicks "12 failed documents" on Google Drive card
  System shows table:
    File: "Q4 2025 Budget Revision.xlsx"
    Location: Finance Shared Drive / Confidential / Q4
    Error: "403 Permission Denied"
    Diagnosis: "The sync user (mingai-sync@acme.com) does not have access to this subfolder"
    Fix suggestion: "Add mingai-sync@acme.com as a Viewer in the 'Confidential' folder, or exclude this folder from sync"
    [Add to Exclusion List] [Open in Google Drive] [Dismiss]

  Admin clicks "Add to Exclusion List" for sensitive files → confirms
  System adds folder to exclusion list → failed docs removed from error list

STEP 3: Retry Failed Documents
  For documents with transient errors (API timeout, temporary quota):
    Admin selects documents → "Retry Selected"
    System retries immediately → progress shown inline

STEP 4: Trigger Manual Sync
  Admin clicks "Sync Now" on SharePoint card
  System queues immediate sync run
  Progress shows: "Scanning for changes since last sync..."
  Shows incremental count: 3 new docs, 1 modified, 0 deleted

STEP 5: Request Full Re-Index
  Admin considers full re-index after a major document reorganization
  Clicks "Full Re-Index" → system warns:
    "This will delete all current index entries for this source and rebuild from scratch.
    Users will see reduced search results during the process (~45 minutes).
    Estimated token cost: ~$0.18 (embeddings for 1,247 documents)"
  Admin confirms → full re-index queued
  Dashboard shows: "Full re-index in progress: 234/1,247 documents processed"
```

---

## Flow 5: Build and Manage the Organizational Glossary

**Trigger**: Admin notices AI giving wrong answers about company-specific terms, OR system surfaces glossary miss signals.
**Persona**: Knowledge Manager / Tenant Admin
**Entry**: Workspace → Glossary

```
STEP 1: Review Glossary Miss Signals (Proactive)
  System shows "Suggested Additions" banner:
    "These terms appeared in user queries this week without a glossary entry:
    'EMEA' (queried 47 times), 'Project Falcon' (queried 23 times), 'RFP' (queried 12 times)"
  Admin can click each suggestion to pre-fill a new glossary entry

STEP 2: Add New Glossary Entry
  Admin clicks "Add Term" or clicks a suggested term

  Form:
    Term: [EMEA]
    Full form: [Europe, Middle East, and Africa]  (optional)
    Definition: [Our primary revenue region, comprising the European Union, UK, Middle East,
                 and Sub-Saharan Africa. Sales targets are set separately for EMEA vs APAC vs Americas.]
    Context tags: [finance] [sales] (type to add tags)
    Scope: [All users ▼]  or [specific roles] or [specific KBs]
    Character counter: 128/200 characters used

  Preview: "How this term will appear in AI context:
    EMEA (Europe, Middle East, and Africa): Our primary revenue region...
    [✓ Looks good]"

  Click Save → term active immediately (next AI query will use it)

STEP 3: Bulk Import Existing Glossary
  Admin has existing terminology list in CSV/Excel
  Clicks "Import CSV"
  Downloads template: term, full_form, definition, context_tags, scope
  Uploads filled CSV
  System previews: "47 terms found. 3 validation issues:
    Row 12: Definition exceeds 200 characters (current: 234) — truncate or shorten
    Row 23: Duplicate term 'PO' — merge with existing entry?
    Row 31: Empty definition — required field"
  Admin resolves issues → Import 44 valid terms
  Result: "44 terms imported successfully"

STEP 4: Review Glossary Performance
  Glossary analytics section shows:
    Term | Queries with this term | Satisfaction with term present | Satisfaction without
    ──────────────────────────────────────────────────────────────────────────────────
    EMEA | 47 | 84% | N/A (new term)
    QBR  | 31 | 79% | 64% (before term was added — significant improvement!)
    PO   | 28 | 71% | 68% (marginal improvement — definition may need refinement)
  Admin can see which glossary terms are making a measurable difference

STEP 5: Edit and Remove Terms
  Admin edits "PO" definition — adds disambiguation:
    "PO: In financial contexts, Purchase Order. In engineering contexts, Product Owner.
    Context determines which meaning applies."
  Saves → change active immediately
```

---

## Flow 6: Manage User Access and RBAC

**Trigger**: New employee joins, employee role changes, or admin needs to grant access to a sensitive KB.
**Persona**: Tenant Admin (IT admin or HR admin)
**Entry**: Settings → Users

```
STEP 1: Invite New User(s)
  Admin clicks "Invite Users"
  Form:
    Email: user@acme.com
    Role: [Reader ▼] (options: Viewer, Reader, Analyst, Tenant Admin)
    Knowledge Bases: ☑ General Policy KB  ☑ Finance KB  ☐ HR Confidential KB
    Agents: ☑ General Assistant  ☑ Finance Analyst  ☐ HR Policy Agent

  Add more button → another row appears
  Or: "Bulk Invite" → CSV upload with email, role, kb_assignments, agent_assignments

  Click "Send Invites"
  System sends invite email to each user
  Users appear in directory with status "Pending" until accepted

STEP 2: Manage Role Change
  Employee promoted from Reader to Analyst
  Admin finds user in directory (search by name or email)
  Clicks user → User Detail panel opens:
    Name: Alice Chen
    Email: alice@acme.com
    Role: Reader → change to [Analyst ▼]
    KBs: Finance KB ✓, General Policy ✓
    Agents: Finance Analyst ✓
    Last login: 2 hours ago
    Status: Active

  Changes role to Analyst
  System: "Role change will take effect on Alice's next page load (her current token expires in 14 minutes)"
  Admin can click "Force logout" to apply immediately if needed

STEP 3: Grant Access to Sensitive KB
  HR manager requests that their team access the new "Maternity Leave Policy 2026" knowledge base

  Admin navigates to Documents → Knowledge Bases → "HR Maternity Policy 2026"
  → Access Control tab
  Current setting: Visibility: Workspace-wide (everyone)
  Admin changes to: Role-Restricted
  Roles with access: [tenant_admin] [analyst] — removes 'reader' and 'viewer'

  Or: User-specific (for very sensitive content):
  Add specific users: alice@acme.com, bob@acme.com
  Click Save
  System: "5 users who had access via their Reader role no longer have access.
  Any agents configured to query this KB will respect these restrictions."

STEP 4: Enable Access Request Workflow
  Admin navigates to Settings → Access Control → Access Requests
  Toggles "Allow users to request access to restricted KBs and agents"
  Sets approval routing: "Send all access requests to me (tenant_admin@acme.com)"
  Saves

  User experience (after admin enables):
    User sees locked agent: "HR Policy Agent — Request Access"
    User submits request with reason: "I'm the new HR coordinator and need access"
    Admin receives notification → approves → user gets access within 5 minutes

STEP 5: Suspend Departing Employee
  Employee leaves organization
  Admin finds user → "Suspend Account"
  System: "Alice Chen's access will be blocked immediately.
  Her conversation history is preserved for 90 days."
  Admin confirms → Alice's next API call returns 401
  If also removed from SSO group: automatic revocation on next login attempt

STEP 6: Bulk Offboarding
  End-of-quarter contractor offboarding: 12 contractor accounts to suspend
  Admin downloads user list as CSV
  Filters by role="analyst" and last-login > 30 days ago (potential inactive contractors)
  Reviews list → selects 12 accounts → "Bulk Suspend"
  System confirms: "12 accounts suspended. Data retained for 90 days."
```

---

## Flow 7: Deploy Agent from Library (Adopt)

**Trigger**: Admin wants to give users an AI agent for a specific function (HR queries, finance analysis, etc.)
**Persona**: Tenant Admin (any type — IT admin, HR manager, knowledge manager)
**Entry**: Workspace → Agents → Browse Library

```
STEP 1: Browse Agent Library
  Library shows available templates as cards:
    ┌────────────────────────┐  ┌────────────────────────┐
    │ HR Policy Assistant    │  │ Financial Analyst      │
    │ ★★★★☆ 82% satisfaction│  │ ★★★★☆ 79% satisfaction│
    │ Category: HR           │  │ Category: Finance      │
    │ Version: v2            │  │ Version: v3            │
    │ Used by 11 orgs        │  │ Used by 8 orgs         │
    │ [Preview] [Deploy]     │  │ [Preview] [Deploy]     │
    └────────────────────────┘  └────────────────────────┘
  Filter by: category, plan tier eligibility, satisfaction score, recently added

STEP 2: Preview Template
  Admin clicks "Preview" on HR Policy Assistant
  Modal shows:
    Description: "Helps employees navigate HR policies, benefits, and procedures"
    System prompt: [Read-only view — shows the structure without full content]
    Required variables:
      {{company_name}} — "Your organization name"
      {{hr_contact_email}} — "Where users go for complex HR issues"
    Optional variables:
      {{jurisdiction}} — "Primary legal jurisdiction for employment law" (defaults to US Federal)
    Example conversation:
      User: "How many vacation days do new employees get?"
      Agent: "Based on the HR policy documents, new employees receive..."

STEP 3: Deploy Agent
  Admin clicks "Deploy HR Policy Assistant"
  Configuration form:
    Agent name (visible to users): "Acme HR Helper"
    Description: "Ask questions about Acme Corp HR policies and benefits"

    Fill required variables:
      Company name: "Acme Corp"
      HR contact email: "hr@acme.com"

    Fill optional variables:
      Jurisdiction: "US Federal + California"

    Knowledge bases (pre-populated with suggested KBs from admin's connected sources):
      ☑ SharePoint HR Portal (recommended — contains HR policy documents)
      ☐ Finance Documents (not relevant)

    Access control:
      ● Workspace-wide (all users)
      ○ Role-restricted
      ○ Specific users

  Admin clicks "Deploy"
  Agent is live immediately: appears in user-facing agent list

STEP 4: Verify Agent Behavior
  Admin uses the test chat in the admin console:
    "How many sick days are Acme employees entitled to?"
  Agent responds with answer drawn from the HR Policy SharePoint library
  Admin verifies: answer matches their current policy document
  If answer is wrong: admin checks if the relevant policy document is indexed
  (checks sync status of HR Portal KB)
```

---

## Flow 8: Build a Custom Agent in Agent Studio

**Trigger**: Admin wants an agent that does not exist in the library, or needs full control over agent behavior.
**Persona**: Knowledge Manager / Tenant Admin with domain expertise
**Entry**: Workspace → Agents → Create New Agent → Agent Studio

```
STEP 1: Set Agent Identity
  Name: "Acme Procurement Assistant"
  Description: "Helps procurement team understand vendor contracts, purchasing policies, and approval workflows"
  Category: [Operations]
  Avatar: [select from icon library or upload image]

STEP 2: Write System Prompt
  Large text area with syntax highlighting for {{variables}}

  Admin writes:
    "You are a procurement assistant for Acme Corp. You help the procurement team
    understand vendor contracts, purchasing policies, and spending approval workflows.

    When answering questions:
    - Only reference information from the Acme Procurement Policy document
    - If a contract question comes up, remind users that specific contract terms
      require Legal team review at legal@acme.com
    - Always confirm your answers with document references"

  AI-assisted prompt improvement (optional):
    System suggests: "Your prompt could benefit from specifying what to do when
    information is not found. Add: 'If you cannot find the answer in the documents,
    say so and suggest who to contact.'"
    Admin accepts or dismisses suggestion.

STEP 3: Attach Knowledge Bases
  Admin selects KBs this agent can query:
    ☑ Procurement Policies (SharePoint Finance Portal / Procurement)
    ☑ Vendor Contracts (SharePoint Legal / Contracts — requires analyst+ role to access)
    ☐ HR Policies (not relevant)

  Note shown: "Users who access this agent must have access to all selected KBs.
  Users without KB access will see responses with reduced context."

STEP 4: Set Guardrails
  Blocked topics: "Competitor pricing, personnel decisions, financial forecasts"
  Required response elements: "Always include document source reference"
  Confidence threshold: 0.60 (below this, agent says "I'm not certain — please verify")
  Max response length: 500 words

STEP 5: Add Example Conversations (optional but recommended)
  Admin adds 3 example Q&A pairs:
    Example 1:
      User: "What is the spending limit for IT equipment purchases without manager approval?"
      Agent: "Based on the Procurement Policy (Section 3.2), individual purchases up to $2,500
              do not require manager approval. Above that threshold, manager sign-off is required."
  These examples help calibrate the model's response style.

STEP 6: Test the Agent
  Test chat interface appears in the right panel
  Admin asks 5-6 questions covering:
    - Common user questions
    - Edge cases (what happens when the answer isn't in the docs?)
    - Guardrail triggers (admin tries to ask about competitor pricing → guardrail fires correctly)
  Admin reviews responses, adjusts prompt if needed, re-tests

STEP 7: Publish
  Click "Publish"
  Access control: Workspace-wide / Role: [Analyst] (procurement team)
  Agent goes live → appears in analyst users' agent list
  Admin gets a deployment summary:
    "Acme Procurement Assistant is live.
    Accessible to: Analysts (78 users)
    Drawing from: Procurement Policies KB (924 docs), Vendor Contracts KB (156 docs)
    Monitor performance at: Workspace → Analytics → Agents → Procurement Assistant"
```

---

## Flow 9: Monitor User Feedback and Resolve Issues

**Trigger**: Admin reviews weekly AI performance, or receives a notification about low satisfaction.
**Persona**: Tenant Admin
**Entry**: Workspace → Analytics → Feedback

```
STEP 1: View Weekly Satisfaction Summary
  Dashboard shows:
    7-day satisfaction rate: 74% (⚠ down from 82% last week)
    Agent breakdown:
      Acme HR Helper         | 89% | ↑ +3% | 234 rated responses
      Finance Analyst        | 71% | ↓ -8% | 156 rated responses
      Procurement Assistant  | 63% | ↓ -12% | 89 rated responses  [Alert]

STEP 2: Investigate Low-Performing Agent
  Admin clicks "Procurement Assistant" (63% satisfaction, -12%)
  Detail view:
    Satisfaction trend: dropped sharply after 2026-02-28
    Possible cause: "Procurement Policies KB last full sync was 2026-01-15 (42 days ago)"
    Low confidence responses: 23 this week (26% of total — unusually high)
    Most common low-confidence topics: "Preferred vendor list" (12 instances)
    Sample low-rated response:
      User: "Is Acme's preferred vendor for IT laptops still Dell?"
      Agent: "I don't have current information about preferred vendor agreements."
      User rating: ☹ (thumbs down)

  Root cause diagnosis:
    "The vendor list was updated February 28 (the day satisfaction dropped)
    but the sync has not captured the updated policy document."

STEP 3: Fix the Root Cause
  Admin clicks "Sync Procurement Policies KB now"
  Sync runs → captures updated vendor list policy
  Admin re-tests the agent: "Is Acme's preferred vendor for IT laptops still Dell?"
  New response: "According to the updated Preferred Vendor List (last updated Feb 28),
  Dell remains the preferred vendor for standard IT laptops..."
  Admin confirms fix → satisfaction expected to recover

STEP 4: Review User-Submitted Issue Reports
  Admin sees issue queue: 3 open reports
  Report 1 (routed from platform admin):
    Reporter: procurement-analyst@acme.com
    Issue: "The agent keeps saying it doesn't know who to escalate to for large contracts"
    Admin analysis: missing escalation path in system prompt
    Action: Edit agent system prompt → add escalation guidance → re-publish
    Response to user: "Thanks for the report. I've updated the Procurement Assistant with
    clearer escalation guidance. Try it now."

  Report 2 (tenant config issue, user-submitted):
    Reporter: hr-admin@acme.com
    Issue: "I can't access the HR Policy Agent"
    Admin checks: hr-admin@acme.com has "Reader" role; HR Policy Agent is restricted to "Analyst+"
    Action: Either upgrade user's role or create a Reader-accessible HR agent variant
    Response to user: "Your current role doesn't have access to this agent.
    I've upgraded your account to Analyst — you should now see it."

STEP 5: Track Resolution Metrics
  Admin views resolution summary:
    This month: 8 issues reported | 6 resolved | 2 pending
    Average resolution time: 4.2 hours
    Most common issue type: "Access / permissions" (3/8)
    Resolution types: Admin fixed config (5), Routed to platform (1), User question answered (2)
```

---

## Edge Cases

### E1: SSO Setup Fails During Wizard

```
Admin completes SAML configuration → test login fails
System shows: "SAML Response Error: Missing required attribute 'email'"
Diagnosis: "The SAML application in your IdP is not sending the email attribute.
Ensure the attribute statement maps: user.email → email"
Admin returns to IdP, fixes attribute mapping, re-tests
Second attempt succeeds
```

### E2: SharePoint Client Secret Expires

```
System detects 401 error on scheduled sync
Notification sent: "SharePoint connection expired — client secret may have expired"
Admin navigates to Settings → Integrations → SharePoint → Reconnect
Wizard shown: "Your current credentials failed authentication.
If your client secret expired, create a new one in Azure Portal and enter it below."
Admin creates new secret in Azure → enters it → test connection passes
Sync resumes automatically
```

### E3: Google Drive Sync User Loses Access

```
12 documents suddenly fail with "Permission Denied" errors
Admin investigates: sync user (mingai-sync@acme.com) was removed from a Shared Drive by Drive admin
Admin adds sync user back to Shared Drive as Viewer in Google Workspace Admin Console
Admin clicks "Retry Failed Documents" → all 12 re-index successfully
```

### E4: Agent Studio Agent Produces Harmful Output

```
Admin receives report: "The procurement agent recommended an unlisted vendor for a $50K purchase"
Admin reviews: Agent Studio prompt did not explicitly prohibit recommending vendors not on the approved list
Admin edits guardrail: "Never recommend vendors not on the current Preferred Vendor List"
Agent re-tested: correctly declines to recommend unapproved vendors
Old conversations are not affected — only future responses apply new guardrail
```

### E5: User Access Request for Sensitive KB

```
User requests access to "Legal Contracts KB"
Admin reviews request: user is a new procurement analyst (legitimate need)
Admin approves with note: "Approved — this KB contains confidential vendor agreements.
Do not share contract contents externally."
User receives notification + access granted
Audit log records: who approved, when, reason provided
```

### E6: New Employee Bulk Onboarding (100+ users)

```
Company acquires a subsidiary — 127 new employees need access
HR provides CSV: email, department, job title
Admin maps departments to roles: Engineering → Analyst, Operations → Reader, Management → Analyst
Uses bulk invite CSV format: email, role
127 users invited simultaneously
SSO group assignments happen separately in Entra ID → next-day sync applies AI access rules
Admin verifies: checks 3 random new users to confirm correct role assignment
```

---

## Flow 10: Tenant Admin — Issue Queue Management

**Trigger**: Tenant admin opens the Issues panel in their admin console, or receives a notification about a new user-submitted report in their workspace.
**Entry**: Tenant Admin Console → Issues (left nav, Insights section)
**Persona**: Tenant Admin (workspace administrator for one tenant, e.g. Acme Corp)

---

### Happy Path — Reviewing and Acting on a Reported Issue

```
Start
  |
  v
[Tenant Admin opens Issues panel]
  |-- Notification badge may have triggered this visit:
  |   e.g. "2 new issues reported by your users"
  |
  v
[Issue Queue — default view]
  |-- Table columns:
  |   |-- Reference (rpt_Q5FEID) — monospaced
  |   |-- Reported by (user name / email)
  |   |-- Issue type (Bug / Performance / UX / Feature Request)
  |   |-- AI severity (P0–P4, colour-coded)
  |   |-- Status (New / In Triage / In Progress / Resolved / Won't Fix)
  |   |-- SLA target (date, red if overdue)
  |   |-- Submitted (relative timestamp)
  |
  |-- Default filter: Status = New or In Triage
  |-- Sorted by: SLA target ascending (most urgent first)
  |
  v
[Admin clicks a specific report]
  |
  v
[Issue Detail Panel slides in]
  |-- Reporter: Sarah Ang · Finance Team
  |-- Submitted: 2026-03-06 14:23 · Chat screen
  |-- Type: Bug · AI severity: P2 · SLA target: 2026-03-13
  |
  |-- Session context:
  |   |-- Last query: "What is our travel reimbursement limit for APAC?"
  |   |-- Model: GPT-5.2-chat · Balanced profile
  |   |-- Retrieval confidence: 41% (low)
  |   |-- Sources searched: HR Policies (SharePoint), Finance Policies (SharePoint)
  |
  |-- Screenshot (blurred by default — same R4.1 protection as submission)
  |   |-- Admin clicks "Reveal" if needed for investigation
  |
  |-- Description: "Confidence score missing after Finance query. Expected to
  |    see the confidence percentage below the response."
  |
  |-- AI triage result:
  |   |-- Root cause hypothesis: "SharePoint sync may be stale — last successful
  |       sync was 42 days ago. Retrieval confidence below threshold."
  |   |-- Duplicate check: 0 matching open issues
  |   |-- GitHub issue: #4521 (linked)
  |
  v
[Admin reviews and takes action]
  |
  +-- ACCEPT AI TRIAGE (most common)
  |     |-- Issue moves to "In Progress" status
  |     |-- Admin clicks "Sync Now" on Documents panel to address stale KB
  |     |-- Admin adds note: "KB re-synced. Monitoring for improvement."
  |
  +-- ROUTE TO PLATFORM ADMIN
  |     |-- Issue requires infrastructure investigation
  |     |-- Admin clicks "Escalate to Platform" with note
  |     |-- Platform admin Issue Queue receives a copy
  |     |-- Reporter notified: "Your issue has been escalated to our platform team."
  |
  +-- RESOLVE AS CONFIGURATION ISSUE
  |     |-- Admin identifies the root cause in workspace settings
  |     |-- Fixes it (e.g. re-syncs KB, adjusts agent guardrail)
  |     |-- Marks issue "Resolved" with resolution note:
  |         "SharePoint KB re-synced. Confidence scores should normalise
  |          within 30 minutes. Please retest."
  |     |-- Reporter receives: "Your issue rpt_Q5FEID has been resolved."
  |
  +-- MARK AS WON'T FIX
  |     |-- Requires a written reason (mandatory)
  |     |-- Reporter notified with explanation
  |
  v
[Reporter can confirm resolution]
  |-- "Was this resolved for you? [Yes] [No — still happening]"
  |-- If "No": regression report auto-created; admin notified
  |
  v
End
```

---

### Resolution Metrics View

```
[Admin clicks Issues → Overview tab]
  |
  v
[Resolution Summary]
  |-- This month: N issues reported | M resolved | K pending
  |-- Average resolution time: X hours
  |-- Most common issue type: [type] (N/total)
  |-- Resolution types:
  |   |-- Admin fixed configuration  (most)
  |   |-- Escalated to platform      (some)
  |   |-- Won't Fix / Expected       (rare)
  |
  v
[SLA Adherence]
  |-- P1 issues: SLA < 24h → X% adherence
  |-- P2 issues: SLA < 7d  → X% adherence
  |-- Issues overdue: highlighted in red in the queue
  |
  v
End
```

---

### Feature Request Routing

```
[User submits issue with type = "Feature Request"]
  |
  v
[AI routes to product backlog channel — NOT bug triage queue]
  |-- Appears in admin Issue Queue with type badge "Feature"
  |-- No SLA target assigned
  |-- Status: "In Backlog"
  |
  v
[Admin sees feature requests separately]
  |-- Can vote to prioritise (increases visibility to platform team)
  |-- Can add workspace context: "5 of our users have mentioned this"
  |
  v
End
```

---

### Configuring Issue Reporting Settings (Flow 6 reference)

Per the product spec (10-issue-reporting-flows.md, Flow 6), tenant admins can configure:

- GitHub / GitLab / Jira / Linear integration for their team's issue tracking
- Reporter widget position and label
- Notification recipients for P0/P1 alerts (email + Slack webhook)
- Custom SLA targets (override platform defaults per severity)

Entry: Tenant Admin Console → Settings → Issue Reporting

---

### Edge Cases

**E-IR-1: Reporter submits sensitive information in description**

```
User describes issue but pastes a contract excerpt in the description field
Admin reviews: flags as "Contains sensitive data"
Admin can redact the description before routing to GitHub
Platform does not share reporter content externally without admin review
```

**E-IR-2: Same issue reported by 10 users in one day**

```
Widespread problem (e.g. SharePoint sync failure affecting all users)
AI auto-escalates to P1 based on duplicate volume threshold (10 reports)
Admin receives P1 alert
Admin addresses root cause (fixes sync), bulk-resolves linked duplicates
All 10 reporters notified simultaneously: "Your issue has been resolved."
```

**E-IR-3: Report submitted but GitHub integration not configured**

```
Issue created successfully in mingai platform
GitHub step is skipped (logged as "GitHub not configured")
Admin receives: "Issue rpt_Q5FEID received. Configure GitHub integration to
auto-create issues in your repository. [Configure now]"
```

---

---

## Flow 11: Low-Satisfaction Response Escalation (3-Rating Rule)

**Trigger**: Three or more distinct users submit a thumbs-down rating on the same AI response (message_id) within any 7-day window.
**Persona**: Tenant Admin (receives notification and review queue entry)
**Entry**: Workspace → Analytics → Feedback → Flagged Responses

This flow covers the **non-cached** response case. The cached response case (cache invalidation on thumbs-down) is defined in `05-caching-ux-flows.md` Flow EU-C5.

---

### Auto-Escalation and Admin Review

```
Start
  |
  v
[3rd user submits thumbs-down on message_id: msg-abc123]
  |
  v
[Platform: threshold check]
  |-- Query: SELECT COUNT(*) FROM feedback WHERE message_id = 'msg-abc123' AND rating = -1
  |-- Count = 3 → threshold met
  |
  v
[System: auto-escalation]
  |-- POST /api/v1/admin/feedback/flags (internal)
  |-- Creates flagged_responses record:
  |   |-- message_id: msg-abc123
  |   |-- negative_count: 3
  |   |-- auto_escalated_at: timestamp
  |   |-- status: pending_review
  |-- Notification sent to tenant admin:
  |   |-- In-app badge on Analytics → Feedback → Flagged tab
  |   |-- Email (if enabled): "A response received 3 negative ratings and requires review"
  |
  v
[Admin navigates to Feedback → Flagged Responses]
  |
  v
[Flagged Responses table]
  |-- Row: msg-abc123 | Query: "What is the Q4 travel budget?" | Negative: 3 | Status: Pending
  |-- Sort: newest / most negative ratings first
  |
  v
[Admin clicks row → Review Detail Panel]
  |
  v
[Detail Panel]
  |-- Original query: "What is the Q4 travel budget?"
  |-- AI response shown in full
  |-- Source citations: "Finance Policy 2024 (SharePoint)"
  |-- All negative feedback entries:
  |   |-- User A: "Inaccurate — this is the 2024 budget, not 2025"
  |   |-- User B: "Incomplete — missing APAC region figures"
  |   |-- User C: [no comment, thumbs-down only]
  |
  v
[Admin diagnoses root cause]
  |
  +-- CASE: Stale source document
  |     |-- KB sync check shows: Finance Policy KB last synced 45 days ago
  |     |-- Action: Admin clicks "Sync Now" on Finance Policy KB
  |     |-- After sync: response will use updated document on next query
  |     |-- Marks flagged item: "Resolved — KB re-synced"
  |     |-- Users who flagged: notified "This issue has been addressed"
  |
  +-- CASE: Agent system prompt too narrow
  |     |-- Admin reviews: agent's system prompt says "Finance Index only"
  |     |-- Action: Edit agent in Agent Studio → add Regional Finance Index
  |     |-- Re-test: ask same question → response now includes APAC figures
  |     |-- Marks flagged item: "Resolved — agent updated"
  |
  +-- CASE: Platform bug (not fixable by tenant admin)
  |     |-- Admin escalates: "Escalate to Platform" with note
  |     |-- Platform admin receives copy in their issue queue
  |     |-- Marks flagged item: "Escalated — awaiting platform fix"
  |
  +-- CASE: User misunderstanding (response was correct)
        |-- Admin reviews: response accurately cited 2025 budget
        |-- Action: marks "Won't Fix — response is correct" with explanation
        |-- Optional: admin replies to users with context note
        |
        v
[Flagged item resolved or escalated]
  |-- Status updated in flagged_responses table
  |-- Audit log entry: who acted, what was done, when
  |
  v
End
```

---

### Aggregate Flagging Analytics

```
[Admin → Analytics → Feedback → Summary]

Flagged Responses This Month: 7
  Auto-resolved (cache invalidated, re-served): 4
  Pending admin review: 2
  Escalated to platform: 1

Most flagged topics: "travel budget", "Q4 reporting", "APAC expenses"
Most common flag reason: "Inaccurate" (71%)
Average negative ratings before flag: 3.2 (some items accumulate more before review)

Recommendation shown: "5 flagged responses reference Finance Policy 2024.
Consider forcing a full KB re-index of the Finance Policy SharePoint library."
[Trigger Full Re-Index]
```

---

**Section Added**: 2026-03-06
**Covers**: Issue Queue review, resolution actions, escalation to platform, SLA monitoring, feature request routing

**Section Added**: 2026-03-07
**Covers**: Low-satisfaction response escalation (3-rating rule), flagged response review, root cause actions
