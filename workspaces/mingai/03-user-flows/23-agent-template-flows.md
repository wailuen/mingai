# 23 -- Agent Template: User Flows

**Date**: 2026-03-21
**Personas**: Platform Admin (template author, tool catalog manager), Tenant Admin (agent deployer, agent auditor), End User (chat consumer), External A2A Client (machine-to-machine discovery)
**Domains**: Template Authoring, Template Publishing, Template Updating, Template Deprecation, Agent Deployment, Agent Reconfiguration, Guardrail Enforcement, Agent Auditing, A2A Discovery, Compliance Monitoring
**Design System**: Obsidian Intelligence -- dark-first, `--accent: #4FFFB0`, Plus Jakarta Sans + DM Mono
**Source Documents**: `49-agent-template-a2a-gap-analysis.md`, `50-agent-template-requirements.md`, `16-agent-template-value-audit/01-enterprise-buyer-perspective.md`, `16-agent-template-value-audit/02-ux-design-spec.md`

> **Note**: This document supersedes `12-tenant-admin-flows.md` Flow 7 (Deploy from Template) and Flow 8 (Agent Library). Those flows are retained for historical reference.

---

## RBAC Permissions

| Action                        | Platform Admin | PA Operator | PA Support | PA Security |
| ----------------------------- | -------------- | ----------- | ---------- | ----------- |
| Create draft template         | Y              | Y           | -          | -           |
| Edit draft template           | Y              | Y           | -          | -           |
| Publish template              | Y              | -           | -          | -           |
| Edit published template       | Y              | -           | -          | -           |
| Deprecate template            | Y              | -           | -          | -           |
| View compliance log           | Y              | Y           | Y          | Y           |
| Export compliance log         | Y              | Y           | -          | Y           |
| View guardrail configurations | Y              | Y           | -          | Y           |

---

## Flow 1: Platform Admin -- Create Agent Template with Full A2A Config

**Trigger**: Platform admin needs to create a new pre-built agent template for tenant adoption.
**Persona**: Platform Admin
**Entry**: Platform Admin > Agent Templates table (`pa-panel-templates`) > "+ New Template" button

```
STEP 1: Open Template Authoring Panel
  Platform admin clicks "+ New Template" in the top-right of pa-panel-templates.
  A slide-in detail panel opens from the right (480px width, max-width 50vw).
  Panel header: "New Template" with a [x] close button top-right.
  Panel contains 7 collapsible sections, all expanded by default on create.
  Two action buttons in header area: [Save Draft] (ghost) and [Publish] (disabled
  until all required fields pass validation).

  VALUE: Platform admin sees the full authoring surface in a single scrollable
  panel -- no multi-step wizard, no page navigation. All configuration is visible
  and editable in context.

STEP 2: Fill Identity Section (Section 1)
  Admin fills:
    Name: "HR Policy Advisor"
    Description: "Answers employee questions about company policies, benefits,
    and HR procedures using bound knowledge bases."
    Category: dropdown -- selects "Human Resources" from [Financial Data,
    Human Resources, Legal, IT Support, Procurement, Custom]
    Icon: 6-option icon picker grid -- selects the HR icon

  All text fields use Plus Jakarta Sans. Name field: 15px/500.
  Description field: 13px/400, max 200 chars, character counter in DM Mono 11px.

  VALIDATION: Name required, 3-80 chars. Red inline error below field if violated,
  using --alert color. Name validation: globally unique across all templates
  (case-insensitive). Checked on blur and on save. Validation message:
  "A template named [name] already exists. Please choose a different name."

STEP 3: Write System Prompt (Section 2)
  Admin writes the base system prompt in a monospace textarea (DM Mono, 12 lines):

    "You are an HR Policy Advisor for {{org_name}}. You answer employee questions
    about company policies, benefits, leave entitlements, and HR procedures.

    Always cite the specific policy document and section number.
    If a question is outside HR policy scope, say so clearly.
    Never provide legal advice -- direct users to Legal."

  Below the textarea:
    Variables detected: {{org_name}} shown as accent-colored chips
    [+ Add Variable] button opens inline row: key (slug), label, required toggle
    Character count: "423 / 2,000" in DM Mono 11px (counter turns --alert at 1800+)
    Required variables: org_name (marked required)
    Optional variables: (none yet)

  VALIDATION: System prompt required. Max 2,000 chars. Variables must use
  {{variable_name}} syntax. Invalid variable references highlighted inline.

STEP 4: Configure Authentication (Section 3)
  Auth Mode is a radio group (not dropdown -- three mutually exclusive states):
    (*) None
    ( ) Tenant Credentials
    ( ) Platform Credentials

  Admin selects "None" for this HR template (it uses internal KB data only,
  no external API credentials required).

  The Required Credentials Schema table is hidden when auth_mode = "None."
  A subtle note reads: "No credentials required. This agent uses knowledge
  base data only."

  IF the admin had selected "Tenant Credentials," the credentials schema
  table would appear:
    +------------------------------------------------------------------+
    | Key              | Label              | Type   | Sensitive        |
    | api_client_id    | API Client ID      | string | No               |
    | api_secret       | API Client Secret  | string | Yes              |
    +------------------------------------------------------------------+
    [+ Add Credential Field]

  Each row is editable inline. Key auto-generates from label (slugified).
  Sensitive toggle: when Yes, tenant UI masks the input as password field.
  [+ Add Credential Field] appends a new blank row -- no modal.

STEP 5: Set Plan and Access Gate (Section 4)
  Plan Required: dropdown -- admin selects "None" (available to all plans)
  Options: [None / Starter / Professional / Enterprise]
  Note: Tenants on a lower plan see the template in catalog with a locked
  state and upgrade prompt.

  Capabilities: chip input -- admin types and presses Enter:
    [policy_lookup] [benefits_inquiry] [leave_balance] [onboarding_guide]

  Cannot Do: chip input:
    [legal_advice] [salary_negotiation] [disciplinary_actions]

  These are informational metadata shown to tenants during adoption --
  not enforced programmatically. Guardrails handle enforcement.

STEP 6: Assign Knowledge Base Bindings (Section 5 -- KB Binding)
  Section header: "Knowledge Base Bindings"
  Info note: "Select which KB indexes this template should query at runtime.
  Tenants will choose from their own synced sources during deployment."

  The platform admin does NOT bind specific KB indexes here (those are
  tenant-specific). Instead, they define KB binding recommendations:
    Recommended KB Categories: chip input
      [hr_policies] [employee_handbook] [benefits_guide]

  These categories are used to auto-sort matching tenant KBs to the top
  of the list during the tenant deploy wizard (Flow 3, Step 2).

  VALIDATION: KB categories are informational. No validation against a
  registry -- tenants may name their KBs freely.

STEP 7: Assign Tools from Tool Catalog (Section 5 -- Tool Assignment)
  Section header: "Tool Assignments"
  Subheader: "Assigned tools (0 of 8 available)"

  Checkbox list of all tools from the platform Tool Catalog:
    +------------------------------------------------------------------+
    | [ ] Jira Issue Reader         Read-Only    Healthy               |
    | [ ] Slack Notifier            Write        Healthy               |
    | [ ] Calendar Lookup           Read-Only    Healthy               |
    | [ ] Confluence Search         Read-Only    Degraded (!)          |
    | [ ] Salesforce CRM Reader     Read-Only    Healthy               |
    | [ ] Bloomberg Data Feed       Read-Only    Healthy               |
    | [ ] Tavily Web Search         Read-Only    Healthy               |
    | [ ] Calculator                Execute      Healthy               |
    +------------------------------------------------------------------+
    Info: Tools must be registered in Tool Catalog first.

  Each row shows:
    - Checkbox (Plus Jakarta Sans 13px/500 for tool name)
    - Classification badge: Read-Only = accent dot, Write = --warn lightning,
      Execute = --alert triangle
    - Health status: "Healthy" in --accent, "Degraded (!)" in --warn,
      "Down" in --alert, "Unknown" in --text-faint

  Admin checks [Jira Issue Reader] and [Confluence Search].
  Subheader updates: "Assigned tools (2 of 8 available)"

  Degraded tools: the row still allows assignment, but the --warn "(Degraded)"
  label communicates the risk. No blocking validation.

  REAL-TIME VALIDATION: Tool health status is fetched from the platform's
  5-minute health check cycle. If a tool's MCP endpoint was last checked
  >15 minutes ago, status shows "Unknown" with --text-faint dash indicator.

STEP 8: Configure Guardrails (Section 6)
  Section header: "Guardrails"

  Form fields:
    Blocked Topics: chip input with pattern definition
      Admin types: "salary_disclosure" and presses Enter
      Each chip opens an inline expansion for pattern config:
        +--------------------------------------------------------------+
        | salary_disclosure                                    [x]     |
        | Rule Type: [keyword_block v]                                 |
        | Patterns (regex, one per line):                              |
        | \b(CEO salary|executive comp|how much does .* earn)\b        |
        | \b(pay grade|salary band|compensation details)\b             |
        |                                                              |
        | On Violation: (*) Block  ( ) Redact  ( ) Warn                |
        | User Message:                                                |
        | "Salary and compensation details are confidential. Please    |
        |  contact HR directly for compensation inquiries."            |
        +--------------------------------------------------------------+

    Max Response Length: [1500] tokens -- DM Mono input
    Confidence Threshold: [0.65] -- DM Mono input
    Citation Mode: dropdown [Required / Optional / None]

  Admin adds a second guardrail rule:
    "no_legal_advice" -- keyword_block
    Patterns: \b(legal advice|I advise you to|sue|lawsuit|litigate)\b
    On Violation: Block
    User Message: "Legal advice is outside this agent's scope.
    Please consult your Legal department."

  VALIDATION:
    - Regex patterns are validated on blur. Invalid regex shows inline error
      in --alert: "Invalid pattern: unbalanced parenthesis at position 12"
    - On Violation action is required for each rule
    - User Message is required when action = Block or Redact
    - Confidence threshold must be 0.0-1.0; inline error if out of range

  ERROR STATE -- Guardrail config not in registry:
    If a rule references a type not supported by the platform output filter
    (e.g., "semantic_check" which is not yet deployed), the validation shows:
    "Rule type 'semantic_check' is not available in the current deployment.
    Available types: keyword_block, citation_required." in --alert color
    below the rule type dropdown. The admin must select a supported type
    or remove the rule before saving.

STEP 9: Save as Draft
  Admin clicks [Save Draft] in the panel header.
  POST /platform/agent-templates with status='Draft'.

  Save confirmation:
    - Panel header updates: "HR Policy Advisor" with [Draft] badge
      (--bg-elevated background, --text-muted text, --r-sm radius)
    - Toast notification slides in from top-right: "Template saved as draft"
      (accent left border, --bg-surface background, auto-dismisses in 4s)
    - Template row appears in pa-panel-templates table with Draft status badge

  The [Publish] button is now enabled (all required fields validated).
  Version History section shows: "No versions published yet."
  [Publish] button text: accent green, primary button style.

  VALUE: The entire template is configured in a single session without
  leaving the panel. Draft status allows iteration before tenant visibility.
```

