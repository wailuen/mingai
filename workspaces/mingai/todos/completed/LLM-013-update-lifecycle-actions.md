# TODO-LLM-013: Update LifecycleActions.tsx — Publish Button Requires Test Passed

## Status

Active

## Summary

Update `LifecycleActions.tsx` to disable the Publish button (and show a tooltip explanation) when `entry.last_test_passed_at` is null. This is a UI affordance complementing the server-side publish gate in LLM-007. The server remains authoritative — this change improves discoverability by preventing the admin from attempting publish before running the test.

## Context

`LifecycleActions.tsx` renders inline in the list view (one row per entry). The current Publish button is enabled for any Draft entry. After the redesign, Publish should only be enabled when the entry has passed the connectivity test. The admin's workflow is: fill credentials in the form → test → see "ready to publish" → click Publish in the list OR in the form.

## Acceptance Criteria

- [ ] Publish button disabled when `entry.status === "Draft"` AND `entry.last_test_passed_at` is null or undefined
- [ ] When disabled due to no test: button shows tooltip (HTML `title` attribute) "Run the connectivity test before publishing"
- [ ] When disabled due to no test: button visual matches the design system disabled state (`opacity-40`)
- [ ] When enabled (test passed): button behavior unchanged — calls `publishMutation.mutate(entry.id)`
- [ ] `publishMutation.error` display retained (shown when publish API call fails)
- [ ] Deprecate flow (Published → Deprecated confirm) unchanged
- [ ] Deprecated state rendering unchanged
- [ ] No new network calls or state introduced (uses existing `entry` prop fields — `last_test_passed_at` is now in the type from LLM-010)
- [ ] useTestProfile mutation calls queryClient.invalidateQueries({ queryKey: ["platform-llm-library-entry", id] }) on success so the re-fetched entry has the updated last_test_passed_at
- [ ] Publish button disabled state is driven by entry.last_test_passed_at === null (not null = test passed, null = not yet tested)

## Implementation Notes

File to edit: `src/web/app/(platform)/platform/llm-library/elements/LifecycleActions.tsx`

The `entry` prop is of type `LLMLibraryEntry`. After LLM-010, this type has `last_test_passed_at?: string`.

Change the Publish button section:

```typescript
const canPublish = entry.status === "Draft" && !!entry.last_test_passed_at;
const publishTitle = canPublish
  ? undefined
  : "Run the connectivity test before publishing";

// In the render:
{entry.status === "Draft" && (
  <button
    type="button"
    onClick={handlePublish}
    disabled={publishMutation.isPending || !canPublish}
    title={publishTitle}
    className="inline-flex items-center gap-1 rounded-control bg-accent px-2.5 py-1 text-[11px] font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
  >
    {publishMutation.isPending ? (
      <Loader2 size={12} className="animate-spin" />
    ) : (
      <CheckCircle2 size={12} />
    )}
    Publish
  </button>
)}
```

Note: the `title` attribute provides a native browser tooltip on hover — sufficient for this use case. No custom tooltip component needed.

Query cache invalidation is critical: after a passing test, the backend sets last_test_passed_at in the DB, but the frontend cache still has the old entry object (last_test_passed_at = null). Without invalidation, the Publish button stays disabled even after a successful test.

## Dependencies

- Depends on: LLM-010 (type has `last_test_passed_at`)
- Depends on: LLM-007 (server-side gate — this is the UI mirror)
- Blocks: LLM-016

## Test Requirements

- [ ] `tsc --noEmit` passes
- [ ] Manual: Draft entry with no test → Publish button disabled, `opacity-40`, hover shows tooltip text
- [ ] Manual: Draft entry after test passed → Publish button enabled
- [ ] Manual: Publish button click on enabled entry → calls API → entry transitions to Published in list (via query invalidation)
