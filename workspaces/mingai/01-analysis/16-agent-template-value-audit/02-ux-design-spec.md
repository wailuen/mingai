# Agent Template Capability Configuration -- UX Design Spec

> **Status**: Design Specification
> **Date**: 2026-03-21
> **Design System**: Obsidian Intelligence (dark-first, `--accent: #4FFFB0`, Plus Jakarta Sans + DM Mono)
> **Depends on**: `33-agent-library-studio-architecture.md`, `18-a2a-agent-architecture.md`, prototype `99-ui-proto/index.html`
> **Roles covered**: Platform Admin (template authoring, tool catalog), Tenant Admin (agent deploy, agent card)

---

## 1. Executive Summary

Four screens require capability configuration UX that the current prototype lacks:

| Screen                     | Role           | Gap                                                                | Priority |
| -------------------------- | -------------- | ------------------------------------------------------------------ | -------- |
| Template Authoring         | Platform Admin | Missing: credential schema, auth_mode, plan gate, tool assignments | P0       |
| Agent Deploy Form          | Tenant Admin   | Missing: credential entry, tool enablement, rate limits            | P0       |
| Agent Card (deployed)      | Tenant Admin   | Missing: KB/tool badges, credential health, version upgrade        | P1       |
| Tool Catalog -- Assignment | Platform Admin | Missing: template assignment workflow, per-tenant control, health  | P1       |

All designs follow the existing panel architecture: Platform Admin uses `showPAPanel()` with slide-in detail panels for drill-down and wizard modals for multi-step creation. Tenant Admin uses `showTAPanel()` with `ta-panel-{name}` naming.

---

## 2. Platform Admin -- Template Authoring (Slide-In Detail Panel)

### 2.1 Entry Point

The existing `pa-panel-templates` table has an "Edit" row action. Clicking it opens a **slide-in detail panel from the right** (consistent with PA drill-down pattern). The "+ New Template" button opens the same panel in create mode.

### 2.2 Information Architecture

The slide-in panel is divided into collapsible sections, ordered by authoring workflow priority:

```
+------------------------------------------------------------+
| x  Edit Template: Bloomberg Intelligence Agent             |
|    Draft / Published                     [Save Draft] [Pub] |
+------------------------------------------------------------+
| SECTION 1: IDENTITY                                    [-] |
|   Name ________________________________________            |
|   Description __________________________________           |
|   Category  [dropdown: Financial Data v]                   |
|   Icon      [icon picker grid, 6 options]                  |
+------------------------------------------------------------+
| SECTION 2: SYSTEM PROMPT                               [-] |
|   [textarea, monospace, 12 lines]                          |
|   Variables: {{tenant_context}}  [+ Add Variable]          |
|   Required variables: (none)                               |
|   Optional variables: tenant_context                       |
|   Character count: 847 / 2,000          DM Mono 11px       |
+------------------------------------------------------------+
| SECTION 3: AUTHENTICATION                              [-] |
|   Auth Mode:  ( ) None                                     |
|               (*) Tenant Credentials                       |
|               ( ) Platform Credentials                     |
|                                                            |
|   Required Credentials Schema:                             |
|   +------------------------------------------------------+ |
|   | Key              | Label           | Type | Sensitive | |
|   | bloomberg_cli... | Bloomberg BSS.. | str  | No        | |
|   | bloomberg_sec... | Bloomberg BSS.. | str  | Yes       | |
|   +------------------------------------------------------+ |
|   [+ Add Credential Field]                                 |
+------------------------------------------------------------+
| SECTION 4: PLAN & ACCESS GATE                          [-] |
|   Plan Required: [dropdown: None / Starter / Pro / Ent]    |
|   Capabilities:  [chip input: market_data, earnings, ...]  |
|   Cannot Do:     [chip input: historical > 10yr, ...]      |
+------------------------------------------------------------+
| SECTION 5: TOOL ASSIGNMENTS                            [-] |
|   Assigned tools (2 of 8 available):                       |
|   +------------------------------------------------------+ |
|   | [x] Jira Issue Reader       Read-Only   Healthy      | |
|   | [x] Bloomberg Data Feed     Read-Only   Degraded (!) | |
|   | [ ] Slack Notifier          Write                    | |
|   | [ ] Salesforce CRM Reader   Read-Only                | |
|   +------------------------------------------------------+ |
|   Info: Tools must be registered in Tool Catalog first.    |
+------------------------------------------------------------+
| SECTION 6: GUARDRAILS                                  [-] |
|   Max Output Tokens: [____]                                |
|   Confidence Threshold: [____]                             |
|   Citation Mode: [Required / Optional / None]              |
|   Avg Latency (ms): [____]  (displayed to tenants)         |
+------------------------------------------------------------+
| SECTION 7: VERSION HISTORY                             [-] |
|   v2.1.0  2026-03-01  Added FX historical queries          |
|   v2.0.0  2026-01-15  OAuth2 BSSO migration                |
|   v1.0.0  2025-11-01  Initial release                      |
|   [+ Publish New Version]                                  |
+------------------------------------------------------------+
| DANGER ZONE                                                |
|   [Deprecate Template]  --alert color, visually separated  |
+------------------------------------------------------------+
```

