# Bedrock Provider — Implementation Plan

**Date**: 2026-03-22
**Research refs**: `01-research/53-llm-library-redesign-analysis.md`, `01-research/54-bedrock-provider-analysis.md`
**Prerequisite**: The LLM Library redesign from doc 53 must be complete (credentials stored in llm_library, crypto.py extracted, test harness rewritten). This plan is additive on top of that.

---

## Scope

Add `bedrock` as a fourth provider type to the LLM Library. Minimal change — reuses all existing infrastructure.

**In scope:**

- `BedrockProvider` adapter class
- Provider enum extension
- Publish gate for bedrock-specific required fields
- ARN validation
- Frontend: new provider option + conditional credential fields

**Out of scope:**

- IAM/SigV4 auth
- Token expiry management
- Bedrock embeddings
- Any changes to llm_providers table

---

## Phase 1 — Backend (0.5 day)

### Step 1.1 — Provider enum (migration)

`provider` is stored as a `VARCHAR` with a CHECK constraint (confirmed from `migrations/versions/v009_llm_library.py`). There is no PostgreSQL ENUM type. Write:

```python
# migrations/versions/v050_add_bedrock_provider.py

def upgrade():
    op.execute("ALTER TABLE llm_library DROP CONSTRAINT IF EXISTS llm_library_provider_check")
    op.execute("""
        ALTER TABLE llm_library ADD CONSTRAINT llm_library_provider_check
        CHECK (provider IN ('azure_openai', 'openai_direct', 'anthropic', 'bedrock'))
    """)

def downgrade():
    op.execute("""
        DELETE FROM llm_library WHERE provider = 'bedrock'
    """)
    op.execute("ALTER TABLE llm_library DROP CONSTRAINT IF EXISTS llm_library_provider_check")
    op.execute("""
        ALTER TABLE llm_library ADD CONSTRAINT llm_library_provider_check
        CHECK (provider IN ('azure_openai', 'openai_direct', 'anthropic'))
    """)
```

No data migration needed. No new columns.

### Step 1.2 — No separate adapter file needed

The existing codebase uses inline `AsyncOpenAI` / `AsyncAzureOpenAI` client construction directly inside `_run_single_test_prompt` — there is no `_build_provider_from_entry()` factory. Follow the same inline pattern for Bedrock (do NOT create a separate `bedrock.py` adapter file).

**Critical**: Bedrock's OpenAI-compatible base URL uses `/v1` — confirmed in `workspaces/mingai/bedrock.md`. The model ARN goes in `model=` at call time, **not** in the base URL path.

The bedrock elif block to add inside `_run_single_test_prompt`:

```python
elif provider == "bedrock":
    _assert_endpoint_ssrf_safe(entry.endpoint_url)   # required — same as azure_openai
    client = AsyncOpenAI(
        api_key=decrypted_key,
        base_url=f"{entry.endpoint_url.rstrip('/')}/v1",   # /v1, NOT /model/{arn}/
    )
    response = await client.chat.completions.create(
        model=entry.model_name,    # full ARN as model= parameter
        messages=[{"role": "user", "content": prompt}],
    )
    # extract content, tokens, latency — same as openai_direct branch
```

### Step 1.3 — Routes: validation + publish gate + test harness

In `src/backend/app/modules/platform/llm_library/routes.py`:

**1. `_VALID_PROVIDERS` frozenset** (line ~63) — MUST add `"bedrock"` or create rejects it before any other logic:

```python
_VALID_PROVIDERS = frozenset({"azure_openai", "openai_direct", "anthropic", "bedrock"})
```

**2. Pydantic `Literal` type + field description:**

```python
provider: Literal["azure_openai", "openai_direct", "anthropic", "bedrock"]
# Also update description="One of: azure_openai, openai_direct, anthropic, bedrock"
```

**3. Model name validation** — **no ARN prefix check** (ADR-5). Bedrock accepts ARNs, plain model IDs (`anthropic.claude-3-sonnet-20240229-v1:0`), and cross-region profile IDs. A prefix check rejects valid non-ARN formats. Existing `max_length=200` + non-empty is sufficient. Test harness is the authoritative validator — AWS returns a clear error for invalid model names.

**4. Publish gate** — uses Pydantic object attribute access (NOT dict `.get()`), as an explicit `elif`:

```python
elif entry.provider == "bedrock":
    if not entry.endpoint_url:
        raise HTTPException(422, "Bedrock entries require endpoint_url (BEDROCK_BASE_URL)")
    if not entry.api_key_encrypted:
        raise HTTPException(422, "Bedrock entries require an AWS Bearer Token")
    # api_version explicitly NOT required for bedrock
```

