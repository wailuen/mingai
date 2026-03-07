# 11 — Platform Admin: Operations User Flows

**Date**: 2026-03-05
**Personas**: Platform Admin, Platform Operator, Tenant Admin (as receiver of downstream actions)
**Domains**: Tenant Lifecycle, Issue Queue, Analytics, LLM Config, Cost Monitoring, Agent Templates, Tool Catalog

---

## Flow 1: Onboard a New Tenant

**Trigger**: Sales confirms new customer. Platform admin needs to provision a live workspace.
**Persona**: Platform Admin or Platform Operator
**Entry**: Platform Admin Console → Tenants → New Tenant

```
STEP 1: Open New Tenant Wizard
  Admin navigates to Tenants → clicks "New Tenant"
  System opens a 4-step wizard (progress bar visible at top)

STEP 2: Basic Info (Step 1/4)
  Admin fills:
    - Tenant display name (e.g., "Acme Corp")
    - Subdomain slug (e.g., "acme") → system checks availability, shows green tick
    - Primary contact email (becomes first tenant admin account)
    - Plan tier selection: [Starter | Professional | Enterprise] (radio cards with token limits shown)
    - Contract start date (auto-defaults to today)
  Validation: slug must be 3-32 chars, alphanumeric + hyphens, unique
  Click: "Next →"

STEP 3: LLM Profile Assignment (Step 2/4)
  System shows available LLM profiles with descriptions:
    - Cost-Optimized: "Best for high-volume, query-response workloads. GPT-5 Mini primary."
    - Balanced: "Recommended for most deployments. GPT-5.2-chat primary." [DEFAULT]
    - Premium: "Best for complex reasoning and document analysis. GPT-5.2 primary."
    - Vision-Enabled: "Enables image analysis and document OCR."
  Admin selects one profile
  System shows: estimated cost/1000 queries for selected profile + plan tier
  Click: "Next →"

STEP 4: Resource Quotas (Step 3/4)
  System pre-fills based on plan tier:
    - Monthly token quota: [plan default] (editable within plan range)
    - Storage quota: [plan default]
    - Agent instance limit: [plan default]
    - MCP tool connections: [plan default]
  Admin can override within plan limits (e.g., give Professional plan extra tokens for trial period)
  Click: "Next →"

STEP 5: Review & Provision (Step 4/4)
  System shows confirmation summary:
    - Tenant name, subdomain, plan, LLM profile
    - Resources that will be created:
      ✓ Cosmos DB container (partition key: /tenantId)
      ✓ Azure AI Search index (tenant-scoped)
      ✓ Azure Blob container with SAS token
      ✓ Redis namespace (mingai:{tenant_id}:*)
      ✓ PostgreSQL tenant record
      ✓ Initial admin account (email invite pending)
  Click: "Provision Tenant"

STEP 6: Provisioning Runs (< 10 minutes)
  System shows live progress:
    [✓] Database container created
    [✓] Search index created
    [✓] Storage container created
    [⟳] Sending admin invite email...
    [✓] Invite sent
  Admin can leave — provisioning continues in background
  Notification on completion: "Acme Corp provisioned. Admin invite sent to admin@acme.com"

STEP 7: Post-Provisioning
  Tenant appears in Tenants table with status: "Active"
  Health score: "Awaiting first login" (null state)
  Admin can immediately: edit quota, change LLM profile, send welcome message
```

**Decision points**:

- Subdomain taken → system suggests alternatives (acme-corp, acme-inc, acme01)
- Provisioning fails → rollback, admin sees which step failed, retry button
- Invite bounces → admin can resend or change email from tenant detail page

---

## Flow 2: Suspend and Offboard a Tenant

**Trigger**: Contract termination, non-payment after grace period, or policy violation.
**Persona**: Platform Admin
**Entry**: Tenants → [Tenant Name] → Actions

```
STEP 1: Initiate Suspension
  Admin navigates to tenant detail page
  Clicks "Suspend Tenant" (warning color button, not prominent)

  System shows confirmation dialog:
    "Suspending Acme Corp will:
    • Block all end-user logins immediately
    • Preserve all data for 30 days
    • Allow tenant admin read-only access for data export
    This action is reversible until deletion."
  Admin confirms suspension reason (dropdown):
    [Non-payment | Contract ended | Policy violation | Requested by tenant | Other]
  Click: "Confirm Suspension"

STEP 2: Suspension Takes Effect
  System immediately:
    - Sets tenant status → Suspended
    - Blocks end-user auth (JWT issuance disabled for this tenant)
    - Sends notification to tenant admin:
      "Your workspace has been suspended. Data is preserved for 30 days.
       Contact support to reactivate or export your data."
  Tenant admin retains read-only access to export data
  Health score shows: "Suspended" badge

STEP 3: Grace Period (30 days)
  System tracks suspension date
  On day 25: System sends admin alert "Acme Corp deletion scheduled in 5 days"
  Admin sees countdown in tenant detail: "Data deletion in 5 days"

  Option A: Reactivate
    Admin clicks "Reactivate" → tenant status → Active
    End-user access restored within 60 seconds

  Option B: Extend grace period
    Admin can extend by 30 days with a reason

  Option C: Immediate deletion
    Admin clicks "Delete Tenant Data" (requires confirmation + typed tenant slug)
    System schedules async deletion of all tenant data

STEP 4: Scheduled Deletion
  System runs deletion pipeline:
    [✓] Cosmos DB container purged
    [✓] Azure AI Search index deleted
    [✓] Blob container deleted
    [✓] Redis namespace flushed
    [✓] PostgreSQL record soft-deleted (retained 90 days for billing records)
  Audit log: deletion event recorded with timestamp + admin who authorized
  Admin receives completion notification
```

