# 19 — Tenant Admin: Advanced Configuration Flows

**Date**: 2026-03-10
**Personas**: Tenant Admin, End User (affected by downstream changes)
**Domains**: MFA Enforcement, Document-Level Permission Verification, Agent Cloning, Agent Live Version Update, Workspace Branding (ongoing), Multilingual Query Expansion

---

## Flow 1: MFA Enforcement for Non-SSO Users

**Trigger**: Tenant admin wants to enforce MFA for all users who log in with email+password (non-SSO), following a security review recommendation.
**Persona**: Tenant Admin (with IT Security approval)
**Entry**: Settings → Authentication → MFA Policy

```
STEP 1: Navigate to MFA Policy
  Tenant admin opens Settings → Security & Authentication
  Current state:
    Authentication mode: Platform-managed (email + password)
    MFA status: Optional (users can enable voluntarily)
    Users with MFA enabled: 4 of 23 users

  Admin clicks "MFA Policy" tab

STEP 2: Configure Enforcement Policy
  MFA Policy form:

  Enforcement level:
    [◉] Required for all users
    [ ] Required for tenant_admin role only
    [ ] Optional (users may enable voluntarily)

  Supported MFA methods (platform-managed):
    [✓] Authenticator app (TOTP — Google Authenticator, Authy, 1Password)
    [✓] SMS verification (fallback)
    [ ] Hardware key (FIDO2 / YubiKey) — Enterprise plan only
    [ ] Email code (not recommended for high-security environments)

  Grace period:
    [◉] 7 days — users can log in without MFA during grace period, then enforced
    [ ] 14 days
    [ ] Immediate (no grace period)
    [ ] Custom: __ days

  What happens to users who don't complete MFA setup after grace period:
    [◉] Block login with prompt to set up MFA
    [ ] Allow login but display persistent MFA setup banner

  Admin clicks "Review Impact"

STEP 3: Review Impact Before Enabling
  System calculates impact:
    Total users: 23
    SSO users: 8 (not affected — MFA managed by IdP)
    Platform-managed users: 15 (affected by this policy)
    Already have MFA: 4
    NEED TO ENROLL in grace period: 11

    At-risk users: 2 users have not logged in for 8+ days (may miss the grace period)
    Admin can proactively reach these users via "Notify specific users" below

  Admin notes at-risk users: user@acme.com, contractor@acme.com

STEP 4: Enable Policy with Targeted Pre-Notifications
  Admin clicks "Notify all affected users before enabling" (optional step)
  System drafts notification to 15 platform-managed users:
    "Important Security Update: MFA Required in 7 Days

     Starting March 17, your mingai account will require two-factor authentication
     to log in. Please set up your authenticator app before then to avoid disruption.

     Setup instructions: [link to help article]
     Time needed: ~3 minutes

     If you have questions, contact your IT team."

  Admin can edit the message and preview it, then click "Send Notification"
  Notifications sent via: in-app notification + email to all 15 users

  Admin then clicks "Enable MFA Policy"
  System shows final confirmation:
    "This will require MFA for 15 users in 7 days (March 17).
     4 users already enrolled. 11 users need to enroll during grace period."
  Admin clicks "Confirm — Enable MFA Requirement"

STEP 5: Grace Period (7 Days)
  Policy status: "MFA Required — Grace period active until March 17"
  Dashboard shows live enrollment tracker:
    Day 1: 4/15 enrolled (baseline)
    Day 2: 6/15 enrolled
    Day 3: 9/15 enrolled
    ...

  Users who log in during grace period see a banner:
    "⚠️ MFA Required — please set up your authenticator app before March 17.
     [Set Up Now] — takes 3 minutes"

  User clicks "Set Up Now" → guided enrollment flow:
    1. Download Google Authenticator or compatible app
    2. Scan QR code displayed on screen
    3. Enter 6-digit code to verify
    4. Recovery codes shown (user saves them)
    5. "MFA setup complete. You're protected."

STEP 6: Enforcement Day
  Grace period expires on March 17 at 00:00 UTC
  System enables enforcement for all non-enrolled users
  Next time each non-enrolled user tries to log in:

  CASE A: User complies
    User enters email + password → system redirects to MFA setup
    User completes setup → logs in successfully

  CASE B: User cannot comply (lost phone, etc.)
    User enters email + password → prompted for MFA code
    User clicks "I lost access to my authenticator"
    → System shows: "Contact your workspace administrator to reset your MFA"
    User contacts tenant admin

  Admin can reset MFA for a user:
    Settings → Users → [user] → Security → "Reset MFA — user must re-enroll next login"

STEP 7: Monitor Ongoing Compliance
  MFA dashboard shows ongoing compliance:
    Users with MFA: 15/15 (100%) ← after enforcement
    MFA method breakdown: 11 authenticator app, 4 SMS
    Recent MFA resets: 1 (user lost phone)
    Failed MFA attempts (last 7d): 2 (flagged for review — possible account sharing?)

  Admin can investigate failed MFA spikes as potential unauthorized access attempts
```

