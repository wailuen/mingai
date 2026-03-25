# Platform Credential Vault — UX Design Specification

**Date**: 2026-03-23
**Design System**: Obsidian Intelligence
**References**: `02-requirements-and-adr.md`

---

## Placement

Platform Admin → Intelligence → Agent Templates → [select template] → **Credentials tab** (new tab in the Template Studio Panel).

The Credentials tab joins the existing tab bar: Edit | Test | Instances | Version History | Performance | **Credentials**

---

## Component Hierarchy

```
Template Studio Panel (slide-in from right, existing)
└── Tab Bar
    ├── Edit | Test | Instances | Version History | Performance
    └── Credentials [badge: N missing, orange dot]
        └── Credentials Tab Content
            ├── Header Bar
            │   ├── "Required Credentials"  (section heading, 15px/600)
            │   ├── Subtitle                (13px/400/text-muted)
            │   └── Completeness Badge      (right-aligned)
            ├── Credential Row (×N, one per required_credentials key)
            │   ├── Summary Line (always visible)
            │   │   ├── Key name   (DM Mono, 13px/500)
            │   │   ├── Status badge
            │   │   ├── Description (13px/400/text-muted)
            │   │   ├── Last updated (DM Mono, 11px/text-faint)
            │   │   └── Action buttons (Add | Rotate + Delete)
            │   ├── Inline Form (expanded on Add/Rotate click)
            │   │   ├── Password input + show/hide toggle
            │   │   ├── Warning: encryption notice
            │   │   ├── Warning: rotation impact (only for Rotate)
            │   │   └── [Save] [Cancel]
            │   └── Delete Confirmation (expanded on Delete click)
            │       ├── "Delete KEY? N agents across M tenants..."
            │       └── [Delete] [Cancel]
            └── Empty State (when required_credentials is empty)
```

---

## Header Bar

```
Required Credentials                            [2/3 configured]
Credentials needed for agents using this template
```

- Title: `text-section-heading` (15px/600/Plus Jakarta Sans)
- Subtitle: 13px/400/text-muted
- Badge: right-aligned, 11px/500/uppercase/letter-spacing 0.06em, padding 4px 10px, border-radius `var(--r-sm)` (4px)

### Completeness Badge States

| Credential state | Label | Background | Text |
|---|---|---|---|
| All stored | "All configured" | `accent-dim` | `accent` |
| Partial (N/M) | "2/3 configured" | `warn-dim` | `warn` |
| None stored | "Unconfigured" | `alert-dim` | `alert` |
| No credentials required | *(badge hidden)* | — | — |

---

## Credential Row — Summary Line

```
PITCHBOOK_API_KEY         [Stored]     Updated 3h ago
Access to PitchBook data API                  [Rotate] [🗑]
```

**Container**: padding 14px 0, border-bottom `1px solid var(--border-faint)`. No card — rows sit directly on tab background.

**Key name**: DM Mono, 13px/500, text-primary. Data identifiers use monospace throughout.

**Description**: 13px/400/Plus Jakarta Sans, text-muted. One line, truncated with ellipsis > 80 chars.

**Timestamp**: DM Mono, 11px/400, text-faint. Relative if < 30 days ("3h ago", "2d ago"), absolute otherwise ("Mar 12, 2026"). Tooltip on hover: full ISO timestamp. "Never" shown for unconfigured.

**Sort order**: Missing first → Stored (alphabetical) → Revoked last.

### Status Badges

| Status | Label | Background | Text |
|---|---|---|---|
| Stored | "Stored" | `accent-dim` | `accent` |
| Missing | "Missing" | `alert-dim` | `alert` |
| Revoked | "Revoked" | `bg-elevated` | `text-faint` |

Badge: 10px/500/uppercase/letter-spacing 0.06em/padding 3px 8px/border-radius `var(--r-sm)`.

### Action Buttons per Status

| Status | Actions |
|---|---|
| Missing | "Add" (accent ghost) |
| Stored | "Rotate" (neutral ghost) + trash icon (text-faint → alert on hover) |
| Revoked | "Add" (accent ghost) + row at 50% opacity |

Ghost button: no background at rest, `bg-elevated` on hover, 6px 12px padding, `var(--r)` radius.

Delete button: 16px trash icon only (no text label) — destructive actions are present but visually recessive.

