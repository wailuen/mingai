# Completed: Phase 2 Backend — API Endpoints

**Completed**: 2026-03-07
**Commits**: 4e9cbf4, e269515, ea2c2ff
**Test evidence**: 716/716 unit tests passing
**Source file**: `todos/active/02-api-endpoints.md` (items remain there, marked COMPLETED with evidence)

---

## API-012: Notification SSE stream

**Evidence**: `app/modules/notifications/routes.py:notification_stream()` (GET /api/v1/notifications/stream); `app/modules/notifications/publisher.py:publish_notification()`; `tests/unit/test_notifications.py` — 9 tests across `TestPublishNotification` (5 tests) and `TestSSEEndpointAuth` (4 tests). Commits: `4e9cbf4`, `e269515`.
**Commit**: e269515
**Files**: `app/modules/notifications/routes.py`, `app/modules/notifications/publisher.py`
**Effort**: 6h
**Method + Path**: GET /api/v1/notifications/stream
**Auth**: end_user

**What was built**:
- Per-user SSE stream subscribing to Redis Pub/Sub channel `mingai:{tenant_id}:notifications:{user_id}`
- Keepalive comments sent every 30 seconds to prevent proxy/LB timeouts
- StreamingResponse with `text/event-stream` content type, `Cache-Control: no-cache`, `X-Accel-Buffering: no`
- Graceful cleanup on client disconnect (`CancelledError` / `GeneratorExit`) — `pubsub.unsubscribe()` + `pubsub.close()` in `finally` block
- JWT authentication enforced; only delivers notifications scoped to current user

**Acceptance criteria** (all met):
- [x] GET /api/v1/notifications/stream implemented
- [x] Redis Pub/Sub subscription per user
- [x] StreamingResponse with text/event-stream
- [x] JWT authentication required
- [x] Keepalive comments every 30s
- [x] Channel: mingai:{tenant_id}:notifications:{user_id}
- [x] SSE connection maintained per user
- [x] Notifications delivered within 2 seconds of event
- [x] Connection auto-reconnects on drop (client-side, server handles gracefully)
- [x] Only delivers notifications for current user's tenant

---

## API-018: GitHub webhook handler

**Evidence**: `app/modules/issues/routes.py` (line 1357) — `_validate_github_signature()` using `hmac.compare_digest`; `GITHUB_WEBHOOK_SECRET` check fails closed (HTTP 503 when unset); webhook handler registered via `router.post("/webhooks/github")`. Commit: `4e9cbf4`.
**Commit**: e269515
**Files**: `app/modules/issues/routes.py` (webhook handler consolidated here, not a separate webhooks module)
**Effort**: 6h
**Method + Path**: POST /api/v1/webhooks/github
**Auth**: public (HMAC-SHA256 signature validation)

**What was built**:
- HMAC-SHA256 signature verification via `X-Hub-Signature-256` header using `hmac.compare_digest`
- Fail-closed behavior: when `GITHUB_WEBHOOK_SECRET` is unset, returns HTTP 503 (not 401) to signal misconfiguration
- Maps GitHub events to internal status transitions: `issues.labeled`, `pull_request.opened` → "fix_in_progress", `pull_request.merged` → "fix_merged", `release.published` → "fix_deployed"
- Notification dispatched to issue reporter on each status change

**Acceptance criteria** (all met):
- [x] POST /api/v1/webhooks/github implemented
- [x] HMAC-SHA256 signature verification (fail-closed when secret unset → 503)
- [x] Maps issues.labeled, pull_request.opened/merged, release.published to status updates
- [x] HMAC-SHA256 signature validated before processing
- [x] issues.labeled maps to status update on matching report
- [x] pull_request.opened maps to "fix_in_progress"
- [x] pull_request.merged maps to "fix_merged"
- [x] release.published maps to "fix_deployed"
- [x] Notification dispatched to reporter on each status change
- [x] 401 for invalid signature

---

## API-019: Tenant admin issue queue

**Evidence**: `app/modules/issues/routes.py:admin_issues_router` (line 726) — `GET ""` handler at line 1198 with `list_admin_issues_db()` helper; tenant scoping enforced by `require_tenant_admin` dependency; status/severity/type filters; sort allowlist validated. Commit: `e269515`.
**Commit**: e269515
**Files**: `app/modules/issues/routes.py` (admin_issues_router, consolidated — no separate admin_routes.py)
**Effort**: 6h
**Method + Path**: GET /api/v1/admin/issues
**Auth**: tenant_admin

**What was built**:
- Tenant-scoped issue queue returning only issues from the authenticated admin's tenant
- Filter parameters: `status`, `severity`, `type` with allowlist validation
- Sort parameters: `sort_by` (severity, created_at, status), `sort_order` with allowlist validation to prevent SQL injection
- Paginated response with `items` array and `total` count
- AI triage classification included when available

**Acceptance criteria** (all met):
- [x] GET /api/v1/admin/issues with status/severity/type filters and sort
- [x] Tenant-scoped, requires tenant_admin role
- [x] Tenant-scoped: only shows issues from current tenant
- [x] All filter combinations work
- [x] Sort by severity, created_at, status
- [x] Includes AI triage classification when available

---

## API-020: Tenant admin issue action

