# TODO-LLM-010: Update useLLMLibrary.ts — Remove Slot Types, Add Credential Types

## Status

Active

## Summary

Update `src/web/lib/hooks/useLLMLibrary.ts` to remove all slot-related types (`ModelSlotKey`, `ModelSlot`), remove `model_slots` from payload types, and add credential fields (`endpoint_url`, `api_key`, `api_version`, `key_present`, `api_key_last4`, `last_test_passed_at`) to the `LLMLibraryEntry` interface and payload types.

## Context

`useLLMLibrary.ts` is the single source of truth for TypeScript types shared across `LibraryForm.tsx`, `LibraryList.tsx`, and `LifecycleActions.tsx`. The slot types (`ModelSlotKey`, `ModelSlot`) belong in a future LLM Profiles hook — they are wrong here. The `TestProfileResult` type also needs replacing: the current type describes slot-based results which the backend never actually returned.

## Acceptance Criteria

- [ ] `ModelSlotKey` type export REMOVED
- [ ] `ModelSlot` interface REMOVED
- [ ] `model_slots?: Record<ModelSlotKey, ModelSlot>` removed from `LLMLibraryEntry`, `CreateLLMLibraryPayload`, `UpdateLLMLibraryPayload`
- [ ] `LLMLibraryEntry` gains: `endpoint_url?: string`, `api_version?: string`, `key_present: boolean`, `api_key_last4?: string`, `last_test_passed_at?: string`
- [ ] `CreateLLMLibraryPayload` gains: `endpoint_url?: string`, `api_key?: string`, `api_version?: string`
- [ ] `UpdateLLMLibraryPayload` gains: `endpoint_url?: string`, `api_key?: string`, `api_version?: string`, `model_name?: string` (model_name was missing from update payload)
- [ ] `TestProfileResult` interface replaced with `TestEntryResult` that matches the actual backend `ProfileTestResponse` shape: `{ tests: TestPromptResult[] }`
- [ ] `TestPromptResult` interface: `{ prompt: string; response: string; tokens_in: number; tokens_out: number; latency_ms: number; estimated_cost_usd: number | null }`
- [ ] `useTestProfile` mutation updated to use new `TestEntryResult` type
- [ ] TestProfileResult type rewritten to match actual backend response: { tests: Array<{ prompt: string; response: string; tokens_in: number; tokens_out: number; latency_ms: number; estimated_cost_usd: number | null }> }
- [ ] Remove TestProfileResult.slot_results (old slot-based shape) entirely
- [ ] No TypeScript errors (`tsc --noEmit` passes)
- [ ] `LLMLibraryEntry.pricing_per_1k_tokens_in` changed from `number` to `number | null` (backend returns null for unset pricing — existing type was too strict)

## Implementation Notes

File to edit: `src/web/lib/hooks/useLLMLibrary.ts`

Remove entirely:

```typescript
export type ModelSlotKey = "intent_model" | "primary_model" | "vision_model" | "embedding_model";
export interface ModelSlot { ... }
```

Updated `LLMLibraryEntry`:

```typescript
export interface LLMLibraryEntry {
  id: string;
  provider: LLMLibraryProvider;
  model_name: string;
  display_name: string;
  plan_tier: PlanTier;
  is_recommended: boolean;
  status: LLMLibraryStatus;
  best_practices_md?: string;
  pricing_per_1k_tokens_in: number | null;
  pricing_per_1k_tokens_out: number | null;
  endpoint_url?: string;
  api_version?: string;
  key_present: boolean;
  api_key_last4?: string;
  last_test_passed_at?: string;
  created_at: string;
  updated_at?: string;
}
```

Updated `CreateLLMLibraryPayload`:

```typescript
export interface CreateLLMLibraryPayload {
  provider: LLMLibraryProvider;
  model_name: string;
  display_name: string;
  plan_tier: PlanTier;
  is_recommended?: boolean;
  best_practices_md?: string;
  pricing_per_1k_tokens_in: number;
  pricing_per_1k_tokens_out: number;
  endpoint_url?: string;
  api_key?: string;
  api_version?: string;
}
```

New `TestEntryResult` and `TestPromptResult`:

```typescript
export interface TestPromptResult {
  prompt: string;
  response: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  estimated_cost_usd: number | null;
}

export interface TestEntryResult {
  tests: TestPromptResult[];
}
```

Update `useTestProfile`:

```typescript
export function useTestProfile() {
  return useMutation({
    mutationFn: (id: string) =>
      apiPost<TestEntryResult>(`/api/v1/platform/llm-library/${id}/test`, {}),
  });
}
```

The existing TestProfileResult type has slot_results: Record<ModelSlotKey, ...> which completely mismatches the backend ProfileTestResponse schema. The backend returns a flat tests array. This mismatch causes silent data loss — test results will not display correctly.

## Dependencies

- Depends on: LLM-004 (backend response model defines what fields are available)
- Blocks: LLM-011, LLM-012, LLM-013

## Test Requirements

- [ ] `tsc --noEmit` passes with no type errors
- [ ] All imports of `ModelSlotKey` and `ModelSlot` in consuming components have been removed (TypeScript compilation catches these)
- [ ] `LibraryForm.tsx` compiles after LLM-011 removes slot references