---

## Flow 3: Review and Triage the Issue Queue

**Trigger**: Daily operations review. Admin checks incoming issue reports.
**Persona**: Platform Admin or Platform Operator
**Entry**: Dashboard → Issue Queue (badge count shows unreviewed items)

```
STEP 1: View Issue Queue
  Admin opens Issue Queue from dashboard or nav
  Queue shows items sorted by:
    - P0/P1 first (auto-surfaced, highlighted in red/orange)
    - Then by received time (newest first)

  Each queue item shows:
    - Severity badge (P0-P4, AI-assigned)
    - Short description (first 80 chars of user title)
    - Tenant name
    - Time received
    - Status: [New | In Review | Escalated | Resolved | Closed]
    - Duplicate indicator: "Similar to #47" (if AI detected duplicate)

STEP 2: Open Issue for Review
  Admin clicks an issue item
  Detail panel opens (right side or full page):

    SECTION A — Reporter Context
      Reporter: "user@acme.com" (role: Analyst)
      Reported: 2026-03-05 14:32 UTC
      Tenant: Acme Corp (plan: Professional, health score: 72)

    SECTION B — Issue Content
      Title: "AI response missing when document uploaded"
      Category: [Bug | Feature Request | Question | Performance]
      Description: [user's text]
      Screenshot: [thumbnail, click to expand]

    SECTION C — AI Triage Assessment
      Severity: P2 (Medium) — AI rationale: "Affects document upload flow,
        no data loss, workaround available via re-upload"
      Classification: "Platform Bug" vs "Tenant Config" indicator
        [Platform Bug — confirmed across 2 other tenants]
      Similar issues: "#31 (Resolved), #47 (Open)" with similarity score

    SECTION D — Contextual Data
      Last query: "Summarize Q4 financial report"
      Model used: Balanced profile (GPT-5.2-chat)
      Confidence score: 0.21 (low)
      Browser: Chrome 121, Windows 11
      Console errors: [list]

STEP 3: Admin Takes Action

  Option A: Create GitHub Issue
    Admin clicks "Create GitHub Issue"
    System pre-populates:
      - Title: "[P2] AI response missing on document upload"
      - Labels: ["bug", "platform", "p2"]
      - Body: formatted Markdown with all context data
      - Assignee: (admin selects from GitHub team members)
    Admin reviews, edits if needed, clicks "Create"
    GitHub issue created → URL stored → queue item status → "Escalated"
    User notified: "Your report #52 has been escalated to engineering (GitHub #1047)"

  Option B: Route to Tenant Support
    Admin clicks "Route to Tenant"
    Writes a message: "This appears to be a configuration issue in your Document Library settings.
      Please verify your SharePoint connection is active."
    User notified with admin's message + next steps
    Queue item status → "Routed to Tenant"

  Option C: Close as Duplicate
    Admin clicks "Close as Duplicate"
    Links to existing open/resolved issue
    System: "Closed #52 as duplicate of #31. User notified."
    User notified: "Your report is tracked under #31. Watch that issue for updates."

  Option D: Request More Info
    Admin writes a question: "Can you reproduce this on a different browser?"
    Queue item status → "Awaiting Reporter"
    User sees a follow-up message in their notification

STEP 4: Batch Processing
  For queues with many items, admin can:
    - Filter by severity, tenant, category, date range
    - Select multiple items → Bulk action: "Close as Known Issue" / "Route to Tenant"
    - Sort by: severity / received time / tenant plan tier / health score
```

---

## Flow 4: Monitor Analytics and Generate Roadmap Signals

**Trigger**: Weekly operations review or monthly business review.
**Persona**: Platform Admin
**Entry**: Dashboard → Analytics

