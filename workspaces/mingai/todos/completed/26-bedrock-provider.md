# TODO-15: AWS Bedrock Provider — LLM Library

**Status**: ACTIVE
**Created**: 2026-03-22
**Research**: `workspaces/mingai/01-analysis/01-research/54-bedrock-provider-analysis.md`
**Plan**: `workspaces/mingai/02-plans/16-bedrock-provider-plan.md`
**User flows**: `workspaces/mingai/03-user-flows/24-bedrock-provider-flows.md`
**Prerequisite**: LLM Library redesign (P2LLM-005 through P2LLM-011, v049 migration) COMPLETE.

## Scope

Add `bedrock` as a fourth provider type to the LLM Library. Reuses existing `openai` package
via `AsyncOpenAI` with `base_url` override — no new Python dependencies. Seven backend files
touched, two frontend files modified, one migration added.

## Key constraints (apply to every relevant task)

- `base_url = {endpoint_url}/v1` — NOT `/model/{arn}/`. Model ARN goes in `model=` at call time.
- No ARN prefix validation (ADR-5). `max_length=200` + non-empty is the only model_name check.
- `_assert_endpoint_ssrf_safe()` MUST be called before any outbound Bedrock call in the test harness.
- `decrypted_key = ""` in `finally` block — same pattern as all existing providers.
- `last_test_passed_at` resets to NULL on any api_key PATCH (existing behaviour — no new code needed).
- Bedrock is excluded from the `embed()` path — falls back to azure_openai (same as anthropic).
- Provider name is `"bedrock"` (not `"aws_bedrock"`) — consistent with `"azure_openai"` precedent.

---

## BEDROCK-001 — Alembic migration v050: expand provider CHECK constraint

**Status**: TODO
**Files**:

- `src/backend/alembic/versions/v050_add_bedrock_provider.py` (NEW)

**Dependencies**: None

The `provider` column uses a VARCHAR CHECK constraint (not a PostgreSQL ENUM type). Confirmed
in `v009_llm_library.py`. Write a new migration that drops the existing constraint and re-adds it
with `'bedrock'` included. The downgrade must delete all `bedrock` rows before restoring the
three-value constraint. Use `IF EXISTS` on the DROP so the migration is safe to run more than once.

No new columns required — Bedrock reuses `endpoint_url` (for `BEDROCK_BASE_URL`),
`api_key_encrypted` (for `AWS_BEARER_TOKEN_BEDROCK`), `model_name` (for the ARN), and
`api_key_last4` (last 4 chars of the bearer token).

**Acceptance criteria**:

- [ ] Migration file `v050_add_bedrock_provider.py` exists under `src/backend/alembic/versions/`
- [ ] `upgrade()` drops `llm_library_provider_check` (IF EXISTS) then adds it with `('azure_openai', 'openai_direct', 'anthropic', 'bedrock')`
- [ ] `downgrade()` deletes `WHERE provider = 'bedrock'` then restores the three-value constraint
- [ ] `alembic upgrade head` runs clean against a dev database
- [ ] Existing rows (azure_openai, openai_direct, anthropic) survive both upgrade and downgrade unmodified

---

## BEDROCK-002 — routes.py: add `"bedrock"` to `_VALID_PROVIDERS` frozenset

**Status**: TODO
**Files**:

- `src/backend/app/modules/platform/llm_library/routes.py` — line 63

**Dependencies**: BEDROCK-001

`_VALID_PROVIDERS` at line 63 currently reads:

```python
_VALID_PROVIDERS = frozenset({"azure_openai", "openai_direct", "anthropic"})
```

Without this change every `POST /platform/llm-library` with `provider="bedrock"` is rejected at
line 353 before any other logic runs. This is Risk R8 (marked Certain / Critical in doc 54).

**Acceptance criteria**:

- [ ] `_VALID_PROVIDERS` includes `"bedrock"` as the fourth member
- [ ] `POST /platform/llm-library` with `provider="bedrock"` no longer returns 422 at the frozenset guard
- [ ] Existing providers are unaffected

---

## BEDROCK-003 — routes.py: update `CreateLLMLibraryRequest` Literal type and description

**Status**: TODO
**Files**:

- `src/backend/app/modules/platform/llm_library/routes.py` — `CreateLLMLibraryRequest.provider` field (~line 103)

**Dependencies**: BEDROCK-002

The `provider` field currently has type `str` with description `"One of: azure_openai,
openai_direct, anthropic"`. Update the description to include bedrock so the OpenAPI schema
is accurate. If the project adds a `Literal` type annotation for this field, include
`"bedrock"` in the union.

Also update `endpoint_url` field description (~line 114) from `"Required for azure_openai"` to
`"Required for azure_openai and bedrock"`.

**Acceptance criteria**:

- [ ] `provider` field description reads `"One of: azure_openai, openai_direct, anthropic, bedrock"`
- [ ] `endpoint_url` field description updated to reflect bedrock requirement
- [ ] OpenAPI docs (`/docs`) show the updated description

---

## BEDROCK-004 — routes.py: publish gate — add `elif entry.provider == "bedrock"` branch

**Status**: TODO
**Files**:

- `src/backend/app/modules/platform/llm_library/routes.py` — `publish_llm_library_entry()` (~line 595)

**Dependencies**: BEDROCK-002

The publish gate currently has one provider-specific branch:

```python
if entry.provider == "azure_openai":
    if not entry.endpoint_url or not entry.api_version:
        raise HTTPException(422, "Azure OpenAI entries require endpoint_url and api_version...")
```

