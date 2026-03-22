# 54 -- AWS Bedrock Provider: Requirements & Architecture Decisions

**Status**: Proposed
**Date**: 2026-03-22
**Builds on**: `53-llm-library-redesign-analysis.md`
**Scope**: Adding AWS Bedrock as a new provider type to the LLM Library

---

## 0. Executive Summary

| Attribute        | Value                                                               |
| ---------------- | ------------------------------------------------------------------- |
| Feature          | AWS Bedrock provider for LLM Library                                |
| Complexity       | Medium                                                              |
| Risk Level       | Medium (new auth model, DB constraint change, new adapter branch)   |
| Estimated Effort | 3--5 days                                                           |
| Affected Files   | Migration (v050+), routes.py, instrumented_client.py, frontend form |
| New Dependencies | None (reuses existing `openai` package)                             |

---

## 1. What Bedrock Is (in this context)

AWS Bedrock is a managed service that hosts foundation models from multiple vendors (Anthropic, Meta, Mistral, Amazon, etc.) behind a unified AWS API. The provider name is `bedrock` — generic, not tied to a specific model family — because the same config pattern applies regardless of which model is hosted.

This implementation targets **Application Inference Profiles** accessed via **AWS Bearer Token authentication** — the pattern provided in the reference config.

---

## 2. Config → LLM Library Field Mapping

| Bedrock Config Variable    | LLM Library Field   | Notes                                                               |
| -------------------------- | ------------------- | ------------------------------------------------------------------- |
| `BEDROCK_MODEL_INTENT` ARN | `model_name`        | Full ARN stored as-is. e.g. `arn:aws:bedrock:ap-southeast-1:...`    |
| `AWS_BEARER_TOKEN_BEDROCK` | `api_key_encrypted` | Fernet-encrypted BYTEA. Same encryption path as all other providers |
| `BEDROCK_BASE_URL`         | `endpoint_url`      | `https://bedrock-runtime.ap-southeast-1.amazonaws.com`              |
| `AWS_DEFAULT_REGION`       | Derivable from URL  | `ap-southeast-1` is embedded in `endpoint_url` — no new column      |

### Why region doesn't need a new column

The `endpoint_url` for Bedrock follows a deterministic pattern:

```
https://bedrock-runtime.{region}.amazonaws.com
```

Region is extractable: `endpoint_url.split(".")[1]` = `ap-southeast-1`. The adapter constructs the full API path from `endpoint_url` directly — no separate region field required. This keeps the schema unchanged beyond the enum addition.

---

## 3. Provider Field Matrix (updated from doc 53)

| Field                 | azure_openai | openai_direct |  anthropic   |    **bedrock**     |
| --------------------- | :----------: | :-----------: | :----------: | :----------------: |
| `model_name`          |   REQUIRED   |   REQUIRED    |   REQUIRED   | **REQUIRED (ARN)** |
| `endpoint_url`        |   REQUIRED   |       —       |      —       |    **REQUIRED**    |
| `api_key_encrypted`   |   REQUIRED   |   REQUIRED    |   REQUIRED   |    **REQUIRED**    |
| `api_version`         |   REQUIRED   |       —       |      —       |       **—**        |
| `api_key_last4`       | auto-derived | auto-derived  | auto-derived |  **auto-derived**  |
| `pricing_*`           | publish gate | publish gate  | publish gate |  **publish gate**  |
| `last_test_passed_at` |   required   |   required    |   required   |    **required**    |

---

## 4. Schema Changes

**Only one change**: add `"bedrock"` to the `provider` CHECK constraint (or enum).

```sql
-- No new columns. Bedrock reuses existing fields.
-- Only the provider constraint expands:
ALTER TABLE llm_library DROP CONSTRAINT IF EXISTS llm_library_provider_check;
ALTER TABLE llm_library ADD CONSTRAINT llm_library_provider_check
  CHECK (provider IN ('azure_openai', 'openai_direct', 'anthropic', 'bedrock'));
```

If `provider` is a PostgreSQL native ENUM type:

```sql
ALTER TYPE llm_provider_type ADD VALUE IF NOT EXISTS 'bedrock';
```

---

## 5. Adapter Design: `BedrockProvider`

### Auth mechanism

Bedrock Application Inference Profiles support an **OpenAI-compatible endpoint** authenticated via HTTP Bearer token. This means we can use `AsyncOpenAI` (already a dependency) pointed at the Bedrock runtime URL, with the bearer token as the `api_key` argument.

No boto3, no SigV4, no new dependencies.

### Client construction

The correct base URL for Bedrock's OpenAI-compatible endpoint is `{endpoint_url}/v1` — the `/v1` suffix is what the `AsyncOpenAI` SDK appends its paths from (`/v1/chat/completions`). The model ARN is passed as the `model=` argument at call time, not embedded in the base URL.

Reference: `workspaces/mingai/bedrock.md` confirms `base_url = "https://bedrock-runtime.ap-southeast-1.amazonaws.com/v1"`.

```python
# Inline client pattern (consistent with existing azure_openai, anthropic branches in _run_single_test_prompt)
# No separate BedrockProvider class needed — follow the inline pattern already established

from openai import AsyncOpenAI

# Inside _run_single_test_prompt, bedrock elif branch:
elif provider == "bedrock":
    _assert_endpoint_ssrf_safe(entry.endpoint_url)   # MUST call SSRF check (same as azure_openai)
    client = AsyncOpenAI(
        api_key=decrypted_key,
        base_url=f"{entry.endpoint_url.rstrip('/')}/v1",  # /v1 suffix, NOT /model/{arn}/
    )
    response = await client.chat.completions.create(
        model=entry.model_name,     # full ARN passed as model= parameter
        messages=[{"role": "user", "content": prompt}],
    )

    async def complete(self, messages: list[dict], model: str = None, **kwargs) -> CompletionResponse:
        import time
        start = time.monotonic()
        response = await self._client.chat.completions.create(
            model=self._model_arn,
            messages=messages,
            **kwargs,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        choice = response.choices[0]
        return CompletionResponse(
            content=choice.message.content,
            tokens_in=response.usage.prompt_tokens,
            tokens_out=response.usage.completion_tokens,
            model=self._model_arn,
            provider="bedrock",
            latency_ms=latency_ms,
        )
```

The connectivity test ping is identical to other providers: send a short user message, verify a response is returned, record `last_test_passed_at`.

**Important**: `asyncio.gather` fires all 3 test prompts simultaneously. Bedrock Application Inference Profiles have tighter RPS limits than Azure OpenAI — 3 concurrent calls may trigger a 429 on non-production profiles. Consider sequential execution for the Bedrock branch, or document that 429 errors in tests indicate rate limiting, not credential failure.

---

## 6. Publish Gate for Bedrock

The existing publish gate uses Pydantic object attribute access (not dict `.get()`). The bedrock branch must follow the same pattern:

```python
elif entry.provider == "bedrock":
    if not entry.endpoint_url:
        raise HTTPException(422, "Bedrock entries require endpoint_url (BEDROCK_BASE_URL)")
    if not entry.api_key_encrypted:
        raise HTTPException(422, "Bedrock entries require an AWS Bearer Token")
    # api_version explicitly NOT required for bedrock — skip the azure_openai api_version check
```

The `api_version` is explicitly skipped for Bedrock — this must be an active `elif` branch, not just an omission, so the shared validation logic doesn't accidentally apply the Azure api_version check.

---

## 7. Frontend Changes

### Provider dropdown

Add `"bedrock"` option with display label `"AWS Bedrock"`:

```tsx
const PROVIDER_OPTIONS = [
  { value: "azure_openai", label: "Azure OpenAI" },
  { value: "openai_direct", label: "OpenAI Direct" },
  { value: "anthropic", label: "Anthropic" },
  { value: "bedrock", label: "AWS Bedrock" }, // new
];
```

### Conditional credential fields (LibraryForm.tsx)

