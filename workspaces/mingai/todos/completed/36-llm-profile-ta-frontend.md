---
id: 36
title: LLM Profile Redesign — Phase D: Tenant Admin Frontend
status: pending
priority: high
phase: D
estimated_days: 3
---

# LLM Profile Redesign — Phase D: Tenant Admin Frontend

## Context

The tenant-facing LLM configuration UI replaces the old settings that exposed raw model names and API keys. Three distinct experiences are needed based on the tenant's plan tier. Starter tenants see read-only info and a plan gate card. Professional tenants can select from platform profiles. Enterprise tenants get the BYOLLM configuration flow in addition to profile selection.

The BYOLLM configuration is the most complex part: a multi-step flow with an acknowledgement gate, per-slot endpoint cards, connection testing, and an activation gate that requires all required slots to be configured and tested.

Design system: Obsidian Intelligence throughout. All new components match the established patterns.

## Scope

Files to create:

- `src/web/app/settings/llm-profile/page.tsx`
- `src/web/app/settings/llm-profile/elements/StarterProfileView.tsx`
- `src/web/app/settings/llm-profile/elements/ProfessionalProfileView.tsx`
- `src/web/app/settings/llm-profile/elements/EnterpriseProfileView.tsx`
- `src/web/app/settings/llm-profile/elements/BYOLLMSection.tsx`
- `src/web/app/settings/llm-profile/elements/AddEndpointModal.tsx`
- `src/web/lib/hooks/useLLMProfileConfig.ts`

Files to modify:

- Tenant admin settings navigation — add "LLM Profile" under the appropriate settings section
- `src/web/lib/hooks/useLLMConfig.ts` — mark old hooks as deprecated (see GAP-13 below)

Files to deprecate (not delete yet — old routes still active during transition):

- `src/web/lib/hooks/useLLMConfig.ts`: add `@deprecated` JSDoc to `useLLMConfig`, `useLLMLibraryOptions`, `useUpdateLLMConfig`, `useUpdateBYOLLM`, `useDeleteBYOLLM`
- `src/web/app/(admin)/admin/settings/llm/page.tsx`: add banner "This page is being replaced by Settings > LLM Profile"

## Requirements

### D1. Settings > LLM Profile page (page.tsx)

Route: `/settings/llm-profile`

The page renders one of three views based on `tenant.plan_tier`:

- `plan_tier === 'starter'` → `<StarterProfileView />`
- `plan_tier === 'professional'` → `<ProfessionalProfileView />`
- `plan_tier === 'enterprise'` → `<EnterpriseProfileView />`

Uses `useEffectiveProfile()` to load the current profile. Loading state: skeleton rows for each slot.

### StarterProfileView

Section heading: "AI Model Configuration" (text-section-heading).

Shows: current profile name + description (platform-managed, read-only). No edit controls.

Slot table — 4 rows:

- Chat / Intent: model name in DM Mono, provider badge
- Vision / Agent: model name in DM Mono + "Enterprise" lock badge (--bg-elevated, text-faint)

Plan gate card below the table: dark card (--bg-elevated, border --border, --r-lg), accent left border. Text: "Want to choose from additional AI profiles? Upgrade to Professional to select from [N] available profiles." Button: "Explore Professional features" (accent outline).

### ProfessionalProfileView

Section: "AI Model Configuration".

Profile selector dropdown at top:

- Label: "Active Profile"
- Currently selected profile name (text-body-default, 13px/500) + description below (text-muted)
- [Change Profile] button opens a selection dropdown
- Dropdown options: profile name (13px/500) + description (11px/text-faint) + plan tier chips + `estimated_cost_per_1k_queries` in DM Mono

On profile selection: confirmation dialog "Switch to [Profile Name]? Your AI responses will use the models in this profile." [Cancel] [Confirm switch]. On confirm: calls `useSelectProfile`, invalidates hook cache, shows success toast.

Slot display (read-only after selection):

- Chat / Intent: model name in DM Mono + provider badge
- Vision / Agent: model name in DM Mono + "Enterprise" lock badge + "Upgrade to Enterprise to configure these slots" tooltip

### EnterpriseProfileView (Platform track)

Same as Professional but:

- All 4 slots visible and readable (no lock badges)
- Full profile selector with enterprise profiles included

Section below slot display: "Advanced: Bring Your Own LLM" with a [Configure custom models] link. If BYOLLM profile is active: shows BYOLLM summary instead. Link activates `BYOLLMSection`.

### EnterpriseProfileView (BYOLLM track active)

When `profile.is_byollm === true`, show `BYOLLMSection` as the primary view.

Header shows: "Custom AI Models" badge + profile name.

Per-slot rows (Chat, Intent, Vision, Agent):