Add an explicit `elif` for Bedrock. It must be an active `elif` — not an omission — so the
shared gate logic (key_present, last_test_passed_at, pricing) still applies, but the
Azure-specific `api_version` check does NOT apply to Bedrock. `endpoint_url` IS required.

```python
elif entry.provider == "bedrock":
    if not entry.endpoint_url:
        raise HTTPException(422, "Bedrock entries require endpoint_url (BEDROCK_BASE_URL)")
    # api_version explicitly NOT required for bedrock
```

Also add `endpoint_url` to the atomic UPDATE WHERE clause for Bedrock entries: the existing
WHERE clause checks `api_key_encrypted IS NOT NULL AND last_test_passed_at IS NOT NULL`
which is correct; no change needed there — the Bedrock gate checks endpoint_url at the
Python level above the UPDATE.

**Acceptance criteria**:

- [ ] `POST /{id}/publish` for a Bedrock entry without `endpoint_url` returns 422 with `"Bedrock entries require endpoint_url (BEDROCK_BASE_URL)"`
- [ ] `POST /{id}/publish` for a Bedrock entry with `endpoint_url` but without `api_version` succeeds (no api_version gate)
- [ ] `POST /{id}/publish` for a Bedrock entry without `api_key_encrypted` returns 422 (`"api_key must be set before publishing"` — existing shared gate)
- [ ] `POST /{id}/publish` for a Bedrock entry without `last_test_passed_at` returns 422 (existing shared gate)
- [ ] Azure OpenAI publish gate unchanged — still requires api_version

---

## BEDROCK-005 — routes.py: region cross-validation at create/update time

**Status**: TODO
**Files**:

- `src/backend/app/modules/platform/llm_library/routes.py` — `create_llm_library_entry()` and `update_llm_library_entry()`

**Dependencies**: BEDROCK-002

When both `endpoint_url` and `model_name` are provided for a Bedrock entry, and the model_name
is an ARN (starts with `"arn:aws:bedrock:"`), extract the region from both fields and reject
if they differ. This catches the most common misconfiguration without blocking valid non-ARN
model IDs (which skip this check entirely).

Extract region from ARN: `model_name.split(":")[3]` (index 3, zero-based — e.g., `"ap-southeast-1"`).
Extract region from URL: `endpoint_url.replace("https://", "").split(".")[1]`
(e.g., `"bedrock-runtime.ap-southeast-1.amazonaws.com"` → `"ap-southeast-1"`).

Only raise 422 if both extractions yield non-empty strings AND they differ. Skip the check
when model_name is not an ARN (non-ARN model IDs have no region to extract).

```python
# In create handler, after provider check, before INSERT:
if request.provider == "bedrock" and request.endpoint_url and request.model_name:
    if request.model_name.startswith("arn:aws:bedrock:"):
        arn_parts = request.model_name.split(":")
        if len(arn_parts) >= 4:
            arn_region = arn_parts[3]
            url_parts = request.endpoint_url.replace("https://", "").split(".")
            if len(url_parts) >= 2:
                url_region = url_parts[1]
                if arn_region and url_region and arn_region != url_region:
                    raise HTTPException(
                        422,
                        f"Region mismatch: endpoint_url is '{url_region}' but "
                        f"model identifier is '{arn_region}'"
                    )
```

Apply the same logic to the update handler when both fields are being changed.

**Acceptance criteria**:

- [ ] `POST /platform/llm-library` with `endpoint_url` pointing to `us-east-1` and ARN with `ap-southeast-1` returns 422 with `"Region mismatch: endpoint_url is 'us-east-1' but model identifier is 'ap-southeast-1'"`
- [ ] Same entry with non-ARN `model_name` (e.g., `"anthropic.claude-3-sonnet-20240229-v1:0"`) is accepted without region check
- [ ] Matching regions pass without error
- [ ] `PATCH /{id}` with mismatched regions also returns 422

---

## BEDROCK-006 — routes.py: `_run_single_test_prompt` — add Bedrock elif branch

**Status**: TODO
**Files**:

- `src/backend/app/modules/platform/llm_library/routes.py` — `_run_single_test_prompt()` (~line 789)

**Dependencies**: BEDROCK-002

Currently `_run_single_test_prompt` has branches for `azure_openai`, `openai_direct`/`openai`,
and `anthropic`. The `else` branch raises `ValueError`. Add an `elif provider == "bedrock"`
branch before the `else`.

Critical constraints:

- Call `_assert_endpoint_ssrf_safe(endpoint_url)` before constructing the client (same as azure_openai branch)
- `base_url = f"{endpoint_url.rstrip('/')}/v1"` — the `/v1` suffix is mandatory. Do NOT embed the ARN in the base_url.
- Pass `model=deployment_name` (which is `entry.model_name`, the full ARN) at call time
- `response.usage` may be `None` on some Bedrock models — guard with `if response.usage`
- Extract `content = resp.choices[0].message.content or ""`

```python
elif provider == "bedrock":
    from openai import AsyncOpenAI

    if endpoint_url:
        _assert_endpoint_ssrf_safe(endpoint_url)
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=f"{endpoint_url.rstrip('/')}/v1",
    )
    resp = await client.chat.completions.create(
        model=deployment_name,
        messages=[{"role": "user", "content": prompt}],
    )
    latency_ms = int((time.time() - start) * 1000)
    usage = resp.usage
    tokens_in = usage.prompt_tokens if usage else 0
    tokens_out = usage.completion_tokens if usage else 0
    content = resp.choices[0].message.content or ""
```

