# Bedrock Provider — User Flows

**Date**: 2026-03-22
**Research ref**: `01-research/54-bedrock-provider-analysis.md`
**Plan ref**: `02-plans/16-bedrock-provider-plan.md`
**Actor**: Platform Admin

---

## Flow 1 — Add a Bedrock Model Entry (Happy Path)

**Goal**: Platform admin registers a new AWS Bedrock inference profile as a publishable LLM Library entry.

```
1. Platform Admin navigates to Platform > LLM Library
2. Clicks "New Entry"
3. LibraryForm opens

4. Selects provider: "AWS Bedrock"
   → api_version field hides (not required for Bedrock)
   → New fields appear:
      - "Bedrock Base URL"
      - "AWS Bearer Token" (password input)
      - model_name hint updates: "Enter the full ARN, e.g. arn:aws:bedrock:..."

5. Fills in:
   - Display Name:       "Claude 3.5 Sonnet (Bedrock AP)"
   - Bedrock Base URL:   https://bedrock-runtime.ap-southeast-1.amazonaws.com
   - AWS Bearer Token:   ABSK... [pasted, masked after focus-out]
   - Model ARN:          arn:aws:bedrock:ap-southeast-1:106056766526:application-inference-profile/6wbz52t5c3rz
   - Plan Tier:          Professional
   - Price (in/out):     $0.003 / $0.015 per 1K tokens

6. Clicks "Save Draft"
   → Entry created with status = Draft
   → api_key_last4 shown: "****...rT0="
   → api_version field absent from saved entry (null, not displayed)

7. Clicks "Test Connectivity"
   → Backend: decrypts bearer token → constructs BedrockProvider → sends 3 test prompts
   → UI shows per-prompt results:
      Prompt 1: ✓  "Hello" → 12 tokens in / 8 out  45ms  ~$0.00
      Prompt 2: ✓  "What is 2+2?" → 18 tokens in / 4 out  38ms  ~$0.00
      Prompt 3: ✓  [longer prompt] → 45 tokens in / 120 out  210ms  ~$0.00
   → Banner: "All tests passed. Entry is ready to publish."
   → last_test_passed_at recorded server-side

8. Clicks "Publish"
   → Publish gate runs (server-side):
      ✓ model_name set (valid ARN prefix)
      ✓ endpoint_url set
      ✓ api_key_encrypted not null
      ✓ pricing set
      ✓ last_test_passed_at not null
   → Status transitions: Draft → Published
   → Entry appears in tenant-facing library picker
```

---

## Flow 2 — Region Mismatch Detection

**Goal**: Admin enters an endpoint URL whose region does not match the model ARN's region.

```
1. Admin selects provider "AWS Bedrock"
2. Fills in:
   - Bedrock Base URL:  https://bedrock-runtime.us-east-1.amazonaws.com
   - Model ARN:         arn:aws:bedrock:ap-southeast-1:...:application-inference-profile/...
   (regions differ: us-east-1 vs ap-southeast-1)

3. Clicks "Save Draft"

4. Backend extracts:
   - URL region:  us-east-1   (from hostname)
   - ARN region:  ap-southeast-1  (from ARN segment 4)
   → Mismatch detected

5. Returns 422:
   "Region mismatch: endpoint_url is 'us-east-1' but model identifier is 'ap-southeast-1'"

6. Admin corrects the endpoint URL to ap-southeast-1 → Save succeeds
```

**Note**: Model names that are not ARNs (e.g. `anthropic.claude-3-sonnet-20240229-v1:0`) skip region cross-validation — there is no region to extract. Those are validated by the test harness only.

---

## Flow 3 — Connectivity Test Failure (Invalid/Expired Token)

**Goal**: Admin saves a Bedrock entry but the bearer token is expired or has insufficient permissions.