**Edge Cases**:

- SSO users are NOT affected by this policy. SSO handles MFA at the IdP level. If tenant admin wants SSO users to use MFA, they configure it in their IdP (Okta / Entra ID), not in mingai.
- Contractor who shares a login across a team → MFA enforcement forces them to use a single authenticator → admin may need to convert to individual accounts
- User is on vacation during grace period, returns to find login blocked → Admin resets MFA, user re-enrolls on first login

---

## Flow 2: Document-Level Permission Verification

**Trigger**: Tenant admin wants to verify that only authorized users can access documents in the "Legal" knowledge base, and that users without access cannot retrieve those documents via AI queries.
**Persona**: Tenant Admin
**Entry**: Settings → Knowledge Bases → Legal KB → Access Control

```
STEP 1: Review KB Access Configuration
  Tenant admin opens Settings → Knowledge Bases
  List shows all KBs:
    General Company KB      | Workspace-wide   | 2,081 docs | Active
    HR Policies KB          | Role-restricted  | 347 docs   | Active
    Legal Contracts KB      | User-specific    | 89 docs    | Active  ← click this
    Finance Reports KB      | Role-restricted  | 512 docs   | Active

  Admin clicks "Legal Contracts KB" → KB detail panel opens

STEP 2: View Current Access Configuration
  KB Access Control tab:

    Visibility: User-specific
    Users with access:
      sarah.johnson@acme.com  (tenant_admin)    ✓
      mark.chen@acme.com      (analyst)         ✓
      legal@acme.com          (reader)          ✓

    Users WITHOUT access:
      All other 20 users in workspace

  Admin reviews and confirms this is correct configuration.
  The KB is connected to: SharePoint Legal drive (89 files indexed)

STEP 3: Verify KB Access Enforcement — Test Authorized User
  Admin wants to verify an authorized user can query this KB.
  Admin uses "Access Test" tool:

  Simulate query as user:
    User: mark.chen@acme.com (has access)
    Query: "What are the key terms in our standard NDA template?"
    KB scope: Legal Contracts KB
    [Run Test]

  System simulates the query under mark.chen's permissions:
    Result: ✓ Query processed
    Sources returned: 3 documents from Legal KB (NDA Template v3, Contract Checklist, etc.)
    Response: "Based on the NDA template, the key terms include: 1) Definition of
      Confidential Information (Section 1)..."
    Verdict: AUTHORIZED USER CAN ACCESS — PASS ✓

STEP 4: Verify KB Access Enforcement — Test Unauthorized User
  Admin simulates query as an unauthorized user:
    User: david.kim@acme.com (no access to Legal KB)
    Query: "What are the key terms in our standard NDA template?"
    [Run Test]

  System simulates the query under david.kim's permissions:
    Result: ✓ Query processed (user can still send a query)
    Sources returned: 0 documents from Legal KB (correctly excluded)
    Response from agent: "I don't have relevant documents to answer this question.
      If you believe you need access to this information, contact your workspace admin."
    Verdict: UNAUTHORIZED USER CANNOT ACCESS LEGAL KB — PASS ✓

  If the unauthorized user explicitly mentions a legal document:
    Query: "Show me Contract ACME-NDA-2024-003"
    Sources returned: 0 (document not returned — access blocked)
    Verdict: SPECIFIC DOCUMENT ACCESS BLOCKED — PASS ✓

STEP 5: Audit Log — Who Has Accessed the KB
  Admin clicks "Access Log" for Legal Contracts KB
  Log shows (last 30 days):
    Date       | User              | Query excerpt                    | Docs retrieved
    ─────────────────────────────────────────────────────────────────────────────────
    Mar 9      | sarah.johnson     | "Review indemnification clause"  | 2 docs
    Mar 8      | mark.chen         | "IP ownership for contractors"   | 3 docs
    Mar 7      | mark.chen         | "NDA terms for Vendor A"         | 1 doc
    Mar 5      | legal@acme.com    | "Liability cap standard"         | 2 docs
    Feb 28     | david.kim         | "NDA template"                   | 0 docs (blocked)
    Feb 25     | sarah.johnson     | "Contract renewal terms"         | 4 docs

  Admin can see: david.kim attempted a query on Feb 28 (correctly blocked, 0 docs returned)
  This audit trail provides evidence for compliance reviews

STEP 6: Share KB Access With a New User
  Admin wants to temporarily grant legal-external@vendor.com access for a project:

  Admin clicks "Add User to KB"
    User: legal-external@vendor.com
    Access type: [◉] Permanent  [ ] Time-limited
    If time-limited: Expires [March 31, 2026]
  Admin clicks "Grant Access"

  legal-external@vendor.com receives notification:
    "You have been granted access to the Legal Contracts KB in Acme Corp's workspace.
     You can now query legal documents in your mingai chat."

  Admin notes: time-limited access expires automatically — no manual revocation needed

STEP 7: Verify SharePoint Permission Alignment
  Advanced check: Admin verifies that the documents in the Legal KB are also
  restricted at the SharePoint level (defense-in-depth).

  Admin clicks "Verify Source Permissions" (Enterprise plan feature)
  System connects to SharePoint API and checks:
    - For each indexed document: does the SharePoint permission list match the KB access list?
    - Documents where SharePoint permissions are WIDER than KB permissions (risk):
      "contract_template_v3.docx" — accessible by 5 users in SharePoint,
      but KB access grants only 3 users
      Action: OK — KB is MORE restrictive than SharePoint (correct behavior)
    - Documents where SharePoint permissions are MORE restrictive:
      "draft_contract_sealed.pdf" — restricted in SharePoint to General Counsel only
      but this user is not in KB access list → document was synced but no KB user
      can query it
      Action: Admin adds general.counsel@acme.com to KB access list

  Permission alignment summary:
    89 documents analyzed
    2 misalignment cases found (reviewed above)
    After admin adjustments: fully aligned ✓
```