**Edge Cases**:

| Scenario                          | What Happens                                                                                                        | Recovery                                             |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Duplicate template name           | Inline error on blur: "A template named 'HR Policy Advisor' already exists" in --alert                              | Admin changes the name                               |
| System prompt exceeds 2,000 chars | Character counter turns --alert. [Save Draft] disabled. Inline text: "Reduce system prompt to 2,000 characters"     | Admin trims the prompt                               |
| All tools degraded/down           | Warn banner above tool list: "All available tools are experiencing issues. Tool assignments can still be saved."    | Admin can proceed; tools are monitored platform-side |
| Regex pattern invalid             | Inline error below pattern field: "Invalid regex: {error detail}" in --alert                                        | Admin fixes the pattern                              |
| Browser close during edit         | Unsaved changes prompt: "You have unsaved changes. Leave without saving?" with [Stay] (primary) and [Leave] (ghost) | Admin clicks Stay to continue                        |

---

## Flow 2: Platform Admin -- Publish Template to Marketplace

**Trigger**: Platform admin has completed and reviewed a draft template and wants to make it available to tenants.
**Persona**: Platform Admin
**Entry**: Template detail slide-in panel > [Publish] button (or template row > "..." menu > Publish)

```
STEP 1: Initiate Publish
  Platform admin opens the "HR Policy Advisor" template (Draft status).
  The slide-in detail panel shows all 7 sections with current configuration.
  Admin clicks [Publish] button (accent green, top-right of panel header).

  A publish review overlay appears within the slide-in panel (not a separate
  modal -- inline expansion below the header):

STEP 2: Review Pre-Publish Checklist
  The checklist renders as a vertical list with pass/fail indicators:

    +------------------------------------------------------------------+
    | PRE-PUBLISH REVIEW                                               |
    |                                                                  |
    | [check] Name and description complete                            |
    | [check] System prompt defined (423 chars)                        |
    | [check] Auth mode set: None                                      |
    | [check] Guardrail rules configured: 2 rules                     |
    |         - salary_disclosure (keyword_block, block)               |
    |         - no_legal_advice (keyword_block, block)                 |
    | [check] Confidence threshold set: 0.65                           |
    | [check] Citation mode: Required                                  |
    | [warn]  No tools assigned (optional)                             |
    | [check] No credential schema required (auth_mode: none)          |
    |                                                                  |
    | All required checks passed.                                      |
    |                                                                  |
    | Version Label: [1.0.0________]   DM Mono                        |
    | Changelog:                                                       |
    | [Initial release: HR policy Q&A with salary disclosure and       |
    |  legal advice guardrails.__________________________________]     |
    |                                                                  |
    | [Cancel]                              [Confirm Publish]          |
    +------------------------------------------------------------------+

  Check indicators:
    [check] = accent green checkmark (--accent color)
    [warn] = yellow warning triangle (--warn color) -- non-blocking
    [fail] = red X (--alert color) -- blocking, [Confirm Publish] disabled

  Blocking failures (if any):
    - No system prompt: [fail] "System prompt is required"
    - Credential schema incomplete: [fail] "Auth mode is 'tenant_credentials'
      but no credential fields defined"
    - Guardrail regex invalid: [fail] "Rule 'salary_disclosure' has invalid
      regex pattern"

  Version label defaults to "1.0.0" for first publish, auto-incremented
  for subsequent publishes. Editable (DM Mono input).
  Changelog is required -- textarea, Plus Jakarta Sans 13px.

STEP 3: Confirm Publish
  Admin fills version "1.0.0" and changelog text.
  Clicks [Confirm Publish] (accent green primary button).

  PATCH /platform/agent-templates/{id} with status='Published', version='1.0.0'.

  Publish confirmation:
    - Status badge changes from [Draft] to [Published] (accent background,
      dark text, --r-sm radius)
    - Toast: "HR Policy Advisor v1.0.0 published" (accent left border)
    - Version History section updates:
        v1.0.0  2026-03-21  Initial release: HR policy Q&A...
      (DM Mono 12px for version, Plus Jakarta Sans 13px for date and changelog)
    - Pre-publish checklist collapses and disappears

STEP 4: What "Published" Means
  The template is now visible to tenant admins in their agent catalog:
    - GET /agents/templates returns this template for tenants whose plan
      meets the plan_required gate (or all tenants if plan_required = NULL)
    - Template appears as a card in the tenant's "Agent Library" view

  What tenants see (template card in their marketplace):
    +------------------------------------------------------------------+
    | [HR icon]  HR Policy Advisor                           v1.0.0    |
    |                                                                  |
    | Answers employee questions about company policies, benefits,     |
    | and HR procedures using bound knowledge bases.                   |
    |                                                                  |
    | Category: Human Resources                                        |
    | Auth: No credentials required                                    |
    | Capabilities: policy_lookup, benefits_inquiry, leave_balance     |
    |                                                                  |
    | [Adopt]                                                          |
    +------------------------------------------------------------------+

  Card design:
    - --bg-surface background, 1px --border, --r-lg radius, 20px padding
    - Icon: 36x36px, left-aligned with name
    - Version: DM Mono 11px, --text-faint, right-aligned
    - Category: 11px uppercase label, --text-faint, letter-spacing .06em
    - Auth indicator: "No credentials required" in --text-muted 11px
    - Capabilities: inline chips, --bg-elevated background, --r-sm radius
    - [Adopt] button: accent green outline, transitions to filled on hover
```

**Edge Cases**:

| Scenario                            | What Happens                                                                                                                                             | Recovery                                                    |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Required field missing at publish   | Checklist shows [fail] indicator. [Confirm Publish] disabled. Specific missing field named.                                                              | Admin scrolls to section, fills field, returns to publish   |
| Publish with degraded tool assigned | Checklist shows [warn] on tool line: "1 assigned tool is degraded." Non-blocking.                                                                        | Admin can publish anyway; tool health is platform-monitored |
| Network error during publish        | Alert toast: "Failed to publish template. Please try again." Panel stays open with all data preserved.                                                   | Admin retries                                               |
| Subsequent version publish          | Version auto-increments to next minor (1.0.0 -> 1.1.0). Admin can override. Template update notifications trigger for all tenant instances (see Flow 7). | N/A                                                         |

---

## Flow 2B: Platform Admin -- Update Published Template

**Trigger**: Platform admin needs to modify a published template (fix a description, update guardrail rules, revise the system prompt).
**Persona**: Platform Admin
**Entry**: Platform Admin > Agent Templates (`pa-panel-templates`) > [Published Template] slide-in > Edit button

```
STEP 1: Open Published Template for Editing
  Platform admin clicks on a published template row in pa-panel-templates.
  The slide-in detail panel opens, showing the template in read-only view.
  Panel header shows: "HR Policy Advisor" with [Published] badge and
  version indicator "v1.0 (live)" in DM Mono 11px, --text-muted.

  Admin clicks [Edit] button (ghost style, top-right, next to the [x] close).
  All sections transition to editable mode. The panel header updates to show:
  "Editing: HR Policy Advisor" with [Cancel] (ghost) and [Save] (primary).

STEP 2: Make Non-Breaking Changes (In-Place Save)
  Non-breaking fields can be saved immediately without a version bump:
    - Description text
    - Icon selection
    - Recommended KB categories (recommended_kb_categories)

  Admin updates the description from "Answers employee questions..." to
  "Answers employee and manager questions about company policies, benefits,
  leave entitlements, and HR procedures."

  Admin clicks [Save].

  PATCH /platform/agent-templates/{id} with updated fields.
  No version bump. No tenant notification. Toast: "Template updated."
  The published version number remains unchanged.

STEP 3: Make Breaking Changes (Version Modal)
  Breaking changes are fields that affect agent behavior for existing
  deployments. These fields trigger a version modal on save:
    - System prompt
    - Guardrail rules (patterns, actions, or user messages)
    - Tool assignments (adding or removing tools)
    - Required credentials (schema changes)

  Admin modifies the system prompt to add: "When answering benefits questions,
  always include the enrollment deadline if applicable."

  Admin also adds a new guardrail rule: "no_performance_data" (keyword_block).

  Admin clicks [Save].

STEP 4: Version Modal
  Instead of saving directly, a version modal overlay appears within the
  slide-in panel:

    +------------------------------------------------------------------+
    | VERSION UPDATE                                                    |
    |                                                                   |
    | Changes detected that affect agent behavior:                      |
    |                                                                   |
    | [changed] System prompt changed                                   |
    | [added]   1 guardrail rule added (no_performance_data)            |
    |                                                                   |
    | These changes require a new version. Existing tenant instances    |
    | will see an "Update available" banner.                            |
    |                                                                   |
    | VERSION TYPE                                                      |
    |                                                                   |
    | ( ) Patch (1.0.0 -> 1.0.1)                                       |
    |     Minor clarifications or typo fixes                            |
    |                                                                   |
    | (*) Minor (1.0.0 -> 1.1.0)                                       |
    |     New capabilities or behavior improvements                     |
    |                                                                   |
    | ( ) Major (1.0.0 -> 2.0.0)                                       |
    |     Breaking behavior changes                                     |
    |                                                                   |
    | CHANGE SUMMARY (required)                                         |
    | [Updated system prompt to include benefits enrollment deadlines.  |
    |  Added performance data guardrail rule.________________________]  |
    |                                                                   |
    | This summary will be shown to tenant admins in the update         |
    | notification.                                                     |
    |                                                                   |
    | [Cancel]                              [Publish New Version]       |
    +------------------------------------------------------------------+

  Change indicators:
    [changed] = --warn text (existing item modified)
    [added] = --accent text (new item)
    [removed] = --alert text (item removed)

  Version type radio:
    - Patch (1.0 -> 1.0.1): minor clarifications, no functional change
    - Minor (1.0 -> 1.1): new capabilities, improved behavior
    - Major (1.0 -> 2.0): breaking behavior change

  Change summary: required textarea (Plus Jakarta Sans 13px). This text
  appears in the tenant notification and in the tenant update review
  (Flow 3B). Minimum 10 characters.

STEP 5: Publish New Version
  Admin selects "Minor" and writes the change summary.
  Clicks [Publish New Version] (accent green primary button).

  PATCH /platform/agent-templates/{id} with new version, updated fields.

  Result:
    - Template stays in Published state
    - Version updates from 1.0.0 to 1.1.0
    - Version History section adds new entry:
        v1.1.0  2026-03-21  Updated system prompt to include benefits...
    - All tenant instances of this template show "Update available" banner
      on their agent card (see Flow 3B for tenant update acceptance)
    - Toast: "HR Policy Advisor v1.1.0 published. 4 tenant instances notified."

STEP 6: Credential Count Increase Validation
  If the update adds new required credentials (e.g., adding a new credential
  field to required_credentials schema), the version modal shows a validation
  warning before allowing publish:

    +------------------------------------------------------------------+
    | [warn] New version requires 1 additional credential              |
    |                                                                   |
    | New credential field: "sso_refresh_token"                         |
    | Tenants must provide this credential before updating to v1.1.0.   |
    | Tenants who accept the update will be prompted to enter the new   |
    | credential in the update review flow.                             |
    +------------------------------------------------------------------+

  This is a non-blocking warning (publish is still allowed). The tenant
  update review flow (Flow 3B) handles the credential entry step.

  ERROR STATE: If removing a required credential that active instances
  depend on, validation error: "Cannot remove credential 'api_secret' --
  3 tenant instances have this credential configured. Deprecate the
  template instead if this credential is no longer needed."
```

