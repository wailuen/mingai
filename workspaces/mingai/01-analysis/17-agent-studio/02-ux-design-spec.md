# Agent Studio -- UX Design Specification

> **Status**: Design Specification
> **Date**: 2026-03-21
> **Design System**: Obsidian Intelligence (dark-first)
> **Source Documents**: `23-agent-template-flows.md`, `33-agent-library-studio-architecture.md`, `18-a2a-agent-architecture.md`, `50-agent-template-requirements.md`
> **Supersedes**: Current `TemplateAuthoringForm.tsx` (560px slide-in panel with flat field layout)

---

## Executive Summary

The current template authoring form is a narrow (560px) slide-in panel with a flat list of fields. It lacks 4 of the 7 required configuration dimensions (authentication, plan gate, KB recommendations, version lifecycle), has no section organization, and does not communicate the complexity of what the platform admin is building.

This spec defines three surfaces:

1. **Platform Admin -- Agent Template Studio**: Full authoring environment for template creation and management
2. **Tenant Admin -- Agent Deployment Wizard**: Guided adoption of platform templates
3. **Tenant Admin -- Custom Agent Studio**: Simplified authoring for tenant-built agents

---

## 1. Information Architecture

### 1.1 Platform Admin -- Agent Template Studio

```
Platform Admin > Agent Templates > [+ New Template] or [row click]
                                          |
                                          v
                              Full-Page Overlay (not slide-in)
                              +-----------------------------------+
                              |  Header: Name + Status + Actions  |
                              +-----------------------------------+
                              |  Tab Bar: [Edit] [Compliance]     |
                              |           [Instances] [History]   |
                              +-----------------------------------+
                              |  Edit Tab:                        |
                              |  7 collapsible accordion sections |
                              |    S1: Identity                   |
                              |    S2: System Prompt              |
                              |    S3: Authentication             |
                              |    S4: Plan & Capabilities        |
                              |    S5: KB & Tools                 |
                              |    S6: Guardrails                 |
                              |    S7: Version & Lifecycle        |
                              |                                   |
                              |  Sticky footer: [Save Draft]      |
                              |                 [Publish]          |
                              +-----------------------------------+
```

### 1.2 Tenant Admin -- Agent Deployment Wizard

```
Settings > Agents > [+ New Agent] > [From Template]
                          |
                          v
                    Wizard Modal (640px max-width)
                    Step 1: Select Template (card picker)
                    Step 2: Knowledge & Tools (KB checkboxes + tool toggles)
                    Step 3: Access & Limits (RBAC + rate limits + guardrail read-only)
                    Step 4: Credentials (conditional -- only if auth_mode != none)
                    Final:  Deploy confirmation
```

### 1.3 Tenant Admin -- Custom Agent Studio

```
Settings > Agents > [+ New Agent] > [Custom Agent]
                          |
                          v
                    Slide-In Panel (560px, existing pattern)
                    5 collapsible sections:
                      S1: Identity (name, description, category, icon)
                      S2: System Prompt (template variable detection)
                      S3: KB Bindings (checkbox list of tenant KBs)
                      S4: Guardrails (editable -- tenant owns these)
                      S5: Access Control (RBAC + rate limits)
                    Footer: [Save Draft] [Publish]
```

---

## 2. Key UX Decisions

### 2.1 Full-Page Overlay vs. Slide-In Panel

**Decision**: Platform Admin Template Studio uses a full-page overlay. Tenant Admin Custom Agent Studio uses a slide-in panel.

**Rationale**: The platform admin authoring surface has 7 configuration dimensions, a tab bar (Edit, Compliance, Instances, History), and inline test harness. A 560px slide-in cannot contain this without extreme scrolling. The full-page overlay provides breathing room for the system prompt textarea, variable schema table, credential schema table, guardrail pattern editor, and tool assignment list -- all of which need horizontal space.

The tenant admin custom agent studio has 5 simpler sections (no authentication, no plan gate, no versioning). The existing slide-in pattern (560px) is sufficient and consistent with other tenant admin configuration panels.

```
Full-page overlay dimensions:
  - Width: 100vw - sidebar (sidebar collapses to icon-only mode)
  - Max content width: 860px (centered, same as chat message area)
  - Header: sticky, 56px height
  - Footer: sticky, 56px height
  - Body: scrollable between header and footer
```

### 2.2 Accordion vs. Tabs for Section Layout

**Decision**: Vertical accordion with collapsible sections for the Edit tab. Tab bar at the panel level for Edit/Compliance/Instances/History.

**Rationale**: Accordion allows the admin to see multiple sections simultaneously (e.g., system prompt open while checking variable definitions). Tabs would force single-section visibility, requiring constant switching. The accordion pattern matches the "configure everything in one session" value proposition from Flow 1.

**Accordion behavior**:
- On create: all 7 sections expanded by default (admin needs to see the full surface)
- On edit: only modified sections and Section 1 (Identity) expanded; others collapsed showing a one-line summary
- Click section header to toggle
- Section headers show validation state: green accent dot (valid), alert dot (error), no dot (untouched)

### 2.3 Wizard vs. Single-Panel for Tenant Deployment

**Decision**: Wizard modal for template deployment. Single panel for custom agent authoring.

**Rationale**: Template deployment is a linear workflow with conditional steps (credentials appear only when needed). A wizard naturally handles step skipping and progressive disclosure. Custom agent authoring is non-linear (admin may jump between prompt and KB bindings while iterating), making a single scrollable panel more appropriate.

### 2.4 Test Harness Placement

**Decision**: Test harness is a slide-in panel that opens from the right edge, overlaying the studio content. Triggered from a persistent [Test] button in the sticky header.

**Rationale**: Testing is a frequent action during authoring. It must not close the editing surface or lose unsaved work. The slide-in overlay pattern (used for version history already) allows the admin to test, read the response, close the test panel, and continue editing without interruption.

### 2.5 Mobile/Responsive Strategy

