# LLM Library Redesign — Gap Analysis & Requirements

**Date**: 2026-03-21
**Trigger**: Platform admin identified that the LLM Library was built as a metadata catalog with no endpoint URL, no API key, and no connectivity test. The feature is non-functional as a credential store.

---

## 1. The Fundamental Design Error

The LLM Library was designed as a **naming + pricing catalog** when it should be a **deployment endpoint registry**.

### What Was Built (Wrong)

Each `llm_library` row stores:

- `provider` (string label)
- `model_name` (deployment name — no endpoint to reach it)
- `display_name`, `plan_tier`, `status`, `pricing`

There is no URL, no API key, no API version. The test endpoint (`POST /{id}/test`) calls `AzureOpenAIProvider()` which reads from `AZURE_PLATFORM_OPENAI_*` env vars — it does NOT use the stored entry's credentials. Every test fires against the same global endpoint regardless of which library entry is being tested.

The frontend `LibraryForm.tsx` further confuses the domain by embedding "Model Slots" (intent_model, primary_model, vision_model, embedding_model) inside the Library entry form. These are **Profile** concepts. The backend ignores them entirely — the form sends data the API silently discards.

### What Should Be Built (Correct)

```
LLM Library Entry = one fully-specified connection to one LLM deployment
  - endpoint_url (required for Azure OpenAI)
  - api_key (encrypted at rest, never returned)
  - api_version (required for Azure OpenAI)
  - deployment_name / model_name
  - pricing, plan_tier, display_name (catalog metadata)
  - last_test_passed_at (test gate for publish)

LLM Profile = named mapping of 6 role slots → Library entry IDs
  - primary_model → library entry ID
  - intent_model → library entry ID
  - vision_model → library entry ID
  - doc_embedding → library entry ID
  - kb_embedding → library entry ID
  - auxiliary → library entry ID
```

---

## 2. Gap Summary

| Dimension                | Current State                              | Required State                                        | Severity |
| ------------------------ | ------------------------------------------ | ----------------------------------------------------- | -------- |
| **Endpoint URL**         | Not in schema                              | `endpoint_url VARCHAR(500) NOT NULL` for azure_openai | CRITICAL |
| **API Key**              | Not stored                                 | Fernet-encrypted BYTEA, never returned in API         | CRITICAL |
| **API Version**          | Not stored                                 | `api_version VARCHAR(50)` for azure_openai            | MAJOR    |
| **Key masking**          | N/A                                        | `api_key_last4 VARCHAR(4)` — show `****...1234` in UI | MAJOR    |
| **Test harness**         | Uses env vars, not entry credentials       | Decrypt entry's key, call entry's endpoint            | CRITICAL |
| **Publish gate**         | Only checks pricing non-null               | Requires: endpoint+key+apiversion set + test passed   | CRITICAL |
| **Model Slots in form**  | Frontend shows slot UI; backend ignores it | Remove slots from Library; slots belong in Profiles   | CRITICAL |
| **Test result recorded** | No record of last test                     | `last_test_passed_at TIMESTAMPTZ` column              | MAJOR    |

---

## 3. Provider Field Matrix

| Field                          |               azure_openai               |     openai_direct     |       anthropic       |
| ------------------------------ | :--------------------------------------: | :-------------------: | :-------------------: |
| `model_name` (deployment name) |                 REQUIRED                 |       REQUIRED        |       REQUIRED        |
| `endpoint_url`                 |               **REQUIRED**               |           —           |           —           |
| `api_key` (encrypted)          |               **REQUIRED**               |     **REQUIRED**      |     **REQUIRED**      |
| `api_version`                  | **REQUIRED** (e.g. `2024-12-01-preview`) |           —           |           —           |
| `api_key_last4`                |               auto-derived               |     auto-derived      |     auto-derived      |
| `pricing_per_1k_tokens_in`     |           required for publish           | required for publish  | required for publish  |
| `pricing_per_1k_tokens_out`    |           required for publish           | required for publish  | required for publish  |
| `last_test_passed_at`          |          auto-set on test pass           | auto-set on test pass | auto-set on test pass |

---

## 4. ADR-001: Credential Storage Approach

### Decision: Direct storage in `llm_library` (Option A)

**Context**: Two options considered:

- **A** — Add `api_key_encrypted BYTEA`, `endpoint_url`, `api_version`, `api_key_last4`, `last_test_passed_at` directly to `llm_library`
- **B** — Add `llm_provider_id UUID REFERENCES llm_providers(id)` to `llm_library`, inherit credentials from the `llm_providers` table

**Decision: Option A** — direct storage.

**Rationale**:

1. **One entry = one self-contained connection.** A library entry IS the fully-specified deployment config. Forcing indirection through `llm_providers` breaks this model.
2. **Different deployments, different contexts.** Two entries for the same Azure account but different deployments might share a key today but diverge tomorrow (different resource groups, regions, keys). Option A handles this natively; Option B forces either duplicate provider rows or a many-to-many.
3. **`llm_providers` serves a different purpose.** It was built for platform-wide provider management (PVDR-001-020 feature) with health checks, default-provider logic, and enabled/disabled lifecycle. Coupling library entries to it entangles two features with different lifecycles.
4. **Fernet helpers are pure utility.** `ProviderService.encrypt_api_key()` / `decrypt_api_key()` can be extracted to `app.core.crypto` and reused by `llm_library` without taking any dependency on the `llm_providers` table.
5. **Migration simplicity.** Adding 5 columns to `llm_library` is one `ALTER TABLE`. An FK approach requires ensuring provider rows exist first and a data migration to populate them.

**Consequence of Option A — key rotation cost**: If the same Azure subscription key is used for 10 entries, rotation requires patching 10 rows. Acceptable: (a) keys are short strings, encrypted overhead is ~200 bytes/key; (b) a future bulk-rotate UI action can address this. Not a Day 1 concern.

---

## 5. Schema Changes Required (New Migration)

```sql
-- vNNN_llm_library_credentials.py
ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS endpoint_url     VARCHAR(500);
ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS api_key_encrypted BYTEA;
ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS api_key_last4     VARCHAR(4);
ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS api_version       VARCHAR(50);
ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS last_test_passed_at TIMESTAMPTZ;
```

**Migration notes:**

- All new columns are nullable — existing 3 rows are unaffected, retain their current status.
- Publish gate applies only on future Draft → Published transitions; existing Published rows are not touched.
- No data migration needed.

---

## 6. Backend Changes Required

### `app/modules/platform/llm_library/routes.py`

**`CreateLLMLibraryRequest` — add fields:**

```python
endpoint_url: Optional[str] = Field(None, max_length=500)
api_key: Optional[str] = None   # plaintext, encrypted before storage, NOT stored as-is
api_version: Optional[str] = Field(None, max_length=50)
```

**`UpdateLLMLibraryRequest` — add fields:**

```python
endpoint_url: Optional[str] = Field(None, max_length=500)
api_key: Optional[str] = None
api_version: Optional[str] = Field(None, max_length=50)
```

**`LLMLibraryEntry` (response model) — add, NEVER include api_key:**

```python
endpoint_url: Optional[str] = None
api_version: Optional[str] = None
key_present: bool = False
api_key_last4: Optional[str] = None
last_test_passed_at: Optional[str] = None
```

**`_UPDATE_ALLOWLIST` — add:**

```python
"endpoint_url", "api_key_encrypted", "api_key_last4", "api_version"
```

Note: `api_key` is accepted in PATCH but stored as encrypted BYTEA — the plaintext never persists.

**Publish gate — per-provider validation:**

```python
# azure_openai requires endpoint + key + api_version
if entry.provider == "azure_openai":
    if not entry.endpoint_url or not entry.key_present or not entry.api_version:
        raise HTTPException(422, "Azure OpenAI entries require endpoint_url, api_key, and api_version")
# all providers require key
if not entry.key_present:
    raise HTTPException(422, "api_key must be set before publishing")
# test must have passed
if entry.last_test_passed_at is None:
    raise HTTPException(422, "Entry must pass a connectivity test before publishing")
```

**Test harness rewrite (`_run_single_test_prompt`):**

```python
# Before (BROKEN):
adapter = AzureOpenAIProvider()  # reads env vars

# After (CORRECT):
decrypted_key = decrypt_api_key(entry.api_key_encrypted)
try:
    if entry.provider == "azure_openai":
        client = AsyncAzureOpenAI(
            azure_endpoint=entry.endpoint_url,
            api_key=decrypted_key,
            api_version=entry.api_version,
        )
        response = await client.chat.completions.create(
            model=entry.model_name,
            messages=[{"role": "user", "content": prompt}]
        )
finally:
    decrypted_key = ""   # always clear
```

On success: `UPDATE llm_library SET last_test_passed_at = NOW() WHERE id = :id`

### Extract Fernet helpers to `app/core/crypto.py`

Move `encrypt_api_key()` and `decrypt_api_key()` from `ProviderService` to a shared module callable from both `llm_providers` routes and `llm_library` routes.

---

## 7. Frontend Changes Required

### Remove from `LibraryForm.tsx`

- `SLOT_KEYS` constant (intent_model, primary_model, vision_model, embedding_model)
- `SlotFormState` interface
- `FormState.slots` field
- The entire "Model Slots" section render block
- All slot-related state management

### Add to `LibraryForm.tsx` (conditional on provider type)

**For `azure_openai`:**

```
Endpoint URL     [text input] e.g. https://ai-xxx.cognitiveservices.azure.com/
API Key          [password input] ● When key exists: show "****...{last4}"
API Version      [text input] default: 2024-12-01-preview
```

