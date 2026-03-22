# LLM Profile Configuration — User Flows (Final)

**Date**: 2026-03-22 (revised post-decisions)
**Research**: `01-research/55-llm-profile-redesign-analysis.md`
**Plan**: `02-plans/17-llm-profile-redesign-plan.md`

---

## Actor Map

| Actor                                      | Surface                           | Capabilities                                                                         |
| ------------------------------------------ | --------------------------------- | ------------------------------------------------------------------------------------ |
| Platform Admin                             | Platform > LLM Profiles           | Create/edit/publish/deprecate profiles, assign slots, set default, assign plan tiers |
| Tenant Admin — Starter                     | Settings > LLM Profile            | View-only                                                                            |
| Tenant Admin — Professional                | Settings > LLM Profile            | Select from available platform profiles                                              |
| Tenant Admin — Enterprise (Platform track) | Settings > LLM Profile            | Select from all platform profiles                                                    |
| Tenant Admin — Enterprise (BYOLLM track)   | Settings > LLM Profile > Advanced | Create own Library entries per slot, build own profile, activate it                  |
| End User                                   | Chat interface                    | Transparent — zero visibility                                                        |

---

## Platform Admin Flows

### PA-0: Add a Model to the Library (Prerequisite for All Profiles)

**Trigger**: Platform admin wants to make a new Azure OpenAI deployment available for profiles.

```
1. Platform Admin opens Platform > LLM Library
   → Clicks [+ Add Model]

2. Fills form:
   Provider: Azure OpenAI
   Display Name: GPT-5.2 East US
   Model Name: gpt-5.2-chat
   Endpoint URL: https://mingai-prod-east.openai.azure.com/
   API Key: [password field]
   API Version: 2024-12-01-preview
   Plan Tier: Enterprise
   Pricing: $2.50 / 1K in · $10.00 / 1K out
   Capabilities: [✓ Streaming] [✓ Vision] [✓ Function Calling] [✓ JSON Mode]
                 Context: 128,000 tokens

3. [Save as Draft] → entry saved, not yet testable from profile

4. [Test Connection] →
   Backend: decrypt key → hit endpoint with 3 canned prompts (parallel)
   Result card appears:
     ✓ All 3 tests passed
     Chat: 842ms · 47 tokens · $0.0006
     Chat: 1,102ms · 63 tokens · $0.0008
     Chat: 788ms · 41 tokens · $0.0005
     Tested: just now

5. [Publish] → entry status becomes Published
   → now assignable to profiles
   → appears in slot selectors

OUTCOME: GPT-5.2 East US is published and eligible for Chat, Vision, Agent slots.
```

---

### PA-1: Create a New Platform Profile

**Trigger**: Platform admin wants to offer an "Economy" profile to Professional tenants.

**Precondition**: At least 3 published Library entries exist (for Chat, Intent, Agent slots).

```
1. Opens Platform > LLM Profiles
   → Profile list table: Name | Chat | Intent | Vision | Agent | Plan Tiers | Tenants

2. Clicks [+ New Profile]
   → Slide-in panel opens (480px, right)

3. Identity section:
   Name: Economy
   Description: Cost-optimised profile for high-volume workspaces.
                Uses economy-tier models across all slots.

4. Slot Assignment section:

   CHAT (required)
   Opens dropdown → searchable list filtered to entries with "chat" in eligible_slots
   Each option shows: model name (DM Mono) · provider badge · health dot · test age
   Admin selects: gpt-5-mini
   → NOTE: "gpt-5-mini has limited context (8K tokens). Consider for short-session workspaces."
   Admin acknowledges.

   INTENT (required)
   Admin selects: gpt-5-mini

   VISION (optional)
   Admin selects: gpt-5.2-chat-vision
   (only vision-capable models appear here)

   AGENT (required)
   Admin selects: gpt-5-mini

5. Plan Availability:
   [✓] Professional  [✓] Enterprise

6. [Create Profile]
   → Validation: name unique ✓, Chat assigned ✓, Intent assigned ✓, Agent assigned ✓
   → Profile created, history snapshot written, audit log entry written
   → Panel closes. Toast: "Profile 'Economy' created."
   → Row appears in list.

OUTCOME: Economy profile available to Professional and Enterprise tenants.
```

**Edge Case — Vision slot assigned deprecated entry**:

```
→ Panel shows warn indicator on Vision slot: "This entry is deprecated.
  It will continue serving but cannot be assigned to new profiles.
  Select a different entry before publishing."
→ [Create Profile] blocked until resolved.
```

---

### PA-2: Update an Existing Profile