```
STEP 1: View Platform Health Overview
  Dashboard top section shows KPI cards:
    - Active tenants: 24 / 30 total
    - At-risk tenants: 3 (health score declining 3+ weeks)
    - Platform satisfaction (7d): 78% thumbs up
    - P0/P1 open issues: 1
    - Quota warnings: 2 tenants > 80% monthly usage

STEP 2: Tenant Health Deep-Dive
  Admin clicks "At-Risk Tenants" → sees list of 3 tenants
  For each at-risk tenant:
    Tenant: BetaCo (health score: 41, dropping -12 pts/week)
    Signals:
      - Login frequency: -60% vs prior 4 weeks
      - Feature usage: only 2 of 8 features active (breadth declining)
      - Satisfaction rate: 54% (platform avg: 78%)
      - Error rate: 8% (platform avg: 2%)
      - Open issues: 2 (1 unacknowledged for 5 days)
    Admin action options:
      [Proactive Outreach] [Upgrade LLM Profile] [Adjust Quota] [Flag for CSM Review]

  Admin clicks "Proactive Outreach"
  System opens message template:
    "Hi [Tenant Admin Name], we noticed some unusual activity in your workspace
     and want to make sure everything is working well for your team..."
  Admin edits and sends → message delivered to tenant admin's notification center

STEP 3: Feature Adoption Analysis
  Admin views adoption table:
    Feature             | Active Tenants | Avg Sessions/Week | Satisfaction
    Document Upload     | 22/24          | 148               | 82%
    SharePoint Sync     | 11/24          | 44                | 71%
    Glossary            | 6/24           | 12                | 88%
    Agent Templates     | 18/24          | 203               | 79%
    MCP Tools           | 4/24           | 8                 | N/A (too few)

  Low-adoption features flagged with tooltip: "Consider in-app guidance or outreach"
  High-satisfaction features flagged: "Candidate for promotion in marketing materials"

STEP 4: Roadmap Signal Board
  System aggregates from issue reports:
    Top Feature Requests (last 90 days):
      1. Slack integration (14 requests, 8 tenants, mostly Enterprise plan)
      2. Bulk document re-index (9 requests, 9 tenants, evenly distributed)
      3. Tenant-scoped glossary auto-sync (7 requests, 5 tenants, Professional+)

    Top Pain Points:
      1. Document upload timeout on large files (23 reports, 11 tenants, P2)
      2. SharePoint reconnect after token expiry (18 reports, 8 tenants, P2)

  Admin can:
    - Export roadmap signals as CSV → paste into planning doc
    - Tag items: "In Roadmap Q2", "Under Review", "Won't Fix"
    - Filter by: plan tier, tenure, feature area
```

---

## Flow 5: Create and Publish an LLM Profile

**Trigger**: New model becomes available, or performance data shows a profile needs updating.
**Persona**: Platform Admin
**Entry**: LLM Library → New Profile

```
STEP 1: Create New Profile
  Admin clicks "New Profile"
  Form opens:
    - Profile name: "Balanced v2"
    - Description: "Updated Balanced profile with GPT-5.2-turbo as primary"
    - Status: Draft (cannot be selected by tenants until Published)

STEP 2: Configure Each Pipeline Slot
  For each of the 6 deployment slots, admin fills:

  Slot 1: Primary (Synthesis)
    - Deployment: [dropdown of available Azure OpenAI deployments]
      → Select: "gpt-5-2-chat-eastus"
    - Reasoning effort: [Low | Medium | High] → Medium
    - Max tokens: 4096
    - Temperature: 0.7
    - Notes: "Use for most tenants. Good balance of quality vs cost."

  Slot 2: Intent Detection
    - Deployment: → "gpt-5-mini-eastus2"
    - Reasoning effort: Low
    - Max tokens: 512
    - Notes: "Keep this slot cost-optimized — runs on every query."

  [Slots 3-6 follow same pattern]

STEP 3: Test the Profile
  Admin clicks "Test Profile"
  System opens test harness:
    - Input: [test query text box]
    - System: "Test against profile: Balanced v2"
  Admin types: "What are the Q4 financial results for our EU operations?"
  Runs test → system shows:
    - Response from primary slot (GPT-5.2-turbo)
    - Latency: 1.4s
    - Tokens used: 1,847 input + 312 output
    - Estimated cost: $0.0041
    - Confidence score: 0.89
  Admin can run multiple test queries to verify behavior

STEP 4: Add Best Practices Notes
  Admin fills markdown notes field:
    "## Balanced v2 Best Practices
    - Best for: general document Q&A, policy lookup, knowledge base search
    - Not recommended for: image-heavy documents (use Vision-Enabled instead)
    - Watch for: contexts >3000 tokens will hit cost ceiling faster than Cost-Optimized
    - Updated March 2026 to use GPT-5.2-turbo (15% faster than prior model)"

STEP 5: Publish Profile
  Admin clicks "Publish"
  System prompts: "Publishing makes Balanced v2 available for tenant selection.
    Current tenants on Balanced v1 will NOT be automatically migrated."
  Admin clicks "Confirm Publish"
  Profile status → Published
  Profile appears in tenant LLM profile selector

STEP 6: Deprecate Old Profile (Optional)
  Admin navigates to "Balanced v1" → clicks "Deprecate"
  System: "6 tenants are currently on Balanced v1.
    They can continue to use it but cannot be newly assigned to this profile."
  Admin confirms → profile status → Deprecated
  Tenant admins on deprecated profiles see: "This profile is deprecated. Upgrade recommended."
```