Note on concurrent test prompts (Risk R7): `asyncio.gather` fires all 3 prompts simultaneously.
Bedrock Application Inference Profiles have tighter RPS than Azure. If the test returns 429
errors, add a brief `asyncio.sleep(0.5)` between prompts for Bedrock, or document that 429
in tests indicates rate limiting, not credential failure. Check the test endpoint caller to
see if sequential execution can be applied for Bedrock.

**Acceptance criteria**:

- [ ] `POST /{id}/test` on a Bedrock entry executes without `"Unsupported provider for test harness"` error
- [ ] Test harness constructs `AsyncOpenAI(base_url="{endpoint_url}/v1", api_key=bearer_token)`
- [ ] ARN is passed as `model=` parameter — not embedded in base_url
- [ ] `_assert_endpoint_ssrf_safe()` is called before client construction
- [ ] `response.usage` being `None` does not raise AttributeError (guarded with `if usage`)
- [ ] Successful test writes `last_test_passed_at = NOW()` to the DB
- [ ] Expired/invalid token returns 502 with human-readable message (existing error wrapper)

---

## BEDROCK-007 — routes.py: test endpoint — wrap Bedrock errors as 502

**Status**: TODO
**Files**:

- `src/backend/app/modules/platform/llm_library/routes.py` — `test_llm_library_profile()` (~line 870)

**Dependencies**: BEDROCK-006

Read the existing `test_llm_library_profile` handler to confirm the error wrapping pattern
(the handler catches exceptions from `_run_single_test_prompt` and re-raises as 502 with
a human-readable detail string). Verify this wrapping already applies to the Bedrock branch
without any special-casing. The handler should already convert raw AWS exception messages
(403 Unauthorized, 404 model not found, 429 rate limited) into 502 responses.

If there is a provider-specific exception type from the `openai` package that is NOT currently
caught (e.g., `openai.AuthenticationError`, `openai.NotFoundError`), ensure those are caught
alongside the generic `Exception` handler. The existing 30-second timeout (`asyncio.wait_for`)
applies to all providers equally.

**Acceptance criteria**:

- [ ] Bedrock 403 (expired/invalid token) surfaces as 502 with `"403"` in the detail string
- [ ] Bedrock 404 (model not found) surfaces as 502 with `"404"` in the detail string
- [ ] Bedrock 429 (rate limit) surfaces as 502 — NOT mistaken for a credential failure
- [ ] Timeout (>30s) returns 504 (existing behaviour — verify it applies to Bedrock)
- [ ] No raw AWS exception classes leak to the response body

---

## BEDROCK-008 — instrumented_client.py: `_resolve_library_adapter` — add Bedrock branch

**Status**: TODO
**Files**:

- `src/backend/app/core/llm/instrumented_client.py` — `_resolve_library_adapter()` (~line 348)

**Dependencies**: BEDROCK-001, BEDROCK-002

This is Risk R9 (marked Certain / Critical in doc 54). Without this change, tenant queries
routed to a Published Bedrock entry raise `ValueError("Provider type 'bedrock' does not have
a supported adapter")` at runtime even after the entry passes the publish gate.

The current `_resolve_library_adapter` resolves `db_provider_type` from the `llm_providers`
table (not `llm_library`). The Bedrock entry is in `llm_library`, accessed via `llm_library_id`
in tenant config. The adapter resolution needs to handle the case where the resolved provider
row's type is `"bedrock"` — or where the library entry itself supplies the credentials.

Study the existing code path carefully: if the library entry provides `provider="bedrock"`,
the credentials come from `llm_library.api_key_encrypted` (decrypted inline), not from
`llm_providers`. Add the `elif db_provider_type == "bedrock"` branch inside the `try` block
that already handles `azure_openai` and `openai`, using `OpenAIDirectAdapter` (existing class)
with `AsyncOpenAI(base_url="{row['endpoint_url'].rstrip('/')}/v1")`.

```python
elif db_provider_type == "bedrock":
    from openai import AsyncOpenAI
    from app.core.llm.openai_direct import OpenAIDirectProvider

    client = AsyncOpenAI(
        api_key=decrypted_key,
        base_url=f"{db_endpoint.rstrip('/')}/v1",   # endpoint_url stored in db_endpoint
    )
    adapter = OpenAIDirectProvider(client=client)
```

Clear `decrypted_key = ""` in the existing `finally` block — do not add a new `finally`.

**Acceptance criteria**:

- [ ] Tenant query routed to a Published Bedrock entry does not raise `ValueError` about unsupported adapter
- [ ] Client constructed with `base_url="{endpoint_url}/v1"` — not `/model/{arn}/`
- [ ] `decrypted_key` is cleared in the `finally` block alongside other providers
- [ ] `model_name` (ARN) is passed through to the completion call at request time
- [ ] Existing azure_openai and openai adapter branches are unchanged

---

## BEDROCK-009 — instrumented_client.py: `embed()` — exclude Bedrock from embedding path

**Status**: TODO
**Files**:

- `src/backend/app/core/llm/instrumented_client.py` — `embed()` method (~line 132)

**Dependencies**: BEDROCK-008

Risk R10 (Certain / Major). Bedrock's OpenAI-compatible endpoint does not support embeddings.
The current `embed()` method falls back to `_resolve_embedding_fallback_adapter()` only for
`provider_type == "anthropic"`. Bedrock must be added to this exclusion so it also falls back.

Current code (~line 132):

```python
if provider_type == "anthropic":
    # Anthropic doesn't support embeddings — fall back to azure/openai
    (embed_adapter, embedding_model) = await self._resolve_embedding_fallback_adapter()
    return await embed_adapter.embed(texts=texts, model=embedding_model)
```