---

## Flow 3: Agent Cloning / Duplication

**Trigger**: Tenant admin has a working "Finance Assistant" agent configured for the finance team, and wants to create a similar "Legal Finance Assistant" for a different team with adjusted prompts.
**Persona**: Tenant Admin
**Entry**: Settings → Agents → Finance Assistant → Clone

```
STEP 1: Initiate Clone
  Admin opens Settings → Agents
  Clicks "Finance Assistant" (Studio agent, not a template instance)
  In the agent detail panel, clicks "⋮" menu → "Duplicate Agent"

  Clone options:
    New agent name: Finance Assistant — COPY
    (admin edits to): Legal Finance Assistant
    What to copy:
      [✓] System prompt
      [✓] Knowledge sources (KB assignments)
      [✓] Guardrails
      [✓] Tool assignments
      [✓] Tone settings
      [ ] Conversation history (do not copy — confidential data from original)
    Status: Draft (not published until admin configures)

  Admin clicks "Create Clone"

STEP 2: Customize the Clone
  Legal Finance Assistant opens in Agent Studio (Draft state):

  Admin sees diff from original with all sections editable:

  A) System prompt — edit for Legal Finance use case:
    Original: "You are a financial assistant helping our finance team understand
      our company's financial data, policies, and metrics..."
    Edit to: "You are a specialized assistant for our Legal Finance team helping
      them understand financial obligations in contracts, billing structures, and
      legal-financial cross-functional processes..."
    Changes highlighted in diff view

  B) Knowledge Sources — adjust for Legal Finance:
    Remove: Finance Analytics KB (not relevant for Legal Finance)
    Add: Legal Contracts KB (now accessible to legal team)
    Keep: Finance Policies KB (relevant to both)

  C) Access Control:
    Original agent: visible to Finance team roles
    New: visible to Legal team + Finance Admin roles
    Admin assigns: mark.chen@acme.com (analyst), legal@acme.com (reader)

  D) Guardrails — adjust:
    Original blocked: "investment advice, stock trading"
    New blocked: "legal advice, attorney-client privileged matters"
    Note: guardrails are now different from original — deliberate

STEP 3: Test Clone Before Publishing
  Admin clicks "Test Agent" → test chat opens
  Types: "What are the payment terms in our standard contract and how do they
         align with our cash flow policies?"
  Agent responds drawing from both Legal Contracts KB and Finance Policies KB
  Response quality: PASS — agent correctly uses both knowledge sources

  Admin clicks "Publish Agent"
  Legal Finance Assistant status: Published
  Mark.chen and legal@acme.com can now see this agent in their agent selector

STEP 4: Both Agents Are Independent
  Admin changes Finance Assistant (original) system prompt after the clone:
    This change DOES NOT affect Legal Finance Assistant
    They are fully independent after cloning — changes to one do not propagate to the other

  If admin wants to sync future improvements:
    Admin must manually apply the same changes to the clone
    (There is no "link to parent" option — clones are autonomous)

  Audit log shows:
    "Legal Finance Assistant" created as clone of "Finance Assistant" by admin@acme.com
    This is useful for audit: explains origin of agent configuration
```

