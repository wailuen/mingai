---
id: 38
title: LLM Profile Redesign — Phase E: Health Monitoring
status: pending
priority: medium
phase: E
estimated_days: 2
---

# LLM Profile Redesign — Phase E: Health Monitoring

## Context

Platform admins need to know when a library entry starts failing. The health monitoring system runs a background job every 24 hours to probe each published library entry and update its health_status. Degraded entries surface as warnings in the profile detail UI and trigger a platform admin notification.

Two critical design decisions:

1. The health check uses each entry's own credentials (`api_key_encrypted`, `endpoint_url`) — it does NOT fall back to env vars. This is intentional: health checks must be representative of what tenants actually experience.
2. Response body content is NEVER stored. The probe only checks connectivity and records HTTP status + latency + truncated error. No prompts, no completions, no user data.

## Scope

Files to create:

- `src/backend/app/jobs/llm_health_check.py` — background job
- `tests/unit/test_health_check_credentials.py` — credential isolation unit tests
- `tests/unit/test_health_check_degraded_notification.py` — notification trigger tests
- `tests/integration/test_health_check_degraded_shows_warning.py` — UI warning integration test

## Requirements

### Background Health Check Job (llm_health_check.py)

Schedule: APScheduler cron job, every 24 hours. Registered at application startup.

Scope: all `llm_library` entries where `status = 'published'` and `test_passed_at IS NOT NULL`.

Per-entry probe:

1. Fetch entry including `api_key_encrypted`, `endpoint_url`, `api_version`, `provider`
2. Decrypt `api_key_encrypted` to get `api_key`
3. Send a minimal connectivity probe:
   - NOT a completion call (no prompt, no response generation)
   - Just: a models/list endpoint call, or a minimal OPTIONS/HEAD probe if available for the provider
   - Azure OpenAI: `GET {endpoint_url}/openai/models?api-version={api_version}` with Authorization header
   - OpenAI: `GET https://api.openai.com/v1/models` with Bearer token
   - Anthropic: not supported for list endpoint — use a minimal `POST /v1/messages` with `max_tokens: 1` and a single whitespace prompt. Store no response body.
   - Google: `GET https://generativelanguage.googleapis.com/v1/models` with API key
4. Record:
   - `http_status_code: int`
   - `latency_ms: int`
   - `error_message: str | None` — truncated to 200 chars. Sanitised: no credential values, no internal URLs
5. In finally block: zero the decrypted api_key (`api_key = ""`)
6. On success (HTTP 2xx):
   - `UPDATE llm_library SET health_status = 'healthy', health_checked_at = NOW() WHERE id = entry_id`
7. On failure (non-2xx or exception):
   - `UPDATE llm_library SET health_status = 'degraded', health_checked_at = NOW() WHERE id = entry_id`
   - Call `notify_platform_admin_degraded_entry(entry_id, error_message)`

#### notify_platform_admin_degraded_entry

Creates a platform admin notification (in-app, async):

- Notification record in the existing notifications table (or a new one if it doesn't exist)
- Type: `llm_entry_degraded`
- Message: "Model entry [name] is reporting connectivity issues. Check the LLM Library."
- Does NOT auto-deprecate the entry
- Does NOT stop the entry from being used in active profiles (only a platform admin can deprecate)

If the entry was already degraded (previous check also failed): do NOT create a duplicate notification. Check `health_status == 'degraded'` before the probe; if already degraded, skip notification creation.

Email notification: on first degradation (transition from 'healthy' to 'degraded'), send email to platform admin email address from env var `PLATFORM_ADMIN_EMAIL`. Subject: "Action required: LLM model entry [name] is degraded". Not a recurring email — only on status transition.

#### Probe timeout

5 seconds per entry. On timeout: treat as failure, record `error_message = "Connection timed out"`.

#### Parallel execution

Probe all entries concurrently using `asyncio.gather` with a semaphore of 10 (max 10 concurrent probes). This prevents overwhelming providers with simultaneous requests.

#### Concurrency guard

Job should not run if a previous run is still in progress. Use a Redis distributed lock (`mingai:health_check:running`, TTL 2 hours) to prevent overlap.

### Health Status in UI

These UI updates are part of this todo:

Platform LLM Library list table: add a `health_status` column (dot indicator). Accent = healthy, alert = degraded, --text-faint dot = unknown (never checked). Column header: "Health" (11px uppercase).

Platform Profile detail panel (SlotAssignmentSection): if assigned library entry has `health_status = 'degraded'`, show warn indicator next to the model name and add a tooltip: "This model reported issues [X hours ago]. Consider reassigning this slot."

Platform admin in-app notification banner (top of any platform admin page): if any assigned-slot entry is degraded, show a dismissible warn banner: "One or more model entries are reporting issues. Check LLM Library." Links to `/platform/llm-library`.

### Tests

`test_health_check_credentials.py`:

- Unit test that the probe function reads credentials from the entry, NOT from env vars
- Override env vars to different values; assert probe uses entry's own credentials
- Assert api_key is zeroed in finally block (inspect the local scope after execution via a spy/instrument on the entry's decrypted key — this may require a test helper to inject into the decrypt path)

`test_health_check_degraded_notification.py`:

- Unit test: successful probe → health_status = 'healthy', no notification
- Unit test: failed probe → health_status = 'degraded', notification created
- Unit test: already degraded entry fails again → no duplicate notification created
- Unit test: degraded entry succeeds → status transitions to 'healthy' (recovery path)
- Unit test: first degradation triggers email notification, second degradation does not

`test_health_check_degraded_shows_warning.py`:

- Integration test: set an entry's health_status to 'degraded' directly in DB
- Fetch `GET /platform/llm-profiles/{id}` for a profile with that entry assigned to a slot
- Assert response includes health warning indicator in the slot's data
- Fetch `GET /platform/llm-library` — assert health dot data for the degraded entry is 'degraded'

## Acceptance Criteria

- Health check job is registered in APScheduler at application startup
- Probes use entry credentials only — env var override test passes
- api_key is zeroed in finally block (verified by test)
- Degraded entry creates exactly one in-app notification per degradation event (no duplicates on repeat failures)
- First degradation sends email to PLATFORM_ADMIN_EMAIL; repeat degradations do not
- Profile detail API returns health indicator for degraded slot entries
- LLM Library list returns health_status per entry
- Concurrency guard prevents overlapping job runs
- Response body content is never stored (probes use list/models endpoints, not completions, except Anthropic minimal probe)

## Dependencies

- 27 (schema) — health_status, health_checked_at columns on llm_library
- 35 (platform admin frontend) — UI warning indicators are part of the profile detail panel from todo 35; this todo adds the data source
