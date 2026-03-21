# TODO-LLM-011: Update LibraryForm.tsx — Remove Model Slots, Add Credential Fields

## Status

Active

## Summary

Rewrite `LibraryForm.tsx` to remove the entire Model Slots section and replace it with provider-conditional credential fields (`endpoint_url` for azure_openai, `api_key` for all providers with masking, `api_version` for azure_openai). Wire the Test button to call `useTestProfile` and display per-prompt results inline.

## Context

`LibraryForm.tsx` currently renders a full "Model Slots" section (4 sub-forms) that the backend silently ignores. This sends incorrect signals to the platform admin — they believe they are configuring something functional. The form also has no credential inputs, so there is no way to supply the endpoint URL and API key that are now required for publish. This is the most visible user-facing change in the redesign.

## Acceptance Criteria

### Remove from form

- [ ] `SLOT_KEYS` constant removed
- [ ] `SlotFormState` interface removed
- [ ] `FormState.slots` field removed
- [ ] `EMPTY_SLOT` constant removed
- [ ] The "Model Slots" render block removed (the `<div>` with `rounded-card border border-border bg-bg-base p-4` containing the 4 slot fields)
- [ ] `ModelSlotField` sub-component removed
- [ ] `buildModelSlots` helper function removed
- [ ] `slotFromEntry` helper function removed
- [ ] `updateSlot` function removed
- [ ] All `model_slots` references removed from `handleSaveDraft` and `handlePublish`
- [ ] Imports of `ModelSlotKey`, `ModelSlot` removed

### Add credential fields (conditional on provider)

- [ ] When `form.provider === "azure_openai"`: show `Endpoint URL` text input (placeholder: `https://ai-xxx.cognitiveservices.azure.com/`)
- [ ] For all providers: show `API Key` password input
- [ ] When key already stored (`entry?.key_present === true`): API Key input shows placeholder `****...${entry.api_key_last4}` and is not required on save (leaving it blank means "don't change the key")
- [ ] When `form.provider === "azure_openai"`: show `API Version` text input (placeholder: `2024-12-01-preview`, default value pre-filled if new entry)
- [ ] Credential fields are placed between Pricing section and Best Practices section
- [ ] Credential fields are visually grouped under a section label "Connection Credentials"

### FormState updates

- [ ] `FormState` gains: `endpoint_url: string`, `api_key: string`, `api_version: string`
- [ ] `EMPTY_FORM` sets these to empty string defaults
- [ ] `formFromEntry` populates `endpoint_url` and `api_version` from entry; `api_key` always initialises to `""` (never pre-filled from entry)

### Save payload updates

- [ ] `handleSaveDraft` includes `endpoint_url`, `api_key` (omit if empty string), `api_version` in create/update payloads
- [ ] Empty string for `api_key` must NOT be sent in PATCH (means "no change") — use `payload.api_key = form.api_key || undefined`

### Test button

- [ ] Test button only visible when `isEditing` (entry already saved — test requires a saved Draft)
- [ ] Test button enabled when `entry.key_present === true` (key is stored)
- [ ] Test button is disabled with tooltip "Save the entry first to enable testing" when entry === null (new unsaved form)
- [ ] Test button is enabled once entry has been saved (entry.id exists as a Draft)
- [ ] Click calls `testMutation.mutate(entry.id)`
- [ ] While pending: button shows spinner, disabled
- [ ] On success: renders `TestResultsPanel` inline below the form footer showing per-prompt results (prompt text, latency in ms, tokens in/out, estimated cost)
- [ ] On success with all prompts returned: shows green banner "All tests passed — entry is ready to publish"
- [ ] On error: shows error message in plain language (parse the `detail` field from the 422/502 response)
- [ ] Import `useTestProfile` from `useLLMLibrary`

### canPublish logic

- [ ] `canPublish` updated to also require `entry.last_test_passed_at !== null && entry.last_test_passed_at !== undefined`

### Pricing no longer required for Save

- [ ] `canSave` updated: pricing is optional for saving a Draft (required only for publish, enforced server-side). Remove `pricingInValid && pricingOutValid` from `canSave`. Pricing validation remains server-side in the publish gate (LLM-007).

## Implementation Notes

File to edit: `src/web/app/(platform)/platform/llm-library/elements/LibraryForm.tsx`

Design system rules (Obsidian Intelligence):

- Credential section label: `text-label-nav uppercase text-text-faint` with a `KeyRound` lucide icon (16px)
- API Key input: `type="password"` with a toggle-show button (Eye/EyeOff) — consistent with existing toggle pattern in the file
- Endpoint URL field: `font-mono text-sm` input (same as Deployment Name field)
- Test button: outlined variant (not accent-filled) since it is an action, not a save: `border border-border text-text-muted hover:border-accent hover:text-accent`
- TestResultsPanel: `rounded-card border border-border bg-bg-base p-4 space-y-3 mt-4`; each result row in a small grid showing prompt (truncated), latency (DM Mono), tokens (DM Mono), cost (DM Mono)

New state:

```typescript
const testMutation = useTestProfile();
const [testResults, setTestResults] = useState<TestPromptResult[] | null>(null);
```

Call on test success:

```typescript
testMutation.mutate(entry.id, {
  onSuccess: (data) => setTestResults(data.tests),
  onError: (err) => setTestResults(null),
});
```

## Dependencies

- Depends on: LLM-010 (types updated)
- Blocks: LLM-016 (E2E test verifies this form)

## Test Requirements

- [ ] `tsc --noEmit` passes
- [ ] Manual: create new azure_openai entry — credential section visible, slots section absent
- [ ] Manual: fill endpoint + key + version → save → test → see results inline
- [ ] Manual: after test passes, Publish button becomes enabled
- [ ] E2E test in LLM-016 validates the complete flow
