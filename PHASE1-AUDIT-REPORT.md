# Phase 1 Value Audit Report -- mingai Enterprise RAG Platform

**Date**: 2026-03-09
**Auditor Perspective**: Enterprise CTO evaluating $500K+ platform purchase
**Environment**: Backend `http://localhost:8022` / Frontend `http://localhost:3022`
**Method**: Direct API testing (curl/Python requests) + Playwright headless browser walkthrough
**Credentials**: `admin@mingai.test` / `Admin1234!` (Platform Admin)

---

## Executive Summary

The platform has the architectural skeleton of an enterprise AI governance product -- three-role layout, dark-first design system, sidebar-driven navigation -- but **75% of the Platform Admin surface area and 100% of the Tenant Admin surface area are non-functional in a demo context**. The backend API has 5 endpoints returning 500 errors, and the frontend has 6 of 8 Platform Admin sidebar pages showing a placeholder string ("This section is coming in a future phase.") or redirecting away. The single highest-impact fix is **making the Tenants page and Issue Queue functional**, because without tenant management and issue triage working, the core Platform Admin story ("I govern and monitor my AI tenants") cannot be told.

---

## 1. API Health Summary

| #   | Endpoint                               | Method | Status  | Issue                                                                                       |
| --- | -------------------------------------- | ------ | ------- | ------------------------------------------------------------------------------------------- |
| 1   | `/health`                              | GET    | 200     | OK -- returns `{"status":"healthy"}`                                                        |
| 2   | `/ready`                               | GET    | 404     | **MISSING** -- endpoint does not exist. No readiness probe for Kubernetes deployments.      |
| 3   | `/api/v1/auth/local/login`             | POST   | 200     | OK -- returns JWT with correct claims                                                       |
| 4   | `/api/v1/platform/tenants`             | GET    | 200     | OK -- returns 7 seeded tenants with name, status, plan, created_at                          |
| 5   | `/api/v1/platform/tenants`             | POST   | 201     | OK -- creates tenant successfully                                                           |
| 6   | `/api/v1/platform/llm-profiles`        | GET    | 200     | Returns empty array `[]` -- no profiles seeded                                              |
| 7   | `/api/v1/platform/llm-profiles`        | POST   | **500** | **BROKEN** -- Internal Server Error on create. Schema mismatch between OpenAPI and handler. |
| 8   | `/api/v1/platform/analytics/costs`     | GET    | **404** | **MISSING** -- endpoint not implemented                                                     |
| 9   | `/api/v1/platform/issues`              | GET    | 200     | Returns empty array -- no issues seeded                                                     |
| 10  | `/api/v1/platform/tenants/{id}/health` | GET    | **500** | **BROKEN** -- Internal Server Error                                                         |
| 11  | `/api/v1/issues`                       | POST   | **500** | **BROKEN** -- Internal Server Error on issue creation                                       |
| 12  | `/api/v1/teams/`                       | GET    | **500** | **BROKEN** -- Internal Server Error                                                         |
| 13  | `/api/v1/users/`                       | GET    | 403     | Requires tenant_admin scope (correct RBAC, but no tenant admin user seeded to test)         |
| 14  | `/api/v1/glossary/`                    | GET    | 200     | Returns empty array -- no terms seeded                                                      |
| 15  | `/api/v1/glossary/`                    | POST   | 403     | Requires tenant_admin scope (correct RBAC)                                                  |

### API Summary

- **Working**: 7 endpoints (health, login, tenant CRUD read/write, LLM profiles read, issues read, glossary read)
- **Broken (500)**: 4 endpoints (LLM profile create, tenant health, issue create, teams list)
- **Missing (404)**: 2 endpoints (ready probe, cost analytics)
- **RBAC-gated but untestable**: 3 endpoints (users list, glossary create -- no tenant_admin seed user)

### Critical API Finding

The 500 errors on LLM profile creation and issue creation are **demo-blocking**. These are the two write operations that a Platform Admin would most likely perform in a live demo (configure the AI models, report a problem). Both fail silently with generic Internal Server Error responses.

---

## 2. Frontend Flow Results

### 2a. Platform Admin Flows

#### Dashboard (`/settings/dashboard`)

**What I See**: Dark theme page with four KPI cards (Active Users, Documents Indexed, Queries Today, Satisfaction) all showing **0** with **+0% vs last 7 days** trend lines. Below: Quick Actions section with three cards (Invite Users, Connect Document Store, Deploy Agent).