**Decision**: Desktop-recommended banner on screens below `md` (768px). Full layout renders at `lg` (1024px) and above. Between `md` and `lg`, the accordion sections stack full-width with reduced padding.

**Rationale**: Agent template authoring is a power-user workflow performed by platform administrators on desktop machines. The system prompt textarea, variable schema table, credential schema table, and guardrail pattern editor are not usable on mobile. Forcing a mobile-optimized layout would compromise the authoring experience for the 99% desktop use case.

```tsx
{/* Desktop recommended banner -- md:hidden */}
<div className="md:hidden rounded-card border border-warn/30 bg-warn-dim p-4 mb-4">
  <p className="text-body-default text-warn">
    Agent template authoring is optimized for desktop. Some features may
    not display correctly on smaller screens.
  </p>
</div>
```

---

## 3. Surface 1: Platform Admin -- Agent Template Studio

### 3.1 Entry Points

**Create**: Platform Admin > Agent Templates table > [+ New Template] button (top-right, accent green, primary style)

**Edit**: Platform Admin > Agent Templates table > click row > full-page overlay opens in read-only mode > click [Edit] to enable editing

**Layout transition**: When the full-page overlay opens, the sidebar collapses to icon-only mode (60px) and the overlay fills the remaining viewport. On close, the sidebar restores to full width.

### 3.2 Full-Page Overlay Structure

```
+-----------------------------------------------------------------------+
|  [< Back to Templates]                                                |
|                                                                       |
|  HR Policy Advisor                    [Draft]     or    [Published]   |
|  text-page-title (22px/700)           badge              v1.0.0      |
|                                                          DM Mono 11px |
|                                                                       |
|  [Edit]  [Compliance]  [Instances]  [Version History]                 |
|  ---- tab bar, 12px/500, accent underline on active ----             |
+-----------------------------------------------------------------------+
|                                                                       |
|  (Tab content area -- scrollable, max-width 860px, centered)          |
|                                                                       |
|  ... accordion sections when Edit tab is active ...                   |
|  ... compliance table when Compliance tab is active ...               |
|  ... instance list when Instances tab is active ...                   |
|  ... version timeline when Version History tab is active ...          |
|                                                                       |
+-----------------------------------------------------------------------+
|  (Sticky footer -- visible only on Edit tab)                          |
|                                                                       |
|  [Test]               [Discard Changes]    [Save Draft]    [Publish]  |
|  ghost                ghost, --text-faint  ghost           primary    |
+-----------------------------------------------------------------------+
```

**Header tokens**:
- Back link: `text-body-default text-text-muted hover:text-accent`, with left-arrow icon (16px)
- Template name: `text-page-title text-text-primary`
- Status badge: `rounded-badge px-2 py-0.5 text-[11px] font-mono`
  - Draft: `bg-bg-elevated text-text-muted`
  - Published: `bg-accent/15 text-accent`
  - Deprecated: `bg-bg-elevated text-text-faint`
- Version: `font-mono text-[11px] text-text-faint`
- Tab bar: `text-[12px] font-medium` per design system tab pattern

**Footer tokens**:
- [Test] button: `rounded-control border border-border px-4 py-2 text-body-default text-text-muted hover:bg-bg-elevated hover:text-text-primary`
- [Save Draft]: same ghost style
- [Publish]: `rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-deep hover:bg-accent/90` (disabled state: `opacity-30 cursor-not-allowed`)
- [Discard Changes]: `text-body-default text-text-faint hover:text-alert` (only visible when form is dirty)

### 3.3 Section 1: Identity

```
+-----------------------------------------------------------------------+
|  v  IDENTITY                                          [valid dot]     |
|     text-label-nav uppercase, --text-faint                            |
+-----------------------------------------------------------------------+
|                                                                       |
|  TEMPLATE NAME *                                                      |
|  [HR Policy Advisor_________________________]                         |
|  text-body-default, rounded-control, bg-bg-elevated                   |
|  Error: "A template named 'X' already exists" -- text-body-default    |
|         text-alert, below field                                       |
|                                                                       |
|  DESCRIPTION                                                          |
|  [Answers employee questions about...______]   178 / 200              |
|  textarea, 2 rows, text-body-default                    DM Mono 11px  |
|                                                         --text-faint  |
|                                                                       |
|  CATEGORY                                                             |
|  [Human Resources v]                                                  |
|  select, rounded-control, bg-bg-elevated                              |
|  Options: Financial Data, Human Resources, Legal, IT Support,         |
|           Procurement, Custom                                         |
|                                                                       |
|  ICON                                                                 |
|  [ HR ] [ Finance ] [ Legal ] [ IT ] [ Search ] [ Custom ]           |
|  6-option icon picker grid, 40x40px buttons, rounded-control          |
|  Selected: accent border + accent-dim background                      |
|  Unselected: border-faint border, bg-bg-elevated                     |
|                                                                       |
+-----------------------------------------------------------------------+
```

**Field tokens**:
- Section header: `text-label-nav uppercase tracking-wider text-text-faint`
- Field labels: `text-[11px] uppercase tracking-wider text-text-faint mb-1`
- Input fields: `w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none`
- Inline errors: `text-body-default text-alert mt-1`
- Character counter: `font-mono text-[11px] text-text-faint` (turns `text-alert` at threshold)

### 3.4 Section 2: System Prompt

This is the most complex section. It features a monospace textarea with live variable detection, a variable schema table, and a preview toggle.