**Edge Cases**:

| Scenario                                 | What Happens                                                                                                                                 | Recovery                                                  |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| Non-breaking change only                 | [Save] saves immediately. No version modal. No tenant notification.                                                                          | N/A                                                       |
| Mixed breaking and non-breaking changes  | Version modal shows. All changes (breaking and non-breaking) are published together under the new version.                                   | N/A                                                       |
| Change summary left empty                | [Publish New Version] disabled. Inline error: "Change summary is required (minimum 10 characters)."                                          | Admin writes summary                                      |
| New required_credentials count increases | Warn banner in version modal: "New version requires N additional credentials. Tenants must provide them before updating."                    | Non-blocking; tenant update flow handles credential entry |
| Network error during publish             | Alert toast. Panel stays open with all edits preserved.                                                                                      | Admin retries                                             |
| Concurrent edit by another admin         | On save: 409 Conflict. Alert: "This template was modified by another admin. Please reload and re-apply your changes." [Reload] button shown. | Admin reloads and re-applies                              |

---

## Flow 2C: Platform Admin -- Deprecate Published Template

**Trigger**: Platform admin needs to retire a template from the deployment catalog (no longer offering it for new deployments).
**Persona**: Platform Admin
**Entry**: Template slide-in detail panel > three-dot menu > Deprecate

```
STEP 1: Initiate Deprecation
  Platform admin opens a published template's slide-in detail panel.
  Admin clicks the three-dot menu (top-right, next to [Edit] and [x]).
  Menu items: [Duplicate] [Export Config] [Deprecate]

  Admin clicks [Deprecate].

STEP 2: Confirmation Dialog
  A confirmation dialog appears (centered modal overlay, max-width: 480px,
  --r-lg radius):

    +------------------------------------------------------------------+
    | Deprecate Template                                         [x]   |
    |                                                                   |
    | This template is deployed by 4 tenants.                           |
    |                                                                   |
    | Deprecation means:                                                |
    |   - No new deployments allowed                                    |
    |   - Existing agents continue running until tenant explicitly      |
    |     decommissions them                                            |
    |   - You can restore this template at any time                     |
    |                                                                   |
    | [Cancel]                            [Deprecate Template]          |
    +------------------------------------------------------------------+

  Tenant count: DM Mono, --text-primary. Dynamically queried.
  Bullet points: Plus Jakarta Sans 13px/400, --text-muted.
  [Cancel]: ghost button.
  [Deprecate Template]: --alert background, white text, --r radius.

  If the template has zero deployments, the dialog reads:
  "This template has no active deployments. It will be moved to the
  Deprecated view."

STEP 3: After Deprecation
  Admin clicks [Deprecate Template].
  PATCH /platform/agent-templates/{id} with status='Deprecated'.

  Result:
    - Template card in pa-panel-templates shows "Deprecated" badge
      (--text-faint text, --border background, --r-sm radius)
    - Template row moves to the "Deprecated" filter tab in the template
      table (filter tabs: [All] [Published] [Draft] [Deprecated])
    - Template is removed from tenant deployment catalog
      (GET /agents/templates no longer returns it)
    - Existing tenant agent instances are NOT affected -- they continue
      running on their current template version
    - Toast: "HR Policy Advisor deprecated. 4 existing instances unaffected."

  Tenant notification (sent to all tenants with active instances):
    "The HR Policy Advisor template has been deprecated. Your agents
    using this template continue to work. New deployments are no longer
    available."

  Notification appears in tenant admin's notification area and as an
  info-level banner on affected agent cards (--text-faint color, not
  --warn or --alert -- deprecation is informational, not urgent).

STEP 4: A2A Discovery Impact
  Deprecated agents deployed by tenants are still discoverable via
  A2A discovery (their individual agent cards remain valid and functional).
  Only the template itself is removed from the tenant deployment catalog.
  External A2A clients querying GET /api/v1/agents still see deployed
  instances of this template.

STEP 5: Restore Deprecated Template
  Platform admin navigates to the "Deprecated" filter view in pa-panel-templates.
  Clicks on the deprecated template row to open the slide-in panel.

  The slide-in panel shows:
    - All sections in read-only mode (same as published view)
    - [Restore Template] button in the panel header (accent outline style)
    - No [Edit] button (must restore before editing)

  Admin clicks [Restore Template].
  PATCH /platform/agent-templates/{id} with status='Published'.

  Result:
    - Badge changes from [Deprecated] to [Published]
    - Template returns to the tenant deployment catalog immediately
    - Template moves back to the "Published" filter tab
    - Toast: "HR Policy Advisor restored to Published."
    - No tenant notification on restore (template simply becomes available
      for new deployments again)
```

**Edge Cases**:

| Scenario                                        | What Happens                                                                                                                         | Recovery                            |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------- |
| Deprecate template with zero deployments        | Dialog shows "This template has no active deployments." Still requires confirmation.                                                 | N/A                                 |
| Tenant deploys agent during deprecation request | Race condition handled server-side: deprecation completes, the in-flight deployment succeeds (last-write-wins). Instance is created. | N/A -- instance works normally      |
| Restore and immediately edit                    | After restore, [Edit] button appears. Admin can edit and publish a new version normally (Flow 2B).                                   | N/A                                 |
| Deprecate a template that has pending updates   | Deprecation proceeds. Tenants with "Update available" banners keep those banners -- they can still accept the pending update.        | Tenants can accept update or ignore |

---

## Flow 3: Tenant Admin -- Deploy Template to Workspace

**Trigger**: Tenant admin wants to deploy a pre-built agent template for their users.
**Persona**: Tenant Admin (IT admin, knowledge manager, or department head)
**Entry**: Tenant Admin > Agents (`ta-panel-agents`) > "+ New Agent" > "From Template" (or Agents > Agent Library > template card > [Adopt])

> **Wizard step order (2026-03-21 revision)**: This document supersedes the step order in `02-ux-design-spec.md` Section 3.2. The canonical step order is: (1) Select Template, (2) KB & Tools, (3) Access & Limits, (4) Credentials [conditional]. The UX spec will be updated separately to match.

