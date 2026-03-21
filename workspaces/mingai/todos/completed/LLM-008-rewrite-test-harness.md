# TODO-LLM-008: Rewrite Test Harness to Use Entry Credentials

## Status

Active

## Summary

Replace `_run_single_test_prompt` and `test_llm_library_profile` with an implementation that decrypts the entry's stored `api_key_encrypted` and constructs a provider-specific client using the entry's own `endpoint_url`, `api_version`, and `model_name`. On all three prompts passing, write `NOW()` to `last_test_passed_at`. Remove all dependency on `AzureOpenAIProvider()` and environment variables in this endpoint.

## Context

The current test harness (lines 521-622 of routes.py) instantiates `AzureOpenAIProvider()` which reads from `AZURE_PLATFORM_OPENAI_*` env vars. Every test fires against the same global endpoint regardless of which library entry is being tested. This is the most critical bug: a platform admin can test entry A, see it "pass", but the test actually called entry B's (or the platform's) endpoint. After this fix, each test definitively verifies the exact credentials stored in that entry.

## Acceptance Criteria

- [ ] `_run_single_test_prompt` signature changes to accept `entry_config` dict instead of `model` string (or be replaced by a direct async function that takes the entry's decrypted credentials)
- [ ] For `azure_openai` entries: client constructed as `AsyncAzureOpenAI(azure_endpoint=entry.endpoint_url, api_key=decrypted_key, api_version=entry.api_version)`
- [ ] For `openai_direct` entries: client constructed as `AsyncOpenAI(api_key=decrypted_key)`
- [ ] For `anthropic` entries: client constructed as `anthropic.AsyncAnthropic(api_key=decrypted_key)`
- [ ] Decrypted key is cleared (`decrypted_key = ""`) in a `finally` block after client construction — regardless of success or failure
- [ ] `api_key_encrypted` is fetched via a separate raw SQL query (not via `_get_entry` which does not expose it); see implementation notes
- [ ] On all 3 prompts passing: `UPDATE llm_library SET last_test_passed_at = NOW() WHERE id = :id` executed
- [ ] On any prompt failing: `last_test_passed_at` is NOT updated — it retains its previous value (or null)
- [ ] `ProfileTestResponse` still returns the same `tests: list[TestPromptResult]` structure
- [ ] Entry with no `api_key_encrypted` (null) returns 422 "Cannot test entry with no API key stored"
- [ ] If api_key_encrypted IS NULL for the entry, return 422 with message: "This entry has no API key configured. Edit the entry and add credentials before testing."
- [ ] Provider string 'openai_direct' maps to AsyncOpenAI client (not 'openai' — they are different strings)
- [ ] entry.model_name is used directly as the model/deployment parameter — no slot lookup
- [ ] Structlog output contains `[REDACTED]` for any key-adjacent log field — the actual key value never appears in logs
- [ ] `AzureOpenAIProvider` is NOT imported in `test_llm_library_profile` or `_run_single_test_prompt`
- [ ] Deprecated entries still rejected with 409 (existing check retained)

## Implementation Notes

File to edit: `src/backend/app/modules/platform/llm_library/routes.py`

Add imports:

```python
from openai import AsyncAzureOpenAI, AsyncOpenAI
from app.core.crypto import decrypt_api_key
```

Anthropic import should be lazy (inside the handler) since `anthropic` is an optional package.

The test handler needs `api_key_encrypted` bytes which `_row_to_entry` does not expose. Add a separate helper:

```python
async def _get_encrypted_key(entry_id: str, db: AsyncSession) -> Optional[bytes]:
    result = await db.execute(
        text("SELECT api_key_encrypted FROM llm_library WHERE id = :id"),
        {"id": entry_id},
    )
    row = result.fetchone()
    return row[0] if row else None
```

Updated `test_llm_library_profile` handler flow:

```python
# 1. Fetch entry (metadata — no encrypted key)
entry = await _get_entry(entry_id, db)
if entry is None: raise 404
if entry.status == "Deprecated": raise 409

# 2. Fetch encrypted key separately
encrypted_key_bytes = await _get_encrypted_key(entry_id, db)
if not encrypted_key_bytes:
    raise HTTPException(422, "Cannot test entry with no API key stored")

# 3. Decrypt — clear in finally
decrypted_key = ""
try:
    decrypted_key = decrypt_api_key(encrypted_key_bytes)
    tasks = [_run_prompt_with_client(...) for p in _TEST_PROMPTS]
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=_TEST_TIMEOUT_SECONDS)
finally:
    decrypted_key = ""

# 4. On success: update last_test_passed_at
await db.execute(
    text("UPDATE llm_library SET last_test_passed_at = NOW() WHERE id = :id"),
    {"id": entry_id}
)
await db.commit()
```

For the actual provider dispatch, implement a `_build_test_client(provider, decrypted_key, endpoint_url, api_version)` helper that returns an openai-compatible client. The 3 prompts are then run against this single client rather than re-instantiating per prompt.

Note: `anthropic` SDK is currently in `pyproject.toml` as a dependency (check `uv.lock` to confirm). If not present, the `anthropic` provider test should raise 501 with a note to install the package.

Null guard: BEFORE calling decrypt_api_key(), check if api_key_encrypted is None/null. The 3 existing Published rows have null keys — they will hit this path on Test. Raise HTTPException(422) with a clear user-facing message.

Provider mapping: the llm_library uses 'openai_direct' as the provider string. Map to AsyncOpenAI client. Do NOT reuse \_do_connectivity_test() from ProviderService — the data model is different (flat entry.model_name vs provider with models dict).

## Dependencies

- Depends on: LLM-002 (crypto module), LLM-006 (entry object populated)
- Blocks: LLM-009, LLM-016

## Test Requirements

- [ ] Unit test: `_build_test_client` returns `AsyncAzureOpenAI` for `azure_openai` provider with correct params
- [ ] Unit test: decrypted key is cleared even when the LLM call raises an exception (verify via mock)
- [ ] Integration test: POST /{id}/test on entry with no API key → 422
- [ ] Integration test: POST /{id}/test on entry with valid credentials → 200 + `last_test_passed_at` set in subsequent GET
- [ ] Integration test: POST /{id}/test on Deprecated entry → 409 (regression)
- [ ] Log scan: structlog output from test call contains no raw key substring