```
+-----------------------------------------------------------------------+
|  v  SYSTEM PROMPT                                     [valid dot]     |
+-----------------------------------------------------------------------+
|                                                                       |
|  [Edit]  [Preview]   toggle, right-aligned, text-[11px] text-text-muted|
|                                                                       |
|  +-------------------------------------------------------------------+|
|  | You are an HR Policy Advisor for {{org_name}}. You answer         ||
|  | employee questions about company policies, benefits, leave        ||
|  | entitlements, and HR procedures.                                  ||
|  |                                                                   ||
|  | Always cite the specific policy document and section number.      ||
|  | If a question is outside HR policy scope, say so clearly.         ||
|  | Never provide legal advice -- direct users to Legal.              ||
|  +-------------------------------------------------------------------+|
|  textarea: font-mono text-body-default, 12 rows, bg-bg-deep          |
|  border border-border rounded-control                                 |
|  {{variables}} rendered inline with text-accent in preview mode       |
|                                                                       |
|  423 / 2,000                                    font-mono text-[11px] |
|  --text-faint (normal) | --warn (1600+) | --alert (1800+)            |
|                                                                       |
|  DETECTED VARIABLES                                                   |
|  [{{org_name}}]                                                       |
|  accent-dim bg, accent text, rounded-badge, font-mono text-[11px]    |
|                                                                       |
|  VARIABLE SCHEMA                                                      |
|  +------------------------------------------------------------------+|
|  | KEY          | LABEL              | REQUIRED                     ||
|  |--font-mono---|--text-body---------|--toggle----                   ||
|  | org_name     | Organization Name  | [*] (toggle on)              ||
|  +------------------------------------------------------------------+|
|  [+ Add Variable]  ghost button, text-body-default text-text-muted   |
|                                                                       |
+-----------------------------------------------------------------------+
```

**Interaction flow**:
1. Admin types in textarea. The UI scans for `{{variable_name}}` patterns on every keystroke (debounced 300ms)
2. Detected variables appear as accent-colored chips below the textarea
3. Each detected variable auto-populates a row in the Variable Schema table (if not already present)
4. Admin can set label and required toggle for each variable
5. Variables removed from the prompt are grayed in the schema table with a "Not in prompt" note
6. [+ Add Variable] adds a manual variable row (for variables injected server-side, not in the prompt text)

**Preview mode**: Textarea becomes read-only with `{{variable}}` tokens highlighted in accent. No background change on the tokens -- just the accent text color against the `bg-bg-deep` textarea background.

**Variable schema table tokens**:
- Table header: `text-label-nav uppercase tracking-wider text-text-faint`
- Key column: `font-mono text-data-value`
- Label column: `text-body-default text-text-primary`
- Required toggle: accent green when on, `bg-bg-elevated border-border` when off, `rounded-badge` radius
- Row: `border-b border-border-faint py-2`

### 3.5 Section 3: Authentication

```
+-----------------------------------------------------------------------+
|  v  AUTHENTICATION                                    [valid dot]     |
+-----------------------------------------------------------------------+
|                                                                       |
|  AUTH MODE                                                            |
|  (*) None                                                             |
|  ( ) Tenant Credentials                                               |
|  ( ) Platform Credentials                                             |
|  radio group, text-body-default, accent dot when selected             |
|                                                                       |
|  -- When "None" selected: --                                          |
|  "No credentials required. This agent uses knowledge base data only." |
|  text-body-default text-text-faint                                    |
|                                                                       |
|  -- When "Tenant Credentials" selected: --                            |
|  CREDENTIAL SCHEMA                                                    |
|  +------------------------------------------------------------------+|
|  | KEY              | LABEL                  | TYPE   | SENSITIVE   ||
|  |--font-mono-------|--text-body-------------|--------|--toggle--   ||
|  | api_client_id    | API Client ID          | string | [ ]         ||
|  | api_secret       | API Client Secret      | string | [*]         ||
|  +------------------------------------------------------------------+|
|  [+ Add Credential Field]  ghost button                              |
|                                                                       |
|  Key auto-generates from label (slugified). Sensitive toggle controls |
|  whether tenant UI masks the input as password field.                 |
|                                                                       |
+-----------------------------------------------------------------------+
```

**Radio group tokens**:
- Radio: custom-styled, 16px diameter circle
  - Unselected: `border-2 border-border bg-transparent`
  - Selected: `border-2 border-accent bg-accent` with inner 6px white dot
- Radio label: `text-body-default text-text-primary ml-2`
- Radio group spacing: `space-y-3`

**Credential schema table tokens**:
- Same table pattern as variable schema
- Key column: `font-mono text-data-value` (auto-generated, editable)
- Sensitive toggle: same style as required toggle
- Inline row editing: fields become editable inputs on focus, save on blur
- Delete row: `X` icon on hover, right side of row, `text-text-faint hover:text-alert`

### 3.6 Section 4: Plan & Capabilities

```
+-----------------------------------------------------------------------+
|  v  PLAN & CAPABILITIES                              [valid dot]      |
+-----------------------------------------------------------------------+
|                                                                       |
|  PLAN REQUIRED                                                        |
|  [None v]                                                             |
|  select: None / Starter / Professional / Enterprise                   |
|  "Tenants on a lower plan see this template locked with an upgrade    |
|  prompt."  text-body-default text-text-faint                          |
|                                                                       |
|  CAPABILITIES                                   informational chips   |
|  [policy_lookup] [benefits_inquiry] [leave_balance] [+]               |
|  chip input: type and press Enter to add                              |
|  bg-bg-elevated border-border rounded-badge text-[11px] font-mono    |
|  X button on each chip to remove                                     |
|                                                                       |
|  CANNOT DO                                      informational chips   |
|  [legal_advice] [salary_negotiation] [+]                              |
|  same chip input pattern, but chips use alert-dim background          |
|                                                                       |
+-----------------------------------------------------------------------+
```

**Chip input tokens**:
- Input wrapper: `rounded-control border border-border bg-bg-elevated flex flex-wrap gap-1.5 p-2`
- Chips (capabilities): `inline-flex items-center gap-1 rounded-badge bg-bg-elevated border border-border px-2 py-0.5 font-mono text-[11px] text-text-muted`
- Chips (cannot do): same but `border-alert/20 bg-alert-dim text-alert`
- Chip X button: `text-text-faint hover:text-text-primary` (capabilities) or `text-alert/60 hover:text-alert` (cannot do)
- Text input inside wrapper: `bg-transparent border-none outline-none text-body-default text-text-primary placeholder:text-text-faint min-w-[120px] flex-1`

### 3.7 Section 5: KB & Tools