**5. Test harness** — inline inside `_run_single_test_prompt` (no separate adapter file); MUST call `_assert_endpoint_ssrf_safe` and use `/v1` base URL:

```python
elif provider == "bedrock":
    _assert_endpoint_ssrf_safe(entry.endpoint_url)         # mandatory — same as azure_openai
    client = AsyncOpenAI(
        api_key=decrypted_key,
        base_url=f"{entry.endpoint_url.rstrip('/')}/v1",   # /v1 suffix — NOT /model/{arn}/
    )
    response = await client.chat.completions.create(
        model=entry.model_name,    # full ARN passed as model= parameter
        messages=[{"role": "user", "content": prompt}],
    )
    # extract content / tokens / latency — same pattern as openai_direct branch
```

### Step 1.4 — `InstrumentedLLMClient._resolve_library_adapter` (BLOCKER for production)

**File**: `src/backend/app/core/llm/instrumented_client.py`

This is the runtime adapter resolver — the code that constructs the actual LLM client when a tenant's query hits a Published library entry. Without a Bedrock branch here, production traffic fails with `ValueError("Provider type 'bedrock' does not have a supported adapter")` even after the library entry is published and tested.

Add bedrock branch inside `_resolve_library_adapter`:

```python
elif db_provider_type == "bedrock":
    decrypted_key = decrypt_api_key(row["api_key_encrypted"])
    try:
        client = AsyncOpenAI(
            api_key=decrypted_key,
            base_url=f"{row['endpoint_url'].rstrip('/')}/v1",   # /v1, NOT /model/{arn}/
        )
        return OpenAIDirectAdapter(client=client, model=row["model_name"])  # reuse existing adapter
    finally:
        decrypted_key = ""    # always clear
```

### Step 1.5 — Embedding exclusion for Bedrock

**File**: `src/backend/app/core/llm/instrumented_client.py` — `embed()` method

Bedrock's OpenAI-compatible endpoint does not support embeddings. Add Bedrock to the exclusion list alongside Anthropic in the embedding fallback path:

```python
# Existing: if provider in ("anthropic",): use_fallback_embedding = True
# Updated:
if db_provider_type in ("anthropic", "bedrock"):
    use_fallback_embedding = True
```

### Step 1.6 — Region cross-validation

In the create/update route handler, after the ARN prefix check, validate that the region embedded in the ARN matches the region in the endpoint URL:

```python
if request.provider == "bedrock" and request.endpoint_url and request.model_name:
    # Extract region from ARN: arn:aws:bedrock:{region}:{account}:...
    arn_parts = request.model_name.split(":")
    if len(arn_parts) >= 4:
        arn_region = arn_parts[3]
        # Extract region from URL: https://bedrock-runtime.{region}.amazonaws.com
        url_parts = request.endpoint_url.replace("https://", "").split(".")
        if len(url_parts) >= 2:
            url_region = url_parts[1]
            if arn_region != url_region:
                raise HTTPException(
                    422,
                    f"Region mismatch: endpoint_url is '{url_region}' but model ARN is '{arn_region}'"
                )
```

### Step 1.7 — Defensive `usage` handling in test harness

Bedrock may return `None` for `usage` on some models. The bedrock branch must guard against this:

```python
tokens_in = response.usage.prompt_tokens if response.usage else 0
tokens_out = response.usage.completion_tokens if response.usage else 0
```

---

## Phase 2 — Frontend (0.5 day)

### Step 2.1 — Provider options

**`LibraryList.tsx`** — add `"bedrock"` to `providerLabel()` switch:

```tsx
case "bedrock": return "AWS Bedrock";
```

**`LibraryForm.tsx`** — PROVIDERS array:

```tsx
const PROVIDER_OPTIONS = [
  { value: "azure_openai", label: "Azure OpenAI" },
  { value: "openai_direct", label: "OpenAI Direct" },
  { value: "anthropic", label: "Anthropic" },
  { value: "bedrock", label: "AWS Bedrock" }, // add
];
```

### Step 2.2 — Endpoint URL visibility fix

Currently `endpoint_url` field renders only when `provider === "azure_openai"`. Bedrock also requires it. Update the condition:

```tsx
// Before:
{
  provider === "azure_openai" && <EndpointUrlField />;
}

// After:
{
  (provider === "azure_openai" || provider === "bedrock") && (
    <EndpointUrlField />
  );
}
```

`api_version` remains Azure-only. `api_version` field must be hidden when `provider === "bedrock"`.

### Step 2.3 — Conditional credential fields (labels)