---

## Flow 6: Monitor Platform Costs and Gross Margin

**Trigger**: Admin performs monthly cost review or receives cost alert.
**Persona**: Platform Admin
**Entry**: Cost Monitoring → Overview

```
STEP 1: View Cost Dashboard
  Admin sees cost dashboard with period selector (default: current calendar month)

  Top KPIs:
    - Total platform LLM cost (MTD): $4,823
    - Total infrastructure cost (MTD): $1,247
    - Total platform cost: $6,070
    - Total plan revenue (MTD): $18,500
    - Gross margin: 67.2% (target: 65%+) → GREEN indicator
    - Projected month-end margin: 64.8% → YELLOW (approaching threshold)

STEP 2: Per-Tenant Cost Breakdown
  Table shows each tenant:

  Tenant          | Plan Revenue | LLM Cost | Infra Cost | Total Cost | Gross Margin
  ─────────────────────────────────────────────────────────────────────────────────
  Acme Corp       | $2,000/mo    | $847      | $124       | $971       | 51.4% ⚠️
  BetaCo          | $500/mo      | $112      | $41        | $153       | 69.4%
  GammaTech       | $1,000/mo    | $203      | $82        | $285       | 71.5%
  ...

  Color coding:
    - Red: margin < 40% (pricing action required)
    - Yellow: margin 40-55% (monitor, consider upgrade)
    - Green: margin > 55%

STEP 3: Investigate a Low-Margin Tenant
  Admin clicks "Acme Corp" row (51.4% margin, yellow warning)
  Detail view shows:
    - LLM cost by slot: Primary 68%, Intent 12%, Embedding 20%
    - Daily cost trend (chart): spike on 2026-02-28 (+$340 in one day)
    - Spike tooltip: "148% above average — likely large document batch upload"
    - Quota status: 73% of monthly token quota used on day 18
    - Plan: Professional ($2,000/mo) — next tier: Enterprise ($4,000/mo)

  Admin action options:
    [Recommend Plan Upgrade] [Adjust Token Quota] [Switch LLM Profile] [Send Cost Alert]

  Admin clicks "Switch LLM Profile"
  → Pops up: "Switch Acme Corp from Balanced to Cost-Optimized?"
  → "This will reduce their LLM cost by ~35% at potential quality reduction"
  Admin decides to instead contact tenant about plan upgrade.

STEP 4: Infrastructure Cost Attribution
  Admin clicks "Infrastructure" tab
  System shows:
    - Azure Cost Management API data (pulled daily at 06:00 UTC)
    - Costs split by resource type: Cosmos DB, AI Search, Blob Storage, Redis
    - Attribution estimate per tenant (based on provisioned resource ratios)
    - Note: "Infrastructure costs are estimated from shared resource pools.
       Dedicated resource costs (Enterprise tenants) are direct-attributed."

  Admin can export cost data as CSV for billing reconciliation.

STEP 5: Set Cost Alerts
  Admin navigates to Cost → Alert Settings
  Can set:
    - Platform-level monthly budget: alert at $X
    - Per-tenant margin threshold: alert when any tenant margin < 40%
    - Per-tenant daily spend spike: alert when day's cost > 200% of 7-day average
  Admin saves → alerts delivered via dashboard notification and email
```

---

## Flow 7: Manage Agent Template Library

**Trigger**: Admin creates a new template, updates an existing one, or reviews underperforming templates.
**Persona**: Platform Admin
**Entry**: Agent Templates → [New Template | Edit | Analytics]