**Value Assessment**:

- Purpose clarity: **CLEAR** -- Dashboard communicates "here is your platform health at a glance"
- Data credibility: **EMPTY** -- Every metric is zero. The "+0% vs last 7 days" trend is mathematically meaningless on zero data. Satisfaction shows "0%" in alert-red, which is misleading (no data is not the same as 0% satisfaction).
- Value connection: **ISOLATED** -- Quick Actions lead to pages that either redirect or are stubbed. "Invite Users" goes to a page that redirects to /chat. "Connect Document Store" goes to a page that redirects to /chat. "Deploy Agent" goes nowhere functional.
- Action clarity: **MISLEADING** -- Quick Actions promise functionality that does not exist in the Platform Admin context.

**Client Questions**:

1. "Why does my dashboard show 0% satisfaction in red? I have no users yet -- 0% implies they are all unhappy."
2. "These Quick Actions -- Invite Users, Connect Document Store -- are these not Tenant Admin functions? Why are they on the Platform Admin dashboard?"
3. "Where are the tenant health scores, active tenant count, and system-wide query volume?"

**Verdict**: VALUE DRAIN -- A dashboard of zeros with broken Quick Actions is worse than no dashboard. It signals "we built the frame but nothing is connected."

---

#### Tenants (`/settings/tenants`)

**What I See**: Page shows only the text "This section is coming in a future phase." on a dark background.

**Value Assessment**:

- Purpose clarity: **MISSING** -- The page has no content.
- Data credibility: **N/A** -- No data present.
- Value connection: **DEAD END** -- The backend API at `GET /platform/tenants` returns 7 fully populated tenants with names, plans, statuses. The frontend simply does not render them.
- Action clarity: **ABSENT** -- No actions available.

**Client Questions**:

1. "The API returns 7 tenants. Why can I not see them here?"
2. "Tenant management is the core Platform Admin function. When does this ship?"

**Verdict**: VALUE DRAIN -- This is the most important page for Platform Admin and it is a placeholder. The API is ready. The frontend is not. This is a P0 gap.

---

#### Issue Queue (`/settings/issue-queue`)

**What I See**: Page title "Issue Queue" with subtitle "Issues reported by your workspace users". Filter chips for severity (P0-P4) and status (New, In Review, Escalated, Resolved, Closed). Table with column headers (SEVERITY, TITLE, REPORTER, STATUS, REPORTED). **Five skeleton loading rows that never resolve to actual data.**

**Value Assessment**:

- Purpose clarity: **CLEAR** -- The page communicates its purpose well through title, filters, and table structure.
- Data credibility: **BROKEN** -- Skeleton rows indicate data is being fetched but never arrives. The API at `GET /platform/issues` returns an empty array (200 OK), so the frontend should show an empty state, not infinite skeleton loading.
- Value connection: **PARTIAL** -- The page structure is correct (severity filters, status workflow). But with no issues seeded and the skeleton loading bug, it demonstrates nothing.
- Action clarity: **HIDDEN** -- No way to create a test issue from this page; the POST /issues endpoint returns 500 anyway.

**Client Questions**:

1. "Why is the table stuck loading? Is it fetching from the wrong endpoint?"
2. "Can I seed some sample P0/P1 issues to see the triage workflow?"
3. "Where is the slide-in detail panel for individual issues? The spec describes it but I see no evidence."

**Verdict**: NEUTRAL (with bug) -- The UI structure is correct and the filter chips suggest a thoughtful design. But the skeleton-never-resolving bug and empty data make it undemoable. Fix the loading state and seed 5-10 issues and this page becomes a value add.

---

#### LLM Profiles (`/settings/llm-profiles`)

**What I See**: "This section is coming in a future phase."

**Value Assessment**:

- Value connection: **DEAD END** -- The backend has a full LLM profile CRUD API. The frontend ignores it.
- The spec describes a 6-slot model (primary, intent, embedding, vision, router, worker) that is central to the "AI governance" narrative. A Platform Admin who cannot configure models cannot govern anything.

**Verdict**: VALUE DRAIN -- P0 for demo readiness.

---

#### Agent Templates, Analytics, Tool Catalog, Cost Analytics (`/settings/agent-templates`, `/settings/analytics-platform`, `/settings/tool-catalog`, `/settings/cost-analytics`)

**What I See**: All four pages show "This section is coming in a future phase." (Agent Templates, Tool Catalog, Cost Analytics) or redirect to `/chat` (Analytics).

