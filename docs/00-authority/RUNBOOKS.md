# Platform Operations Runbooks

Operational procedures for platform admins managing the mingai platform.

---

## RB-001: LLM Library — Credentialize Existing Published Entries

**Applies to**: Any `llm_library` entries that were created before migration `v049` (which added credential columns). These entries have `key_present = false`, `endpoint_url = null`, `api_version = null`, and cannot be connectivity-tested.

After v049, the 3 entries from the initial setup are in this state:

- `aihub2-main` (Primary Chat, Published)
- `intent5` (Intent Detection, Published)
- `text-embedding-3-large` (Document Embedding, Published)

These entries are still **Published** and visible to tenants — the migration is non-destructive. However, the test endpoint will return 422 for them until credentials are added.

### Step 1: Identify uncredentialed entries

```bash
curl -s https://api.mingai.dev/api/v1/platform/llm-library?status=Published \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.[] | select(.key_present == false) | {id, display_name, provider, model_name}'
```

Note the `id` of each entry that needs credentials.

### Step 2: Add credentials (PATCH)

**For `azure_openai` entries** (e.g. `aihub2-main`, `intent5`):

```bash
curl -X PATCH https://api.mingai.dev/api/v1/platform/llm-library/{ENTRY_ID} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "endpoint_url": "https://ai-cloudappintegrum8776ai770723526188.cognitiveservices.azure.com/",
    "api_key": "YOUR_AZURE_OPENAI_KEY",
    "api_version": "2024-12-01-preview"
  }'
```

Verify the response shows `key_present: true` and `api_key_last4` matching the last 4 chars of your key.

**For non-Azure entries** (e.g. `openai_direct`, `anthropic`):

```bash
curl -X PATCH https://api.mingai.dev/api/v1/platform/llm-library/{ENTRY_ID} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "YOUR_API_KEY"}'
```

### Step 3: Verify credentials stored

```bash
curl https://api.mingai.dev/api/v1/platform/llm-library/{ENTRY_ID} \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{key_present, api_key_last4, endpoint_url, api_version}'
```

Expected output:

```json
{
  "key_present": true,
  "api_key_last4": "qaN9",
  "endpoint_url": "https://ai-cloudappintegrum8776ai770723526188.cognitiveservices.azure.com/",
  "api_version": "2024-12-01-preview"
}
```

### Step 4: Run connectivity test

```bash
curl -X POST https://api.mingai.dev/api/v1/platform/llm-library/{ENTRY_ID}/test \
  -H "Authorization: Bearer $TOKEN"
```

Expected response:

```json
{
  "all_passed": true,
  "last_test_passed_at": "2026-03-21T10:30:00Z",
  "tests": [
    {"passed": true, "latency_ms": 342, ...},
    {"passed": true, "latency_ms": 289, ...},
    {"passed": true, "latency_ms": 310, ...}
  ]
}
```

If `all_passed` is `false`, check the `error` field on each failed test for the specific error message from the Azure API (e.g. `"Deployment 'aihub2-main' not found"`).

### Step 5: Repeat for each entry

Repeat Steps 2–4 for each uncredentialed entry. Note that:

- These entries are already **Published** — no re-publish step is required.
- `last_test_passed_at` is set on the Published entry after a successful test.
- The test endpoint works identically for all statuses except `Deprecated`.

### Notes

- The PATCH endpoint allows credential updates on **Published** entries (not just Draft). The only status that blocks PATCH is `Deprecated`.
- Updating `api_key`, `endpoint_url`, or `api_version` clears `last_test_passed_at` (stale test invalidation). Always re-run the test after any credential change.
- If you change the key, the old `api_key_last4` is replaced with the last 4 chars of the new key.

---

## RB-002: LLM Library — Rotate API Key for an Entry

When an Azure OpenAI key is rotated:

1. PATCH the entry with the new key:

   ```bash
   curl -X PATCH https://api.mingai.dev/api/v1/platform/llm-library/{ENTRY_ID} \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"api_key": "NEW_API_KEY"}'
   ```

2. Run the test to verify the new key works:

   ```bash
   curl -X POST https://api.mingai.dev/api/v1/platform/llm-library/{ENTRY_ID}/test \
     -H "Authorization: Bearer $TOKEN"
   ```

3. Verify `last_test_passed_at` is updated in the response.

**Note**: If the same key is used in multiple entries, each must be PATCHed individually.
