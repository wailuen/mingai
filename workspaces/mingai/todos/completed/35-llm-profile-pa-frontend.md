---
id: 35
title: LLM Profile Redesign — Phase C: Platform Admin Frontend
status: pending
priority: high
phase: C
estimated_days: 3
---

# LLM Profile Redesign — Phase C: Platform Admin Frontend

## Context

The platform admin needs a complete UI to create and manage LLM profiles — assign slots, set the default, test profiles, and monitor which tenants are using each profile. This integrates into the existing Platform Admin sidebar under the Intelligence section.

The LLM Library form also needs cleanup: the old slot-based structure (where admins filled in model names per slot in the library) is removed. Library entries are now single-model connections. Platform admins set eligible_slots in the capabilities JSON to control which profile slots can use the entry.

Design system: Obsidian Intelligence. Dark-first. Accent #4fffb0 (mint). Plus Jakarta Sans for all text, DM Mono for data values (model names, latency, token counts). Cards use --r-lg (10px). Inputs use --r (7px).

## Scope

Files to create:

- `src/web/app/(platform)/platform/llm-profiles/page.tsx`
- `src/web/app/(platform)/platform/llm-profiles/elements/ProfileDetailPanel.tsx`
- `src/web/app/(platform)/platform/llm-profiles/elements/SlotSelector.tsx`
- `src/web/app/(platform)/platform/llm-profiles/elements/CreateProfileModal.tsx`
- `src/web/lib/hooks/usePlatformLLMProfiles.ts`

Files to modify:

- Platform admin sidebar (wherever the nav links are rendered in `src/web/app/(platform)/`) — add "LLM Profiles" under Intelligence section, below LLM Library
- `src/web/app/(platform)/platform/llm-library/elements/LibraryForm.tsx` — remove old slot fields, add capabilities editor
- `src/web/lib/hooks/useLLMLibrary.ts` — update types

## Requirements

### C1. Navigation

Add "LLM Profiles" to the Platform sidebar Intelligence section, positioned after "LLM Library". Use the same nav item component pattern as existing items. Link to `/platform/llm-profiles`.

### C2. LLM Profiles List Page (page.tsx)

Header row: page title "LLM Profiles" (text-page-title, 22px/700) + "New Profile" button (primary, accent background).

Profile list table columns:

- Name (text-body-default, 13px/500)
- Chat / Intent / Vision / Agent — each shows the model name (DM Mono, 13px) or an empty dash in text-faint
- Plan Tiers — chips: starter (--bg-elevated), professional (--warn-dim), enterprise (--accent-dim)
- Tenants — count in DM Mono
- Status — badge: active (accent), draft (--bg-elevated, text-muted), deprecated (alert-dim)
- Default star icon — accent coloured star for the platform default profile

Row click: opens `ProfileDetailPanel` as slide-in from right (480px wide, full height).

Table header: 11px uppercase letter-spacing .05em, --text-faint. Row hover: --accent-dim background.

### C3. ProfileDetailPanel (slide-in)

Header: profile name (text-section-heading, 15px/600) + status badge + close button.

Sections in order:

**ProfileIdentitySection**: name field (editable inline), description (editable inline), status badge. [Save changes] button appears when edits are detected.

**SlotAssignmentSection**: 4 rows, one per slot (Chat, Intent, Vision, Agent).

- Each row: slot label (text-label-nav, 11px uppercase) + SlotSelector component + params preview badge
- Unassigned slot: "Not assigned" in text-faint + [Assign] button
- Assigned slot: model name in DM Mono + health dot + [Change] button

**PlanAvailabilitySection**: checkboxes for Starter / Professional / Enterprise. Label explains: "This profile will appear in the selector for tenants on these plans."

**TenantUsageSection**: "X tenants using this profile" count + scrollable list showing tenant name + plan tier badge. If 0 tenants: "No tenants are using this profile yet."

**TestProfileSection**: "Test All Slots" button. On click: runs all assigned slots in parallel, shows per-slot result cards:

- Slot name (label-nav) + model name (DM Mono)
- Latency in ms (DM Mono, accent if < 1000ms, warn if 1000-3000ms, alert if > 3000ms)
- Token count (DM Mono)
- Response snippet (2 lines, text-muted, truncated)
- Error state: alert colour, plain language message

**Actions** (bottom of panel, separated by border-top):