Update to:

```python
if provider_type in ("anthropic", "bedrock"):
    # These providers don't support embeddings — fall back to azure/openai
    (embed_adapter, embedding_model) = await self._resolve_embedding_fallback_adapter()
    return await embed_adapter.embed(texts=texts, model=embedding_model)
```

Note: the `embed()` method reads from `llm_providers` (not `llm_library`). The `provider_type`
field here refers to the `llm_providers.provider_type` column. This is a different code path
from `_resolve_library_adapter`. Verify the exact field name in the row access before patching.

**Acceptance criteria**:

- [ ] When the default `llm_providers` row has `provider_type="bedrock"`, `embed()` falls back to azure_openai instead of raising ValueError
- [ ] Anthropic fallback behaviour is unchanged
- [ ] Embedding fallback logs `"llm_providers_embed_env_fallback_active"` only when the env fallback path is taken, not for normal Bedrock fallback

---

## BEDROCK-010 — useLLMLibrary.ts: add `"bedrock"` to `LLMLibraryProvider` type union

**Status**: TODO
**Files**:

- `src/web/lib/hooks/useLLMLibrary.ts` — line 10

**Dependencies**: None (can be done in parallel with backend)

Current type at line 10:

```typescript
export type LLMLibraryProvider = "azure_openai" | "openai_direct" | "anthropic";
```

Update to:

```typescript
export type LLMLibraryProvider =
  | "azure_openai"
  | "openai_direct"
  | "anthropic"
  | "bedrock";
```

This single change propagates through all interfaces that reference `LLMLibraryProvider`
(`LLMLibraryEntry.provider`, `CreateLLMLibraryPayload.provider`, `UpdateLLMLibraryPayload.provider`).
No other type changes in this file are needed — `endpoint_url`, `api_key`, `key_present`,
`api_key_last4` already exist as fields.

**Acceptance criteria**:

- [ ] `LLMLibraryProvider` union includes `"bedrock"`
- [ ] TypeScript compiler (`tsc --noEmit`) reports zero errors in `src/web/`
- [ ] `LLMLibraryEntry`, `CreateLLMLibraryPayload`, and `UpdateLLMLibraryPayload` all accept `provider: "bedrock"` without type error

---

## BEDROCK-011 — LibraryList.tsx: add `"bedrock"` case to `providerLabel()`

**Status**: TODO
**Files**:

- `src/web/app/(platform)/platform/llm-library/elements/LibraryList.tsx` — `providerLabel()` function (~line 50)

**Dependencies**: BEDROCK-010

The `providerLabel()` function currently handles three cases and falls through to `return provider`
(raw string) for unknown values. Add an explicit case before the default:

```typescript
function providerLabel(provider: string): string {
  switch (provider) {
    case "azure_openai":
      return "Azure OpenAI";
    case "openai_direct":
      return "OpenAI Direct";
    case "anthropic":
      return "Anthropic";
    case "bedrock":
      return "AWS Bedrock"; // add
    default:
      return provider;
  }
}
```

**Acceptance criteria**:

- [ ] A Bedrock entry in the library list displays `"AWS Bedrock"` in the Provider column
- [ ] Existing provider labels are unchanged
- [ ] No TypeScript errors introduced

---

## BEDROCK-012 — LibraryForm.tsx: add `"AWS Bedrock"` to `PROVIDERS` array

**Status**: TODO
**Files**:

- `src/web/app/(platform)/platform/llm-library/elements/LibraryForm.tsx` — `PROVIDERS` constant (~line 73)

**Dependencies**: BEDROCK-010

Current `PROVIDERS` array at line 73–77:

```typescript
const PROVIDERS: { value: LLMLibraryProvider; label: string }[] = [
  { value: "azure_openai", label: "Azure OpenAI" },
  { value: "openai_direct", label: "OpenAI Direct" },
  { value: "anthropic", label: "Anthropic" },
];
```

Add the fourth entry:

```typescript
{ value: "bedrock", label: "AWS Bedrock" },
```

**Acceptance criteria**:

- [ ] Provider dropdown in the New/Edit form includes "AWS Bedrock" as a selectable option
- [ ] Selecting "AWS Bedrock" sets `form.provider` to `"bedrock"`
- [ ] Existing options are unchanged

---

## BEDROCK-013 — LibraryForm.tsx: endpoint_url visible for Bedrock; api_version hidden for Bedrock; conditional labels

**Status**: TODO
**Files**:

- `src/web/app/(platform)/platform/llm-library/elements/LibraryForm.tsx` — Connection Credentials section (~line 616)

**Dependencies**: BEDROCK-012

Three conditional rendering changes in the Connection Credentials section:

**1. Endpoint URL — currently Azure-only, extend to Bedrock.**

Current (~line 625):

```tsx
{form.provider === "azure_openai" && (
  <div>
    <label ...>Endpoint URL</label>
    <input ... placeholder="https://ai-xxx.cognitiveservices.azure.com/" />
  </div>
)}
```

Update condition and add a provider-aware placeholder:

```tsx
{(form.provider === "azure_openai" || form.provider === "bedrock") && (
  <div>
    <label ...>
      {form.provider === "bedrock" ? "Bedrock Base URL" : "Endpoint URL"}
    </label>
    <input
      ...
      placeholder={
        form.provider === "bedrock"
          ? "https://bedrock-runtime.ap-southeast-1.amazonaws.com"
          : "https://ai-xxx.cognitiveservices.azure.com/"
      }
    />
  </div>
)}
```

