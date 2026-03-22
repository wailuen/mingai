# TODO-LLM-QG-5: Security + Code Review Agents — Validate Round-2 Fixes

## Status

COMPLETED — 2026-03-22

## Summary

Security review agent and intermediate reviewer validated all round-2 fixes applied to the BYOLLM / LLM Library credential management work. All 7 findings (2 CRITICAL, 2 HIGH, 2 MEDIUM, 1 from IPv6 coverage) were confirmed resolved. 3246 unit tests pass. TypeScript compiles cleanly (0 errors).

## Acceptance Criteria

- [x] Security agent sign-off: no remaining CRITICAL or HIGH findings
- [x] Intermediate reviewer sign-off: no outstanding code review findings
- [x] All unit tests pass: 3246 passing, 0 failures
- [x] TypeScript compiles cleanly: 0 errors

## Findings Resolved

### CRITICAL

1. **api_key min_length enforcement** — `CreateLibraryEntryRequest`, `RotateKeyRequest`, and `TestConnectionRequest` all now enforce `min_length=8` on the `api_key` field (previously `min_length=1`). `_encrypt_api_key()` now returns `"****"` for any key shorter than 8 characters as a fail-safe.

2. **LEFT JOIN duplicate rows (LATERAL deduplication)** — The llm_library query that used `LEFT JOIN` was producing duplicate rows when multiple credential rows existed. Replaced with a `LATERAL` subquery + `LIMIT 1` to guarantee at most one credential row per library entry.

### HIGH

3. **Missing cache invalidation after slot assignment** — `create_library_entry` and `assign_byollm_slot` were not calling `_invalidate_config_cache()` after modifying the DB. Cache invalidation added to both code paths to prevent stale LLM profile resolution.

4. **`_SLOT_COL` promoted to module level** — The slot column name was previously constructed via f-string interpolation inside `assign_byollm_slot`, creating a SQL injection surface. Promoted to a module-level constant `_SLOT_COL` and used consistently throughout the function.

5. **Frontend `showBYOLLM` state drift** — The `showBYOLLM` boolean in `LibraryModeTab.tsx` was not syncing when the server-side `profile.is_byollm` changed (e.g., after a plan upgrade). Added `useEffect([profile.is_byollm])` to synchronise the local state with server-side changes.

### MEDIUM

6. **`aws/bedrock` provider alias missing** — `_FRONTEND_PROVIDER_MAP` in `byollm.py` lacked the `aws/bedrock` → `aws_bedrock` mapping used by the frontend. Added to ensure the provider dropdown resolves correctly.

7. **IPv6 link-local range missing from SSRF denylist** — `fe80::/10` (IPv6 link-local) was absent from the private IP ranges checked by the SSRF validation middleware. Added to close the gap.

## Evidence

- Commits: `fix(llm-library): security hardening from red team round 2` (4264325), `fix(llm-library): security hardening — SSRF protection, model_name invalidation, publish gate atomicity, surfaced test errors` (3bf3312)
- Test suite: 3246 unit tests passing, 0 failures
- TypeScript: clean build, 0 errors

## Dependencies

- Depends on: LLM-003A, LLM-007, LLM-008, LLM-009
- Part of: LLM Profile Redesign (TODO-27–38) quality gate sequence