```
STEP 1: View Template Library
  Admin sees library grid:
    Template Name           | Version | Tenants Using | Satisfaction | Status
    HR Policy Assistant     | v2      | 11            | 82%          | Published
    Financial Analyst       | v3      | 8             | 74% ⚠️       | Published
    Customer Support Agent  | v1      | 18            | 89%          | Published
    Technical Docs Helper   | v1      | 4             | 71% ⚠️       | Draft

STEP 2: Create a New Template
  Admin clicks "New Template"
  Form: 4 sections

  SECTION 1: Metadata
    - Name: "Legal Document Reviewer"
    - Category: [HR | Finance | Legal | Customer Support | Technical | Other] → Legal
    - Description: "Helps users navigate legal documents, contracts, and compliance materials"
    - Tags: "legal, contracts, compliance"
    - Visibility: [All plans | Professional+ | Enterprise only] → Professional+

  SECTION 2: Agent Configuration
    - System prompt: [Large textarea]
      "You are a legal document assistant helping users understand contracts and legal documents.
       Always remind users that you provide information, not legal advice.
       When analyzing: {document_type} documents, apply {jurisdiction} standards.
       Focus on: {focus_areas}."

    Variable definitions:
      {{document_type}}: "Type of legal documents" (text, required, example: "employment contracts")
      {{jurisdiction}}: "Applicable law jurisdiction" (text, required, example: "US Federal")
      {{focus_areas}}: "Specific areas to emphasize" (text, optional, example: "liability clauses, IP ownership")

    Note: system prompt content is admin-controlled, tenants fill variables only.

  SECTION 3: Guardrails
    - Blocked topics: "Specific legal advice, predictions of legal outcomes"
    - Required disclaimers: "This is informational, not legal advice"
    - Confidence threshold: 0.60 (below this, suggest human review)
    - Max response length: 800 tokens

  SECTION 4: Test Scenarios
    Admin adds 3 test cases:
      Input: "Is this non-compete clause enforceable?"
      Expected behavior: "Explains factors affecting enforceability, does not predict outcome"

  Admin clicks "Run Tests" → AI generates responses, admin reviews quality
  If tests pass: click "Save as Draft"

STEP 3: Publish Template
  Admin reviews draft template
  Clicks "Publish"
  System: "Published templates cannot have system prompt modified after tenants deploy.
    Create a new version to change system prompt."
  Admin confirms → status → Published
  Template available in tenant agent library

STEP 4: Review Underperforming Template
  Admin clicks "Financial Analyst v3" (74% satisfaction, flagged yellow)
  Analytics panel shows:
    - Satisfaction: 74% (platform avg: 82%)
    - Guardrail trigger rate: 12% (platform avg: 4%) → HIGH
    - Top failure patterns:
        1. "Insufficient context" (43% of low-rated responses)
        2. "Guardrail triggered on earnings data" (31%)
        3. "Response too short" (18%)
    - Compared to v2: satisfaction dropped 8% after v3 update

  Admin reviews individual low-rated sessions (anonymized):
    Session: User asked about EBITDA margins → guardrail triggered "financial advice"
    Assessment: Guardrail too aggressive — should allow factual financial data retrieval

  Admin creates v4:
    - Adjusts guardrail: narrow "financial advice" guardrail to specific predictions
    - Adds to system prompt: "You MAY provide factual financial data and ratios..."
    - Runs tests → satisfaction improves in test harness
    - Publishes v4

  System: "11 tenant instances on v3. They will be notified of v4 availability.
    Tenant admins choose when to upgrade their instances."

STEP 5: Push Template Upgrade Notification
  Admin can optionally push upgrade notice:
    Clicks "Notify Tenants of v4"
    System sends notification to tenant admins using Financial Analyst:
      "Financial Analyst v4 is now available with improved accuracy.
       Review changes and upgrade your instance at your convenience."
```

---

## Flow 8: Register and Govern a Tool in the Tool Catalog

**Trigger**: New MCP-compatible tool becomes available for integration.
**Persona**: Platform Admin
**Entry**: Tool Catalog → Register Tool

```
STEP 1: Initiate Tool Registration
  Admin clicks "Register Tool"

  Registration form:

  SECTION 1: Identity
    - Tool name: "Jira Issue Reader"
    - Provider: "Atlassian"
    - Version: "1.0.0"
    - Description: "Read and search Jira issues, epics, and sprints"
    - MCP server endpoint: https://mcp.atlassian.com/jira
    - Authentication: OAuth 2.0
    - Documentation URL: [link to MCP spec]

  SECTION 2: Capability Declaration
    Admin selects all capabilities offered:
      [x] Read Jira issues and comments
      [x] Search issues by JQL
      [ ] Create Jira issues (not enabling this version)
      [ ] Update issue status
      [ ] Delete issues

  SECTION 3: Safety Classification (permanent — cannot be downgraded)
    Based on enabled capabilities:
    System auto-suggests: "Read-Only" (only read/search capabilities enabled)
    Admin confirms: Read-Only

    If Write capabilities were enabled: System would require "Write" classification
    Admin note: "Read-only access to Jira issues for context in agent responses"

STEP 2: Automated Health Check
  Admin clicks "Run Health Check"
  System tests MCP server:
    [✓] Endpoint reachable (latency: 142ms)
    [✓] Auth handshake successful
    [✓] Tool schema valid (3 tools declared)
    [✓] Sample capability invoked: "Search issues" → response in 340ms
    [✗] Rate limit headers present: WARN (not critical)

  Health status: "Healthy with 1 warning"
  Admin acknowledges warning, notes in description

STEP 3: Configure Availability
  Admin sets:
    - Available to plans: [Professional | Enterprise] (Starter excluded — MCP tools are advanced)
    - Require explicit tenant opt-in: YES (agents must individually enable this tool)
    - Tenant configuration required: YES
      Required fields: "Jira workspace URL", "OAuth credentials"
      (tenant admins provide their own Jira credentials)

STEP 4: Publish to Catalog
  Admin clicks "Publish"
  Tool appears in tenant tool catalog under "Integrations"

  Tenant admin view:
    Tool: "Jira Issue Reader" | Classification: Read-Only | Status: Available
    [Enable for Agent] button → tenant provides their Jira credentials → tool enabled

STEP 5: Ongoing Health Monitoring
  System pings registered tools every 5 minutes
  If health degrades:
    - 1 consecutive failure: Admin alert (warning)
    - 3 consecutive failures: Tool enters "Degraded" status
    - Agents using tool receive: fallback instruction "Jira unavailable, proceed without Jira context"
    - 10 consecutive failures: Tool enters "Unavailable" status — alert to affected tenant admins

  Admin receives daily health summary for all registered tools
  Admin can manually trigger health check at any time
  Admin can retire a tool:
    "Retiring removes it from new tenant selections.
     Existing agents with tool enabled can continue but are warned."
```