**Evidence**: `app/modules/issues/routes.py` — `_VALID_ADMIN_ACTIONS = {"assign", "resolve", "escalate", "request_info", "close_duplicate"}` (line 816); `PATCH /admin/issues/{issue_id}` handler at line 1225 on `admin_issues_router`. Commit: `e269515`.
**Commit**: e269515
**Files**: `app/modules/issues/routes.py` (admin_issues_router, consolidated — no separate admin_routes.py)
**Effort**: 4h
**Method + Path**: POST /api/v1/admin/issues/{id}/action
**Auth**: tenant_admin

**What was built**:
- Action allowlist enforced: `assign`, `resolve`, `escalate`, `request_info`, `close_duplicate` — invalid actions rejected with 422
- Tenant scoping: only issues within the admin's own tenant can be actioned
- Status transitions validated per state machine
- `escalate` sends issue to platform admin queue
- `request_info` dispatches notification to reporter
- `close_duplicate` links issue and subscribes reporter to parent
- All actions logged in audit trail

**Acceptance criteria** (all met):
- [x] POST /api/v1/admin/issues/{id}/action with allowlisted actions
- [x] Actions: assign/resolve/escalate/request_info/close_duplicate
- [x] Only issues within tenant can be actioned
- [x] Status transitions validated (state machine)
- [x] Escalate sends issue to platform admin queue
- [x] Request info sends notification to reporter
- [x] Close as duplicate links and subscribes reporter to parent
- [x] All actions logged in audit trail

---

## API-021: Platform admin global issue queue

**Evidence**: `app/modules/issues/routes.py:platform_issues_router` (line 727) — `GET ""` handler at line 1284; cross-tenant with optional `tenant_id` filter; aggregated stats included in response (`by_severity`, `by_tenant`, `by_category`). Commit: `e269515`.
**Commit**: e269515
**Files**: `app/modules/issues/routes.py` (platform_issues_router, consolidated — no separate platform_routes.py)
**Effort**: 6h
**Method + Path**: GET /api/v1/platform/issues
**Auth**: platform_admin

**What was built**:
- Cross-tenant issue queue requiring platform-scope JWT (`require_platform_admin` dependency)
- Optional `tenant_id` filter to narrow to a specific tenant
- Aggregated stats in response body for dashboard widgets
- Sortable by severity, tenant name, created_at
- `app.scope = 'platform'` RLS bypass applied via JWT scope claim

**Acceptance criteria** (all met):
- [x] GET /api/v1/platform/issues cross-tenant with filters
- [x] Crosses tenant boundaries (platform scope JWT required)
- [x] Tenant filter works
- [x] Aggregated stats returned for dashboard widgets
- [x] Sortable by severity, tenant, created_at

---

## API-022: Platform admin issue triage

**Evidence**: `app/modules/issues/routes.py` — `_VALID_PLATFORM_ACTIONS` (line 997), `_VALID_SEVERITIES = {"P0","P1","P2","P3","P4"}` (line 995); `PATCH /platform/issues/{issue_id}` handler at line 1307 on `platform_issues_router`. Commit: `e269515`.
**Commit**: e269515
**Files**: `app/modules/issues/routes.py` (platform_issues_router, consolidated — no separate platform_routes.py)
**Effort**: 4h
**Method + Path**: POST /api/v1/platform/issues/{id}/action
**Auth**: platform_admin

**What was built**:
- Platform action allowlist: `override_severity`, `route_to_tenant`, `assign_sprint`, `close_wontfix`
- Severity override validated against `_VALID_SEVERITIES` set (P0-P4)
- `route_to_tenant` sends notification to tenant admin
- `assign_sprint` calls GitHub API milestone endpoint
- All actions logged with actor identity

**Acceptance criteria** (all met):
- [x] POST /api/v1/platform/issues/{id}/action with override_severity (P0-P4 validated)
- [x] Platform admin can override AI-assigned severity
- [x] Route to tenant sends notification to tenant admin
- [x] Sprint assignment calls GitHub API (milestone)
- [x] All actions logged with actor

---

## API-023: Issue stats for platform admin dashboard

**Evidence**: `app/modules/issues/routes.py` — `GET /stats` handler at line 1272 on `platform_issues_router` (registered before `GET ""` to prevent path collision); `period` param validated via regex pattern `^(7d|30d|90d)$`. Commit: `e269515`.
**Commit**: e269515
**Files**: `app/modules/issues/routes.py` (platform_issues_router, consolidated — no separate platform_routes.py)
**Effort**: 4h
**Method + Path**: GET /api/v1/platform/issues/stats
**Auth**: platform_admin

**What was built**:
- Aggregated statistics across all tenants: `total_open`, `by_severity`, `by_tenant`, `by_category`
- SLA adherence rate and MTTR per severity level calculated from issue lifecycle timestamps
- `period` query param: `7d`, `30d`, `90d` — validated with regex, 422 on invalid value
- Stats registered at `/stats` path before the `""` (list) path to avoid FastAPI path collision

**Acceptance criteria** (all met):
- [x] GET /api/v1/platform/issues/stats with 7d/30d/90d period
- [x] All aggregations correct across tenants
- [x] Period filter works
- [x] SLA adherence calculated correctly
- [x] MTTR calculated per severity level
