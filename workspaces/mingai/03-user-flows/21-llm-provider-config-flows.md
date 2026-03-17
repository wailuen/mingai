# 21 — LLM Provider Credentials Management — User Flows

**Generated**: 2026-03-17
**Feature**: Platform LLM Provider Credentials Management (PVDR)
**Related plan**: `02-plans/11-llm-provider-config-plan.md`
**Related todos**: `todos/active/08-llm-provider-config.md`

---

## Flow Index

| #    | Flow                                                  | Actor                   | Trigger                             |
| ---- | ----------------------------------------------------- | ----------------------- | ----------------------------------- |
| F-01 | First login / bootstrap — env fallback active         | Platform Admin          | First deployment                    |
| F-02 | Add first provider                                    | Platform Admin          | Bootstrap banner CTA                |
| F-03 | Rotate API key (zero-downtime)                        | Platform Admin          | Key expiry / security rotation      |
| F-04 | Enable / disable a provider                           | Platform Admin          | Maintenance or provider outage      |
| F-05 | Set a new default provider                            | Platform Admin          | Provider switch / cost optimisation |
| F-06 | Add Anthropic provider (no embedding)                 | Platform Admin          | Adding Claude support               |
| F-07 | Tenant Admin views available providers                | Tenant Admin            | Exploring LLM options               |
| F-08 | Tenant Admin selects a provider                       | Tenant Admin            | Switching to a specific provider    |
| F-09 | Error flows — bad credentials, outage, health failure | Platform / Tenant Admin | Misconfiguration / provider outage  |

---

## F-01: Platform Admin First Login / Bootstrap Flow

### Actor

Platform Admin

### Preconditions

- `llm_providers` table has zero rows
- `AZURE_PLATFORM_OPENAI_API_KEY`, `AZURE_PLATFORM_OPENAI_ENDPOINT`, `PRIMARY_MODEL` are set in `.env`
- Server has started and `seed_llm_provider_from_env()` has already run (seeds one default row)

### Scenario A: Bootstrap Seed Succeeded (env vars present)

1. Platform Admin logs in and lands on the Platform Admin Dashboard.
2. Dashboard `llm_providers` health widget shows: `1 provider | unchecked | seeded from env`.
3. Platform Admin navigates to **Operations → Providers** (new nav item in Platform Admin sidebar).
4. Provider List page renders with a **yellow bootstrap banner** at the top:
   - Title: "Running on environment fallback"
   - Body: "Platform LLM credentials are being read from .env. Add a provider above to move credentials into the database and enable rotation without restarting the server."
5. The table shows the auto-seeded row: display_name "Platform Azure OpenAI (seeded from env)", status "unchecked", is_default checkmark.
6. Health check job fires within 10 minutes; status transitions to "healthy" (accent green) or "error" (alert orange).
7. Platform Admin can click **Edit** on the seeded row to rename it, add description, fill missing slots, or update the API key.
8. After editing and saving, the banner remains visible until Platform Admin dismisses it or the server config note is updated (banner is informational only — the system is fully operational).
9. Platform Admin clicks **×** to dismiss the banner. Dismissal stored in localStorage. Banner does not reappear until a new deployment.

**Expected result**: System is fully operational. Real API calls use the DB-backed provider. Env vars are now redundant but remain as break-glass.

### Scenario B: Bootstrap Seed Skipped (env vars absent or partial)

1. Platform Admin logs in.
2. Dashboard shows a **red alert widget**: "No LLM provider configured — system cannot process chat requests."
3. Platform Admin navigates to Providers.
4. Table is empty. Bootstrap banner is shown with an elevated alert style (orange instead of yellow):
   - Title: "No provider configured"
   - Body: "Chat, embeddings, and intent detection are non-functional. Add a provider to restore service."
5. "Add Provider" button is visually prominent with an accent ring indicator.
6. Flow continues to F-02.

**Expected result**: System gracefully shows error state. No silent failures. Chat endpoint returns 503 with `"detail": "LLM provider not configured"` until a provider is added.

### Error Handling

- Server restart without env vars and without DB providers: startup completes (no crash), first chat request returns 503 with `"LLM provider not configured"`.
- Partial env vars (key present, endpoint absent): bootstrap seed skipped, warning logged. Scenario B applies.

---

## F-02: Platform Admin Adds First Provider