---

## Flow 9: Respond to a Quota Warning Alert

**Trigger**: System alert: "Acme Corp at 85% of monthly token quota with 8 days remaining."
**Persona**: Platform Admin or Platform Operator
**Entry**: Dashboard notification → Quota Warnings

```
STEP 1: Receive Alert
  Admin receives dashboard notification badge
  Clicks notification: "2 tenants approaching token quota"

  List shows:
    Acme Corp: 85% used, 8 days remaining. Projected overage: 14,000 tokens.
    Initech: 91% used, 8 days remaining. Projected overage: 42,000 tokens.

STEP 2: Investigate Each Tenant
  Admin clicks Acme Corp:
    Usage trend chart: consistent growth month-over-month (+18%/month)
    Current plan: Professional (500,000 tokens/month)
    Overage cost: $0.021/1000 tokens × 14,000 = ~$0.29 (negligible)

    Context: Acme Corp's usage has been growing — they are approaching a plan upgrade naturally.

  Admin action: "Proactive outreach — suggest Professional+ or plan upgrade conversation"

  Admin clicks Initech:
    Usage trend chart: spike on 2026-03-01 (5x normal daily usage)
    Spike day: 42,000 tokens in one day (vs 4,000/day average)
    Analysis: "Likely bulk document upload or batch query session"
    Contact: initech-admin@initech.com

    Admin action: "Temporary quota override + investigation"

STEP 3: Apply Quota Override (Initech)
  Admin clicks "Temporary Quota Override"
  Form:
    - Increase by: +50,000 tokens (one-time this month)
    - Reason: "Investigating usage spike; preventing disruption"
    - Expiry: end of current billing month (automatic)
  Admin saves override.
  Initech's effective quota: 550,000 (original) + 50,000 override = 600,000 tokens
  Initech admin notified: "Your team has been granted 50,000 additional tokens this month.
    Our team will follow up to discuss your usage."

STEP 4: Follow Up with Tenant Admins
  Admin sends outreach message to each tenant admin via platform notification
  For Acme Corp: "Your workspace is growing — let's chat about your plan options."
  For Initech: "We noticed unusual usage on March 1st. Can we connect to review?"
  Messages logged in tenant communication history
```

---

## Edge Cases

### E1: Provisioning Fails Mid-Way

```
System fails during Cosmos DB creation (Azure service error)
→ System detects failure, triggers rollback of partially created resources
→ Admin sees: "Provisioning failed at step 3/6 — Azure Cosmos DB creation error"
→ Retry button available — system restarts from failed step (not from scratch)
→ If retry fails again: "Contact Azure support. Error code: [Azure error code]"
→ Admin can manually clean up any partial resources from audit log
```

### E2: LLM Profile Test Fails

```
Admin tests profile, response quality is clearly wrong (low confidence, nonsense output)
→ Admin inspects: discovers wrong deployment name was entered in slot config
→ Admin fixes deployment, re-runs test
→ System does not allow publishing until at least 3 test queries pass
```

### E3: Tool Health Permanently Degraded

```
A registered MCP tool has been "Unavailable" for 48 hours
→ Admin receives escalation alert
→ Admin contacts tool provider → learns tool has been discontinued
→ Admin retires tool: "Mark as Discontinued"
→ Tenant admins notified: "Jira Issue Reader has been discontinued. Agents using this tool will operate without Jira context."
→ Tool removed from new selections immediately
→ Existing agent configurations flagged: "Needs attention — connected tool discontinued"
```

### E4: Tenant Requests Immediate Data Deletion (GDPR)

```
Tenant admin submits GDPR data deletion request via platform
→ Platform admin receives high-priority alert: "GDPR Deletion Request — BetaCo"
→ Admin verifies tenant identity (must match account owner on record)
→ Admin initiates immediate deletion (overrides grace period)
→ System generates GDPR deletion confirmation report (timestamp, scope, data categories)
→ Admin sends report to tenant admin
→ All steps logged in immutable audit log (PostgreSQL)
```