**Verdict**: VALUE DRAIN -- These are Phase 2+ items on the sidebar but should not be visible if they have no content. Showing a placeholder for 5 out of 8 sidebar items tells the buyer "we planned a lot but built very little."

---

### 2b. Tenant Admin Flows

**Testing Limitation**: The seed data only creates a platform_admin user. No tenant_admin user exists in the seed. When logged in as platform_admin (scope: "platform"), navigating to tenant admin pages (Users, Documents, Agents, Glossary) results in a redirect to `/chat` -- the AppShell correctly gate-checks the scope and redirects non-tenant users.

**However**, the code exists. Reading the source files confirms:

| Page           | File                               | Status         | Implementation                                                                |
| -------------- | ---------------------------------- | -------------- | ----------------------------------------------------------------------------- |
| Users          | `settings/users/page.tsx`          | **BUILT**      | Full UserTable with search, filters, pagination, invite modal                 |
| Knowledge Base | `settings/knowledge-base/page.tsx` | **BUILT**      | SharePoint + Google Drive tabs, connection wizards, source status cards       |
| Glossary       | `settings/glossary/page.tsx`       | **BUILT**      | Full term CRUD, search, status filters, CSV import/export, miss signals panel |
| Agents         | N/A                                | **NOT FOUND**  | No `settings/agents/page.tsx` file exists                                     |
| Analytics      | N/A                                | **NOT TESTED** | Redirects to /chat for platform scope                                         |
| Issues         | N/A                                | **NOT TESTED** | Separate from platform issue queue                                            |

**Critical Gap**: The Tenant Admin persona cannot be demonstrated because no tenant_admin user is seeded. The code for 3 of the 5 core Tenant Admin pages exists and appears substantial (Users, Knowledge Base, Glossary). The demo is blocked by missing seed data, not missing code.

---

### 2c. End User Flows

#### Chat Page (`/chat`)

**What I See**: Centered empty state with a diamond agent icon (44x44px), greeting "Good evening, Admin.", subtitle "What would you like to know today?", embedded input bar with "Auto" mode selector dropdown, attachment icon, send button. Below the input: KB hint "SharePoint . Google Drive . 2,081 documents indexed" with green accent dot. Four suggestion chips: "Outstanding invoices", "Salary band L5", "Annual leave policy", "Contract clause 8.2b".

**Value Assessment**:

- Purpose clarity: **CLEAR** -- This immediately communicates "ask your enterprise AI a question."
- Data credibility: **CREDIBLE** -- The KB hint claims 2,081 documents indexed from SharePoint and Google Drive. This is specific enough to be believable. The suggestion chips are domain-relevant (finance, HR, legal).
- Value connection: **POTENTIAL** -- This is the revenue-generating surface. If the RAG pipeline works, this is where value is delivered. Not tested end-to-end (would require document indexing and LLM integration to be active).
- Action clarity: **OBVIOUS** -- Type a question, hit send. The mode selector provides routing. The suggestions lower the barrier.

**Design System Compliance**:

- Empty state layout: CORRECT -- centered, agent icon, greeting, embedded input (not bottom-fixed)
- KB hint: CORRECT -- "SharePoint . Google Drive . 2,081 documents indexed" (no "RAG" label visible to user)
- Suggestion chips: Present and styled correctly with accent border
- Mode selector: "Auto" dropdown present in input bar per spec

**Client Questions**:

1. "What happens when I send a message? Does the RAG pipeline actually work?"
2. "The mode selector shows 'Auto' -- what other modes are available? Are finance, HR, legal agents configured?"
3. "2,081 documents -- is this real data or a hardcoded string?"

**Verdict**: VALUE ADD -- The chat empty state is the strongest element in the entire demo. It is well-designed, communicates its purpose clearly, and follows the design system precisely. The question is whether anything happens when you press send.

---

### 2d. Sidebar Structure Audit

**Design System Spec (design-system.md)**:

| Role           | Spec Sections                     | Spec Items                                                                                              |
| -------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Platform Admin | Operations, Intelligence, Finance | Dashboard, Tenants, Issue Queue, LLM Profiles, Agent Templates, Analytics, Tool Catalog, Cost Analytics |
| Tenant Admin   | Workspace, Insights               | Dashboard, Documents, Users, Agents, Glossary, Analytics, Issues, Settings                              |
| End User       | History only (conversation list)  | No navigation items in sidebar                                                                          |

