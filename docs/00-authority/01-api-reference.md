# API Reference — mingai Backend

Base URL: `http://localhost:8022/api/v1`

Auth: `Authorization: Bearer <jwt>` on all endpoints except `/auth/local/login`.

Auth roles: `end_user`, `tenant_admin`, `platform_admin`. Scope: `tenant` or `platform`.

---

## Auth

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/local/login` | None | Bootstrap login (platform admin from env vars). Returns JWT v2. |
| POST | `/auth/token/refresh` | Any | Re-issue token with current claims. |
| POST | `/auth/logout` | Any | Session logout (Phase 1: no-op; no token revocation). |
| GET | `/auth/current` | Any | Current user — id, tenant_id, roles, scope, plan, email. |

Login body: `{ "email": str, "password": str }`. Returns `{ "access_token", "token_type", "expires_in" }`.

---

## Chat

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/chat/stream` | Any | SSE streaming chat. Body: `{ "query", "agent_id", "conversation_id"?, "active_team_id"? }`. |
| POST | `/chat/feedback` | Any | Thumbs up/down on a message. Body: `{ "message_id", "rating": "up"\|"down", "comment"? }`. |
| GET | `/conversations` | Any | List conversations (paginated: `page`, `page_size`). |
| GET | `/conversations/{id}` | Any | Get conversation with messages. |
| DELETE | `/conversations/{id}` | Any | Delete conversation. |

---

## Issues

### End-User Issue Reporting

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/issues` | Any | Create issue. `screenshot_url` requires `blur_acknowledged=true`. |
| GET | `/issues/{id}` | Any | Get issue. Admin sees all; others see own only. |
| GET | `/issue-reports/presign` | Any | Get presigned upload URL. Query params: `filename`, `content_type` (image/png or image/jpeg). |
| GET | `/my-reports` | Any | Current user's own reports (paginated). |
| GET | `/my-reports/{id}` | Any | Detail of own report with timeline. |
| POST | `/issue-reports/{id}/still-happening` | Any | Report regression. Creates linked report; auto-escalates or routes to human review. |

### Tenant Admin Issue Queue (API-019/020)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/admin/issues` | tenant_admin | List tenant issues. Query params: `status`, `severity`, `page`, `page_size`. Results scoped to caller's tenant via RLS. |
| PATCH | `/issues/{id}/status` | tenant_admin | Update status: `open`, `investigating`, `resolved`, `closed`. |
| POST | `/issues/{id}/events` | tenant_admin | Add comment/event to issue log. |
| POST | `/admin/issues/{id}/action` | tenant_admin | State machine action. Body: `{ "action": "assign"\|"resolve"\|"escalate"\|"request_info"\|"close_duplicate", "payload"?: {} }`. Unknown actions → 422. |

### Platform Issue Queue (API-021/022/023)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/platform/issues` | platform_admin | Cross-tenant issue list. Query params: `tenant_id`?, `severity`, `status`, `page`, `page_size`. |
| POST | `/platform/issues/{id}/action` | platform_admin | Triage action. Body: `{ "action": "override_severity"\|"route_to_tenant"\|"assign_sprint"\|"close_wontfix", "payload"?: {} }`. Unknown actions → 422. |
| GET | `/platform/issues/stats` | platform_admin | Aggregated issue stats. Query param: `period=7d\|30d\|90d`. Returns counts by severity and status across all tenants. |

### GitHub Webhook (API-018)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/webhooks/github` | HMAC-SHA256 | GitHub event ingestion. Validates `X-Hub-Signature-256` header. Returns 503 if `GITHUB_WEBHOOK_SECRET` not configured. |

Supported events → status transitions:

| Event | Status applied |
|---|---|
| `issues.labeled` | `triaged` |
| `pull_request.opened` | `fix_in_progress` |
| `pull_request.merged` | `fix_merged` |
| `release.published` | `fix_deployed` |

Unrecognized events return `{ "processed": false }` with status 200.

---

## Platform Admin