```
STEP 1: Select Template (Wizard Step 1 of 4)
  Tenant admin clicks "+ New Agent" on ta-panel-agents.
  A selection appears: [From Template] [Custom Agent]
  Admin clicks [From Template].

  A wizard modal opens (max-width: 640px, --r-lg radius, centered).
  Progress bar at top: accent fill at 25%. Label: "Step 1 of 4 -- Select Template"

  The modal shows the template catalog as a scrollable card list:

    +----------------------------------------------------------+
    | [====-------]  Step 1 of 4 -- Select Template            |
    +----------------------------------------------------------+
    |                                                          |
    |  Search templates...  [________________]                 |
    |                                                          |
    |  [HR icon]  HR Policy Advisor                   v1.0.0  |
    |  Answers employee questions about company                |
    |  policies, benefits, and HR procedures.                  |
    |  Auth: No credentials required                           |
    |  [policy_lookup] [benefits_inquiry]                      |
    |                                          [Select]        |
    |  -----------------------------------------------         |
    |  [Finance icon]  Finance Analyst            v3.0.0       |
    |  Provides financial data analysis and                    |
    |  reporting from bound knowledge bases.                   |
    |  Auth: Tenant credentials required                       |
    |  [financial_analysis] [reporting]                        |
    |                                          [Select]        |
    |  -----------------------------------------------         |
    |  [Lock icon]  Bloomberg Intelligence        v2.1.0       |
    |  Requires Enterprise plan                                |
    |  [Contact Admin to Upgrade]         --text-faint         |
    |                                                          |
    +----------------------------------------------------------+
    |  [Cancel]                                                |
    +----------------------------------------------------------+

  Template card info shown per card:
    - Icon + Name (Plus Jakarta Sans 15px/600) + Version (DM Mono 11px)
    - Description (13px/400, --text-muted, max 2 lines with ellipsis)
    - Auth indicator: "No credentials required" or "Tenant credentials required"
    - Capability chips (--bg-elevated, --r-sm, 11px)
    - [Select] button (accent outline)

  Plan-gated templates show locked state:
    - Icon replaced with lock icon
    - Card background: --bg-deep (darker than normal)
    - [Contact Admin to Upgrade] text in --text-faint, no button action
    - [Select] button absent

  Admin clicks [Select] on "HR Policy Advisor."

  VALUE: Tenant admin sees all available templates at a glance with plan
  eligibility, credential requirements, and capability summary -- enough
  information to make a selection without reading documentation.

STEP 2: Configure KB Bindings (Wizard Step 2 of 4)
  Progress bar updates to 50%. Label: "Step 2 of 4 -- Knowledge & Tools"

    +----------------------------------------------------------+
    | [========----]  Step 2 of 4 -- Knowledge & Tools         |
    +----------------------------------------------------------+
    |                                                          |
    |  Deploying: HR Policy Advisor v1.0.0                     |
    |                                                          |
    |  KNOWLEDGE BASES                                         |
    |  Select the document sources this agent can search.      |
    |                                                          |
    |  [x] Employee Handbook                                   |
    |      SharePoint / HR Portal          891 docs            |
    |  [x] Benefits Guide 2026                                 |
    |      SharePoint / HR Portal          124 docs            |
    |  [ ] Procurement Policies                                |
    |      SharePoint / Finance Portal     1,204 docs          |
    |  [ ] Vendor Contracts                                    |
    |      Google Drive / Legal            342 docs            |
    |                                                          |
    |  Search Mode: (*) Parallel  ( ) Priority Order           |
    |  Note: Users must have KB access to see results from     |
    |  each source.                                            |
    |                                                          |
    |  -----------------------------------------------         |
    |                                                          |
    |  TOOLS                                                   |
    |  Enable tools assigned to this template.                 |
    |                                                          |
    |  [x] Jira Issue Reader       Read-Only   Healthy         |
    |  [ ] Confluence Search       Read-Only   Degraded (!)    |
    |                                                          |
    |  Note: Only tools assigned by the platform appear here.  |
    |                                                          |
    +----------------------------------------------------------+
    |  [<-- Back]                    [Next: Access -->]         |
    +----------------------------------------------------------+

  KB list rendering:
    - Checkbox + KB name (Plus Jakarta Sans 13px/500)
    - Source path (11px, --text-faint): "SharePoint / HR Portal"
    - Document count (DM Mono 11px, --text-muted): "891 docs"
    - KBs matching the template's recommended categories (hr_policies,
      employee_handbook, benefits_guide) sort to the top and show a
      subtle accent dot indicator before the name

  KB-required template validation:
    If the template has requires_kb: true AND the tenant selects zero KBs,
    a blocking inline error appears below the KB list:
    "This agent requires at least one knowledge base to answer questions.
    Select a knowledge base, or go to Documents > Data Sources to connect one."
    in --alert color. The [Next] button is disabled.

    Escape hatch: Tenant Admins with Manager role and above see a
    [Continue Anyway] link below the error (--text-faint, 11px). Clicking
    it shows a confirmation: "This agent may not be able to answer questions
    without a knowledge base. Are you sure you want to proceed?"
    with [Cancel] and [Continue Without KB] buttons.

  Tool list rendering:
    - Only tools the platform admin assigned to this template appear
    - Checkbox + tool name + classification badge + health status
    - Degraded tools: --warn colored "(Degraded !)" label
    - If template has zero assigned tools, the TOOLS subsection is hidden

  Tool health validation at deploy:
    - Tool status "Down" + classification "Execute" (core to agent function):
      deployment BLOCKED. Error shown inline below the tool row in --alert:
      "[Tool Name] is currently unavailable. This tool is required for this
      agent to function. Deployment is blocked until the tool is restored."
      The tool checkbox is checked but disabled with --alert border.
    - Tool status "Down" + classification "Read-Only":
      warn-and-proceed. Warn note in --warn: "[Tool Name] is unavailable
      but will not affect core functionality."
    - Tool status "Degraded": warn-and-proceed (existing behavior).
      Warn note in --warn: "[Tool Name] is experiencing issues."

  EMPTY STATE (no KBs synced):
    "No knowledge bases configured. Go to Documents to connect a data source."
    [Go to Documents] is an accent-colored link that closes the wizard and
    calls showTAPanel('documents').

  Admin checks Employee Handbook and Benefits Guide. Leaves Procurement
  unchecked. Enables Jira Issue Reader, leaves Confluence (degraded) unchecked.
  Clicks [Next: Access -->].

STEP 3: Assign Tools and Access (Wizard Step 3 of 4)
  Progress bar: 75%. Label: "Step 3 of 4 -- Access & Limits"

    +----------------------------------------------------------+
    | [============-]  Step 3 of 4 -- Access & Limits          |
    +----------------------------------------------------------+
    |                                                          |
    |  ACCESS CONTROL                                          |
    |  Who can use this agent?                                 |
    |                                                          |
    |  (*) All workspace users                                 |
    |  ( ) Specific roles: [Analyst] [Executive] [+ Add]       |
    |  ( ) Specific users: [search and add users]              |
    |                                                          |
    |  -----------------------------------------------         |
    |                                                          |
    |  RATE LIMITS                                             |
    |  Queries per user per day                                |
    |  [50___]   Platform max: 200    DM Mono                  |
    |                                                          |
    |  -----------------------------------------------         |
    |                                                          |
    |  GUARDRAILS (read-only for template agents)              |
    |  These guardrails are managed by the platform template.  |
    |                                                          |
    |  Confidence Threshold: 0.65          DM Mono             |
    |  Citation Mode: Required                                 |
    |  Active Rules: 2                                         |
    |    - salary_disclosure (block)                            |
    |    - no_legal_advice (block)                              |
    |                                                          |
    +----------------------------------------------------------+
    |  [<-- Back]                     [Next: Review -->]        |
    +----------------------------------------------------------+

  Admin selects "All workspace users" for access.
  Sets rate limit to 50/day (DM Mono input). Platform max shown as
  reference from tenant's plan.

  VALIDATION:
    - Rate limit exceeding plan max: inline error in --alert below field:
      "Exceeds your plan limit of 200/day"
    - Guardrails section is read-only for template-based agents (grayed
      labels, no edit controls). Note in --text-faint: "Guardrails are
      managed by the platform template."

STEP 4: Enter Credentials (Conditional -- Only When Required)
  For "HR Policy Advisor" (auth_mode = none), this step is SKIPPED entirely.
  The wizard shows 3 steps total (Step 1: Select, Step 2: KB/Tools,
  Step 3: Access & Limits), and the final step has [Deploy Agent] as CTA.

  IF the template had auth_mode = "tenant_credentials" (e.g., Bloomberg
  Intelligence), this would appear as Step 3, shifting Access to Step 4:

    +----------------------------------------------------------+
    | [========----]  Step 3 of 4 -- Connect Credentials       |
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
    |  (idle: outlined neutral button)                         |
    |  (testing: spinner + "Validating...")                    |
    |  (passed: accent check + "Connected: acme@bloomberg")    |
    |  (failed: alert X + error message + "Retry")            |
    |  (untested: warn note, no test button shown)             |
    |                                                          |
    +----------------------------------------------------------+
    |  [<-- Back]                      [Next: Access -->]      |
    +----------------------------------------------------------+

  Sensitive fields (sensitive: true in schema) render as password inputs
  with a show/hide eye toggle, right-aligned inside the input.

  [Test Connection] calls POST /api/v1/admin/agents/test-credentials async.
  During test: spinner replaces button text, all inputs disabled.
  On success: accent-colored banner with masked account info.
  On failure: alert-colored error below button. Inputs re-enable.
  Testing is optional -- admin can proceed without testing, but a --warn
  note appears: "Credentials not validated. The agent may fail if
  credentials are incorrect."

  ERROR STATE -- Credential vault check fails:
    If the POST returns 422 (vault unreachable, schema mismatch, or
    credential format invalid), the error is shown inline below the
    [Test Connection] button in --alert color:
    "Credential validation failed: {specific error message}"
    The admin can correct the values and retry without leaving the step.

FINAL: Deploy Confirmation
  On the last wizard step, the CTA changes to [Deploy Agent] (accent green
  filled button, Plus Jakarta Sans 13px/600).

  Admin clicks [Deploy Agent].
  POST /agents/templates/{id}/deploy with KB bindings, tool enablement,
  access control, credentials (if any), and rate limits.

  Deploy processing:
    - Full-screen overlay within the modal: spinner + "Deploying agent..."
      (Plus Jakarta Sans 14px/500, --text-muted)
    - Typical duration: 2-5 seconds

  Success state:
    - Overlay replaces with success confirmation:
      [accent checkmark icon, 44px]
      "HR Policy Advisor deployed successfully"
      "2 knowledge bases bound -- 1 tool enabled -- All users"
      [Go to Agents] (primary) [Deploy Another] (ghost)
    - Toast notification: "HR Policy Advisor is ready for your team"
    - Agent card created in ta-panel-agents grid with active status

  New agent card in ta-panel-agents:
    +----------------------------------------------------------+
    | [HR icon]  HR Policy Advisor                             |
    |            Template v1.0.0 -- Deployed Mar 2026          |
    |                                                          |
    |  [2 KBs]  [1 tool]                                      |
    |                                                          |
    |  Employee Handbook -- SharePoint                         |
    |                                                          |
    |  [==============================--------]  0%            |
    |  0 rated responses           New                         |
    |                                                          |
    |  [Analytics]  [Configure]  [Test Chat]                   |
    +----------------------------------------------------------+

  Badge row: DM Mono 11px, --bg-elevated background, --border outline.
  "0%" and "0 rated responses" in DM Mono -- fresh agent with no data yet.
```

**Edge Cases**:

| Scenario                              | What Happens                                                                                                                                 | Recovery                                                    |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| No KBs available                      | Empty state in Step 2 KB section. Wizard allows proceeding (some agents use real-time data, not KBs).                                        | Admin can deploy without KBs or go to Documents panel first |
| Template requires KB, no KBs selected | Inline block error with link to Documents: "This agent requires at least one knowledge base." [Next] disabled.                               | Admin selects a KB or connects a data source                |
| Credential test fails                 | Alert error inline. Admin can retry, fix values, or skip. If skipped, agent created with status pending_validation; card shows --warn state. | Admin updates credentials post-deploy via Configure         |
| Plan gate blocks template             | Template card shows locked state with "Requires {Plan} plan. Contact Admin to Upgrade." [Select] button absent.                              | Admin contacts billing/platform admin                       |
| All assigned tools degraded           | Warn banner in Step 2 Tools section: "Some tools are experiencing issues. The agent may have limited capabilities."                          | Admin can deploy; tool health is platform-monitored         |
| Required Execute-class tool is Down   | Deploy blocked, inline alert on tool row, link to check tool status page.                                                                    | Admin waits for tool restoration or contacts platform admin |
| Duplicate agent name in workspace     | Inline error after [Deploy Agent]: "An agent named 'HR Policy Advisor' already exists in your workspace." Deploy does not proceed.           | Admin returns to Step 1 and edits the display name          |