**Implementation (Sidebar.tsx)**:

| Role           | Implemented Sections              | Implemented Items                                                                                       | Match?  |
| -------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------- | ------- |
| Platform Admin | Operations, Intelligence, Finance | Dashboard, Tenants, Issue Queue, LLM Profiles, Agent Templates, Analytics, Tool Catalog, Cost Analytics | **YES** |
| Tenant Admin   | Workspace, Insights               | Dashboard, Documents, Users, Agents, Glossary, Analytics, Issues, Settings                              | **YES** |
| End User       | ConversationList component        | Privacy link at bottom                                                                                  | **YES** |

**Sidebar implementation matches the design system spec exactly.** The three-role architecture is correctly implemented in code. The issue is that 6 of 8 Platform Admin destination pages have no content.

---

## 3. Gap Registry

| #    | Gap                                | Spec Promise                                                                            | Reality                                                                                    | Severity | Root Cause                                                                 |
| ---- | ---------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | -------- | -------------------------------------------------------------------------- |
| G-01 | Tenant list page empty             | Platform Admin sees all tenants in a table with health scores, user counts, plan badges | "This section is coming in a future phase." despite API returning 7 tenants                | **P0**   | Frontend not wired to API                                                  |
| G-02 | LLM Profile page empty             | Platform Admin configures 6-slot model profiles (primary, intent, embedding, etc.)      | "This section is coming in a future phase."                                                | **P0**   | Frontend not built                                                         |
| G-03 | LLM Profile creation 500           | POST creates a new profile                                                              | 500 Internal Server Error                                                                  | **P0**   | Backend schema/handler mismatch                                            |
| G-04 | Issue creation 500                 | POST /issues creates a new issue with AI triage                                         | 500 Internal Server Error                                                                  | **P1**   | Backend handler error                                                      |
| G-05 | Tenant health 500                  | GET /platform/tenants/{id}/health returns health score                                  | 500 Internal Server Error                                                                  | **P1**   | Backend handler error                                                      |
| G-06 | Teams endpoint 500                 | GET /teams/ lists team memberships                                                      | 500 Internal Server Error                                                                  | **P1**   | Backend handler error                                                      |
| G-07 | Issue Queue skeleton bug           | Table shows empty state or populated rows                                               | Infinite skeleton loading (never resolves)                                                 | **P1**   | Frontend loading state not handling empty array response correctly         |
| G-08 | No /ready endpoint                 | Kubernetes readiness probe at /ready                                                    | 404                                                                                        | **P2**   | Not implemented                                                            |
| G-09 | No cost analytics API              | GET /platform/analytics/costs returns spend data                                        | 404                                                                                        | **P2**   | Not implemented                                                            |
| G-10 | Dashboard KPIs all zero            | Dashboard shows real metrics (active users, queries, satisfaction)                      | All metrics are 0 with "+0% vs last 7 days"                                                | **P1**   | No data aggregation pipeline or seed data                                  |
| G-11 | Dashboard Quick Actions misleading | Quick Actions lead to functional pages                                                  | "Invite Users" and "Connect Document Store" redirect to /chat for Platform Admin           | **P1**   | Quick Actions are Tenant Admin functions shown on Platform Admin dashboard |
| G-12 | No tenant_admin seed user          | Tenant Admin flows can be demonstrated                                                  | Tenant Admin pages redirect to /chat because no tenant_admin JWT can be obtained           | **P0**   | Bootstrap only seeds platform_admin                                        |
| G-13 | Satisfaction 0% in red             | No-data state should show N/A or "--"                                                   | Shows "0%" in alert-red coloring, implying all users are unhappy                           | **P2**   | Zero treated as a valid metric value instead of no-data state              |
| G-14 | 5 sidebar pages are stubs          | All sidebar items lead to functional pages                                              | Tenants, LLM Profiles, Agent Templates, Tool Catalog, Cost Analytics show placeholder text | **P1**   | Frontend pages not implemented                                             |
| G-15 | Analytics redirects to /chat       | Platform Analytics page shows cross-tenant analytics                                    | Navigating to /settings/analytics-platform redirects to /chat                              | **P1**   | Page not implemented, falls through to default route                       |
| G-16 | Agents page missing                | Tenant Admin Agents page allows agent deployment configuration                          | No `settings/agents/page.tsx` file exists                                                  | **P2**   | Not yet implemented                                                        |
| G-17 | Empty glossary with no seed data   | Glossary page shows terms, miss signals, usage stats                                    | Empty array, no terms to demonstrate the value of domain terminology governance            | **P2**   | No seed data                                                               |
| G-18 | Chat RAG pipeline untested         | User sends query, gets AI response with sources and relevance scores                    | Not tested -- requires active LLM and document indexing                                    | **P1**   | Requires integration testing with live LLM                                 |