```
+-----------------------------------------------------------------------+
|  v  KNOWLEDGE & TOOLS                                [valid dot]      |
+-----------------------------------------------------------------------+
|                                                                       |
|  RECOMMENDED KB CATEGORIES                                            |
|  "Tenants see matching KBs sorted to the top during deployment."      |
|  text-body-default text-text-faint                                    |
|                                                                       |
|  [hr_policies] [employee_handbook] [benefits_guide] [+]               |
|  chip input, same pattern as capabilities                             |
|                                                                       |
|  -------------------------------------------------------------------- |
|                                                                       |
|  TOOL ASSIGNMENTS                            2 of 8 available        |
|                                              font-mono text-[11px]    |
|                                                                       |
|  [x] Jira Issue Reader         Read-Only     [Healthy]               |
|  [ ] Slack Notifier            Write         [Healthy]               |
|  [x] Confluence Search         Read-Only     [Degraded (!)]          |
|  [ ] Calendar Lookup           Read-Only     [Healthy]               |
|  ...                                                                  |
|                                                                       |
|  "Tools must be registered in Tool Catalog first."                    |
|  text-body-default text-text-faint                                    |
|                                                                       |
+-----------------------------------------------------------------------+
```

**Tool row tokens**:
- Checkbox: `rounded-badge border-2`, selected: `bg-accent border-accent`, check icon white
- Tool name: `text-body-default font-medium text-text-primary`
- Classification badge:
  - Read-Only: accent dot (6px circle `bg-accent`) + `text-[11px] text-text-muted`
  - Write: warn dot + `text-[11px] text-warn`
  - Execute: alert dot + `text-[11px] text-alert`
- Health badge:
  - Healthy: `font-mono text-[11px] text-accent`
  - Degraded: `font-mono text-[11px] text-warn`
  - Down: `font-mono text-[11px] text-alert`
  - Unknown: `font-mono text-[11px] text-text-faint`
- Row: `flex items-center gap-3 py-2 border-b border-border-faint`

### 3.8 Section 6: Guardrails

```
+-----------------------------------------------------------------------+
|  v  GUARDRAILS                                       [valid dot]      |
+-----------------------------------------------------------------------+
|                                                                       |
|  BLOCKED TOPICS                                                       |
|                                                                       |
|  +------------------------------------------------------------------+|
|  | salary_disclosure                                           [x]  ||
|  | Rule Type: [keyword_block v]                                     ||
|  | Patterns (regex, one per line):                                  ||
|  | +--------------------------------------------------------------+||
|  | | \b(CEO salary|executive comp|how much does .* earn)\b        |||
|  | | \b(pay grade|salary band|compensation details)\b             |||
|  | +--------------------------------------------------------------+||
|  | On Violation: (*) Block  ( ) Redact  ( ) Warn                   ||
|  | User Message:                                                    ||
|  | [Salary and compensation details are confidential...]            ||
|  +------------------------------------------------------------------+|
|                                                                       |
|  [+ Add Rule]  ghost button                                          |
|                                                                       |
|  -------------------------------------------------------------------- |
|                                                                       |
|  MAX RESPONSE LENGTH                                                  |
|  [1500] tokens                      font-mono, w-24, bg-bg-elevated  |
|                                                                       |
|  CONFIDENCE THRESHOLD                                                 |
|  [==========|--------]  0.65                                         |
|  range slider, accent track, DM Mono value readout                   |
|                                                                       |
|  CITATION MODE                                                        |
|  [Required v]    select: Required / Optional / None                  |
|                                                                       |
+-----------------------------------------------------------------------+
```

**Guardrail rule card tokens**:
- Rule card: `rounded-control border border-border bg-bg-elevated p-4 space-y-3`
- Rule name header: `font-mono text-data-value text-text-primary font-medium`
- Rule type select: `rounded-control border border-border bg-bg-deep px-2 py-1 text-body-default`
- Regex textarea: `font-mono text-body-default bg-bg-deep border border-border rounded-control p-2` -- min 3 rows
- Regex validation error: `text-body-default text-alert mt-1` -- "Invalid regex: {detail}"
- Violation radio: same pattern as auth mode radio, but inline horizontal
- User message textarea: `text-body-default bg-bg-deep border border-border rounded-control px-3 py-2` -- 2 rows

**Confidence threshold slider tokens**:
- Track: `h-1 rounded-full bg-border`
- Filled track: `h-1 rounded-full bg-accent`
- Thumb: `w-4 h-4 rounded-full bg-accent border-2 border-bg-surface shadow`
- Value readout: `font-mono text-data-value text-accent ml-3`

### 3.9 Section 7: Version & Lifecycle (Edit mode -- read-only section)

```
+-----------------------------------------------------------------------+
|  v  VERSION & LIFECYCLE                                               |
+-----------------------------------------------------------------------+
|                                                                       |
|  -- On unpublished drafts: --                                         |
|  "No versions published yet. Save as draft and publish when ready."   |
|  text-body-default text-text-faint                                    |
|                                                                       |
|  -- On published templates: --                                        |
|  CURRENT VERSION                                                      |
|  v1.0.0     Published 2026-03-21     font-mono text-data-value       |
|                                                                       |
|  RECENT CHANGES                                                       |
|  v1.0.0  2026-03-21  Initial release: HR policy Q&A...              |
|  (DM Mono version, Plus Jakarta date, Plus Jakarta changelog)        |
|  [View Full History -->]  accent text, opens Version History tab     |
|                                                                       |
|  DEPLOYMENT STATUS                                                    |
|  4 active instances across 3 tenants   font-mono text-data-value     |
|  [View Instances -->]  accent text, switches to Instances tab        |
|                                                                       |
+-----------------------------------------------------------------------+
```

### 3.10 Tab: Compliance

See Flow 7 in `23-agent-template-flows.md` for the full violation log specification. The Compliance tab renders the filterable violations table with date range, rule, action, and tenant filters, inline row expansion for violation detail, and [Export CSV] button.

