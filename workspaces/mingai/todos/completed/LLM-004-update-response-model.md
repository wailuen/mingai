# TODO-LLM-004: Update LLMLibraryEntry Response Model

## Status

Active

## Summary

Add five new fields to the `LLMLibraryEntry` Pydantic response model: `endpoint_url`, `api_version`, `key_present`, `api_key_last4`, and `last_test_passed_at`. The `api_key_encrypted` BYTEA column MUST NEVER appear in this model or any API response.

## Context

The current `LLMLibraryEntry` response model has no credential fields. After LLM-001 adds the DB columns and LLM-006 updates `_row_to_entry` to read them, the response model must be updated to expose safe credential metadata. Specifically: `key_present` (computed bool indicating whether a key is stored), `api_key_last4` (last 4 chars for UI masking), and `last_test_passed_at` (ISO timestamp for publish gate UI feedback). The raw encrypted bytes are a security invariant — they must not appear in any serialized response.

## Acceptance Criteria

- [ ] `LLMLibraryEntry` gains `endpoint_url: Optional[str] = None`
- [ ] `LLMLibraryEntry` gains `api_version: Optional[str] = None`
- [ ] `LLMLibraryEntry` gains `key_present: bool = False`
- [ ] `LLMLibraryEntry` gains `api_key_last4: Optional[str] = None`
- [ ] `LLMLibraryEntry` gains `last_test_passed_at: Optional[str] = None` (ISO 8601 string, same pattern as `created_at`)
- [ ] `api_key_encrypted` does NOT appear anywhere in `LLMLibraryEntry` — not as a field, not aliased, not in a computed property
- [ ] All five new fields have defaults so existing callers that construct `LLMLibraryEntry` manually (e.g. in tests) do not break
- [ ] `GET /platform/llm-library` list response and `GET /platform/llm-library/{id}` detail response both include the five new fields
- [ ] `key_present` is `True` when `api_key_encrypted` is not null in the DB row; `False` otherwise
- [ ] `last_test_passed_at` is an ISO 8601 string when set, `None` when the column is null
- [ ] The `LibraryOption` type in `useLLMLibrary.ts` (tenant-facing) does NOT need these credential fields — it serves a different audience

## Implementation Notes

File to edit: `src/backend/app/modules/platform/llm_library/routes.py`

Update `LLMLibraryEntry`:

```python
class LLMLibraryEntry(BaseModel):
    id: str
    provider: str
    model_name: str
    display_name: str
    plan_tier: str
    is_recommended: bool
    status: str
    best_practices_md: Optional[str] = None
    pricing_per_1k_tokens_in: Optional[float] = None
    pricing_per_1k_tokens_out: Optional[float] = None
    endpoint_url: Optional[str] = None
    api_version: Optional[str] = None
    key_present: bool = False
    api_key_last4: Optional[str] = None
    last_test_passed_at: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = {"protected_namespaces": ()}
```

The `key_present` and `last_test_passed_at` fields are computed in `_row_to_entry` (see LLM-006), not derived here. The response model is a pure data container.

Security note: Pydantic's `model_dump()` and JSON serialization will expose `key_present` and `api_key_last4` but never `api_key_encrypted` since that field is not declared in the model.

## Dependencies

- Depends on: LLM-001 (columns must exist), LLM-006 (row-to-entry must populate new fields)
- Blocks: LLM-010 (frontend types must match)

## Test Requirements

- [ ] Unit test: `LLMLibraryEntry.model_validate(...)` with `api_key_encrypted` in the source dict does NOT include that field in the serialized output
- [ ] Unit test: `key_present=True` when row has api_key data, `False` when null
- [ ] Unit test: `last_test_passed_at` serializes as ISO string when not None
- [ ] Verify GET response body via integration test does not contain `api_key_encrypted` key at any nesting level
