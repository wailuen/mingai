---
id: TODO-52
title: TemplateStudioPanel — add Credentials tab and missing-count badge
status: pending
priority: medium
phase: C3
dependencies: [TODO-50, TODO-51, TODO-49]
---

## Goal

Add the "Credentials" tab to the existing tab bar in `TemplateStudioPanel.tsx`, render `CredentialsTab` as the tab panel content, and display an orange dot badge with the count of missing credentials when `auth_mode = 'platform_credentials'` and any credentials are not configured.

## Context

The Template Studio Panel currently has tabs: Edit | Test | Instances | Version History | Performance. The Credentials tab must join this bar. The tab badge provides a cross-tab signal so platform admins notice unconfigured credentials even when they are viewing another tab.

Reference: `workspaces/mingai/01-analysis/19-platform-credential-vault/04-ux-design-spec.md` — Tab Badge section. Component file: `src/web/app/(platform)/platform/agent-templates/elements/TemplateStudioPanel.tsx`.

## Implementation

### Locate the tab bar

In `TemplateStudioPanel.tsx`, find the tab bar definition (array of tab objects or JSX tab list). The current tabs are: Edit, Test, Instances, Version History, Performance.

### Add Credentials tab entry

Add "Credentials" as the last tab in the tab list. The tab is only meaningful when `auth_mode = 'platform_credentials'`. For templates with other auth modes, the tab should still render but show the empty state message (handled by `CredentialsTab` itself when `requiredCredentials` is empty or when health returns `not_required`).

### Tab panel content

When the Credentials tab is active, render:
```tsx
<CredentialsTab
  templateId={template.id}
  authMode={template.auth_mode}
  requiredCredentials={template.required_credentials ?? []}
/>
```

Import `CredentialsTab` from `./CredentialsTab`.

### Tab badge — missing credentials count

When `auth_mode = 'platform_credentials'`, call `useCredentialHealth(template.id)` to get the health status.

Compute missing count:
```typescript
const missingCount = health
  ? Object.values(health.keys).filter(s => s === "missing" || s === "revoked").length
  : 0;
```

Render a badge on the Credentials tab label when `missingCount > 0`:

```
Credentials  [2]   ← orange circle badge, top-right offset
```

Badge specification:
- Shape: 16px × 16px circle
- Position: top-right of tab text, offset -4px/-4px relative to the tab label
- Background: `alert` (`#ff6b35`)
- Text: white, 10px/600/DM Mono
- Content: `missingCount` as string (no "+" for large numbers — just the number)
- Hidden when `missingCount === 0` or `auth_mode !== 'platform_credentials'`

Tab `aria-label`: when badge is showing, `aria-label="Credentials, {N} missing"`; when no badge, standard label "Credentials".

### Badge implementation pattern

Use absolute positioning within a `position: relative` wrapper on the tab element:

```tsx
<div className="relative inline-flex">
  <span>Credentials</span>
  {missingCount > 0 && (
    <span
      aria-hidden="true"
      style={{
        position: "absolute",
        top: "-4px",
        right: "-4px",
        width: "16px",
        height: "16px",
        borderRadius: "50%",
        backgroundColor: "var(--alert)",
        color: "white",
        fontSize: "10px",
        fontWeight: 600,
        fontFamily: "DM Mono, monospace",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {missingCount}
    </span>
  )}
</div>
```

Note `aria-hidden="true"` on the badge element because the count is communicated via the parent tab's `aria-label` instead.

### Health data loading

`useCredentialHealth` is called with the template ID. During loading, no badge is shown (treat as zero missing). On error, no badge is shown. The badge only appears on a successful health response with missing count > 0.

Do not block the tab render while health is loading. The tab bar must be immediately interactive.

## Acceptance Criteria

- [ ] "Credentials" tab appears in the tab bar after "Performance"
- [ ] Clicking "Credentials" tab renders `CredentialsTab` component
- [ ] For `auth_mode = 'platform_credentials'` with missing credentials: orange badge with count is shown
- [ ] Badge: 16px circle, `alert` background, white 10px/600/DM Mono text
- [ ] Badge position: top-right offset -4px/-4px from tab label
- [ ] Badge is hidden when all credentials are configured (missingCount = 0)
- [ ] Badge is hidden for templates with `auth_mode != 'platform_credentials'`
- [ ] Tab `aria-label` when badge showing: `"Credentials, N missing"`
- [ ] Badge element has `aria-hidden="true"` (count communicated via parent aria-label)
- [ ] Tab bar remains interactive during health data loading (no loading block)
- [ ] Existing tabs (Edit, Test, Instances, Version History, Performance) are unaffected
- [ ] CredentialsTab receives `templateId`, `authMode`, and `requiredCredentials` props