---

## Flow 4: Agent Live Version Update

**Trigger**: Tenant admin wants to update the system prompt of the deployed "HR Assistant" agent to reflect a new HR policy that was just published, WITHOUT taking the agent offline.
**Persona**: Tenant Admin
**Entry**: Settings → Agents → HR Assistant → Edit

```
STEP 1: Understand Update Scope
  Before editing a live agent, admin understands:

  Types of changes:
    Minor (effective immediately, no conversation disruption):
      - Adding/updating glossary terms
      - Adjusting max response length
      - Changing tone settings

    Major (may affect ongoing conversations):
      - System prompt changes
      - KB source changes (adding/removing knowledge)
      - Guardrail changes

  The admin wants to update the system prompt to include new remote work policy.
  This is a MAJOR change.

STEP 2: Review Current State of Live Agent
  Admin opens HR Assistant → Edit
  Current configuration:
    Version: 1.3 (last updated: 2026-02-14)
    Status: Published — live to 23 users
    Last 7 days: 148 queries, 84% satisfaction, 0 errors

  System prompt (current):
    "You are an HR assistant for Acme Corp. You answer questions about our HR
     policies including leave, benefits, performance reviews, and onboarding.
     Knowledge base: Acme HR Policies (updated weekly).
     Always cite the specific policy section..."

  Admin sees: "This agent has active conversations. Changes take effect for new queries.
  In-progress conversations may see different behavior after saving."

STEP 3: Make the Change
  Admin edits system prompt:
    Add after "onboarding":
    ", remote work policies, and the new hybrid work framework (effective March 1, 2026)"

  Admin also: updates KB — adds "Remote Work Policy 2026" document subset to HR KB
  (The document was uploaded yesterday and is now indexed)

  Change summary shown in diff view:
    + ", remote work policies, and the new hybrid work framework (effective March 1, 2026)"
    + KB addition: "Remote Work Policy 2026" (47 pages, indexed yesterday)

STEP 4: Pre-Save Test
  Admin clicks "Test Updated Version" before saving:
    Query: "Can I work from a different country for 2 weeks?"
    Expected: Draws from new Remote Work Policy 2026
    Result: "Under Acme's new hybrid work framework (effective March 1, 2026),
      employees may work from a different country for up to 14 consecutive days...
      [Section 3.2 of Remote Work Policy 2026]"
    PASS ✓

  Admin also tests original good case still works:
    Query: "How many days of sick leave do I have?"
    Result: Still answers correctly from HR Policies KB ✓

STEP 5: Save and Deploy
  Admin clicks "Save Changes"
  System saves as version 1.4 (minor patch increment for prompt changes)
  Status: Published (remained live throughout — no downtime)

  Version history now shows:
    v1.4 (now) — System prompt updated: remote work policy + KB addition
    v1.3 — Previous version
    v1.2 — KB sources updated
    v1.1 — Initial adjustments post-launch
    v1.0 — Original published version

  New queries immediately use v1.4 config
  In-flight conversations (user actively chatting) see v1.4 on their next message

STEP 6: Rollback if Needed
  If v1.4 causes unexpected behavior (satisfaction drops, errors increase):
  Admin opens Version History → selects v1.3 → "Restore to v1.3"

  System shows confirmation:
    "Restoring HR Assistant to v1.3:
     • Remote work policy knowledge will be removed from responses
     • Conversation history is preserved
     • v1.4 is saved as an archived version"
  Admin confirms → agent reverts to v1.3 immediately
  Affected users notified (if any ongoing sessions): "Agent configuration updated"

STEP 7: Monitoring Post-Update
  Admin sets a monitoring alert for the next 24 hours:
    "Notify me if HR Assistant satisfaction drops below 70%"
  Dashboard shows 24h post-update metrics:
    - Satisfaction: 87% (up from 84% — new policy answers improving quality)
    - Error rate: 0%
    - Remote work queries: 12 in first 24h (confirming users are finding the new capability)
  Admin marks update as SUCCESSFUL
```

