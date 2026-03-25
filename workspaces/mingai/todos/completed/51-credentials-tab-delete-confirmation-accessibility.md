---
id: TODO-51
title: CredentialsTab — DeleteConfirmation sub-component and full accessibility pass
status: pending
priority: medium
phase: C1
dependencies: [TODO-50]
---

## Goal

Add the `DeleteConfirmation` inline expansion to the CredentialsTab and complete the full accessibility pass across all sub-components: ARIA roles, keyboard navigation, focus management, and color-independence verification.

## Context

The delete flow has impact-loading, confirmation, and post-delete state transitions that are complex enough to warrant their own todo. Accessibility cannot be deferred — the credential management UI handles security operations and must be usable by keyboard-only users and screen reader users.

Reference: `workspaces/mingai/01-analysis/19-platform-credential-vault/04-ux-design-spec.md` — Delete Confirmation and Accessibility sections.

## Implementation

### DeleteConfirmation sub-component

Clicking the trash icon expands an inline confirmation below the credential row's summary line. Action buttons (Rotate, trash) are hidden while the confirmation is open.

Container styling:
- Background: `alert-dim` (rgba(255, 107, 53, 0.08))
- Border: `1px solid rgba(255, 107, 53, 0.2)`
- Border-radius: `var(--r)`
- Padding: 14px 16px
- Role: `role="alertdialog"`, `aria-describedby` pointing to the impact text element

Layout:
```
Delete PITCHBOOK_API_KEY?
12 agents across 4 tenants will lose access.

[Delete]  Cancel
```

Title: 13px/600/Plus Jakarta Sans/text-primary. Key name rendered inline in DM Mono.
Impact text element id: `delete-impact-{key}` (for `aria-describedby`).

### Delete states

| State | Behaviour |
|---|---|
| Loading impact | "Checking agent usage…" with pulse animation. Delete button disabled. Impact text is a skeleton shimmer. |
| Zero agents | "No active agents affected." in text-muted. Delete enabled immediately. |
| Nonzero agents | "N agents across M tenants will lose access." in `alert`. Numbers (N, M) in DM Mono. Delete enabled. |
| Deleting | "Deleting…" + spinner. Both buttons disabled. |
| Deleted | Confirmation collapses (180ms ease), row transitions to Revoked state (opacity 0.5, badge changes, action buttons change to "Add"). Transition: 220ms ease. |
| Error | Error message below impact text. Both buttons re-enabled. |

The impact count is loaded via the DELETE pre-flight or a separate API call. The implementation must call the delete endpoint with `force=false` first to get `affected_agent_count` if the deletion fails with 409, OR use a dedicated preview endpoint if one exists. If the endpoint does not support a non-destructive impact preview, call the delete endpoint and handle the 409 response as the impact check result.

Skeleton shimmer: 1500ms loop ease-in-out on the impact text element while loading.

### Focus management on delete confirmation expand

On expand: focus must move to the Cancel button (NOT the Delete button — prevents accidental Enter key confirmation). Use `useEffect` + `ref.current?.focus()`.

On collapse (Cancel or after delete): focus must return to the trash icon button that triggered the confirmation.

### Full accessibility pass for CredentialsTab

Apply to all sub-components (including those from TODO-50):

**ARIA roles:**
- Completeness badge: `role="status"`, `aria-live="polite"`
- All status badges (Stored/Missing/Revoked): `role="status"`
- Delete confirmation container: `role="alertdialog"`, `aria-describedby={impactTextId}`
- Delete impact text: `id="delete-impact-{key}"`

**ARIA labels:**
- Password input: `aria-label="Credential value for {KEY}"`
- Show/hide toggle: `aria-label` changes between `"Show credential value"` and `"Hide credential value"`; `aria-pressed` reflects current visibility state
- Trash icon button: `aria-label="Delete credential {KEY}"`
- Completeness badge count: when missing, `aria-label` on the badge element should read the full count e.g. `"2 of 3 credentials configured"`

**Keyboard navigation:**
- Tab order: header badge (non-focusable/`aria-hidden`) → credential rows top to bottom → action buttons within each row → inline form when open
- Arrow Up/Down: navigate between credential rows without entering rows (optional enhancement — implement if time permits)
- Escape: closes any open inline form or delete confirmation, returns focus to the trigger element
- Enter/Space on action buttons: trigger the action (standard button behaviour)

**Color independence:**
- Status communicated via text label AND color — no status relies solely on color
- Publish gate warning uses icon + text, not just warn tint
- Delete confirmation uses "alertdialog" role, not just red background

**Focus ring:**
- All interactive elements: `outline: 2px solid var(--accent)`, `outline-offset: 2px`, `:focus-visible` only (not `:focus`, to avoid outline on mouse click)

## Acceptance Criteria

- [ ] Trash icon click expands DeleteConfirmation inline
- [ ] Action buttons (Rotate, trash) are hidden/disabled while confirmation is open
- [ ] Impact count loads asynchronously with skeleton shimmer
- [ ] Delete button is disabled until impact count has loaded
- [ ] Impact zero: "No active agents affected." in text-muted
- [ ] Impact nonzero: "N agents across M tenants will lose access." with numbers in DM Mono
- [ ] Delete button triggers deletion and transitions row to Revoked state
- [ ] After deletion: confirmation collapses, row shows "Revoked" badge at 50% opacity, action shows "Add"
- [ ] Delete error: error message shown, buttons re-enabled
- [ ] Focus moves to Cancel button on confirmation expand (not Delete)
- [ ] Focus returns to trash icon after confirmation closes (Cancel or success)
- [ ] Escape key closes the confirmation and returns focus to trash icon
- [ ] `role="alertdialog"` with `aria-describedby` on confirmation container
- [ ] `role="status"` on all status badges
- [ ] `aria-live="polite"` on completeness badge
- [ ] `aria-label` on password input: `"Credential value for {KEY}"`
- [ ] `aria-label` on trash icon: `"Delete credential {KEY}"`
- [ ] `aria-pressed` on show/hide toggle reflects current state
- [ ] Focus ring uses `--accent` with `:focus-visible` (not `:focus`)
- [ ] Status differences are communicated by text label, not color alone
