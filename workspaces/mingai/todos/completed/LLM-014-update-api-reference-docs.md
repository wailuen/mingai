# TODO-LLM-014: Update API Reference and Architecture Docs

## Status

Active

## Summary

Update `docs/00-authority/01-api-reference.md` to document the new credential fields in the LLM Library endpoints, and update `docs/00-authority/02-architecture.md` to reflect the corrected schema and the architectural decision (ADR-001) that credentials live directly in `llm_library`.

## Context

The authority docs describe the LLM Library as a "naming + pricing catalog". After the redesign, they must describe it as a "deployment endpoint registry". Without updating these docs, future implementers will recreate the same design mistake. The docs also serve as the contract for the frontend — keeping them accurate prevents API drift.

## Acceptance Criteria

### 01-api-reference.md changes

- [ ] `POST /platform/llm-library` request body documented with `endpoint_url`, `api_key`, `api_version` fields including which are required per provider
- [ ] `PATCH /platform/llm-library/{id}` request body updated with same new fields plus `model_name`
- [ ] `LLMLibraryEntry` response object documented with new fields: `endpoint_url`, `api_version`, `key_present`, `api_key_last4`, `last_test_passed_at`
- [ ] Security note added: "api_key_encrypted is never returned in any response"
- [ ] `POST /platform/llm-library/{id}/test` response updated to match actual `ProfileTestResponse` shape (`tests: TestPromptResult[]`)
- [ ] `POST /platform/llm-library/{id}/publish` documented with new 422 conditions (no key, no test, missing azure fields)
- [ ] Provider field matrix table added (from analysis section 3) showing which fields are required per provider

### 02-architecture.md changes

- [ ] LLM Library section updated: concept description changed from "naming catalog" to "deployment endpoint registry"
- [ ] ADR-001 summary added: credential storage approach (Option A — direct columns vs Option B — FK to llm_providers), decision and rationale
- [ ] Schema section updated to show all 17 columns of `llm_library` after migration
- [ ] Note added: Fernet encryption via `app.core.crypto` derived from `JWT_SECRET_KEY`, same key derivation as HAR and llm_providers

## Implementation Notes

Files to locate first (check if they exist at these paths):

- `src/backend/docs/00-authority/01-api-reference.md`
- `src/backend/docs/00-authority/02-architecture.md`
- Or: `docs/00-authority/01-api-reference.md` (project root)

Run `find . -name "01-api-reference.md" -path "*/00-authority/*"` to confirm exact paths before editing.

If the docs directory is at a different path, update the file paths accordingly. Do NOT create new doc files — update the existing ones.

For the provider field matrix table, use the format from the analysis (`53-llm-library-redesign-analysis.md` section 3):
| Field | azure_openai | openai_direct | anthropic |
| --- | --- | --- | --- |
| model_name | REQUIRED | REQUIRED | REQUIRED |
| endpoint_url | REQUIRED | — | — |
| api_key | REQUIRED | REQUIRED | REQUIRED |
| api_version | REQUIRED | — | — |

## Dependencies

- Depends on: LLM-004 (response model finalised — docs must match actual implementation)
- Blocks: nothing (documentation)

## Test Requirements

- [ ] Verify all new field names in docs match exactly the field names returned by `GET /platform/llm-library/{id}` (no typos)
- [ ] Verify 422 error messages in docs match the exact `detail` strings in LLM-007 implementation