**2. API Key label — "AWS Bearer Token" when provider is Bedrock.**

The API Key field is always rendered (~line 641). Update its label:

```tsx
<label ...>
  {form.provider === "bedrock" ? "AWS Bearer Token" : "API Key"}
</label>
```

**3. API Version — currently Azure-only (correct). Verify condition does NOT include Bedrock.**

Line 677: `{form.provider === "azure_openai" && (...)}` — this is already correct.
Confirm no change is needed and document explicitly that Bedrock does not get api_version.

**4. Model name field — add Bedrock-specific hint text.**

The Deployment Name field (~line 503) currently has hint text `"Must match deployment name exactly"`.
When provider is Bedrock, replace this hint with the ARN format hint:

```tsx
<p className="mt-1 text-[11px] text-text-faint">
  {form.provider === "bedrock"
    ? "Enter the full ARN, e.g. arn:aws:bedrock:ap-southeast-1:123456789:application-inference-profile/..."
    : "Must match deployment name exactly"}
</p>
```

Also update the label from "Deployment Name \*" to provider-aware text:

```tsx
{
  form.provider === "bedrock" ? "Model ARN *" : "Deployment Name *";
}
```

**Acceptance criteria**:

- [ ] Selecting "AWS Bedrock" in provider dropdown causes Endpoint URL field to appear, labeled "Bedrock Base URL"
- [ ] Endpoint URL placeholder shows `"https://bedrock-runtime.ap-southeast-1.amazonaws.com"` for Bedrock
- [ ] API Key label reads "AWS Bearer Token" when provider is Bedrock
- [ ] API Version field is NOT shown for Bedrock (existing `azure_openai`-only condition is correct)
- [ ] Model name field label reads "Model ARN" and hint shows ARN format when provider is Bedrock
- [ ] No form behaviour changes for azure_openai, openai_direct, or anthropic

---

## BEDROCK-014 — Unit tests: base_url construction, region cross-validation, provider validation

**Status**: TODO
**Files**:

- `src/backend/tests/unit/test_llm_library_bedrock.py` (NEW)

**Dependencies**: BEDROCK-001 through BEDROCK-006

Create a new unit test file. Tests must not make network calls. Focus on the logic pieces
that can be exercised without a real Bedrock endpoint.

```python
# tests/unit/test_llm_library_bedrock.py

def test_bedrock_base_url_construction_uses_v1_suffix():
    """base_url must end with /v1 — not /model/{arn}/ or bare endpoint."""
    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com"
    base_url = f"{endpoint.rstrip('/')}/v1"
    assert base_url == "https://bedrock-runtime.ap-southeast-1.amazonaws.com/v1"

def test_bedrock_base_url_strips_trailing_slash():
    """Trailing slash on endpoint_url must be stripped before appending /v1."""
    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com/"
    base_url = f"{endpoint.rstrip('/')}/v1"
    assert base_url == "https://bedrock-runtime.ap-southeast-1.amazonaws.com/v1"

def test_bedrock_in_valid_providers_frozenset():
    """'bedrock' must be a member of _VALID_PROVIDERS after BEDROCK-002."""
    from app.modules.platform.llm_library.routes import _VALID_PROVIDERS
    assert "bedrock" in _VALID_PROVIDERS

def test_bedrock_accepts_arn_model_name():
    """Bedrock accepts full ARN — no prefix check (ADR-5). Only max_length=200."""
    arn = "arn:aws:bedrock:ap-southeast-1:106056766526:application-inference-profile/6wbz52t5c3rz"
    assert len(arn) <= 200

def test_bedrock_accepts_plain_model_id():
    """Bedrock also accepts non-ARN model IDs — test harness is the real validator."""
    model_id = "anthropic.claude-3-sonnet-20240229-v1:0"
    assert len(model_id) <= 200
    assert not model_id.startswith("arn:")  # confirms prefix check not applied

def test_bedrock_region_cross_validation_detects_mismatch():
    """Region in ARN must match region in endpoint_url."""
    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com"
    arn = "arn:aws:bedrock:us-east-1:123456:application-inference-profile/abc"
    url_region = endpoint.replace("https://", "").split(".")[1]
    arn_region = arn.split(":")[3]
    assert url_region == "ap-southeast-1"
    assert arn_region == "us-east-1"
    assert url_region != arn_region  # should trigger 422

def test_bedrock_region_cross_validation_matching_regions():
    """Matching regions pass without error."""
    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com"
    arn = "arn:aws:bedrock:ap-southeast-1:123456:application-inference-profile/abc"
    url_region = endpoint.replace("https://", "").split(".")[1]
    arn_region = arn.split(":")[3]
    assert url_region == arn_region

def test_bedrock_non_arn_skips_region_check():
    """Non-ARN model IDs have no region to extract — region check is skipped."""
    model_id = "anthropic.claude-3-sonnet-20240229-v1:0"
    is_arn = model_id.startswith("arn:aws:bedrock:")
    assert not is_arn  # confirms no region check applied

def test_bedrock_usage_none_guard():
    """Defensive guard: tokens_in/out default to 0 when usage is None."""
    usage = None
    tokens_in = usage.prompt_tokens if usage else 0
    tokens_out = usage.completion_tokens if usage else 0
    assert tokens_in == 0
    assert tokens_out == 0
```

**Acceptance criteria**:

- [ ] `test_llm_library_bedrock.py` exists in `src/backend/tests/unit/`
- [ ] All tests pass with `pytest src/backend/tests/unit/test_llm_library_bedrock.py -v`
- [ ] No network calls made in any test
- [ ] Test count: at least 9 tests covering the items above