```tsx
// Bedrock: endpoint + bearer token (no api_version)
{provider === "bedrock" && (
  <>
    <Field label="Bedrock Base URL" placeholder="https://bedrock-runtime.ap-southeast-1.amazonaws.com" ... />
    <Field label="AWS Bearer Token" type="password" ... />
    <Field label="Model ARN" placeholder="arn:aws:bedrock:ap-southeast-1:...:application-inference-profile/..." ... />
  </>
)}
```

### API key label

When `provider === "bedrock"`, the API key field label reads **"AWS Bearer Token"**, not "API Key". This is purely a UI label — the backend field is still `api_key` / `api_key_encrypted`.

### Key masking

`api_key_last4` is derived from the last 4 characters of the bearer token (same as all other providers). Displayed as `****...{last4}` when a token is already stored.

---

## 8. Model Name Validation

**Per ADR-5: Permissive validation only.**

Bedrock `model_name` accepts multiple formats — full ARN (`arn:aws:bedrock:...`), model ID (`anthropic.claude-3-sonnet-20240229-v1:0`), cross-region profile IDs, and custom model ARNs. A strict prefix check would reject valid non-ARN identifiers that Bedrock supports.

Validation: non-empty + `max_length=200` (consistent with all other providers — no model_name format validation). The connectivity test is the authoritative validator: an incorrect model name returns a clear AWS error message that surfaces directly to the platform admin.

**No ARN prefix check is implemented.** The earlier section 8 draft showing `arn:aws:bedrock:` prefix check is superseded by ADR-5.

### `api_key_last4` for bearer tokens

Bedrock bearer tokens are base64-encoded and typically end in `=` padding characters (e.g. `rT0=`). The last 4 chars will often show padding rather than unique content. This is a UX limitation — not a security issue. Displaying `****...rT0=` remains acceptable for distinguishing between tokens at a glance.

---

## 9. Security Invariants (same as all providers)

1. `api_key_encrypted` BYTEA — never returned in any API response
2. `api_key_last4` — only key metadata visible in responses
3. Bearer token decrypted only in test/use paths, cleared (`= ""`) in `finally` block immediately
4. Logs redact token as `[REDACTED]`
5. Audit log records test run (who, which entry, pass/fail, timestamp) — not the token or response content

### Bearer token semantics vs API key

A bearer token is more privileged than a typical API key — it may grant access to multiple models and accounts under the AWS account. Key considerations:

- Treat expiry as a real operational risk (tokens may have TTLs unlike API keys)
- Document in UI: "Bearer tokens may expire. If tests fail unexpectedly, refresh the token."
- No automated expiry detection — the connectivity test serves as the manual verification gate

---

## 10. What Is Out of Scope

| Item                      | Reason                                                                                |
| ------------------------- | ------------------------------------------------------------------------------------- |
| IAM/SigV4 authentication  | Requires boto3, adds significant complexity. Bearer token covers the stated use case. |
| Streaming completions     | Not part of LLM Library connectivity test. Streaming is a RAG pipeline concern.       |
| Bedrock Titan embeddings  | LLM Library entries are for chat/completion models. Embeddings handled separately.    |
| Multi-region failover     | Single endpoint per entry. Failover is an infrastructure concern.                     |
| Token refresh/rotation UI | Day 2 feature. Platform admin manually updates token when expired.                    |

---

## 11. Risk Register