### 2.3 Section Details

**Section 3 -- Authentication** (new)

- `auth_mode` is a radio group, not a dropdown. Three states are mutually exclusive and the choice has significant downstream implications (tenant sees credential form vs not). Radio makes the choice explicit.
- When `auth_mode = none`: credential schema table is hidden entirely.
- When `auth_mode = tenant_credentials`: credential schema table is shown. Each row defines a credential field the tenant must fill during adoption.
- When `auth_mode = platform_credentials`: credential schema is hidden; a note reads "Credentials managed by platform operations team."
- Credential field editor per row: `key` (slug, auto-generated from label), `label` (human-readable), `description` (help text shown to tenant), `type` (string | url | oauth2), `sensitive` (boolean toggle -- sensitive fields are masked in tenant UI and stored encrypted).
- The `+ Add Credential Field` button appends a new row inline. No modal.

**Section 5 -- Tool Assignments** (new)

- Checkbox list of all tools from the Tool Catalog. Each row shows: tool name, classification badge (Read-Only = accent dot, Write = warn lightning, Execute = alert triangle), and health status.
- Tools with degraded health show a warn-colored "(degraded)" label. The platform admin can still assign degraded tools but the UI communicates the risk.
- Tool assignment is per-template, not per-tenant. Tenants can enable/disable assigned tools at the instance level (see Section 3 below).

**Section 4 -- Plan & Access Gate** (new)

- `plan_required` dropdown: `null` (any plan), Starter, Professional, Enterprise. Tenants on a lower plan see the template in the catalog but with a locked state and upgrade prompt.
- Capabilities and Cannot Do are chip inputs (type and press Enter). These are informational metadata shown to tenants during adoption -- not enforced programmatically.

### 2.4 State Transitions

```
[Create] --> Draft --> [Publish] --> Published --> [New Version] --> Published (v+1)
                                        |
                                  [Deprecate] --> Deprecated
                                                    |
                                              (existing instances
                                               continue running;
                                               no new adoptions)
```

- Draft: only visible to platform admins. "Publish" button is primary CTA (accent green, top-right).
- Published: "Save" updates the current version in-place for non-breaking changes (description, icon). "Publish New Version" creates a new semver entry and triggers tenant notifications.
- Deprecated: grayed-out row in the template table. Badge: `status-suspended` style (existing in prototype). No "Edit" action, only "View" and "Restore."

### 2.5 Validation Rules

| Field           | Rule                                | Error Display                          |
| --------------- | ----------------------------------- | -------------------------------------- |
| Name            | Required, 3-80 chars                | Inline under field, alert color        |
| System Prompt   | Required, max 2000 chars            | Character counter turns alert at 1800+ |
| Credential Key  | Slug format, unique within template | Inline, auto-corrects non-slug chars   |
| Plan Required   | Valid enum                          | Dropdown enforces                      |
| Tool Assignment | At least 0 (optional)               | Info note, not error                   |

---

## 3. Tenant Admin -- Agent Deploy Form (Wizard Modal)

### 3.1 Entry Point

Two paths to this form:

1. **Agent Library**: Tenant admin clicks "Adopt" on a catalog template card. Opens the deploy wizard.
2. **Agent Studio**: Tenant admin clicks "+ Custom Agent" on `ta-panel-agents`. Opens Agent Studio (already exists in prototype). This spec extends it.