---

## Flow 5: Workspace Branding — Ongoing Updates (Post-Wizard)

**Trigger**: Tenant admin needs to update the workspace logo, display name, and UI color accent after an organizational rebrand.
**Persona**: Tenant Admin
**Entry**: Settings → Workspace → Branding

```
STEP 1: Access Branding Settings
  Admin navigates to Settings → Workspace → Branding tab
  Current branding:
    Workspace name: "Acme Corp Knowledge AI"
    Logo: acme_logo_v1.png (uploaded 2026-01-15)
    Accent color: [default platform green]
    Login page message: "Welcome to Acme Corp's AI knowledge system"
    Support email: aihelp@acme.com

  The company has rebranded to "Acme Technologies" in February 2026.
  New logo, new corporate color.

STEP 2: Update Display Name
  Admin clicks "Edit" next to Workspace name
  Changes: "Acme Corp Knowledge AI" → "Acme Technologies AI Workspace"
  Click "Save"
  Effect: Immediate — updated in sidebar header, login page, email templates
  Users see updated name on next page load

STEP 3: Upload New Logo
  Admin clicks "Replace Logo"
  File picker opens
  Admin uploads: acme_tech_logo_2026.svg
  System validation:
    - File type: SVG ✓ (preferred) or PNG/JPG accepted
    - File size: 48KB (< 2MB limit) ✓
    - Dimensions: SVG scales automatically ✓
    Recommended: SVG for crisp rendering at all sizes

  Preview shown:
    ┌─────────────────────────────────────┐
    │ [New logo preview]                   │
    │ Sidebar — how it appears to users    │
    └─────────────────────────────────────┘
    ┌─────────────────────────────────────┐
    │ Login page — how it appears          │
    └─────────────────────────────────────┘
    ┌─────────────────────────────────────┐
    │ Email notification — how it appears  │
    └─────────────────────────────────────┘

  Admin confirms → logo saved
  Users see new logo on next page load (no cache issues — logo served with cache-busting headers)

STEP 4: Update Accent Color (Enterprise Feature)
  Enterprise tenants can customize the accent color used in the UI.
  Admin clicks "Accent Color"
  Current: platform default (#4FFFB0 mint green)
  New brand color: #0066CC (Acme Technologies corporate blue)

  Color input: [hex #] [color picker]
  Admin enters: #0066CC

  Accessibility check:
    System tests contrast ratios:
      Text on accent: 4.2:1 ✓ (WCAG AA passes)
      Active state visibility: PASS
      Dark mode contrast: PASS
    Warnings: "This color is significantly different from the default. Test with your users."

  Preview shows accent applied to:
    - Active nav items
    - CTA buttons
    - Highlighted chat responses
    - Progress indicators

  Admin clicks "Apply Color"
  Effect: Takes 60 seconds to propagate to all active sessions (CSS variable update)

STEP 5: Update Login Page Customization
  Admin updates the login page message:
    Old: "Welcome to Acme Corp's AI knowledge system"
    New: "Welcome to Acme Technologies AI — your intelligent knowledge platform"

  Admin can also configure:
    Support contact: aihelp@acmetech.com (updated domain)
    Help article URL: https://acmetech.atlassian.net/servicedesk/ai-help
    Login background: upload custom image or keep default dark gradient

  Admin saves all changes.
  Next person to visit the login page sees updated branding immediately.

STEP 6: Update Email Notification Templates
  Automated emails (invites, password resets, issue notifications) use branding.
  Admin clicks "Email Templates" tab

  Templates that include branding:
    - User invitation email (shows logo + workspace name)
    - Password reset email
    - MFA setup email
    - Issue notification email
    - Sync failure alert

  Admin previews "User Invitation Email":
    Logo: now shows new Acme Technologies logo ✓
    "Acme Technologies AI Workspace" in subject and body ✓
    Support email: aihelp@acmetech.com ✓

  No additional action needed — email templates auto-reference the saved branding settings.
```

