# Value Audit Report

**Date**: 2026-03-15
**Auditor Perspective**: Enterprise CTO evaluating $500K+ platform adoption
**Environment**: http://localhost:3022 (frontend) / http://localhost:8022 (backend)
**Method**: Playwright browser automation + direct API testing

---

## Executive Summary

The mingai platform presents a structurally complete enterprise RAG application with three distinct roles (Platform Admin, Tenant Admin, End User), real seeded data, and a coherent dark-themed UI. However, the **core value proposition -- AI-powered chat -- is broken** (stream error on every query), several pages render empty skeleton tables with no data, and one critical page (Tenant Detail) crashes entirely. The platform tells an 80% story: navigation, layout, and data architecture are sound, but the final 20% -- the parts that prove the product works -- are missing or broken.

**Top finding**: The RAG pipeline fails at the LLM streaming stage, meaning no end user can get an AI response. This is a demo-ending defect.

**Single highest-impact fix**: Fix the chat stream error (likely Azure OpenAI client configuration or prompt builder failure) so the core chat flow works end-to-end. Without this, the product cannot demonstrate its reason for existence.

---

## Phase 0: Environment Check

| Check                | Result                                                                |
| -------------------- | --------------------------------------------------------------------- |
| Frontend (port 3022) | Running, serves pages                                                 |
| Backend (port 8022)  | Running, health = "degraded" (Redis error)                            |
| Login API            | All 3 roles authenticate successfully                                 |
| Console errors       | Multiple ERR_INCOMPLETE_CHUNKED_ENCODING, 404s, 405s, and CORS errors |

**Assessment**: Infrastructure is functional but noisy. Redis being down affects session management. Console errors would be visible in a live demo.

---

## Page-by-Page Audit

### Login Page (`/login`)

**What I See**: Clean dark login form with mingai logo, email/password fields, mint-green CTA button, "Phase 1: Local JWT authentication" footer text.

**Value Assessment**:

- Purpose clarity: CLEAR -- unmistakably a login page
- Data credibility: REAL -- authenticates against actual user records
- Value connection: CONNECTED -- routes to correct dashboard per role
- Action clarity: OBVIOUS -- single form, single button

**Client Questions**:

1. "Phase 1: Local JWT authentication" -- why is this visible to users? Implementation details leak into the UI.

**Verdict**: VALUE ADD (minor polish needed to remove dev text)

---

### Platform Admin Dashboard (`/platform`)

**What I See**: Four KPI cards (Active Users: 3, Documents Indexed: 0, Queries Today: 3, Satisfaction: 100.0%), tenant overview table showing 10 tenants with plan and status.

**Value Assessment**:

- Purpose clarity: CLEAR -- platform health at a glance
- Data credibility: CONTRADICTORY -- "0 Documents Indexed" alongside "100% Satisfaction" is suspicious. 3 queries with 0 documents = where are queries going? Satisfaction at 100% with only 2 feedback ratings is misleading.
- Value connection: CONNECTED -- links to tenant detail, issue queue
- Action clarity: OBVIOUS -- table rows link to tenant details

**Client Questions**:

1. "0 documents indexed but 3 queries today -- what are they querying against?"
2. "100% satisfaction with effectively no data -- is this calculated correctly or is it a default?"
3. "I see 10 tenants but several are obviously test data ('Test Corp 0f139d65', 'Contract Test Tenant a871096e'). In a demo, this screams 'not real'."

**Verdict**: NEUTRAL -- structure is right but data tells no compelling story

---

### Platform Admin: Tenants (`/platform/tenants`)

**What I See**: Table with 10 tenants, columns: Name, Plan, Status, Contact, Created, Actions (View link). "New Tenant" button visible.

**Value Assessment**:

- Purpose clarity: CLEAR -- tenant registry
- Data credibility: CONTRADICTORY -- mix of real seed tenant ("mingai") and obvious test artifacts ("Test Corp 0f139d65", "Error Test Corp", "Idempotent Corp"). Draft tenants mixed with active ones.
- Value connection: CONNECTED -- View links go to detail pages, New Tenant opens wizard
- Action clarity: OBVIOUS -- clear CTAs

