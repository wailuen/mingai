# API Reference — mingai Backend

Base URL: `http://localhost:8022/api/v1`

Auth: `Authorization: Bearer <jwt>` on all endpoints except `/auth/local/login`.

Auth roles: `end_user`, `tenant_admin`, `platform_admin`. Scope: `tenant` or `platform`.

---

## Auth

| Method | Path                  | Auth | Description                                                     |
| ------ | --------------------- | ---- | --------------------------------------------------------------- |
| POST   | `/auth/local/login`   | None | Bootstrap login (platform admin from env vars). Returns JWT v2. |
| POST   | `/auth/token/refresh` | Any  | Re-issue token with current claims.                             |
| POST   | `/auth/logout`        | Any  | Session logout (Phase 1: no-op; no token revocation).           |
| GET    | `/auth/current`       | Any  | Current user — id, tenant_id, roles, scope, plan, email.        |

Login body: `{ "email": str, "password": str }`. Returns `{ "access_token", "token_type", "expires_in" }`.

---

## Chat

| Method | Path                  | Auth | Description                                                                                 |
| ------ | --------------------- | ---- | ------------------------------------------------------------------------------------------- |
| POST   | `/chat/stream`        | Any  | SSE streaming chat. Body: `{ "query", "agent_id", "conversation_id"?, "active_team_id"? }`. |
| POST   | `/chat/feedback`      | Any  | Thumbs up/down on a message. Body: `{ "message_id", "rating": "up"\|"down", "comment"? }`.  |
| GET    | `/conversations`      | Any  | List conversations (paginated: `page`, `page_size`).                                        |
| GET    | `/conversations/{id}` | Any  | Get conversation with messages.                                                             |
| DELETE | `/conversations/{id}` | Any  | Delete conversation.                                                                        |

---

## Issues

### End-User Issue Reporting

| Method | Path                                  | Auth | Description                                                                                   |
| ------ | ------------------------------------- | ---- | --------------------------------------------------------------------------------------------- |
| POST   | `/issues`                             | Any  | Create issue. `screenshot_url` requires `blur_acknowledged=true`.                             |
| GET    | `/issues/{id}`                        | Any  | Get issue. Admin sees all; others see own only.                                               |
| GET    | `/issue-reports/presign`              | Any  | Get presigned upload URL. Query params: `filename`, `content_type` (image/png or image/jpeg). |
| GET    | `/my-reports`                         | Any  | Current user's own reports (paginated).                                                       |
| GET    | `/my-reports/{id}`                    | Any  | Detail of own report with timeline.                                                           |
| POST   | `/issue-reports/{id}/still-happening` | Any  | Report regression. Creates linked report; auto-escalates or routes to human review.           |

### Tenant Admin Issue Queue (API-019/020)

| Method | Path                        | Auth         | Description                                                                                                                                            |
| ------ | --------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| GET    | `/admin/issues`             | tenant_admin | List tenant issues. Query params: `status`, `severity`, `page`, `page_size`. Results scoped to caller's tenant via RLS.                                |
| PATCH  | `/issues/{id}/status`       | tenant_admin | Update status: `open`, `investigating`, `resolved`, `closed`.                                                                                          |
| POST   | `/issues/{id}/events`       | tenant_admin | Add comment/event to issue log.                                                                                                                        |
| POST   | `/admin/issues/{id}/action` | tenant_admin | State machine action. Body: `{ "action": "assign"\|"resolve"\|"escalate"\|"request_info"\|"close_duplicate", "payload"?: {} }`. Unknown actions → 422. |

### Platform Issue Queue (API-021/022/023)