The deploy wizard uses the **wizard / step modal** pattern: `max-width: 640px`, `border-radius: var(--r-lg)`, progress bar at top with accent fill, "Step N of M" label, footer with Back (ghost) + Next (primary) + close X.

### 3.2 Wizard Steps

**Step 1 of 4: Identity & Context** (exists partially)

```
+----------------------------------------------------------+
| [====-------]  Step 1 of 4 -- Identity & Context         |
+----------------------------------------------------------+
|                                                          |
|  Adopting: Bloomberg Intelligence Agent                  |
|  Template v2.1.0 -- Financial Data                       |
|                                                          |
|  Display Name                                            |
|  [Bloomberg Intelligence_____________]                   |
|  (pre-filled from template, editable)                    |
|                                                          |
|  Tenant Context (optional)                               |
|  [Acme Capital focuses on APAC equities and US           |
|   investment-grade bonds.___________________________]    |
|                                                          |
|  Info: This context is injected into the agent's         |
|  system prompt to personalize responses for your org.    |
|                                                          |
+----------------------------------------------------------+
|  [Cancel]                               [Next: Auth -->] |
+----------------------------------------------------------+
```

- Variable fields are generated dynamically from `template.variables.required` and `template.variables.optional`. Required variables show a red asterisk. Optional variables show "(optional)" label.
- If the template has no variables, this step collapses to just the display name field and the wizard shows "Step 1 of 3."

**Step 2 of 4: Credentials** (new -- only shown when `auth_mode = tenant_credentials`)

```
+----------------------------------------------------------+
| [========----]  Step 2 of 4 -- Connect Credentials       |
+----------------------------------------------------------+
|                                                          |
|  Bloomberg requires your organization's API              |
|  credentials to access market data.                      |
|                                                          |
|  Bloomberg BSSO Client ID                                |
|  [________________________________]                      |
|  From your Bloomberg BSSO application registration       |
|                                                          |
|  Bloomberg BSSO Client Secret                            |
|  [********________________________]   [Show/Hide]        |
|                                                          |
|  [Test Connection]                                       |
|                                                          |
|  (idle state: button outlined, neutral)                  |
|  (testing: spinner + "Validating...")                    |
|  (passed: accent check + "Connected: acme@bloomberg")    |
|  (failed: alert X + error message + "Retry")            |
|  (untested: warn -- "No test available; stored as-is")   |
|                                                          |
+----------------------------------------------------------+
|  [<-- Back]                       [Next: Access -->]     |
+----------------------------------------------------------+
```

- When `auth_mode = none` or `platform_credentials`, this step is skipped entirely. The wizard adjusts step count and progress bar.
- Sensitive fields (`sensitive: true`) render as password inputs with a show/hide toggle.
- "Test Connection" calls the credential test endpoint asynchronously. The button transitions through four states: idle, testing (spinner), passed (accent), failed (alert). The test is optional -- the tenant can proceed without testing, but the wizard shows a warn-colored note: "Credentials not validated. The agent may fail if credentials are incorrect."
- Credential values are never returned to the browser after save. On subsequent edits, fields show "[encrypted]" placeholder with a "Replace" action.

**Step 3 of 4: Knowledge Bases & Tools** (extends existing KB selector)

```
+----------------------------------------------------------+
| [============-]  Step 3 of 4 -- Knowledge & Tools        |
+----------------------------------------------------------+
|                                                          |
|  KNOWLEDGE BASES                                         |
|  Select the document sources this agent can query.       |
|                                                          |
|  [x] Procurement Policies                                |
|      SharePoint / Finance Portal    1,204 docs           |
|  [x] Vendor Contracts                                    |
|      SharePoint / Legal             342 docs             |
|  [ ] HR Policies                                         |
|      SharePoint / HR                891 docs             |
|                                                          |
|  Search Mode: (*) Parallel  ( ) Priority Order           |
|  Info: Users must have KB access to see results.         |
|                                                          |
|  -----------------------------------------------         |
|                                                          |
|  TOOLS                                                   |
|  Enable MCP tools assigned to this template.             |
|                                                          |
|  [x] Jira Issue Reader     Read-Only   Healthy           |
|  [ ] Bloomberg Data Feed   Read-Only   Degraded (!)      |
|                                                          |
|  (only tools assigned to this template by platform       |
|   admin appear here)                                     |
|                                                          |
+----------------------------------------------------------+
|  [<-- Back]                      [Next: Limits -->]      |
+----------------------------------------------------------+
```