### Actor

Platform Admin

### Preconditions

- User is on the Providers page (from F-01 or direct navigation)
- User has the Azure OpenAI endpoint URL and API key ready

### Steps

**Step 1 — Open the Add Provider form**

1. Click **"Add Provider"** button (top-right of Provider List page).
2. A modal dialog opens (`max-width: 640px`). Progress bar at top shows "Step 1 of 2".
3. Step 1 header: "Provider Identity"

**Step 2 — Fill Provider Identity (Step 1 of form)**

4. Enter `display_name`: e.g. "Azure OpenAI (Southeast Asia)".
5. Select `provider_type`: "azure_openai" from dropdown.
6. The **Azure Endpoint URL** field appears (conditionally shown for azure_openai only). Enter: `https://agentic-openai01.cognitiveservices.azure.com/`.
7. Enter `api_key` in password field (characters masked). Field label: "API Key".
8. Optionally fill `description`: "Primary production endpoint, Southeast Asia region."
9. `api_version` field appears (azure_openai only), pre-filled with `2024-02-01`. Leave as-is.
10. `is_default` toggle shown (this is the first provider, so it is auto-checked and labelled "Will be set as default (no other providers exist)").
11. Click **"Next →"**. Client-side validation runs:
    - display_name: required ✓
    - provider_type: selected ✓
    - endpoint: required for azure_openai ✓
    - api_key: required, min 1 char ✓
    - If any fail: inline red error messages, no navigation.
12. Progress bar advances to Step 2 of 2.

**Step 3 — Configure Slot Mappings (Step 2 of form)**

13. SlotMappingGrid renders 6 slot rows:

    | Slot            | Label                    | Input      |
    | --------------- | ------------------------ | ---------- |
    | primary         | Chat synthesis           | text input |
    | intent          | Intent detection         | text input |
    | vision          | Image analysis           | text input |
    | doc_embedding   | Document vectors         | text input |
    | kb_embedding    | Legacy KB vectors        | text input |
    | intent_fallback | Circuit breaker fallback | text input |

    All 6 slots are active (azure_openai supports all).

14. Fill `primary` slot: `agentic-worker`.
15. Fill `intent` slot: `agentic-router`.
16. Fill `doc_embedding` slot: `text-embedding-3-small`.
17. Optionally fill remaining slots.

**Step 4 — Test Connectivity**

18. Click **"Test Connectivity"** button (in Step 2 footer, left of Save).
19. Button shows spinner. POST sent to `/api/v1/platform/providers` with `dry_run: true` flag, OR test uses the already-created provider ID if PA is in edit mode.
    - On success: green checkmark + latency badge, e.g. "Connected — 312ms".
    - On failure: red X + error message, e.g. "Authentication failed — check API key."
20. Test result is inline — no navigation, no modal close.

**Step 5 — Save**

21. Click **"Save →"**.
22. POST `/api/v1/platform/providers` sent with all fields. `api_key` encrypted server-side before DB write.
23. Modal closes. Provider List refreshes.
24. New row appears in table: "Azure OpenAI (Southeast Asia)" | azure_openai | unchecked → healthy | default ✓ | primary, intent, doc_embedding chips.
25. If this was the bootstrap scenario, the yellow banner is replaced with an info message: "Provider added successfully. System is now using database-backed credentials." (dismissable).

**Expected result**: One `llm_providers` row in DB with encrypted key. `is_default=true`. Chat and embeddings now route through this provider. Env var fallback no longer active.

### Error Handling

- Duplicate default: impossible — only one provider exists. If somehow two concurrent creates both set `is_default=true`, the DB partial unique index returns a conflict error; backend returns 409 "Only one default provider allowed."
- Network timeout during test: inline error "Connection timed out (30s). Check endpoint URL."
- Test passes but Save fails (e.g. DB write error): error toast "Failed to save provider. Please try again."

---

## F-03: Platform Admin Rotates API Key (Zero-Downtime)

### Actor

Platform Admin

### Preconditions

- At least one provider exists in the table with an active API key
- Old key is expiring or has been compromised
- New key has been issued by the provider

### Steps