---

## 4. Design System Compliance

### Obsidian Intelligence Adherence

| Element            | Spec                                                                      | Implementation                                                     | Compliant?                                                                                       |
| ------------------ | ------------------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| Background base    | `#0c0e14`                                                                 | Dark background visible in screenshots                             | **YES**                                                                                          |
| Surface color      | `#161a24`                                                                 | Cards and sidebar match                                            | **YES**                                                                                          |
| Accent color       | `#4FFFB0` mint green                                                      | Active nav items, send button, suggestion chips use mint green     | **YES**                                                                                          |
| Alert color        | `#ff6b35` orange                                                          | Satisfaction "0%" rendered in alert coloring                       | **PARTIAL** -- correctly alert-colored but semantically wrong (0 is not an alert, it is no-data) |
| Typography         | Plus Jakarta Sans + DM Mono                                               | KPI values appear in monospace (DM Mono), labels in sans-serif     | **YES**                                                                                          |
| Sidebar width      | 216px                                                                     | Appears correct                                                    | **YES**                                                                                          |
| Section labels     | 11px, uppercase, letter-spacing, text-faint                               | "OPERATIONS", "INTELLIGENCE", "FINANCE" match spec                 | **YES**                                                                                          |
| Active nav item    | bg-accent-dim, text-accent                                                | Green highlight on active item matches                             | **YES**                                                                                          |
| Role separation    | Platform/Tenant/EndUser never share layout                                | Sidebar.tsx implements three distinct layouts                      | **YES**                                                                                          |
| Filter chips       | Outlined neutral by default                                               | Issue Queue severity/status chips appear as outlined neutral pills | **YES**                                                                                          |
| Chat empty state   | Centered, agent icon, greeting, embedded input, KB hint, suggestion chips | All elements present and positioned correctly                      | **YES**                                                                                          |
| KB hint            | No "RAG" label visible to users                                           | Shows "SharePoint . Google Drive . 2,081 documents indexed"        | **YES**                                                                                          |
| Table headers      | 11px uppercase letter-spacing text-faint                                  | Issue Queue table headers match                                    | **YES**                                                                                          |
| No banned patterns | No purple/blue, no Inter/Roboto, no glassmorphism                         | None observed                                                      | **YES**                                                                                          |

### Design System Verdict

The design system implementation is **strong**. Obsidian Intelligence tokens, typography, spacing, and role-based layouts are faithfully implemented. The visual language is consistent and professional. The problems are not in how things look but in what they contain (nothing).

---

## 5. Critical Blockers (P0 Items for Demo Readiness)

### Blocker 1: Tenants Page Has No Frontend (G-01)

**Impact**: The Platform Admin narrative collapses without this page. "I manage multi-tenant AI workspaces" requires being able to SEE the tenants.

**Fix**: Wire `/settings/tenants` to `GET /api/v1/platform/tenants`. The API already returns all data needed. Render a table with columns: Name, Plan, Status, Created. Add a "New Tenant" button that opens a wizard modal. This is a **DATA** fix (connect existing API to existing page shell).

**Effort Estimate**: 1-2 days for a basic table; 3-5 days for table + detail panel + new tenant wizard.

---

### Blocker 2: LLM Profiles Page Has No Frontend (G-02)

**Impact**: "I configure and govern which AI models my tenants use" is the second-most important Platform Admin story. Without this, the "Intelligence" sidebar section is entirely empty.

**Fix**: Build `/settings/llm-profiles` page showing profile list and a create/edit form with the 6-slot model (primary, intent, embedding, vision, router, worker). Also fix the backend 500 on POST (G-03).

**Effort Estimate**: 3-5 days (frontend + backend fix).

---

### Blocker 3: No Tenant Admin Seed User (G-12)

**Impact**: The entire Tenant Admin persona is undemoable. The code for Users, Knowledge Base, and Glossary pages EXISTS and appears substantial, but no one can see it because you cannot log in as a tenant_admin.

**Fix**: Add a tenant_admin user to the bootstrap seed script. Something like `tenantadmin@mingai.test` / `TenantAdmin1234!` with scope: "tenant", roles: ["tenant_admin"], tenant_id pointing to the default "mingai" tenant.