| ID  | Risk                                                                             | Likelihood          | Impact      | Mitigation                                                                                         |
| --- | -------------------------------------------------------------------------------- | ------------------- | ----------- | -------------------------------------------------------------------------------------------------- |
| R1  | Bearer token expires mid-operation                                               | Medium              | High        | Connectivity test catches expiry; UI shows last test date                                          |
| R2  | ARN points to wrong region vs endpoint_url                                       | Medium              | Medium      | ARN prefix validation catches region mismatch early                                                |
| R3  | Wrong `base_url` construction — `/model/{arn}/` instead of `/v1` causes 404      | **Confirmed/Fixed** | Critical    | Use `{endpoint_url}/v1`; ARN goes in `model=` param. Confirmed in `bedrock.md`.                    |
| R4  | Token has insufficient IAM permissions for the inference profile                 | Medium              | Medium      | Connectivity test will fail with 403; surfaced in test results                                     |
| R5  | Token grants broader AWS access than intended                                    | Low                 | High        | Document that tokens should be scoped to Bedrock runtime only                                      |
| R6  | api_version check in shared publish gate applies to bedrock                      | Low                 | Low         | Explicit `elif provider == "bedrock"` branch skips api_version requirement                         |
| R7  | `asyncio.gather` fires 3 concurrent prompts; Bedrock profiles have tight RPS     | Medium              | Medium      | May need sequential execution for bedrock, or clearer 429 error message                            |
| R8  | `_VALID_PROVIDERS` frozenset not updated — create rejects "bedrock" at line 353  | Certain             | Critical    | Add `"bedrock"` to frozenset alongside Pydantic `Literal` type update                              |
| R9  | `InstrumentedLLMClient._resolve_library_adapter` has no Bedrock branch — BLOCKER | Certain             | Critical    | Add `elif db_provider_type == "bedrock"` using `AsyncOpenAI(base_url=.../v1)` inline               |
| R10 | Bedrock not excluded from `embed()` path — falls to broken adapter               | Certain             | Major       | Add `"bedrock"` to `("anthropic", "bedrock")` exclusion; fall back to azure_openai for embeddings  |
| R11 | Region mismatch between ARN and endpoint_url not caught until test-time          | Medium              | Major       | Cross-validate regions at create/update time (extractable from both ARN prefix and URL hostname)   |
| R12 | ARN contains AWS account ID — must never appear in tenant-facing UI              | Medium              | Significant | All tenant-facing components must use `display_name`; require non-empty `display_name` for bedrock |

---

## 12. Formal Functional Requirements

### FR-1: Create Bedrock Entry

| Attribute      | Value                                                                                                                                                                                  |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Input          | provider="bedrock", model_name (ARN), display_name, endpoint_url, api_key (bearer token)                                                                                               |
| Output         | Draft LLM Library entry with encrypted bearer token                                                                                                                                    |
| Business Logic | Validate provider in `_VALID_PROVIDERS`; validate endpoint_url starts with `https://`; encrypt bearer token via `encrypt_api_key()`; derive `api_key_last4` from last 4 chars of token |
| Edge Cases     | Bearer token shorter than 8 chars (blocked by existing `min_length=8`); endpoint URL with trailing slash (stripped by `rstrip('/')`); ARN vs short model ID                            |
| SDK Mapping    | Reuses `encrypt_api_key()`, `_SELECT_COLUMNS`, `_row_to_entry()`                                                                                                                       |

### FR-2: Test Bedrock Entry

| Attribute      | Value                                                                                                                                                                                                                                                                                                               |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Input          | Entry ID (existing Bedrock entry with encrypted bearer token)                                                                                                                                                                                                                                                       |
| Output         | 3 `TestPromptResult` objects with token counts, latency, cost                                                                                                                                                                                                                                                       |
| Business Logic | Decrypt bearer token via `decrypt_api_key()`; SSRF-check endpoint_url; construct `AsyncOpenAI(base_url={endpoint_url}/v1, api_key=bearer_token)`; call `chat.completions.create(model=model_name)`; extract `usage.prompt_tokens`, `usage.completion_tokens`; on all 3 pass, write `NOW()` to `last_test_passed_at` |
| Edge Cases     | Bearer token expired (AWS 403); non-standard usage fields; timeout (30s); model ARN not found (404); Bedrock rate limiting (429 on concurrent prompts via `asyncio.gather`)                                                                                                                                         |
| SDK Mapping    | New `elif provider == "bedrock"` branch in `_run_single_test_prompt()`                                                                                                                                                                                                                                              |

### FR-3: Publish Bedrock Entry