- KB selector already exists in prototype. This spec adds: document count badge in DM Mono after each KB name, and a search mode radio below the list.
- Tool enablement is new. Only tools that the platform admin assigned to this template (Section 2, step 5) appear here. Each tool shows its classification badge and health status. Degraded tools show a warn note.
- If the template has zero assigned tools, the Tools subsection is hidden entirely.
- If the tenant has no synced KBs, the KB section shows an empty state: "No knowledge bases configured. [Go to Documents]" linking to `showTAPanel('documents')`.

**Step 4 of 4: Access & Limits** (extends existing access control)

```
+----------------------------------------------------------+
| [================]  Step 4 of 4 -- Access & Limits       |
+----------------------------------------------------------+
|                                                          |
|  ACCESS CONTROL                                          |
|  Who can use this agent?                                 |
|                                                          |
|  (*) All workspace users                                 |
|  ( ) Specific roles:  [Analyst] [Executive] [+ Add]      |
|  ( ) Specific users:  [search and add users]             |
|                                                          |
|  -----------------------------------------------         |
|                                                          |
|  RATE LIMITS                                             |
|  Queries per user per day                                |
|  [50___]   Platform max: 200    DM Mono                  |
|                                                          |
|  -----------------------------------------------         |
|                                                          |
|  GUARDRAILS (for custom agents only)                     |
|  Confidence Threshold: [0.65]                            |
|  Citation Mode: [Required v]                             |
|  Max Output Tokens: [1500]                               |
|                                                          |
+----------------------------------------------------------+
|  [<-- Back]                          [Deploy Agent]      |
+----------------------------------------------------------+
```

- The final step CTA changes from "Next" to "Deploy Agent" (accent green, primary button).
- Rate limit field: DM Mono input. If the tenant enters a value exceeding the platform maximum (from their plan), the field shows an inline error: "Exceeds your plan limit of 200/day."
- Guardrails section: shown only for Agent Studio (custom) agents. For library-adopted agents, guardrails are platform-defined and immutable -- show them as read-only with a note: "Guardrails are managed by the platform template."
- Access control already exists in prototype. This spec adds the rate limit and guardrail sections.

### 3.3 Wizard Step Adaptation

The wizard dynamically adjusts based on template properties:

| Template Property                 | Step Count | Skipped Steps                                   |
| --------------------------------- | ---------- | ----------------------------------------------- |
| `auth_mode: none`, no variables   | 2 steps    | Identity context collapsed, credentials skipped |
| `auth_mode: none`, has variables  | 3 steps    | Credentials skipped                             |
| `auth_mode: tenant_credentials`   | 4 steps    | None                                            |
| `auth_mode: platform_credentials` | 3 steps    | Credentials skipped                             |

Progress bar and "Step N of M" update accordingly.

### 3.4 Edge Cases

**No KBs available**: Empty state in Step 3 KB section. CTA links to Documents panel. The wizard allows proceeding without KBs (some agents like Bloomberg fetch real-time data).

**Credential test fails**: Alert-colored error message below the test button. The tenant can retry, fix the value, or skip. If they skip, the instance is created with `status: pending_validation` and the agent card shows a warn state.

**Plan gate blocks adoption**: The catalog shows a locked state on the template card: "Requires Professional plan. [Contact Admin]". The "Adopt" button is disabled (`--text-faint` color, no hover effect).

**All tools degraded**: Warn-colored banner above the tool list: "Some tools are experiencing issues. The agent may have limited capabilities."

---

## 4. Tenant Admin -- Agent Card (Enhanced)

### 4.1 Current State (Prototype)

The `agent-card-ta` in `ta-panel-agents` currently shows: icon, name, template version, KB source label, satisfaction bar, rated response count, trend, and three actions (Analytics, Configure, Test Chat).

### 4.2 New Elements