**For `openai_direct` / `anthropic`:**

```
API Key          [password input] ● When key exists: show "****...{last4}"
```

### Test Button behavior

- Active from the moment all required fields are filled (even before save)
- Click → calls `POST /{id}/test` (entry must exist — so Test runs on saved Draft, not on unsaved form)
- Shows per-prompt results: response snippet, latency, token count, estimated cost
- On all pass: shows green checkmark + "Entry is ready to publish"
- On any fail: shows error message in plain language

### Update `useLLMLibrary.ts`

- Remove `ModelSlotKey`, `ModelSlot`, slot-related types
- Add `endpoint_url`, `api_version`, `key_present`, `api_key_last4`, `last_test_passed_at` to `LLMLibraryEntry`
- Add `endpoint_url`, `api_key`, `api_version` to `CreateLLMLibraryPayload` and `UpdateLLMLibraryPayload`

---

## 8. Test Flow Design

### Pre-save validation

- Required for all providers: `model_name`, `display_name`, `plan_tier`, `api_key`
- Required for azure_openai: + `endpoint_url`, `api_version`

### Test-before-publish flow

1. Fill form → Save → entry created as Draft
2. Click "Test" → POST /{id}/test
3. Backend: decrypt key → construct provider client → run 3 prompts in parallel → record `last_test_passed_at`
4. UI shows results per prompt: latency, tokens, estimated cost, response preview
5. If all pass: "Publish" button becomes enabled
6. If any fail: error shown in plain language ("Deployment 'aihub2-main' not found — check the deployment name in Azure")

### Publish gate (enforced server-side)

- `model_name` set ✓
- `provider` valid ✓
- `api_key_encrypted` not null ✓
- `pricing_per_1k_tokens_in` + `_out` not null ✓
- `last_test_passed_at` not null ✓
- `endpoint_url` not null (azure_openai only) ✓
- `api_version` not null (azure_openai only) ✓

---

## 9. Security Invariants

1. `api_key_encrypted` BYTEA — **never returned in any API response**
2. `api_key_last4 VARCHAR(4)` — the only key data visible in responses
3. Fernet encryption uses same key as `llm_providers` (derived from `JWT_SECRET_KEY`)
4. Decrypted key cleared (`= ""`) in `finally` block immediately after client construction
5. Test calls log `[REDACTED]` for any key-adjacent values in structlog output
6. Audit log records who ran the test, which entry, pass/fail, timestamp — not the key or response content

---

## 10. Risk Register

| ID  | Risk                                                        | Likelihood      | Impact   | Mitigation                                                              |
| --- | ----------------------------------------------------------- | --------------- | -------- | ----------------------------------------------------------------------- |
| R1  | Test fires against env vars, admin publishes broken entries | **Certain now** | Critical | Fix test to use entry credentials                                       |
| R2  | Frontend sends slot data that backend discards silently     | **Certain now** | Major    | Remove slots from LibraryForm                                           |
| R3  | Admin publishes entry with no URL/key/test                  | High            | Critical | Add publish gate                                                        |
| R4  | 3 existing DB rows lack credentials, remain Published       | Medium          | Major    | Leave as-is; force re-test gate only on new Draft→Published transitions |
| R5  | JWT_SECRET_KEY rotation invalidates all Fernet keys         | Low             | Critical | Document rotation; implement re-encryption script                       |

---

## 11. Existing Rows (from Playwright session)

3 entries created during previous testing session:

- `aihub2-main` (Primary Chat, Published)
- `intent5` (Intent Detection, Published)
- `text-embedding-3-large` (Document Embedding, Published)

These rows have no credentials. They will remain in the DB after migration. The platform admin should:

1. Edit each entry to add endpoint_url, api_key, api_version
2. Run test on each
3. Note: since they are already Published (not Draft), the publish gate does not retroactively block them — but the test endpoint will now actually verify connectivity

---

## 12. Implementation Plan

### Phase 1 — Backend + DB (2-3 days)

1. Extract Fernet helpers → `app/core/crypto.py`
2. New Alembic migration: add 5 columns to `llm_library`
3. Update `routes.py`: create/update/get/list with new fields
4. Rewrite publish gate with provider-specific required field checks
5. Rewrite test harness to use entry credentials
6. Unit tests for credential storage and test flow

### Phase 2 — Frontend (1-2 days)

1. Remove Model Slots section from `LibraryForm.tsx`
2. Add conditional credential fields (endpoint_url, api_key, api_version)
3. Show `api_key_last4` masking for existing entries
4. Update `useLLMLibrary.ts` types
5. Test button shows per-prompt results

### Phase 3 — E2E validation (1 day)

1. Full create → test → publish flow via Playwright
2. Verify existing 3 rows unaffected
3. Verify API key never appears in any API response
4. Verify test harness uses entry credentials (not env vars)
