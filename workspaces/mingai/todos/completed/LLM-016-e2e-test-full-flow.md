# TODO-LLM-016: E2E Test — Full Create → Credentials → Test → Publish Flow

## Status

Active

## Summary

Write a Playwright E2E test that exercises the complete LLM Library happy path: create a Draft azure_openai entry, fill in credentials, save, run the connectivity test, verify test results appear, then publish. Also verify the 3 existing entries are unaffected, and that `api_key` never appears in any network response.

## Context

The redesign changes the platform admin workflow from a pure form-fill to a form-fill + test gate. The E2E test must validate the complete new workflow is functional end-to-end with real credentials. It also serves as a regression guard for the 3 existing rows that were created before credentials existed.

## Acceptance Criteria

### Pre-flight checks

- [ ] Backend is running and healthy (`GET /api/v1/health` returns 200)
- [ ] Frontend dev server is running at port 3022
- [ ] Platform admin credentials available in env: `PLATFORM_ADMIN_EMAIL`, `PLATFORM_ADMIN_PASSWORD`
- [ ] Azure OpenAI test credentials available in env: `TEST_AZURE_ENDPOINT`, `TEST_AZURE_API_KEY`, `TEST_AZURE_API_VERSION`, `TEST_AZURE_DEPLOYMENT`

### Create flow

- [ ] Navigate to `/platform/llm-library`
- [ ] Click "New Entry" (or equivalent button)
- [ ] Fill: Display Name = "E2E Test Entry [timestamp]", Provider = Azure OpenAI, Deployment = `TEST_AZURE_DEPLOYMENT` value, Plan Tier = Starter, Pricing In = 0.000150, Pricing Out = 0.000600
- [ ] Fill credentials: Endpoint URL = `TEST_AZURE_ENDPOINT`, API Key = `TEST_AZURE_API_KEY`, API Version = `TEST_AZURE_API_VERSION`
- [ ] Click "Save Draft"
- [ ] Entry appears in list with status "Draft"
- [ ] `Key` column shows "Key set" badge for the new entry
- [ ] Verify GET /api/v1/platform/llm-library/{id} response body does NOT contain `api_key_encrypted` field

### Test flow

- [ ] Open edit form for the newly created entry
- [ ] API Key field shows `****...{last4}` masking (not the actual key)
- [ ] "Test" button is visible and enabled
- [ ] Click "Test" button
- [ ] Spinner appears during test execution
- [ ] Test results panel appears with 3 rows (one per test prompt): prompt text, latency ms, tokens in/out, estimated cost
- [ ] "All tests passed" success banner appears
- [ ] Close form and verify list shows the entry with a non-null `Tested` column value

### Publish flow

- [ ] "Publish" button in `LifecycleActions` column is now enabled
- [ ] Click Publish
- [ ] Entry status changes to "Published" in the list
- [ ] Verify `GET /api/v1/platform/llm-library/{id}` returns `status: "Published"`

### Existing rows preservation

- [ ] Verify all 3 original entries (aihub2-main, intent5, text-embedding-3-large) still appear in the list
- [ ] Verify they retain `Published` status
- [ ] Verify `key_present` is `false` for all 3 (no credentials migrated)

### Security invariants

- [ ] Intercept all `GET /api/v1/platform/llm-library*` network responses during the test
- [ ] Verify none of them contain the string `api_key_encrypted` in the response body
- [ ] Verify none of them contain the actual `TEST_AZURE_API_KEY` value in the response body

### Cleanup

- [ ] Deprecate the test entry after the test (POST /deprecate) to avoid polluting the library with test data

## Implementation Notes

File to create: `src/web/tests/e2e/llm-library-credentials.spec.ts` (or follow existing E2E test directory convention — check `src/web/tests/e2e/` for existing test files)

Use the E2E god-mode rules: if the test entry is not found after create, query the list and find it by display_name prefix rather than hardcoded ID.

Test credentials must come from environment variables:

```typescript
const testEndpoint = process.env.TEST_AZURE_ENDPOINT!;
const testKey = process.env.TEST_AZURE_API_KEY!;
const testVersion = process.env.TEST_AZURE_API_VERSION ?? "2024-12-01-preview";
const testDeployment = process.env.TEST_AZURE_DEPLOYMENT!;
```

For the API key security check, use Playwright's `page.on("response", ...)` to intercept all responses and scan their bodies for the key value.

The test must be idempotent — if a previous run left a "E2E Test Entry" in the library, find it and reuse or deprecate/recreate.

## Dependencies

- Depends on: LLM-008 (test harness), LLM-011 (form), LLM-012 (list), LLM-013 (lifecycle actions)
- Blocks: nothing (terminal)

## Test Requirements

This todo IS the E2E test requirement. The test must pass against a live environment with real Azure OpenAI credentials to be marked complete.

Note: This is a Tier 3 test — no mocking allowed. Real LLM calls, real DB, real browser.