```
+----------------------------------------------------------+
| [icon]  Finance Analyst                                  |
|         Template v3 -- Deployed Jan 2026                 |
|         [v3.1 available -->]  (accent, only when update) |
|                                                          |
|  [2 KBs]  [1 tool]  [creds: OK]                         |
|  ^^badges in DM Mono, 11px, outlined chips               |
|                                                          |
|  Finance Documents -- SharePoint                         |
|                                                          |
|  [=============================-------]  74%             |
|  156 rated responses       -5% this week                 |
|                                                          |
|  [Analytics]  [Configure]  [Test Chat]                   |
+----------------------------------------------------------+
```

**New badge row** (between header and KB label):

| Badge             | Display              | Condition                                   | Style                                                                             |
| ----------------- | -------------------- | ------------------------------------------- | --------------------------------------------------------------------------------- |
| KB count          | `2 KBs`              | Always shown                                | DM Mono 11px, `--bg-elevated` background, `--border` outline, `--text-muted` text |
| Tool count        | `1 tool`             | Only when tools > 0                         | Same chip style                                                                   |
| Credential health | `creds: OK`          | Only when `auth_mode != none`               | OK = accent text. Failed = alert text + alert border. Untested = warn text        |
| Version upgrade   | `v3.1 available -->` | Only when `template_update_available: true` | Accent text, 12px, clickable. Opens version review inline or slide-in             |

**Credential health indicator states**:

| State                       | Visual                                                  | Copy                |
| --------------------------- | ------------------------------------------------------- | ------------------- |
| Passed (daily check OK)     | `--accent` text, accent-dim background                  | `creds: OK`         |
| Failed (daily check failed) | `--alert` text, alert-dim background, alert-ring border | `creds: FAILED`     |
| Untested (no test class)    | `--warn` text, warn-dim background                      | `creds: unverified` |
| Not applicable              | Badge hidden                                            | (auth_mode = none)  |

**Version upgrade prompt**: When `template_update_available: true`, a clickable accent-colored line appears below the version label. Clicking opens a **compact inline expansion** (not a modal) showing:

```
+----------------------------------------------------------+
| v3.1.0 available -- What's new:                          |
| Added commodity futures support and FX pair lookups.     |
|                                                          |
| [Review Changes]  [Dismiss]                              |
+----------------------------------------------------------+
```

"Review Changes" opens a diff-style view (old prompt vs new prompt) in a slide-in panel. "Accept Update" re-resolves the system prompt with the tenant's existing variables. "Dismiss" hides the prompt for this version (can be re-accessed from Configure).

### 4.3 Agent Card Alert State (Enhanced)

The existing alert state (Procurement Assistant in prototype) wraps the card with `border-color: var(--alert-ring)` and shows a banner. This spec adds credential failure as a trigger:

| Alert Trigger        | Banner Text                                           | Banner Color |
| -------------------- | ----------------------------------------------------- | ------------ |
| KB stale > 30 days   | "KB stale {N} days -- satisfaction dropped {N}%"      | `--alert`    |
| Credential failure   | "Credentials expired -- agent cannot access {source}" | `--alert`    |
| Satisfaction < 70%   | "Satisfaction below threshold"                        | `--warn`     |
| Tool health degraded | "1 tool degraded -- {tool name}"                      | `--warn`     |

Multiple alerts stack vertically within the banner area (max 2 visible, "+N more" overflow).

---

## 5. Platform Admin -- Tool Catalog Enhancement

### 5.1 Current State (Prototype)

`pa-panel-tools` shows a table with: Tool, Provider, Classification, Plans Available, Health, Tenants count, and Manage action.

### 5.2 "Manage" Slide-In Detail Panel

Clicking "Manage" on a tool row opens a slide-in detail panel (consistent with PA drill-down pattern):

