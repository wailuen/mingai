# 10 — Issue Reporting: User Flows

**Date**: 2026-03-05
**Personas**: End User (Reporter), Engineering Team (Resolver), Platform Admin, Tenant Admin

---

## Flow 1: End User Reports a Bug (Primary Flow)

**Trigger**: User encounters unexpected behavior during platform usage.
**Persona**: End User (any role: reader, analyst, admin)
**Entry points**: Floating report button, keyboard shortcut (Ctrl+Shift+F), auto-triggered on error detection

```
STEP 1: Trigger — User notices a problem
  User is on any page within the mingai platform
  Options:
    a) Clicks floating "Report Issue" button (always visible, bottom-right)
    b) Presses Ctrl+Shift+F (keyboard shortcut)
    c) Platform detects API error (5xx) → auto-opens reporter with pre-filled context

STEP 2: Issue Reporter Dialog Opens
  System automatically:
    - Captures screenshot of current page state (html2canvas, no permission prompt)
    - Collects session context (last query, model, sources, confidence score)
    - Collects browser context (browser, OS, viewport, console errors)
    - Pre-populates current URL and component name

  Dialog shows:
    - Screenshot preview with annotation toolbar (highlight, arrow, text, redact)
      **RAG response area is blurred by default.** User must click "Reveal RAG content" and confirm before it becomes visible in the screenshot. This prevents accidental inclusion of sensitive retrieved content.
    - Issue type selector: Bug / Performance / UX / Feature Request
      Note: "Feature Request" type routes to product backlog channel (NOT bug triage queue). AI skips severity/SLA classification for feature requests.
    - Title field (suggested: "[Component] - [brief description]")
    - Description field ("What happened? What did you expect?")
    - Severity hint: "How severe is this?" (High / Medium / Low / Suggestion)
      Note: This is a hint only — AI performs final classification

STEP 3: User Annotates Screenshot (Optional)
  User can:
    - Draw arrows/highlights to point at specific elements
    - Add text annotations
    - Redact sensitive information (draw black box over PII)

  Auto-redaction (background):
    - Password fields blurred automatically
    - Input fields with PII patterns (email, credit card) masked

STEP 4: User Writes Description and Submits
  User enters:
    - Title (required)
    - Description (required, max 10,000 chars)
    - Issue type (required)
    - Severity hint (optional)

  User clicks "Submit Report"

  System validates:
    - Title not empty
    - Description not empty
    - Not duplicate submission within 5 minutes (same description)
    - Rate limit not exceeded (max 10/day per user)

STEP 5: Screenshot Upload and Issue Creation
  [Frontend → Backend (async, non-blocking)]

  a) GET /api/v1/issue-reports/presign → pre-signed Azure Blob URL
  b) PUT screenshot directly to Azure Blob
  c) POST /api/v1/issue-reports with full payload

  User sees:
    - "Submitting..." loading state
    - Success: "Report submitted! Reference: #rpt_abc123"
    - Error: "Submission failed, try again" (with retry button)

STEP 6: Immediate Acknowledgment (< 30 seconds)
  System sends:
    - In-app notification: "Your report #rpt_abc123 has been received. Reference: #rpt_abc123"
    - Email acknowledgment: same content + link to My Reports page

  User sees notification badge on bell icon

STEP 7: AI Triage (Background, < 5 minutes)
  User does NOT wait for this — they continue working.

  AI agent processes:
    - Duplicate check (semantic similarity search)
    - Severity classification (P0-P4)
    - Category refinement (bug/performance/ux/feature)
    - Root cause hypothesis (using session context)
    - GitHub issue creation
    - SLA calculation

  After triage:
    User receives: "Your report has been triaged: Priority P2, target resolution by March 12.
    GitHub issue: #4521. [View My Reports]"

STEP 8: Status Tracking (Ongoing)
  User can view "My Reports" page at any time:
    - List of all submitted reports
    - Each report shows: status, severity, SLA target, GitHub issue number
    - Clicking a report shows: full timeline, AI triage result, current assignee (if public)

  Automated notifications (user receives without doing anything):
    - "Fix in progress — a developer has started working on #4521"
    - "Fix deployed to staging — please test if your issue is resolved"
    - "Fix live in production — this issue has been resolved in version 2.3.1"
    - "Issue closed (won't fix) — reason: [explanation from engineer]"
```