| Attribute      | Value                                                                                                                                                                                                                                 |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Input          | Entry ID for a Draft Bedrock entry                                                                                                                                                                                                    |
| Output         | Status transitions to Published                                                                                                                                                                                                       |
| Business Logic | Publish gate: `api_key_encrypted` present, `endpoint_url` present, `last_test_passed_at` present. `api_version` explicitly NOT required. Must be an active `elif` branch to prevent azure_openai's `api_version` check from applying. |
| Edge Cases     | Entry with endpoint_url but no bearer token (blocked by `key_present` check)                                                                                                                                                          |
| SDK Mapping    | Extend `publish_llm_library_entry()` with `elif entry.provider == "bedrock"`                                                                                                                                                          |

### FR-4: Use Bedrock Entry for Tenant Queries

| Attribute      | Value                                                                                                                                                              |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Input          | Tenant assigned to a Published Bedrock entry; user query                                                                                                           |
| Output         | LLM completion via Bedrock                                                                                                                                         |
| Business Logic | `InstrumentedLLMClient` resolves tenant config, selects Bedrock adapter, constructs `AsyncOpenAI` with `base_url={endpoint_url}/v1` and bearer token, routes query |
| Edge Cases     | Bearer token expiry mid-session; Bedrock throttling (429)                                                                                                          |
| SDK Mapping    | New adapter branch in `InstrumentedLLMClient.complete()`                                                                                                           |

### FR-5: Frontend Display

| Attribute   | Value                                                                                                                                                                                                                  |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Input       | API response with provider="bedrock"                                                                                                                                                                                   |
| Output      | Provider-conditional form: endpoint_url (required, labeled "Bedrock Base URL"), api_key (labeled "AWS Bearer Token"), model_name (labeled "Model ARN"), api_version (hidden), region badge (derived from endpoint_url) |
| Edge Cases  | Other provider entries unchanged; `api_key_last4` may show base64 padding chars                                                                                                                                        |
| SDK Mapping | Frontend only                                                                                                                                                                                                          |

### FR-6: Database Migration

| Attribute      | Value                                                                                           |
| -------------- | ----------------------------------------------------------------------------------------------- |
| Input          | Alembic migration v050+                                                                         |
| Output         | Provider CHECK constraint expanded: `('azure_openai', 'openai_direct', 'anthropic', 'bedrock')` |
| Business Logic | DROP + ADD CONSTRAINT pattern; no new columns                                                   |
| Edge Cases     | Idempotent (IF EXISTS guards); existing rows unaffected                                         |

---

## 13. Non-Functional Requirements

### Security

| Requirement               | Specification                                                          |
| ------------------------- | ---------------------------------------------------------------------- |
| Bearer token storage      | Encrypted via existing Fernet path (`api_key_encrypted` BYTEA)         |
| Bearer token in responses | NEVER returned; only `key_present: bool` and `api_key_last4`           |
| Bearer token in logs      | Always `[REDACTED]` (existing pattern)                                 |
| Bearer token in memory    | Cleared (`= ""`) in `finally` block after use (existing pattern)       |
| Endpoint URL validation   | SSRF check via `_assert_endpoint_ssrf_safe()` before any outbound call |
| Bearer token scope        | UI documents tokens should be scoped to Bedrock runtime only           |

### Performance

| Requirement          | Specification                                                                                                                  |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Test harness latency | < 30s total for 3 prompts (`_TEST_TIMEOUT_SECONDS = 30`)                                                                       |
| Rate limiting        | Bedrock profiles have tighter RPS; 3 concurrent test prompts may trigger 429 -- surface as clear error, not credential failure |
| No new dependencies  | Reuses `openai` package (already installed for azure_openai + openai_direct)                                                   |

### Backward Compatibility

| Requirement            | Specification                                                    |
| ---------------------- | ---------------------------------------------------------------- |
| Existing entries       | Zero impact; migration only adds to CHECK constraint             |
| Existing API contracts | No breaking changes; `provider` field accepts one new value      |
| Existing tests         | All existing unit/integration tests pass without modification    |
| Frontend               | Provider selector gains one option; all existing flows unchanged |

---

## 14. Architecture Decision Records

### ADR-1: Bearer Token Only (Not IAM/SigV4)

**Status**: Proposed

#### Context