**Effort Estimate**: 0.5 days.

---

### Blocker 4: LLM Profile Creation Returns 500 (G-03)

**Impact**: Even if the LLM Profiles frontend is built, the backend cannot create profiles. The POST handler crashes.

**Fix**: Debug the 500 error on `POST /api/v1/platform/llm-profiles`. Likely a schema validation or database column mismatch.

**Effort Estimate**: 0.5-1 day.

---

## Value Flow Analysis

### Flow 1: Platform Admin -- "Provision and Monitor a Tenant"

**Steps Traced**:

1. Login (`/login`) -- Action: enter credentials -- Result: JWT issued, redirect to `/settings/dashboard` -- **WORKS**
2. Dashboard (`/settings/dashboard`) -- Action: review KPIs -- Result: All zeros, no insight -- **EMPTY**
3. Tenants (`/settings/tenants`) -- Action: view tenant list -- Result: "Coming in a future phase" -- **BROKEN AT STEP 3**

**Flow Assessment**:

- Completeness: **BROKEN AT STEP 3**
- Narrative coherence: **WEAK** -- The login works, the dashboard gives no information, and the primary destination is a stub
- Evidence of value: **ABSENT**

---

### Flow 2: Platform Admin -- "Configure AI Model Governance"

**Steps Traced**:

1. Navigate to LLM Profiles (`/settings/llm-profiles`) -- Result: "Coming in a future phase" -- **BROKEN AT STEP 1**

**Flow Assessment**:

- Completeness: **BROKEN AT STEP 1**
- Narrative coherence: **N/A**
- Evidence of value: **ABSENT**

---

### Flow 3: Platform Admin -- "Triage User-Reported Issues"

**Steps Traced**:

1. Navigate to Issue Queue (`/settings/issue-queue`) -- Result: Skeleton loading rows that never resolve -- **BROKEN AT STEP 1**

**Flow Assessment**:

- Completeness: **BROKEN AT STEP 1** (loading bug)
- Narrative coherence: **PROMISING** -- the UI structure (severity chips, status filters, table columns) is correct and matches the spec
- Evidence of value: **ABSENT** -- would work if (a) skeleton bug fixed and (b) issues seeded

---

### Flow 4: End User -- "Ask a Question, Get an Answer"

**Steps Traced**:

1. Navigate to Chat (`/chat`) -- Result: Empty state with greeting, mode selector, suggestion chips, KB hint -- **WORKS**
2. Send a question -- Result: **NOT TESTED** (requires live LLM integration)

**Flow Assessment**:

- Completeness: **THEORETICAL** -- Step 1 works beautifully; Step 2 is untestable without LLM
- Narrative coherence: **STRONG** for Step 1
- Evidence of value: **PROMISED but not demonstrated**

---

### Flow 5: Tenant Admin -- "Manage My Workspace"

**Steps Traced**:

1. Login as tenant_admin -- Result: **IMPOSSIBLE** -- no tenant_admin user seeded -- **BROKEN AT STEP 1**

**Flow Assessment**:

- Completeness: **BROKEN AT STEP 1**
- Note: Source code review confirms that Users, Knowledge Base, and Glossary pages have full implementations. This flow is blocked by seed data, not by missing code.

---

## Cross-Cutting Issues

### Cross-Cutting Issue 1: Stub Pages Visible in Navigation

**Severity**: HIGH
**Affected Pages**: /settings/tenants, /settings/llm-profiles, /settings/agent-templates, /settings/tool-catalog, /settings/cost-analytics
**Impact**: 5 of 8 sidebar items lead to "This section is coming in a future phase." In a demo, clicking any of these immediately destroys credibility. The buyer thinks: "This product is 60% vaporware."
**Root Cause**: All sidebar items are hardcoded in Sidebar.tsx with no feature-flag gating.
**Fix Category**: DESIGN -- Either implement the pages or hide unimplemented items behind a feature flag. Alternatively, show a more informative "coming soon" state with an illustration and expected timeline.

---

### Cross-Cutting Issue 2: No Seed Data Anywhere