```
+------------------------------------------------------------+
| x  Jira Issue Reader                                       |
|    [Read-Only]  [Healthy]                                  |
+------------------------------------------------------------+
| IDENTITY                                                   |
|   Provider: Atlassian                                      |
|   MCP Endpoint: jira-mcp.internal:9001    DM Mono          |
|   Classification: Read-Only                                |
|   Plans: Professional, Enterprise                          |
+------------------------------------------------------------+
| TEMPLATE ASSIGNMENTS                                   [+] |
|                                                            |
|   Assigned to 3 templates:                                 |
|   +------------------------------------------------------+ |
|   |  IT Helpdesk           Published   11 tenants  [ x ] | |
|   |  Customer Support      Published   18 tenants  [ x ] | |
|   |  Financial Analyst     Published    8 tenants  [ x ] | |
|   +------------------------------------------------------+ |
|                                                            |
|   [+ Assign to Template]  (opens template picker)          |
+------------------------------------------------------------+
| TENANT ENABLEMENT                                          |
|                                                            |
|   4 tenants have this tool enabled:                        |
|   +------------------------------------------------------+ |
|   | Acme Capital       via IT Helpdesk     [Enabled v]   | |
|   | GlobalFin Corp     via Customer Supp   [Enabled v]   | |
|   | TechStart Inc      via Financial Ana   [Enabled v]   | |
|   | MegaCorp           via IT Helpdesk     [Disabled]    | |
|   +------------------------------------------------------+ |
|                                                            |
|   Note: Tenant admins control enable/disable per agent.    |
|   Platform can override to force-disable.                  |
+------------------------------------------------------------+
| HEALTH                                                     |
|   Status: Healthy                        DM Mono accent    |
|   Last check: 2 min ago                  DM Mono faint     |
|   Avg latency: 340ms                     DM Mono           |
|   Error rate (24h): 0.2%                 DM Mono           |
|   Uptime (30d): 99.7%                    DM Mono           |
+------------------------------------------------------------+
| DANGER ZONE                                                |
|   [Force Disable All Tenants]  --alert                     |
|   [Remove Tool]                --alert                     |
+------------------------------------------------------------+
```

### 5.3 Tool-to-Template Assignment Workflow

**Assign from Template side** (Section 2.2, step 5): Platform admin checks tools in the template authoring panel. This is the primary path -- designing the template and selecting which tools it needs.

**Assign from Tool side** (this section): Platform admin clicks "[+ Assign to Template]" in the tool detail panel. Opens a **picker dropdown** (not a modal -- it is a single selection):

```
+--------------------------------------+
| Search templates...                  |
| +----------------------------------+ |
| | HR Policy Assistant    Published | |
| | Legal Doc Reviewer     Draft     | |
| | Procurement Assistant  Published | |
| +----------------------------------+ |
+--------------------------------------+
```

Selecting a template immediately adds the assignment (no confirmation step -- it is a non-destructive action). The template row appears in the assignment list. A toast confirms: "Jira Issue Reader assigned to HR Policy Assistant."

**Remove assignment**: The [x] button on each template row in the assignment list. If tenants have active instances using this tool through this template, a confirmation dialog warns: "3 tenant instances use this tool through IT Helpdesk. Removing will disable the tool for those agents. [Remove Anyway] [Cancel]."

### 5.4 Per-Tenant Enable/Disable