**Client Questions**:

1. "Why do I see 'Error Test Corp' and 'Idempotent Corp' in a production-looking UI?"
2. "Where are the user counts per tenant? Cost per tenant? I need at-a-glance metrics."

**Verdict**: VALUE ADD (needs data cleanup for demo)

---

### Platform Admin: Tenant Detail (`/platform/tenants/[id]`)

**What I See**: BLANK PAGE. React error boundary catches a crash. Console shows 500 Internal Server Error.

**Value Assessment**:

- Purpose clarity: MISSING -- page is broken
- Data credibility: N/A
- Value connection: DEAD END -- the drill-down from tenant list goes nowhere
- Action clarity: ABSENT

**Root Cause**: The page component (`TenantDetailPage`) renders `TenantHeader`, `TenantActions`, `HealthBreakdown`, and `QuotaUsageBar`. The API endpoints `/platform/tenants/:id` (200), `/platform/tenants/:id/health` (200), and `/platform/tenants/:id/quota` (200) all work. However, a sub-component likely throws during rendering, crashing the whole page despite `ErrorBoundary` wrappers. The NotFoundErrorBoundary in the console error suggests a Next.js routing issue or an unhandled promise rejection in the page component.

**Severity**: CRITICAL

**Verdict**: VALUE DRAIN -- the most important drill-down in the PA flow is broken

---

### Platform Admin: Issue Queue (`/platform/issues`)

**What I See**: Filter chips for severity (P0-P4) and status (Open, In Progress, Waiting Info, Closed). Empty table below with column headers but no data.

**Value Assessment**:

- Purpose clarity: CLEAR -- issue management
- Data credibility: EMPTY -- we know there are 5 issues in the database (verified via API), but none appear in the table
- Value connection: ISOLATED -- filters and table exist but show nothing
- Action clarity: HIDDEN -- no visible actions since table is empty