**Severity**: CRITICAL
**Affected Pages**: Dashboard (all zeros), Issue Queue (empty), Glossary (empty), LLM Profiles (empty), Users (empty)
**Impact**: Every page that does work shows empty state. The product appears hollow even where it is functional.
**Root Cause**: Bootstrap only seeds the platform admin user and initial tenant. No demo data (issues, glossary terms, user accounts, LLM profiles, documents, conversations) is seeded.
**Fix Category**: DATA -- Create a comprehensive seed script that populates: 3-5 tenants with varying plans/statuses, 10-20 users across tenants, 5-10 glossary terms, 5-10 issues at various severities/statuses, 2-3 LLM profiles, fake document index counts, conversation history.

---

### Cross-Cutting Issue 3: Backend 500 Errors on Write Operations

**Severity**: HIGH
**Affected Endpoints**: POST /llm-profiles, POST /issues, GET /tenants/{id}/health, GET /teams/
**Impact**: Core write operations fail. Even if the frontend is built, the forms will submit and crash.
**Root Cause**: Varies per endpoint -- likely schema mismatches, missing database columns, or unhandled null cases.
**Fix Category**: DATA (backend fixes)

---

### Cross-Cutting Issue 4: Role-Specific Content Mismatch

**Severity**: MEDIUM
**Affected Pages**: Dashboard (shows Tenant Admin Quick Actions to Platform Admin)
**Impact**: Quick Actions (Invite Users, Connect Document Store, Deploy Agent) are Tenant Admin operations displayed on the Platform Admin dashboard. Clicking them redirects to /chat because the Platform Admin scope does not grant access to those pages.
**Root Cause**: Dashboard Quick Actions are not role-filtered.
**Fix Category**: DESIGN -- Show Platform Admin-specific quick actions (e.g., "Provision New Tenant", "Configure LLM Models", "Review Issue Queue").

---

## What a Great Demo Would Look Like

A compelling mingai demo walks through three personas in sequence, each building on the last:

**Act 1 -- Platform Admin (3 minutes)**: Login. Dashboard shows 5 active tenants, 12,400 documents indexed, 340 queries today, 94% satisfaction in accent-green. Click "Tenants" -- see a table of 5 tenants with health scores (one at 67% in yellow, four in green). Click into the struggling tenant -- slide-in panel shows their issue count is high and satisfaction is dropping. Navigate to "LLM Profiles" -- see 2 profiles configured (Production and Development), each with 6 model slots filled. Navigate to "Issue Queue" -- see 8 issues, 2 at P1 severity flagged in orange. Click one -- see the AI triage summary, affected tenant, and resolution workflow.

**Act 2 -- Tenant Admin (3 minutes)**: Switch to tenant admin login. Dashboard shows workspace-specific metrics. Navigate to "Documents" -- see SharePoint connected with 2,081 documents, last sync 4 minutes ago, all green. Navigate to "Glossary" -- see 15 domain terms (LTV, KYC, EBITDA, etc.) with usage counts. Add a new term. Navigate to "Users" -- see 23 users across 3 roles.

**Act 3 -- End User (2 minutes)**: Switch to end user login. Chat page shows greeting with suggestion chips. Click "Outstanding invoices" -- watch the AI generate a response citing 3 source documents with relevance scores. See the response formatted cleanly (no card wrapping per design spec). Click a source to see the citation. Give thumbs-up feedback.

**What makes this compelling**: Every click reveals real data. Every number is non-zero. Every navigation leads somewhere meaningful. The story builds: Platform Admin governs -> Tenant Admin configures -> End User gets value.

---

## Severity Table