**Trigger**: Platform admin wants to upgrade the Intent model in the Standard profile from gpt-5-mini to gpt-4.1-mini.

```
1. Clicks "Standard" row in profile list
   → Detail panel opens with current assignments

2. Opens Intent slot dropdown
   → Selects: gpt-4.1-mini
   → Diff indicator appears: "Intent: gpt-5-mini → gpt-4.1-mini"

3. [Save Changes]
   → History snapshot written (before state preserved)
   → Audit log entry written with diff
   → Cache invalidated for all tenants using Standard profile
   → Toast: "Profile updated"

4. Notification queue: affected tenants receive in-app notification:
   "Your LLM configuration was updated by the platform.
    Intent model: gpt-5-mini → gpt-4.1-mini
    [View LLM Profile]"

OUTCOME: Standard profile updated. All tenants using it get the new Intent model
on their next query. Current in-flight requests complete on the old model.
```

---

### PA-3: Set Platform Default Profile

**Trigger**: Admin wants "Standard" as the platform default for new tenants.

```
1. Opens Standard profile detail panel

2. Clicks ★ star icon in panel header
   → Confirmation:
     "Make 'Standard' the platform default?
      All new tenants and those without a profile selection will use this.
      Currently: 'Legacy' is the default (15 tenants).
      [Cancel] [Set as Default]"

3. Clicks [Set as Default]
   → Previous default loses star
   → Standard gains star (accent color)
   → Cache invalidated for 15 tenants on Legacy default

OUTCOME: New tenants get Standard. Tenants who explicitly selected Legacy are unaffected.
```

---

### PA-4: Rollback a Profile to Previous State

**Trigger**: A model change caused degraded response quality. Admin wants to revert.

```
1. Opens affected profile detail panel
   → Clicks "View History" (link in panel footer)
   → History list appears: timestamps + changedBy + summary of diff

2. Finds the last good snapshot (e.g., 3 versions ago)
   → Clicks [Restore this version]
   → Confirmation: "Restore profile to state from 2 hours ago?
     Chat: gpt-5.2-chat (was gpt-5-mini)
     Intent: gpt-5-mini (unchanged)
     [Cancel] [Restore]"

3. Clicks [Restore]
   → Profile slots reset to snapshot values
   → New history entry written: "Restored from version at [timestamp]"
   → Cache invalidated for all tenants on this profile
   → Toast: "Profile restored to 2026-03-22 14:30"

OUTCOME: All tenants on this profile revert to the previous model assignments
on their next query.
```

---

### PA-5: Deprecate a Library Entry in Use

**Trigger**: Azure is retiring the gpt-5-mini deployment. Admin needs to remove it.

```
1. Opens Platform > LLM Library
   → Finds gpt-5-mini row
   → Clicks "Deprecate"

2. Confirmation:
   "Deprecate 'gpt-5-mini'?
    This entry is assigned to 3 profiles used by 28 tenants.
    Deprecated entries continue serving but cannot be assigned to new profiles.
    You should reassign all affected profiles before disabling.
    [Cancel] [Deprecate]"

3. Admin clicks [Deprecate]
   → Entry status: deprecated (still serving, yellow warning dot)
   → Affected profiles show warn indicator on that slot

4. Admin opens each affected profile → reassigns deprecated slot to new entry
   → After last profile reassigned:
     Admin clicks [Disable] on the deprecated entry
     → Blocked: if any profile still references it → lists them
     → When all clear: entry disabled. No longer serves any request.

OUTCOME: Orderly retirement. Zero tenant disruption if done before disabling.
```

---

## Tenant Admin Flows — Platform Profile Track

### TA-1: Starter — View Active Configuration

```
1. Opens Settings > LLM Profile

   LLM Profile
   ──────────────────────────────────────────────────────────────
   Active Profile: Standard
   Balanced performance for everyday knowledge queries.

   MODEL CONFIGURATION
   CHAT       gpt-5.2-chat          Azure OpenAI    ✓ healthy
   INTENT     gpt-5-mini            Azure OpenAI    ✓ healthy
   VISION     gpt-5.2-chat          Azure OpenAI    ✓ healthy
   AGENT      gpt-5.2-chat          Azure OpenAI    ✓ healthy

   EMBEDDING (platform managed)
   Documents  text-embedding-3-large   Azure OpenAI
   Knowledge  text-embedding-ada-002   Azure OpenAI

   ┌─────────────────────────────────────────────────────────┐
   │ 🔒  Your plan (Starter) uses the platform-assigned     │
   │     profile. Upgrade to Professional to choose from    │
   │     additional profiles.                               │
   └─────────────────────────────────────────────────────────┘

OUTCOME: Full transparency into what's active. Nothing hidden.
Clear upgrade path. No grayed-out controls.
```