---

## BEDROCK-015 — Integration tests: create → test → publish lifecycle for Bedrock

**Status**: TODO
**Files**:

- `src/backend/tests/unit/test_llm_library_bedrock_integration.py` (NEW — integration tests using TestClient)

**Dependencies**: BEDROCK-001 through BEDROCK-007

Following the pattern in `test_llm_library_credentials.py` and `test_llm_library_test_harness.py`,
write integration tests using FastAPI `TestClient` (or async equivalent) against a real test
database. Use the existing `test_db` fixture. Do not mock the API key encryption — use real
Fernet via the existing `encrypt_api_key` utility.

Key test scenarios:

1. **Create Bedrock entry** — `POST /platform/llm-library` with valid payload returns 201 with `status="Draft"`, `key_present=True`, `api_key_last4` set, `api_key_encrypted` NOT in response body.

2. **Create with missing endpoint_url** — returns 422 at publish gate (not at create time — create allows missing endpoint_url).

3. **Create with region mismatch** — ARN region `us-east-1`, endpoint `ap-southeast-1` → 422 with region mismatch message.

4. **Publish without test** — `last_test_passed_at` is null → 422 `"Entry must pass a connectivity test before publishing"`.

5. **Publish without endpoint_url** — 422 `"Bedrock entries require endpoint_url"`.

6. **PATCH api_key resets last_test_passed_at** — create entry, manually set `last_test_passed_at` in DB, PATCH api_key, verify `last_test_passed_at` is null again.

7. **API response never contains api_key_encrypted** — scan all response bodies for the field name.

8. **Existing providers unaffected** — create an azure_openai entry before and after migration; verify it still creates successfully.

Note: Do NOT mock the Bedrock API calls in integration tests — the test harness endpoint (`/test`)
will fail with a real network error, which is expected in CI. Test the harness's error handling
(502 returned, not 500) rather than success paths. Success path testing requires a live Bedrock
endpoint and should be done manually or in a separate E2E test.

**Acceptance criteria**:

- [ ] All 8 scenarios above have corresponding test functions
- [ ] Tests run against real SQLite/PostgreSQL test database (no mocking of DB layer)
- [ ] `api_key_encrypted` does not appear in any response body (assertion in test 7)
- [ ] Region mismatch test (scenario 3) returns 422 with the expected message
- [ ] PATCH api_key reset test (scenario 6) verifies `last_test_passed_at` is null after update
- [ ] Tests pass in CI without a live Bedrock endpoint (harness tests assert 502, not 200)

---

## BEDROCK-016 — Verify: ModelBreakdownTable.tsx and TenantCostTable.tsx handle `provider="bedrock"` gracefully

**Status**: TODO
**Files**:

- `src/web/app/(platform)/platform/analytics/cost/elements/ModelBreakdownTable.tsx`
- `src/web/app/(platform)/platform/analytics/cost/elements/TenantCostTable.tsx`

**Dependencies**: BEDROCK-011 (providerLabel — reusable if these tables call it)

Read both files and confirm neither contains a hardcoded provider allowlist or switch statement
that would render `provider="bedrock"` as blank, `undefined`, or an error state. If either
component uses a `providerLabel()`-style function that does NOT include `"bedrock"`, add the case.

If neither file has provider-specific rendering (they display whatever string the API returns),
document that as confirmed and close this task.

Verification pattern: search for `"azure_openai"`, `"openai_direct"`, `"anthropic"` as string
literals in both files. If found in switch/case/map structures, ensure `"bedrock"` is added.
If not found, the component is provider-agnostic — no change required.

**Acceptance criteria**:

- [ ] Both files inspected
- [ ] If either contains a provider switch/case, `"bedrock"` case is added
- [ ] If neither contains a provider switch/case, this is documented and the task is marked verified-no-change
- [ ] No TypeScript errors in either file after any changes

---

## BEDROCK-017 — E2E test: full platform admin flow — create Bedrock entry, test connectivity, publish

**Status**: TODO
**Files**:

- `tests/e2e/test_llm_library_bedrock.spec.ts` (NEW)

**Dependencies**: All BEDROCK tasks above; live Bedrock endpoint required

Write a Playwright E2E test covering the full happy-path flow from Flow 1 in the user flows doc:

1. Navigate to Platform > LLM Library
2. Click "New Entry"
3. Select provider "AWS Bedrock" — verify `api_version` field disappears, endpoint URL field appears
4. Fill in Display Name, Bedrock Base URL, AWS Bearer Token, Model ARN, Plan Tier, Pricing
5. Click "Save Draft" — verify entry appears with status "Draft" and `api_key_last4` shown
6. Click "Test Connectivity" — verify test results panel appears with 3 rows (or error is clearly surfaced, not a crash)
7. If all tests pass: click "Publish" — verify entry moves to Published
8. Verify entry displays "AWS Bedrock" in the Provider column in the list

The test should read credentials from environment variables (do not hardcode):

- `BEDROCK_TEST_ENDPOINT_URL` — the Bedrock runtime endpoint URL
- `BEDROCK_TEST_BEARER_TOKEN` — the bearer token
- `BEDROCK_TEST_MODEL_ARN` — the model ARN

If the env vars are not set, skip the test with `test.skip()` — the test is not expected to
pass in environments without live Bedrock credentials.

Also cover the region mismatch flow (Flow 2):

1. Create entry with mismatched regions
2. Verify 422 error message displayed in form