```
1. Admin saves valid-looking Draft (ARN + URL + token all present)
2. Clicks "Test Connectivity"

3. Backend: decrypts token → constructs BedrockProvider → fires first test prompt
   → Bedrock runtime returns 403 Unauthorized (or 401)
   → test harness catches exception

4. UI shows test result:
   Prompt 1: ✗  "403 — Access denied. Check that the bearer token is valid and scoped to this inference profile."
   Prompts 2 & 3: skipped

5. Banner: "Test failed. Fix the credentials and run the test again before publishing."
6. "Publish" button remains disabled (last_test_passed_at is null)

7. Admin updates bearer token via PATCH (re-enters in API Key field)
   → api_key_encrypted updated, api_key_last4 updated
   → last_test_passed_at RESET TO NULL (credential changed — prior test no longer valid)
   → "Publish" button becomes disabled again

8. Admin re-runs test with new token → passes → Publish enabled again
```

---

## Flow 4 — Publish Gate Rejection (Missing Endpoint)

**Goal**: Admin attempts to publish a Bedrock entry that was saved without an endpoint URL (edge case — form should prevent this, but server enforces it too).

```
1. Admin has a Draft Bedrock entry somehow missing endpoint_url
2. Clicks "Publish"

3. Backend publish gate:
   provider == "bedrock" → check endpoint_url → null → reject

4. Returns 422:
   "Bedrock entries require endpoint_url (BEDROCK_BASE_URL)"

5. UI shows error toast:
   "Cannot publish: Bedrock Base URL is required. Edit the entry to add it."

6. Admin edits entry → adds endpoint_url → re-publishes → succeeds
```

---

## Flow 5 — View Existing Bedrock Entry

**Goal**: Admin views a previously published Bedrock entry from the library list.

```
1. Admin opens LLM Library
2. Sees entry: "Claude 3.5 Sonnet (Bedrock AP)" | AWS Bedrock | Published | ★ Recommended

3. Clicks to open detail / edit:
   - Provider:        AWS Bedrock
   - Bedrock Base URL: https://bedrock-runtime.ap-southeast-1.amazonaws.com
   - AWS Bearer Token: ****...rT0=  (masked, last4 shown)
   - Model ARN:       arn:aws:bedrock:ap-southeast-1:...:application-inference-profile/6wbz52t5c3rz
   - API Version:     (not shown — not applicable for Bedrock)
   - Last Tested:     2026-03-22 14:32 UTC  ✓

4. Admin can:
   - Update bearer token (re-enter → re-test required before republish)
   - Deprecate the entry
   - Re-run test (without deprecating)
```

---

## Flow 6 — Bearer Token Rotation (Token Expired)

**Goal**: A previously published Bedrock entry starts failing because the bearer token has expired.

```
1. Tenant reports: Bedrock-powered queries returning errors
2. Platform Admin navigates to LLM Library → finds the entry
3. Sees: Last Tested: 2026-03-15 (7 days ago)
4. Runs test → Prompt 1: ✗  "403 — Token expired"

5. Admin obtains new bearer token from AWS console
6. Edits entry → pastes new token in "AWS Bearer Token" field → saves
   → api_key_encrypted updated
   → api_key_last4 updated (new token's last 4 chars)
   → last_test_passed_at RESET TO NULL (new credential must be re-verified)
   → Entry remains Published — tenants are not disrupted by the save itself

7. Runs test again → all prompts pass → last_test_passed_at updated to now

8. Entry continues serving tenants with new token

**Note**: The entry stays Published during rotation. Only `last_test_passed_at` is cleared on PATCH — the entry's Published status is not reverted to Draft. However, if the token is wrong, the next tenant query will fail. Run the test immediately after saving the new token.
```

**Note**: The entry remains Published through the token rotation — there is no Draft transition required. Only the credential is updated in-place.

---

## Edge Cases

| Scenario                                                             | Behaviour                                                                                           |
| -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Admin selects Bedrock but leaves model name blank                    | Form-level required field validation blocks save                                                    |
| Admin enters ARN with mismatched region vs endpoint URL              | Server rejects on save: "Region mismatch: endpoint_url is 'X' but model identifier is 'Y'"          |
| Admin enters non-ARN model ID (e.g. `anthropic.claude-3-sonnet-...`) | Accepted on save — no prefix validation (ADR-5); test harness validates existence                   |
| Admin submits empty bearer token                                     | Form-level required field validation blocks save                                                    |
| Two entries point to same model name, different tokens               | Both valid — entries are independent                                                                |
| Deprecating a Published Bedrock entry                                | Same as any other provider — status → Deprecated; tenant assignment checks surface affected tenants |