- "Set as Platform Default" — accent outline button. Disabled + tooltip if profile has required slots unassigned. Shows current default indicator if this is the default.
- "Deprecate Profile" — alert colour, outline. Disabled with count badge "Used by N tenants" if active tenants exist.

### C4. SlotSelector Component

Dropdown triggered by [Assign] / [Change] button in SlotAssignmentSection.

Data: fetches `GET /platform/llm-profiles/available-models/{slot}` when opened (not on page load).

Each option in dropdown:

- Model name in DM Mono (13px/400) — primary label
- Provider badge (small chip, --bg-elevated) — e.g. "Azure OpenAI"
- Health dot — accent (healthy), warn (unknown), alert (degraded)
- Test age — "Tested 2h ago" in text-faint, or "Not tested" in alert if test_passed_at is null
- Deprecation warning: if entry is deprecated, show "Deprecated" chip in alert-dim and disable selection

Search input at top of dropdown (filters by model name, provider name).

Empty state: "No eligible models for this slot. Add entries in LLM Library." with link.

After selection: confirm button (not auto-save) — allows user to cancel.

### C5. CreateProfileModal

Two-step modal (max-width 560px, --r-lg):

Step 1 of 2: Profile Details

- Name field (required, max 80 chars)
- Description field (optional, max 300 chars, textarea 3 rows)
- Plan tiers checkboxes
- [Cancel] [Next: Assign Slots →]

Step 2 of 2: Assign Slots

- 4 SlotSelector rows (Chat required, Intent required, Vision optional, Agent optional)
- Note: "You can assign slots after creation — a profile can be saved without all slots filled."
- [← Back] [Create Profile]

On create: POST to `/platform/llm-profiles`, then refresh list, open detail panel for new profile.

### C6. LLM Library Form Cleanup

Remove from `LibraryForm.tsx`:

- `SLOT_KEYS` constant
- `SlotFormState` interface
- `FormState.slots` field
- The "Model Slots" render block (the section where admins used to fill in model names per slot)

Add to `LibraryForm.tsx`:

- Capabilities JSON editor (multi-line textarea, validates JSON on blur)
- Pre-populated with default: `{"eligible_slots": ["chat", "intent"], "supports_vision": false}`
- Health status display row (below connection fields): health dot + "Last checked: X ago" or "Not yet checked"

Update `useLLMLibrary.ts` types:

- Remove `slots` field from library entry type
- Add `capabilities: Record<string, unknown>` and `health_status: 'healthy' | 'degraded' | 'unknown'` and `health_checked_at: string | null`

### usePlatformLLMProfiles hook

- `useProfileList()` → GET /platform/llm-profiles, SWR with 30s revalidation
- `useProfileDetail(id)` → GET /platform/llm-profiles/{id}
- `useCreateProfile(data)` → POST /platform/llm-profiles
- `useUpdateProfile(id, data)` → PATCH /platform/llm-profiles/{id}
- `useAssignSlot(profileId, slot, data)` → PATCH /platform/llm-profiles/{id}/slots/{slot}
- `useSetDefault(profileId)` → POST /platform/llm-profiles/{id}/set-default
- `useTestProfile(profileId)` → POST /platform/llm-profiles/{id}/test
- `useAvailableModels(slot)` → GET /platform/llm-profiles/available-models/{slot} (fetched on demand)
- `useProfileTenants(profileId)` → GET /platform/llm-profiles/{id}/tenants

## Acceptance Criteria

- "LLM Profiles" appears in Platform sidebar under Intelligence section
- Profile list shows all platform profiles with correct slot names and status
- SlotSelector dropdown shows only entries with the slot in eligible_slots
- Cannot select a deprecated library entry via SlotSelector
- "Set as Default" is disabled when required slots (chat, intent) are unassigned
- "Deprecate" is disabled when tenants_count > 0 (shows count badge)
- "Test All Slots" shows per-slot results including latency (DM Mono) and response snippet
- LibraryForm no longer shows slot fields; shows capabilities JSON editor instead
- CreateProfileModal: Step 1 → Step 2 navigation works, Back navigation preserves inputs
- All text uses Plus Jakarta Sans; data values (model names, latency, counts) use DM Mono
- No purple, blue, or non-design-system colors used

## Dependencies

- 32 (platform API) — all hooks call these endpoints
- 27 (schema) — capabilities field on llm_library entries
