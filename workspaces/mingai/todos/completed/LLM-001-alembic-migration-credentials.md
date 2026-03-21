# TODO-LLM-001: Alembic Migration — Add Credential Columns to llm_library

## Status

Active

## Summary

Create Alembic migration `v049_llm_library_credentials.py` that adds five new columns to the `llm_library` table: `endpoint_url`, `api_key_encrypted`, `api_key_last4`, `api_version`, and `last_test_passed_at`. All columns are nullable so existing rows are unaffected.

## Context

The current `llm_library` schema (v009) contains no endpoint URL, no API key, and no test result timestamp. This makes every stored entry non-functional as a real deployment connection. Without these columns, the test harness fires against environment variables rather than entry-specific credentials, and the publish gate cannot enforce connectivity. This migration is the prerequisite for every other LLM redesign todo.

## Acceptance Criteria

- [ ] Migration file `v049_llm_library_credentials.py` exists at `src/backend/alembic/versions/`
- [ ] `down_revision = "048"` (or the actual latest revision — confirm with `alembic current` before writing)
- [ ] `endpoint_url VARCHAR(500)` — nullable, no default
- [ ] `api_key_encrypted BYTEA` — nullable, no default; stores Fernet ciphertext
- [ ] `api_key_last4 VARCHAR(4)` — nullable; last 4 chars of plaintext key for UI masking
- [ ] `api_version VARCHAR(50)` — nullable; e.g. `2024-12-01-preview`
- [ ] `last_test_passed_at TIMESTAMPTZ` — nullable; set by test harness on success
- [ ] All columns added with `IF NOT EXISTS` guard in the SQL to make the migration re-runnable in dev
- [ ] `downgrade()` drops each column with `IF EXISTS` guard
- [ ] `alembic upgrade head` completes without error against a fresh local DB
- [ ] `alembic downgrade -1` restores original table without error
- [ ] Existing 3 rows in `llm_library` (aihub2-main, intent5, text-embedding-3-large) retain all current field values after upgrade

## Implementation Notes

Migration file naming: follow the existing pattern — `v049_llm_library_credentials.py`. Check `alembic/versions/` for the current latest revision number before writing to confirm `v049` is correct (the last seen was `v048_tool_catalog_rls_degraded.py`).

SQL for upgrade:

```sql
ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS endpoint_url     VARCHAR(500);
ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS api_key_encrypted BYTEA;
ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS api_key_last4     VARCHAR(4);
ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS api_version       VARCHAR(50);
ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS last_test_passed_at TIMESTAMPTZ;
```

SQL for downgrade:

```sql
ALTER TABLE llm_library DROP COLUMN IF EXISTS last_test_passed_at;
ALTER TABLE llm_library DROP COLUMN IF EXISTS api_version;
ALTER TABLE llm_library DROP COLUMN IF EXISTS api_key_last4;
ALTER TABLE llm_library DROP COLUMN IF EXISTS api_key_encrypted;
ALTER TABLE llm_library DROP COLUMN IF EXISTS endpoint_url;
```

Use `op.execute()` for each statement as done in existing migration files. Do NOT use `op.add_column()` — the existing codebase pattern uses raw SQL via `op.execute()` consistently.

No RLS policy changes needed — existing `llm_library_platform_admin` and `llm_library_tenant_read` policies remain correct. The new columns follow the same access pattern as existing columns.

## Dependencies

- Depends on: nothing (first in the chain)
- Blocks: LLM-003, LLM-004, LLM-005, LLM-006, LLM-007, LLM-008

## Test Requirements

- Manual: run `alembic upgrade head` and `alembic downgrade -1` against local DB
- Verify `\d llm_library` in psql shows all 5 new columns after upgrade
- Verify existing row data (pricing, status, model_name) unchanged after upgrade
- No automated test file required for pure DDL migrations (consistent with existing migration tests)