- Entry name in DM Mono + provider badge
- Test timestamp: "Tested X ago" in text-faint
- [Re-test] button — retests entry, shows inline result
- [Edit] button — opens AddEndpointModal in edit mode
- [Remove] button — confirmation dialog before removing

[Use Platform Profile instead] button at bottom — confirmation dialog: "Switch back to [Platform Profile Name]? Your custom AI configuration will be preserved but deactivated." On confirm: calls API to deactivate BYOLLM and select platform default.

### BYOLLMSection

Rendered inside EnterpriseProfileView. Three states: hidden (default), acknowledgement gate, configuration.

**State 1: Acknowledgement gate**
Triggered when user clicks [Configure custom models].
Full-width card (--bg-surface, --r-lg, --border):

- Heading: "Bring Your Own LLM" (text-section-heading)
- Body: three bullet points explaining:
  - "You are responsible for the availability, cost, and performance of your custom models."
  - "Your API credentials are encrypted and stored securely. They are never visible after saving."
  - "Switching to a custom profile means your workspace will not automatically benefit from platform model upgrades."
- [Cancel] [I understand, configure my models] button (accent)

**State 2: Configuration flow**
Four slot cards (Chat, Intent, Vision, Agent):

Not configured card:

- Slot name label (text-label-nav) + "Required" or "Optional" chip
- Empty state text: "No model configured"
- [Add Model Endpoint] button

Configured card:

- Entry name (DM Mono) + provider badge + test age
- [Re-test] [Edit] [Remove] buttons

Footer area:

- [Activate Custom Profile] button — accent, full width. Disabled state: "Configure and test Chat, Intent, and Agent slots to activate" with a count badge showing remaining required slots.
- Enabled when Chat + Intent + Agent all configured and tested (test_passed_at not null)

### AddEndpointModal

Triggered by [Add Model Endpoint] or [Edit] on a slot card.
Modal: max-width 520px, --r-lg.

Header: "Configure [Slot Name] Model" (e.g. "Configure Chat Model")

Form fields:

- Provider: radio/select — Azure OpenAI | OpenAI | Anthropic | Google (affects which fields appear)
- Endpoint URL: visible for Azure OpenAI only. Text input, placeholder "https://your-resource.openai.azure.com/". Help text: "Your Azure OpenAI resource endpoint."
- API Key: password input. Write-only after save. Placeholder: "sk-..." Hint: "Never shared or displayed after saving."
- API Version: visible for Azure OpenAI only. Select or text input.
- Deployment / Model name: text input.

[Test Connection] button — inline result below fields:

- Success: accent dot + "Connected successfully — model responded in Xms"
- Auth failure: alert dot + "Authentication failed — check your API key"
- SSRF/endpoint error: alert dot + "Endpoint address is not permitted — use a supported provider URL"
- Timeout: alert dot + "Connection timed out — check the endpoint URL"

[Cancel] [Save Configuration] — Save only enabled after a successful test.

### useLLMProfileConfig hook

```typescript
useEffectiveProfile(); // GET /admin/llm-config
useAvailableProfiles(); // GET /admin/llm-config/available-profiles
useSelectProfile(profileId); // POST /admin/llm-config/select-profile
useBYOLLMEntries(); // GET /admin/byollm/library-entries
useCreateBYOLLMEntry(data); // POST /admin/byollm/library-entries
useTestBYOLLMEntry(id); // POST /admin/byollm/library-entries/{id}/test
useRotateBYOLLMKey(id, data); // PATCH /admin/byollm/library-entries/{id}/rotate-key
useActivateBYOLLMProfile(id); // POST /admin/byollm/profiles/{id}/activate
```

All mutation hooks invalidate `useEffectiveProfile` on success.

## Acceptance Criteria

- Starter: profile name shows, no selector visible, plan gate card present, Vision+Agent locked
- Professional: [Change Profile] opens selector with plan-eligible profiles only, confirmed switch updates displayed slot names
- Enterprise (platform track): all 4 slots visible without locks, BYOLLM section accessible
- BYOLLM acknowledgement gate: 3 bullet points present, user must click confirm to proceed
- AddEndpointModal: Azure fields appear only for Azure provider selection
- AddEndpointModal: [Save Configuration] disabled until test passes
- AddEndpointModal: wrong API key returns human-readable error inline (not a toast or console error)
- AddEndpointModal: private IP URL shows "Endpoint address is not permitted"
- [Activate Custom Profile] disabled until Chat + Intent + Agent all have test_passed_at
- After activation: BYOLLM view shows per-slot entry names + test ages
- [Use Platform Profile instead] reverts to platform profile view
- All text uses Plus Jakarta Sans; model names, latency, counts use DM Mono

## Dependencies

- 33 (tenant admin + BYOLLM API) — all hooks call these endpoints
- 32 (plan tier middleware) — plan tier enforced server-side; client reads plan_tier from JWT/user context