### 3.11 Tab: Instances

Lists all tenant deployments of this template:

```
+-----------------------------------------------------------------------+
|  INSTANCES                                          4 active          |
|                                                                       |
|  +------------------------------------------------------------------+|
|  | Tenant              | Version | Status   | Deployed    | Usage   ||
|  |--text-body----------|--mono---|--badge---|--mono-------|--mono---||
|  | Acme Capital        | v1.0.0  | Active   | 2026-03-01  | 847     ||
|  | GlobalFin Corp      | v1.0.0  | Active   | 2026-03-05  | 2,104   ||
|  | TechStart Inc       | v1.0.0  | Pending  | 2026-03-18  | 12      ||
|  | Pinnacle Advisory   | v0.9.0  | Active   | 2026-02-15  | 456     ||
|  +------------------------------------------------------------------+|
|                                                                       |
|  Version column: instances on older version show --warn text          |
|  Status badge: Active = accent, Pending = warn, Paused = text-faint  |
|  Usage = query count in trailing 30 days, DM Mono                    |
|                                                                       |
|  Note: Platform admin sees tenant names and aggregate usage but       |
|  cannot see agent configuration, KB bindings, or system prompts       |
|  (tenant data sovereignty).                                           |
+-----------------------------------------------------------------------+
```

### 3.12 Tab: Version History

Vertical timeline layout:

```
+-----------------------------------------------------------------------+
|  VERSION HISTORY                                                      |
|                                                                       |
|  o  v1.1.0    2026-03-21    Minor                                    |
|  |  Updated system prompt to include benefits enrollment deadlines.   |
|  |  Added performance data guardrail rule.                           |
|  |  Published by admin@platform.com                                  |
|  |                                                                   |
|  o  v1.0.0    2026-03-15    Initial                                  |
|  |  Initial release: HR policy Q&A with salary disclosure and        |
|  |  legal advice guardrails.                                         |
|  |  Published by admin@platform.com                                  |
|                                                                       |
|  Timeline: vertical line 2px --border, dot 8px --accent for latest,  |
|  --bg-elevated for older. Version: font-mono text-data-value.        |
|  Date: font-mono text-[11px] text-text-faint.                        |
|  Type badge: rounded-badge, 11px -- Initial/Patch/Minor/Major        |
|  Changelog: text-body-default text-text-muted                        |
|  Publisher: text-[11px] text-text-faint                              |
+-----------------------------------------------------------------------+
```

### 3.13 Publish Flow (Inline within Edit Tab)

When the admin clicks [Publish] in the footer, the accordion sections collapse and a pre-publish review section expands at the top of the scroll area:

```
+-----------------------------------------------------------------------+
|  PRE-PUBLISH REVIEW                                                   |
|                                                                       |
|  [check] Name and description complete                                |
|  [check] System prompt defined (423 chars)                            |
|  [check] Auth mode set: None                                          |
|  [check] Guardrail rules configured: 2 rules                         |
|  [warn]  No tools assigned (optional)                                 |
|  [check] Confidence threshold set: 0.65                               |
|                                                                       |
|  VERSION LABEL                                                        |
|  [1.0.0________]   font-mono, bg-bg-elevated, rounded-control        |
|                                                                       |
|  CHANGELOG *                                                          |
|  [Initial release: HR policy Q&A with salary disclosure and___]       |
|  textarea, text-body-default, 3 rows, min 10 chars                   |
|                                                                       |
|  [Cancel]                                     [Confirm Publish]       |
|  ghost                                        accent primary          |
+-----------------------------------------------------------------------+
```

**Checklist item tokens**:
- Pass: accent checkmark (16px) + `text-body-default text-text-primary`
- Warn: warn triangle (16px) + `text-body-default text-warn`
- Fail: alert X (16px) + `text-body-default text-alert`
- Row spacing: `space-y-2`

### 3.14 Test Harness (Slide-In from Right)

When the admin clicks [Test] in the footer, a test panel slides in from the right (400px width) overlaying the studio content:

```
+-----------------------------------------------+
|  TEST HARNESS                            [x]  |
|  HR Policy Advisor -- Draft                    |
+-----------------------------------------------+
|                                                |
|  TEST QUERY                                    |
|  [What's our PTO policy?___________________]  |
|  input, text-body-default, rounded-control     |
|                                                |
|  [Run Test]  accent primary button             |
|                                                |
|  -------------------------------------------- |
|                                                |
|  RESULT                                        |
|                                                |
|  Response:                                     |
|  "According to the Employee Handbook (Section  |
|  4.2), full-time employees receive..."         |
|  text-body-default, --bg-deep background       |
|                                                |
|  Confidence: 0.82           font-mono, accent  |
|  Sources: 2                 font-mono           |
|  KB Queries: Employee Handbook, Benefits Guide  |
|  Guardrail Events: None                         |
|  Latency: 1,247ms          font-mono           |
|                                                |
|  -------------------------------------------- |
|                                                |
|  GUARDRAIL TEST                                |
|  [What's the CEO's salary?_________________]  |
|  [Run Test]                                    |
|                                                |
|  Response: (blocked)                           |
|  "Salary and compensation details are..."     |
|  Rule triggered: salary_disclosure   --alert   |
|  Action: block                                 |
|                                                |
+-----------------------------------------------+
```

**Test panel tokens**:
- Panel: `w-[400px] bg-bg-surface border-l border-border animate-slide-in-right`
- Result section: `rounded-control bg-bg-deep border border-border p-3`
- Response text: `text-body-default text-text-primary`
- Metrics: `font-mono text-data-value text-text-muted`
- Guardrail triggered: `font-mono text-data-value text-alert`

---

## 4. Surface 2: Tenant Admin -- Agent Deployment Wizard

### 4.1 Entry Point

Settings > Agents > [+ New Agent] button (top-right of `ta-panel-agents`). A popover or small selection UI appears:

```
+---------------------------+
|  [From Template]          |
|  [Custom Agent]           |
+---------------------------+
```

Clicking [From Template] opens the wizard modal.