**Success criteria**: User submitted report in < 60 seconds, received acknowledgment < 30 seconds, received SLA commitment < 5 minutes.

---

## Flow 2: Duplicate Issue Detection (Parallel Flow)

**Trigger**: User submits a report that semantically matches an existing open issue.
**Persona**: End User

```
STEP 1: User submits report (same as Flow 1, Steps 1-5)

STEP 2: AI Duplicate Detection
  AI agent finds existing issue with similarity score > 0.88

  Triage result:
    - is_duplicate = true
    - parent_issue_id = 4521
    - similarity_score = 0.94

STEP 3: User Notification
  User receives:
    In-app: "Your report matches an existing known issue (#4521: 'Document upload
    fails silently on large PDFs'). Your report has been added as a +1.
    Current priority: P2, target resolution: March 12."

    Email: same content

STEP 4: User's Report Linked, Not Discarded
  The user's report is:
    - Stored with status "duplicate_linked"
    - Linked to parent issue #4521
    - User added to notification list for parent issue
    - User receives ALL status updates on parent issue going forward

  The user still sees their report in My Reports, with status "Linked to #4521"

STEP 5: Priority Boost
  If report volume for an issue crosses a threshold:
    - 5 reports: priority boost consideration
    - 10 reports: automatic escalation to next severity level
    - P2 with 10 reports → reviewed for promotion to P1

  All reporters receive: "Due to high report volume, this issue has been elevated to P1."
```

**Success criteria**: User knows their report was received AND that it's a known issue. No frustration from "issue not created."

---

## Flow 3: Auto-Triggered Report on Error Detection

**Trigger**: Platform detects a 5xx error, API timeout, or critical JS error.
**Persona**: End User (passive trigger)

```
STEP 1: Error Detection
  Frontend monitors:
    - API responses: any 5xx status code
    - Network timeouts: > 30 seconds for any request
    - Critical JS errors: uncaught exceptions (not validation errors)

  On detection:
    - Error metadata collected (status code, endpoint, timestamp, request duration)
    - Error added to pending_context for issue reporter

STEP 2: Soft Prompt (Non-Blocking)
  User sees a non-modal toast notification (does not interrupt flow):
    "Something went wrong. Would you like to report this? [Report Now] [Dismiss]"

  Note: This is NEVER a blocking modal — user can dismiss and continue.

STEP 3: User Clicks "Report Now"
  Issue reporter dialog opens with:
    - Error context PRE-FILLED: "API error 500 on /api/v1/rag/query at 14:23:45"
    - Screenshot auto-captured at moment of error (stored in memory, not yet uploaded)
    - Title pre-filled: "Error 500 on RAG query"
    - Error details pre-filled in description

  User reviews, optionally adds description, and submits.

STEP 4: High-Priority Auto-Classification
  Any 5xx error report → minimum P2 severity
  Repeated 5xx (>3 times same endpoint) → P1
  Service unavailable → P0

  These override the user's severity hint (protective measure).

STEP 5: Immediate Engineering Alert (P0/P1 only)
  P0: PagerDuty/on-call alert sent immediately
  P1: Slack engineering channel notification
  P2+: Standard triage queue
```

---

## Flow 4: Engineering Team Reviews Triaged Issues

**Persona**: Engineer / Engineering Manager
**Entry**: GitHub Issues or mingai Platform Admin > Issues Dashboard