---

## Flow 6: Multilingual Query Expansion (Full Flow)

**Trigger**: Tenant admin enables the glossary pretranslation feature for a multilingual team. This flow covers the complete setup, query path, and quality review cycle.
**Persona**: Tenant Admin (setup), End User (query experience)
**Entry**: Settings → AI Configuration → Language Settings

```
PART A: TENANT ADMIN SETUP

STEP 1: Enable Multilingual Mode
  Admin navigates to Settings → AI Configuration → Language
  Current state:
    Primary language: English
    Glossary pretranslation: Disabled
    Query language detection: Disabled

  Admin enables:
    [✓] Detect query language automatically
    [✓] Glossary pretranslation — expand company terms in non-English queries
    Primary language: English (documents indexed in English)
    Supported query languages: [✓] French [✓] Spanish [✓] Mandarin [✓] German

STEP 2: Add Multilingual Glossary Entries
  Admin navigates to Settings → Glossary
  For each key company term, admin adds translations:

  Example entry:
    Term: "Project Falcon"
    Full form: "Internal digital transformation program"
    Definition: "Launched Q1 2026, covers cloud migration and AI adoption"
    Context tags: [strategy, IT, executive]

    Translations (optional):
      French: "Projet Faucon" — full form: "Programme de transformation digitale"
      Spanish: "Proyecto Halcón"
      Mandarin: "猎鹰项目"
      German: "Projekt Falke"

  When a user queries in French and mentions "Projet Faucon", the system maps it
  back to "Project Falcon" before searching the knowledge base.

  Admin adds 12 key company terms with translations.
  Each term: 15-30 minutes to add translations via the form or CSV import.

  CSV import format for multilingual terms:
    term, full_form, definition, context_tags, fr_term, es_term, zh_term, de_term

STEP 3: Configure Pretranslation Behavior
  Admin configures how pretranslation works:

    Behavior when term detected in query:
      [◉] Silently expand (transparent to user) — recommended
      [ ] Show expansion notice: "I recognized 'Projet Faucon' as 'Project Falcon'"

    Confidence threshold for term matching:
      Exact match: always expand
      Fuzzy match (≥80% confidence): expand
      Fuzzy match (<80%): do not expand (avoid false positives)

    Fallback when query language has no glossary entry for a term:
      [◉] Query using the original term as-is
      [ ] Ask user to clarify

  Admin saves configuration.

---

PART B: END USER QUERY EXPERIENCE

STEP 4: User Submits Query in French
  User: Marie Dupont (analyst, French speaker, working from Paris office)
  Entry: Chat interface

  Marie types in French:
    "Quels sont les principaux objectifs du Projet Faucon pour le Q2 2026?"
    (Translation: "What are the main objectives of Project Falcon for Q2 2026?")

STEP 5: Pretranslation Pipeline Executes (Transparent to Marie)
  Behind the scenes:
    1. Language detection: French (confidence: 0.98)
    2. Glossary scan: "Projet Faucon" detected → maps to "Project Falcon"
    3. Query expansion: original query preserved, "Projet Faucon" augmented
       with "Project Falcon" for RAG search
    4. Vector search runs with expanded query terms
    5. Documents retrieved: "Project Falcon Q2 Objectives.docx", "2026 Roadmap.pptx"
    6. Response generated in English (primary language of docs)

  What Marie sees in the chat:
    Meta row: "AUTO · ANALYST · 0.87 confidence"
    Response: In English (document language):
      "Project Falcon's Q2 2026 objectives include: 1) Complete cloud migration
       of core HR systems, 2) Deploy AI tools to 500 employees, 3) Achieve
       SOC 2 Type II certification..."
    Footer: "📄 2 sources · 1.8s"

  Note: Response is in English because the source documents are in English.
  Future enhancement (Phase 6): response translation to French.

STEP 6: Glossary Expansion Metadata (Admin View)
  Tenant admin can see pretranslation activity in Glossary Analytics:

  Glossary Usage Log (last 7 days):
    Term "Project Falcon"   | 18 queries | 4 languages | Avg confidence: 0.94
      Triggered by: "Projet Faucon" (12), "Proyecto Halcón" (4), "猎鹰项目" (2)
    Term "QBR"              | 7 queries  | 2 languages | Avg confidence: 0.88
      Triggered by: "RTA" (6 — French: Revue Trimestrielle des Affaires), "RTA" (1)
    Term "EMEA"             | 23 queries | 3 languages | — (abbreviation, no translation needed)

  Admin can see: which terms are being used by multilingual users.
  This drives: which additional translations to add (or which English terms are well-known enough to not need translation).

STEP 7: Quality Review — Pretranslation Accuracy
  Admin checks the quality of pretranslation in Glossary → Quality Review:

  Potentially mismatched expansions (low confidence triggers):
    Query: "revue de performance" (FR) → expanded to "Performance Review"
    Confidence: 0.76 (below 0.8 ideal threshold)
    Source text was about Q3 review, but user may have meant HR performance review
    Admin notes: ambiguous — may need context tags to differentiate

  Missed expansions (term appears in query but no glossary entry):
    "Protocole de validation" appeared in 4 French queries with 0 KB hits
    Admin checks: "validation protocol" is a company term not yet in glossary
    Action: Admin adds "Validation Protocol" to glossary with French translation

  Admin iterates: adding missing terms improves hit rate for multilingual users.
```

