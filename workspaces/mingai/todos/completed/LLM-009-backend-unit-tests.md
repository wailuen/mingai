# TODO-LLM-009: Backend Unit and Integration Tests for Credential Features

## Status

Active

## Summary

Write the full test suite for the backend changes introduced by LLM-001 through LLM-008. Tests cover: Fernet encryption round-trip in `crypto.py`, publish gate per-provider validation, test harness client construction, key-never-in-response invariant, and credential storage/retrieval via the HTTP routes.

## Context

The redesign touches security-critical code. Encryption round-trips, key memory clearing, and the publish gate must all have explicit test coverage before any code ships. The existing test infrastructure (`tests/unit/` and `tests/integration/`) follows established patterns — new tests must follow the same conventions (pytest, fixtures from `conftest.py`, real SQLite for integration tests via AsyncSession).

## Acceptance Criteria

- [ ] All new tests in correct tier directories: unit tests in `tests/unit/`, integration tests in `tests/integration/`
- [ ] All new tests pass (`pytest tests/unit/` and `pytest tests/integration/`)
- [ ] No mocking in integration tests (real DB, real crypto)
- [ ] Test file for crypto module: `tests/unit/test_crypto.py`
- [ ] Test file for routes: `tests/integration/test_llm_library_credentials.py`

### test_crypto.py (unit tests)

- [ ] `test_encrypt_decrypt_round_trip`: encrypt a key string, decrypt it, verify match
- [ ] `test_decrypt_tampered_ciphertext_raises`: tamper with encrypted bytes, verify `ValueError`
- [ ] `test_decrypt_empty_bytes_raises`: pass empty bytes, verify `ValueError` or similar
- [ ] `test_decrypt_without_jwt_secret_raises`: monkeypatch `JWT_SECRET_KEY=""`, verify `ValueError`
- [ ] `test_api_key_last4_derivation`: verify `key[-4:]` logic for keys shorter than 4 chars

### test_llm_library_credentials.py (integration tests)

- [ ] `test_create_entry_with_api_key_stores_encrypted`: POST with `api_key`, verify DB has `api_key_encrypted` (BYTEA, not plaintext), verify response has `key_present=True` and `api_key_last4` correct
- [ ] `test_create_entry_without_api_key_key_present_false`: POST without `api_key`, verify `key_present=False`
- [ ] `test_api_key_never_in_response`: POST with `api_key`, GET, verify response JSON contains no `api_key_encrypted` key at any level
- [ ] `test_update_entry_api_key_resets_test_timestamp`: PATCH with new `api_key` on entry that had `last_test_passed_at` set, verify GET shows `last_test_passed_at=null`
- [ ] `test_publish_gate_requires_api_key`: Draft entry + pricing + test passed but no key → 422
- [ ] `test_publish_gate_requires_test_passed`: Draft entry + key + pricing but no test → 422
- [ ] `test_publish_gate_azure_requires_endpoint`: azure_openai entry + key + test + pricing but no `endpoint_url` → 422
- [ ] `test_publish_gate_azure_requires_api_version`: azure_openai entry + key + test + pricing + endpoint but no `api_version` → 422
- [ ] `test_publish_gate_fully_configured_azure`: fully configured azure_openai entry → 200 Published
- [ ] `test_publish_gate_openai_direct_no_endpoint_required`: `openai_direct` entry with key + test + pricing, no endpoint → 200 Published
- [ ] `test_test_endpoint_no_key_stored_returns_422`: call POST /{id}/test on entry with no `api_key_encrypted` → 422
- [ ] `test_update_model_name_allowed`: PATCH with `model_name` in payload → deployment name updated in GET

## Implementation Notes

Test file locations:

- `src/backend/tests/unit/test_crypto.py`
- `src/backend/tests/integration/test_llm_library_credentials.py`

For integration tests: use the existing `test_client` and `admin_headers` fixtures from `conftest.py`. Follow the patterns in `tests/integration/test_llm_providers.py` which tests the analogous provider credential routes.

For the publish gate integration tests: manually set `last_test_passed_at` in the test setup via direct DB UPDATE (since the test harness requires real LLM connectivity — these are unit-level checks of the gate logic, not E2E connectivity tests).

Do NOT mock the Fernet encryption in integration tests — use a real `JWT_SECRET_KEY` value from the test `.env`.

## Dependencies

- Depends on: LLM-002 (crypto module), LLM-003, LLM-004, LLM-005, LLM-006, LLM-007, LLM-008 (all backend changes)
- Blocks: nothing (tests are terminal)

## Test Requirements

This todo IS the test requirement. All tests in this todo must pass before marking complete.