---

## Flow 3B: Tenant Admin -- Review and Accept Template Update

**Trigger**: Platform admin has published a new version of a template, and a tenant admin's deployed agent shows "Update Available."
**Persona**: Tenant Admin
**Entry**: Tenant Admin > Agents (`ta-panel-agents`) > [Agent Card with "Update Available" banner] > "Review Update" button

```
STEP 1: View Update Notification
  The tenant admin's agent card shows an "Update available" banner:

    +----------------------------------------------------------+
    | [HR icon]  HR Policy Advisor                             |
    |            Template v1.0.0 -- Deployed Mar 2026          |
    |            [v1.1.0 available -->]      accent, clickable |
    |                                                          |
    |  [2 KBs]  [1 tool]                                      |
    |  ...                                                     |
    +----------------------------------------------------------+

  Admin clicks [v1.1.0 available -->] on the agent card, or opens the
  agent detail slide-in and clicks [Review Update] button.

STEP 2: Diff View (Slide-In Panel)
  A slide-in panel opens from the right showing the update diff:

    +----------------------------------------------------------+
    | x  Template Update: HR Policy Advisor                    |
    |    Version 1.0.0 --> 1.1.0                    DM Mono    |
    +----------------------------------------------------------+
    |                                                          |
    |  WHAT CHANGED                                            |
    |                                                          |
    |  Change Summary (from platform admin):                   |
    |  "Updated system prompt to include benefits enrollment   |
    |  deadlines. Added performance data guardrail rule."      |
    |                                                          |
    |  -----------------------------------------------         |
    |                                                          |
    |  SYSTEM PROMPT                              [changed]    |
    |                                                          |
    |  - "You are an HR Policy Advisor for {{org_name}}..."    |
    |  + "You are an HR Policy Advisor for {{org_name}}...     |
    |  +  When answering benefits questions, always include    |
    |  +  the enrollment deadline if applicable."              |
    |                                                          |
    |  (diff view: removed lines in --alert background,        |
    |   added lines in --accent background, DM Mono 12px)      |
    |                                                          |
    |  -----------------------------------------------         |
    |                                                          |
    |  GUARDRAIL RULES                            [1 added]    |
    |                                                          |
    |  + no_performance_data (keyword_block, block)            |
    |    "Performance data is confidential..."                  |
    |                                                          |
    |  Existing rules unchanged:                               |
    |    salary_disclosure (block)                              |
    |    no_legal_advice (block)                                |
    |                                                          |
    +----------------------------------------------------------+
    |  [Dismiss for Now]              [Accept Update]          |
    +----------------------------------------------------------+

  Diff rendering:
    - Section headers: Plus Jakarta Sans 11px uppercase, --text-faint
    - [changed] badge: --warn background, DM Mono 11px
    - [added] badge: --accent background, DM Mono 11px
    - [removed] badge: --alert background, DM Mono 11px
    - Diff lines: DM Mono 12px, removed = --alert-dim background,
      added = --accent-dim background

STEP 3: Credential Entry (Conditional)
  If the new version requires additional credentials not in the current
  deployment, a credential entry section appears below the diff:

    +----------------------------------------------------------+
    |  NEW CREDENTIALS REQUIRED                      [warn]    |
    |                                                          |
    |  This version requires 1 additional credential.          |
    |                                                          |
    |  SSO Refresh Token                                       |
    |  [________________________________]   [Show/Hide]        |
    |  Required for the new SSO integration                    |
    |                                                          |
    |  [Test Connection]                                       |
    +----------------------------------------------------------+

  Same credential entry UX as Flow 3 Step 4 (test connection, show/hide,
  validation). [Accept Update] is disabled until all new credential fields
  are filled.

  If no new credentials are required, this section is absent.

STEP 4: Accept or Dismiss
  [Dismiss for Now]:
    - Hides the "Update available" banner for 7 days
    - Agent card shows a subtle "1.1 available" badge (DM Mono 11px,
      --text-faint) instead of the prominent banner
    - After 7 days, the full banner reappears
    - Admin can always re-access the update from Configure > Updates

  [Accept Update]:
    - PATCH /api/v1/admin/agents/{id}/update-template with version=1.1.0
      and new credentials (if any)
    - Processing overlay: "Updating agent..." with spinner
    - On success:
      - Agent card version updates to "Template v1.1.0"
      - "Update available" banner disappears
      - Toast: "HR Policy Advisor updated to v1.1.0"
      - Agent immediately uses the new system prompt and guardrail rules
    - [Accept Update] — updates apply to all new messages immediately.
      No conversation data is lost. Follow-up messages in existing
      conversation threads will use the new system prompt. Note: if
      you notice a significant change in agent behavior mid-conversation,
      start a new conversation for a clean context.

  VALUE: Tenant admin sees exactly what changed, can review the impact,
  and accepts the update with full awareness. No surprise behavior changes.
```

**Edge Cases**:

| Scenario                                           | What Happens                                                                                                                                                                                                                                                    | Recovery                                                           |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Agent has in-progress conversations at update time | Active conversations: template updates apply to the next message in any conversation (the system prompt updates per-request). Users mid-conversation may notice a change in agent behavior. For major version changes (v1 → v2), consider notifying your users. | No rollback needed; update is non-destructive to conversation data |
| Multiple version updates pending (1.0 -> 1.2)      | Diff shows cumulative changes from current version to latest. Intermediate versions listed in version history.                                                                                                                                                  | N/A -- single update to latest                                     |
| New credentials required but tenant skips test     | Same as Flow 3: warn note "Credentials not validated." Agent status shows pending_validation after update.                                                                                                                                                      | Admin tests credentials post-update via Configure                  |
| Template deprecated after update published         | "Update available" banner remains. Tenant can still accept the update. Deprecation info banner also shown.                                                                                                                                                      | Tenant accepts update (gets latest version of retired template)    |
| Dismiss expires after 7 days                       | Full "Update available" banner reappears on agent card.                                                                                                                                                                                                         | Admin reviews and accepts or dismisses again                       |

**Note**: Future: A `template_version` field on conversation records would enable version-pinning (preserving old prompt for conversation duration). This is deferred to Phase C.

---

## Flow 4: End User -- Chat with A2A-Compliant Agent (Guardrail Triggered)

**Trigger**: HR employee asks a question that violates a configured guardrail rule.
**Persona**: End User (HR department employee)
**Entry**: End User chat interface, HR Policy Advisor agent selected via mode selector

```
STEP 1: Select Agent and Open Chat
  End user is in the chat interface. The input bar has a mode selector
  dropdown: [Auto / Finance / HR Policy Advisor / IT Helpdesk / ...]
  User selects "HR Policy Advisor."

  The chat is in empty state (centered layout):
    - Agent icon (44x44px) centered
    - Greeting: "HR Policy Advisor" (Plus Jakarta Sans 22px/700)
    - Subtitle: "Ask me about company policies, benefits, and HR procedures."
      (13px/400, --text-muted)
    - Input bar embedded (not bottom-fixed), centered below greeting
    - KB hint below input: "Employee Handbook -- SharePoint -- 891 documents indexed"
      (11px, --text-faint, accent dot indicator)
      Note: KB hint uses resolved names, never raw "RAG ." prefix or UUIDs
    - If the agent has tools enabled, a tool hint appears below the KB hint:
      "Can search Jira" -- 11px, --text-faint, accent dot separator.
      Multiple tools: "Can search Jira -- Can pull Confluence data"
    - Suggestion chips: [What's our PTO policy?] [Benefits enrollment dates]
      [Parental leave policy]

STEP 2: User Sends a Blocked Topic Query
  User types: "What's the CEO's salary?"
  Presses Enter or clicks send.

  Chat transitions to active state:
    - Input bar moves to bottom-fixed position
    - Messages area appears (max-width: 860px, centered)
    - User message renders right-aligned:
      "What's the CEO's salary?"
      (--bg-elevated background, 1px --border, --r-lg radius, max-width 68%)

STEP 3: Buffered Processing (Guardrail-Enabled Agent)
  The LLM generates the complete response -- but unlike standard agents,
  this agent has guardrails configured. The orchestrator BUFFERS the LLM
  output internally. The user sees a "Thinking..." indicator (not the usual
  live token stream) until the full response is ready. This is expected
  behavior for guardrail-enabled agents -- 1-2 second additional latency
  before first token appears.

  The processing pipeline:
    1. Intent detection (GPT-5 Mini, <1s)
    2. Embedding generation
    3. Vector search against bound KBs (Employee Handbook, Benefits Guide)
    4. Context building
    5. LLM synthesis (GPT-5.2-chat) -- full response buffered internally
    6. Output guardrail check (next step)

  The AI response area appears below the user message with no box, no card,
  no border -- text flows directly on --bg-base (per design system rule).

  Meta row appears:
    "HR POLICY ADVISOR -- KNOWLEDGE" in --accent, 11px uppercase, letter-spacing
    .06em + confidence pill (DM Mono 11px)

  Below the meta row, "Thinking..." indicator pulses (Plus Jakarta Sans
  13px, --text-faint, subtle opacity animation 220ms ease).

STEP 4: Output Guardrail Check (Stage 7.5)
  The complete buffered response is scanned by the output filter.

  The salary_disclosure guardrail rule detects a match:
    Rule: salary_disclosure (keyword_block)
    Pattern matched: "CEO salary" in the query context + response contains
    compensation data patterns
    Action: block

  The SSE stream emits a guardrail event:
    event: guardrail_triggered
    data: {
      "action": "block",
      "rule_id": "salary_disclosure",
      "user_message": "Salary and compensation details are confidential.
       Please contact HR directly for compensation inquiries."
    }

  Note: The SSE event contains ONLY the user-safe message and action type.
  It does NOT contain: the rule's regex patterns, the internal rule
  configuration, the system prompt content, or the original LLM response
  that was blocked.

STEP 5: User Sees Guardrail Response
  The safe fallback message streams to the user, appearing as if it were
  the normal response. The "Thinking..." indicator is replaced by the
  streamed message. The user sees clean, seamless output with no indication
  of the internal replacement.

  The response area shows:

    HR POLICY ADVISOR -- KNOWLEDGE                     --accent, 11px

    Salary and compensation details are confidential.
    Please contact HR directly for compensation inquiries.

    (14px/1.6, Plus Jakarta Sans, --text-primary)
    (no source footer -- blocked responses have no citations)

    [thumbs up] [thumbs down]                         feedback row

  The response renders with the same typography and positioning as a
  normal AI response -- no special "error" styling, no red borders,
  no alert icons. The message is designed to feel like a natural agent
  boundary, not a system error.

  What the user does NOT see:
    - No indication that a "guardrail" or "filter" exists
    - No rule name ("salary_disclosure")
    - No regex pattern details
    - No system message or prompt content
    - No "blocked by policy" banner or error state styling
    - No reference to the output filter mechanism

  The experience from the user's perspective: the agent simply does not
  help with salary questions and redirects them appropriately.

STEP 6: Feedback Still Works
  The feedback row (thumbs up/down) is visible and functional.
  If the user clicks thumbs down, the standard feedback flow triggers.
  The guardrail violation is logged separately in the compliance audit
  trail (visible to tenant admin and platform admin, not to end user).

  VALUE: The user experiences a clear, helpful boundary without any
  awareness of the enforcement mechanism. The agent feels knowledgeable
  and professional, not broken or restricted.
```