The Tenant Enablement section in the tool detail panel shows a read-only view of which tenants have the tool enabled through their agent instances. Platform admin can force-disable a tool for a specific tenant (overriding the tenant admin's choice) using the dropdown: `[Enabled]` / `[Force Disabled]`.

Force-disable is a platform-level override. It shows in the tenant admin's agent configure view as: "This tool has been disabled by platform administration" with the tool row grayed out and unclickable.

### 5.5 Tool Health States

| State    | Color          | Indicator        | Meaning                                             |
| -------- | -------------- | ---------------- | --------------------------------------------------- |
| Healthy  | `--accent`     | Filled dot       | Endpoint responding, error rate < 1%, latency < SLA |
| Degraded | `--warn`       | Warning triangle | Error rate 1-5% or latency > 2x SLA                 |
| Down     | `--alert`      | Filled dot       | Endpoint unreachable or error rate > 5%             |
| Unknown  | `--text-faint` | Dash             | No health check configured                          |

Health data displayed in DM Mono throughout. Health check runs every 5 minutes (platform-side cron). When a tool transitions from Healthy to Degraded or Down, an entry is added to the Platform Admin Issue Queue.

### 5.6 "+ Add Tool" Registration Wizard

The existing "+ Add Tool" button opens a wizard modal (consistent with PA multi-step pattern):

**Step 1**: Identity (name, provider, description, classification)
**Step 2**: Connection (MCP endpoint URL, authentication method, health check endpoint)
**Step 3**: Access (plan availability, initial template assignments)

Three steps, same wizard chrome as the tenant deploy wizard.

---

## 6. State Transition Map (Agent Instance Lifecycle)

```
                    Tenant Admin Actions
                    ====================

  [Adopt Template]          [Create in Studio]
        |                         |
        v                         v
  +-- configured --+      +---- draft -----+
  | (credentials   |      | (editing in    |
  |  validated)    |      |  studio)       |
  +-------+--------+      +------+---------+
          |                       |
          | [Deploy]              | [Publish]
          v                       v
  +------------ active ----------------------+
  |  Normal operation. Users can query.      |
  |  Daily credential health check runs.     |
  +--+-----------+-----------+-------+-------+
     |           |           |       |
     | creds     | template  | admin | admin
     | fail      | update    | pause | archive
     v           v           v       v
  +-------+  +--------+  +------+ +--------+
  | cred  |  | update |  |paused| |archived|
  | warn  |  | avail  |  |      | |(soft   |
  | (still|  | (still |  |      | | delete)|
  |active)|  | active)|  +------+ +--------+
  +---+---+  +---+----+
      |          |
      | fix      | accept/dismiss
      | creds    | update
      v          v
    active     active (new version)
```

Key transitions:

| From                  | To                    | Trigger                                 | User Action                             |
| --------------------- | --------------------- | --------------------------------------- | --------------------------------------- |
| (none)                | configured            | Adopt template, fill credentials        | Complete wizard steps 1-2               |
| configured            | active                | Deploy (step 4 complete)                | Click "Deploy Agent"                    |
| (none)                | draft                 | Create in studio                        | Click "+ Custom Agent"                  |
| draft                 | active                | Publish                                 | Click "Publish" in studio               |
| active                | active (cred warn)    | Daily health check fails                | Automatic -- admin notified             |
| active (cred warn)    | active                | Admin updates credentials               | Click "Update Credentials" in configure |
| active                | active (update avail) | Platform publishes new template version | Automatic -- admin notified             |
| active (update avail) | active                | Admin accepts or dismisses update       | Click "Accept Update" or "Dismiss"      |
| active                | paused                | Admin pauses agent                      | Click "Pause" in configure              |
| paused                | active                | Admin resumes agent                     | Click "Resume"                          |
| active                | archived              | Admin archives agent                    | Click "Archive" (soft delete)           |

---

## 7. Interaction Specifications

### 7.1 Credential Entry Flow

1. Tenant admin reaches Step 2 of deploy wizard.
2. Fields are rendered dynamically from `template.required_credentials` array.
3. Each field uses `<input type="text">` or `<input type="password">` based on `sensitive` flag.
4. Sensitive fields have a show/hide eye icon toggle (right-aligned inside the input, consistent with password field patterns).
5. "Test Connection" button calls `POST /api/v1/admin/agents/test-credentials` asynchronously.
6. During test: button shows spinner, inputs are disabled.
7. On success: accent-colored success state with masked account info (e.g., "Connected: acme@bloomberg.com"). "Next" button becomes enabled.
8. On failure: alert-colored error message. Inputs re-enable for correction. "Next" button remains enabled (testing is optional) but shows a warn note.
9. On untested (no test class): warn-colored note permanently visible. No test button shown.
10. On subsequent edits (configure existing agent): fields show "[encrypted]" and a "Replace" link. Clicking "Replace" clears the field for new input. Unchanged fields are not re-sent to the server.

### 7.2 KB Binding Interaction

1. Checkbox list rendered from tenant's synced document sources.
2. Each item shows: checkbox, KB name (Plus Jakarta Sans 13px/500), source path (11px faint), document count (DM Mono 11px).
3. Checking a KB adds it to `kb_bindings` array immediately (no save needed -- wizard collects all state on final submit).
4. If template has `recommended_kb_categories`, matching KBs show a subtle accent dot indicator and sort to the top of the list.
5. Empty state: illustration-free message. "No knowledge bases synced. Go to Documents to connect a data source." with accent-colored link.

### 7.3 Tool Assignment Interaction (Platform Admin)

1. Checkbox list in template authoring panel (Section 2.2, step 5).
2. Each tool row shows: checkbox, tool name, classification badge (colored dot + label), health status.
3. Checking a tool assigns it to the template immediately on save.
4. If the tool is unhealthy (Degraded/Down), the row still allows assignment but shows a warn-colored health label.
5. Assignment persists across template versions -- new versions inherit the tool assignments of the previous version.

### 7.4 Tool Enablement Interaction (Tenant Admin)

1. In deploy wizard Step 3, tools appear below the KB section.
2. Only tools assigned to the adopted template appear (tenant cannot add tools not in the template).
3. Toggle-style checkboxes. Each row: checkbox, tool name, classification badge, health status.
4. Disabled tools (force-disabled by platform) show as grayed-out with explanatory text.
5. In the agent configure view (post-deploy), tools can be toggled on/off without redeploying.

---

## 8. Empty States and Error States

### 8.1 Empty States

| Context                              | Message                                       | CTA                                                     |
| ------------------------------------ | --------------------------------------------- | ------------------------------------------------------- |
| No templates in catalog              | "No agent templates available for your plan." | "Contact your platform administrator" (text, no button) |
| No KBs synced                        | "No knowledge bases configured."              | "[Go to Documents]" accent link                         |
| No tools assigned to template        | Tools section hidden entirely                 | N/A                                                     |
| No deployed agents                   | "Deploy your first agent to get started."     | "[Browse Library]" primary button                       |
| No credential fields on template     | Authentication section hidden in wizard       | N/A                                                     |
| Version history empty (new template) | "No versions published yet."                  | "[Publish]" primary button                              |

### 8.2 Error States

| Error                            | Display                                            | Recovery                          |
| -------------------------------- | -------------------------------------------------- | --------------------------------- |
| Credential test failure          | Alert banner in wizard step 2 with error message   | "Retry" button or fix input       |
| Credential daily check failure   | Alert banner on agent card + badge `creds: FAILED` | "Update Credentials" in configure |
| Tool health degraded             | Warn label on tool row + card badge                | No tenant action -- platform-side |
| Tool force-disabled by platform  | Gray row + explanatory text                        | Contact platform admin            |
| Plan gate blocks template        | Locked card in catalog + upgrade prompt            | Contact billing admin             |
| System prompt validation failure | Inline error under textarea in studio              | Fix blocked pattern               |
| Rate limit exceeds plan max      | Inline error under rate limit input                | Lower the value                   |

### 8.3 Loading States

- Credential test: spinner in button, inputs disabled, "Validating credentials..." text.
- KB list: skeleton rows (3 shimmer lines, 14px height, staggered widths).
- Tool list: skeleton rows (same pattern).
- Agent deploy: full-screen overlay with spinner and "Deploying agent..." on the final wizard step. Auto-closes on success with toast: "Bloomberg Intelligence deployed successfully."

---

## 9. Typography and Data Formatting Rules

Per design system, all data values use DM Mono:

| Data Element            | Font    | Size   | Example                      |
| ----------------------- | ------- | ------ | ---------------------------- |
| Document count          | DM Mono | 11px   | `1,204 docs`                 |
| Version number          | DM Mono | 12px   | `v2.1.0`                     |
| Satisfaction score      | DM Mono | varies | `74%` (card) / `89%` (table) |
| Rate limit value        | DM Mono | 13px   | `50 / day`                   |
| Credential test latency | DM Mono | 11px   | `340ms`                      |
| Tool error rate         | DM Mono | 12px   | `0.2%`                       |
| Uptime percentage       | DM Mono | 12px   | `99.7%`                      |
| Tenant count            | DM Mono | 12px   | `18`                         |

Labels, names, descriptions, and navigation use Plus Jakarta Sans exclusively.

---

## 10. Responsive Considerations

All four screens follow the existing admin layout: fixed sidebar (`--sidebar-w: 216px`) + scrollable content area. Content area minimum width: `640px`. Below that, sidebar collapses to icon-only mode (existing prototype behavior).

- Wizard modal: `max-width: 640px`, centered. On narrow screens (< 768px), modal goes full-width with `16px` side padding.
- Slide-in panel: `width: 480px` default, `max-width: 50vw`. On narrow screens, overlays the full content area.
- Agent card grid: existing `grid-template-columns: repeat(2, 1fr)` collapses to single column below `900px` content width.

---

**Document Version**: 1.0
**Last Updated**: 2026-03-21