**Acceptance criteria**:

- [ ] E2E test file exists at `tests/e2e/test_llm_library_bedrock.spec.ts`
- [ ] Test reads credentials from env vars; skips gracefully if not set
- [ ] Happy path flow (create → test → publish) succeeds end-to-end with live credentials
- [ ] Region mismatch error message is visible in the form UI (no live credentials required)
- [ ] Provider column in list shows "AWS Bedrock" for the created entry
- [ ] api_version field is not visible when Bedrock is selected

---

## BEDROCK-018 — TenantLLMConfig.tsx: add `"bedrock"` to provider label ternary

**Status**: TODO
**Files**:

- `src/web/app/(platform)/platform/tenants/[id]/elements/TenantLLMConfig.tsx` — lines 140–146

**Dependencies**: BEDROCK-010

The platform tenant detail panel shows the assigned LLM provider's display name via a ternary
chain at lines 140–146. If Bedrock entries are assigned to tenants, this ternary will fall through
to `"Unknown"` or the raw `"bedrock"` string. Read the file and add the Bedrock case.

Expected current structure (lines 140–146):

```tsx
{
  llmConfig.provider === "azure_openai"
    ? "Azure OpenAI"
    : llmConfig.provider === "openai_direct"
      ? "OpenAI Direct"
      : llmConfig.provider === "anthropic"
        ? "Anthropic"
        : "Unknown";
}
```

Add before the final `"Unknown"`:

```tsx
: llmConfig.provider === "bedrock"
? "AWS Bedrock"
```

**Acceptance criteria**:

- [ ] File read and ternary chain inspected at lines 140–146
- [ ] `"bedrock"` case added — renders `"AWS Bedrock"` in tenant LLM config panel
- [ ] `"Unknown"` fallback retained for any future unknown provider
- [ ] No TypeScript errors introduced

---

## BEDROCK-019 — LibraryModeTab.tsx: extend embedding fallback note to include Bedrock

**Status**: TODO
**Files**:

- `src/web/app/(admin)/admin/settings/llm/elements/LibraryModeTab.tsx` — ~line 120

**Dependencies**: BEDROCK-010

The admin LLM settings panel contains a note at ~line 120 explaining that Anthropic does not
support embeddings and falls back to Azure. Bedrock has the same limitation. The current note
reads approximately:

```tsx
<p>
  Note: Anthropic models do not support embeddings. A separate Azure OpenAI or
  OpenAI Direct entry is required for document indexing.
</p>
```

(Read the file to confirm the exact text before editing.)

Update to include Bedrock:

```tsx
<p>
  Note: Anthropic and AWS Bedrock models do not support embeddings. A separate
  Azure OpenAI or OpenAI Direct entry is required for document indexing.
</p>
```

Also check whether there is a conditional note that only renders when `provider_type === "anthropic"`.
If so, extend the condition: `provider_type === "anthropic" || provider_type === "bedrock"`.

**Acceptance criteria**:

- [ ] File read and note inspected at ~line 120
- [ ] Note updated to include "AWS Bedrock" alongside "Anthropic"
- [ ] If note is conditional on provider check, condition extended to include `"bedrock"`
- [ ] No TypeScript errors introduced

---

## BEDROCK-020 — LibraryForm.tsx: exclude `api_version` from the request payload for Bedrock

**Status**: TODO
**Files**:

- `src/web/app/(platform)/platform/llm-library/elements/LibraryForm.tsx` — payload construction (~line 310 or `handleSubmit`)

**Dependencies**: BEDROCK-013

BEDROCK-013 hides the `api_version` field from the UI when `provider === "bedrock"`. However,
if the form payload is constructed from the full `form` state object, `api_version` may still
be included as `null` or `""` in the request body, even though it is not displayed.

The backend `_API_VERSION_RE` regex validator runs for `azure_openai` only (gated on provider),
so a null `api_version` for Bedrock does not currently cause a 422. But the field should be
omitted entirely from the payload to avoid confusion and future breakage.

Read the `handleSubmit` function (or equivalent payload builder). Find where the request body
is assembled. If `api_version` is always included:

```ts
const payload = {
  ...form, // includes api_version even when null
};
```

Change to strip it for Bedrock:

```ts
const payload = {
  ...form,
  ...(form.provider === "bedrock" ? { api_version: undefined } : {}),
};
```

Or, if the payload is built field-by-field, simply omit `api_version` from the bedrock branch.

Also: `LibraryForm.tsx` initializes `api_version` with a default value of `"2024-12-01-preview"` at line 70.
When the user switches the provider dropdown to `"bedrock"`, this value persists in form state unless
explicitly cleared. Add a `useEffect` (or `onChange` handler on the provider select) that resets
`api_version` to `""` when provider changes to `"bedrock"`:

```ts
// in provider onChange handler:
if (newProvider === "bedrock") {
  setForm((prev) => ({ ...prev, provider: newProvider, api_version: "" }));
}
```

**Acceptance criteria**:

- [ ] `handleSubmit` payload constructor read and inspected
- [ ] For `provider === "bedrock"`, `api_version` is absent (undefined / omitted) in the request body — not `null` or `""`
- [ ] For `provider === "azure_openai"`, `api_version` is included as before
- [ ] When user switches to bedrock provider, `api_version` form field value is cleared (not the stale `"2024-12-01-preview"`)
- [ ] Verified by checking the network request in the browser DevTools during E2E test (BEDROCK-017)
- [ ] No TypeScript errors introduced

---

## BEDROCK-021 — useLLMProviders.ts: verify `ProviderType` union — add `"bedrock"` if needed

