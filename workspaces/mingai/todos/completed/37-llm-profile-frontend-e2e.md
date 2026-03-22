---
id: 37
title: LLM Profile Redesign — Phase C+D E2E Tests
status: pending
priority: medium
phase: C
estimated_days: 1
---

# LLM Profile Redesign — Phase C+D E2E Tests

## Context

End-to-end browser tests covering the critical flows for both platform admin and tenant admin LLM profile UIs. These tests use Playwright (real browser, real backend, no mocking) and follow the project's god-mode E2E rule: if a required record is missing, create it before testing, never skip.

## Scope

Files to create:

- `tests/e2e/test_llm_profile_platform_admin.spec.ts` — Platform admin flows
- `tests/e2e/test_llm_profile_tenant_admin.spec.ts` — Tenant admin flows
- `tests/e2e/test_llm_profile_byollm.spec.ts` — BYOLLM configuration flow

## Requirements

### test_llm_profile_platform_admin.spec.ts

**Setup (god-mode)**: Before each test, query `/platform/llm-profiles` to discover existing profiles. Create a test platform profile via API if none exists. Create at least 2 published library entries with different eligible_slots sets.

Test: Create profile via UI

1. Navigate to `/platform/llm-profiles`
2. Click "New Profile"
3. Fill in name and description in Step 1
4. Check "Professional" and "Enterprise" plan tiers
5. Click "Next: Assign Slots"
6. In Step 2: use SlotSelector to assign chat slot (verify only eligible models appear in dropdown)
7. Click "Create Profile"
8. Assert profile appears in list with name and chat model name in DM Mono

Test: Assign all slots

1. Open created profile's detail panel
2. Assign chat, intent, vision, agent slots via SlotSelector
3. Verify each slot shows the selected model name after assignment
4. Verify SlotSelector filters: assign a model that does not have 'vision' in eligible_slots to vision slot — verify it does not appear in vision slot dropdown

Test: Cannot assign unpublished entry

1. Create an unpublished (draft status) library entry via API
2. Open SlotSelector for any slot
3. Assert the draft entry does not appear (only published entries shown)

Test: Set platform default

1. Create two active profiles via API
2. Set Profile A as default via "Set as Platform Default" button
3. Assert Profile A shows the default star indicator
4. Set Profile B as default
5. Assert Profile B shows star, Profile A star is gone
6. Assert only one profile has the default indicator at any time

Test: Deprecate profile blocked

1. Create profile via API, assign it to a tenant via API
2. Open profile detail panel
3. Click "Deprecate Profile"
4. Assert: button is disabled (not clickable) or shows "Used by 1 tenant" count badge
5. Remove tenant assignment via API
6. Refresh panel
7. Click "Deprecate Profile" — confirm dialog → deprecate
8. Assert profile status badge shows "deprecated"

Test: Test Profile button shows per-slot results

1. Create profile with chat and intent slots assigned and tested (via API)
2. Open detail panel
3. Click "Test All Slots"
4. Assert: per-slot result cards appear within 10 seconds
5. Assert: latency value uses DM Mono font family (verify via CSS computed style or class)

### test_llm_profile_tenant_admin.spec.ts

**Setup (god-mode)**: Create three test tenants with plan_tier starter, professional, enterprise respectively. Create test platform profiles for professional and enterprise. Assign the professional profile to the professional tenant.

Test: Starter read-only view

1. Log in as starter tenant admin
2. Navigate to `/settings/llm-profile`
3. Assert: no profile selector or [Change Profile] button visible
4. Assert: plan gate card visible with "Upgrade to Professional" text
5. Assert: Chat and Intent slots show model names
6. Assert: Vision and Agent slots show "Enterprise" lock badge

Test: Professional profile selector

1. Log in as professional tenant admin
2. Navigate to `/settings/llm-profile`
3. Click [Change Profile]
4. Assert: dropdown shows only profiles with 'professional' or 'enterprise' in plan_tiers
5. Assert: no Starter-only profiles visible
6. Select a different profile
7. Confirm in dialog
8. Assert: slot names update to show new profile's models

Test: Professional cannot see BYOLLM section

1. Logged in as professional tenant admin
2. Assert: no "Bring Your Own LLM" section, no "Configure custom models" link on the page

Test: Enterprise BYOLLM acknowledgement gate

1. Log in as enterprise tenant admin
2. Navigate to `/settings/llm-profile`
3. Click "Configure custom models"
4. Assert: acknowledgement card with 3 bullet points visible
5. Assert: [Save Configuration] or [Activate] NOT visible at this stage
6. Click [I understand, configure my models]
7. Assert: slot configuration cards appear (Chat, Intent, Vision, Agent)

### test_llm_profile_byollm.spec.ts

**Setup (god-mode)**: Enterprise tenant exists. A valid test LLM endpoint is available (use the test server's own echo endpoint or a real provider endpoint from .env). SSRF-blocked IP: use `10.0.0.1` or `169.254.169.254`.

Test: Full BYOLLM configuration and activation

1. Navigate through acknowledgement gate
2. Click [Add Model Endpoint] on Chat slot
3. Select provider, fill in endpoint, API key, model name
4. Click [Test Connection] — assert success message appears with latency
5. Click [Save Configuration]
6. Assert: Chat slot card shows entry name + "Tested Xm ago"
7. Repeat for Intent and Agent slots
8. Assert: [Activate Custom Profile] button becomes enabled (not disabled)
9. Click [Activate Custom Profile]
10. Assert: BYOLLM active view appears with per-slot entry names

Test: Private IP endpoint rejected immediately

1. Open AddEndpointModal for any slot
2. Enter `http://10.0.0.1/api` as endpoint URL
3. Click [Test Connection]
4. Assert: error message "Endpoint address is not permitted — use a supported provider URL" appears inline
5. Assert: [Save Configuration] remains disabled

Test: Wrong API key shows human-readable error

1. Open AddEndpointModal
2. Enter valid endpoint URL but incorrect API key
3. Click [Test Connection]
4. Assert: error message "Authentication failed — check your API key" appears inline (not a generic "Error 401" message)

Test: Switch from BYOLLM back to platform profile

1. BYOLLM profile is active (set up via API)
2. Navigate to `/settings/llm-profile`
3. Assert: BYOLLM active view shown
4. Click [Use Platform Profile instead]
5. Confirm dialog
6. Assert: platform profile view is now shown (slot names from platform profile visible)
7. Assert: BYOLLM configuration preserved but inactive (verify via API that profile still exists in draft state)

## Acceptance Criteria

- All 3 test files exist and run against a live stack (not mocked)
- God-mode setup: missing tenants, profiles, or library entries are created before each test
- No hardcoded user emails or IDs — all test data discovered via API query before use
- Tests pass in isolation and when run sequentially
- Private IP test uses actual connection attempt (not just frontend validation)
- DM Mono font assertion: verifiable via computed CSS class check

## Dependencies

- 35 (platform admin frontend)
- 36 (tenant admin frontend)
- 33 (tenant admin + BYOLLM API — endpoints must be live for E2E to run)