All require `scope=platform` (i.e. `platform_admin` role).

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/admin/dashboard` | platform_admin | Dashboard stats: active_users, documents_indexed, queries_today, satisfaction_pct. |
| GET | `/platform/tenants` | platform_admin | List all tenants (paginated). |
| POST | `/platform/tenants` | platform_admin | Provision tenant. Body: `{ "name", "plan", "primary_contact_email", "slug"? }`. |
| GET | `/platform/tenants/{id}` | platform_admin | Get tenant. |
| PATCH | `/platform/tenants/{id}` | platform_admin | Update tenant name/plan/contact/status. |
| POST | `/platform/tenants/{id}/suspend` | platform_admin | Suspend tenant. |
| POST | `/platform/tenants/{id}/activate` | platform_admin | Reactivate suspended tenant. |
| GET | `/platform/tenants/{id}/health` | platform_admin | Health score (0–100) with 4 weighted components. |
| GET | `/platform/llm-profiles` | platform_admin | List all LLM profiles across tenants. |
| POST | `/platform/llm-profiles` | platform_admin | Create LLM profile. Body: `{ "tenant_id", "name", "provider", "primary_model", "intent_model", "embedding_model", "endpoint_url"?, "api_key_ref"?, "is_default" }`. |
| GET | `/platform/llm-profiles/{id}` | platform_admin | Get LLM profile. |
| PATCH | `/platform/llm-profiles/{id}` | platform_admin | Update LLM profile fields. |
| DELETE | `/platform/llm-profiles/{id}` | platform_admin | Delete profile. 409 if assigned to a tenant. |
| GET | `/platform/stats` | platform_admin | Platform stats: total_tenants, active_tenants, total_users, queries_today. |
| GET | `/platform/issues` | platform_admin | Cross-tenant issue list. See Issues → Platform Issue Queue above. |
| POST | `/platform/issues/{id}/action` | platform_admin | Triage action. See Issues → Platform Issue Queue above. |
| GET | `/platform/issues/stats` | platform_admin | Issue stats with period filter. See Issues → Platform Issue Queue above. |

---

## Users

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/users` | tenant_admin | List users in tenant (paginated). |
| POST | `/users` | tenant_admin | Invite user. Body: `{ "email": EmailStr, "role", "name"? }`. |
| GET | `/users/me` | Any | Current user profile. |
| PATCH | `/users/me` | Any | Update own profile: `name`, `preferences`. |
| GET | `/users/{id}` | tenant_admin | Get user by ID. |
| PATCH | `/users/{id}` | tenant_admin | Update user: `role`, `name`, `is_active`. |
| DELETE | `/users/{id}` | tenant_admin | Deactivate user. |
| POST | `/users/me/gdpr/export` | Any | Export user data package. |
| POST | `/users/me/gdpr/erase` | Any | GDPR erasure — clears all 3 stores (DB, Redis, profile). |

---

## Teams

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/teams` | Any | List teams in tenant. |
| POST | `/teams` | tenant_admin | Create team. |
| GET | `/teams/{id}` | Any | Get team details. |
| PATCH | `/teams/{id}` | tenant_admin | Update team. |
| DELETE | `/teams/{id}` | tenant_admin | Delete team. |
| POST | `/teams/{id}/members` | tenant_admin | Add member. |
| DELETE | `/teams/{id}/members/{uid}` | tenant_admin | Remove member. |
| GET | `/teams/{id}/memory` | Any | Get anonymized team working memory. |

---

## Glossary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/glossary` | Any | List terms (paginated). |
| POST | `/glossary` | tenant_admin | Create term. Body: `{ "term", "full_form", "aliases"? }`. |
| POST | `/glossary/import` | tenant_admin | Bulk CSV import. Multipart file upload. |
| GET | `/glossary/{id}` | Any | Get term. |
| PATCH | `/glossary/{id}` | tenant_admin | Update term. |
| DELETE | `/glossary/{id}` | tenant_admin | Delete term. Invalidates Redis cache. |

All writes invalidate `mingai:{tenant_id}:glossary_terms` in Redis.

---

