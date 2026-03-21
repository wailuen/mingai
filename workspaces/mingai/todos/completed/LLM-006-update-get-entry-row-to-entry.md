# TODO-LLM-006: Update \_get_entry and \_row_to_entry to Read New Columns

## Status

Active

## Summary

Update the SQL SELECT in `_get_entry` to fetch the five new columns, and update `_row_to_entry` to map them into the `LLMLibraryEntry` response model. Compute `key_present` from `api_key_encrypted IS NOT NULL`. The encrypted bytes are read from the DB but never passed to the response model — only the derived bool and the stored `api_key_last4` string are included in the response.

## Context

`_get_entry` currently SELECTs 12 columns and `_row_to_entry` maps them by positional index. After LLM-001 adds the new columns, both functions must be updated to read them. This is also where `key_present` is computed — the response model receives a bool, never the raw bytes. The list endpoint's inline SQL also needs updating.

## Acceptance Criteria

- [ ] `_get_entry` SELECT statement extended to fetch `endpoint_url`, `api_key_encrypted`, `api_key_last4`, `api_version`, `last_test_passed_at` (5 new columns, positional indices 12-16)
- [ ] Define \_SELECT_COLUMNS constant listing all safe columns (never include api_key_encrypted)
- [ ] `_row_to_entry` maps new columns: `endpoint_url=row[12]`, `api_key_last4=row[14]`, `api_version=row[15]`, `last_test_passed_at=row[16].isoformat() if row[16] else None`
- [ ] `key_present` computed as `bool(row[13] is not None)` — True when `api_key_encrypted` column is not null
- [ ] `api_key_encrypted` bytes (row[13]) are NOT passed to `LLMLibraryEntry` — they are only used to compute `key_present` and then discarded
- [ ] List endpoint SELECT in `list_llm_library_entries` similarly extended to include the same 5 columns, so the list view also shows credential metadata
- [ ] Row index mapping is correct — confirm no off-by-one errors by counting existing columns (currently 12: id=0 through updated_at=11)
- [ ] `_row_to_entry` handles `None` for all new columns gracefully (existing rows have no values)

## Implementation Notes

File to edit: `src/backend/app/modules/platform/llm_library/routes.py`

Updated SELECT in `_get_entry`:

```python
"SELECT id, provider, model_name, display_name, plan_tier, "
"is_recommended, status, best_practices_md, "
"pricing_per_1k_tokens_in, pricing_per_1k_tokens_out, "
"created_at, updated_at, "
"endpoint_url, api_key_encrypted, api_key_last4, api_version, last_test_passed_at "
"FROM llm_library WHERE id = :id"
```

Column indices after update:

- 0: id, 1: provider, 2: model_name, 3: display_name, 4: plan_tier
- 5: is_recommended, 6: status, 7: best_practices_md
- 8: pricing_per_1k_tokens_in, 9: pricing_per_1k_tokens_out
- 10: created_at, 11: updated_at
- 12: endpoint_url, 13: api_key_encrypted (BYTEA), 14: api_key_last4
- 15: api_version, 16: last_test_passed_at

Updated `_row_to_entry`:

```python
def _row_to_entry(row) -> LLMLibraryEntry:
    return LLMLibraryEntry(
        id=str(row[0]),
        provider=row[1],
        model_name=row[2],
        display_name=row[3],
        plan_tier=row[4],
        is_recommended=row[5],
        status=row[6],
        best_practices_md=row[7],
        pricing_per_1k_tokens_in=float(row[8]) if row[8] is not None else None,
        pricing_per_1k_tokens_out=float(row[9]) if row[9] is not None else None,
        created_at=row[10].isoformat() if row[10] else "",
        updated_at=row[11].isoformat() if row[11] else "",
        endpoint_url=row[12],
        key_present=bool(row[13] is not None),  # row[13] = api_key_encrypted bytes
        api_key_last4=row[14],
        api_version=row[15],
        last_test_passed_at=row[16].isoformat() if row[16] else None,
    )
```

Also update the list endpoint's two SELECT statements (status-filtered and unfiltered) to include the same 5 new columns.

Define module-level \_SELECT_COLUMNS = 'id, provider, model_name, display_name, plan_tier, is_recommended, status, best_practices_md, pricing_per_1k_tokens_in, pricing_per_1k_tokens_out, endpoint_url, api_version, api_key_last4, key_present_flag, last_test_passed_at, created_at, updated_at' — use in all SELECT queries. api_key_encrypted is NEVER in this list. See ProviderService.\_SELECT_SAFE pattern. Note: key_present is derived as `(api_key_encrypted IS NOT NULL) AS key_present` in the SELECT — never fetch the encrypted bytes.

Note: the `test_llm_library_profile` endpoint calls `_get_entry` to get the entry, but needs `api_key_encrypted` for decryption (LLM-008). Because `_row_to_entry` does not expose it, the test handler needs a separate raw query to fetch `api_key_encrypted`. See LLM-008 for details.

## Dependencies

- Depends on: LLM-001 (columns), LLM-004 (response model fields exist)
- Blocks: LLM-007, LLM-008

## Test Requirements

- [ ] Unit test: `_row_to_entry` with `api_key_encrypted=None` → `key_present=False`
- [ ] Unit test: `_row_to_entry` with `api_key_encrypted=b"some_bytes"` → `key_present=True`
- [ ] Unit test: `_row_to_entry` with `last_test_passed_at=datetime(...)` → ISO string in response
- [ ] Integration test: GET /platform/llm-library/{id} response body includes `endpoint_url`, `key_present`, `api_key_last4`, `api_version`, `last_test_passed_at` fields
- [ ] Integration test: GET /platform/llm-library list response includes same fields per entry