```
STEP 1: Engineer Opens Platform Issues Dashboard
  Dashboard shows:
    - Incoming queue: new reports pending review
    - Triaged queue: AI-processed, ready for sprint planning
    - In Progress: issues with active PRs
    - SLA at risk: issues approaching SLA deadline
    - Resolved this week: recently closed

  Filters: severity, category, tenant, date range, assigned to me

STEP 2: Engineer Reviews a Triaged Issue
  Issue card shows:
    - AI severity score + reasoning
    - Category + root cause hypothesis
    - Duplicate count (if N users reported this)
    - Session context summary (query, model, confidence score, data sources)
    - Screenshot thumbnail
    - SLA target date
    - Reporter's user role (end_user, tenant_admin, etc.)

STEP 3: Engineer Accepts or Overrides AI Triage
  Options:
    a) Accept AI classification → issue moves to sprint backlog
    b) Override severity → engineer sets different P level + reason
    c) Mark as Won't Fix → requires reason; user notified with explanation
    d) Request more information → in-app message to reporter
    e) Mark as duplicate manually (if AI missed it)

STEP 4: Issue Assigned to Sprint
  Engineer assigns to milestone/sprint
  GitHub issue updated: assignee, milestone, sprint label

  Reporter receives: "An engineer has been assigned to your issue.
  Target completion: Sprint 14 (ends March 22)."

STEP 5: Engineer Works on Fix
  Normal development workflow (GitHub PR, code review, etc.)

  Reporter automatically notified when:
    - PR opened (Fix in progress)
    - PR merged to main (Fix deployed to staging)
    - Release published (Fix live in production)

STEP 6: Issue Closed
  On release deploy, GitHub webhook fires:
    - Issue record status → "resolved"
    - All reporters notified: "Fixed in version 2.3.1"
    - Reporter can confirm: "Was this resolved for you? [Yes] [No - still happening]"

  If reporter says "No - still happening":
    - Regression report created automatically
    - Linked to original issue
    - Severity escalated by 1 level
    - Rate limited: reporter can only trigger "still happening" once per 24 hours per issue (prevents abuse; subsequent clicks show: "Response recorded — engineering team has been notified")
```

---

## Flow 5: Platform Admin Reviews Cross-Tenant Quality Dashboard

**Persona**: Platform Admin
**Entry**: Platform Admin Console > Issue Analytics

```
STEP 1: Admin Views Platform-Wide Issue Heatmap
  Dashboard shows:
    - Issue volume by tenant (which tenants are experiencing the most issues?)
    - Issue volume by category (bugs vs performance vs UX vs features)
    - Issue volume by severity (P0-P4 distribution)
    - SLA adherence rate this month
    - Mean Time to Resolution (MTTR) by severity
    - Trend charts: issue volume week-over-week

STEP 2: Admin Drills into Cross-Tenant Duplicates
  Cross-tenant duplicate view shows:
    - Issues reported by 2+ tenants (deduplicated by embedding)
    - Impact score: how many tenants × how many users each
    - These are surface to the top of the priority queue

STEP 3: Admin Sets Platform-Wide SLA Policies
  Admin can configure:
    - SLA targets per severity level (default: P0=4h, P1=24h, P2=7d, P3=30d)
    - Escalation rules (who gets alerted when SLA is at risk)
    - Auto-escalation thresholds (report volume → severity bump)
    - Blackout periods (no SLA during planned maintenance)

STEP 4: Admin Reviews Issue Analytics Report
  Monthly report available:
    - Top 10 most-reported bugs
    - Features most requested
    - Tenants with highest issue density (possible quality problem signal)
    - Average reporter satisfaction (did user confirm fix worked?)
```

---

## Flow 6: Tenant Admin Configures Issue Reporting Settings

**Persona**: Tenant Admin
**Entry**: Tenant Settings > Issue Reporting