### 4.2 Wizard Modal Structure

```
Max-width: 640px
Border-radius: rounded-card (10px)
Background: bg-bg-surface
Border: 1px border
Centered overlay with bg-bg-deep/60 backdrop

Header: accent progress bar (4px height, full width, percentage fill)
         "Step N of M -- Step Name"   text-body-default text-text-muted
         [x] close button, top-right

Footer: [< Back] ghost + [Next: Step Name >] accent primary
        Final step: [Deploy Agent] accent filled
```

**Progress bar tokens**:
- Track: `h-1 w-full bg-border rounded-full`
- Fill: `h-1 bg-accent rounded-full transition-all duration-300`
- Step label: `text-body-default text-text-muted mt-2`

### 4.3 Step 1: Select Template

Card list of published templates. Each card:

```
+----------------------------------------------------------+
| [HR icon]  HR Policy Advisor                     v1.0.0  |
|            text-section-heading                  mono 11px|
|                                                          |
| Answers employee questions about company policies...     |
| text-body-default text-text-muted, max 2 lines ellipsis  |
|                                                          |
| Auth: No credentials required   text-[11px] text-faint   |
| [policy_lookup] [benefits_inquiry]  chips, 11px mono     |
|                                                          |
|                                            [Select]      |
|                         accent outline, rounded-control   |
+----------------------------------------------------------+
```

Card: `rounded-card border border-border bg-bg-surface p-5 hover:border-accent-ring transition-colors`

Plan-gated cards: `bg-bg-deep opacity-60`, lock icon replaces category icon, no [Select] button.

Search input at top: `rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default w-full`

### 4.4 Step 2: Knowledge & Tools

See Flow 3 Step 2 in `23-agent-template-flows.md` for the complete specification. Key tokens:

- KB checkbox rows: `flex items-center gap-3 py-3 border-b border-border-faint`
- KB name: `text-body-default font-medium text-text-primary`
- Source path: `text-[11px] text-text-faint`
- Doc count: `font-mono text-[11px] text-text-muted`
- Recommended KB indicator: accent dot (6px) before KB name
- Search mode radio: same radio pattern as auth mode
- Tool rows: same pattern as Section 5 of platform studio

### 4.5 Step 3: Access & Limits

See Flow 3 Step 3 in `23-agent-template-flows.md`. Key tokens:

- Access mode radio group: `space-y-3`
- Role chips: `rounded-badge bg-bg-elevated border border-border px-2 py-0.5 text-[11px]`
- Rate limit input: `font-mono text-data-value w-24 rounded-control border border-border bg-bg-elevated px-3 py-2`
- Platform max reference: `font-mono text-[11px] text-text-faint ml-2`
- Guardrail read-only section: `rounded-control bg-bg-deep border border-border-faint p-4`
  - Note: `text-body-default text-text-faint italic`

### 4.6 Step 4: Credentials (Conditional)

Only appears when `auth_mode != "none"`. See Flow 3 Step 4 in `23-agent-template-flows.md`.

- Credential input: `rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default`
- Sensitive field: `type="password"` with eye toggle icon (16px, right-aligned inside input)
- [Test Connection] button: `rounded-control border border-border px-4 py-2 text-body-default text-text-muted`
- Test states:
  - Idle: ghost button
  - Testing: spinner (16px) + "Validating..." `text-text-muted`
  - Passed: accent check (16px) + "Connected: acme@bloomberg" `text-accent`
  - Failed: alert X (16px) + error message `text-alert`

### 4.7 Deploy Confirmation

Success overlay within the modal:

```
+----------------------------------------------------------+
|                                                          |
|         [accent checkmark, 44px]                         |
|                                                          |
|    HR Policy Advisor deployed successfully               |
|    text-section-heading text-text-primary                |
|                                                          |
|    2 knowledge bases bound                               |
|    1 tool enabled                                        |
|    All users                                             |
|    text-body-default text-text-muted                     |
|                                                          |
|    [Go to Agents]           [Deploy Another]             |
|    accent primary           ghost                        |
|                                                          |
+----------------------------------------------------------+
```

---

## 5. Surface 3: Tenant Admin -- Custom Agent Studio

### 5.1 Entry Point

Settings > Agents > [+ New Agent] > [Custom Agent] opens a slide-in panel (560px, consistent with existing TA panel pattern).

### 5.2 Slide-In Panel Structure

```
+-------------------------------------------------------+
|  Custom Agent                               [x] close |
|  text-section-heading                                  |
+-------------------------------------------------------+
|                                                        |
|  5 collapsible accordion sections:                     |
|                                                        |
|  S1: IDENTITY                                          |
|      Name, Description, Category, Icon                 |
|      (same as Platform S1 minus version controls)      |
|                                                        |
|  S2: SYSTEM PROMPT                                     |
|      Monospace textarea with variable detection        |
|      Character counter (2,000 max)                     |
|      No variable schema table (tenant agents do not    |
|      use template variables -- prompt is literal)      |
|                                                        |
|  S3: KB BINDINGS                                       |
|      Checkbox list of tenant's synced KBs              |
|      Search mode: Parallel / Priority Order            |
|      Same UX as wizard Step 2 KB section               |
|                                                        |
|  S4: GUARDRAILS (tenant-editable)                      |
|      Blocked topics with pattern editor                |
|      Max response length, confidence threshold,        |
|      citation mode                                     |
|      Same UX as Platform S6 but tenant-scoped          |
|                                                        |
|  S5: ACCESS CONTROL                                    |
|      Access mode radio (workspace_wide / roles / users)|
|      Rate limit input                                  |
|                                                        |
+-------------------------------------------------------+
|  [Test]         [Save Draft]         [Publish]         |
|  ghost          ghost                accent primary    |
+-------------------------------------------------------+
```