| Method | Path                           | Auth           | Description                                                                                                                                           |
| ------ | ------------------------------ | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/platform/issues`             | platform_admin | Cross-tenant issue list. Query params: `tenant_id`?, `severity`, `status`, `page`, `page_size`.                                                       |
| POST   | `/platform/issues/{id}/action` | platform_admin | Triage action. Body: `{ "action": "override_severity"\|"route_to_tenant"\|"assign_sprint"\|"close_wontfix", "payload"?: {} }`. Unknown actions → 422. |
| GET    | `/platform/issues/stats`       | platform_admin | Aggregated issue stats. Query param: `period=7d\|30d\|90d`. Returns counts by severity and status across all tenants.                                 |

### GitHub Webhook (API-018)

| Method | Path               | Auth        | Description                                                                                                            |
| ------ | ------------------ | ----------- | ---------------------------------------------------------------------------------------------------------------------- |
| POST   | `/webhooks/github` | HMAC-SHA256 | GitHub event ingestion. Validates `X-Hub-Signature-256` header. Returns 503 if `GITHUB_WEBHOOK_SECRET` not configured. |

Supported events → status transitions:

| Event                 | Status applied    |
| --------------------- | ----------------- |
| `issues.labeled`      | `triaged`         |
| `pull_request.opened` | `fix_in_progress` |
| `pull_request.merged` | `fix_merged`      |
| `release.published`   | `fix_deployed`    |

Unrecognized events return `{ "processed": false }` with status 200.

---

## Platform Admin

All require `scope=platform` (i.e. `platform_admin` role).

| Method | Path                                | Auth           | Description                                                                                                                                                         |
| ------ | ----------------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/admin/dashboard`                  | platform_admin | Dashboard stats: active_users, documents_indexed, queries_today, satisfaction_pct.                                                                                  |
| GET    | `/platform/tenants`                 | platform_admin | List all tenants (paginated).                                                                                                                                       |
| POST   | `/platform/tenants`                 | platform_admin | Provision tenant. Body: `{ "name", "plan", "primary_contact_email", "slug"? }`.                                                                                     |
| GET    | `/platform/tenants/{id}`            | platform_admin | Get tenant.                                                                                                                                                         |
| PATCH  | `/platform/tenants/{id}`            | platform_admin | Update tenant name/plan/contact/status.                                                                                                                             |
| POST   | `/platform/tenants/{id}/suspend`    | platform_admin | Suspend tenant.                                                                                                                                                     |
| POST   | `/platform/tenants/{id}/activate`   | platform_admin | Reactivate suspended tenant.                                                                                                                                        |
| GET    | `/platform/tenants/{id}/health`     | platform_admin | Health score (0–100) with 4 weighted components.                                                                                                                    |
| GET    | `/platform/tenants/{id}/cost-usage` | platform_admin | Token and cost usage for a single tenant. Query: `?period=7d\|30d\|90d`. Returns `{ tokens_in, tokens_out, cost_usd, by_model: [...] }`.                            |
| GET    | `/platform/llm-profiles`            | platform_admin | List all LLM profiles across tenants.                                                                                                                               |
| POST   | `/platform/llm-profiles`            | platform_admin | Create LLM profile. Body: `{ "tenant_id", "name", "provider", "primary_model", "intent_model", "embedding_model", "endpoint_url"?, "api_key_ref"?, "is_default" }`. |
| GET    | `/platform/llm-profiles/{id}`       | platform_admin | Get LLM profile.                                                                                                                                                    |
| PATCH  | `/platform/llm-profiles/{id}`       | platform_admin | Update LLM profile fields.                                                                                                                                          |
| DELETE | `/platform/llm-profiles/{id}`       | platform_admin | Delete profile. 409 if assigned to a tenant.                                                                                                                        |
| GET    | `/platform/stats`                   | platform_admin | Platform stats: total_tenants, active_tenants, total_users, queries_today.                                                                                          |
| GET    | `/platform/issues`                  | platform_admin | Cross-tenant issue list. See Issues → Platform Issue Queue above.                                                                                                   |
| POST   | `/platform/issues/{id}/action`      | platform_admin | Triage action. See Issues → Platform Issue Queue above.                                                                                                             |
| GET    | `/platform/issues/stats`            | platform_admin | Issue stats with period filter. See Issues → Platform Issue Queue above.                                                                                            |
| GET    | `/platform/cost-analytics/summary`  | platform_admin | Cross-tenant cost rollup. Query: `?period=7d\|30d\|90d`. Returns aggregate totals + per-tenant breakdown sorted by `cost_usd` descending.                           |

### Platform LLM Provider Credentials (PVDR-001–020)

All require `scope=platform`. `api_key` is accepted on POST/PATCH but **never returned** in any response. Responses include `key_present: bool` instead.