## Memory

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/memory/notes` | Any | List user's memory notes. |
| POST | `/memory/notes` | Any | Create note (max 200 chars). |
| DELETE | `/memory/notes/{id}` | Any | Delete specific note. |
| DELETE | `/memory/notes` | Any | Clear all notes for user. |
| PATCH | `/memory/privacy` | Any | Toggle `profile_learning_enabled`, `working_memory_enabled`. |
| GET | `/memory/profile` | Any | Get user profile with learning data. |
| DELETE | `/memory/profile` | Any | GDPR comprehensive erasure. |
| GET | `/memory/working` | Any | Get working memory summary. |
| DELETE | `/memory/working` | Any | Clear working memory (Redis). |
| GET | `/memory/export` | Any | Export all profile data (GDPR). |

---

## Workspace (Tenant Admin)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/admin/workspace` | tenant_admin | Get workspace settings (name, timezone, locale, notification_preferences). |
| PATCH | `/admin/workspace` | tenant_admin | Update workspace settings. Allowlisted fields only. |

---

## Documents — SharePoint

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/documents/sharepoint/connect` | tenant_admin | Create SharePoint connection. Credentials stored as vault ref only. |
| POST | `/documents/sharepoint/{id}/test` | tenant_admin | Test connection health. |
| POST | `/documents/sharepoint/{id}/sync` | tenant_admin | Trigger document sync job. |
| GET | `/documents/sharepoint/{id}/sync` | tenant_admin | List sync job history. |

---

## HAR A2A Transactions (AI-040 to AI-051)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/har/transactions` | tenant_admin | Create HAR transaction. Body: `{initiator_agent_id, counterparty_agent_id, amount?, currency?, payload?}`. Sets `requires_human_approval=true` and 48h deadline if amount ≥ $5,000. Returns 201 with `{id, state, requires_human_approval}`. |
| GET | `/har/transactions` | tenant_admin | List transactions. Query: `?state=DRAFT\|OPEN\|...&page=1&page_size=20`. |
| GET | `/har/transactions/{txn_id}` | tenant_admin | Get transaction detail with all fields. |
| POST | `/har/transactions/{txn_id}/transition` | tenant_admin | Advance state machine. Body: `{new_state}`. Returns updated transaction. 400 on invalid transition. |
| POST | `/har/transactions/{txn_id}/approve` | tenant_admin | Human approval for high-value transactions. Sets `human_approved_at`, transitions to COMMITTED. 400 if approval not required. |
| POST | `/har/transactions/{txn_id}/reject` | tenant_admin | Human rejection. Transitions to ABANDONED. 400 if approval not required. |

### Agents — Keypair & Trust (AI-040, AI-046)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/agents/templates/{agent_id}/public-key` | tenant_admin | Get Ed25519 public key for signature verification. 404 if keypair not yet generated. |
| POST | `/agents/templates/{agent_id}/compute-trust-score` | tenant_admin | Recompute and persist trust score for an agent. Returns `{agent_id, trust_score}`. |

### HAR State Transitions

Valid transitions: `DRAFT→OPEN→NEGOTIATING→COMMITTED→EXECUTING→COMPLETED`. Also: `OPEN|NEGOTIATING|COMMITTED→ABANDONED`, `EXECUTING→DISPUTED`, `DISPUTED→RESOLVED`. Terminal: COMPLETED, ABANDONED, RESOLVED.

---

## Storage (Local Dev Only)

Available when `CLOUD_PROVIDER=local`. Internal endpoints, not part of the external API contract.

| Method | Path | Description |
|--------|------|-------------|
| PUT | `/storage/upload` | HMAC-signed upload target for local dev. |
| GET | `/storage/serve/{path}` | Serve stored file. |

---

## Notifications (API-012)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/notifications/stream` | Any | SSE notification stream. `Content-Type: text/event-stream`. Keepalive comment every 30s. Closes when client disconnects. |

The stream delivers JSON payloads published to `mingai:{tenant_id}:notifications:{user_id}` via Redis Pub/Sub. Each event line: `data: {json}\n\n`. Keepalives: `: keepalive\n\n`.

---

## Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Liveness check. Returns `{ "status": "ok" }`. |