**Key differences from Platform Studio**:
- No Authentication section (custom agents use internal KB data only)
- No Plan & Capabilities section (no plan gating for tenant agents)
- No Version & Lifecycle section (custom agents are single-version, not versioned templates)
- System prompt has no variable schema (prompt is literal, not a template)
- Guardrails are fully editable (tenant owns these, unlike template agents where guardrails are read-only)
- Test harness opens as a nested slide-in (same 400px panel pattern as platform test harness)

---

## 6. States Matrix

### 6.1 Template States (Platform Admin)

| State       | Header Badge                  | Edit Tab | Compliance Tab | Publish Button | Footer Actions             |
| ----------- | ----------------------------- | -------- | -------------- | -------------- | -------------------------- |
| New (unsaved) | "(unsaved)" text-text-faint | Editable | Hidden         | Disabled       | [Save Draft]               |
| Draft       | [Draft] bg-elevated           | Editable | Hidden         | Enabled        | [Save Draft] [Publish]     |
| Published   | [Published] bg-accent/15      | Read-only| Visible        | N/A            | [Edit] in header           |
| Editing published | [Published] + "(editing)" | Editable | Visible      | Becomes [Save] | [Discard] [Save]           |
| Deprecated  | [Deprecated] bg-elevated      | Read-only| Visible        | N/A            | [Restore Template]         |

### 6.2 Agent Instance States (Tenant Admin)

| State              | Card Badge            | Configure | Test Chat |
| ------------------ | --------------------- | --------- | --------- |
| Draft              | [Draft] text-muted    | Editable  | Available |
| Active             | [Active] text-accent  | Editable  | Available |
| Paused             | [Paused] text-warn    | Editable  | Disabled  |
| Pending Validation | [Pending] text-warn   | Editable  | Disabled  |
| Archived           | Not shown (soft deleted) | N/A    | N/A       |

### 6.3 Test Mode Indicator

When the test harness is open and a test is in progress:

```
[Running Test...]
rounded-badge bg-accent/15 text-accent font-mono text-[11px]
Pulses with 220ms opacity animation
```

---

## 7. Component Inventory

### 7.1 New Components Required

| Component                  | Location                                     | Surface            | Description                                          |
| -------------------------- | -------------------------------------------- | ------------------ | ---------------------------------------------------- |
| `AgentStudioOverlay`       | `platform/agent-templates/elements/`         | Platform           | Full-page overlay container with header, tabs, footer |
| `AccordionSection`         | `components/shared/`                         | Platform + Tenant  | Collapsible section with validation dot               |
| `SystemPromptEditor`       | `platform/agent-templates/elements/`         | Platform + Tenant  | Monospace textarea with variable detection            |
| `VariableSchemaTable`      | `platform/agent-templates/elements/`         | Platform           | Editable table for variable key/label/required        |
| `CredentialSchemaTable`    | `platform/agent-templates/elements/`         | Platform           | Editable table for credential key/label/type/sensitive|
| `ChipInput`               | `components/shared/`                         | Platform + Tenant  | Type-and-enter chip input with X remove               |
| `ToolAssignmentList`       | `platform/agent-templates/elements/`         | Platform           | Checkbox list with classification and health badges   |
| `GuardrailRuleEditor`      | `platform/agent-templates/elements/`         | Platform + Tenant  | Pattern editor card with rule type, regex, action     |
| `ConfidenceSlider`         | `components/shared/`                         | Platform + Tenant  | Range slider with DM Mono value readout               |
| `PrePublishChecklist`      | `platform/agent-templates/elements/`         | Platform           | Validation checklist with pass/warn/fail indicators   |
| `VersionTimeline`          | `platform/agent-templates/elements/`         | Platform           | Vertical timeline for version history                 |
| `ComplianceLog`            | `platform/agent-templates/elements/`         | Platform           | Filterable violations table with drill-down           |
| `InstancesTable`           | `platform/agent-templates/elements/`         | Platform           | Tenant deployment list with version/status/usage      |
| `DeployWizard`             | `settings/agents/elements/`                  | Tenant             | Multi-step wizard modal for template deployment       |
| `TemplateCatalogPicker`    | `settings/agents/elements/`                  | Tenant             | Card list with search for template selection          |
| `KBBindingPicker`          | `settings/agents/elements/`                  | Tenant             | Checkbox list of tenant KBs with recommendations      |
| `CredentialEntryForm`      | `settings/agents/elements/`                  | Tenant             | Credential inputs with test connection                |
| `CustomAgentPanel`         | `settings/agents/elements/`                  | Tenant             | Slide-in panel for custom agent authoring             |
| `AgentCreationSelector`    | `settings/agents/elements/`                  | Tenant             | [From Template] / [Custom Agent] selection            |

### 7.2 Existing Components to Reuse

| Component                  | Location                                     | Reuse In                |
| -------------------------- | -------------------------------------------- | ----------------------- |
| `ScrollableTableWrapper`   | `components/shared/`                         | Compliance log, instances |
| `LifecycleActions`         | `platform/agent-templates/elements/`         | Refactor into AccordionSection S7 |
| `TestHarnessPanel`         | `platform/agent-templates/elements/`         | Redesign width and content |
| `VersionHistoryDrawer`     | `platform/agent-templates/elements/`         | Replace with VersionTimeline tab |
| `VariableDefinitions`      | `platform/agent-templates/elements/`         | Replace with VariableSchemaTable |

### 7.3 Components to Deprecate

| Component                  | Reason                                       |
| -------------------------- | -------------------------------------------- |
| `TemplateAuthoringForm`    | Replaced by `AgentStudioOverlay` with accordion sections |
| `VersionHistoryDrawer`     | Replaced by Version History tab in studio overlay |

---

## 8. Interaction Flows (Step-by-Step)

### 8.1 Create New Template