1. Navigate to **Operations → Providers**.
2. Locate the provider row in the table. Click **"Edit"** (pencil icon in Actions column).
3. Edit modal opens in single-step mode. All fields are pre-populated from the existing row.
4. `api_key` field shows placeholder text: "Leave blank to keep existing key". Field is empty.
5. Platform Admin pastes the new API key into the field.
6. Optionally update `display_name` or `description` to note the rotation date.
7. Click **"Test Connectivity"** to verify the new key before saving.
   - If test fails: inline error. Old key is NOT overwritten yet (no write has occurred).
   - If test succeeds: green checkmark + latency.
8. Click **"Save Changes"**. PATCH request sent. Backend logic:
   - `api_key` field is present in payload → encrypt new key → overwrite `api_key_encrypted` in DB
   - All other fields updated
   - Commit in single transaction
9. Modal closes. Table refreshes. Provider status remains "healthy".

**Zero-downtime guarantee**: The old key remains active in DB until the PATCH commit succeeds. In-flight requests using the old key complete normally. The next request after the PATCH uses the new key.

**Expected result**: `api_key_encrypted` in DB now contains the new Fernet-encrypted key. Old key discarded. No restart required. No interruption to active tenants.

### Error Handling

- New key is invalid (test fails): Platform Admin sees test error inline. Old key preserved. No DB write.
- PATCH fails mid-transaction: PostgreSQL atomicity ensures old key is preserved. Error toast shown.
- Platform Admin leaves `api_key` empty: PATCH payload omits the `api_key` field. Backend preserves existing encrypted key (no overwrite).
- Platform Admin accidentally pastes same key: no harm — encrypted value changes (new Fernet token, same underlying key) but decryption works identically.

---

## F-04: Platform Admin Enables / Disables a Provider

### Actor

Platform Admin

### Preconditions

- Multiple providers exist in the table
- Provider to be disabled is NOT the only enabled provider

### Disabling a Provider

1. Navigate to **Operations → Providers**.
2. Locate the provider row. The row shows `is_enabled: true` (no explicit column — represented by active status badge).
3. Click **"Edit"** on the provider.
4. Toggle `is_enabled` switch to Off.
5. If the provider `is_default=true`, an inline warning appears:
   - "This is the current default provider. Disabling it will break chat for tenants with no explicit provider selection. Set another provider as default first."
   - The Save button is disabled until user acknowledges or changes selection.
6. If the provider is NOT the default, click **"Save Changes"**.
7. Provider row in table shows greyed-out status badge: "disabled".

**Impact on tenants**:

- Tenants with no explicit selection: fallback to the default provider (unaffected if this is not the default).
- Tenants with an explicit selection pointing to this provider: `InstrumentedLLMClient` detects `is_enabled=false`, falls back to default provider, logs `"tenant_provider_disabled_fallback"` warning.
- No error is surfaced to the end user — chat continues via default provider.
- Tenant Admin will see the selected provider's health dot turn grey ("disabled") in their LLM Settings page.

### Re-enabling a Provider

1. Click **"Edit"** on the disabled provider row.
2. Toggle `is_enabled` to On.
3. Click **"Save Changes"**.
4. Provider immediately eligible for use. Health check job will ping it within 10 minutes.
5. Tenants who had this provider selected will have their requests route through it again on next request.

### Error Handling

- Attempt to disable the only enabled provider: API returns 409 "Cannot disable the only active provider." Save button client-side check prevents submission (disable Save if this is the last enabled provider).
- Disable and re-enable race condition: Idempotent — toggling enabled/disabled is a simple boolean update, no index constraint.

---

## F-05: Platform Admin Sets a New Default Provider

### Actor

Platform Admin

### Preconditions

- At least 2 providers exist, both enabled
- One is currently `is_default=true` (call it Provider A)
- Platform Admin wants Provider B to become the new default

### Steps

1. Navigate to **Operations → Providers**.
2. Locate Provider B row. The "Default" column shows a dash (not default).
3. Click **"Set Default"** in Provider B's Actions column.
4. Confirmation dialog appears:
   - "Set 'Provider B Name' as the platform default?"
   - "Tenants using the platform default (not a specific selection) will switch to this provider immediately."
   - [Cancel] [Confirm]
5. Click **"Confirm"**. POST `/api/v1/platform/providers/{id}/set-default`.
6. Backend executes two-step atomic update:
   - UPDATE: clear `is_default` on all rows (`SET is_default = false WHERE is_default = true`)
   - UPDATE: set `is_default = true WHERE id = {B.id}`
   - Single commit.