AWS Bedrock supports two auth mechanisms: (1) IAM/SigV4 using access key ID + secret access key + optional session token, and (2) bearer token -- a single string usable with Bedrock's OpenAI-compatible endpoint. The LLM Library stores a single encrypted string (`api_key_encrypted` BYTEA). IAM credentials require two or three strings -- a fundamentally different shape.

mingai's deployment uses bearer tokens (`AWS_BEARER_TOKEN_BEDROCK`).

#### Options Considered

| Option               | Description                           | Pros                                                                                  | Cons                                                                      |
| -------------------- | ------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| A. Bearer token only | Store in existing `api_key_encrypted` | Zero schema change; reuses Fernet; single credential matches model; no new dependency | No IAM-native auth; tokens expire and must be rotated manually            |
| B. IAM only          | Two new BYTEA columns                 | Standard AWS auth; no token rotation                                                  | Schema change; `boto3` dependency (~50MB); breaks single-credential model |
| C. Both              | Discriminator field selects auth mode | Maximum flexibility                                                                   | Doubles validation; unclear UX; premature generalization                  |

#### Decision

**Option A -- Bearer token only.**

#### Rationale

- Bearer token fits the existing single-string credential model with zero schema change.
- The deployment already uses bearer tokens -- operational reality, not theoretical preference.
- IAM requires `boto3` (~50MB), adding dependency weight and supply-chain surface.
- Future IAM support can be additive as a separate provider type (`bedrock_iam`), not a breaking migration.

#### Consequences

- **Positive**: Zero new dependencies, zero credential schema changes, consistent model.
- **Negative**: Manual token rotation required. No STS/assume-role. Token expiry causes tenant failures until refreshed and re-tested.

---

### ADR-2: OpenAI-Compatible Client (Not boto3/aioboto3)

**Status**: Proposed

#### Context

Bedrock exposes an OpenAI-compatible API at `{endpoint_url}/v1` when accessed with a bearer token. The `openai` package (already installed) works with a `base_url` override. The alternative is `boto3`/`aioboto3` with the native Bedrock API (different request/response schema).

Confirmed by `workspaces/mingai/bedrock.md`: `base_url = "https://bedrock-runtime.ap-southeast-1.amazonaws.com/v1"`.

#### Options Considered

| Option                                               | Description                  | Pros                                                                              | Cons                                                                       |
| ---------------------------------------------------- | ---------------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| A. `AsyncOpenAI(base_url=..., api_key=bearer_token)` | Reuse existing OpenAI client | Zero new deps; consistent token counting; code identical to openai_direct; proven | Dependent on AWS maintaining compat endpoint; no Bedrock-specific features |
| B. `aioboto3` + native API                           | AWS SDK                      | Full feature access; standard patterns                                            | ~50MB new dep; different response schema; different code path              |
| C. `httpx` + manual SigV4                            | Raw HTTP                     | No dep; full control                                                              | Must implement SigV4; fragile; high maintenance                            |

#### Decision

**Option A -- `openai.AsyncOpenAI` with `base_url` override.**

#### Rationale

- Proven in deployment. `openai` already installed. `base_url` override is ~5 lines.
- Token counting uses `usage.prompt_tokens` / `usage.completion_tokens` -- `_calculate_test_cost()` unchanged.
- No new supply-chain attack surface.

#### Consequences

- **Positive**: Minimal change; no deps; consistent response handling.
- **Negative**: If AWS deprecates compat endpoint, `aioboto3` migration needed. Bedrock-specific features inaccessible. Acceptable: LLM Library is a connectivity/catalog layer.

---

### ADR-3: Derive Region from Endpoint URL (No Explicit Column)

**Status**: Proposed

#### Context

Bedrock endpoints encode region: `https://bedrock-runtime.ap-southeast-1.amazonaws.com`. Region could be stored in a new column or derived from the URL.

#### Options Considered