1. Admin clicks [+ New Template] on `pa-panel-templates`
2. Full-page overlay opens with sidebar collapsed
3. Header shows "New Template" with "(unsaved)" faint text
4. All 7 accordion sections expanded, Edit tab active
5. Admin fills Identity section (name, description, category, icon)
6. Admin writes system prompt; variables auto-detected as chips
7. Admin configures auth mode (radio group)
8. Admin sets plan gate and capability/cannot-do chips
9. Admin assigns tools and KB recommendations
10. Admin adds guardrail rules with patterns
11. Admin clicks [Save Draft] in sticky footer
12. POST creates template, header updates to show name + [Draft] badge
13. [Publish] button enables in footer
14. Admin clicks [Publish]
15. Accordion sections collapse; pre-publish checklist expands at top
16. Admin enters version label and changelog
17. Admin clicks [Confirm Publish]
18. Status badge changes to [Published]; toast confirms
19. Compliance and Instances tabs become visible in tab bar

### 8.2 Edit Published Template (Non-Breaking Change)

1. Admin clicks published template row in table
2. Full-page overlay opens in read-only mode (all sections collapsed with summaries)
3. Admin clicks [Edit] in header
4. Sections become editable; footer shows [Discard Changes] [Save]
5. Admin updates description (non-breaking field)
6. Admin clicks [Save]
7. PATCH saves immediately; no version bump; toast "Template updated"
8. Sections return to read-only mode

### 8.3 Edit Published Template (Breaking Change)

1. Steps 1-4 same as 8.2
2. Admin modifies system prompt or guardrail rules
3. Admin clicks [Save]
4. Version modal overlay appears within the panel (not accordion -- centered overlay)
5. Modal shows change diff: [changed] system prompt, [added] guardrail rule
6. Admin selects version type (Patch/Minor/Major)
7. Admin writes change summary (required, min 10 chars)
8. Admin clicks [Publish New Version]
9. Template version increments; toast shows instance notification count
10. Tenant instances see "Update available" banner

### 8.4 Deploy Template (Tenant Admin)

1. Tenant admin clicks [+ New Agent] > [From Template]
2. Wizard modal opens at Step 1 (Select Template)
3. Admin searches and selects template
4. Step 2: Admin checks KB sources, enables/disables tools
5. Step 3: Admin sets access mode and rate limit, reviews guardrails (read-only)
6. Step 4 (conditional): Admin enters credentials and tests connection
7. Final step: Admin clicks [Deploy Agent]
8. Processing overlay (2-5 seconds)
9. Success confirmation with summary stats
10. Agent card appears in `ta-panel-agents` grid

---

## 9. Error States and Edge Cases

### 9.1 Unsaved Changes Guard

When the admin navigates away from the studio with unsaved changes:

```
+------------------------------------------+
|  Unsaved Changes                    [x]  |
|                                          |
|  You have unsaved changes.               |
|  Leave without saving?                   |
|                                          |
|  [Stay]                     [Leave]      |
|  accent primary              ghost       |
+------------------------------------------+
```

Modal: `max-w-[400px] rounded-card bg-bg-surface border border-border p-5`

### 9.2 Concurrent Edit Detection

When another admin modifies the same template during editing:

```
+------------------------------------------+
|  Conflict Detected                  [x]  |
|                                          |
|  This template was modified by another   |
|  admin. Please reload and re-apply       |
|  your changes.                           |
|                                          |
|  [Reload]                                |
|  accent primary                          |
+------------------------------------------+
```

HTTP 409 from PATCH triggers this modal. All local edits are preserved in form state until the admin explicitly reloads.

### 9.3 Validation Summary

When [Save Draft] or [Publish] is clicked with validation errors, the first section containing an error auto-expands and scrolls into view. The section header shows an alert dot. The specific field with the error has an inline error message in `text-alert`.

---

## 10. Responsive Breakpoints

| Breakpoint | Behavior |
| --- | --- |
| `< md` (768px) | Desktop-recommended banner shown. Studio renders but with reduced padding and compressed layouts. Regex textarea and variable table may require horizontal scroll. |
| `md` -- `lg` (768--1024px) | Accordion sections stack full-width. Footer actions wrap to 2 rows if needed. Test harness panel width reduces to 320px. |
| `>= lg` (1024px) | Full layout. Max content width 860px centered. Test harness 400px. All sections render at full size. |
| `>= xl` (1280px) | Additional horizontal breathing room. Content stays at 860px max. |

---

## 11. Animation and Transition Tokens

| Element | Animation | Timing |
| --- | --- | --- |
| Full-page overlay open | Fade in (`animate-fade-in`) | 260ms ease |
| Full-page overlay close | Fade out (reverse) | 200ms ease |
| Accordion section toggle | Height transition (CSS `grid-template-rows: 0fr`/`1fr`) | 220ms ease |
| Test harness panel open | Slide in from right (`animate-slide-in-right`) | 200ms ease |
| Test harness panel close | Slide out right (`animate-slide-out-right`) | 200ms ease |
| Pre-publish checklist expand | Height transition | 220ms ease |
| Toast notification | Slide in from top-right, auto-dismiss | In: 200ms, visible 4s, out: 200ms |
| Wizard step transition | Fade + 8px translateX | 220ms ease |
| Progress bar fill | Width transition | 300ms ease |
| Confidence slider thumb | Transform on drag | None (native range input) |
| Validation dot state change | Color transition | 220ms ease |

All transitions use the design system `--t` shorthand: `background 220ms ease, color 220ms ease, border-color 220ms ease, box-shadow 220ms ease`. No `transition-all`. No bounce/elastic easing.

---

## 12. Accessibility Notes

- All accordion sections are keyboard-navigable (Enter/Space to toggle)
- Tab bar follows WAI-ARIA tabs pattern (`role="tablist"`, `role="tab"`, `role="tabpanel"`)
- Radio groups use semantic `<input type="radio">` with `<fieldset>` and `<legend>`
- Chip inputs announce chip count to screen readers on add/remove
- Confidence slider uses `<input type="range">` with `aria-valuemin`, `aria-valuemax`, `aria-valuenow`
- Color alone never communicates state -- icons (check, triangle, X) accompany status colors
- Focus rings use `focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent-ring`
- Minimum touch target: 44px on interactive elements (consistent with iOS/Android guidelines)

---

**Document Version**: 1.0
**Last Updated**: 2026-03-21