7. Table refreshes. Provider A row: Default column shows dash. Provider B row: Default column shows green checkmark.
8. Success toast: "Default provider updated to 'Provider B Name'."

**Impact on tenants**:

- Tenants with no explicit selection: next request routes through Provider B. No restart.
- Tenants with an explicit selection: unaffected — their selection overrides the default.
- Tenants who had Provider A explicitly selected: still use Provider A (their selection is not changed by this operation).

### Error Handling

- Setting already-default provider as default: API is idempotent (no-op). No error, no toast.
- Provider B is disabled: API returns 422 "Cannot set a disabled provider as default. Enable it first." Client-side: "Set Default" button hidden for disabled providers.
- Concurrent set-default race: DB partial unique index ensures only one row can have `is_default=true`. Second concurrent request will see a unique index violation; API returns 409, client shows retry toast.

---

## F-06: Platform Admin Adds Anthropic Provider (No Embedding)

### Actor

Platform Admin

### Preconditions

- At least one Azure OpenAI provider with `doc_embedding` slot configured already exists (required for embedding fallback)
- Platform Admin has an Anthropic API key ready

### Steps

1. Navigate to **Operations → Providers**. Click **"Add Provider"**.
2. Step 1 — Provider Identity:
   - `display_name`: "Anthropic Claude 3.7"
   - `provider_type`: "anthropic" (selected from dropdown)
   - **Endpoint field disappears** — Anthropic is key-based only, no endpoint URL.
   - `api_key`: paste Anthropic key (format: `sk-ant-...`).
   - `description`: "Anthropic Claude for primary chat synthesis."
   - `is_default`: leave off (Azure OpenAI is still default for now)
3. Click **"Next →"**.
4. Step 2 — Slot Mapping:
   - `primary` slot: text input active. Enter: `claude-3-7-sonnet-20250219`.
   - `intent` slot: text input active. Enter: `claude-3-5-haiku-20241022` (optional — Anthropic intent).
   - `vision`, `doc_embedding`, `kb_embedding`, `intent_fallback`: **greyed-out inputs** with tooltip "Not supported by anthropic". Cannot be typed in.
5. An **inline info banner** appears below the slot grid:
   - Icon: info circle (text-muted)
   - "Anthropic does not support text embeddings. The platform will automatically fall back to your configured Azure OpenAI or OpenAI provider for document indexing. Ensure an embedding-capable provider is active."
6. Click **"Test Connectivity"**. Backend tests with a 1-token completion request. Success: green checkmark.
7. Click **"Save →"**.
8. Provider row appears in table with slot chips: `primary`, `intent`. No embedding chips.

**What happens at chat time with Anthropic as primary:**

- `InstrumentedLLMClient.complete()`: routes through Anthropic adapter, using `claude-3-7-sonnet-20250219`.
- `InstrumentedLLMClient.embed()`: `_resolve_embedding_fallback_adapter()` called, finds Azure OpenAI `doc_embedding` slot, uses `text-embedding-3-small`. Tenant never sees this routing — it is transparent.

**Setting Anthropic as default (advanced scenario):**

- Platform Admin clicks "Set Default" on the Anthropic provider row.
- Confirmation dialog shows additional note: "Note: Anthropic does not support embeddings. The platform will use your Azure OpenAI provider (Platform Azure OpenAI (Southeast Asia)) for document indexing automatically."
- On confirm: Anthropic becomes default. Embed calls route to Azure OpenAI fallback.
- If the Azure OpenAI embedding provider is later deleted or disabled, embed calls will fail with a clear error. Dashboard will show an alert.

### Error Handling

- No embedding-capable fallback provider exists: "Test Connectivity" succeeds, but saving is still allowed (the test only checks completion, not embedding). A warning banner on the Providers list reads: "Anthropic is the default provider but no Azure OpenAI / OpenAI provider with doc_embedding is configured. Document indexing will fail."
- Anthropic key format validation: if key doesn't start with `sk-ant-`, show inline warning: "This does not look like an Anthropic API key. Proceed with caution." (not a hard block — format validation is advisory only).

---

## F-07: Tenant Admin Views Available Providers

### Actor

Tenant Admin

### Preconditions

- Platform Admin has configured at least one enabled provider
- Tenant Admin is logged in to their tenant workspace

