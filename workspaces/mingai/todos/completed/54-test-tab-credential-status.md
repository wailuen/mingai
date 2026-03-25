---
id: TODO-54
title: Test tab enhancement — replace stub banner with real credential health status
status: pending
priority: medium
phase: C5
dependencies: [TODO-49]
---

## Goal

In `TestHarnessTab.tsx`, replace the current static/stub credential banner for `platform_credentials` templates with a live status panel that calls `useCredentialHealth` and disables the Run Test button when any credentials are missing.

## Context

The test harness currently shows a placeholder info message for `platform_credentials` templates, silently letting admins run tests without credentials configured. The test would fail with a confusing 503 error rather than a clear "configure credentials first" message. This change makes the issue visible and actionable before the test is even attempted.

Reference: `workspaces/mingai/01-analysis/19-platform-credential-vault/04-ux-design-spec.md` — Test Tab Enhancement section.

## Implementation

### Locate the TestHarnessTab credential banner

In `src/web/app/(platform)/platform/agent-templates/elements/TestHarnessTab.tsx`, find the existing banner or info block that currently shows something like "This template uses platform credentials" (static text). This is the element to replace.

### Conditional banner replacement

Only activate this logic when `template.auth_mode === "platform_credentials"`. For other auth modes, no credential banner is shown.

```typescript
const { data: credentialHealth, isLoading: healthLoading } = useCredentialHealth(
  template.auth_mode === "platform_credentials" ? template.id : undefined
);
```

### All configured state (N/N)

When `credentialHealth?.status === "complete"`:

```
● Platform credentials (2/2 configured)
  Credentials will be injected automatically at runtime
```

Styling:
- Left dot: 8px solid circle, `accent` color
- Background: `accent-dim` (rgba(79, 255, 176, 0.08))
- Border: `1px solid rgba(79, 255, 176, 0.15)`
- Border-radius: `var(--r)` (7px)
- Padding: 12px 16px
- First line: 13px/500/text-primary. Count "N/N" in DM Mono.
- Second line: 13px/400/text-muted
- Run Test button: enabled as normal

### Any missing state (N/M or 0/M)

When `credentialHealth?.status === "incomplete"`:

```
● N/M credentials missing
  Configure in the Credentials tab before testing        [Go →]
```

Compute `total = credentialHealth.required_credentials.length` and `missing = Object.values(credentialHealth.keys).filter(s => s === 'missing' || s === 'revoked').length`.

Styling:
- Left dot: 8px solid circle, `alert` color
- Background: `alert-dim` (rgba(255, 107, 53, 0.08))
- Border: `1px solid rgba(255, 107, 53, 0.15)`
- Border-radius: `var(--r)` (7px)
- Padding: 12px 16px
- First line: 13px/500/text-primary. Counts in DM Mono.
- Second line: 13px/400/text-muted
- "Go →" link: `accent` color, navigates to Credentials tab in the studio panel

Run Test button when missing:
- Background: `bg-elevated`
- Text: `text-faint`
- `cursor: not-allowed`
- `disabled` attribute set
- Tooltip: "Configure missing credentials before testing."

### Loading state

While `healthLoading` is true, show a skeleton shimmer in place of the banner (same height as the complete state banner, 1500ms ease-in-out pulse). Do not disable Run Test while loading — the test will naturally fail if credentials are missing, and the user should be able to initiate.

### not_required state

When `credentialHealth?.status === "not_required"`, show no credential banner (template has no required credentials but still uses `platform_credentials` auth_mode — edge case, no action needed).

### Tab navigation

The "Go →" link must switch the active tab to Credentials. The TestHarnessTab must receive either a tab-switching callback prop or access to shared tab state. Follow whatever pattern is used by similar cross-tab links in the panel.

## Acceptance Criteria

- [ ] When all credentials are configured: green accent-dim banner with "N/N configured" and Run Test enabled
- [ ] When any credentials are missing: alert-dim banner with "N/M credentials missing" and Run Test disabled
- [ ] Run Test button has `cursor: not-allowed` and `disabled` when credentials are missing
- [ ] Run Test tooltip reads "Configure missing credentials before testing." when disabled
- [ ] "Go →" link navigates to the Credentials tab
- [ ] Counts are rendered in DM Mono
- [ ] Loading state shows skeleton shimmer (not blank)
- [ ] No credential banner shown for `auth_mode != 'platform_credentials'`
- [ ] No credential banner shown when `status === 'not_required'`
- [ ] Banner colours follow Obsidian Intelligence spec (accent-dim for complete, alert-dim for missing)
- [ ] The existing Run Test button state (other enabled/disabled conditions) is not regressed