---

## Flow 7: KB Access Request Workflow (User Requesting Access)

**Trigger**: An end user (viewer role) tries to interact with the Legal Finance Agent and sees a "Request Access" prompt because they lack access to the Legal Contracts KB used by that agent.
**Persona**: End User (initiator), Tenant Admin (approver)
**Entry**: Chat interface → agent selection → access gate

```
STEP 1: User Encounters Access Gate
  User David Kim (viewer role) is browsing available agents.
  He sees "Legal Finance Assistant" in the agent list (visible to all, queryable by authorized only).

  David tries to start a chat with Legal Finance Assistant:
    Types: "What are the standard payment terms we use with vendors?"
    Submits query

  Response from agent:
    "I'd be happy to help with that, but I need access to the Legal Contracts
     knowledge base to answer this accurately. [Request Access]"

  OR: Agent list shows a padlock icon on agents David cannot fully use.
  He sees a tooltip: "Requires Legal Contracts KB access · [Request Access]"

STEP 2: User Submits Access Request
  David clicks "Request Access"
  A request form opens:
    Resource requested: Legal Contracts KB
    Request type: [◉] Access to query this knowledge base
    Reason for access (required):
      David types: "Working on vendor payment analysis project with finance team.
      Need to understand our standard contract terms for benchmarking."
    Urgency: [Standard (< 48h response)] or [Urgent (< 4h)]
    Manager who approves: [optional — auto-populated if org chart configured]
  David clicks "Submit Request"

STEP 3: Tenant Admin Receives Notification
  Tenant admin (Sarah Johnson) receives:
    In-app notification badge: "1 new access request"
    Email: "Access Request: David Kim → Legal Contracts KB"

  Admin opens the request:
    Requester: David Kim (viewer, Engineering)
    Resource: Legal Contracts KB
    Reason: "Working on vendor payment analysis project..."
    Submitted: 5 minutes ago
    Context: David's last 7 days — 23 queries, 91% satisfaction (active user)

STEP 4: Admin Approves or Denies
  APPROVE path:
    Admin reviews reason — legitimate project use case
    Admin clicks "Approve"
    Options:
      [◉] Grant full access (permanent)
      [ ] Grant time-limited access: expires [date picker]
      [ ] Grant restricted access (read-only, specific document subset)

    Admin adds optional note to David:
      "Access granted for vendor payment project. Please note these documents
       are confidential — do not share outside the company."

    Admin clicks "Approve with Access"
    David immediately has access to Legal Contracts KB
    David notified: "Access approved! You can now query the Legal Contracts KB."
    David's pending query is automatically re-run against the KB:
      "Standard payment terms in contracts: Net 30 days for services, Net 45 for goods..."

  DENY path:
    Admin reviews reason — not a sufficient business case
    Admin clicks "Deny"
    Required: explanation to David

    Admin types: "This KB contains sensitive legal documents. Please work with
    the Legal team directly for contract information. The Finance team has a
    separate resource I can direct you to."
    Admin adds alternative resource: Finance Policies KB (grants automatic redirect)

    David notified: "Your access request was not approved. [Admin's message]"

STEP 5: Access Request Audit
  All access requests logged:
    Date     | User       | Resource         | Decision | Decided By   | Expires
    ─────────────────────────────────────────────────────────────────────────────
    Mar 10   | david.kim  | Legal Contracts  | Approved | sarah.j      | Never
    Mar 8    | anna.s     | Finance Reports  | Denied   | sarah.j      | —
    Feb 28   | tom.w      | HR Policies      | Approved | sarah.j      | Mar 31
    Feb 25   | tom.w      | Finance Reports  | Approved | sarah.j      | Never

  Tom.w's time-limited access to HR Policies expires March 31 automatically.
  No manual revocation needed — system removes access and notifies Tom.
```