### Steps

1. Tenant Admin navigates to **Settings → LLM** in Tenant Admin sidebar.
2. The LLM Settings page loads. The top section is "Platform Provider" (new, above the existing Library Mode section).
3. The section shows a list of available providers fetched from `GET /admin/llm-config/providers`.
4. Each provider item shows:
   - Display name (Plus Jakarta Sans 500)
   - Provider type chip (DM Mono, e.g. `azure_openai`)
   - Health status dot: green (healthy), orange (error), grey (unchecked)
   - "Default" badge when `is_default=true`
5. Credentials (API key, endpoint) are NOT shown — Tenant Admin sees capability information only.
6. "Slots available" for each provider is shown as small chips: `primary`, `intent`, `doc_embedding`, etc.
7. If the Tenant Admin's tenant has no explicit selection, the default provider shows a highlight: "Currently using this provider (platform default)".

**What the Tenant Admin CANNOT see:**

- API keys (encrypted or plaintext)
- Azure endpoint URLs
- Internal provider IDs in readable form (only used as values in the PATCH request)

**Expected result**: Tenant Admin has informed choice — knows which providers are available, healthy, and what capabilities each has. Cannot exfiltrate platform credentials.

### Error Handling

- All providers are disabled: section shows empty state "No providers available. Contact your platform administrator."
- All providers are in error state: each shows orange dot. Tenant Admin cannot fix this — contact PA message shown.

---

## F-08: Tenant Admin Selects a Provider

### Actor

Tenant Admin

### Preconditions

- Multiple providers are enabled (at least 2)
- Tenant Admin wants their workspace to use a specific provider rather than the platform default

### Steps

1. On LLM Settings → Platform Provider section (from F-07).
2. Tenant Admin sees the list. The current default provider shows "Currently using (platform default)".
3. Tenant Admin clicks a different provider option (radio-style selection, accent border on selected).
4. If the selected provider has no embedding support (e.g. Anthropic): an inline info note appears:
   - "This provider does not support embeddings. The platform will automatically use an Azure OpenAI provider for document indexing."
5. The UI optimistically marks the selection. PATCH `/admin/llm-config/provider` sent with `{"provider_id": "uuid"}`.
6. On success: toast "Provider updated. Your workspace now uses [Provider Name]."
7. The selected provider item shows highlight + "Currently using" label.

**Effect on workspace**:

- Next chat request by any user in this tenant routes through the selected provider.
- Document indexing still uses the appropriate embedding slot (fallback if Anthropic selected).
- Conversation quality/latency reflects the new provider starting from the next message.

### Reverting to Platform Default

8. Tenant Admin clicks the "Reset to platform default" link (small text below the provider list).
9. PATCH sent with `{"provider_id": null}`. Backend deletes the `llm_provider_selection` row from `tenant_configs`.
10. "Currently using (platform default)" label returns to the default provider item.
11. Toast: "Reset to platform default."

### Error Handling

- Selected provider has become disabled since the list loaded: PATCH returns 422 "Provider is not enabled." Toast error. UI refreshes list — disabled provider no longer shown.
- Selected provider_id not found: 404. Toast error. UI refreshes.
- Network failure: optimistic UI reverts. Error toast.

---

## F-09: Error Flows

### E-01: Bad API Key at Provider Creation

**Trigger**: Platform Admin enters an incorrect API key when creating a provider.

**Flow**:

1. PA fills form and clicks "Test Connectivity".
2. Backend: decrypts the key (in the create case, no decryption needed yet — key is in the request body), makes a real API call.
3. Provider returns 401 Unauthorized.
4. `test_connectivity()` returns `(False, "Authentication failed — check API key")`.
5. Backend returns `{success: false, latency_ms: 850, error: "Authentication failed — check API key"}`.
6. Frontend shows inline error: red X icon + "Authentication failed — check API key".
7. **The form does NOT close.** PA corrects the key and can retry.
8. If PA clicks "Save →" without testing (or after a failed test): save proceeds. Provider saved with bad key. Provider status will show "error" after health check runs.

**Key invariant**: Error message never echoes the API key value back to the user, even partially.

### E-02: Provider Outage During Normal Operation

**Trigger**: An enabled, healthy provider's upstream service becomes unavailable.

**Flow**:

