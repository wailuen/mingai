---
id: TODO-53
title: Publish gate warning UI — inline warning below Publish button in Edit tab
status: pending
priority: medium
phase: C4
dependencies: [TODO-49, TODO-52]
---

## Goal

In the Edit tab section of `TemplateStudioPanel.tsx` (or wherever the Publish button lives), intercept the Publish button click for `platform_credentials` templates with missing credentials, check credential health, and display an inline warning block when credentials are incomplete. The warning auto-dismisses after 8 seconds and links to the Credentials tab.

## Context

Without this UI gate, a platform admin could click "Publish" and only learn about missing credentials from a raw 422 API error. The frontend gate provides a friendly, actionable message that directs them to the Credentials tab to configure before attempting to publish again.

Reference: `workspaces/mingai/01-analysis/19-platform-credential-vault/04-ux-design-spec.md` — Publish Gate Warning section.

## Implementation

### Locate the Publish button

In `TemplateStudioPanel.tsx` or its Edit sub-component, find the "Publish" button and its click handler. This is the button that calls the publish/status-change API endpoint.

### Pre-publish credential check

Before submitting the publish API call for `platform_credentials` templates:

```typescript
const handlePublish = async () => {
  if (template.auth_mode === "platform_credentials") {
    const health = await fetchCredentialHealth(template.id);
    const missingCount = Object.values(health.keys)
      .filter(s => s === "missing" || s === "revoked").length;

    if (missingCount > 0) {
      setPublishWarning({
        missingCount,
        missingKeys: Object.entries(health.keys)
          .filter(([_, s]) => s === "missing" || s === "revoked")
          .map(([k]) => k),
      });
      return; // Do not proceed with publish
    }
  }
  // Proceed with publish API call
  await submitPublish();
};
```

### Warning block rendering

When `publishWarning` state is set, render below the Publish button:

```
┌─────────────────────────────────────────────────────────────┐
│  ⚠ Cannot publish: 2 required credentials not configured    │
│     Configure them in the Credentials tab.  [Go to Creds →] │
└─────────────────────────────────────────────────────────────┘
```

Styling:
- Background: `warn-dim` (rgba(245, 197, 24, 0.08))
- Border: `1px solid rgba(245, 197, 24, 0.2)`
- Border-radius: `var(--r)` (7px)
- Padding: 12px 16px
- Margin-top: 8px (below the Publish button)

Typography:
- Icon: warning-triangle SVG (13px, `warn` color)
- Text: 13px/500/Plus Jakarta Sans/`warn`
- "Go to Credentials →" link: `accent` color, underline on hover, `cursor: pointer`

### Tab navigation link

"Go to Credentials →" must switch the active tab in `TemplateStudioPanel` to the Credentials tab. Pass a `setActiveTab` callback down or use the tab management state that already exists in the panel.

### Auto-dismiss behaviour

The warning auto-dismisses after 8 seconds:

```typescript
useEffect(() => {
  if (!publishWarning) return;
  const timer = setTimeout(() => setPublishWarning(null), 8000);
  return () => clearTimeout(timer);
}, [publishWarning]);
```

It also dismisses on the next user interaction with the Publish button or when the user navigates away.

### Entrance and exit animations

Entrance: opacity 0→1 + translateY 4px→0, 220ms ease. Use CSS transition or a lightweight animation library consistent with the rest of the panel.

Exit (auto-dismiss and manual dismiss): opacity 1→0, 300ms ease.

```css
.publish-warning-enter {
  opacity: 0;
  transform: translateY(4px);
}
.publish-warning-enter-active {
  opacity: 1;
  transform: translateY(0);
  transition: opacity 220ms ease, transform 220ms ease;
}
.publish-warning-exit-active {
  opacity: 0;
  transition: opacity 300ms ease;
}
```

If the codebase uses Framer Motion or a CSS transition approach already, follow that pattern.

### No double-check on backend

This UI check is a client-side convenience. The backend publish gate (TODO-48) still validates server-side. If the frontend check somehow misses a missing credential and the publish API returns 422, display the API error message directly (same warning block, no auto-dismiss on error).

## Acceptance Criteria

- [ ] Clicking Publish on a `platform_credentials` template with missing credentials shows the warning block
- [ ] The warning block uses `warn-dim` background and `warn/0.2` border
- [ ] The warning text includes the count of missing credentials
- [ ] "Go to Credentials →" link switches the active tab to Credentials
- [ ] Warning auto-dismisses after 8 seconds
- [ ] Warning dismisses immediately on next user interaction with the Publish button
- [ ] Entrance animation: opacity 0→1 + translateY 4px→0 in 220ms ease
- [ ] Dismiss animation: opacity 1→0 in 300ms ease
- [ ] Warning does NOT appear for `auth_mode != 'platform_credentials'` templates
- [ ] Warning does NOT appear when all credentials are configured
- [ ] If health check returns all configured, publish proceeds directly (no warning)
- [ ] If backend returns 422 on publish (fallback), the 422 error is displayed in the same warning block
- [ ] Warning block is accessible: icon + text (not color alone) conveys the warning state