| Method | Path                                    | Auth           | Description                                                                                                                                                                                           |
| ------ | --------------------------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/platform/providers`                   | platform_admin | List all providers. Query: `?enabled_only=true`. Returns `{ providers: [...], bootstrap_active: bool }`. `bootstrap_active=true` means 0 rows exist and env fallback is in use.                       |
| GET    | `/platform/providers/health-summary`    | platform_admin | Aggregate health counts: `{ total, healthy, error, unchecked, last_checked_at }`.                                                                                                                     |
| GET    | `/platform/providers/{id}`              | platform_admin | Get single provider. Never returns `api_key_encrypted`.                                                                                                                                               |
| POST   | `/platform/providers`                   | platform_admin | Create provider. Body: `{ "provider_type", "display_name", "api_key", "endpoint"?, "models"?, "options"?, "pricing"?, "is_enabled"?, "is_default"? }`. Returns 201. `azure_openai` requires endpoint. |
| PATCH  | `/platform/providers/{id}`              | platform_admin | Update provider. Omit `api_key` to keep existing encrypted key.                                                                                                                                       |
| DELETE | `/platform/providers/{id}`              | platform_admin | Delete provider. 409 if it is the default provider or the only enabled provider.                                                                                                                      |
| POST   | `/platform/providers/{id}/test`         | platform_admin | Test connectivity via real API call. Returns `{ success, latency_ms, error? }`. Updates `provider_status` and `last_health_check_at`.                                                                 |
| POST   | `/platform/providers/{id}/set-default`  | platform_admin | Atomically set this provider as the default (clears all others). 422 if provider is disabled.                                                                                                         |

Provider response shape: `id`, `provider_type`, `display_name`, `description`, `endpoint`, `models` (dict), `options` (dict), `pricing`, `is_enabled`, `is_default`, `provider_status` (`unchecked`\|`healthy`\|`error`\|`timeout`\|`auth_failed`), `last_health_check_at`, `health_error`, `key_present`.

Valid `provider_type` values: `azure_openai`, `openai`, `anthropic`, `deepseek`, `dashscope`, `doubao`, `gemini`.

### Platform LLM Library

| Method | Path                                   | Auth           | Description                                                                                                                                                                    |
| ------ | -------------------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| POST   | `/platform/llm-library`                | platform_admin | Create a Draft entry. Body: `{ "provider", "model_name", "plan_tier", "pricing_per_1k_in", "pricing_per_1k_out" }`. Returns 201 with new entry.                                |
| GET    | `/platform/llm-library`                | platform_admin | List entries. Query: `?status=Draft\|Published\|Deprecated`. Omitting `status` returns all.                                                                                    |
| GET    | `/platform/llm-library/{id}`           | platform_admin | Get single entry.                                                                                                                                                              |
| PATCH  | `/platform/llm-library/{id}`           | platform_admin | Update Draft or Published entry. Allowlisted fields: `provider`, `model_name`, `plan_tier`, `pricing_per_1k_in`, `pricing_per_1k_out`. Cannot update a Deprecated entry — 409. |
| POST   | `/platform/llm-library/{id}/publish`   | platform_admin | Transition `Draft → Published`. Makes the entry visible to tenant admins. 409 if already Published or Deprecated.                                                              |
| POST   | `/platform/llm-library/{id}/deprecate` | platform_admin | Transition `Published → Deprecated`. Entry is hidden from tenant admins but retained for cost history. 409 if not currently Published.                                         |

---

## Users

| Method | Path                    | Auth         | Description                                                  |
| ------ | ----------------------- | ------------ | ------------------------------------------------------------ |
| GET    | `/users`                | tenant_admin | List users in tenant (paginated).                            |
| POST   | `/users`                | tenant_admin | Invite user. Body: `{ "email": EmailStr, "role", "name"? }`. |
| GET    | `/users/me`             | Any          | Current user profile.                                        |
| PATCH  | `/users/me`             | Any          | Update own profile: `name`, `preferences`.                   |
| GET    | `/users/{id}`           | tenant_admin | Get user by ID.                                              |
| PATCH  | `/users/{id}`           | tenant_admin | Update user: `role`, `name`, `is_active`.                    |
| DELETE | `/users/{id}`           | tenant_admin | Deactivate user.                                             |
| POST   | `/users/me/gdpr/export` | Any          | Export user data package.                                    |
| POST   | `/users/me/gdpr/erase`  | Any          | GDPR erasure — clears all 3 stores (DB, Redis, profile).     |

---

## Teams

| Method | Path                        | Auth         | Description                         |
| ------ | --------------------------- | ------------ | ----------------------------------- |
| GET    | `/teams`                    | Any          | List teams in tenant.               |
| POST   | `/teams`                    | tenant_admin | Create team.                        |
| GET    | `/teams/{id}`               | Any          | Get team details.                   |
| PATCH  | `/teams/{id}`               | tenant_admin | Update team.                        |
| DELETE | `/teams/{id}`               | tenant_admin | Delete team.                        |
| POST   | `/teams/{id}/members`       | tenant_admin | Add member.                         |
| DELETE | `/teams/{id}/members/{uid}` | tenant_admin | Remove member.                      |
| GET    | `/teams/{id}/memory`        | Any          | Get anonymized team working memory. |

---

## Glossary

| Method | Path                                   | Auth         | Description                                                                                               |
| ------ | -------------------------------------- | ------------ | --------------------------------------------------------------------------------------------------------- |
| GET    | `/glossary`                            | Any          | List terms (paginated).                                                                                   |
| POST   | `/glossary`                            | tenant_admin | Create term. Body: `{ "term", "full_form", "aliases"? }`.                                                 |
| POST   | `/glossary/import`                     | tenant_admin | Bulk CSV import. Multipart file upload.                                                                   |
| GET    | `/glossary/miss-signals`               | tenant_admin | Top uncovered terms from miss signals. Query: `?limit=20`.                                                |
| GET    | `/glossary/{id}`                       | Any          | Get term.                                                                                                 |
| PATCH  | `/glossary/{id}`                       | tenant_admin | Update term.                                                                                              |
| DELETE | `/glossary/{id}`                       | tenant_admin | Delete term. Invalidates Redis cache.                                                                     |
| GET    | `/glossary/{id}/history`               | tenant_admin | Audit log for a term (TA-012). Returns entries newest-first with before/after state.                      |
| PATCH  | `/glossary/{id}/rollback/{version_id}` | tenant_admin | Restore term to a prior audit snapshot (TA-012). `version_id` = audit_log.id. Atomic (term+audit commit). |

### Admin Glossary

| Method | Path                               | Auth         | Description                                                                        |
| ------ | ---------------------------------- | ------------ | ---------------------------------------------------------------------------------- |
| POST   | `/admin/glossary/miss-signals`     | tenant_admin | Ingest miss signals (TA-013). Body: `[{ "unresolved_term", "conversation_id"? }]`. |
| GET    | `/admin/analytics/glossary-impact` | tenant_admin | Glossary impact analytics (TA-029). Returns per-term usage/satisfaction delta.     |

All glossary writes invalidate `mingai:{tenant_id}:glossary_terms` in Redis.

---

## Memory

| Method | Path                 | Auth | Description                                                  |
| ------ | -------------------- | ---- | ------------------------------------------------------------ |
| GET    | `/memory/notes`      | Any  | List user's memory notes.                                    |
| POST   | `/memory/notes`      | Any  | Create note (max 200 chars).                                 |
| DELETE | `/memory/notes/{id}` | Any  | Delete specific note.                                        |
| DELETE | `/memory/notes`      | Any  | Clear all notes for user.                                    |
| PATCH  | `/memory/privacy`    | Any  | Toggle `profile_learning_enabled`, `working_memory_enabled`. |
| GET    | `/memory/profile`    | Any  | Get user profile with learning data.                         |
| DELETE | `/memory/profile`    | Any  | GDPR comprehensive erasure.                                  |
| GET    | `/memory/working`    | Any  | Get working memory summary.                                  |
| DELETE | `/memory/working`    | Any  | Clear working memory (Redis).                                |
| GET    | `/memory/export`     | Any  | Export all profile data (GDPR).                              |

---

## Workspace (Tenant Admin)

| Method | Path               | Auth         | Description                                                                |
| ------ | ------------------ | ------------ | -------------------------------------------------------------------------- |
| GET    | `/admin/workspace` | tenant_admin | Get workspace settings (name, timezone, locale, notification_preferences). |
| PATCH  | `/admin/workspace` | tenant_admin | Update workspace settings. Allowlisted fields only.                        |

---

## SSO (Tenant Admin)

All stored under `tenant_configs` table using JSONB `config_data`. No external Auth0 validation yet (P3AUTH-001 pending).

### SSO Config

| Method | Path              | Auth         | Description                                                                                             |
| ------ | ----------------- | ------------ | ------------------------------------------------------------------------------------------------------- |
| GET    | `/admin/sso`      | tenant_admin | Get current SSO config (`config_type='sso_config'`). Returns `{ isConfigured, provider, domain, ... }`. |
| POST   | `/admin/sso`      | tenant_admin | Save SSO config. Body: `{ provider, domain, client_id, ... }`. Upserts `tenant_configs` row.            |
| POST   | `/admin/sso/test` | tenant_admin | Check config presence. Returns `{ success, message }`. Full Auth0 test pending P3AUTH-001.              |

### Group Sync Config (P3AUTH-010/015)

| Method | Path                           | Auth         | Description                                                                                                                    |
| ------ | ------------------------------ | ------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| GET    | `/admin/sso/group-sync/config` | tenant_admin | Get Auth0 group sync allowlist and role mapping. Returns `{ allowlist: [str], mapping: {group→role} }`.                        |
| PATCH  | `/admin/sso/group-sync/config` | tenant_admin | Update group sync config. Body: `{ "allowlist"?: [str], "mapping"?: {group→role} }`. Stored as `config_type='sso_group_sync'`. |

`GroupSyncConfigRequest` constraints: max 200 groups in `allowlist`, 256-char group name limit, valid roles: `admin`, `editor`, `viewer`, `user`.

---

## Onboarding Wizard (TA-031)

| Method | Path                         | Auth         | Description                                                                                   |
| ------ | ---------------------------- | ------------ | --------------------------------------------------------------------------------------------- |
| GET    | `/admin/onboarding/status`   | tenant_admin | Get wizard state: `steps` dict (step→bool), `current_step`, `is_complete`, `dismissed_until`. |
| PATCH  | `/admin/onboarding/progress` | tenant_admin | Mark a step complete. Body: `{ "step": "connect_datasource"\|"invite_users"\|...}`.           |
| PATCH  | `/admin/onboarding/dismiss`  | tenant_admin | Dismiss wizard for 7 days.                                                                    |

Steps: `connect_datasource`, `invite_users`, `configure_glossary`, `deploy_agent`, `test_chat`.

---

## Bulk User Actions (TA-032)

| Method | Path                       | Auth         | Description                                                                                     |
| ------ | -------------------------- | ------------ | ----------------------------------------------------------------------------------------------- |
| POST   | `/admin/users/bulk-action` | tenant_admin | Bulk operation on up to 100 users. Returns `{ succeeded: [...], failed: [{user_id, reason}] }`. |

Body: `{ "user_ids": [uuid, ...], "action": "suspend"\|"role_change"\|"kb_assignment", "payload"?: {...} }`.

Action payloads:

- `suspend`: no payload required. Acting user cannot suspend themselves.
- `role_change`: `payload.role = "viewer"\|"tenant_admin"`. Acting user cannot demote themselves.
- `kb_assignment`: `payload.kb_id = <uuid>`, `payload.scope = "workspace_wide"\|"role_restricted"\|"user_specific"\|"agent_only"`. KB must exist in caller's tenant.

---

## KB Source Management (TA-034)

| Method | Path                                             | Auth         | Description                                                                              |
| ------ | ------------------------------------------------ | ------------ | ---------------------------------------------------------------------------------------- |
| GET    | `/admin/knowledge-base/{kb_id}/sources`          | tenant_admin | List all integrations attached to this KB with health indicators.                        |
| GET    | `/admin/knowledge-base/{kb_id}/documents`        | tenant_admin | Search documents across all sources. Query: `?search=<term>` (optional, max_length=200). |
| DELETE | `/admin/knowledge-base/{kb_id}/sources/{int_id}` | tenant_admin | Detach integration from KB (removes `kb_id` from integration config). 204 on success.    |

Health indicator values: `healthy` (active + synced within 24h), `stale` (active + no recent sync), `unhealthy` (disabled/error/failed), `pending`.

---

## KB Access Control (TA-007)

| Method | Path                                           | Auth         | Description                                                                          |
| ------ | ---------------------------------------------- | ------------ | ------------------------------------------------------------------------------------ |
| GET    | `/admin/knowledge-base/{kb_id}/access-control` | tenant_admin | Get visibility mode + allowed_roles + allowed_user_ids.                              |
| PATCH  | `/admin/knowledge-base/{kb_id}/access-control` | tenant_admin | Set visibility mode. Body: `{ visibility_mode, allowed_roles?, allowed_user_ids? }`. |

Visibility modes: `workspace_wide`, `role_restricted`, `user_specific`, `agent_only`.

---

## LLM Config (Tenant Admin)

| Method | Path                       | Auth                           | Description                                                                                                                                                                                               |
| ------ | -------------------------- | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/admin/llm-config`        | tenant_admin                   | Get the tenant's current LLM configuration: `model_source` (`library` or `byollm`), `model_name`, `byollm_configured` (bool).                                                                             |
| PATCH  | `/admin/llm-config`        | tenant_admin                   | Set `model_source` and `model_name`. Body: `{ "model_source": "library"\|"byollm", "model_name": str }`. On success, invalidates `mingai:{tenant_id}:config:llm_config` in Redis.                         |
| PATCH  | `/admin/llm-config/byollm` | tenant_admin (enterprise only) | Store an encrypted BYOLLM API key. Body: `{ "api_key": str, "base_url"?: str }`. 403 if tenant plan is not `enterprise`. The key is Fernet-encrypted before storage — never returned in any GET response. |
| DELETE | `/admin/llm-config/byollm` | tenant_admin (enterprise only) | Remove the BYOLLM key ref and revert `model_source` to `library`. 403 if tenant plan is not `enterprise`. 404 if no BYOLLM key is configured.                                                             |