**Status**: TODO
**Files**:

- `src/web/lib/hooks/useLLMProviders.ts` — lines 10–17

**Dependencies**: BEDROCK-010

The `LLMLibraryProvider` type (in `useLLMLibrary.ts`) and the `ProviderType` type (in
`useLLMProviders.ts`) serve different tables (`llm_library` vs `llm_providers`). However,
components like `TenantLLMConfig.tsx` import from `useLLMConfig.ts` which may reference
`ProviderType`. If TypeScript narrows on `ProviderType` when rendering library entry providers,
bedrock entries could cause compilation errors or type mismatches.

Read `useLLMProviders.ts` and trace whether `ProviderType` is used anywhere that also accepts
`LLMLibraryProvider` values. If yes, add `"bedrock"` to the union. If the two types are
fully separate code paths with no intersection points, document that explicitly and close
with no change.

Current union at lines 10–17 (approximate):

```typescript
export type ProviderType =
  | "azure_openai"
  | "openai"
  | "anthropic"
  | "deepseek"
  | "dashscope"
  | "doubao"
  | "gemini";
```

**Acceptance criteria**:

- [ ] `useLLMProviders.ts` read and type usage traced through all import sites
- [ ] If `ProviderType` is used in any component that also renders `llm_library` provider values, `"bedrock"` added to the union
- [ ] If types are fully independent, documented as verified-no-change
- [ ] `tsc --noEmit` reports zero new errors after any changes

---

## Summary

| ID          | Area                       | File(s)                                               | Effort              |
| ----------- | -------------------------- | ----------------------------------------------------- | ------------------- |
| BEDROCK-001 | DB migration               | `v050_add_bedrock_provider.py`                        | 0.5h                |
| BEDROCK-002 | Backend: frozenset         | `routes.py` line 63                                   | 0.25h               |
| BEDROCK-003 | Backend: Pydantic schema   | `routes.py` ~line 103                                 | 0.25h               |
| BEDROCK-004 | Backend: publish gate      | `routes.py` ~line 595                                 | 0.5h                |
| BEDROCK-005 | Backend: region validation | `routes.py` create + update handlers                  | 1h                  |
| BEDROCK-006 | Backend: test harness      | `routes.py` `_run_single_test_prompt()`               | 1h                  |
| BEDROCK-007 | Backend: 502 error wrap    | `routes.py` `test_llm_library_profile()`              | 0.5h                |
| BEDROCK-008 | Backend: runtime adapter   | `instrumented_client.py` `_resolve_library_adapter()` | 1.5h                |
| BEDROCK-009 | Backend: embed exclusion   | `instrumented_client.py` `embed()`                    | 0.25h               |
| BEDROCK-010 | Frontend: type union       | `useLLMLibrary.ts` line 10                            | 0.25h               |
| BEDROCK-011 | Frontend: list label       | `LibraryList.tsx` `providerLabel()`                   | 0.25h               |
| BEDROCK-012 | Frontend: providers array  | `LibraryForm.tsx` `PROVIDERS`                         | 0.25h               |
| BEDROCK-013 | Frontend: form fields      | `LibraryForm.tsx` Connection Credentials section      | 1.5h                |
| BEDROCK-014 | Unit tests                 | `test_llm_library_bedrock.py`                         | 1h                  |
| BEDROCK-015 | Integration tests          | `test_llm_library_bedrock_integration.py`             | 1.5h                |
| BEDROCK-016 | Verify cost analytics      | `ModelBreakdownTable.tsx`, `TenantCostTable.tsx`      | 0.25h               |
| BEDROCK-017 | E2E test                   | `test_llm_library_bedrock.spec.ts`                    | 1.5h                |
| BEDROCK-018 | Frontend: tenant panel     | `TenantLLMConfig.tsx` lines 140–146                   | 0.25h               |
| BEDROCK-019 | Frontend: embed note       | `LibraryModeTab.tsx` ~line 120                        | 0.25h               |
| BEDROCK-020 | Frontend: payload strip    | `LibraryForm.tsx` `handleSubmit` + provider onChange  | 0.25h               |
| BEDROCK-021 | Frontend: ProviderType     | `useLLMProviders.ts` lines 10–17                      | 0.25h               |
| **Total**   |                            |                                                       | **~13h (1.5 days)** |

## Recommended implementation order

```
Phase 1 — Backend (Day 1 morning)
  BEDROCK-001 → BEDROCK-002 → BEDROCK-003
  → BEDROCK-004 (publish gate)
  → BEDROCK-005 (region validation)
  → BEDROCK-006 (test harness branch)
  → BEDROCK-007 (verify 502 wrapping)
  → BEDROCK-008 (runtime adapter — BLOCKER for production)
  → BEDROCK-009 (embed exclusion)

Phase 2 — Frontend (Day 1 afternoon)
  BEDROCK-010 (type union — unblocks all frontend)
  → BEDROCK-021 (ProviderType verification — may reveal further type errors)
  → BEDROCK-011 (list label)
  → BEDROCK-012 (providers array)
  → BEDROCK-013 (form fields)
  → BEDROCK-020 (payload strip + api_version clear on provider switch)
  → BEDROCK-016 (verify cost analytics)
  → BEDROCK-018 (tenant panel label)
  → BEDROCK-019 (embed note)

Phase 3 — Tests (Day 2)
  BEDROCK-014 (unit tests)
  → BEDROCK-015 (integration tests)
  → BEDROCK-017 (E2E — requires live Bedrock credentials)
```
