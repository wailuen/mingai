# TODO-LLM-007: Rewrite Publish Gate with Provider-Specific Validation

## Status

Active

## Summary

Replace the current `publish_llm_library_entry` validation (which only checks `model_name`, `provider`, and pricing) with a complete provider-specific publish gate that also requires: `api_key` set (`key_present=True`), `last_test_passed_at` not null, and for `azure_openai` specifically: `endpoint_url` and `api_version` set.

## Context

The current publish gate (lines 413-430 of routes.py) can publish an entry that has no endpoint URL, no API key, and has never been tested. This means tenants can be assigned a completely non-functional library entry. The redesign requires that every published entry has been verified to actually connect. The gate is enforced server-side so the frontend publish button state (LLM-013) is just a UI affordance — the server is the authoritative enforcer.

## Acceptance Criteria

- [ ] Pricing check retained: `pricing_per_1k_tokens_in` and `pricing_per_1k_tokens_out` both required (existing)
- [ ] API key check added: `key_present` must be `True` — returns 422 "api_key must be set before publishing"
- [ ] Test gate added: `last_test_passed_at` must not be null — returns 422 "Entry must pass a connectivity test before publishing"
- [ ] Azure-specific checks: when `provider == "azure_openai"`: `endpoint_url` must not be null/empty AND `api_version` must not be null/empty — returns 422 "Azure OpenAI entries require endpoint_url, api_key, and api_version"
- [ ] All 422 responses include a `detail` string that is human-readable (the frontend displays this message verbatim)
- [ ] Check order: provider-specific first, then key check, then test gate, then pricing (more specific errors shown first)
- [ ] Existing rows that are already `Published` are NOT retroactively affected — the gate only applies on Draft → Published transitions (this is already the case since the handler checks `entry.status != "Draft"` first)
- [ ] The 3 existing published rows (aihub2-main, intent5, text-embedding-3-large) without credentials remain Published and unaffected

## Implementation Notes

File to edit: `src/backend/app/modules/platform/llm_library/routes.py`

Replace the validation block in `publish_llm_library_entry` (after the status check):

```python
# Provider-specific required fields
if entry.provider == "azure_openai":
    if not entry.endpoint_url or not entry.api_version:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Azure OpenAI entries require endpoint_url and api_version before publishing",
        )

# All providers require an API key
if not entry.key_present:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="api_key must be set before publishing",
    )

# All providers require a successful connectivity test
if entry.last_test_passed_at is None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Entry must pass a connectivity test before publishing",
    )

# All providers require pricing
if entry.pricing_per_1k_tokens_in is None or entry.pricing_per_1k_tokens_out is None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="pricing_per_1k_tokens_in and pricing_per_1k_tokens_out must be set before publishing",
    )
```

Note: `entry.key_present` is a bool derived in `_row_to_entry` from `api_key_encrypted IS NOT NULL`. We do NOT need to re-query the DB to check this — the already-loaded entry object has the value.

## Dependencies

- Depends on: LLM-006 (entry object has new fields populated)
- Blocks: LLM-009, LLM-013

## Test Requirements

- [ ] Integration test: Draft entry with no credentials → POST /publish returns 422 "api_key must be set"
- [ ] Integration test: Draft entry with key set but no test → POST /publish returns 422 "must pass a connectivity test"
- [ ] Integration test: azure_openai Draft entry with key + test but no endpoint_url → POST /publish returns 422 "require endpoint_url and api_version"
- [ ] Integration test: azure_openai Draft entry fully configured + test passed → POST /publish returns 200
- [ ] Integration test: openai_direct Draft entry with key + test (no endpoint_url needed) → POST /publish returns 200
- [ ] Integration test: Already-Published entry → POST /publish returns 409 (regression)