---

### TA-2: Professional — Select a Different Profile

**Trigger**: Professional tenant wants to switch from Standard to Economy to reduce costs.

```
1. Opens Settings > LLM Profile
   → Current profile selector shows: Standard (current)

2. Opens profile dropdown:
   ○ Standard (current)
     Balanced performance. ~$0.008/query
   ○ Economy
     Cost-optimised. ~$0.001/query

3. Selects Economy
   → Page updates to show Economy's slot assignments:
     CHAT       gpt-5-mini    Azure OpenAI
     INTENT     gpt-5-mini    Azure OpenAI
     VISION     gpt-5.2-chat  Azure OpenAI
     AGENT      gpt-5-mini    Azure OpenAI

4. [Save] button activates in page header

5. Admin clicks [Save]
   → Confirmation dialog:
     "Switch to Economy profile?
      Chat: gpt-5.2-chat → gpt-5-mini
      Intent: (unchanged)
      Vision: (unchanged)
      Agent: gpt-5.2-chat → gpt-5-mini

      New queries will use Economy. Active sessions unaffected.
      [Cancel] [Switch Profile]"

6. Admin clicks [Switch Profile]
   → Toast: "Profile updated to Economy"
   → All 4 slot rows update to Economy values

OUTCOME: All new queries use Economy profile. ~87% cost reduction on Chat and Agent.
```

---

### TA-3: Professional — Platform Updates Their Active Profile

**Trigger**: Platform admin updated the Standard profile (new Intent model). Tenant is on Standard.

```
1. Tenant admin has notification badge in sidebar

2. Opens notification:
   "Your LLM configuration was updated by the platform.
    Profile: Standard
    Intent model: gpt-5-mini → gpt-4.1-mini
    [View LLM Profile] [Dismiss]"

3. Admin clicks [View LLM Profile]
   → Settings > LLM Profile shows updated Intent row

4. If admin is satisfied: nothing to do.
   If admin prefers the old behaviour: selects Economy profile
   (or asks platform admin to create a profile with gpt-5-mini as Intent).

OUTCOME: Tenant is informed. They can switch profiles if the update doesn't suit them.
```

---

## Tenant Admin Flows — BYOLLM Track (Enterprise)

### TA-4: Enterprise Tenant Activates BYOLLM

**Trigger**: Enterprise tenant has their own Azure OpenAI subscription with fine-tuned models.

```
1. Opens Settings > LLM Profile
   → Shows current platform profile (Standard)
   → "Advanced" section at bottom: [Configure Custom Models (BYOLLM)]

2. Clicks [Configure Custom Models]
   → Acknowledgement gate:
     ┌──────────────────────────────────────────────────────────┐
     │ ⚠ Custom Model Configuration                            │
     │                                                          │
     │ By using your own model endpoints, you accept that:      │
     │ • You are responsible for endpoint availability          │
     │ • Cost tracking will show "Untracked" for custom slots   │
     │ • Platform SLAs do not apply to custom endpoints         │
     │ • Credentials are encrypted and never recoverable         │
     │                                                          │
     │ [Cancel]                  [I understand, continue]       │
     └──────────────────────────────────────────────────────────┘

3. Admin clicks [I understand, continue]
   → BYOLLM configuration page opens
   → 4 per-slot cards: CHAT · INTENT · VISION · AGENT (all "Not configured")

4. Admin clicks [Add Model] on CHAT card
   → Modal opens:
     Provider: [Azure OpenAI ▾]
     Display Name: Contoso GPT-5 (Chat)
     Endpoint URL: https://contoso-ai.openai.azure.com/
     API Key: [password field]
     API Version: 2024-12-01-preview
     Deployment: contoso-fintuned-gpt5
     [Test Connection]

5. Admin fills fields → [Test Connection]
   → SSRF validation fires (before any network call):
     ✓ Endpoint domain: *.openai.azure.com → allowed
   → Network call:
     ✓ Connection successful · 1,204ms · gpt-5.2-chat · Streaming: ✓

6. [Save] → entry saved, credential encrypted, key shown as ••••••••1234
   → CHAT card now shows: "Contoso GPT-5 (Chat) · Azure · ✓ just now"

7. Admin repeats for INTENT and AGENT slots
   → VISION: Admin clicks [Skip — Use Platform Model]
   (Vision slot will use platform default for this tenant)

8. [Activate Custom Profile] button activates (Chat + Intent + Agent configured and tested)
   → Confirmation:
     "Activate BYOLLM profile?
      Chat:   Contoso GPT-5 (Chat)          — Custom
      Intent: Contoso Intent Model           — Custom
      Vision: gpt-5.2-chat                  — Platform default
      Agent:  Contoso Agent Model            — Custom

      Platform SLAs do not apply to custom slots.
      [Cancel] [Activate]"

9. Admin clicks [Activate]
   → Tenant's `llm_profile_id` → BYOLLM profile
   → All queries now route to custom endpoints for Chat, Intent, Agent
   → Vision uses platform default (Standard profile's Vision slot)

OUTCOME: 3 slots use tenant's own models. Vision uses platform. Zero slot mixing
within the platform profile system — the BYOLLM profile IS their profile.
```