### E5: Admin Accidentally Publishes Wrong LLM Profile

```
Admin publishes profile with wrong deployment in slot 2 (intent detection)
→ 3 tenants select new profile within 10 minutes
→ Intent detection queries failing across those tenants
→ Admin receives error rate alert
→ Admin immediately deprecates the profile
→ Tenants on wrong profile are notified: "Selected profile has been deprecated.
   Please select a different profile."
→ Admin fixes deployment config → publishes corrected profile
→ Tenant admins can re-select correct profile
Note: No automatic rollback to prevent unintended tenant disruption.
     Tenant admin always controls profile selection.
```

---

## Flow N+1: Platform Admin — Cross-Tenant Issue Queue

**Trigger**: Platform Admin opens the Issue Queue panel in the Platform Admin Console, or receives a P0/P1 alert.
**Entry**: Platform Admin Console → Issue Queue (left nav, Operations section)
**Persona**: Platform Admin (mingai platform operator, cross-tenant visibility)

---

### Happy Path — Triaging and Managing Incoming Issues

```
Start
  |
  v
[Platform Admin opens Issue Queue]
  |-- May be triggered by:
  |   |-- P0 PagerDuty alert (on-call)
  |   |-- P1 Slack engineering channel notification
  |   |-- Routine daily review
  |
  v
[Issue Queue — default view]
  |-- Table columns:
  |   |-- Reference (rpt_Q5FEID) — monospaced
  |   |-- Tenant (Acme Corp / BetaCo / ...)
  |   |-- Reported by role (End User / Tenant Admin)
  |   |-- Issue type (Bug / Performance / UX / Feature Request)
  |   |-- AI severity (P0–P4, colour-coded)
  |   |-- Status (New / In Triage / In Progress / Resolved / Won't Fix)
  |   |-- SLA target (date, red if overdue)
  |   |-- Duplicate count (N users reported this)
  |   |-- Submitted
  |
  |-- Default filter: Status ≠ Resolved, sorted by AI severity → SLA ascending
  |-- P0 issues appear at top with red alert border
  |
  v
[Admin scans queue]
  |
  |-- P0 issue visible (e.g. total service outage for one tenant)
  |     |-> Admin triages P0 first (see P0 path below)
  |
  |-- P1 issue (e.g. "Finance Agent 0% confidence on all tax queries — BetaCo")
  |     |-> Admin clicks to review
  |
  v
[Issue Detail Panel — Platform view]
  |-- Reporter info: user name, tenant (BetaCo), role
  |-- Submitted: timestamp · Screen: Chat
  |-- Type: Bug · AI severity: P1 · SLA: 4h · Submitted: 2h 12m ago
  |
  |-- Session context (collected at report time):
  |   |-- Query: "What is the corporate tax rate for SG entities?"
  |   |-- Model: GPT-5.2-chat · Balanced LLM Profile
  |   |-- Retrieval confidence: 0%
  |   |-- Sources: Finance KB (SharePoint) · Last synced: 67 days ago
  |
  |-- Screenshot (blurred by default — admin must explicitly reveal)
  |
  |-- Description (verbatim from user):
  |   "Every tax query returns 0% confidence. Started this morning."
  |
  |-- AI triage result:
  |   |-- Root cause hypothesis: "Finance KB not synced in 67 days.
  |       SharePoint connection may have expired (client secret rotation)."
  |   |-- Related issues: cross-tenant check shows 0 similar open issues
  |       in other tenants (isolated to BetaCo)
  |   |-- GitHub issue: #4521 (created by triage agent)
  |
  v
[Admin chooses action]
  |
  +-- ACCEPT AND ASSIGN TO ENGINEERING
  |     |-- Assigns to engineering sprint / milestone in GitHub
  |     |-- Reporter notified: "A developer has been assigned to your issue."
  |     |-- Tenant admin (BetaCo) notified: "P1 issue open in your workspace.
  |         [View details]"
  |
  +-- OVERRIDE AI SEVERITY
  |     |-- Admin adjusts P level + writes reason (required)
  |     |-- Example: AI said P1, admin upgrades to P0 because customer
  |         has a board presentation in 2 hours
  |     |-- SLA recalculates automatically
  |
  +-- ROUTE TO TENANT ADMIN FOR SELF-SERVICE
  |     |-- Issue is configuration-resolvable by tenant admin
  |     |-- Admin sends message: "Your SharePoint client secret has likely
  |         expired. Please reconnect in Settings → Integrations →
  |         SharePoint. [Instructions]"
  |     |-- Issue status: "Pending Tenant Action"
  |
  +-- MARK WON'T FIX
  |     |-- Requires written reason (mandatory)
  |     |-- Reporter + tenant admin notified with explanation
  |
  v
[Issue tracked until resolution]
  |-- Admin monitors SLA countdown
  |-- GitHub webhook fires on PR events → status auto-updates
  |-- On release deploy: all reporters notified "Fixed in version 2.3.1"
  |
  v
End
```