`PATCH /byollm` and `DELETE /byollm` must be registered before `PATCH /admin/llm-config` to avoid path shadowing.

---

## Agents (Tenant Admin)

| Method | Path                             | Auth         | Description                                                                                                         |
| ------ | -------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------- |
| GET    | `/agents`                        | tenant_admin | List workspace agents. Query: `?status=<filter>`.                                                                   |
| POST   | `/agents`                        | tenant_admin | Create agent. Body: `{ name, system_prompt, kb_ids?, agent_type?, status?, template_id? }`.                         |
| GET    | `/agents/{id}`                   | tenant_admin | Get agent.                                                                                                          |
| PATCH  | `/agents/{id}`                   | tenant_admin | Update agent fields.                                                                                                |
| DELETE | `/agents/{id}`                   | tenant_admin | Archive agent.                                                                                                      |
| PATCH  | `/agents/{id}/status`            | tenant_admin | Update lifecycle status. Body: `{ "status": "draft"\|"published"\|"unpublished"\|"active"\|"paused"\|"archived" }`. |
| POST   | `/agents/{id}/test`              | tenant_admin | Run test chat against agent. Body: `{ "query" }`. 504 if no response within 30s.                                    |
| GET    | `/agents/{id}/upgrade-available` | tenant_admin | Check if a newer template version exists (TA-024). Returns `{ upgrade_available, current, latest }`.                |
| PATCH  | `/agents/{id}/upgrade`           | tenant_admin | Apply template upgrade (TA-024). Updates `template_id` to latest version.                                           |
| GET    | `/agents/templates/library`      | tenant_admin | Browse platform agent template library. Query: `?category=<cat>&page=1&page_size=20`.                               |
| POST   | `/agents/deploy-from-library`    | tenant_admin | Deploy agent from a library template. Returns created agent with `status=active`.                                   |

