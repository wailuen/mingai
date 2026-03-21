# TODO-LLM-017: Document and Handle Existing Published Rows Migration Path

## Status

Active

## Summary

The 3 existing Published entries (aihub2-main, intent5, text-embedding-3-large) have no credentials after the schema migration. Create a platform admin runbook documenting the manual steps to add credentials to these entries, and add a backend admin-only bulk-status endpoint or script to facilitate this. Ensure the test endpoint works correctly on these "legacy" entries before and after credentials are added.

## Context

After LLM-001 runs, the 3 existing Published rows will have all 5 new columns as NULL. The publish gate (LLM-007) only applies on Draft → Published transitions, so these rows remain Published. However, the test endpoint after LLM-008 will return 422 "Cannot test entry with no API key stored" for them. Platform admins need a clear path to bring these entries into the new credential model without re-publishing them.

The analysis (section 11) identifies the migration path:

1. Admin edits each entry to add endpoint_url, api_key, api_version
2. Runs test on each — verifies connectivity
3. Entry now has `last_test_passed_at` set

No forced re-publish is needed — the entries are already Published. The test simply serves as a verification step.

## Acceptance Criteria

- [ ] `docs/00-authority/RUNBOOKS.md` (or equivalent runbook file — locate it first) has a section "LLM Library: Credentialize Existing Published Entries"
- [ ] Runbook documents: for each existing entry, PATCH with endpoint_url + api_key + api_version, then POST /{id}/test
- [ ] Runbook includes the exact PATCH payload for azure_openai entries
- [ ] Runbook includes a verification step: after patching, GET the entry and confirm `key_present=true` and `api_key_last4` is correct
- [ ] Test endpoint returns 422 with message "Cannot test entry with no API key stored" for existing entries before credentials are added (not a 500 or unhelpful error)
- [ ] After credentials are added and test passes, `last_test_passed_at` is set even on existing Published entries (no special-casing needed — test endpoint works the same for all statuses except Deprecated)
- [ ] The PATCH endpoint allows updating `endpoint_url`, `api_key`, `api_version` on Published entries (not just Draft entries) — verify this is true by checking the Deprecated-only guard in the update handler

## Implementation Notes

The update handler currently has:

```python
if entry.status == "Deprecated":
    raise HTTPException(status_code=409, detail="Deprecated entries cannot be modified.")
```

This means Published entries CAN be PATCH'd — which is correct for the credential migration path. Verify this is still the case after LLM-005 changes.

For the runbook, provide curl examples:

```bash
# Add credentials to existing entry
curl -X PATCH https://api.mingai.dev/api/v1/platform/llm-library/{id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"endpoint_url": "https://ai-xxx.cognitiveservices.azure.com/", "api_key": "...", "api_version": "2024-12-01-preview"}'

# Run test to verify
curl -X POST https://api.mingai.dev/api/v1/platform/llm-library/{id}/test \
  -H "Authorization: Bearer $TOKEN"

# Verify result
curl https://api.mingai.dev/api/v1/platform/llm-library/{id} \
  -H "Authorization: Bearer $TOKEN" | jq '{key_present, api_key_last4, last_test_passed_at}'
```

The 3 entry IDs are unknown at the time of this todo — the runbook should instruct the admin to run `GET /platform/llm-library?status=Published` and identify entries by `display_name`.

## Dependencies

- Depends on: LLM-005 (PATCH handler supports credentials), LLM-008 (test endpoint uses entry credentials)
- Blocks: nothing

## Test Requirements

- [ ] Manual verification: PATCH a Published entry in a local dev environment to add credentials → GET shows `key_present=true`
- [ ] Manual verification: POST /{id}/test on the now-credentialed Published entry → 200 with test results