| Issue                              | ID   | Severity | Impact                                | Fix Category | Effort    |
| ---------------------------------- | ---- | -------- | ------------------------------------- | ------------ | --------- |
| Tenants page is stub (API ready)   | G-01 | **P0**   | Core Platform Admin flow broken       | FRONTEND     | 2-3 days  |
| LLM Profiles page is stub          | G-02 | **P0**   | AI governance story broken            | FRONTEND     | 3-5 days  |
| No tenant_admin seed user          | G-12 | **P0**   | Entire Tenant Admin persona blocked   | DATA         | 0.5 day   |
| LLM Profile POST returns 500       | G-03 | **P0**   | Cannot configure AI models            | BACKEND      | 0.5-1 day |
| Issue creation POST returns 500    | G-04 | **P1**   | Cannot demonstrate issue reporting    | BACKEND      | 0.5-1 day |
| Tenant health GET returns 500      | G-05 | **P1**   | Cannot show tenant monitoring         | BACKEND      | 0.5-1 day |
| Teams GET returns 500              | G-06 | **P1**   | Teams feature broken                  | BACKEND      | 0.5-1 day |
| Issue Queue infinite skeleton      | G-07 | **P1**   | Issue Queue appears broken            | FRONTEND     | 0.5 day   |
| Dashboard KPIs all zero            | G-10 | **P1**   | Dashboard provides no insight         | DATA         | 1-2 days  |
| Dashboard Quick Actions wrong role | G-11 | **P1**   | Quick Actions mislead Platform Admin  | FRONTEND     | 0.5 day   |
| 5 stub sidebar pages visible       | G-14 | **P1**   | 60% of navigation leads to dead ends  | DESIGN       | 1 day     |
| Analytics redirects to /chat       | G-15 | **P1**   | Intelligence section partially broken | FRONTEND     | 2-3 days  |
| Chat RAG untested                  | G-18 | **P1**   | Core value proposition unverified     | INTEGRATION  | 2-5 days  |
| Satisfaction 0% shows as alert     | G-13 | **P2**   | Misleading metric presentation        | FRONTEND     | 0.25 day  |
| No /ready endpoint                 | G-08 | **P2**   | K8s readiness probe missing           | BACKEND      | 0.25 day  |
| Cost analytics API missing         | G-09 | **P2**   | Finance section empty                 | BACKEND      | 2-3 days  |
| Agents page not implemented        | G-16 | **P2**   | Tenant Admin agent management missing | FRONTEND     | 3-5 days  |
| Empty glossary (no seed)           | G-17 | **P2**   | Glossary feature looks unused         | DATA         | 0.5 day   |

---

## Bottom Line

If I saw this demo today, I would tell my board: "The team has a clear architectural vision -- three-role governance model, dark-first design system, slot-based LLM configuration -- and the design execution is genuinely professional. But the product is at about 25% demo-readiness. The chat interface is polished, the sidebar structure is exactly right, and the design system is faithfully implemented. However, the Platform Admin cannot manage tenants, configure models, or review issues -- the three things a Platform Admin exists to do. The Tenant Admin persona cannot be demonstrated at all. And every page that does render shows zero data. I would revisit in 2-3 weeks after they (1) wire the Tenants and LLM Profiles frontend to their existing APIs, (2) seed a demo dataset, (3) fix the 4 backend 500 errors, and (4) create a tenant_admin login. Those four items would take the demo from 'interesting architecture' to 'compelling product.'"

---

## Files Referenced

- **Sidebar implementation**: `/Users/cheongwailuen/Development/mingai/src/web/components/layout/Sidebar.tsx`
- **Knowledge Base page (Tenant Admin, implemented)**: `/Users/cheongwailuen/Development/mingai/src/web/app/settings/knowledge-base/page.tsx`
- **Users page (Tenant Admin, implemented)**: `/Users/cheongwailuen/Development/mingai/src/web/app/settings/users/page.tsx`
- **Glossary page (Tenant Admin, implemented)**: `/Users/cheongwailuen/Development/mingai/src/web/app/settings/glossary/page.tsx`
- **Issue Queue page**: `/Users/cheongwailuen/Development/mingai/src/web/app/settings/issue-queue/page.tsx`
- **Bootstrap seed script**: `/Users/cheongwailuen/Development/mingai/src/backend/app/core/bootstrap.py`
- **Auth routes**: `/Users/cheongwailuen/Development/mingai/src/backend/app/modules/auth/routes.py`
- **Design system spec**: `/Users/cheongwailuen/Development/mingai/.claude/rules/design-system.md`
- **Platform Admin user flows**: `/Users/cheongwailuen/Development/mingai/workspaces/mingai/03-user-flows/01-platform-admin-flows.md`
- **Tenant Admin user flows**: `/Users/cheongwailuen/Development/mingai/workspaces/mingai/03-user-flows/12-tenant-admin-flows.md`
- **End User flows**: `/Users/cheongwailuen/Development/mingai/workspaces/mingai/03-user-flows/03-end-user-flows.md`
- **Issue reporting flows**: `/Users/cheongwailuen/Development/mingai/workspaces/mingai/03-user-flows/10-issue-reporting-flows.md`
- **Glossary flows**: `/Users/cheongwailuen/Development/mingai/workspaces/mingai/03-user-flows/08-glossary-flows.md`
- **Screenshots captured**: `/tmp/settings-dashboard.png`, `/tmp/settings-tenants.png`, `/tmp/settings-issue-queue.png`, `/tmp/settings-llm-profiles.png`, `/tmp/settings-cost-analytics.png`, `/tmp/chat.png`