> **UX Note**: Guardrail-enabled agents have slightly higher first-response latency (~1-2s extra) because the orchestrator must complete the full LLM synthesis before streaming begins. This is by design and necessary for regulated deployments. Standard (non-guardrail) agents continue to stream tokens in real time.

**Edge Cases**:

| Scenario                                     | What Happens                                                                                                                                                        | Recovery                                             |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Guardrail action = redact (not block)        | The LLM response streams normally but offending phrases are replaced inline with the replacement text (e.g., "[REDACTED]"). No interruption to streaming.           | User sees a complete response with redacted sections |
| Guardrail action = warn                      | The full LLM response is shown. A warning footer appends below: "Note: {warning message}" in --text-muted 12px.                                                     | User sees the response plus the warning              |
| Output filter throws exception (fail-closed) | LLM response is NOT shown. Safe canned message: "Response could not be processed. Please try again." No error details. Circuit breaker alerts platform.             | User retries; platform admin investigates            |
| Multiple guardrail rules trigger             | First matching rule's action takes precedence (block > redact > warn). Only one user message shown. All violations logged in audit trail.                           | N/A                                                  |
| User asks follow-up about the boundary       | The agent treats it as a new query. If the follow-up also matches the blocked topic, the same guardrail message appears. The agent does not explain its guardrails. | User contacts HR directly as instructed              |

---

## Flow 5: Tenant Admin -- View Agent Card A2A Capabilities

**Trigger**: Tenant admin wants to audit what a deployed agent can do, what data it accesses, and its compliance status.
**Persona**: Tenant Admin
**Entry**: Tenant Admin > Agents (`ta-panel-agents`) > agent row > click for detail

```
STEP 1: Open Agent Detail Panel
  Tenant admin is on ta-panel-agents, viewing the agent card grid.
  Admin clicks on the "HR Policy Advisor" card (anywhere on the card,
  or the [Configure] action button).

  A slide-in detail panel opens from the right (consistent with TA
  drill-down pattern for agent configuration).

  Panel header:
    "HR Policy Advisor"
    [Active] badge (accent background, dark text, --r-sm radius)
    [x] close button top-right

STEP 2: View KB Bindings
  First section: "Knowledge Bases"

    +----------------------------------------------------------+
    | KNOWLEDGE BASES                                   2 bound |
    |                                                          |
    | Employee Handbook                                        |
    |   SharePoint / HR Portal       891 docs     Synced       |
    |   Last sync: 2 hours ago                                 |
    |                                                          |
    | Benefits Guide 2026                                      |
    |   SharePoint / HR Portal       124 docs     Synced       |
    |   Last sync: 2 hours ago                                 |
    |                                                          |
    | Search Mode: Parallel                                    |
    +----------------------------------------------------------+

  KB names are resolved display names (Plus Jakarta Sans 13px/500),
  never raw UUIDs or integration IDs.
  Source path: 11px, --text-faint
  Document count: DM Mono 11px
  Sync status: "Synced" in --accent, "Stale" in --warn, "Error" in --alert
  Last sync: DM Mono 11px, --text-faint

  VALUE: Admin immediately sees which document sources the agent queries,
  how many documents are indexed, and whether the data is current --
  without navigating to the Documents panel.

STEP 3: View Tool Assignments
  Second section: "Tools"

    +----------------------------------------------------------+
    | TOOLS                                          1 enabled |
    |                                                          |
    | Jira Issue Reader                                        |
    |   Read-Only     [Healthy]                                |
    |                                                          |
    | Confluence Search                     (disabled by admin)|
    |   Read-Only     [Degraded]                               |
    +----------------------------------------------------------+

  Tool name: Plus Jakarta Sans 13px/500
  Classification badge: "Read-Only" with accent dot
  Health status badge:
    [Healthy] = DM Mono 11px, --accent text, accent-dim background
    [Degraded] = DM Mono 11px, --warn text, warn-dim background
    [Down] = DM Mono 11px, --alert text, alert-dim background
  Disabled tools: grayed row with "(disabled by admin)" note in --text-faint

STEP 4: View Guardrail Summary
  Third section: "Guardrails"

    +----------------------------------------------------------+
    | GUARDRAILS                            2 rules active     |
    |                                                          |
    | Active Rules:                                            |
    |   salary_disclosure        keyword_block    block        |
    |   no_legal_advice          keyword_block    block        |
    |                                                          |
    | Confidence Threshold: 0.65                   DM Mono     |
    | Citation Mode: Required                                  |
    | Max Response Length: 1,500 tokens            DM Mono     |
    |                                                          |
    | Last Violation: 2026-03-20 14:32 UTC         DM Mono     |
    |   Rule: salary_disclosure                                |
    |   Action: blocked                                        |
    |                                                          |
    | [View Violation Log]                                     |
    +----------------------------------------------------------+

  Rule summary table: rule name in DM Mono 12px, type and action in
  Plus Jakarta Sans 11px, --text-muted.
  "2 rules active" count in DM Mono 11px, --text-muted.
  Last violation: timestamp in DM Mono 11px. If no violations ever,
  shows "No violations recorded" in --text-faint.
  [View Violation Log] links to a filtered view of the agent's compliance
  events (see Flow 7 for full audit view).

  Note: Guardrail rule patterns (regex) are NOT shown to tenant admin.
  Only rule names, types, and actions are visible. The platform owns
  the guardrail implementation details.

STEP 5: View Credential Status
  Fourth section: "Credentials" (only shown when auth_mode != none)

  For HR Policy Advisor (auth_mode = none), this section is hidden entirely.

  For a Bloomberg agent (auth_mode = tenant_credentials), it would show:

    +----------------------------------------------------------+
    | CREDENTIALS                                              |
    |                                                          |
    | Bloomberg BSSO Client ID           [check] stored        |
    | Bloomberg BSSO Client Secret       [check] stored        |
    |                                                          |
    | Last health check: 6 hours ago    DM Mono 11px           |
    | Status: Healthy                   DM Mono, --accent      |
    |                                                          |
    | [Update Credentials]                                     |
    +----------------------------------------------------------+

  Each required credential shows:
    [check] stored = accent checkmark + "stored" (credentials exist in vault)
    [X] missing = alert X + "missing" (credential never provided or deleted)

  Credential values are NEVER shown. Only storage status.
  Health check timestamp: DM Mono 11px, --text-faint
  Status: DM Mono 11px -- "Healthy" in --accent, "Failed" in --alert,
  "Unverified" in --warn
  [Update Credentials] opens a modal to replace credential values
  (fields show "[encrypted]" with "Replace" action per field).

STEP 6: View A2A Metadata
  Fifth section: "A2A Configuration"

    +----------------------------------------------------------+
    | A2A CONFIGURATION                                        |
    |                                                          |
    | Agent URL:                                               |
    | https://api.mingai.com/a2a/agents/hr-policy-advisor      |
    |   DM Mono 12px, --text-muted, truncated with copy button |
    |                                                          |
    | Capabilities:                                            |
    | [policy_lookup] [benefits_inquiry] [leave_balance]       |
    |                                                          |
    | Template: HR Policy Advisor v1.0.0                       |
    | Deployed: 2026-03-21                    DM Mono 11px     |
    | Agent ID: ag_7f3k2m9x                  DM Mono 11px     |
    +----------------------------------------------------------+

  Agent URL: DM Mono 12px with a copy-to-clipboard icon button.
  Capability chips: --bg-elevated, --r-sm, 11px.
  Agent ID: DM Mono 11px, --text-faint (internal reference, not prominently
  displayed).

  VALUE: The admin has a complete view of the agent's configuration,
  health status across all dimensions (KB freshness, tool health,
  credential status, guardrail compliance), and A2A identity -- all
  in a single scrollable panel without navigating away.
```

**Edge Cases**:

| Scenario                        | What Happens                                                                                                                                                  | Recovery                                        |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| KB sync stale > 30 days         | KB row shows "Stale" in --alert with last sync timestamp. Agent card in grid has alert border.                                                                | Admin navigates to Documents to trigger re-sync |
| Credential health check failed  | Credential status: "Failed" in --alert. Alert banner on agent card: "Credentials expired -- agent cannot access Bloomberg"                                    | Admin clicks [Update Credentials] to replace    |
| Template update available       | Below the template version line: "v1.1.0 available -->" in --accent, clickable. Opens inline expansion with changelog and [Review Changes] [Dismiss] actions. | Admin reviews and accepts or dismisses          |
| Tool force-disabled by platform | Tool row grayed out with: "Disabled by platform administration" in --text-faint. Unclickable.                                                                 | Admin contacts platform admin                   |

---

## Flow 5B: Tenant Admin -- Reconfigure Deployed Agent

**Trigger**: Tenant admin needs to adjust a deployed agent's configuration (KB bindings, tool toggles, access control, rate limits).
**Persona**: Tenant Admin
**Entry**: Tenant Admin > Agents (`ta-panel-agents`) > [Agent Card] > Configure button (or three-dot > Configure)

