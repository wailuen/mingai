# TODO-LLM-005: Update create and update Route Handlers for Credential Storage

## Status

Active

## Summary

Update `create_llm_library_entry` and `update_llm_library_entry` route handlers to accept, encrypt, and store the new credential fields (`api_key`, `endpoint_url`, `api_version`). The plaintext `api_key` is encrypted via `app.core.crypto.encrypt_api_key` and stored as `api_key_encrypted`. `api_key_last4` is extracted from the plaintext before encryption and stored alongside.

## Context

The request schemas (LLM-003) now accept credential fields but the route handlers do not yet write them to the DB. This todo wires the handlers to (a) call the crypto module, (b) insert/update the five new columns, and (c) clear the plaintext key from memory immediately after encryption.

## Acceptance Criteria

### create handler

- [ ] When `request.api_key` is provided, call `encrypt_api_key(request.api_key)` to get `encrypted_bytes`
- [ ] Derive `api_key_last4 = request.api_key[-4:]` before clearing
- [ ] Clear the reference: conceptually clear after use (Python GC handles this; at minimum do not retain the value in a variable after it's encrypted)
- [ ] INSERT includes `endpoint_url`, `api_key_encrypted`, `api_key_last4`, `api_version` columns (all nullable — absent when not provided)
- [ ] `api_key` is logged as `"[REDACTED]"` in structlog output
- [ ] INSERT succeeds when all credential fields are absent (backward compatible)

### update handler

- [ ] When `request.api_key` is present in the PATCH body, handle it BEFORE the allowlist loop: encrypt it, derive `last4`, add `api_key_encrypted` and `api_key_last4` to `set_parts` and `params`
- [ ] `endpoint_url` and `api_version` handled via existing allowlist loop (they are in `_UPDATE_ALLOWLIST` after LLM-003)
- [ ] `model_name` handled via allowlist loop (also added in LLM-003)
- [ ] When `api_key` is updated, `last_test_passed_at` is reset to NULL — a new key means the old test result is invalid
- [ ] UPDATE for `api_key` logs `"[REDACTED]"`
- [ ] Deprecated entries still blocked from update (existing check retained)
- [ ] PATCH with only non-credential fields works exactly as before (no regression)
- [ ] When PATCH updates api_key, endpoint_url, or api_version, last_test_passed_at is set to NULL in the same UPDATE statement

## Implementation Notes

File to edit: `src/backend/app/modules/platform/llm_library/routes.py`

Add import at top of file:

```python
from app.core.crypto import encrypt_api_key
```

In `create_llm_library_entry`, before the INSERT:

```python
encrypted_key = None
key_last4 = None
if request.api_key:
    encrypted_key = encrypt_api_key(request.api_key)
    key_last4 = request.api_key[-4:] if len(request.api_key) >= 4 else request.api_key
```

Expand the INSERT to include the 4 new columns:

```python
"INSERT INTO llm_library ("
"  id, provider, model_name, display_name, plan_tier, "
"  is_recommended, status, best_practices_md, "
"  pricing_per_1k_tokens_in, pricing_per_1k_tokens_out, "
"  endpoint_url, api_key_encrypted, api_key_last4, api_version"
") VALUES ("
"  :id, :provider, :model_name, :display_name, :plan_tier, "
"  :is_recommended, 'Draft', :best_practices_md, "
"  :pricing_in, :pricing_out, "
"  :endpoint_url, :api_key_encrypted, :api_key_last4, :api_version"
")"
```

In `update_llm_library_entry`, before the allowlist loop, add the api_key block:

```python
if request.api_key:
    from app.core.crypto import encrypt_api_key
    encrypted_key = encrypt_api_key(request.api_key)
    key_last4 = request.api_key[-4:] if len(request.api_key) >= 4 else request.api_key
    set_parts.append("api_key_encrypted = :api_key_encrypted")
    set_parts.append("api_key_last4 = :api_key_last4")
    set_parts.append("last_test_passed_at = NULL")  # key changed — old test result invalid
    params["api_key_encrypted"] = encrypted_key
    params["api_key_last4"] = key_last4
    logger.info("llm_library_api_key_updated", entry_id=entry_id, api_key="[REDACTED]")
```

Add the allowlist handlers for `endpoint_url`, `api_version`, `model_name` (three new `if` blocks following the existing pattern for `display_name` etc.).

Critical: stale test invalidation. When any credential field changes, the previous test result is no longer valid. The UPDATE statement must include: SET last_test_passed_at = NULL WHERE the PATCH includes api_key, endpoint_url, or api_version.

## Dependencies

- Depends on: LLM-001 (columns), LLM-002 (crypto module), LLM-003 (request schemas)
- Blocks: LLM-009 (unit tests)

## Test Requirements

- [ ] Integration test: POST with `api_key="sk-test1234"` → GET response has `key_present=true`, `api_key_last4="1234"`, no `api_key_encrypted` field
- [ ] Integration test: PATCH with new `api_key` → `last_test_passed_at` resets to null in GET response
- [ ] Integration test: POST without `api_key` → `key_present=false`, `api_key_last4=null`
- [ ] Unit test: `api_key` does not appear in structlog output (scan log capture for key substring)
- [ ] Integration test: PATCH on Deprecated entry → 409 (regression)