---

### TA-5: Rotate a BYOLLM API Key

**Trigger**: Security team rotated the Azure OpenAI key. Tenant admin needs to update it.

```
1. Settings > LLM Profile shows BYOLLM profile active
   → CHAT card shows: Contoso GPT-5 · ••••••••1234 · ✓ 3d ago

2. Admin clicks [Edit] on CHAT card → [Rotate Key]
   → Modal: new API key field only (endpoint and model unchanged)
   → Admin enters new key → [Test with New Key]
   → Test passes → [Save New Key]
   → Old key overwritten. New key encrypted. Shown as ••••••••5678.

OUTCOME: Key rotated without disrupting other slots.
Active connections drain before next request uses new key.
```

---

### TA-6: Switch from BYOLLM Back to Platform Profile

**Trigger**: BYOLLM endpoint has been unreliable. Tenant wants to revert to platform.

```
1. Settings > LLM Profile shows BYOLLM active
   → Clicks [Switch to Platform Profile]
   → Confirmation:
     "Switch back to platform profile?
      Your custom model configuration will be preserved but deactivated.
      [Cancel] [Switch to Platform]"

2. Admin clicks [Switch to Platform]
   → Profile selector appears with platform profiles available for Enterprise
   → Admin selects: Standard
   → Confirmation → [Switch Profile]

3. Toast: "Now using Standard profile."
   → BYOLLM profile deactivated (not deleted — can reactivate later)
   → All 4 slots now use Standard's assignments

OUTCOME: Instant failover to platform. BYOLLM config preserved for future reactivation.
```

---

## End User Flow

### EU-1: Transparent Profile Experience

```
User sends: "What is our Q3 headcount target?"

InstrumentedLLMClient(slot="intent") →
  ProfileResolver.resolve(tenant_id) →
  Redis HIT → EffectiveProfile { intent: {library_id: X, model: gpt-5-mini} }
  → Decrypt key for library entry X
  → Intent model classifies query → routes to HR agent

InstrumentedLLMClient(slot="chat") →
  Redis HIT → EffectiveProfile { chat: {library_id: Y, model: gpt-5.2-chat} }
  → Chat model synthesises RAG results → streams response

User sees: a streamed answer. No model names. No profile names. No configuration.
```

---

## Edge Cases

| Scenario                                                                     | Behavior                                                                                                                                         |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Professional tenant tries BYOLLM endpoint via API                            | 403: "Your plan (Professional) does not allow custom model endpoints. Upgrade to Enterprise."                                                    |
| Vision slot null; tenant uploads image                                       | Falls to platform default Vision slot. If default also null: "Image analysis is not available. Contact your administrator."                      |
| Platform admin updates profile while tenant mid-query                        | In-flight SSE stream completes on old model. Next query uses updated profile (Redis invalidated).                                                |
| BYOLLM endpoint returns 503                                                  | Error returned to user: "Your custom model endpoint is temporarily unavailable. Contact your administrator." Platform default NOT used silently. |
| BYOLLM endpoint URL is 10.0.0.1                                              | Rejected before any network call: "Private IP addresses are not permitted. Use a public provider endpoint."                                      |
| Enterprise tenant tries to activate BYOLLM profile with Vision missing       | [Activate] allowed — Vision is optional. Falls back to platform default Vision for that slot.                                                    |
| Enterprise tenant has BYOLLM active; platform admin updates Standard profile | BYOLLM tenant is unaffected — they're not using Standard profile. No notification sent.                                                          |
| Platform default profile deprecated                                          | System uses `PLATFORM_DEFAULT_PROFILE_ID` env var as emergency fallback. Admin alerted immediately.                                              |
| Two admins edit same profile concurrently                                    | Last write wins. Both writes create history snapshots. Rollback available for either.                                                            |

---

**Document Version**: 2.0 (final)
**All decisions resolved**: D1 ✓ D2 ✓ D3 ✓