```
STEP 1: Open Agent Configuration Panel
  Tenant admin clicks [Configure] on an agent card in ta-panel-agents.
  The slide-in detail panel opens with configuration sections in edit mode.

  Panel header:
    "Configure: HR Policy Advisor"
    [Active] badge
    [x] close button top-right

  The panel shows editable sections for what the tenant admin CAN change,
  and read-only sections for what is locked to the template.

STEP 2: Editable Configuration Sections

  KNOWLEDGE BASES (editable)
    +----------------------------------------------------------+
    | KNOWLEDGE BASES                                   2 bound |
    |                                                          |
    | [x] Employee Handbook                                    |
    |     SharePoint / HR Portal       891 docs                |
    | [x] Benefits Guide 2026                                  |
    |     SharePoint / HR Portal       124 docs                |
    | [ ] Procurement Policies                                 |
    |     SharePoint / Finance Portal  1,204 docs              |
    |                                                          |
    | Search Mode: (*) Parallel  ( ) Priority Order            |
    +----------------------------------------------------------+

  Admin can add/remove KB sources. If removing the last KB from a
  KB-dependent agent (requires_kb: true), a blocking warning appears:
  "This agent requires at least one knowledge base to answer questions.
  Removing the last KB will prevent the agent from functioning."
  with [Cancel] and [Remove Anyway] (--alert text).

  TOOLS (editable -- toggle only)
    +----------------------------------------------------------+
    | TOOLS                                          1 enabled |
    |                                                          |
    | [x] Jira Issue Reader       Read-Only   Healthy          |
    | [ ] Confluence Search       Read-Only   Degraded (!)     |
    |                                                          |
    | Note: Only tools assigned to this template can be        |
    | enabled. Contact your platform admin to add new tools.   |
    +----------------------------------------------------------+

  Admin can enable/disable tools that were assigned to the template by
  the platform admin. Cannot add tools not in the original template.

  ACCESS CONTROL (editable)
    +----------------------------------------------------------+
    | ACCESS CONTROL                                           |
    |                                                          |
    | (*) All workspace users                                  |
    | ( ) Specific roles: [+ Add role]                         |
    | ( ) Specific users: [+ Add user]                         |
    +----------------------------------------------------------+

  Admin can change from workspace_wide to role_restricted or user-specific.
  Role/user picker uses existing TA user management patterns.

  RATE LIMITS (editable)
    +----------------------------------------------------------+
    | RATE LIMITS                                              |
    |                                                          |
    | Queries per user per day                                 |
    | [50___]   Platform max: 200    DM Mono                   |
    +----------------------------------------------------------+

  Adjustable within tenant plan limits. Same validation as deploy wizard.

STEP 3: Read-Only Sections (Locked to Template)

  SYSTEM PROMPT (read-only)
    Displayed as read-only monospace text (DM Mono 12px, --bg-deep
    background, --border, --r radius). Note: "System prompt is managed
    by the platform template and cannot be modified." in --text-faint.

  GUARDRAILS (read-only)
    Same display as Flow 5 Step 4. Note: "Guardrail rules are managed
    by the platform template." in --text-faint.

  CREDENTIALS (values editable, structure locked)
    Admin can update credential values (click "Replace" on each field
    to enter new values) but cannot remove credential entries required
    by the template schema. Cannot add credential fields not in the
    template schema.

STEP 4: Save Changes
  Admin clicks [Save] (accent green primary button, bottom of panel).

  Changes apply immediately -- no redeployment needed. The agent continues
  operating with updated configuration.

  PATCH /api/v1/admin/agents/{id}/configure with updated bindings.

  Success: Toast "Configuration updated." Panel remains open showing
  the new state.

  VALUE: Tenant admin can tune agent behavior (which data sources,
  which tools, who has access) without redeploying or involving
  platform admin. Template-controlled settings remain consistent
  across all instances.
```

**Edge Cases**:

| Scenario                                      | What Happens                                                                                                | Recovery                                    |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| Remove last KB when requires_kb = true        | Blocking warning: "Agent requires at least one KB." [Remove Anyway] available but with confirmation dialog. | Admin keeps at least one KB or acknowledges |
| Disable all tools                             | Allowed. Info note: "No tools enabled. The agent will rely on knowledge bases only."                        | N/A -- valid configuration                  |
| Change access from all users to specific role | Immediate effect. Users not in the specified role lose access on next query.                                | N/A -- expected behavior                    |
| Rate limit set to 0                           | Inline error: "Rate limit must be at least 1 query per day." [Save] disabled.                               | Admin sets a valid rate limit               |
| Credential replace fails test                 | Same as deploy wizard: alert error inline, can retry or skip.                                               | Admin fixes credential value                |

---

## Flow 6: External A2A Client -- Discover Platform Capabilities

**Trigger**: An external AI agent or service wants to discover what agents are available on the mingai platform.
**Persona**: External A2A Client (machine-to-machine, no human UI)
**Entry**: GET /.well-known/agent.json (unauthenticated HTTP request)

> **Agent name confidentiality**: The per-tenant agent listing at /api/v1/agents is authenticated. Tenant admins can configure agent visibility: each agent card has a "Public name" field (shown in A2A discovery) and an "Internal name" (hidden from external discovery). Default: agent name used as public name.

```
STEP 1: Send Discovery Request
  The external A2A client sends an HTTP GET request:
    GET https://api.mingai.com/.well-known/agent.json
    No Authorization header (A2A discovery is public per protocol spec)

STEP 2: Receive Platform-Level AgentCard
  The endpoint returns a platform-level discovery document (A2A v0.3 format):

    HTTP/1.1 200 OK
    Content-Type: application/json
    Cache-Control: public, max-age=3600

    {
      "name": "mingai",
      "description": "Enterprise RAG platform with multi-tenant agent deployment",
      "url": "https://api.mingai.com",
      "version": "1.0.0",
      "provider": {
        "organization": "Obsidian Intelligence",
        "url": "https://obsidianintelligence.com"
      },
      "capabilities": {
        "streaming": true,
        "pushNotifications": false
      },
      "authentication": {
        "schemes": ["bearer"],
        "credentials": {
          "token_url": "https://auth.mingai.com/oauth2/token"
        }
      },
      "defaultInputModes": ["text"],
      "defaultOutputModes": ["text"],
      "endpoints": {
        "chat": "/api/v1/chat/stream",
        "agents": "/api/v1/agents"
      }
    }

  What the response contains:
    - Platform name, version, and provider identity
    - Streaming capability flag (true -- SSE streaming supported)
    - Authentication method: bearer token with OAuth2 token URL
    - Endpoint paths for chat and agent listing
    - Input/output modes (text only for now)

STEP 3: What the Response Does NOT Contain (Security Boundary)
  The discovery endpoint is strictly platform-level. It does NOT expose:

    - Individual agent cards or agent IDs
    - System prompts or prompt templates
    - KB bindings, tool configurations, or guardrail rules
    - Tenant data, tenant IDs, or tenant-specific configurations
    - Credential schemas or vault paths
    - Internal architecture details (pipeline stages, LLM models used)

  To discover individual agents, the external client must:
    1. Authenticate via the token_url (OAuth2 client credentials flow)
    2. Call GET /api/v1/agents with a valid bearer token
    3. The response is scoped to the tenant associated with the token
       (no cross-tenant agent discovery)

  VALUE: External systems can discover that mingai exists and how to
  authenticate, without exposing any tenant-specific or agent-specific
  data. This follows the A2A v0.3 standard for platform-level discovery.

STEP 4: Rate Limiting
  The endpoint is rate-limited to 10 requests per second per IP address.
  Exceeding the limit returns:

    HTTP/1.1 429 Too Many Requests
    Retry-After: 1

    { "error": "Rate limit exceeded", "retry_after_seconds": 1 }
```

**Edge Cases**:

| Scenario                                     | What Happens                                                                                                                                             | Recovery                                                 |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Endpoint receives POST/PUT/DELETE            | HTTP 405 Method Not Allowed with Allow: GET header                                                                                                       | Client switches to GET                                   |
| Rate limit exceeded                          | HTTP 429 with Retry-After header                                                                                                                         | Client backs off per Retry-After                         |
| Platform in maintenance mode                 | HTTP 503 Service Unavailable with maintenance message                                                                                                    | Client retries later                                     |
| Request with query params for specific agent | Query params are ignored. Only the platform-level card is returned. Agent-specific discovery requires authentication.                                    | Client authenticates and uses /api/v1/agents             |
| PUBLIC_BASE_URL not configured               | Endpoint returns HTTP 503 with `{"error": "Platform discovery not configured. Contact your administrator."}`. Platform alert triggered on first request. | Platform admin configures PUBLIC_BASE_URL in environment |

---

## Flow 7: Platform Admin -- Monitor Guardrail Violations

**Trigger**: Platform admin needs to review compliance events for audit or incident investigation.
**Persona**: Platform Admin (compliance officer, platform operations)
**Entry**: Platform Admin > Agent Templates (`pa-panel-templates`) > template row > click for detail > Compliance tab