```
STEP 1: Tenant Admin Configures Integration
  Settings:
    - GitHub repository: [org/repo] (tenant's own repo, optional)
    - GitLab project: alternative to GitHub
    - Jira project: alternative for non-GitHub shops
    - Linear team: alternative
    - Notification recipients: who receives P0/P1 alerts (email/Slack)
    - Slack webhook URL: for engineering channel notifications

STEP 2: Tenant Admin Customizes Reporter Widget
  Options:
    - Widget position: bottom-right (default), bottom-left, top-right
    - Widget label: "Report Issue" (default), or custom text
    - Widget color: inherit platform brand colors
    - Custom categories: add domain-specific issue types
    - Custom fields: add fields relevant to their use case

  Note: Core severity classifications and SLA matrix are platform-controlled (not tenant-editable) to ensure consistent quality management.

STEP 3: Tenant Admin Sets Custom SLA Targets
  Tenant can override platform default SLAs:
    - More aggressive (e.g., P2 in 3 days instead of 7)
    - Less aggressive (if they have separate support team handling P3/P4)

  This becomes the communicated SLA to their users.

STEP 4: Tenant Admin Views Tenant Issue Dashboard
  Same as Platform Admin view but scoped to their tenant:
    - Their users' reports only
    - Their SLA adherence
    - Their most common issue categories
```

---

## Flow 7: User Requests Additional Information / Follow-Up

**Persona**: End User + Engineer (collaborative)

```
STEP 1: Engineer Needs More Information
  On GitHub issue or Platform dashboard:
  Engineer clicks "Request Information" → selects user → types question

  Question options:
    - Free text question
    - Request additional screenshot
    - Request browser console logs (user prompted to export)
    - Request session replay (user prompted to record screen)

STEP 2: User Receives Follow-Up Request
  In-app notification: "An engineer has a question about your report #rpt_abc123:
  'Can you tell us what search query you used just before this happened?'"

  Email: same with Reply button

STEP 3: User Responds
  a) In-app: User clicks notification → issue detail view → "Add Response" text area
  b) Via email: User replies to notification email (response captured via email parser)

  User can also:
    - Attach new screenshot
    - Provide additional context text
    - Mark as "no longer relevant / I found a workaround"

STEP 4: Response Delivered to Engineer
  Engineer receives in-app notification: "Reporter responded to #4521"
  Response appended to GitHub issue as comment

  Engineer continues investigation with additional context.
```

---

## Flow Summary Table

| Flow                        | Persona         | Duration            | Outcome                                           |
| --------------------------- | --------------- | ------------------- | ------------------------------------------------- |
| 1: Report Bug               | End User        | < 2 minutes         | Issue reported, acknowledged, SLA committed       |
| 2: Duplicate Detected       | End User        | < 1 minute          | Linked to existing issue, notifications enrolled  |
| 3: Auto-Triggered on Error  | End User        | < 1 minute          | Pre-filled report submitted, high-priority if 5xx |
| 4: Engineering Reviews      | Engineer        | 5-10 min/issue      | Issue triaged, assigned, user notified            |
| 5: Platform Admin Dashboard | Platform Admin  | Ongoing             | Cross-tenant quality visibility                   |
| 6: Tenant Configuration     | Tenant Admin    | 15 minutes one-time | Custom integration and notification setup         |
| 7: Follow-Up Conversation   | User + Engineer | Variable            | Richer context collected collaboratively          |

---

## Edge Cases and Error Handling

### Screenshot Fails to Capture

- html2canvas fails (cross-origin iframe content, WebGL canvas)
- Fallback: user asked to manually upload a screenshot
- Issue submission proceeds without screenshot (screenshot marked as "not available")

### Rate Limit Exceeded

- User sees: "You've reached the daily report limit (10). You can report more tomorrow, or contact support for urgent issues."
- Rate limit resets at midnight UTC

### GitHub API Failure

- Issue creation queued for retry (exponential backoff, max 3 attempts)
- If all retries fail: issue stored in Cosmos DB with `github_status: failed`
- Platform admin alerted; manual issue creation required
- Reporter still receives acknowledgment — GitHub failure is transparent to user

### AI Triage Timeout

- If AI triage takes > 2 minutes: fall back to default classification (P3, bug)
- Reporter notified: "Your issue is being reviewed manually by our team"
- Human triage queue for platform team to review

### Network Failure on Submit

- Frontend queues submission locally (IndexedDB) and retries automatically
- User sees: "Saved locally. Retrying when connection is restored."
- No data loss; report submitted when connectivity resumes