| Option                               | Description                                               | Pros                                                           | Cons                                          |
| ------------------------------------ | --------------------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------- |
| A. Derive from endpoint_url          | Parse via `bedrock-runtime\.([a-z0-9-]+)\.amazonaws\.com` | No schema change; single source of truth; no mismatch possible | VPC endpoints may not match                   |
| B. Explicit `aws_region` VARCHAR(30) | New column                                                | Explicit; works for non-standard URLs                          | Schema change; possible mismatch; more fields |
| C. Both                              | Explicit + derivation fallback                            | Handles all cases                                              | Two sources of truth; conflict resolution     |

#### Decision

**Option A -- Derive region from endpoint URL.**

#### Rationale

- Separate storage creates mismatch risk (column says one region, URL points to another).
- Regex is simple and stable: `bedrock-runtime\.([a-z0-9-]+)\.amazonaws\.com`.
- VPC endpoints: derivation returns None, UI omits region badge. Cosmetic degradation only.
- No migration required.

#### Consequences

- **Positive**: No migration; single source of truth; simpler form.
- **Negative**: VPC endpoints do not display region. Acceptable.

---

### ADR-4: Provider Name "bedrock" (Generic)

**Status**: Proposed

#### Context

Bedrock hosts models from Anthropic, Meta, Amazon, Cohere, Mistral. The enum value could be generic or model-family-specific.

#### Options Considered

| Option                                       | Description                         | Pros                                                                      | Cons                                                                  |
| -------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| A. `bedrock`                                 | Single value for all Bedrock models | Simple; matches `azure_openai` precedent; `model_name` captures specifics | Cannot filter by model family at provider level                       |
| B. `bedrock_anthropic`, `bedrock_meta`, etc. | One per family                      | Explicit                                                                  | Proliferates enum; redundant with ARN; inconsistent with azure_openai |
| C. `aws_bedrock`                             | Cloud vendor prefix                 | Matches AWS naming                                                        | Inconsistent (not `ms_azure_openai`); longer                          |

#### Decision

**Option A -- `bedrock`.**

#### Rationale

- `azure_openai` precedent: one hosting platform = one provider value regardless of model families hosted.
- Specific model is in `model_name` (ARN). Provider enum duplication is redundant.
- Fewer enum values = simpler validation, UI, documentation.

#### Consequences

- **Positive**: Minimal enum change; clean UI; consistent.
- **Negative**: No provider-level model family filter. Not a requirement.

---

### ADR-5: Permissive ARN Validation (Not Strict Regex)

**Status**: Proposed

#### Context

Bedrock model names take multiple forms: full ARN (`arn:aws:bedrock:...`), model ID (`anthropic.claude-3-sonnet-...`), cross-region profile (`us.anthropic.claude-...`), custom model ARN. The `model_name` column is VARCHAR(200).

#### Options Considered

| Option                                 | Description                            | Pros                                                             | Cons                                           |
| -------------------------------------- | -------------------------------------- | ---------------------------------------------------------------- | ---------------------------------------------- |
| A. Permissive (max_length + non-empty) | Accept any string up to 200 chars      | All formats; no regex maintenance; consistent with openai_direct | Typos not caught until test harness            |
| B. Strict ARN regex                    | `^arn:aws:bedrock:...`                 | Catches typos                                                    | Rejects model IDs; must update for new formats |
| C. Prefix check                        | `arn:aws:bedrock:` OR model ID pattern | Covers common cases                                              | Maintenance burden; may reject valid formats   |

#### Decision

**Option A -- Permissive validation (max_length + non-empty).**

_Note_: The existing doc (section 8) shows a prefix check (`arn:aws:bedrock:`). Per this ADR, that check should be removed. The test harness is the authoritative validation -- if the model_name is wrong, the test call returns a clear AWS error. A prefix check would reject valid non-ARN model IDs (e.g., `anthropic.claude-3-sonnet-20240229-v1:0`).

#### Rationale

- Existing providers do not validate model_name format. Consistency.
- Test harness is the real validation with clear AWS error messages.
- ARN formats change with new AWS resource types. Regex is maintenance burden.
- VARCHAR(200) sufficient (typical ARN ~90 chars).

#### Consequences

- **Positive**: No regex; consistent; test harness catches errors clearly.
- **Negative**: Typos caught at test time, not at create time. Same as all providers.