1. Health check job fires (every 10 minutes). `test_connectivity()` times out or returns 500.
2. `provider_status` updated to "error". `health_error` column set to "Connection timeout after 30s".
3. Platform Dashboard health widget turns orange. Alert widget shows: "1 provider in error state."
4. If the erroring provider is the default: an alert is surfaced on the Platform Dashboard under "Active Alerts".
5. PA navigates to Providers. The row shows orange "error" badge.
6. PA clicks "Test" button to re-check manually.
7. If still failing: PA can disable the provider (F-04) and set another as default (F-05).
8. Chat during outage:
   - Tenants on default provider: requests will fail with 502 (provider error). Circuit breaker (existing `circuit_breaker.py`) may kick in if configured, routing to `intent_fallback` slot.
   - Tenants with explicit selection to the erroring provider: same 502 behavior.

### E-03: Health Check Failure on Non-Default Provider

**Trigger**: A non-default provider fails health check.

**Flow**:

1. `provider_status` = "error" for non-default provider.
2. PA Dashboard: counter incremented. No critical alert (non-default outage is informational).
3. Tenants who explicitly selected this provider: their chat requests will fail. They see a generic error.
4. Tenant Admin: their LLM Settings page shows orange dot on their selected provider.
5. Tenant Admin clicks "Reset to platform default" (F-08 revert). Resolved.

### E-04: JWT_SECRET_KEY Changed — Encrypted Keys Become Unreadable

**Trigger**: Infrastructure team rotates `JWT_SECRET_KEY` (e.g. after a secret exposure incident).

**Flow**:

1. Server restarts with new `JWT_SECRET_KEY`.
2. On next chat request: `InstrumentedLLMClient._resolve_library_adapter()` calls `ProviderService.decrypt_api_key()`.
3. Fernet throws `InvalidToken` (new key cannot decrypt old ciphertext).
4. Backend logs `"provider_key_decryption_failed"` at ERROR level.
5. Chat endpoint returns 500 to the user. Error message: "LLM provider configuration error. Contact your administrator."
6. PA logs in. PA Dashboard shows critical alert: "Provider key decryption failure."
7. PA navigates to Providers. All providers show "error" status (health check also failed for same reason).
8. PA edits each provider and re-enters the API keys. On Save, keys are re-encrypted with the new JWT_SECRET_KEY-derived Fernet key.
9. After saving all providers: health checks succeed, service restored.

**Prevention**: Document this in the runbook. Offer a startup diagnostic: on boot, attempt to decrypt the first provider's key. If `InvalidToken`, log `"jwt_secret_rotated_provider_rekey_required"` at CRITICAL level and surface it in the dashboard immediately.

### E-05: Attempt to Delete the Only Provider

**Trigger**: PA tries to delete the last remaining provider.

**Flow**:

1. PA clicks "Delete" on the only provider row.
2. Confirmation dialog opens.
3. PA confirms deletion. DELETE request sent.
4. Backend checks: `is_default=true` → 409 "Cannot delete the default provider. Set another provider as default first."
5. Even if `is_default=false`, backend checks: only enabled provider → 409 "Cannot delete the only active provider."
6. Delete button in the UI should be disabled when `is_default=true` (client-side guard), but server-side validation is the authoritative check.
7. Error toast shown. Provider row preserved.

### E-06: Tenant Admin Selects a Provider That Gets Disabled

**Trigger**: Tenant has Provider B selected. PA disables Provider B (F-04).

**Flow**:

1. Tenant user sends a chat message.
2. `InstrumentedLLMClient._resolve_adapter()` reads tenant selection → Provider B.
3. Provider B has `is_enabled=false` in DB.
4. `_resolve_library_adapter()` detects disabled provider, logs `"tenant_provider_disabled_fallback"` warning: `{tenant_id, selected_provider_id, fallback_provider_id}`.
5. Falls back to default provider. Chat request succeeds.
6. End user: no visible error. Chat response appears normally (may have different model characteristics).
7. Tenant Admin: next time they open LLM Settings, their selected provider shows grey "disabled" dot. An inline note: "Your selected provider is currently disabled. Requests are routing through the platform default."
8. Tenant Admin can select a different provider or reset to default.

**Invariant**: Disabled provider selection causes silent fallback, never a 5xx to the end user. Transparency to Tenant Admin via UI status indicator.