```tsx
{
  /* Bedrock: endpoint + bearer token, no api_version */
}
{
  provider === "bedrock" && (
    <>
      <FormField
        label="Bedrock Base URL"
        name="endpoint_url"
        placeholder="https://bedrock-runtime.ap-southeast-1.amazonaws.com"
        required
      />
      <FormField
        label="AWS Bearer Token"
        name="api_key"
        type="password"
        placeholder="ABSK..."
        hint={
          entry?.key_present
            ? `Token saved (****...${entry.api_key_last4})`
            : undefined
        }
        required
      />
      {/* model_name (ARN) already in the base form — add hint text */}
    </>
  );
}
```

### Step 2.3 — Model name hint

When `provider === "bedrock"`, show helper text below the model name field:

```
"Enter the full ARN, e.g. arn:aws:bedrock:ap-southeast-1:123456789:application-inference-profile/..."
```

### Step 2.4 — Type updates (`useLLMLibrary.ts`)

```typescript
export type LLMProvider =
  | "azure_openai"
  | "openai_direct"
  | "anthropic"
  | "bedrock";
```

No other type changes needed — `endpoint_url`, `api_key`, `key_present`, `api_key_last4` already added as part of the doc 53 redesign.

---

## Phase 3 — Integration Test (0.5 day)

### Test checklist

- [ ] Create Bedrock entry with valid ARN, bearer token, endpoint URL → saves as Draft
- [ ] Create Bedrock entry with non-ARN model_name → rejected with 422
- [ ] Create Bedrock entry with missing endpoint_url → rejected with 422
- [ ] Attempt to publish without running test → rejected with 422
- [ ] Run connectivity test → verifies entry credentials (not env vars)
- [ ] Run connectivity test with expired/invalid token → test fails, clear error message returned
- [ ] Publish after successful test → entry moves to Published
- [ ] API response for Published entry → `api_key_encrypted` absent, `key_present: true`, `api_key_last4` present
- [ ] Existing azure_openai / openai_direct / anthropic entries unaffected

### Unit tests

```python
# tests/unit/test_llm_library_bedrock.py

def test_bedrock_base_url_construction():
    """Bedrock base_url must use /v1 suffix — model name is NOT embedded in base_url."""
    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com"
    base_url = f"{endpoint.rstrip('/')}/v1"
    assert base_url == "https://bedrock-runtime.ap-southeast-1.amazonaws.com/v1"

def test_bedrock_accepts_arn_model_name():
    """Bedrock accepts full ARN (no prefix validation — per ADR-5)."""
    arn = "arn:aws:bedrock:ap-southeast-1:123456:application-inference-profile/abc"
    assert len(arn) <= 200  # max_length check only

def test_bedrock_accepts_plain_model_id():
    """Bedrock also accepts non-ARN model IDs — ADR-5: no prefix check."""
    model_id = "anthropic.claude-3-sonnet-20240229-v1:0"
    assert len(model_id) <= 200  # valid — test harness validates model existence

def test_bedrock_region_cross_validation():
    """Region in ARN must match region in endpoint_url."""
    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com"
    arn = "arn:aws:bedrock:us-east-1:123456:application-inference-profile/abc"
    url_region = endpoint.replace("https://", "").split(".")[1]  # ap-southeast-1
    arn_region = arn.split(":")[3]                               # us-east-1
    assert url_region != arn_region  # should trigger 422 at create time

def test_bedrock_publish_gate_requires_endpoint():
    """Bedrock entries without endpoint_url must be rejected at publish."""
    # Covered by integration test — endpoint_url is required for bedrock
    pass
```

---

## Delivery Summary

| Phase     | Work                                                                                                                                                    | Effort     |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| Phase 1   | Migration + routes (validation, publish gate, test harness) + `InstrumentedLLMClient` (runtime adapter + embedding exclusion) + region cross-validation | 1 day      |
| Phase 2   | Frontend: provider list, endpoint_url visibility, field labels, api_version hide, type union                                                            | 0.5 day    |
| Phase 3   | Integration tests + cost analytics verification                                                                                                         | 0.5 day    |
| **Total** |                                                                                                                                                         | **2 days** |

**Files touched (minimum 7):**

- `routes.py` — `_VALID_PROVIDERS`, publish gate, ARN + region validation, test harness branch
- `instrumented_client.py` — `_resolve_library_adapter` Bedrock branch, `embed()` exclusion
- `migrations/v050_add_bedrock_provider.py` — CHECK constraint update (no new columns)
- `LibraryForm.tsx` — endpoint_url visibility for bedrock, api_version hidden for bedrock, field labels
- `LibraryList.tsx` — `providerLabel()` case
- `useLLMLibrary.ts` — `LLMLibraryProvider` type union
- `tests/unit/test_llm_library_*.py` — Bedrock validation unit tests

**Verify (no code changes, confirm graceful handling):**

- `ModelBreakdownTable.tsx`, `TenantCostTable.tsx` — must handle `provider="bedrock"` without hardcoded provider lists