---

## Inline Form (Add / Rotate)

### Trigger Behaviour

Clicking "Add" or "Rotate" expands the form inline below the credential's summary line. Only one form open at a time — opening a second collapses the first. Escape collapses and returns focus to the action button.

### Layout

```
┌────────────────────────────────────────────────────────────┐  ← bg-deep, border-faint, r=7px, p=16px
│  ┌────────────────────────────────────────┐ [eye icon]     │
│  │  ●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●  │                │
│  └────────────────────────────────────────┘                │
│                                                            │
│  ℹ Stored encrypted. You cannot retrieve this value        │
│    after saving — only rotate or delete.                   │
│                                                            │
│  ⚠ Rotating will update all agents (within 5 min).         │  ← Rotate only
│                                                            │
│  [Save]  Cancel                                            │
└────────────────────────────────────────────────────────────┘
```

**Form area**: `bg-deep` (deepest inset), `border: 1px solid var(--border-faint)`, `border-radius: var(--r)`, padding 16px, margin-top 8px.

**Password input**: full width, height 40px, `bg-elevated`, `border: 1px solid var(--border)`, focus: `border-color: accent` + `box-shadow: 0 0 0 2px var(--accent-ring)`. Font: DM Mono 13px. `type="password"`, `autocomplete="off"`, `data-lpignore="true"`.

**Show/hide toggle**: eye icon inside input (right), 16px, text-faint → text-muted on hover. `aria-label="Show/hide credential value"`, `aria-pressed` toggled.

**Encryption notice** (always shown): info-circle icon 13px, text-faint. Text: 13px/400/text-muted.

**Rotation impact** (Rotate only): warning-triangle icon 13px, warn. Text: 13px/400/warn.

**Save button**: `bg-accent`, `color: bg-base` (dark text on bright green), 36px height, `var(--r)`, 220ms opacity transition.

**Cancel**: text-only, text-muted, no border/background.

### Form Interaction States

| State | Save button | Input | Notes |
|---|---|---|---|
| Empty (initial) | Disabled (accent at 30% opacity) | Empty, auto-focused | Focus moves to input on expand |
| Has value | Enabled (full accent) | Filled | — |
| Submitting | "Saving…" + inline spinner, disabled | Disabled | — |
| Success | Checkmark briefly, then collapses | Cleared | Collapse after 600ms hold |
| Error | Re-enables | Retains value | Error text below input, 13px/alert |

---

## Delete Confirmation (Inline)

### Trigger

Clicking the trash icon expands confirmation inline below the summary line. Action buttons are hidden during confirmation.

```
┌────────────────────────────────────────────────────────────┐  ← alert-dim, alert/0.2 border
│  Delete PITCHBOOK_API_KEY?                                 │
│  12 agents across 4 tenants will lose access.              │
│                                                            │
│  [Delete]  Cancel                                          │
└────────────────────────────────────────────────────────────┘
```

**Container**: `bg-alert-dim`, `border: 1px solid rgba(255, 107, 53, 0.2)`, `border-radius: var(--r)`, padding 14px 16px.

**Title**: "Delete {KEY}?" — 13px/600/Plus Jakarta Sans/text-primary. Key name inline in DM Mono.

**Impact line**: 13px/400/alert. Numbers (12, 4) in DM Mono. Zero agents: "No active agents affected." in text-muted.

**Delete button**: `bg-alert`, text white, 36px, `var(--r)`.

**Cancel**: text-only, text-muted.

**Focus on expand**: moves to Cancel (not Delete — prevent accidental Enter confirmation).

### Delete States

| State | Behaviour |
|---|---|
| Loading impact | "Checking agent usage…" pulse animation. Delete disabled until loaded. |
| Impact loaded, zero | Neutral messaging, delete enabled immediately |
| Impact loaded, nonzero | Alert messaging, delete enabled (no forced delay) |
| Deleting | "Deleting…" + spinner, both buttons disabled |
| Deleted | Row → Revoked state (opacity 0.5, badge changes), confirmation collapses |
| Error | Error message below impact, buttons re-enable |

---

## Tab Badge (Cross-Tab Alert)

When N credentials are missing, the Credentials tab label shows a badge:

- Shape: 16px × 16px circle, positioned top-right of tab text, offset -4px/-4px
- Background: `alert`
- Text: white, 10px/600/DM Mono
- Count: number of MISSING credentials (not total)
- `aria-label` on tab element: "Credentials, 2 missing"
- No badge when all credentials are configured or template has no required_credentials

---

## Publish Gate Warning (Edit Tab)

When the admin clicks "Publish" on a template with missing credentials:

```
┌────────────────────────────────────────────────────────────┐  ← warn-dim, warn/0.2 border, r=7px
│  ⚠ Cannot publish: 2 required credentials not configured   │
│     Configure them in the Credentials tab.   [Go to Creds] │
└────────────────────────────────────────────────────────────┘
```

- Appears below the Publish button area
- `warn-dim` background, `border: 1px solid rgba(245, 197, 24, 0.2)`
- Text: 13px/500/warn
- "Go to Credentials" link: accent, underline on hover, switches to Credentials tab
- Auto-dismisses after 8 seconds or on next user interaction
- Entrance: opacity 0→1 + translateY 4px→0, 220ms ease
- Dismiss: opacity 1→0, 300ms ease

---

## Test Tab Enhancement

When `auth_mode = "platform_credentials"`, the existing banner updates to show credential status:

**All configured (2/2)**:
```
● Platform credentials (2/2 configured)
  Credentials will be injected automatically at runtime
```
- Left dot: `accent` (8px solid circle)
- Background: `accent-dim`, `border: 1px solid rgba(79, 255, 176, 0.15)`
- First line: 13px/500/text-primary. Count "2/2" in DM Mono.
- Second line: 13px/400/text-muted
- Run Test: enabled as normal

**Any missing (1/2)**:
```
● 1/2 credentials missing
  Configure in the Credentials tab before testing         [Go →]
```
- Left dot: `alert`
- Background: `alert-dim`, `border: 1px solid rgba(255, 107, 53, 0.15)`
- "Go →" link: accent, navigates to Credentials tab
- Run Test: disabled. `bg-elevated`, text-faint, `cursor: not-allowed`. Tooltip: "Configure missing credentials before testing."

---

## Interaction Timing

| Action | Duration | Easing |
|---|---|---|
| Inline form expand | 220ms | ease |
| Inline form collapse | 180ms | ease |
| Success hold before collapse | 600ms hold + 180ms collapse | ease |
| Delete confirmation expand | 220ms | ease |
| Row → Revoked transition | 220ms | ease |
| Skeleton shimmer pulse | 1500ms loop | ease-in-out |
| Publish warning appear | 220ms (opacity + translateY) | ease |
| Publish warning auto-dismiss | 300ms at 8s mark | ease |

All use the system standard `--t: 220ms ease` except skeleton shimmer (longer for comfortable loading perception) and success hold (deliberate pause for acknowledgement).

---

## Accessibility

**Keyboard nav**: Tab order is header badge (non-focusable) → credential rows top to bottom → action buttons within each row. Arrow Up/Down navigates between rows. Escape closes any open form/confirmation.

**Screen reader labels**:
- Password input: `aria-label="Credential value for PITCHBOOK_API_KEY"`
- Show/hide toggle: `aria-label="Show credential value"` / `"Hide credential value"`, `aria-pressed`
- Status badges: `role="status"`, text label ("Stored", "Missing", "Revoked")
- Completeness badge: `role="status"`, `aria-live="polite"`
- Delete icon: `aria-label="Delete credential PITCHBOOK_API_KEY"`
- Delete confirmation: `role="alertdialog"`, `aria-describedby` → impact text
- Tab with missing badge: `aria-label="Credentials, 2 missing"`

**Color independence**: Status communicated via text label AND color. No status relies solely on color. Publish gate uses icon + text, not just orange tint.

**Focus ring**: `outline: 2px solid var(--accent)`, `outline-offset: 2px`, `:focus-visible` only.

---

## Priority

| P0 — Blocks use | P1 — Reduces productivity | P2 — Efficiency | P3 — Polish |
|---|---|---|---|
| Credential list + status badges | Rotate flow | Sort missing-first | Success checkmark animation |
| Add/Save inline form | Delete with impact count | Tab badge count | Publish warning auto-dismiss |
| Publish gate | Test tab credential status | Relative timestamps with tooltip | Skeleton states |