**Agent status semantics**: `active` = deployed to end users; `paused` = chat returns 503; `archived` = hidden from all lists.

### Agent Analytics (TA-027)

| Method | Path                           | Auth         | Description                                                                                                                 |
| ------ | ------------------------------ | ------------ | --------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/admin/agents`                | tenant_admin | List workspace agents with 7-day satisfaction rate and session count (TA-021).                                              |
| GET    | `/admin/agents/{id}/analytics` | tenant_admin | Per-agent analytics: `daily_satisfaction`, `low_confidence_responses`, `guardrail_events`, `correlation` (root cause data). |

---

## Analytics (Tenant Admin)

| Method | Path                                      | Auth         | Description                                                                        |
| ------ | ----------------------------------------- | ------------ | ---------------------------------------------------------------------------------- |
| GET    | `/admin/analytics/satisfaction-dashboard` | tenant_admin | Rolling 7-day satisfaction rate, per-agent breakdown, 30-day daily trend (TA-026). |
| GET    | `/admin/analytics/engagement-v2`          | tenant_admin | DAU/WAU/MAU aggregates, per-agent session counts, feature adoption rates (TA-030). |
| GET    | `/admin/analytics/glossary-impact`        | tenant_admin | Per-term usage + satisfaction delta for terms in glossary (TA-029).                |

---

## Documents — SharePoint

| Method | Path                              | Auth         | Description                                                         |
| ------ | --------------------------------- | ------------ | ------------------------------------------------------------------- |
| POST   | `/documents/sharepoint/connect`   | tenant_admin | Create SharePoint connection. Credentials stored as vault ref only. |
| POST   | `/documents/sharepoint/{id}/test` | tenant_admin | Test connection health.                                             |
| POST   | `/documents/sharepoint/{id}/sync` | tenant_admin | Trigger document sync job.                                          |
| GET    | `/documents/sharepoint/{id}/sync` | tenant_admin | List sync job history.                                              |

---

## HAR A2A Transactions (AI-040 to AI-051)

| Method | Path                                    | Auth         | Description                                                                                                                                                                                                                                  |
| ------ | --------------------------------------- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| POST   | `/har/transactions`                     | tenant_admin | Create HAR transaction. Body: `{initiator_agent_id, counterparty_agent_id, amount?, currency?, payload?}`. Sets `requires_human_approval=true` and 48h deadline if amount ≥ $5,000. Returns 201 with `{id, state, requires_human_approval}`. |
| GET    | `/har/transactions`                     | tenant_admin | List transactions. Query: `?state=DRAFT\|OPEN\|...&page=1&page_size=20`.                                                                                                                                                                     |
| GET    | `/har/transactions/{txn_id}`            | tenant_admin | Get transaction detail with all fields.                                                                                                                                                                                                      |
| POST   | `/har/transactions/{txn_id}/transition` | tenant_admin | Advance state machine. Body: `{new_state}`. Returns updated transaction. 400 on invalid transition.                                                                                                                                          |
| POST   | `/har/transactions/{txn_id}/approve`    | tenant_admin | Human approval for high-value transactions. Sets `human_approved_at`, transitions to COMMITTED. 400 if approval not required.                                                                                                                |
| POST   | `/har/transactions/{txn_id}/reject`     | tenant_admin | Human rejection. Transitions to ABANDONED. 400 if approval not required.                                                                                                                                                                     |

### Agents — Keypair & Trust (AI-040, AI-046)

| Method | Path                                               | Auth         | Description                                                                          |
| ------ | -------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------ |
| GET    | `/agents/templates/{agent_id}/public-key`          | tenant_admin | Get Ed25519 public key for signature verification. 404 if keypair not yet generated. |
| POST   | `/agents/templates/{agent_id}/compute-trust-score` | tenant_admin | Recompute and persist trust score for an agent. Returns `{agent_id, trust_score}`.   |

### HAR State Transitions

Valid transitions: `DRAFT→OPEN→NEGOTIATING→COMMITTED→EXECUTING→COMPLETED`. Also: `OPEN|NEGOTIATING|COMMITTED→ABANDONED`, `EXECUTING→DISPUTED`, `DISPUTED→RESOLVED`. Terminal: COMPLETED, ABANDONED, RESOLVED.

---

## Storage (Local Dev Only)

Available when `CLOUD_PROVIDER=local`. Internal endpoints, not part of the external API contract.

| Method | Path                    | Description                              |
| ------ | ----------------------- | ---------------------------------------- |
| PUT    | `/storage/upload`       | HMAC-signed upload target for local dev. |
| GET    | `/storage/serve/{path}` | Serve stored file.                       |

---

## Notifications (API-012)

| Method | Path                    | Auth | Description                                                                                                              |
| ------ | ----------------------- | ---- | ------------------------------------------------------------------------------------------------------------------------ |
| GET    | `/notifications/stream` | Any  | SSE notification stream. `Content-Type: text/event-stream`. Keepalive comment every 30s. Closes when client disconnects. |

The stream delivers JSON payloads published to `mingai:{tenant_id}:notifications:{user_id}` via Redis Pub/Sub. Each event line: `data: {json}\n\n`. Keepalives: `: keepalive\n\n`.

---

## Health

| Method | Path      | Auth | Description                                   |
| ------ | --------- | ---- | --------------------------------------------- |
| GET    | `/health` | None | Liveness check. Returns `{ "status": "ok" }`. |
