---
id: TODO-50
title: CredentialsTab component — CompletenessHeader, CredentialRow, and CredentialInlineForm
status: pending
priority: medium
phase: C1
dependencies: [TODO-49]
---

## Goal

Create `src/web/app/(platform)/platform/agent-templates/elements/CredentialsTab.tsx` with the `CompletenessHeader`, `CredentialRow`, and `CredentialInlineForm` sub-components. This todo covers the read state, the Add/Rotate inline form, and form interaction states. The Delete confirmation expansion is handled in TODO-51.

## Context

The Template Studio Panel needs a Credentials tab so platform admins can manage API keys for `platform_credentials` templates without leaving the panel. This is the core credential management surface described in the UX spec.

Reference: `workspaces/mingai/01-analysis/19-platform-credential-vault/04-ux-design-spec.md` — all sections except Delete Confirmation and Accessibility.

## Implementation

### File: `src/web/app/(platform)/platform/agent-templates/elements/CredentialsTab.tsx`

The tab receives `templateId: string` as its primary prop. It also receives `authMode: string` and `requiredCredentials: string[]` from the parent.

### CompletenessHeader

Positioned at the top of the tab, right-aligned badge:

```
Required Credentials                            [2/3 configured]
Credentials needed for agents using this template
```

Badge states (from `useCredentialHealth`):
- All stored: `"All configured"`, background `accent-dim`, text `accent`
- Partial: `"N/M configured"`, background `warn-dim`, text `warn`
- None stored: `"Unconfigured"`, background `alert-dim`, text `alert`
- `status: "not_required"`: badge hidden

Typography: title at `text-section-heading` (15px/600), subtitle 13px/400/text-muted. Badge: 11px/500/uppercase/letter-spacing 0.06em/padding 4px 10px/border-radius `var(--r-sm)`.

Badge must have `role="status"` and `aria-live="polite"`.

### CredentialRow — summary line

One row per key in `requiredCredentials`. Data from `useTemplateCredentials`.

Sort order: Missing first → Stored (alphabetical) → Revoked last.

Layout:
```
PITCHBOOK_API_KEY    [Stored]    Updated 3h ago
Access to PitchBook data API                  [Rotate] [trash]
```

- Key name: DM Mono, 13px/500, `text-primary`
- Description: 13px/400/Plus Jakarta Sans, `text-muted`, one line, truncated with ellipsis at 80 chars
- Timestamp: DM Mono, 11px/400, `text-faint`. Relative if under 30 days ("3h ago", "2d ago"), absolute ("Mar 12, 2026") otherwise. Tooltip on hover: full ISO timestamp. Show "Never" for keys with no stored value.
- Row container: `padding: 14px 0`, `border-bottom: 1px solid var(--border-faint)`, no card/background

Status badge colours:
- Stored: `accent-dim` bg, `accent` text
- Missing: `alert-dim` bg, `alert` text
- Revoked: `bg-elevated` bg, `text-faint` text
- Badge: 10px/500/uppercase/letter-spacing 0.06em/padding 3px 8px/border-radius `var(--r-sm)`
- `role="status"` on each badge

Action buttons by status:
- Missing: "Add" button (accent ghost)
- Stored: "Rotate" button (neutral ghost) + 16px trash icon button (`text-faint` at rest, `alert` on hover)
- Revoked: "Add" button (accent ghost), row at 50% opacity

Ghost button: no background at rest, `bg-elevated` on hover, padding 6px 12px, `var(--r)` radius. Delete button is icon-only (no text label) with `aria-label="Delete credential {KEY}"`.

### CredentialInlineForm

Clicking "Add" or "Rotate" expands the form inline below the row's summary line.

Rules:
- Only one form open at a time — opening a second collapses the first without saving
- Escape key collapses the form and returns focus to the trigger button
- Input auto-focused on expand

Form area styling: `bg-deep`, `border: 1px solid var(--border-faint)`, `border-radius: var(--r)`, padding 16px, margin-top 8px.

Password input:
- Full width, height 40px, `bg-elevated`, `border: 1px solid var(--border)`
- Focus: `border-color: accent`, `box-shadow: 0 0 0 2px var(--accent-ring)`
- Font: DM Mono 13px
- `type="password"`, `autocomplete="off"`, `data-lpignore="true"` (blocks password manager autofill)
- `aria-label="Credential value for {KEY}"`

Show/hide toggle: eye icon inside input (right side), 16px, `text-faint` → `text-muted` on hover. `aria-label="Show credential value"` / `"Hide credential value"`, `aria-pressed` toggled.

Encryption notice (always shown): info-circle icon, text: "Stored encrypted. You cannot retrieve this value after saving — only rotate or delete." 13px/400/text-muted.

Rotation impact notice (Rotate only): warning-triangle icon, text: "Rotating will update all agents (within 5 min)." 13px/400/warn.

Save button: `bg-accent`, `color: bg-base` (dark text on bright green), 36px height, `var(--r)`, 220ms opacity transition.

Cancel: text-only, `text-muted`, no border.

### Form interaction states

| State | Save button | Input |
|---|---|---|
| Empty (initial) | Disabled (accent at 30% opacity) | Empty, auto-focused |
| Has value | Enabled (full accent) | Filled |
| Submitting | "Saving…" + inline spinner, disabled | Disabled |
| Success | Checkmark briefly, 600ms hold, then collapse | Cleared |
| Error | Re-enabled | Retains value, error text below in alert, 13px |

Success state: hold for 600ms with checkmark visible, then collapse (180ms ease). Do NOT close immediately on mutation success — the 600ms hold provides acknowledgement feedback.

### Animation timing

- Inline form expand: 220ms ease
- Inline form collapse: 180ms ease
- Success hold before collapse: 600ms hold + 180ms collapse

### Empty state

When `requiredCredentials` is empty (or null), display an empty state message: "No credentials required for this template." in `text-muted` centered in the tab area.

## Acceptance Criteria

- [ ] `CredentialsTab` renders with `CompletenessHeader` using `useCredentialHealth` data
- [ ] Completeness badge shows correct state (all/partial/none/hidden) with correct colours
- [ ] Credential rows render sorted: Missing → Stored (A-Z) → Revoked
- [ ] Status badge colours match spec (accent-dim/alert-dim/bg-elevated)
- [ ] Timestamps show relative format under 30 days, absolute otherwise; tooltip shows ISO on hover
- [ ] "Add" button shown for Missing/Revoked; "Rotate" + trash shown for Stored
- [ ] Revoked rows render at 50% opacity
- [ ] Clicking "Add" or "Rotate" expands the inline form with the input auto-focused
- [ ] Only one inline form open at a time — opening a second collapses the first
- [ ] Escape key collapses the open form
- [ ] Password input has `type="password"`, `autocomplete="off"`, `data-lpignore="true"`
- [ ] Show/hide toggle works and updates `aria-pressed`
- [ ] Rotation impact warning shown only on Rotate, not on Add
- [ ] Save button disabled when input is empty
- [ ] Success state holds checkmark for 600ms then collapses
- [ ] Error state re-enables Save and shows error text below input
- [ ] Empty state message shown when `requiredCredentials` is empty
- [ ] All typography follows Obsidian Intelligence spec (DM Mono for keys/data, Plus Jakarta Sans for labels)