---

### P0 Fast-Track Path

```
[PagerDuty alert fires: P0 issue detected]
  |-- Trigger: 5xx error rate > 10% for one tenant for > 5 minutes
  |
  v
[On-call admin joins incident]
  |-- Opens Issue Queue — P0 issue pinned at top with red alert
  |-- Session context shows: which tenant, which endpoint, error codes
  |
  v
[Immediate investigation steps]
  |-- Check Azure monitoring dashboard (linked from issue detail)
  |-- Check LLM profile logs (is the tenant's profile working?)
  |-- Check SharePoint / index sync status
  |
  v
[Mitigation applied]
  |-- e.g. Roll back LLM profile, trigger emergency re-sync, scale up
  |
  v
[Tenant admin notified immediately — P0 SLA: 4h]
  |-- "We are aware of a service issue affecting your workspace and are
  |    actively investigating. Next update in 30 minutes."
  |-- Updates sent every 30 minutes until resolved
  |
  v
[P0 resolved]
  |-- Post-mortem required (linked to GitHub issue)
  |-- All reporters notified
  |-- Root cause documented in issue record
  |
  v
End
```

---

### Cross-Tenant Duplicate Detection

```
[Issue submitted by user at Acme Corp]
  |
  v
[AI triage: semantic similarity check against ALL open issues, ALL tenants]
  |
  |-- Match found in BetaCo (similarity 0.91):
  |   Same root cause — SharePoint sync expired client secret
  |
  v
[Platform admin sees cross-tenant duplicate flag in issue detail]
  |-- "This issue matches rpt_A1B2C3 (BetaCo). Root cause may be shared."
  |-- Impact score: 2 tenants × N users affected
  |-- These issues are surfaced to the top of the priority queue
  |
  v
[Admin can link issues and bulk-act]
  |-- "Apply same resolution to both" (if fix is the same)
  |-- All reporters across both tenants notified when resolved
  |
  v
End
```

---

### Platform-Wide Issue Analytics

```
[Admin clicks Issue Queue → Analytics tab]
  |
  v
[Cross-Tenant Heatmap]
  |-- Issue volume by tenant (which tenants experience the most issues)
  |-- Issue volume by category (Bug vs Performance vs UX vs Feature)
  |-- Issue volume by severity distribution (P0–P4)
  |-- SLA adherence rate this month (per severity level)
  |-- Mean Time to Resolution (MTTR) by severity
  |-- Week-over-week trend chart
  |
  v
[SLA Monitoring]
  |-- Issues at SLA risk: highlighted; shows hours remaining
  |-- P0 SLA: 4h · P1 SLA: 24h · P2 SLA: 7d · P3 SLA: 30d
  |-- Escalation rules: who is alerted when SLA is at risk
  |   (configurable per severity: Slack / email / PagerDuty)
  |
  v
[Auto-escalation thresholds (configurable)]
  |-- N duplicate reports → severity bump (default: 5 = review, 10 = auto-bump)
  |-- Tenant with > X open P1/P2 issues → tenant health score impact
  |
  v
End
```

---

### Edge Cases

**E-IQ-1: P1 issue — tenant admin self-resolves before engineering picks it up**
```
Platform admin assigns issue to engineering sprint
Tenant admin fixes SharePoint connection independently within 1 hour
Tenant admin marks issue "Resolved" from their Issue Queue
Platform issue auto-updated to "Resolved — tenant self-resolved"
Engineering sprint item removed (or kept as a preventive task)
```

**E-IQ-2: AI triage assigns wrong severity (P3 for what is clearly a P1)**
```
Platform admin reviews, overrides severity to P1
Reason logged: "User report indicates all tax queries broken for entire tenant"
SLA recalculates from override timestamp
System learns from override signal for future triage calibration (Phase 3+)
```

**E-IQ-3: Reporter data contains PII or confidential document content**
```
Screenshot was not blurred at submission (user manually revealed RAG content)
Platform admin reviews: screenshot contains extracted contract text
Admin redacts screenshot before forwarding to GitHub
Audit log records: redaction performed by [admin email] at [timestamp]
```

**E-IQ-4: Issue volume spike (> 20 reports in 1 hour from one tenant)**
```
Sudden spike detected — likely a systemic failure
Platform auto-escalates all related issues to P1 minimum
On-call alert fired
Admin investigates root cause (e.g. LLM profile misconfiguration)
After fix: bulk-notify all reporters simultaneously
```

---

**Section Added**: 2026-03-06
**Covers**: Cross-tenant Issue Queue, P0 fast-track, severity override, cross-tenant duplicate detection, SLA monitoring, analytics