---

## Edge Cases

### E1: MFA — Admin Locks Themselves Out

```
Tenant admin enables MFA, sets grace period to "Immediate"
Admin's own MFA is not set up
Admin is immediately locked out on next login attempt
Admin contacts platform admin support
Platform admin has emergency MFA reset capability for tenant_admin accounts only
Platform admin verifies identity via out-of-band means (email + account confirmation)
Platform admin resets admin's MFA
Admin logs in, completes MFA enrollment immediately
```

### E2: Agent Version Update Causes Brief Quality Drop

```
HR Assistant v1.4 system prompt update causes agents to give generic answers for 2 hours
(Reason: new remote work KB added but not yet fully indexed — empty retrieval)
Admin notices satisfaction dropped to 71% in first 2 hours
Admin uses rollback to v1.3 while waiting for KB indexing to complete
After KB indexing done (4 hours): re-applies v1.4 update
Satisfaction recovers to 87%
Lesson: Major KB additions should be verified as indexed before applying system prompt updates
```

### E3: Cloned Agent Used as Basis for Template

```
Tenant admin creates a very effective "Legal Finance Assistant"
Wants to contribute it back to the platform template library
This is not a self-service feature: tenant admin contacts platform admin
Platform admin reviews the agent, sanitizes tenant-specific data
Platform admin creates a new template based on the design
Template published as "Legal Finance Assistant Template v1" in the catalog
Original tenant does not receive attribution by default (privacy)
```

### E4: Document-Level Permission Mismatch — SharePoint Changed

```
SharePoint admin removes legal@acme.com from Legal drive
KB access list still shows legal@acme.com as authorized
Next sync: system re-checks permissions
Document-level permission verification flags: "legal@acme.com listed in KB access
  but no longer has SharePoint access to source documents"
Alert sent to tenant admin: "Permission mismatch detected"
Admin updates KB access list to match: removes legal@acme.com
Audit log records the permission mismatch and resolution
```