```
STEP 1: Navigate to Template Compliance View
  Platform admin is on pa-panel-templates.
  Admin clicks on the "HR Policy Advisor" template row to open the
  slide-in detail panel.

  The panel has tab navigation at the top (consistent with admin tab pattern):
    [Overview]  [Compliance]  [Instances]  [Version History]

  Tab styling:
    - 12px/500, Plus Jakarta Sans
    - Inactive: --text-faint, 2px transparent bottom border
    - Active: --text-primary, 2px --accent bottom border
    - Tab row: 1px --border bottom, 20px margin-bottom

  Admin clicks [Compliance] tab.

STEP 2: View Violations Log
  The Compliance tab shows a filterable table of guardrail violation events:

    +----------------------------------------------------------+
    | GUARDRAIL VIOLATIONS                     47 total events |
    |                                                          |
    | Filters:                                  [Export CSV]    |
    | Date Range: [2026-03-01] to [2026-03-21]                 |
    | Rule: [All Rules v]                                      |
    | Action: [All Actions v]                                  |
    | Tenant: [All Tenants v]                                  |
    |                                                          |
    | +------------------------------------------------------+ |
    | | Timestamp          | Rule              | Action | Ten | |
    | |--------------------+-------------------+--------+-----| |
    | | 2026-03-20 14:32   | salary_disclosure | block  | Acm | |
    | | 2026-03-20 11:17   | no_legal_advice   | block  | Glo | |
    | | 2026-03-19 09:45   | salary_disclosure | block  | Acm | |
    | | 2026-03-18 16:03   | no_legal_advice   | block  | Tec | |
    | | 2026-03-18 15:58   | salary_disclosure | block  | Acm | |
    | | ...                                                    | |
    | +------------------------------------------------------+ |
    |                                                          |
    | Showing 1-20 of 47          [< Prev]  [Next >]          |
    +----------------------------------------------------------+

  [Export CSV] button: positioned in the filter bar row, right-aligned
  (not at the bottom of the table). Ghost button style, DM Mono 11px.

  Table columns:
    - Timestamp: DM Mono 12px (ISO 8601, UTC)
    - Rule: DM Mono 12px (rule_id)
    - Action: DM Mono 11px -- "block" in --alert, "redact" in --warn,
      "warn" in --text-muted
    - Tenant: Plus Jakarta Sans 13px/500 (truncated, full name on hover)
    - Conversation ID: DM Mono 11px, --text-faint (truncated with copy button)

  Table header: 11px uppercase, letter-spacing .05em, --text-faint
  Row hover: background: var(--accent-dim)
  Pagination: DM Mono 11px

STEP 3: Filter Violations
  Admin uses the filter controls:

  Date Range: date picker inputs (DM Mono, --bg-elevated background).
  Default range: last 30 days.

  Rule: dropdown populated from the template's guardrail rules:
    [All Rules] / [salary_disclosure] / [no_legal_advice]

  Action: dropdown: [All Actions] / [block] / [redact] / [warn]

  Tenant: dropdown populated from tenants that have deployed this template:
    [All Tenants] / [Acme Capital] / [GlobalFin Corp] / [TechStart Inc]

  Filters apply immediately on selection (no "Apply" button needed).
  Table updates with filtered results. Count updates: "12 of 47 events"

STEP 4: Drill Down to Violation Detail
  Admin clicks on a violation row (2026-03-20 14:32, salary_disclosure).

  An inline expansion opens below the row (not a new panel -- stays in
  context of the violations table):

    +----------------------------------------------------------+
    | VIOLATION DETAIL                                         |
    |                                                          |
    | Timestamp: 2026-03-20 14:32:17 UTC       DM Mono 12px   |
    | Rule: salary_disclosure                  DM Mono 12px    |
    | Rule Type: keyword_block                                 |
    | Action Taken: block                      --alert         |
    |                                                          |
    | Conversation ID: conv_8k2m4n7x          DM Mono 11px    |
    | Tenant: Acme Capital                                     |
    | Agent Instance: ag_7f3k2m9x             DM Mono 11px    |
    |                                                          |
    | User Message Shown:                                      |
    | "Salary and compensation details are confidential.       |
    |  Please contact HR directly for compensation inquiries." |
    |                                                          |
    | [Collapse]                                               |
    +----------------------------------------------------------+

  What the drill-down shows:
    - Full timestamp (seconds precision) in DM Mono
    - Rule ID and type
    - Action taken with color coding
    - Conversation ID (for cross-referencing with chat logs if needed)
    - Tenant name (resolved, not UUID)
    - Agent instance ID (DM Mono, for technical reference)
    - The exact user message that was shown to the end user

  What the drill-down does NOT show (privacy boundary):
    - No end user identity (user_id is logged in audit trail but not
      displayed to platform admin -- tenant data sovereignty)
    - No full conversation content (what the user asked)
    - No original LLM response that was blocked
    - No PII of any kind

  For regulated tenants with compliance logging tier enabled: an additional
  line appears: "Encrypted content blob available (tenant key required)"
  with a [Request Access] button that initiates a key-exchange workflow.
  Platform admin cannot decrypt without tenant authorization.

STEP 5: Export for SOC 2 Audit Evidence
  Admin clicks [Export CSV] in the filter bar row (right-aligned).

  Export includes all currently filtered violations in CSV format:
    timestamp, rule_id, rule_type, action_taken, tenant_name,
    agent_instance_id, conversation_id, user_message_shown

  Export does NOT include:
    - End user identifiers
    - Original LLM responses
    - Conversation content
    - Encrypted content blobs (these require tenant key access)

  File downloads as:
    guardrail-violations-hr-policy-advisor-2026-03-01-to-2026-03-21.csv

  A toast confirms: "Exported 47 violation records"

  VALUE: Platform admin can generate SOC 2 audit evidence showing that
  guardrail rules are actively enforced, violations are detected and
  blocked, and a complete audit trail exists -- without exposing PII
  or end-user conversation content.

STEP 6: Aggregate Metrics (Panel Header)
  Above the violations table, summary metrics are shown:

    +----------------------------------------------------------+
    | COMPLIANCE SUMMARY                     Last 30 days      |
    |                                                          |
    |  47              23              24              0        |
    |  Total           salary_         no_legal_       Filter   |
    |  Violations      disclosure      advice          Errors   |
    |  DM Mono 22px    DM Mono 18px    DM Mono 18px   DM Mono  |
    |  --text-primary  --alert         --alert         --accent |
    |                                                          |
    |  Violation Rate: 2.3% of queries  DM Mono 12px           |
    |  Filter Health: 100% uptime       DM Mono 12px, --accent |
    +----------------------------------------------------------+

  Metrics use DM Mono for all numbers and percentages.
  "Filter Errors" at 0 shows in --accent (healthy). If > 0, shows in --alert
  with a link to the filter error log.
  Violation rate: violations / total queries for this template across all tenants.
  Filter health: percentage of filter invocations without errors.
```

**Edge Cases**:

| Scenario                             | What Happens                                                                                                                                       | Recovery                                                             |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| No violations recorded               | Empty state: "No guardrail violations recorded for this template." Metrics show all zeros.                                                         | N/A -- healthy state                                                 |
| Filter error occurred                | "Filter Errors" metric shows count in --alert. Clicking navigates to a separate error log showing timestamps and error types.                      | Platform admin investigates filter service health                    |
| Export with >10,000 rows             | Export triggers async generation. Toast: "Generating export... You will be notified when ready." File available in a notifications/downloads area. | Admin waits for notification                                         |
| Tenant deleted but violations remain | Tenant name shows as "Deleted Tenant (tenant_id)" in --text-faint. Violations are preserved for audit purposes.                                    | N/A -- audit trail is immutable                                      |
| Compliance logging tier active       | Additional column in table: "Content" with locked icon. Drill-down shows "Encrypted content blob available (tenant key required)"                  | Platform admin requests access through tenant authorization workflow |

---

## Flow 7B: Tenant Admin -- View Guardrail Violation Log

**Trigger**: Tenant admin wants to review guardrail compliance events for their own agents.
**Persona**: Tenant Admin
**Entry**: Tenant Admin > Agents > [Agent] > Compliance tab OR Tenant Admin > Settings > Compliance

```
STEP 1: Navigate to Agent Compliance View
  Tenant admin opens an agent's detail panel (Flow 5) and clicks the
  [Compliance] tab. Alternatively, navigates to Tenant Admin > Settings >
  Compliance for a cross-agent view.

  The Compliance tab shows the same table layout as Flow 7 but scoped to
  this tenant only (no tenant filter column -- the tenant sees only their
  own data).

STEP 2: View Violations Table

    +----------------------------------------------------------+
    | GUARDRAIL VIOLATIONS                     12 total events |
    |                                                          |
    | Filters:                                  [Export CSV]    |
    | Date Range: [2026-03-01] to [2026-03-21]                 |
    | Rule: [All Rules v]                                      |
    | Action: [All v]  (block / redact / warn)                 |
    |                                                          |
    | +------------------------------------------------------+ |
    | | Timestamp          | Rule              | Action | Agt | |
    | |--------------------+-------------------+--------+-----| |
    | | 2026-03-20 14:32   | salary_disclosure | block  | HR  | |
    | | 2026-03-19 09:45   | salary_disclosure | block  | HR  | |
    | | 2026-03-18 15:58   | salary_disclosure | block  | HR  | |
    | | 2026-03-17 10:22   | no_legal_advice   | block  | HR  | |
    | | ...                                                    | |
    | +------------------------------------------------------+ |
    |                                                          |
    | Showing 1-12 of 12          [< Prev]  [Next >]          |
    +----------------------------------------------------------+

  Table columns:
    - Timestamp: DM Mono 12px (ISO 8601, UTC)
    - Rule: DM Mono 12px (rule_id)
    - Action: DM Mono 11px -- same color coding as Flow 7
    - Agent Name: Plus Jakarta Sans 13px/500
    - Conversation ID: DM Mono 11px, --text-faint (truncated with copy button)

  No tenant column (single-tenant scoped view).
  Agent Name column replaces Tenant column for cross-agent compliance view.

STEP 3: Filter and Drill Down
  Filters: date range, rule type, action (allow/flag/replace/block).
  Same immediate-apply behavior as Flow 7.

  Drill-down on row click: same inline expansion as Flow 7 Step 4.
  PII handling: same as Flow 7 -- no user identity, no conversation content,
  only: timestamp, rule, action, agent name, conversation_id.

STEP 4: Export
  [Export CSV] button in filter bar row, right-aligned.

  CSV export directly -- no key-exchange needed. Tenant admin owns
  their own compliance data.

  Export columns: timestamp, rule_id, rule_type, action_taken, agent_name,
  conversation_id, user_message_shown.

  File downloads as:
    guardrail-violations-acme-capital-2026-03-01-to-2026-03-21.csv

  Toast: "Exported 12 violation records"

  VALUE: Tenant admin has full visibility into guardrail enforcement
  for their own agents, enabling internal compliance reporting without
  depending on the platform admin.
```

**Edge Cases**:

| Scenario                                    | What Happens                                                                    | Recovery                      |
| ------------------------------------------- | ------------------------------------------------------------------------------- | ----------------------------- |
| No violations for this tenant               | Empty state: "No guardrail violations recorded." Metrics show all zeros.        | N/A -- healthy state          |
| Cross-agent view (Settings > Compliance)    | Shows all violations across all tenant agents. Agent Name column distinguishes. | Filter by agent name dropdown |
| Export with no results (filters too narrow) | Toast: "No records match the current filters." No file downloaded.              | Admin adjusts filters         |

---

**Document Version**: 2.0
**Last Updated**: 2026-03-21
**Changelog**: v2.0 -- Added Flows 2B (Update Published Template), 2C (Deprecate Template), 3B (Tenant Update Review), 5B (Reconfigure Deployed Agent), 7B (Tenant Compliance View). Added RBAC table. Fixed Flow 4 streaming model for guardrail-enabled agents. Added tool health validation and KB-required validation to Flow 3. Added PUBLIC_BASE_URL and agent name confidentiality to Flow 6. Added template name uniqueness to Flow 1. Added wizard step order note to Flow 3. Added tool hints to Flow 4. Moved Export CSV button to filter bar in Flow 7. Added deprecation note for old flows.