---

## 15. Acceptance Criteria

### Must Pass (Blocking)

- [ ] **AC-1**: Platform admin can create a Bedrock entry with `provider="bedrock"`, `endpoint_url`, bearer token, and ARN `model_name`. Entry saved in Draft with encrypted token.
- [ ] **AC-2**: Test harness (`POST /{id}/test`) on a Bedrock entry executes 3 prompts, returns valid token counts, latency, and cost via `_calculate_test_cost()`.
- [ ] **AC-3**: Publish (`POST /{id}/publish`) succeeds after test pass. Publish gate requires `api_key_encrypted`, `endpoint_url`, `last_test_passed_at`. `api_version` NOT required.
- [ ] **AC-4**: Bearer token encrypted via Fernet before storage. NEVER in any API response, log, or error message. Only `key_present` and `api_key_last4` exposed.
- [ ] **AC-5**: Existing azure_openai, openai_direct, and anthropic entries completely unaffected. All existing tests pass without modification.
- [ ] **AC-6**: Alembic migration adds `"bedrock"` to provider CHECK constraint. Migration is idempotent (IF EXISTS guards).
- [ ] **AC-7**: SSRF validation (`_assert_endpoint_ssrf_safe()`) runs on Bedrock endpoint URLs before test execution.
- [ ] **AC-8**: Frontend provider selector includes "AWS Bedrock". Form shows endpoint_url (required), bearer token (labeled "AWS Bearer Token"), model ARN. `api_version` hidden.
- [ ] **AC-9**: Bedrock test failure (expired token, wrong ARN, 429 rate limit, network error) returns clear 502 with human-readable message, not raw AWS exception.

### Should Pass (Non-Blocking)

- [ ] **AC-10**: Region derivable from endpoint_url and displayed in frontend as badge (e.g., "ap-southeast-1").
- [ ] **AC-11**: `InstrumentedLLMClient` routes tenant queries through Bedrock when assigned a Published Bedrock entry.
- [ ] **AC-12**: Unit test for `extract_bedrock_region()` covers standard URLs, VPC endpoints, malformed URLs.

---

## 16. Implementation Phases

### Phase 1: Schema + Backend (2 days)

1. Alembic migration: expand provider CHECK constraint.
2. Add `"bedrock"` to `_VALID_PROVIDERS` frozenset in routes.py.
3. Add `elif provider == "bedrock"` branch in `_run_single_test_prompt()` using `AsyncOpenAI(base_url={url}/v1)`.
4. Add Bedrock publish validation: require `endpoint_url`, skip `api_version`.
5. Add `extract_bedrock_region()` utility.
6. Add Bedrock adapter branch in `InstrumentedLLMClient`.

### Phase 2: Frontend (1 day)

1. Add "AWS Bedrock" to provider selector.
2. Conditional fields: endpoint_url required, api_version hidden, token labeled "AWS Bearer Token", model labeled "Model ARN".
3. Region badge derived from endpoint_url via client-side regex.

### Phase 3: Tests (1 day)

1. Unit: `extract_bedrock_region()` -- standard URLs, VPC endpoints, malformed.
2. Unit: Bedrock cost calculation (reuses `_calculate_test_cost()`).
3. Integration: create + test + publish lifecycle (requires live Bedrock endpoint).

---

## 17. Cross-References

- LLM Library routes: `src/backend/app/modules/platform/llm_library/routes.py`
- Crypto utilities: `src/backend/app/core/crypto.py`
- Schema migration (base): `src/backend/alembic/versions/v009_llm_library.py`
- Schema migration (credentials): `src/backend/alembic/versions/v049_llm_library_credentials.py`
- Instrumented client: `src/backend/app/core/llm/instrumented_client.py`
- Test harness tests: `src/backend/tests/unit/test_llm_library_test_harness.py`
- Bedrock reference config: `workspaces/mingai/bedrock.md`
- LLM Library redesign: `workspaces/mingai/01-analysis/01-research/53-llm-library-redesign-analysis.md`