**Root Cause**: The PA issue queue page at `/platform/issues` fetches data but renders an empty table. However, the sub-route `/platform/issues/queue` (Engineering Issue Queue) does show all 4 open issues with proper severity badges, SLA indicators, and action buttons (Accept, Override Severity, Assign, Request Info, Won't Fix).

**Client Questions**:

1. "I have two issue queue pages? Which one am I supposed to use?"
2. "The main Issues page is empty but the sub-queue has data. This is confusing."

**Verdict**: NEUTRAL (the sub-queue works well; the parent page needs fixing or redirecting)

---

### Platform Admin: Engineering Issue Queue (`/platform/issues/queue`)

**What I See**: Tab navigation (Incoming 4, Triaged, In Progress, SLA At-Risk 4, Resolved). Table with 4 issues showing severity badges, titles, tenant, status, reported date. Action buttons row: Accept, Override Severity, Assign, Request Info, Won't Fix.

**Value Assessment**:

- Purpose clarity: CLEAR -- triage and manage engineering issues
- Data credibility: REAL -- actual seeded issues with realistic titles (P0 RAG hallucination, P2 chat history, etc.)
- Value connection: CONNECTED -- SLA indicators show at-risk items, actions available
- Action clarity: OBVIOUS -- bulk actions visible, per-issue checkboxes

**Client Questions**:

1. "All 4 issues are SLA At-Risk -- does the SLA calculation actually work or is it a default?"
2. "The P1 issue ('Indexing pipeline stalled') is missing from this queue -- where is it?"

**Verdict**: VALUE ADD -- genuinely useful issue management interface

---

### Platform Admin: LLM Profiles (`/platform/llm-profiles`)

**What I See**: Table with 5 LLM profiles showing Name, Provider, Primary Model, Intent Model, Created, Actions (Edit/Delete). "New Profile" button. "Primary Azure GPT-5" marked as DEFAULT.

**Value Assessment**:

- Purpose clarity: CLEAR -- LLM deployment management
- Data credibility: REAL -- actual Azure OpenAI deployment names (gpt-5.2-chat, agentic-worker, agentic-vision)
- Value connection: CONNECTED -- edit modal opens with full form (profile name, provider, models, endpoint URL, API key reference)
- Action clarity: OBVIOUS -- Edit/Delete per row, New Profile button

**Client Questions**:

1. "The edit form has 'API Key Reference' -- does this actually connect to a secret store?"
2. "No 'Test Connection' button in the edit modal -- how do I verify the profile works?"

**Verdict**: VALUE ADD -- solid configuration interface

---

### Platform Admin: Analytics Hub (`/platform/analytics`)

**What I See**: Three cards linking to sub-pages: Cost Analytics, Issue Analytics, Cache Analytics. Each with description text.

**Value Assessment**:

- Purpose clarity: CLEAR -- analytics navigation
- Data credibility: N/A -- this is a routing page
- Value connection: CONNECTED -- links to three analytics sub-pages
- Action clarity: OBVIOUS

**Verdict**: NEUTRAL -- pass-through page, fine as-is

---

### Platform Admin: Cost Analytics (`/platform/analytics/cost`)

**What I See**: Time range tabs (7/30/90 Days), "Tenant Cost Breakdown" table header with Export CSV button. Table has column headers (Tenant, Plan, Tokens, LLM Cost, Infra Cost, Revenue, Margin %) but ALL ROWS ARE EMPTY SKELETONS.

**Value Assessment**:

- Purpose clarity: CLEAR -- cost management
- Data credibility: EMPTY -- skeleton rows with no data. Export CSV button on empty data.
- Value connection: DEAD END -- no data to act on
- Action clarity: HIDDEN -- Export CSV on empty data is misleading

**Client Questions**:

1. "This is supposed to be the Finance section -- my CFO is in this demo. An empty cost table is embarrassing."
2. "The Export CSV button on an empty table -- does it export headers only?"

**Verdict**: VALUE DRAIN -- critical section for enterprise buyers is empty

---

### Platform Admin: Agent Templates (`/platform/agent-templates`)

**What I See**: Tab navigation (All Templates, Published, Draft). Table with columns (Name, Category, Version, Status, Satisfaction, Adoption, Actions). ALL ROWS ARE EMPTY SKELETONS.

**Value Assessment**:

- Purpose clarity: CLEAR
- Data credibility: EMPTY -- skeleton rows
- Value connection: ISOLATED
- Action clarity: "New Template" button exists but table is empty

**Verdict**: VALUE DRAIN -- promises agent management but delivers nothing

---

### Platform Admin: Tool Catalog (`/platform/tool-catalog`)

**What I See**: "Register Tool" button. Table with columns (Name, Provider, Safety, Health, Last Ping, Actions). ALL ROWS ARE EMPTY SKELETONS.

**Verdict**: VALUE DRAIN -- empty skeleton table

---

### Platform Admin: Audit Log (`/platform/audit-log`)

**What I See**: Filter panel (Actor type, Action type, Tenant, Date range). Table with columns. Message: "No audit events match the current filters."

**Value Assessment**:

- Purpose clarity: CLEAR -- compliance audit trail
- Data credibility: EMPTY -- no audit events recorded despite login, tenant creation, and issue activities occurring
- Value connection: ISOLATED -- audit log exists but captures nothing

**Client Questions**:

1. "We did multiple admin operations -- logins, tenant views, profile edits -- and nothing shows in the audit log?"
2. "For SOC2 compliance, we need proof this works. An empty audit log is worse than no audit log."

**Verdict**: VALUE DRAIN -- promises compliance capability but proves nothing

---

### Platform Admin: Registry (`/platform/registry`)

**What I See**: Tabs (Published, Pending Review, All). Table with columns (Name, Category, Publisher, Status, Installs, Created, Actions). ALL ROWS ARE EMPTY SKELETONS.

**Verdict**: VALUE DRAIN -- empty

---

### Platform Admin: Alert Center (`/platform/alerts`)

**What I See**: Page title "Alert Center - Monitor and manage platform alerts and threshold breaches"

**Verdict**: NEUTRAL -- placeholder page with correct intent

---

### Tenant Admin Dashboard (`/settings/dashboard`)

**What I See**: Sidebar with WORKSPACE (Dashboard, Documents, Users, Agents, Glossary) and INSIGHTS (Analytics, Issues, Settings) sections. Four KPI cards (Active Users: 3, Documents Indexed: 0, Queries Today: 3, Satisfaction: 100%). Getting Started checklist (1/3 completed). Quick Actions (Invite Users, Manage Glossary, View Issues).

**Value Assessment**:

- Purpose clarity: CLEAR -- workspace health and onboarding
- Data credibility: REAL (partially) -- user count is accurate, getting started checklist is actionable
- Value connection: CONNECTED -- quick actions link to relevant pages
- Action clarity: OBVIOUS

**Client Questions**:

1. "The getting started checklist says 1/3 -- what's the one that's done?"
2. "Same concern as PA: 0 documents, 100% satisfaction -- the numbers don't build trust."

**Verdict**: VALUE ADD -- solid dashboard with onboarding guidance

---

### Tenant Admin: Users (`/settings/users`)

**What I See**: Table with 5 users showing Name, Email, Role, Status, Last Login. Invite User button. Filters for Role (Admin/User) and Status (Active/Invited/Suspended).

**Value Assessment**:

- Purpose clarity: CLEAR
- Data credibility: REAL -- actual seeded users with correct roles and statuses
- Value connection: CONNECTED -- invite flow opens inline form
- Action clarity: OBVIOUS

**Issue Found**: Platform Admin (admin@mingai.test) shows as "User" role, not "Platform Admin" role. This is a display bug -- the user has `platform_admin` in the DB but the UI normalizes to "User/Admin" labels incorrectly for PA users in a tenant context.

**Verdict**: VALUE ADD (minor display bug)

---

### Tenant Admin: Glossary (`/settings/glossary`)

**What I See**: Table with 11 terms (API, EBITDA, Invoice, KPI, KYC, LTV, MFA, NDA, RAG, SLA, SSO). Each with Full Form, Definition, Aliases count, Status. Export CSV, Import CSV, Add Term buttons. "Miss Signals" section below showing "No miss signals yet."

**Value Assessment**:

- Purpose clarity: CLEAR -- domain terminology for AI accuracy
- Data credibility: REAL -- actual business terms with full definitions
- Value connection: CONNECTED -- terms feed into the RAG pipeline's glossary expansion stage
- Action clarity: OBVIOUS

**Client Questions**:

1. "How do glossary terms actually improve AI responses? Can you show me before/after?"
2. "The Miss Signals section is empty -- is this because there's no query data?"

**Verdict**: VALUE ADD -- one of the strongest pages in the demo

---

### Tenant Admin: Knowledge Base / Documents (`/settings/knowledge-base`)

**What I See**: Two tabs: SharePoint and Google Drive. "No SharePoint sources connected. Connect your first source." Connect Source button opens a 4-step SharePoint connection wizard with Azure AD instructions.

**Value Assessment**:

- Purpose clarity: CLEAR
- Data credibility: REAL (empty state is honest)
- Value connection: CONNECTED -- wizard is detailed with real Azure AD setup steps
- Action clarity: OBVIOUS

**Verdict**: VALUE ADD -- honest empty state with actionable wizard

---

### Tenant Admin: Agents (`/settings/agents`)

**What I See**: "Agent management is coming in a future phase."

**Value Assessment**:

- Purpose clarity: VAGUE -- placeholder
- Data credibility: EMPTY
- Value connection: DEAD END -- despite 3 agents existing in the DB (HR Policy, IT Helpdesk, Procurement), the TA agent management page shows nothing
- Action clarity: ABSENT

**Client Questions**:

1. "I see agents in the end-user chat. Where do I configure them as an admin?"
2. "This is a Phase 1 product and agents already exist. Why can't I manage them?"

**Verdict**: VALUE DRAIN -- agents exist but admin management is absent

---

### Tenant Admin: Analytics (`/admin/analytics`)

**What I See**: 7-Day Satisfaction Rate (100.0%), Satisfaction Trend chart (30-day), Agent Breakdown ("No agent data yet"), Low Confidence Responses ("No low-confidence responses found"), Issue Queue with 5 issues, Issue Actions panel with detail view.

**Value Assessment**:

- Purpose clarity: CLEAR -- feedback monitoring and issue management
- Data credibility: REAL (partially) -- issues are real, satisfaction chart renders correctly
- Value connection: CONNECTED -- clicking an issue shows detail panel with actions (Respond, Resolve, Escalate)
- Action clarity: OBVIOUS

**Verdict**: VALUE ADD -- analytics and issue management combined in one view

---

### Tenant Admin: Issue Queue (`/settings/issue-queue`)

**What I See**: REDIRECTS TO CHAT PAGE. URL changes from `/settings/issue-queue` to `/chat`.

**Value Assessment**: This is a broken route. The TA issue queue exists in the sidebar nav but the route doesn't resolve to the correct page.

**Root Cause**: The route `/settings/issue-queue` likely doesn't have middleware to enforce TA role, so the middleware redirects non-authenticated or wrong-role users to chat. But the user IS authenticated as TA, so this is a routing/middleware bug.

**Severity**: HIGH

**Verdict**: VALUE DRAIN -- broken navigation

---

### Tenant Admin: SSO (`/settings/sso`)

**What I See**: "SSO is not configured. Set up SAML or OIDC to enable single sign-on." Configure SSO button opens a 3-step wizard (Step 1: Choose protocol - SAML 2.0 or OIDC).

**Verdict**: VALUE ADD -- proper SSO configuration flow

---

### Tenant Admin: Issue Reporting Settings (`/settings/issue-reporting`)

**What I See**: Configuration form with toggles: Enable Issue Reporting, Auto-escalate P0/P1, Escalation threshold (hours), Slack webhook URL, Notification email.

**Verdict**: VALUE ADD -- operational configuration

---

### Tenant Admin: Memory Settings (`/settings/memory`)

**What I See**: Configuration for Profile Learning, Working Memory (TTL selector), Memory Notes (auto-extract toggle).

**Verdict**: VALUE ADD -- differentiating AI memory feature

---

### Tenant Admin: Workspace Settings (`/settings/workspace`)

**What I See**: Form with workspace name, slug (read-only), plan display, logo upload, timezone, locale (11 languages), welcome message, system prompt token budget.

**Verdict**: VALUE ADD -- comprehensive workspace config

---

### End User: Chat Empty State (`/chat`)

**What I See**: Greeting "Good evening, End User." with subtitle "What would you like to know today?". Mode selector showing "Auto". KB hint: "SharePoint . Google Drive . Knowledge base active". Four suggestion chips (Outstanding invoices, Salary band L5, Annual leave policy, Contract clause 8.2b). Sidebar shows HISTORY with 5 previous conversations.

**Value Assessment**:

- Purpose clarity: CLEAR -- the primary value interface
- Data credibility: REAL -- KB hint is correct (not "RAG"), conversation history is real
- Value connection: CONNECTED -- this is the core product
- Action clarity: OBVIOUS -- type or click a chip

**Client Questions**:

1. "The greeting says 'End User' -- is this the actual user's name? (Yes, it is -- that's the seeded name, which is fine for demo but a real user would have their actual name)"
2. "Knowledge base active but 0 documents indexed -- what happens when I ask?"

**Verdict**: VALUE ADD -- clean, purposeful empty state

---

### End User: Chat Flow (CRITICAL PATH)

**What I See**: After typing a message and pressing Enter:

1. User message appears in the chat
2. Status indicators show: glossary_expansion, intent_detection, embedding, vector_search, sources (empty), context_assembly
3. Then: "Stream error" displayed as the AI response

**Value Assessment**:

- Purpose clarity: CLEAR (the attempt is clear)
- Data credibility: BROKEN -- the core product feature fails
- Value connection: BROKEN -- this is THE value chain
- Action clarity: N/A

**Root Cause**: The RAG pipeline executes stages 1-5 successfully (glossary expansion, intent detection, embedding, vector search with 0 results, context assembly) but fails at stage 6 or 7 (prompt build or LLM streaming). The error is caught by a generic try/except that returns "Stream error" with no useful detail. The likely cause is either:

1. Azure OpenAI API connection failure (wrong model name, expired key, network issue)
2. Prompt builder exception (context assembly succeeds but prompt build fails)
3. LLM streaming timeout

The backend runs with `--log-level warning` so the actual exception is not visible in logs.

**Severity**: CRITICAL -- this is the product's reason for existence

**Verdict**: VALUE DRAIN -- the single most important flow is broken

---

### End User: Conversation History

**What I See**: Sidebar shows 5 previous conversations with titles and timestamps. Clicking a conversation attempts to load it.

**Value Assessment**: History list renders correctly. Previous conversations from other sessions are visible, proving persistence works. Navigation between conversations should work (though we couldn't fully test due to the chat error).

**Verdict**: VALUE ADD (assuming conversations can be loaded)

---

### End User: Discover / Agent Registry (`/discover`)

**What I See**: "Agent Registry - Discover AI agents for your workspace". Category filter tabs (All, HR, IT, Finance, Legal, Procurement, Custom). No agent cards visible.

**Value Assessment**: Despite 3 agents existing in the database, the discover page shows no agent cards. The category filters exist but filter an empty list.

**Severity**: MEDIUM

**Verdict**: VALUE DRAIN -- agents exist but discovery page is empty

---

### End User: My Reports (`/my-reports`)

**What I See**: "My Reports - Track status and updates on issues you've submitted". Empty page.

**Value Assessment**: The page renders but the API call fails with CORS error (`No 'Access-Control-Allow-Origin' header`) and then an Internal Server Error (500).

**Root Cause**: The `/api/v1/my-reports` endpoint either doesn't exist or has a CORS misconfiguration. The backend returns 500 when called directly.

**Severity**: MEDIUM

**Verdict**: VALUE DRAIN -- broken API

---

## Value Flow Analysis

### Flow 1: Platform Admin Oversight (Dashboard -> Tenants -> Detail -> Issues)

**Steps Traced**:

1. `/platform` (Dashboard) -> See 10 tenants, 3 active users -> OK
2. Click "Tenants" -> `/platform/tenants` -> See tenant table -> OK
3. Click "View" on mingai -> `/platform/tenants/[id]` -> BLANK PAGE (500 error) -> BROKEN
4. Navigate to Issues -> `/platform/issues` -> Empty table -> BROKEN
5. Navigate to Issues Queue -> `/platform/issues/queue` -> See 4 issues -> OK

**Flow Assessment**:

- Completeness: BROKEN AT STEP 3
- Narrative coherence: WEAK -- dashboard claims 3 active users but detail page crashes
- Evidence of value: ABSENT at the drill-down level

**Where It Breaks**: Tenant detail page crash destroys the "I can manage my tenants" narrative.

---

### Flow 2: Tenant Admin Setup (Dashboard -> Users -> KB -> Agents -> Glossary)

**Steps Traced**:

1. `/settings/dashboard` -> See KPIs + Getting Started checklist -> OK
2. Click Users -> `/settings/users` -> See 5 users, Invite button works -> OK
3. Click Documents -> `/settings/knowledge-base` -> See empty state with connect wizard -> OK
4. Click Agents -> `/settings/agents` -> "Coming in a future phase" -> DEAD END
5. Click Glossary -> `/settings/glossary` -> See 11 terms with full data -> OK

**Flow Assessment**:

- Completeness: BROKEN AT STEP 4
- Narrative coherence: WEAK -- agents exist in the system but the admin can't manage them
- Evidence of value: DEMONSTRATED for glossary and user management

---

### Flow 3: End User Chat (Login -> Empty State -> Send Query -> Get Response -> Feedback)

**Steps Traced**:

1. `/login` -> Login as end user -> OK
2. `/chat` -> See empty state with greeting, KB hint, chips -> OK
3. Type query, press Enter -> Message sent -> OK
4. Wait for response -> "Stream error" -> BROKEN
5. Feedback -> N/A (no response to rate)

**Flow Assessment**:

- Completeness: BROKEN AT STEP 4
- Narrative coherence: STRONG up to step 3, then collapses
- Evidence of value: ABSENT -- cannot demonstrate the core product

---

## Cross-Cutting Issues

### Cross-Cutting Issue: Empty Skeleton Tables

**Severity**: HIGH
**Affected Pages**: Cost Analytics, Agent Templates, Tool Catalog, Registry
**Impact**: 4 pages in the PA role show skeleton loading rows that never populate. This creates a "hollow product" impression.
**Root Cause**: Backend endpoints either return empty arrays, 404, or are not yet implemented. Frontend renders skeleton placeholders indefinitely.
**Fix Category**: DATA (seed realistic data) + FLOW (show proper empty states instead of skeleton rows)

### Cross-Cutting Issue: Console Errors (ERR_INCOMPLETE_CHUNKED_ENCODING)

**Severity**: MEDIUM
**Affected Pages**: Every page
**Impact**: Multiple "Failed to load resource: net::ERR_INCOMPLETE_CHUNKED_ENCODING" errors appear on every page load. These indicate broken SSE/streaming connections being dropped.
**Root Cause**: SSE endpoints (likely notification streams or real-time updates) fail to establish or are being interrupted. Redis being down may cause these.
**Fix Category**: FLOW -- either fix Redis connection or gracefully handle missing real-time features

### Cross-Cutting Issue: Test Data Pollution

**Severity**: HIGH
**Affected Pages**: Tenants, Users
**Impact**: Tenants like "Test Corp 0f139d65", "Error Test Corp", "Idempotent Corp", and "Contract Test Tenant a871096e" are obviously automated test artifacts. Users "testinvite@example.com" and "invited@acmecorp.com" are test invites. These destroy demo credibility.
**Root Cause**: Integration tests created data that was never cleaned up.
**Fix Category**: DATA -- clean up test artifacts or use separate test database

### Cross-Cutting Issue: CORS Errors

**Severity**: MEDIUM
**Affected Pages**: My Reports
**Impact**: The `/api/v1/my-reports` endpoint returns CORS errors when called from the frontend.
**Root Cause**: Endpoint either missing from CORS configuration or doesn't exist.
**Fix Category**: FLOW

### Cross-Cutting Issue: Route/Navigation Mismatch

**Severity**: MEDIUM
**Affected Pages**: TA Issue Queue (`/settings/issue-queue`), PA Issues vs Queue
**Impact**: Navigation items in the sidebar point to routes that redirect unexpectedly or don't match the expected content.
**Root Cause**: Route middleware or page components are missing for some nav items.
**Fix Category**: FLOW

---

## What a Great Demo Would Look Like

A compelling demo of this platform would show:

1. **Platform Admin**: Login, see dashboard with 3-5 realistic tenants (Acme Financial, Globex Manufacturing, Initech Software), each with 50-200 users, real cost data ($2K-$8K/month), and health scores. Drill into a tenant, see health breakdown, quota usage at 60%, recent issues being triaged. Navigate to cost analytics and see margin data. Show the issue queue with a P0 being triaged in real-time.

2. **Tenant Admin**: Login, see dashboard showing 47 active users (out of 50 quota), 2,081 documents indexed across SharePoint and Google Drive, 94% satisfaction. Navigate to users and show the invite flow. Show the glossary with 20+ terms and demonstrate a "miss signal" where the AI detected an undefined acronym. Navigate to analytics and show the satisfaction trend climbing from 85% to 94%.

3. **End User**: Login, see greeting with their actual name. Click "Annual leave policy" chip, watch the streaming response appear with 3 source citations, confidence score, and source panel. Give thumbs-up feedback. Ask a follow-up question. Switch to Finance Analyst agent mode and ask about Q3 revenue. Show the conversation appearing in history.

The difference between the current state and a great demo is:

- **Chat MUST work** -- streaming AI responses with source citations
- **Data MUST be realistic** -- no test artifacts, believable metrics
- **Empty states MUST be eliminated** -- either seed data or show honest empty states with clear CTAs

---

## Severity Table

| #   | Issue                                                                          | Severity | Impact                                                             | Fix Category | File Reference                                                                                           |
| --- | ------------------------------------------------------------------------------ | -------- | ------------------------------------------------------------------ | ------------ | -------------------------------------------------------------------------------------------------------- |
| 1   | Chat stream error -- core RAG pipeline breaks at context_assembly/prompt_build | CRITICAL | No AI responses possible; product cannot demonstrate primary value | FLOW         | `src/backend/app/modules/chat/orchestrator.py:199-268`, `src/backend/app/modules/chat/routes.py:321-330` |
| 2   | Tenant Detail page crashes (500 + React error boundary)                        | CRITICAL | PA cannot drill into any tenant; oversight flow broken             | FLOW         | `src/web/app/(platform)/platform/tenants/[id]/page.tsx:23-83`                                            |
| 3   | PA Issue Queue (`/platform/issues`) renders empty despite 5 issues in DB       | HIGH     | PA cannot see cross-tenant issues from main nav                    | DATA/FLOW    | `/platform/issues` page vs `/platform/issues/queue`                                                      |
| 4   | Cost Analytics shows only skeleton rows -- no data                             | HIGH     | Finance section is empty; CFO sees nothing                         | DATA         | `src/web/app/(platform)/platform/analytics/cost/page.tsx`                                                |
| 5   | Agent Templates page -- empty skeleton                                         | HIGH     | Intelligence section is hollow                                     | DATA         | `src/web/app/(platform)/platform/agent-templates/page.tsx`                                               |
| 6   | TA Issue Queue (`/settings/issue-queue`) redirects to chat                     | HIGH     | Broken nav item in TA sidebar                                      | FLOW         | Route/middleware issue                                                                                   |
| 7   | TA Agents page shows "coming in a future phase" despite 3 agents in DB         | HIGH     | Admin cannot manage agents that users see                          | FLOW         | `src/web/app/settings/agents/page.tsx`                                                                   |
| 8   | Test data pollution in tenant and user tables                                  | HIGH     | Demo credibility destroyed                                         | DATA         | `src/backend/app/core/bootstrap.py` + test cleanup                                                       |
| 9   | Agent Discovery (`/discover`) shows no agents despite 3 in DB                  | MEDIUM   | End users cannot browse agents                                     | DATA/FLOW    | `src/web/app/discover/page.tsx`                                                                          |
| 10  | My Reports page -- CORS error + 500 on API                                     | MEDIUM   | Issue tracking for end users broken                                | FLOW         | CORS config + `/api/v1/my-reports` endpoint                                                              |
| 11  | Audit Log shows zero events despite admin activity                             | MEDIUM   | Compliance story has no proof                                      | DATA/FLOW    | Audit event capture not wired                                                                            |
| 12  | Tool Catalog, Registry -- empty skeletons                                      | MEDIUM   | More hollow pages                                                  | DATA         | Multiple pages                                                                                           |
| 13  | Console ERR_INCOMPLETE_CHUNKED_ENCODING on every page                          | MEDIUM   | Visible in dev tools during demo                                   | FLOW         | SSE connection handling                                                                                  |
| 14  | Platform Admin shows as "User" role in TA user list                            | LOW      | Misleading role display                                            | DESIGN       | `src/web/app/settings/users/elements/UserTable.tsx`                                                      |
| 15  | "Phase 1: Local JWT authentication" text visible on login                      | LOW      | Implementation detail in user-facing UI                            | DESIGN       | `src/web/app/login/page.tsx:106`                                                                         |
| 16  | Satisfaction 100% with minimal data is misleading                              | LOW      | Data credibility issue                                             | NARRATIVE    | Dashboard calculation logic                                                                              |

---

## Bottom Line

If I were presenting this to my board after a demo, I would say: **"The architecture is sound and the team clearly knows enterprise SaaS. They have real multi-tenancy, proper RBAC, a thoughtful 8-stage RAG pipeline, and strong UX fundamentals. But the product is not demo-ready. The core feature -- AI chat -- is broken. Four major admin pages are empty shells. Test data is littered throughout. I would need to see the chat working end-to-end with real data, all admin pages populated with credible metrics, and test artifacts cleaned up before I would bring this back for a second look. The gap between 'almost there' and 'ready to buy' is probably 2-3 focused engineering sprints."**

The platform has genuine architectural merit -- the multi-tenant isolation, the 8-stage RAG pipeline, the glossary expansion system, the issue escalation workflow, and the SSO configuration wizard are all enterprise-grade. But a demo is about proof, not promise. Right now, this product is 80% promise and 20% proof. To flip that ratio, fix the chat, populate the data, and clean the test artifacts.
