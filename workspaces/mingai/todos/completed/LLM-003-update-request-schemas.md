# TODO-LLM-003: Update CreateLLMLibraryRequest and UpdateLLMLibraryRequest Schemas

## Status

Active

## Summary

Add `endpoint_url`, `api_key`, and `api_version` fields to both `CreateLLMLibraryRequest` and `UpdateLLMLibraryRequest` Pydantic models in `routes.py`. Add `model_name` to `_UPDATE_ALLOWLIST`. The `api_key` field accepts plaintext on the wire but is never stored as plaintext.

## Context

The current request schemas have no credential fields. The frontend form sends these fields but the backend silently discards them. This todo adds the Pydantic-layer definitions only — the storage logic is in LLM-005. The separation ensures schema validation (field types, length limits) is independently testable.

## Acceptance Criteria

- [ ] `CreateLLMLibraryRequest` gains three new optional fields: `endpoint_url: Optional[str] = Field(None, max_length=500)`, `api_key: Optional[str] = None`, `api_version: Optional[str] = Field(None, max_length=50)`
- [ ] `UpdateLLMLibraryRequest` gains the same three optional fields with the same constraints
- [ ] `model_name: Optional[str] = Field(None, max_length=200)` added to `UpdateLLMLibraryRequest` (currently missing — the update route cannot change deployment name)
- [ ] `_UPDATE_ALLOWLIST` updated to include `"endpoint_url"`, `"api_version"`, `"model_name"` (NOT `"api_key"` — key is handled separately via encryption path, never directly in the allowlist)
- [ ] Pydantic validators reject `endpoint_url` values longer than 500 chars with a 422 response
- [ ] `api_key` field is documented with `description="Plaintext API key — encrypted before storage, never returned"` in the Field definition
- [ ] `CreateLLMLibraryRequest.model_config` retains `protected_namespaces: ()` and `arbitrary_types_allowed: True`
- [ ] No change to `validate_provider()` method (still enforces `_VALID_PROVIDERS`)

## Implementation Notes

File to edit: `src/backend/app/modules/platform/llm_library/routes.py`

For `CreateLLMLibraryRequest`, add after `pricing_per_1k_tokens_out`:

```python
endpoint_url: Optional[str] = Field(None, max_length=500, description="Required for azure_openai")
api_key: Optional[str] = Field(None, description="Plaintext — encrypted before storage, never returned")
api_version: Optional[str] = Field(None, max_length=50, description="Required for azure_openai, e.g. 2024-12-01-preview")
```

For `UpdateLLMLibraryRequest`, add the same three fields, plus:

```python
model_name: Optional[str] = Field(None, max_length=200)
```

Update `_UPDATE_ALLOWLIST`:

```python
_UPDATE_ALLOWLIST = frozenset({
    "display_name",
    "model_name",
    "plan_tier",
    "is_recommended",
    "best_practices_md",
    "pricing_per_1k_tokens_in",
    "pricing_per_1k_tokens_out",
    "endpoint_url",
    "api_version",
    # api_key intentionally excluded — handled via explicit encryption path in update handler
})
```

Note: `api_key` is NOT in the allowlist because it requires the special encrypt-then-store treatment. The update handler (LLM-005) checks for `api_key` separately before the allowlist loop.

## Dependencies

- Depends on: LLM-001 (migration must exist so the columns can be referenced)
- Blocks: LLM-005

## Test Requirements

- [ ] Unit test: POST with `api_key` longer than reasonable length still stored (no length limit on api_key — keys vary by provider)
- [ ] Unit test: POST with `endpoint_url` exceeding 500 chars returns 422
- [ ] Unit test: PATCH with `model_name` in payload updates the deployment name
- [ ] Unit test: PATCH with `api_key` in payload does NOT appear in the serialized update dict going to the allowlist handler (verified via the explicit key path instead)
