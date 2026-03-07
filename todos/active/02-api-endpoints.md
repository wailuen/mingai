# 02 — API Endpoints & Backend Services

**Generated**: 2026-03-07
**Total endpoints**: 120
**Numbering**: API-001 through API-120
**Stack**: FastAPI + Kailash Nexus + PostgreSQL + Redis + Auth0
**Base path**: `/api/v1`

---

## Plan 01 — Foundation Phase 1

### API-001: JWT v2 validation middleware ✅ COMPLETED

**Effort**: 8h
**Depends on**: none
**Method + Path**: Middleware (all routes)
**Auth**: all roles
**Description**: FastAPI middleware that validates JWT tokens, extracts `tenant_id`, `scope`, `roles`, `plan`, and `token_version` from claims. Dual-accept window: v1 tokens (no tenant_id) treated as `tenant_id="default"`, `scope="tenant"`, `plan="professional"` for 30 days. Sets `app.tenant_id` and `app.scope` on every DB connection via `SET` commands. Injects user context into `request.state`.
**Request**: Authorization header (Bearer token)
**Response**: 401 if invalid/expired; 403 if tenant suspended; passes through on success
**Acceptance criteria**:

- [ ] v2 tokens with `tenant_id`, `scope`, `plan` claims validated correctly
- [ ] v1 tokens accepted with default values during dual-accept window
- [ ] `SET app.tenant_id` and `SET app.scope` executed on every DB connection
- [ ] 401 returned for expired/invalid tokens
- [ ] 401 returned for suspended tenants
- [ ] `request.state.user` populated with user_id, tenant_id, scope, roles, plan
      **Notes**: This is the foundation for ALL subsequent endpoints. Must ship first. See `01-backend-instructions.md` Step 3.

---

### API-002: Platform health check ✅ COMPLETED

**Effort**: 2h
**Depends on**: none
**Method + Path**: GET /api/v1/health
**Auth**: public
**Description**: Returns platform health status including database connectivity, Redis connectivity, and search service status. Used by load balancers and monitoring.
**Request**: none
**Response**: `{ "status": "healthy", "database": "ok", "redis": "ok", "search": "ok", "version": "1.0.0" }`
**Acceptance criteria**:

- [ ] Returns 200 with component-level health when all services up
- [ ] Returns 503 with degraded component details when any service down
- [ ] No authentication required
- [ ] Response time < 500ms
      **Notes**: Exempt from JWT middleware via `exempt_paths`.

---

### API-003: Auth local login ✅ COMPLETED

**Effort**: 4h
**Depends on**: API-001
**Method + Path**: POST /api/v1/auth/local/login
**Auth**: public
**Description**: Local username/password authentication for development environments and tenants without SSO. Returns JWT v2 access token.
**Request**: `{ "email": "string", "password": "string" }`
**Response**: `{ "access_token": "string", "token_type": "bearer", "expires_in": 900 }`
**Acceptance criteria**:

- [ ] Returns valid JWT v2 token with tenant_id, scope, roles, plan claims
- [ ] Password verified against bcrypt hash
- [ ] Rate limited: 10 attempts per email per 15 minutes
- [ ] 401 for invalid credentials (generic message, no email enumeration)
- [ ] Logs login event to audit log
      **Notes**: Auth0 integration in Phase 3 replaces this for production SSO tenants. Local login always remains as fallback.

---

### API-004: Token refresh ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: POST /api/v1/auth/token/refresh
**Auth**: end_user (valid refresh token)
**Description**: Refreshes an expiring access token. Returns new access token with same claims.
**Request**: `{ "refresh_token": "string" }`
**Response**: `{ "access_token": "string", "token_type": "bearer", "expires_in": 900 }`
**Acceptance criteria**:

- [ ] Validates refresh token not expired and not revoked
- [ ] Issues new access token with current claims (re-reads roles from DB)
- [ ] Old refresh token invalidated (rotation)
- [ ] 401 for expired/revoked refresh tokens
      **Notes**: 15-minute access token, 7-day refresh token.

---

### API-005: Logout ✅ COMPLETED

**Effort**: 2h
**Depends on**: API-001
**Method + Path**: POST /api/v1/auth/logout
**Auth**: end_user
**Description**: Invalidates current session. Revokes refresh token in Redis.
**Request**: none (token from Authorization header)
**Response**: 204 No Content
**Acceptance criteria**:

- [ ] Refresh token revoked in Redis blacklist
- [ ] Subsequent requests with same access token still work until expiry (stateless JWT)
- [ ] Subsequent refresh attempts with revoked token fail
      **Notes**: Access token is stateless; logout only revokes refresh token.

---

### API-006: Get current user ✅ COMPLETED

**Effort**: 2h
**Depends on**: API-001
**Method + Path**: GET /api/v1/auth/current
**Auth**: end_user
**Description**: Returns current authenticated user profile from JWT claims and database.
**Request**: none
**Response**: `{ "id": "uuid", "email": "string", "name": "string", "tenant_id": "uuid", "roles": ["string"], "plan": "string", "scope": "string" }`
**Acceptance criteria**:

- [ ] Returns user data matching JWT claims
- [ ] Includes current roles from database (not just JWT cache)
- [ ] 401 if not authenticated
      **Notes**: Frontend calls this on app load to validate session.

---

### API-007: Response feedback ✅ COMPLETED

**Effort**: 4h
**Depends on**: API-001
**Method + Path**: POST /api/v1/feedback
**Auth**: end_user
**Description**: Records thumbs up/down feedback on an AI response message. Stored with tenant_id, message_id, user_id. Label in UI is "retrieval confidence" (canonical spec).
**Request**: `{ "message_id": "uuid", "rating": 1 | -1, "tags": ["string"], "comment": "string | null" }`
**Response**: `{ "id": "uuid", "status": "recorded" }`
**Acceptance criteria**:

- [ ] Rating constrained to 1 (thumbs up) or -1 (thumbs down)
- [ ] message_id validated to exist and belong to current user's tenant
- [ ] Duplicate feedback for same message_id + user_id updates existing record
- [ ] Tags from predefined list validated
- [ ] Tenant admin flagging: messages with 3+ negative ratings auto-flagged
      **Notes**: Schema in `user_feedback` table per migration plan.

---

## Plan 01 — Chat & SSE

### API-008: Chat stream ✅ COMPLETED

**Effort**: 16h
**Depends on**: API-001, API-007
**Method + Path**: POST /api/v1/chat/stream
**Auth**: end_user
**Description**: Main chat endpoint. Accepts user query, runs full RAG pipeline, returns SSE stream. Includes "remember that..." fast path detection for memory notes. Verifies user has access to requested agent and its KBs via JWT claims.
**Request**: `{ "conversation_id": "uuid | null", "query": "string", "agent_id": "uuid | null", "index_ids": ["uuid"] }`
**Response**: SSE stream with events: `status`, `sources`, `response_chunk`, `metadata`, `profile_context_used`, `memory_saved`, `cache_state`, `glossary_expansions_applied`, `done`, `error`
**Acceptance criteria**:

- [ ] SSE stream starts within 500ms of request
- [ ] `status` event sent for each pipeline stage (searching, synthesizing)
- [ ] `sources` event contains title, score, url for each source document
- [ ] `response_chunk` events stream token-by-token
- [ ] `metadata` event includes `retrieval_confidence` (labeled correctly), `tokens_used`, model name
- [ ] `profile_context_used` event when profile learning influences response
- [ ] `memory_saved` event when "remember that..." fast path triggers
- [ ] `cache_state` event with hit/miss, similarity score, response age
- [ ] `glossary_expansions_applied` lists terms expanded inline
- [ ] `done` event with conversation_id and message_id
- [ ] `error` event on pipeline failure with user-safe message
- [ ] "remember that..." query detected and routed to memory note creation
- [ ] Agent and KB access verified from JWT claims before proceeding
- [ ] New conversation created if conversation_id is null
      **Notes**: This is the highest-complexity endpoint. Pipeline: JWT validation > intent detection > glossary expansion > embedding > vector search > context building (profile, memory, org context, team memory, glossary) > LLM synthesis > streaming. See integration guide SSE protocol.

---

### API-009: List conversations ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/conversations
**Auth**: end_user
**Description**: Returns paginated list of user's conversations within their tenant, sorted by last activity.
**Request**: Query params: `page`, `page_size`, `agent_id` (optional filter)
**Response**: `{ "items": [{ "id": "uuid", "title": "string", "agent_id": "uuid", "last_message_at": "ISO-8601", "message_count": int }], "total": int, "page": int }`
**Acceptance criteria**:

- [ ] Only returns conversations belonging to current user + tenant (RLS enforced)
- [ ] Paginated with default page_size=20, max=100
- [ ] Optional agent_id filter works
- [ ] Sorted by last_message_at descending
      **Notes**: RLS on conversations table ensures tenant isolation.

---

### API-010: Create conversation ✅ COMPLETED

**Effort**: 2h
**Depends on**: API-001
**Method + Path**: POST /api/v1/conversations
**Auth**: end_user
**Description**: Creates a new conversation record.
**Request**: `{ "title": "string | null", "agent_id": "uuid | null" }`
**Response**: `{ "id": "uuid", "title": "string", "agent_id": "uuid", "created_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Conversation created with current user's tenant_id
- [ ] Auto-generates title from first query if null
- [ ] agent_id validated if provided (must be accessible to user)
      **Notes**: Chat stream endpoint auto-creates conversations if conversation_id is null, so this is mainly for explicit creation.

---

### API-011: Get conversation messages ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/conversations/{id}/messages
**Auth**: end_user
**Description**: Returns paginated message history for a conversation.
**Request**: Query params: `page`, `page_size`, `before` (cursor)
**Response**: `{ "items": [{ "id": "uuid", "role": "user|assistant", "content": "string", "sources": [], "metadata": {}, "created_at": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [ ] 404 if conversation not found or belongs to different tenant
- [ ] Messages ordered by created_at ascending
- [ ] Includes source documents and metadata for assistant messages
- [ ] Cursor-based pagination for efficient scrolling
      **Notes**: Frontend loads this when user opens a conversation.

---

### API-012: Notification SSE stream

**Effort**: 6h
**Depends on**: API-001
**Method + Path**: GET /api/v1/notifications/stream
**Auth**: end_user
**Description**: Per-user SSE stream for real-time notification delivery. Used for issue report status updates, access request approvals, sync failure alerts.
**Request**: none (long-lived SSE connection)
**Response**: SSE events: `{ "id": "uuid", "type": "string", "title": "string", "body": "string", "link": "string | null", "read": false, "created_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] SSE connection maintained per user
- [ ] Notifications delivered within 2 seconds of event
- [ ] Connection auto-reconnects on drop (client-side, but server must handle reconnection gracefully)
- [ ] Only delivers notifications for current user's tenant
      **Notes**: Backend publishes to Redis Pub/Sub channel per user; SSE endpoint subscribes.

---

## Plan 04 — Issue Reporting

### API-013: Submit issue report ✅ COMPLETED

**Effort**: 6h
**Depends on**: API-001
**Method + Path**: POST /api/v1/issue-reports
**Auth**: end_user
**Description**: Submit a bug report with automatic context capture. Enqueues to Redis Stream for async AI triage. Rate limited: 10/user/day, 50/tenant/day. Feature requests (type="feature") routed separately to product backlog, not bug triage queue.
**Request**: `{ "title": "string (max 200)", "description": "string (max 10000)", "type": "bug|performance|ux|feature", "severity_hint": "high|medium|low|suggestion|null", "screenshot_blob_url": "string|null", "screenshot_annotations": "Annotation[]|null", "session_context": { "url": "string", "last_query": "string", "console_errors": ["string"], "browser": "string", "agent_id": "uuid|null" } }`
**Response**: 201: `{ "id": "rpt_abc123", "status": "received", "message": "Report submitted successfully" }`
**Acceptance criteria**:

- [ ] Title max 200 chars, description max 10000 chars validated
- [ ] Type enum validated
- [ ] Rate limit: 10/user/day returns 429 with retry_after
- [ ] Rate limit: 50/tenant/day returns 429
- [ ] Issue stored in PostgreSQL `issue_reports` table with tenant_id
- [ ] Enqueued to Redis Stream `issue_reports:incoming`
- [ ] Console errors sanitized (credentials/tokens stripped)
- [ ] Feature type issues flagged for separate routing
      **Notes**: Screenshot upload handled via pre-signed URL (API-014). RAG response area in screenshots must be blurred by default (frontend enforcement, R4.1 CRITICAL).

---

### API-014: Get screenshot pre-signed URL ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/issue-reports/presign
**Auth**: end_user
**Description**: Returns a pre-signed URL for direct screenshot upload to object storage (S3/Azure Blob/GCS per CLOUD_PROVIDER). Tenant-scoped path isolation.
**Request**: Query params: `filename`, `content_type`
**Response**: `{ "upload_url": "string", "blob_url": "string", "expires_in": 300 }`
**Acceptance criteria**:

- [x] Pre-signed URL scoped to tenant's storage path
- [x] URL expires in 5 minutes
- [x] Content type restricted to image/png, image/jpeg
- [x] Max file size: 10MB enforced by storage policy
      **Notes**: Uses ObjectStore abstraction (S3/Azure Blob/GCS per CLOUD_PROVIDER). Cloud-agnostic: aws/azure/gcp/local backends. Files: `app/core/storage.py`, `app/core/local_storage_routes.py`, `app/modules/issues/routes.py`. Tests: `tests/unit/test_storage.py`, `tests/unit/test_issues_routes.py` (TestPresignScreenshotUpload). Committed: fe1d212.

---

### API-015: List user's issue reports ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-013
**Method + Path**: GET /api/v1/my-reports
**Auth**: end_user
**Description**: Returns paginated list of current user's submitted issue reports with status badges.
**Request**: Query params: `page`, `page_size`, `status` (filter)
**Response**: `{ "items": [{ "id": "string", "title": "string", "type": "string", "status": "string", "severity": "string", "created_at": "ISO-8601", "updated_at": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [x] Only returns reports submitted by current user within their tenant
- [x] Status filter works (received, triaging, in_progress, resolved, closed, wont_fix)
- [x] Paginated with default page_size=20
- [x] Sorted by created_at descending
      **Notes**: Helper: `list_my_issues_db()`. Tests: TestListMyReports in `tests/unit/test_issues_routes.py`. Committed: 7cd0e1d.

---

### API-016: Get issue report detail ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-013
**Method + Path**: GET /api/v1/my-reports/{id}
**Auth**: end_user
**Description**: Returns full detail of a specific issue report including timeline, AI triage result, and GitHub issue link.
**Request**: none
**Response**: `{ "id": "string", "title": "string", "description": "string", "type": "string", "status": "string", "severity": "string", "ai_triage": { "severity": "string", "category": "string", "root_cause_hypothesis": "string" }, "github_issue_url": "string|null", "timeline": [{ "event": "string", "timestamp": "ISO-8601", "actor": "string" }], "created_at": "ISO-8601" }`
**Acceptance criteria**:

- [x] 404 if report not found or belongs to different user/tenant
- [x] Timeline includes all status transitions
- [x] AI triage result included when available
- [x] GitHub issue link included when created
      **Notes**: Helper: `get_my_issue_db()`. Tests: TestGetMyReport in `tests/unit/test_issues_routes.py`. Committed: 7cd0e1d. Links to related duplicate parent issue if flagged as duplicate.

---

### API-017: Still happening confirmation ✅ COMPLETED

**Effort**: 4h
**Depends on**: API-013
**Method + Path**: POST /api/v1/issue-reports/{id}/still-happening
**Auth**: end_user
**Description**: User confirms issue is still occurring after a fix was deployed. Rate limited: max 1 auto-escalation per fix deployment. Second occurrence triggers human review.
**Request**: `{ "additional_context": "string|null" }`
**Response**: `{ "status": "regression_reported", "new_report_id": "string" }`
**Acceptance criteria**:

- [x] Only callable when report status is "resolved" or "fix_deployed"
- [x] Rate limited: 1 per fix deployment per original report
- [x] Creates new linked regression report
- [x] Second "still happening" on same fix triggers human review flag
- [x] Notifies assigned engineer
      **Notes**: Implements closed-loop regression detection via StillHappeningRateLimiter. Helper: `record_still_happening_db()`. Tests: TestStillHappening in `tests/unit/test_issues_routes.py`. Committed: 7cd0e1d.

---

### API-018: GitHub webhook handler

**Effort**: 6h
**Depends on**: API-013
**Method + Path**: POST /api/v1/webhooks/github
**Auth**: public (HMAC-SHA256 signature validation)
**Description**: Receives GitHub webhook events and updates issue report status. Maps: issues.labeled, pull_request.opened, pull_request.merged, release.published to internal status transitions. Dispatches notifications to reporters.
**Request**: GitHub webhook payload with X-Hub-Signature-256 header
**Response**: 200 OK
**Acceptance criteria**:

- [ ] HMAC-SHA256 signature validated before processing
- [ ] issues.labeled maps to status update on matching report
- [ ] pull_request.opened maps to "fix_in_progress"
- [ ] pull_request.merged maps to "fix_merged"
- [ ] release.published maps to "fix_deployed"
- [ ] Notification dispatched to reporter on each status change
- [ ] 401 for invalid signature
      **Notes**: GitHub bot account credentials from .env. Webhook secret for HMAC validation from .env.

---

### API-019: Tenant admin issue queue

**Effort**: 6h
**Depends on**: API-013
**Method + Path**: GET /api/v1/admin/issues
**Auth**: tenant_admin
**Description**: Returns tenant-scoped issue queue with filtering and sorting. Shows issues reported by users in this tenant.
**Request**: Query params: `page`, `page_size`, `status`, `severity`, `type`, `sort_by`, `sort_order`
**Response**: `{ "items": [{ "id": "string", "title": "string", "reporter": { "id": "uuid", "name": "string" }, "type": "string", "status": "string", "severity": "string", "ai_classification": "string", "created_at": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [ ] Tenant-scoped: only shows issues from current tenant
- [ ] All filter combinations work
- [ ] Sort by severity, created_at, status
- [ ] Includes AI triage classification when available
      **Notes**: Tenant admin can route, resolve, escalate from this queue.

---

### API-020: Tenant admin issue action

**Effort**: 4h
**Depends on**: API-019
**Method + Path**: PATCH /api/v1/admin/issues/{id}
**Auth**: tenant_admin
**Description**: Perform actions on an issue: assign, resolve, escalate to platform, request more info, close as duplicate.
**Request**: `{ "action": "assign|resolve|escalate|request_info|close_duplicate", "assignee_id": "uuid|null", "note": "string|null", "duplicate_of": "string|null" }`
**Response**: `{ "id": "string", "status": "string", "updated_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Only issues within tenant can be actioned
- [ ] Status transitions validated (state machine)
- [ ] Escalate sends issue to platform admin queue
- [ ] Request info sends notification to reporter
- [ ] Close as duplicate links and subscribes reporter to parent
- [ ] All actions logged in audit trail
      **Notes**: Implements engineering queue actions from Plan 04 Phase 4.

---

### API-021: Platform admin global issue queue

**Effort**: 6h
**Depends on**: API-013
**Method + Path**: GET /api/v1/platform/issues
**Auth**: platform_admin
**Description**: Cross-tenant global issue queue. Shows all issues across all tenants with heatmap data.
**Request**: Query params: `page`, `page_size`, `status`, `severity`, `tenant_id`, `sort_by`
**Response**: `{ "items": [{ "id": "string", "title": "string", "tenant": { "id": "uuid", "name": "string" }, "reporter": { "name": "string" }, "type": "string", "status": "string", "severity": "string", "ai_classification": "string", "created_at": "ISO-8601" }], "total": int, "stats": { "by_severity": {}, "by_tenant": {}, "by_category": {} } }`
**Acceptance criteria**:

- [ ] Crosses tenant boundaries (platform scope JWT required)
- [ ] Tenant filter works
- [ ] Aggregated stats returned for dashboard widgets
- [ ] Sortable by severity, tenant, created_at
      **Notes**: Platform scope bypasses RLS via `app.scope = 'platform'` setting.

---

### API-022: Platform admin issue triage

**Effort**: 4h
**Depends on**: API-021
**Method + Path**: PATCH /api/v1/platform/issues/{id}
**Auth**: platform_admin
**Description**: Platform admin triage actions: override severity, route to tenant, assign to engineering sprint, close as won't fix.
**Request**: `{ "action": "override_severity|route_to_tenant|assign_sprint|close_wontfix", "severity": "string|null", "sprint": "string|null", "note": "string" }`
**Response**: `{ "id": "string", "status": "string", "updated_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Platform admin can override AI-assigned severity
- [ ] Route to tenant sends notification to tenant admin
- [ ] Sprint assignment calls GitHub API (milestone)
- [ ] All actions logged with actor
      **Notes**: Implements Phase 4 analytics actions from Plan 05.

---

### API-023: Issue stats for platform admin dashboard

**Effort**: 4h
**Depends on**: API-021
**Method + Path**: GET /api/v1/platform/issues/stats
**Auth**: platform_admin
**Description**: Aggregated issue statistics for the platform admin dashboard. Heatmap data, SLA adherence, MTTR.
**Request**: Query params: `period` (7d, 30d, 90d)
**Response**: `{ "total_open": int, "by_severity": {}, "by_tenant": {}, "by_category": {}, "sla_adherence_rate": float, "mttr_by_severity": {}, "top_bugs_by_volume": [], "week_over_week_trend": [] }`
**Acceptance criteria**:

- [ ] All aggregations correct across tenants
- [ ] Period filter works
- [ ] SLA adherence calculated correctly
- [ ] MTTR calculated per severity level
      **Notes**: Feeds the platform admin issues dashboard (Plan 05 Phase C1).

---

## Plan 05 — Platform Admin

### API-024: Provision new tenant ✅ COMPLETED

**Effort**: 12h
**Depends on**: API-001
**Method + Path**: POST /api/v1/platform/tenants
**Auth**: platform_admin
**Description**: Initiates async tenant provisioning. Creates tenant record (status: Provisioning), enqueues provisioning job to Redis Stream. Worker provisions: PostgreSQL schema + RLS, search index, object store bucket, Redis namespace, Stripe customer, invite email. Returns job_id for SSE status tracking. Rollback on any step failure after 3 retries.
**Request**: `{ "name": "string", "plan": "starter|professional|enterprise", "admin_email": "string", "admin_name": "string", "llm_profile_id": "uuid|null", "quotas": { "monthly_token_limit": int, "storage_gb": int, "users_max": int } }`
**Response**: 202: `{ "tenant_id": "uuid", "job_id": "uuid", "status": "provisioning" }`
**Acceptance criteria**:

- [ ] Tenant record created with status "Provisioning"
- [ ] Provisioning job enqueued to Redis Stream
- [ ] All 6 resource types provisioned (DB, search, storage, Redis, Stripe, email)
- [ ] Provisioning completes in < 10 minutes (P95)
- [ ] On any step failure after 3 retries: status set to "ProvisioningFailed", cleanup job runs
- [ ] Admin invite email sent on success
- [ ] SSE notification to platform admin on completion
      **Notes**: Kailash Core SDK workflow for orchestration. See Plan 05 provisioning architecture.

---

### API-025: Get provisioning job status (SSE) ✅ COMPLETED

**Effort**: 4h
**Depends on**: API-024
**Method + Path**: GET /api/v1/platform/provisioning/{job_id}
**Auth**: platform_admin
**Description**: SSE stream for provisioning job progress. Emits events for each provisioning step.
**Request**: none (SSE connection)
**Response**: SSE events: `{ "step": "string", "status": "pending|running|completed|failed", "message": "string" }`
**Acceptance criteria**:

- [x] Events emitted for each of 6 provisioning steps
- [x] Final event is "completed" or "failed"
- [x] Job_id validated and scoped to platform
      **Notes**: Platform admin watches this during tenant creation wizard. Implemented in `src/backend/app/modules/tenants/routes.py` as `GET /platform/provisioning/{job_id}` returning SSE stream. Tests: `tests/unit/test_tenants_routes.py::TestProvisioningSSE` (3 tests: requires_platform_admin, returns_404_for_unknown_job, returns_sse_content_type). All 673 unit tests passing.

---

### API-026: List all tenants ✅ COMPLETED

**Effort**: 4h
**Depends on**: API-001
**Method + Path**: GET /api/v1/platform/tenants
**Auth**: platform_admin
**Description**: Paginated list of all tenants with status, plan, health score, and usage indicators.
**Request**: Query params: `page`, `page_size`, `status`, `plan`, `sort_by` (name, created_at, health_score, plan), `sort_order`
**Response**: `{ "items": [{ "id": "uuid", "name": "string", "plan": "string", "status": "string", "health_score": int|null, "user_count": int, "created_at": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [ ] All tenants returned (platform scope)
- [ ] Filter by status and plan
- [ ] Sort by health_score, plan, created_at, name
- [ ] Health score is null until scoring system is active (Phase B)
      **Notes**: Feeds tenant list view in platform admin console.

---

### API-027: Get tenant detail ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-026
**Method + Path**: GET /api/v1/platform/tenants/{id}
**Auth**: platform_admin
**Description**: Full tenant detail including configuration, quota usage, and contact info.
**Request**: none
**Response**: `{ "id": "uuid", "name": "string", "plan": "string", "status": "string", "admin_email": "string", "llm_profile_id": "uuid", "quotas": {}, "usage": { "tokens_used": int, "storage_used_gb": float, "user_count": int }, "created_at": "ISO-8601", "health_score": int|null }`
**Acceptance criteria**:

- [ ] Returns full tenant metadata
- [ ] Usage data is current (last-updated timestamp included)
- [ ] 404 for non-existent tenant
      **Notes**: Feeds tenant detail page.

---

### API-028: Update tenant status ✅ COMPLETED

**Effort**: 4h
**Depends on**: API-027
**Method + Path**: PATCH /api/v1/platform/tenants/{id}/status
**Auth**: platform_admin
**Description**: Suspend or reactivate a tenant. Suspension blocks all user auth; preserves all data. Grace period: 30 days before scheduled deletion.
**Request**: `{ "status": "active|suspended|scheduled_deletion", "reason": "string" }`
**Response**: `{ "id": "uuid", "status": "string", "grace_period_ends_at": "ISO-8601|null" }`
**Acceptance criteria**:

- [ ] Status transitions validated (state machine: Active > Suspended > ScheduledDeletion)
- [ ] Suspension immediately blocks all tenant user logins
- [ ] ScheduledDeletion starts 30-day grace period countdown
- [ ] Reactivation from Suspended restores access immediately
- [ ] All transitions logged in audit log with actor + reason
      **Notes**: Delete background job runs after grace period.

---

### API-029: Get tenant health score ✅ COMPLETED

**Effort**: 6h
**Depends on**: API-027
**Method + Path**: GET /api/v1/platform/tenants/{id}/health
**Auth**: platform_admin
**Description**: Health score breakdown with all 4 component scores and trend data.
**Request**: none
**Response**: `{ "tenant_id": "uuid", "overall_score": int, "components": { "usage_trend": { "score": int, "weight": 0.30, "details": {} }, "feature_breadth": { "score": int, "weight": 0.20, "details": {} }, "satisfaction": { "score": int, "weight": 0.35, "details": {} }, "error_rate": { "score": int, "weight": 0.15, "details": {} } }, "at_risk": bool, "trend": [{ "week": "ISO-8601", "score": int }] }`
**Acceptance criteria**:

- [x] Composite score calculated per Plan 05 formula (usage_trend 30%, feature_breadth 20%, satisfaction 35%, error_rate 15%)
- [x] All 4 components returned with individual scores
- [x] At-risk flag set when declining 3+ consecutive weeks or score < 40
- [x] Trend data for last 12 weeks
- [x] Returns null/empty gracefully when insufficient data
      **Notes**: Helper: `get_tenant_health_components_db()`. Tests: TestGetTenantHealthScore in `tests/unit/test_issues_routes.py`. Committed: 7cd0e1d. Health score calculated by nightly batch job; API reads from cache.

---

### API-030: Get tenant quota ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-027
**Method + Path**: GET /api/v1/platform/tenants/{id}/quota
**Auth**: platform_admin
**Description**: Returns current quota limits and usage for a tenant.
**Request**: none
**Response**: `{ "tenant_id": "uuid", "tokens": { "limit": int, "used": int, "period": "monthly" }, "storage_gb": { "limit": float, "used": float }, "users": { "limit": int, "used": int } }`
**Acceptance criteria**:

- [x] Usage data is current
- [x] All quota types returned
      **Notes**: Feeds quota management UI. Implemented in `src/backend/app/modules/tenants/routes.py` as `GET /platform/tenants/{tenant_id}/quota`. Tests: `tests/unit/test_tenants_routes.py::TestGetTenantQuota`. All 673 unit tests passing.

---

### API-031: Update tenant quota ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-030
**Method + Path**: PATCH /api/v1/platform/tenants/{id}/quota
**Auth**: platform_admin
**Description**: Update quota limits for a tenant. Enforced at API level for all subsequent requests.
**Request**: `{ "monthly_token_limit": int|null, "storage_gb": float|null, "users_max": int|null }`
**Response**: `{ "tenant_id": "uuid", "quotas": { ... updated } }`
**Acceptance criteria**:

- [x] Only provided fields updated (partial update)
- [x] New limits enforced immediately
- [x] Audit log entry created
      **Notes**: Plan tier defaults applied at provisioning; this overrides per-tenant. UPSERT to tenant_configs table with quota config_type. Implemented in `src/backend/app/modules/tenants/routes.py`. Tests: `tests/unit/test_tenants_routes.py::TestUpdateTenantQuota` (4 tests: requires_platform_admin, returns_updated, rejects_negative_token_limit, 404_for_unknown_tenant). All 673 unit tests passing.

---

### API-032: Create LLM profile ✅ COMPLETED

**Effort**: 6h
**Depends on**: API-001
**Method + Path**: POST /api/v1/platform/llm-profiles
**Auth**: platform_admin
**Description**: Create a new LLM profile with 6 deployment slot configurations. Status starts as Draft.
**Request**: `{ "name": "string", "description": "string", "slots": { "primary": { "provider": "string", "model": "string" }, "intent": { "provider": "string", "model": "string" }, "embedding": { "provider": "string", "model": "string" }, "extraction": { "provider": "string", "model": "string" }, "triage": { "provider": "string", "model": "string" }, "synthesis": { "provider": "string", "model": "string" } }, "plan_tiers": ["starter", "professional", "enterprise"], "best_practices": "string|null" }`
**Response**: 201: `{ "id": "uuid", "name": "string", "status": "draft", "created_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Profile created with status "draft"
- [ ] All 6 slots validated (provider + model must be valid)
- [ ] Plan tier eligibility stored
- [ ] Model names read from provider catalog, never hardcoded
      **Notes**: See Plan 05 Phase B1. Model slots from `21-llm-model-slot-analysis.md`.

---

### API-033: List LLM profiles ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-032
**Method + Path**: GET /api/v1/platform/llm-profiles
**Auth**: platform_admin
**Description**: List all LLM profiles with status and tenant assignment counts.
**Request**: Query params: `status` (draft, published, deprecated), `plan_tier`
**Response**: `{ "items": [{ "id": "uuid", "name": "string", "status": "string", "tenant_count": int, "plan_tiers": ["string"], "created_at": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [ ] Filter by status and plan tier
- [ ] Tenant count shows how many tenants are using each profile
- [ ] Deprecated profiles still returned (with badge)
      **Notes**: Also called by tenant admin to list available profiles (published only).

---

### API-034: Update LLM profile ✅ COMPLETED

**Effort**: 4h
**Depends on**: API-032
**Method + Path**: PATCH /api/v1/platform/llm-profiles/{id}
**Auth**: platform_admin
**Description**: Update profile configuration or status. Published profiles: slot changes create new version. Status transitions: Draft > Published > Deprecated.
**Request**: `{ "name": "string|null", "description": "string|null", "slots": {}|null, "status": "published|deprecated|null", "best_practices": "string|null" }`
**Response**: `{ "id": "uuid", "status": "string", "version": int, "updated_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Status transitions validated
- [ ] Published profiles cannot revert to draft
- [ ] Deprecated profiles retain existing tenant assignments
- [ ] Slot changes on published profile propagate to tenants within 60 seconds
- [ ] Audit log entry created
      **Notes**: Profile enforcement: tenant's RAG pipeline reads profile config from Redis cache (15-min TTL).

---

### API-035: Delete (deprecate) LLM profile

**Effort**: 2h
**Depends on**: API-034
**Method + Path**: DELETE /api/v1/platform/llm-profiles/{id}
**Auth**: platform_admin
**Description**: Soft-delete: sets status to Deprecated. Cannot be newly selected by tenants but retains existing assignments.
**Request**: none
**Response**: `{ "id": "uuid", "status": "deprecated" }`
**Acceptance criteria**:

- [ ] Status set to "deprecated"
- [ ] Existing tenant assignments preserved
- [ ] Profile no longer appears in tenant profile selector
      **Notes**: Hard delete not supported (data integrity).

---

### API-036: Cross-tenant cost analytics

**Effort**: 8h
**Depends on**: API-001
**Method + Path**: GET /api/v1/platform/analytics/cost
**Auth**: platform_admin
**Description**: Cross-tenant cost analytics with LLM token attribution and gross margin calculation.
**Request**: Query params: `period` (7d, 30d, 90d), `tenant_id` (optional), `group_by` (tenant, model, day)
**Response**: `{ "platform_total": { "llm_cost_usd": float, "infrastructure_cost_usd": float, "revenue_usd": float, "gross_margin_pct": float }, "by_tenant": [{ "tenant_id": "uuid", "name": "string", "plan": "string", "llm_cost_usd": float, "tokens_in": int, "tokens_out": int, "gross_margin_pct": float }], "trend": [] }`
**Acceptance criteria**:

- [ ] LLM cost calculated from tokens x per-model cost constants (from env config)
- [ ] Gross margin: (plan revenue - LLM cost - infrastructure estimate) / plan revenue
- [ ] Period filter works
- [ ] Per-tenant breakdown correct
- [ ] Infrastructure costs labeled as "estimated" with last-updated timestamp
      **Notes**: LLM cost constants from env (not hardcoded). See Plan 05 section 4.4.

---

### API-037: Tenant health scores dashboard

**Effort**: 4h
**Depends on**: API-029
**Method + Path**: GET /api/v1/platform/analytics/health
**Auth**: platform_admin
**Description**: Dashboard overview of all tenant health scores with at-risk detection.
**Request**: Query params: `sort_by` (score, name, trend), `at_risk_only` (bool)
**Response**: `{ "summary": { "active_tenants": int, "at_risk_count": int, "avg_satisfaction": float, "open_p0_p1": int }, "tenants": [{ "id": "uuid", "name": "string", "health_score": int, "at_risk": bool, "trend": "improving|stable|declining", "satisfaction_rate": float }] }`
**Acceptance criteria**:

- [ ] All tenants with scores returned
- [ ] At-risk filter works
- [ ] Summary KPIs correct
- [ ] Trend direction calculated from last 3 weeks
      **Notes**: Feeds platform admin dashboard KPI cards (Plan 05 Phase B2).

---

### API-038: Publish agent template to library

**Effort**: 6h
**Depends on**: API-001
**Method + Path**: POST /api/v1/platform/agent-templates
**Auth**: platform_admin
**Description**: Create a new agent template in the platform library. Includes system prompt, variable definitions, guardrails, and version tracking.
**Request**: `{ "name": "string", "category": "string", "description": "string", "system_prompt": "string", "variables": [{ "name": "string", "type": "string", "description": "string", "required": bool, "example": "string" }], "guardrails": { "blocked_topics": ["string"], "required_elements": ["string"], "confidence_threshold": float, "max_response_length": int }, "plan_tiers": ["string"] }`
**Response**: 201: `{ "id": "uuid", "name": "string", "version": 1, "status": "draft" }`
**Acceptance criteria**:

- [ ] Template created with version 1, status "draft"
- [ ] System prompt stored (platform-controlled)
- [ ] Variable definitions validated (no reserved names)
- [ ] Guardrails configuration stored
- [ ] Plan tier eligibility enforced
      **Notes**: Template system prompt never concatenated with raw user variables (prompt injection prevention, R06).

---

### API-039: List agent templates

**Effort**: 3h
**Depends on**: API-038
**Method + Path**: GET /api/v1/platform/agent-templates
**Auth**: platform_admin | tenant_admin
**Description**: List agent templates. Platform admin sees all statuses; tenant admin sees only published templates matching their plan tier.
**Request**: Query params: `status`, `category`, `plan_tier`, `page`, `page_size`
**Response**: `{ "items": [{ "id": "uuid", "name": "string", "category": "string", "version": int, "status": "string", "tenant_adoption_count": int, "satisfaction_rate": float|null }], "total": int }`
**Acceptance criteria**:

- [ ] Platform admin: all statuses visible
- [ ] Tenant admin: only published templates matching their plan
- [ ] Filter by category and plan tier
- [ ] Adoption count and satisfaction rate included
      **Notes**: Seed templates (tmpl*seed*\*) always visible regardless of plan tier.

---

### API-040: Update/version agent template

**Effort**: 4h
**Depends on**: API-038
**Method + Path**: PATCH /api/v1/platform/agent-templates/{id}
**Auth**: platform_admin
**Description**: Update template. For published templates, changes create a new version. Supports lifecycle transitions: Draft > Published > Deprecated.
**Request**: `{ "system_prompt": "string|null", "variables": []|null, "guardrails": {}|null, "status": "string|null", "changelog": "string|null" }`
**Response**: `{ "id": "uuid", "version": int, "status": "string", "updated_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Published templates: changes increment version
- [ ] Previous versions preserved (immutable system prompt)
- [ ] Changelog required for version bumps
- [ ] Tenant admins notified of new version availability
      **Notes**: Tenant instances continue using their deployed version until admin opts into upgrade.

---

### API-041: List tool catalog

**Effort**: 4h
**Depends on**: API-001
**Method + Path**: GET /api/v1/platform/tool-catalog
**Auth**: platform_admin | tenant_admin
**Description**: List available MCP tools in the platform catalog. Platform admin sees all; tenant admin sees tools available for their plan tier.
**Request**: Query params: `safety_class` (read_only, write, destructive), `status`, `page`, `page_size`
**Response**: `{ "items": [{ "id": "uuid", "name": "string", "provider": "string", "safety_class": "string", "status": "healthy|degraded|unavailable", "health_check_last": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [ ] Platform admin: all tools visible
- [ ] Tenant admin: plan-eligible tools only
- [ ] Health status from Redis cache (5-min ping cycle)
- [ ] Filter by safety classification
      **Notes**: See Plan 05 Phase D1 tool catalog.

---

### API-042: Register new tool

**Effort**: 6h
**Depends on**: API-041
**Method + Path**: POST /api/v1/platform/tool-catalog
**Auth**: platform_admin
**Description**: Register a new MCP tool in the catalog. Runs automated health check on registration. Safety classification is immutable (can only escalate).
**Request**: `{ "name": "string", "provider": "string", "mcp_endpoint": "string", "auth_type": "api_key|oauth2|none", "auth_config": {}, "capabilities": ["string"], "safety_class": "read_only|write|destructive", "plan_tiers": ["string"] }`
**Response**: 201: `{ "id": "uuid", "name": "string", "status": "pending_health_check", "health_check_result": {} }`
**Acceptance criteria**:

- [ ] Automated health check: endpoint reachability, auth handshake, schema validation
- [ ] Safety classification stored (immutable — can only escalate, never downgrade)
- [ ] MCP endpoint must be HTTPS
- [ ] Auth credentials encrypted and stored in vault
- [ ] 5-minute health monitoring starts immediately
      **Notes**: Degraded status after 3 consecutive ping failures; unavailable after 10.

---

## Plan 06 — Tenant Admin

### API-043: Invite user (single) ✅ COMPLETED

**Effort**: 4h
**Depends on**: API-001
**Method + Path**: POST /api/v1/admin/users/invite
**Auth**: tenant_admin
**Description**: Send invite email to a single user with role assignment. Creates pending user record.
**Request**: `{ "email": "string", "name": "string", "role": "string", "kb_access": ["uuid"]|null, "agent_access": ["uuid"]|null }`
**Response**: 201: `{ "id": "uuid", "email": "string", "status": "invited", "invite_expires_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Email format validated
- [ ] Role must be valid tenant role
- [ ] Invite email sent via SendGrid
- [ ] Invite expires in 7 days
- [ ] Duplicate email returns 409 (already invited/active)
- [ ] User count checked against tenant quota
      **Notes**: Invited user activates via link in email.

---

### API-044: Bulk invite users ✅ COMPLETED

**Effort**: 4h
**Depends on**: API-043
**Method + Path**: POST /api/v1/admin/users/bulk-invite
**Auth**: tenant_admin
**Description**: Bulk invite users via CSV upload. Validates all rows before processing.
**Request**: multipart/form-data with CSV file (columns: email, name, role)
**Response**: `{ "total": int, "successful": int, "failed": int, "errors": [{ "row": int, "email": "string", "reason": "string" }] }`
**Acceptance criteria**:

- [ ] CSV parsed and validated (email format, valid roles)
- [ ] All rows validated before any invites sent
- [ ] Duplicate emails reported as errors (not sent)
- [ ] Tenant user quota checked against total
- [ ] Max 500 rows per upload
      **Notes**: Async processing for large batches (>50 users).

---

### API-045: Change user role ✅ COMPLETED

**Effort**: 4h
**Depends on**: API-001
**Method + Path**: PATCH /api/v1/admin/users/{id}/role
**Auth**: tenant_admin
**Description**: Change a user's role. Triggers JWT invalidation so new role takes effect on next request. RBAC enforced at query time via JWT claims.
**Request**: `{ "role": "string" }`
**Response**: `{ "id": "uuid", "role": "string", "role_changed_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Role must be valid tenant role
- [ ] Existing JWT invalidated in Redis (force re-login within 15 minutes)
- [ ] Cannot demote last admin
- [ ] Audit log entry created
      **Notes**: CRITICAL: RBAC enforced at query time via JWT claims, NOT assignment time.

---

### API-046: Update user status ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: PATCH /api/v1/admin/users/{id}/status
**Auth**: tenant_admin
**Description**: Suspend or reactivate a user. Suspension blocks login, preserves data.
**Request**: `{ "status": "active|suspended", "reason": "string|null" }`
**Response**: `{ "id": "uuid", "status": "string" }`
**Acceptance criteria**:

- [ ] Suspended user cannot log in
- [ ] Suspended user's active sessions invalidated
- [ ] Data preserved on suspension
- [ ] Cannot suspend last admin
- [ ] Audit log entry created
      **Notes**: Different from deletion (API-047) which anonymizes.

---

### API-047: Delete user ✅ COMPLETED

**Effort**: 4h
**Depends on**: API-001
**Method + Path**: DELETE /api/v1/admin/users/{id}
**Auth**: tenant_admin
**Description**: Delete user and anonymize their conversations. GDPR compliant. Irreversible.
**Request**: none
**Response**: 204 No Content
**Acceptance criteria**:

- [ ] User record soft-deleted
- [ ] All conversations anonymized (user reference replaced with "deleted_user")
- [ ] Active sessions invalidated
- [ ] Memory notes cleared
- [ ] Profile data cleared
- [ ] Cannot delete last admin
- [ ] Audit log entry created
      **Notes**: GDPR erasure requirement. Working memory (Redis) also cleared.

---

### API-048: Get workspace settings ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/admin/workspace
**Auth**: tenant_admin
**Description**: Returns workspace configuration: name, logo, timezone, locale, auth mode, notification preferences.
**Request**: none
**Response**: `{ "name": "string", "logo_url": "string|null", "timezone": "string", "locale": "string", "auth_mode": "local|sso", "notification_preferences": {} }`
**Acceptance criteria**:

- [ ] Returns all workspace settings for current tenant
- [ ] Logo URL is pre-signed if from object storage
      **Notes**: Feeds workspace settings page.

---

### API-049: Update workspace settings ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-048
**Method + Path**: PATCH /api/v1/admin/workspace
**Auth**: tenant_admin
**Description**: Update workspace settings. Partial update supported.
**Request**: `{ "name": "string|null", "logo_url": "string|null", "timezone": "string|null", "locale": "string|null", "notification_preferences": {}|null }`
**Response**: `{ ...updated workspace settings }`
**Acceptance criteria**:

- [ ] Only provided fields updated
- [ ] Name max 100 chars
- [ ] Timezone validated against IANA timezone database
- [ ] Audit log entry created
      **Notes**: Logo upload handled via separate pre-signed URL.

---

### API-050: Connect SharePoint ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 8h
**Depends on**: API-001
**Method + Path**: POST /api/v1/admin/integrations/sharepoint/connect
**Auth**: tenant_admin
**Description**: Save SharePoint connection credentials (client_id, client_secret, tenant_id). Validates connection before saving. Credentials encrypted and stored in vault.
**Request**: `{ "azure_tenant_id": "string", "client_id": "string", "client_secret": "string", "site_ids": ["string"] }`
**Response**: `{ "status": "connected", "sites": [{ "id": "string", "name": "string", "document_count": int }] }`
**Acceptance criteria**:

- [ ] Connection tested before saving (Microsoft Graph API call)
- [ ] Credentials encrypted with AES-256 using tenant-scoped key
- [ ] Stored in vault (never in application DB)
- [ ] Site list returned on success
- [ ] 400 with diagnostic message on connection failure
- [ ] Credentials never returned in API responses
      **Notes**: See Plan 06 section 4.4 credential flow.

---

### API-051: Test SharePoint connection ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 3h
**Depends on**: API-050
**Method + Path**: POST /api/v1/admin/integrations/sharepoint/test
**Auth**: tenant_admin
**Description**: Tests existing SharePoint connection without saving changes. Validates credentials, permissions, and site accessibility.
**Request**: `{ "azure_tenant_id": "string", "client_id": "string", "client_secret": "string" }`
**Response**: `{ "status": "success|failed", "sites_accessible": int, "permissions": { "files_read": bool, "sites_read": bool }, "error": "string|null" }`
**Acceptance criteria**:

- [ ] Tests credential validity
- [ ] Reports specific permission gaps
- [ ] No credentials stored (test only)
- [ ] Timeout: 15 seconds
      **Notes**: Used by the connection wizard to validate before committing.

---

### API-052: Connect Google Drive

**Effort**: 8h
**Depends on**: API-001
**Method + Path**: POST /api/v1/admin/integrations/googledrive/connect
**Auth**: tenant_admin
**Description**: Connect Google Drive via OAuth2 or Domain-Wide Delegation (DWD). OAuth: initiates OAuth flow. DWD: accepts service account JSON + sync user email.
**Request**: `{ "auth_type": "oauth|dwd", "service_account_json": "string|null", "sync_user_email": "string|null", "folder_ids": ["string"]|null }`
**Response**: For OAuth: `{ "redirect_url": "string" }`. For DWD: `{ "status": "connected", "folders": [{ "id": "string", "name": "string" }] }`
**Acceptance criteria**:

- [ ] OAuth: returns redirect URL for Google consent screen
- [ ] DWD: validates service account JSON, tests impersonation
- [ ] DWD sync user must be a real Workspace user (not SA email)
- [ ] Credentials encrypted and stored in vault
- [ ] 400 with diagnostic message on failure
      **Notes**: DWD deferred to Phase B per Plan 06. OAuth path in Phase A.

---

### API-053: Google Drive OAuth callback

**Effort**: 3h
**Depends on**: API-052
**Method + Path**: GET /api/v1/admin/integrations/googledrive/callback
**Auth**: tenant_admin (via state parameter)
**Description**: OAuth2 callback handler for Google Drive. Exchanges auth code for tokens, stores encrypted.
**Request**: Query params: `code`, `state` (contains tenant context)
**Response**: Redirect to admin settings page with success/error indicator
**Acceptance criteria**:

- [ ] Auth code exchanged for access + refresh tokens
- [ ] Tokens encrypted and stored in vault
- [ ] State parameter validated (CSRF protection)
- [ ] Redirects to admin UI with status
      **Notes**: Separate from connect endpoint because OAuth is a redirect flow.

---

### API-054: Manual sync trigger ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 3h
**Depends on**: API-050, API-052
**Method + Path**: POST /api/v1/admin/sync/trigger
**Auth**: tenant_admin
**Description**: Trigger manual document sync for a specific source. Enqueues sync job.
**Request**: `{ "source_type": "sharepoint|google_drive", "source_id": "string", "full_reindex": bool }`
**Response**: `{ "job_id": "uuid", "status": "queued", "estimated_duration_minutes": int }`
**Acceptance criteria**:

- [ ] Sync job enqueued
- [ ] Full reindex shows estimated embedding cost before proceeding
- [ ] Rate limited: 1 manual sync per source per hour
- [ ] Returns estimated duration
      **Notes**: Full reindex is expensive (embedding API calls). Warn tenant admin.

---

### API-055: Sync status ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 3h
**Depends on**: API-054
**Method + Path**: GET /api/v1/admin/sync/status
**Auth**: tenant_admin
**Description**: Returns sync health per connected document source.
**Request**: none
**Response**: `{ "sources": [{ "source_type": "string", "source_id": "string", "name": "string", "status": "healthy|syncing|error|stale", "documents_indexed": int, "last_sync_at": "ISO-8601", "next_sync_at": "ISO-8601", "failed_count": int, "freshness": "green|yellow|red" }] }`
**Acceptance criteria**:

- [ ] All connected sources returned
- [ ] Freshness indicator based on time since last sync
- [ ] Failed count accurate
- [ ] Credential expiry warning when < 30 days remaining
      **Notes**: Feeds sync health dashboard.

---

### API-056: Sync failures

**Effort**: 4h
**Depends on**: API-055
**Method + Path**: GET /api/v1/admin/sync/failures
**Auth**: tenant_admin
**Description**: Per-file sync errors with system-generated diagnosis and fix suggestion. No raw API errors shown.
**Request**: Query params: `source_id`, `page`, `page_size`
**Response**: `{ "items": [{ "file_name": "string", "file_path": "string", "error_type": "permission_denied|format_unsupported|too_large|api_error", "diagnosis": "string", "fix_suggestion": "string", "first_failed_at": "ISO-8601", "retry_count": int }], "total": int }`
**Acceptance criteria**:

- [ ] Diagnosis is human-readable (not raw API error)
- [ ] Fix suggestion is actionable
- [ ] "Add to exclusion list" action available for permission-denied files
- [ ] Paginated
      **Notes**: > 80% of failures should show actionable fix suggestion (Plan 06 success criteria).

---

### API-057: List glossary terms ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/admin/glossary
**Auth**: tenant_admin
**Description**: Returns all glossary terms for the tenant with search capability.
**Request**: Query params: `search`, `page`, `page_size`, `sort_by` (term, created_at)
**Response**: `{ "items": [{ "id": "uuid", "term": "string", "full_form": "string|null", "definition": "string", "context_tags": ["string"], "scope": "string", "created_at": "ISO-8601", "updated_at": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [ ] Full-text search across term + definition
- [ ] Paginated
- [ ] Tenant-scoped (RLS)
      **Notes**: Canonical spec: max 20 terms injected per query, 200 char/definition, 800-token ceiling.

---

### API-058: Add glossary term ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-057
**Method + Path**: POST /api/v1/admin/glossary
**Auth**: tenant_admin
**Description**: Add a single glossary term. Definition limited to 200 characters. Embedding generated for similarity matching at query time.
**Request**: `{ "term": "string", "full_form": "string|null", "definition": "string (max 200)", "context_tags": ["string"], "scope": "global|agent_specific", "aliases": ["string"]|null }`
**Response**: 201: `{ "id": "uuid", "term": "string", "definition": "string" }`
**Acceptance criteria**:

- [ ] Definition max 200 chars enforced (block, not truncate)
- [ ] Duplicate term within tenant returns 409
- [ ] Embedding generated async for similarity search
- [ ] Redis cache invalidated (60-second TTL)
- [ ] Active in query pipeline within 60 seconds of save
      **Notes**: Prompt injection protection: definition content sanitized before injection into system message.

---

### API-059: Update glossary term ✅ COMPLETED

**Effort**: 2h
**Depends on**: API-058
**Method + Path**: PATCH /api/v1/admin/glossary/{id}
**Auth**: tenant_admin
**Description**: Update an existing glossary term. Version history tracked.
**Request**: `{ "definition": "string|null", "full_form": "string|null", "context_tags": []|null, "aliases": []|null }`
**Response**: `{ "id": "uuid", ...updated fields }`
**Acceptance criteria**:

- [ ] Definition max 200 chars enforced
- [ ] Version history entry created
- [ ] Embedding regenerated if definition changed
- [ ] Redis cache invalidated
      **Notes**: Version history enables rollback.

---

### API-060: Delete glossary term ✅ COMPLETED

**Effort**: 2h
**Depends on**: API-058
**Method + Path**: DELETE /api/v1/admin/glossary/{id}
**Auth**: tenant_admin
**Description**: Delete a glossary term. Removes from active set.
**Request**: none
**Response**: 204 No Content
**Acceptance criteria**:

- [ ] Term removed from PostgreSQL
- [ ] Redis cache invalidated
- [ ] Embedding removed
- [ ] Audit log entry created
      **Notes**: Soft delete with version history preserved for audit.

---

### API-061: Bulk import glossary ✅ COMPLETED

**Effort**: 4h
**Depends on**: API-058
**Method + Path**: POST /api/v1/admin/glossary/bulk-import
**Auth**: tenant_admin
**Description**: CSV import of glossary terms with validation, preview, and conflict resolution.
**Request**: multipart/form-data with CSV file (columns: term, full_form, definition, context_tags)
**Response**: `{ "preview": [{ "term": "string", "action": "create|update|skip", "conflict": "string|null" }], "total": int, "creates": int, "updates": int, "skips": int }`
**Acceptance criteria**:

- [ ] CSV parsed and validated (200 char definition limit)
- [ ] Preview returned first (no immediate import)
- [ ] Conflicts detected (existing terms)
- [ ] Confirm endpoint to execute import after preview
- [ ] Max 1000 terms per import
      **Notes**: Two-step: preview then confirm. Prevents accidental overwrites.

---

### API-062: Export glossary

**Effort**: 2h
**Depends on**: API-057
**Method + Path**: GET /api/v1/admin/glossary/export
**Auth**: tenant_admin
**Description**: Export all glossary terms as CSV download.
**Request**: none
**Response**: CSV file download (Content-Type: text/csv)
**Acceptance criteria**:

- [ ] All terms exported including full_form, definition, context_tags
- [ ] UTF-8 BOM for Excel compatibility
- [ ] Tenant-scoped export only
      **Notes**: Matches import format for round-tripping.

---

### API-063: Glossary miss analytics

**Effort**: 4h
**Depends on**: API-057
**Method + Path**: GET /api/v1/admin/glossary/analytics/misses
**Auth**: tenant_admin
**Description**: Surface top unmatched query terms that appear frequently but have no glossary coverage.
**Request**: Query params: `period` (7d, 30d), `limit` (default 20)
**Response**: `{ "terms": [{ "term": "string", "frequency": int, "example_queries": ["string"], "suggested_definition": "string|null" }] }`
**Acceptance criteria**:

- [ ] Terms ranked by frequency
- [ ] Example queries anonymized (no user attribution)
- [ ] Period filter works
- [ ] AI-suggested definition included where possible
      **Notes**: Feeds glossary enrichment workflow.

---

### API-064: Configure SAML SSO

**Effort**: 6h
**Depends on**: API-001
**Method + Path**: POST /api/v1/admin/sso/saml
**Auth**: tenant_admin
**Description**: Configure SAML 2.0 SSO. Accepts IdP metadata XML, returns SP metadata for IdP configuration.
**Request**: `{ "idp_metadata_xml": "string", "attribute_mapping": { "email": "string", "name": "string", "groups": "string" }, "jit_provisioning": bool, "default_role": "string" }`
**Response**: `{ "sp_metadata_url": "string", "sp_entity_id": "string", "sp_acs_url": "string", "status": "configured" }`
**Acceptance criteria**:

- [ ] IdP metadata parsed and validated
- [ ] SP metadata generated and downloadable
- [ ] Attribute mapping stored
- [ ] JIT provisioning setting stored
- [ ] SSO NOT enabled until test login succeeds (API-066)
      **Notes**: Use `python3-saml` or `python-social-auth`. See Plan 06 section 4.1.

---

### API-065: Configure OIDC SSO

**Effort**: 5h
**Depends on**: API-001
**Method + Path**: POST /api/v1/admin/sso/oidc
**Auth**: tenant_admin
**Description**: Configure OIDC SSO. Supports auto-discovery via `.well-known/openid-configuration`.
**Request**: `{ "issuer_url": "string", "client_id": "string", "client_secret": "string", "scopes": ["string"], "auto_discover": bool, "jit_provisioning": bool, "default_role": "string" }`
**Response**: `{ "status": "configured", "discovered_endpoints": { "authorization": "string", "token": "string", "userinfo": "string" } }`
**Acceptance criteria**:

- [ ] Auto-discovery fetches and validates OIDC configuration
- [ ] Client credentials encrypted and stored in vault
- [ ] SSO NOT enabled until test login succeeds (API-066)
      **Notes**: Use `authlib` with auto-discovery.

---

### API-066: Test SSO login flow

**Effort**: 4h
**Depends on**: API-064, API-065
**Method + Path**: POST /api/v1/admin/sso/test
**Auth**: tenant_admin
**Description**: Initiates a test SSO login. Admin completes login in browser; result reported back. SSO must pass test before being enabled for all users.
**Request**: `{ "provider": "saml|oidc" }`
**Response**: `{ "test_url": "string", "test_id": "uuid" }` (admin navigates to test_url, then GET /api/v1/admin/sso/test/{test_id}/result for outcome)
**Acceptance criteria**:

- [ ] Test login flow isolated (does not affect production auth)
- [ ] Success/failure result includes diagnostic details
- [ ] Must pass before SSO can be enabled for tenant
- [ ] Rollback instructions provided on failure
      **Notes**: Keep email/password as override. Platform admin emergency access always available.

---

### API-067: KB access control settings

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/admin/kb/{id}/access
**Auth**: tenant_admin
**Description**: Get access control settings for a knowledge base.
**Request**: none
**Response**: `{ "kb_id": "uuid", "access_mode": "workspace_wide|role_restricted|user_specific|agent_only", "allowed_roles": ["string"]|null, "allowed_users": ["uuid"]|null, "allowed_agents": ["uuid"]|null }`
**Acceptance criteria**:

- [ ] Returns current access configuration
- [ ] 404 for KB not in tenant
      **Notes**: See Plan 06 section 4.3 RBAC enforcement.

---

### API-068: Update KB access control

**Effort**: 4h
**Depends on**: API-067
**Method + Path**: PATCH /api/v1/admin/kb/{id}/access
**Auth**: tenant_admin
**Description**: Update KB access mode and permissions. Changes reflected in user permissions within 60 seconds.
**Request**: `{ "access_mode": "workspace_wide|role_restricted|user_specific|agent_only", "allowed_roles": ["string"]|null, "allowed_users": ["uuid"]|null, "allowed_agents": ["uuid"]|null }`
**Response**: `{ "kb_id": "uuid", "access_mode": "string", "updated_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Access mode change propagated within 60 seconds (Redis cache invalidation)
- [ ] JWT claims updated on next token refresh
- [ ] Validation: agent_only mode requires at least 1 agent assigned
- [ ] Audit log entry created
      **Notes**: CRITICAL: enforcement at query time via JWT claims, not just UI visibility.

---

### API-069: List workspace agents

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/admin/agents
**Auth**: tenant_admin
**Description**: List all agents in the workspace with status, version, satisfaction, and source (library/custom).
**Request**: Query params: `status` (draft, published, unpublished), `page`, `page_size`
**Response**: `{ "items": [{ "id": "uuid", "name": "string", "source": "library|custom|seed", "status": "string", "version": int, "satisfaction_rate": float|null, "user_count": int }], "total": int }`
**Acceptance criteria**:

- [ ] All agents for tenant returned
- [ ] Source indicates library adoption vs custom creation vs seed template
- [ ] Satisfaction data included when available
      **Notes**: Feeds agent management page in tenant admin.

---

### API-070: Create agent (Agent Studio)

**Effort**: 8h
**Depends on**: API-001
**Method + Path**: POST /api/v1/admin/agents
**Auth**: tenant_admin
**Description**: Create a custom agent via Agent Studio. System prompt is tenant-controlled. Minimum guardrail requirements enforced at publish.
**Request**: `{ "name": "string", "description": "string", "category": "string", "avatar": "string|null", "system_prompt": "string", "example_conversations": [{ "user": "string", "assistant": "string" }], "kb_ids": ["uuid"], "kb_mode": "grounded|extended", "tool_ids": ["uuid"]|null, "guardrails": { "blocked_topics": ["string"], "required_elements": ["string"], "confidence_threshold": float, "max_response_length": int }, "access_mode": "workspace_wide|role_restricted|user_specific", "status": "draft" }`
**Response**: 201: `{ "id": "uuid", "name": "string", "status": "draft" }`
**Acceptance criteria**:

- [ ] Agent created with status "draft"
- [ ] KB IDs validated (must belong to tenant and admin has access)
- [ ] Tool IDs validated (must be in tenant's plan catalog)
- [ ] Guardrail defaults applied if not specified
- [ ] System prompt stored (tenant-controlled, scoped to tenant only)
      **Notes**: Agent Studio agents scoped to tenant only. Platform reviews flagged agents (R05).

---

### API-071: Update agent

**Effort**: 4h
**Depends on**: API-070
**Method + Path**: PUT /api/v1/admin/agents/{id}
**Auth**: tenant_admin
**Description**: Full update of an agent configuration. Creates new version for published agents.
**Request**: Same schema as POST (API-070)
**Response**: `{ "id": "uuid", "version": int, "status": "string", "updated_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Published agents: update creates new version
- [ ] All validations from creation apply
- [ ] KB and tool access re-validated
- [ ] Audit log entry created
      **Notes**: PUT for full replacement (not PATCH).

---

### API-072: Update agent status

**Effort**: 3h
**Depends on**: API-070
**Method + Path**: PATCH /api/v1/admin/agents/{id}/status
**Auth**: tenant_admin
**Description**: Publish, unpublish, or revert agent to draft. Publish requires minimum guardrails (confidence threshold must be set).
**Request**: `{ "status": "draft|published|unpublished" }`
**Response**: `{ "id": "uuid", "status": "string" }`
**Acceptance criteria**:

- [ ] Publish validates minimum guardrail requirements
- [ ] Published agent visible to eligible users immediately
- [ ] Unpublished agent hidden from users but preserved
- [ ] Draft revert allowed for unpublished agents
      **Notes**: Minimum guardrail: confidence_threshold must be set (R10).

---

### API-073: Deploy agent from template library

**Effort**: 4h
**Depends on**: API-039, API-070
**Method + Path**: POST /api/v1/admin/agents/deploy
**Auth**: tenant_admin
**Description**: Deploy an agent from the platform template library. Fills template variables with tenant-specific values. System prompt is platform-controlled (tenant cannot modify).
**Request**: `{ "template_id": "uuid", "name": "string", "variables": { "key": "value" }, "kb_ids": ["uuid"], "access_mode": "string" }`
**Response**: 201: `{ "id": "uuid", "name": "string", "template_id": "uuid", "template_version": int, "status": "published" }`
**Acceptance criteria**:

- [ ] Template validated for tenant's plan tier
- [ ] Required variables all provided
- [ ] System prompt from template (not editable by tenant)
- [ ] Platform guardrails enforced (tenant can add, not remove)
- [ ] KB IDs validated
      **Notes**: See Plan 06 section 4.5. Template vs Studio comparison.

---

### API-074: Satisfaction dashboard data

**Effort**: 6h
**Depends on**: API-007
**Method + Path**: GET /api/v1/admin/analytics/satisfaction
**Auth**: tenant_admin
**Description**: Satisfaction analytics: 7-day rolling rate, per-agent breakdown, trend chart, low-confidence responses.
**Request**: Query params: `period` (7d, 30d, 90d), `agent_id` (optional)
**Response**: `{ "overall_rate": float, "total_ratings": int, "per_agent": [{ "agent_id": "uuid", "name": "string", "satisfaction_rate": float, "ratings_count": int }], "trend": [{ "date": "ISO-8601", "rate": float }], "low_confidence_responses": [{ "message_id": "uuid", "query": "string", "confidence": float, "rating": int }] }`
**Acceptance criteria**:

- [ ] Rolling rate calculated correctly
- [ ] Per-agent breakdown accurate
- [ ] Low-confidence responses listed (configurable threshold)
- [ ] Period filter works
- [ ] "Not enough data" state for < 50 ratings
      **Notes**: See Plan 06 Phase C3. Cold start: show explicit "not enough data" state.

---

### API-075: Engagement analytics

**Effort**: 4h
**Depends on**: API-001
**Method + Path**: GET /api/v1/admin/analytics/engagement
**Auth**: tenant_admin
**Description**: User engagement metrics: DAU/WAU/MAU per agent, inactive users, feature adoption.
**Request**: Query params: `period` (7d, 30d, 90d), `agent_id` (optional)
**Response**: `{ "dau": int, "wau": int, "mau": int, "per_agent": [{ "agent_id": "uuid", "name": "string", "dau": int, "wau": int, "sessions_per_week": float }], "inactive_users": { "count": int, "pct": float }, "feature_adoption": { "memory_notes": float, "glossary_queries": float, "feedback": float } }`
**Acceptance criteria**:

- [ ] DAU/WAU/MAU calculated correctly
- [ ] Per-agent breakdown works
- [ ] Inactive users identified (no activity in 30 days)
- [ ] Feature adoption rates accurate
      **Notes**: Feeds tenant admin engagement dashboard.

---

### API-076: Get tenant memory policy

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/admin/memory-policy
**Auth**: tenant_admin
**Description**: Returns tenant-level memory policy settings controlling profile learning, working memory, memory notes, and org context behavior.
**Request**: none
**Response**: `{ "profile_learning_enabled": bool, "profile_learning_trigger_interval": int, "working_memory_enabled": bool, "working_memory_ttl_days": int, "memory_notes_enabled": bool, "memory_notes_max_per_user": int, "org_context_enabled": bool, "org_context_source": "azure_ad|okta|saml|none" }`
**Acceptance criteria**:

- [ ] All policy settings returned with current values
- [ ] Defaults applied for unset values
      **Notes**: See Plan 08 Sprint 8.

---

### API-077: Update tenant memory policy

**Effort**: 3h
**Depends on**: API-076
**Method + Path**: PATCH /api/v1/admin/memory-policy
**Auth**: tenant_admin
**Description**: Update tenant-level memory policy. Changes enforced at service instantiation.
**Request**: `{ ...any subset of memory policy fields }`
**Response**: `{ ...updated policy }`
**Acceptance criteria**:

- [ ] Partial update supported
- [ ] Changes enforced within 60 seconds (service checks policy on each invocation)
- [ ] Validation: TTL range 1-30 days, trigger interval 5-25
- [ ] Audit log entry created
      **Notes**: Phase 2 adds configurable TTL per-agent.

---

### API-078: List teams ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/admin/teams
**Auth**: tenant_admin
**Description**: List all teams in the workspace with source badge (manual/auth0_sync).
**Request**: Query params: `page`, `page_size`
**Response**: `{ "items": [{ "id": "uuid", "name": "string", "source": "manual|auth0_sync", "member_count": int, "auth0_group_name": "string|null", "created_at": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [ ] All teams for tenant returned
- [ ] Source badge correct (manual vs synced)
- [ ] Member count accurate
      **Notes**: See Plan 10.

---

### API-079: Create team ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-078
**Method + Path**: POST /api/v1/admin/teams
**Auth**: tenant_admin
**Description**: Create a manually-managed team.
**Request**: `{ "name": "string", "description": "string|null" }`
**Response**: 201: `{ "id": "uuid", "name": "string", "source": "manual" }`
**Acceptance criteria**:

- [ ] Team created with source "manual"
- [ ] Duplicate name within tenant returns 409
- [ ] Audit log entry created
      **Notes**: Auth0-synced teams created automatically on login.

---

### API-080: Update team ✅ COMPLETED

**Effort**: 2h
**Depends on**: API-079
**Method + Path**: PUT /api/v1/admin/teams/{id}
**Auth**: tenant_admin
**Description**: Update team name and description.
**Request**: `{ "name": "string", "description": "string|null" }`
**Response**: `{ "id": "uuid", "name": "string", "updated_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Name uniqueness validated
- [ ] Auth0-synced teams: name update preserved (overrides next sync name)
      **Notes**: PUT for full replacement.

---

### API-081: Delete team ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-079
**Method + Path**: DELETE /api/v1/admin/teams/{id}
**Auth**: tenant_admin
**Description**: Delete a team and its working memory. Members retain their individual data.
**Request**: none
**Response**: 204 No Content
**Acceptance criteria**:

- [ ] Team record deleted
- [ ] Team working memory bucket cleared from Redis
- [ ] Memberships removed
- [ ] Auth0-synced teams: team recreation prevented until next sync cycle
- [ ] Audit log entry created
      **Notes**: Members are not deleted, only disassociated.

---

### API-082: List team members ✅ COMPLETED

**Effort**: 2h
**Depends on**: API-078
**Method + Path**: GET /api/v1/admin/teams/{id}/members
**Auth**: tenant_admin
**Description**: List all members of a specific team.
**Request**: Query params: `page`, `page_size`
**Response**: `{ "items": [{ "user_id": "uuid", "name": "string", "email": "string", "role": "string", "source": "manual|auth0_sync", "joined_at": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [ ] All members returned with source indicator
- [ ] Paginated
      **Notes**: Source indicates how member was added.

---

### API-083: Add team member ✅ COMPLETED

**Effort**: 2h
**Depends on**: API-082
**Method + Path**: POST /api/v1/admin/teams/{id}/members
**Auth**: tenant_admin
**Description**: Add a user to a team.
**Request**: `{ "user_id": "uuid" }`
**Response**: 201: `{ "user_id": "uuid", "team_id": "uuid", "source": "manual" }`
**Acceptance criteria**:

- [ ] User must belong to same tenant
- [ ] Duplicate membership returns 409
- [ ] Audit log entry created with actor
      **Notes**: Manual additions always have source "manual".

---

### API-084: Remove team member ✅ COMPLETED

**Effort**: 2h
**Depends on**: API-083
**Method + Path**: DELETE /api/v1/admin/teams/{id}/members/{user_id}
**Auth**: tenant_admin
**Description**: Remove a user from a team.
**Request**: none
**Response**: 204 No Content
**Acceptance criteria**:

- [ ] Membership removed
- [ ] Auth0-synced members: removal is temporary (re-added on next login if still in group)
- [ ] Audit log entry created
      **Notes**: Admin should be warned about auth0_sync members being re-added.

---

### API-085: Team membership audit log ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-078
**Method + Path**: GET /api/v1/admin/teams/{id}/audit-log
**Auth**: tenant_admin
**Description**: Audit log of all membership changes for a specific team.
**Request**: Query params: `page`, `page_size`
**Response**: `{ "items": [{ "event": "member_added|member_removed|team_created|team_updated", "actor": "string", "target_user": "string|null", "source": "manual|auth0_sync", "timestamp": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [ ] All membership events logged
- [ ] Actor tracked (admin name or "auth0_sync_system")
- [ ] Paginated, sorted newest first
      **Notes**: See Plan 10 membership audit log requirement.

---

### API-086: Configure Auth0 group sync allowlist

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: PATCH /api/v1/admin/settings/auth0-sync
**Auth**: tenant_admin
**Description**: Configure which Auth0 group names to auto-sync as teams. Default: empty (no sync until configured). Supports group name strings and simple wildcards.
**Request**: `{ "enabled": bool, "allowed_groups": ["string"], "wildcard_patterns": ["string"]|null }`
**Response**: `{ "enabled": bool, "allowed_groups": ["string"], "wildcard_patterns": ["string"] }`
**Acceptance criteria**:

- [ ] Empty allowlist means no groups synced
- [ ] Wildcard patterns validated (simple glob, not regex)
- [ ] Changes take effect on next user login
- [ ] Audit log entry created
      **Notes**: Prevents noise teams like vpn-users, all-company from auto-creating.

---

### API-087: Workspace audit log

**Effort**: 4h
**Depends on**: API-001
**Method + Path**: GET /api/v1/admin/audit-log
**Auth**: tenant_admin
**Description**: Searchable event history for all admin actions in the workspace.
**Request**: Query params: `actor`, `action`, `resource_type`, `start_date`, `end_date`, `page`, `page_size`
**Response**: `{ "items": [{ "id": "uuid", "actor": "string", "action": "string", "resource_type": "string", "resource_id": "string", "details": {}, "timestamp": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [ ] All admin actions logged (user changes, settings, agent deployments, glossary, sync)
- [ ] Filterable by actor, action type, resource type, date range
- [ ] Paginated
- [ ] Tenant-scoped (RLS)
      **Notes**: Feeds audit log UI in tenant admin console.

---

### API-088: User directory list

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/users
**Auth**: tenant_admin
**Description**: List all users in the tenant with role, status, and last login.
**Request**: Query params: `role`, `status`, `search` (name/email), `page`, `page_size`
**Response**: `{ "items": [{ "id": "uuid", "email": "string", "name": "string", "role": "string", "status": "active|invited|suspended", "last_login_at": "ISO-8601|null" }], "total": int }`
**Acceptance criteria**:

- [ ] Tenant-scoped (RLS)
- [ ] Search works on name and email
- [ ] Filter by role and status
- [ ] Paginated
      **Notes**: Per integration guide.

---

## Plan 07 — Hosted Agent Registry (HAR)

### API-089: Register agent card

**Effort**: 6h
**Depends on**: API-001
**Method + Path**: POST /api/v1/registry/agents
**Auth**: tenant_admin
**Description**: Publish an agent card to the global registry. Agent must exist in tenant's workspace. Generates Ed25519 keypair (Phase 1: HAR-managed).
**Request**: `{ "workspace_agent_id": "uuid", "name": "string", "description": "string", "transaction_types": ["string"], "industries": ["string"], "languages": ["string"], "a2a_endpoint": "string (HTTPS only)", "health_check_url": "string" }`
**Response**: 201: `{ "agent_id": "uuid", "status": "active", "trust_score": 20, "public_key": "string" }`
**Acceptance criteria**:

- [ ] Agent card stored in `agent_cards` table with tenant_id FK
- [ ] Ed25519 keypair generated; private key in vault, public key in card
- [ ] A2A endpoint must be HTTPS
- [ ] Health check URL validated (must respond 200)
- [ ] Agent indexed in search for discovery
- [ ] Initial trust score: 20 (minimum)
      **Notes**: Phase 1: HAR signs on agent's behalf. BYOK in Phase 2. See Plan 07 Sprint 0-A.

---

### API-090: List/search registry agents

**Effort**: 4h
**Depends on**: API-089
**Method + Path**: GET /api/v1/registry/agents
**Auth**: public (browsing), end_user (for transaction initiation)
**Description**: Search the global agent registry. No auth required for browsing. Filters by industry, transaction type, language.
**Request**: Query params: `query` (text search), `industry`, `transaction_type`, `language`, `min_trust_score`, `page`, `page_size`
**Response**: `{ "items": [{ "agent_id": "uuid", "name": "string", "description": "string", "tenant_name": "string", "transaction_types": ["string"], "industries": ["string"], "trust_score": int, "status": "active|suspended|unavailable", "health_status": "healthy|degraded|unavailable" }], "total": int }`
**Acceptance criteria**:

- [ ] Text search on name + description
- [ ] Filter by industry, transaction type, language, trust score
- [ ] Health status from Redis (5-min ping)
- [ ] No auth required to browse
- [ ] Results sorted by relevance then trust score
      **Notes**: Public discovery is a key feature. See Plan 07 Sprint 0-B.

---

### API-091: Get agent card detail

**Effort**: 2h
**Depends on**: API-089
**Method + Path**: GET /api/v1/registry/agents/{id}
**Auth**: public
**Description**: Full agent card detail including trust score, transaction count, attestations.
**Request**: none
**Response**: `{ "agent_id": "uuid", "name": "string", "description": "string", "tenant": { "id": "uuid", "name": "string" }, "transaction_types": ["string"], "industries": ["string"], "languages": ["string"], "a2a_endpoint": "string", "trust_score": int, "transaction_count": int, "public_key": "string", "created_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Full card returned
- [ ] Transaction count accurate
- [ ] Public key visible for verification
      **Notes**: Public endpoint.

---

### API-092: Update agent card

**Effort**: 3h
**Depends on**: API-089
**Method + Path**: PUT /api/v1/registry/agents/{id}
**Auth**: tenant_admin
**Description**: Update agent card details. Only the owning tenant admin can update.
**Request**: `{ "description": "string|null", "transaction_types": ["string"]|null, "industries": ["string"]|null, "languages": ["string"]|null, "a2a_endpoint": "string|null", "health_check_url": "string|null" }`
**Response**: `{ "agent_id": "uuid", "updated_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Only owning tenant can update
- [ ] A2A endpoint change re-validates HTTPS
- [ ] Search index updated
- [ ] Audit log entry created
      **Notes**: Name changes require deregistration and re-registration.

---

### API-093: Deregister agent

**Effort**: 3h
**Depends on**: API-089
**Method + Path**: DELETE /api/v1/registry/agents/{id}
**Auth**: tenant_admin
**Description**: Remove agent from global registry. Deactivates A2A endpoint. Preserves transaction history.
**Request**: none
**Response**: 204 No Content
**Acceptance criteria**:

- [ ] Agent card removed from active registry
- [ ] Search index updated
- [ ] Transaction history preserved (for audit)
- [ ] Active transactions with this agent marked as agent_deregistered
- [ ] Only owning tenant can deregister
      **Notes**: Soft delete for audit trail preservation.

---

### API-094: Initiate A2A transaction

**Effort**: 8h
**Depends on**: API-089
**Method + Path**: POST /api/v1/registry/transactions
**Auth**: end_user (authenticated, agent must belong to user's tenant)
**Description**: Initiate an A2A transaction between two registered agents. HAR acts as signing proxy in Phase 1. Creates tamper-evident audit log entry.
**Request**: `{ "from_agent_id": "uuid", "to_agent_id": "uuid", "message_type": "RFQ|CAPABILITY_QUERY", "payload": {} }`
**Response**: 201: `{ "txn_id": "string (HAR-YYYYMMDD-NNNNNN)", "status": "OPEN", "message_id": "uuid" }`
**Acceptance criteria**:

- [ ] Transaction ID generated in HAR format
- [ ] Ed25519 signature over SHA-256(header||payload)
- [ ] Audit log entry with signature chain (current event signs over previous hash)
- [ ] Message routed to target agent's A2A endpoint
- [ ] Status set to OPEN
- [ ] From agent must belong to user's tenant
      **Notes**: See Plan 07 Sprint 1-A. Signature chaining creates tamper-evident log.

---

### API-095: Get transaction status + audit trail

**Effort**: 4h
**Depends on**: API-094
**Method + Path**: GET /api/v1/registry/transactions/{txn_id}
**Auth**: end_user (must be participant)
**Description**: Get transaction status and full audit trail with signature verification.
**Request**: none
**Response**: `{ "txn_id": "string", "status": "string", "from_agent": {}, "to_agent": {}, "events": [{ "event_type": "string", "timestamp": "ISO-8601", "payload_hash": "string", "platform_signature": "string", "verified": bool }], "approval_required": bool, "approval_deadline": "ISO-8601|null" }`
**Acceptance criteria**:

- [ ] Full event chain returned
- [ ] Each event's signature verified (verified: true/false)
- [ ] Only transaction participants can view
- [ ] Approval status shown if human approval pending
      **Notes**: Signature verification confirms tamper-evident chain integrity.

---

### API-096: Approve transaction (human approval gate)

**Effort**: 4h
**Depends on**: API-094
**Method + Path**: POST /api/v1/registry/transactions/{txn_id}/approve
**Auth**: tenant_admin
**Description**: Human approval for transactions above configured threshold. Default: $5,000 for PO, always for financial. Timeout: 48 hours (configurable).
**Request**: `{ "approved_by": "uuid", "note": "string|null" }`
**Response**: `{ "txn_id": "string", "status": "COMMITTED", "approved_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Only callable when approval is pending
- [ ] Approver must be admin of the initiating tenant
- [ ] Approval logged in audit trail with signature
- [ ] Transaction state advances to COMMITTED
- [ ] Counterparty notified
      **Notes**: See Plan 07 Sprint 1-C. Human approval is the legally binding act.

---

### API-097: Reject transaction

**Effort**: 2h
**Depends on**: API-096
**Method + Path**: POST /api/v1/registry/transactions/{txn_id}/reject
**Auth**: tenant_admin
**Description**: Reject a pending transaction.
**Request**: `{ "rejected_by": "uuid", "reason": "string" }`
**Response**: `{ "txn_id": "string", "status": "ABANDONED" }`
**Acceptance criteria**:

- [ ] Only callable when approval is pending
- [ ] Rejection logged in audit trail
- [ ] Counterparty notified
- [ ] Transaction state set to ABANDONED
      **Notes**: Expired approvals (48h timeout) auto-reject.

---

### API-098: Registry discovery analytics

**Effort**: 4h
**Depends on**: API-089
**Method + Path**: GET /api/v1/registry/analytics
**Auth**: tenant_admin
**Description**: Discovery analytics for agents published by this tenant. Shows how often their agents were found in searches and transaction volume.
**Request**: Query params: `period` (7d, 30d, 90d), `agent_id` (optional)
**Response**: `{ "agents": [{ "agent_id": "uuid", "name": "string", "discovery_count": int, "transaction_count": int, "trust_score": int, "trust_score_trend": "up|stable|down" }] }`
**Acceptance criteria**:

- [ ] Per-agent discovery and transaction counts
- [ ] Period filter works
- [ ] Only shows agents owned by current tenant
      **Notes**: Feeds "Your agent was discovered X times this week" widget.

---

## Plan 08 — Profile & Memory

### API-099: Get user profile ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/me/profile
**Auth**: end_user
**Description**: Returns current user's profile data including learned attributes, privacy settings, and org context.
**Request**: none
**Response**: `{ "user_id": "uuid", "technical_level": "string|null", "communication_style": "string|null", "interests": ["string"], "expertise_areas": ["string"], "common_tasks": ["string"], "privacy": { "org_context_enabled": bool, "share_manager_info": bool, "profile_learning_enabled": bool }, "org_context": { "department": "string|null", "role": "string|null", "manager": "string|null", "location": "string|null" } }`
**Acceptance criteria**:

- [ ] Returns profile for current user only
- [ ] Org context included based on privacy settings
- [ ] Returns empty/default for new users with no profile
- [ ] Tenant-scoped
      **Notes**: See Plan 08 Sprint 7.

---

### API-100: Update privacy preferences ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 3h
**Depends on**: API-099
**Method + Path**: PATCH /api/v1/me/preferences
**Auth**: end_user
**Description**: Update user's privacy preferences for org context and profile learning.
**Request**: `{ "org_context_enabled": bool|null, "share_manager_info": bool|null, "profile_learning_enabled": bool|null }`
**Response**: `{ ...updated preferences }`
**Acceptance criteria**:

- [ ] Partial update supported
- [ ] Disabling org_context immediately stops injection in next query
- [ ] Disabling profile_learning stops extraction (existing profile preserved)
- [ ] Changes logged (privacy-related audit)
      **Notes**: EU tenants: opt-in default for GDPR. Non-EU: opt-out default.

---

### API-101: List memory notes ✅ COMPLETED

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/me/memory
**Auth**: end_user
**Description**: Returns user's memory notes sorted newest first. Shows source badge (user_directed, auto_extracted).
**Request**: Query params: `agent_id` (optional filter), `page`, `page_size`
**Response**: `{ "items": [{ "id": "uuid", "content": "string", "source": "user_directed|auto_extracted", "agent_id": "uuid|null", "created_at": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [ ] Newest first ordering
- [ ] Source badge correct
- [ ] Agent_id filter works (null = global, specific = agent-scoped)
- [ ] Max 15 notes per user enforced
- [ ] Tenant-scoped
      **Notes**: See Plan 08 Sprint 5. Content max 200 chars.

---

### API-102: Delete single memory note ✅ COMPLETED

**Effort**: 2h
**Depends on**: API-101
**Method + Path**: DELETE /api/v1/me/memory/{note_id}
**Auth**: end_user
**Description**: Delete a specific memory note.
**Request**: none
**Response**: 204 No Content
**Acceptance criteria**:

- [ ] Only own notes can be deleted
- [ ] Note removed from PostgreSQL
- [ ] Prompt builder no longer includes this note
      **Notes**: Immediate effect on next query.

---

### API-103: Clear all memory notes (GDPR) ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 2h
**Depends on**: API-101
**Method + Path**: DELETE /api/v1/me/memory
**Auth**: end_user
**Description**: Clear all memory notes for current user. GDPR erasure support.
**Request**: none
**Response**: 204 No Content
**Acceptance criteria**:

- [ ] All notes for user deleted from PostgreSQL
- [ ] Confirmation required (header: X-Confirm-Delete: true)
- [ ] Audit log entry created
      **Notes**: Part of GDPR Article 17 compliance.

---

### API-104: Export profile data (GDPR) ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 4h
**Depends on**: API-099, API-101
**Method + Path**: GET /api/v1/me/data-export
**Auth**: end_user
**Description**: Export all profile data for the current user: profile attributes, memory notes, working memory snapshot, org context. GDPR Article 17 data portability.
**Request**: none
**Response**: `{ "profile": {}, "memory_notes": [], "working_memory": {}, "org_context": {}, "exported_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] All three data types included (profile, notes, working memory)
- [ ] Org context included
- [ ] Tenant-scoped data only
- [ ] Export does not include other users' data
      **Notes**: JSON format for portability. PDF option in future.

---

### API-105: Clear all profile data (GDPR erasure) ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 4h
**Depends on**: API-099, API-101
**Method + Path**: DELETE /api/v1/me/data
**Auth**: end_user
**Description**: Full GDPR erasure. Clears ALL profile data: profile attributes, memory notes, working memory (Redis), profile learning events. CRITICAL: must clear all three stores (PostgreSQL + Redis L2 + L1).
**Request**: none (header: X-Confirm-Delete: true)
**Response**: 204 No Content
**Acceptance criteria**:

- [ ] Profile attributes cleared from PostgreSQL
- [ ] Memory notes cleared from PostgreSQL
- [ ] Working memory cleared from Redis (including team memory buckets)
- [ ] Profile learning events cleared from PostgreSQL
- [ ] Profile cache (L1 in-process, L2 Redis) invalidated
- [ ] Confirmation header required
- [ ] Audit log entry created
      **Notes**: CRITICAL FIX from aihub2: `clear_profile_data()` MUST also call `WorkingMemoryService.clear_memory()`. Working memory persists 7 days after erasure request without this fix (R04).

---

## Plan 03 — Cache Analytics

### API-106: Cache analytics summary

**Effort**: 4h
**Depends on**: API-001
**Method + Path**: GET /api/v1/admin/analytics/cache/summary
**Auth**: tenant_admin
**Description**: Cache performance summary: total hit rate, cost saved, queries served from cache.
**Request**: Query params: `period` (7d, 30d)
**Response**: `{ "overall_hit_rate": float, "queries_served_from_cache": int, "total_queries": int, "llm_calls_avoided": int, "estimated_cost_saved_usd": float, "by_stage": { "embedding": { "hit_rate": float }, "intent": { "hit_rate": float }, "search": { "hit_rate": float }, "semantic": { "hit_rate": float } } }`
**Acceptance criteria**:

- [ ] All cache types reported
- [ ] Cost saved calculated from LLM calls avoided x cost/call
- [ ] Period filter works
- [ ] Tenant-scoped metrics
      **Notes**: See Plan 03 Phase C4.

---

### API-107: Cache analytics by index

**Effort**: 3h
**Depends on**: API-106
**Method + Path**: GET /api/v1/admin/analytics/cache/by-index
**Auth**: tenant_admin
**Description**: Per-index cache performance: hit rate, TTL efficiency, invalidation frequency.
**Request**: Query params: `period` (7d, 30d)
**Response**: `{ "indexes": [{ "index_id": "uuid", "name": "string", "hit_rate": float, "avg_ttl_efficiency": float, "invalidation_count": int, "cached_queries": int }] }`
**Acceptance criteria**:

- [ ] Per-index breakdown
- [ ] TTL efficiency: ratio of cache lifetime used before invalidation
- [ ] Period filter works
      **Notes**: Helps admins tune per-index cache TTL.

---

### API-108: Cache cost savings

**Effort**: 3h
**Depends on**: API-106
**Method + Path**: GET /api/v1/admin/analytics/cache/cost-savings
**Auth**: tenant_admin
**Description**: Dollar savings breakdown: LLM calls avoided x cost/call, embedding calls avoided, search calls cached.
**Request**: Query params: `period` (7d, 30d, 90d)
**Response**: `{ "total_saved_usd": float, "breakdown": { "llm_synthesis_avoided": { "calls": int, "cost_saved_usd": float }, "embedding_cached": { "calls": int, "cost_saved_usd": float }, "search_cached": { "calls": int, "cost_saved_usd": float } }, "cost_per_query_blended": float, "trend": [] }`
**Acceptance criteria**:

- [ ] Savings within 5% of actual cost reduction
- [ ] Breakdown by pipeline stage
- [ ] Trend data for cost per query over time
      **Notes**: "Your AI platform saved $X this month through intelligent caching."

---

### API-109: Set per-index cache TTL

**Effort**: 2h
**Depends on**: API-001
**Method + Path**: PATCH /api/v1/admin/indexes/{id}/cache-ttl
**Auth**: tenant_admin
**Description**: Set cache TTL for a specific search index.
**Request**: `{ "cache_ttl_seconds": 0|900|1800|3600|14400|28800|86400 }`
**Response**: `{ "index_id": "uuid", "cache_ttl_seconds": int }`
**Acceptance criteria**:

- [ ] TTL validated against allowed values (0 = disabled)
- [ ] Change takes effect immediately (next cache miss uses new TTL)
- [ ] Existing cached entries not invalidated (expire naturally)
      **Notes**: Default: 3600s (1 hour). See Plan 03 Phase C2.

---

## Plan 09 — Glossary Pre-translation

### API-110: Glossary expansions metadata in chat response

**Effort**: 2h
**Depends on**: API-008
**Method + Path**: (Part of POST /api/v1/chat/stream SSE response)
**Auth**: end_user
**Description**: SSE event `glossary_expansions_applied` included in chat stream response metadata. Lists all terms expanded inline during query preprocessing.
**Request**: (Embedded in chat stream)
**Response**: SSE event: `{ "expansions": [{ "term": "string", "full_form": "string", "position": int }] }`
**Acceptance criteria**:

- [ ] All expansions applied to current query listed
- [ ] "Terms interpreted" indicator data provided for frontend rendering
- [ ] Empty array when no expansions applied
      **Notes**: No new standalone endpoint. This is metadata in the chat SSE stream. See Plan 09 Sprint 3. Frontend must render "Terms interpreted" indicator on every response with at least one expansion.

---

## Plan 10 — Teams Collaboration

### API-111: Set active team for chat session ✅ COMPLETED

**Effort**: 2h
**Depends on**: API-078
**Method + Path**: PATCH /api/v1/me/active-team
**Auth**: end_user
**Description**: Set or clear the active team for the current user's chat session. Affects which team working memory is injected into prompts.
**Request**: `{ "team_id": "uuid|null" }`
**Response**: `{ "active_team_id": "uuid|null", "team_name": "string|null" }`
**Acceptance criteria**:

- [ ] User must be a member of the team
- [ ] Setting stored in Redis session key
- [ ] null clears active team (no team memory injected)
- [ ] Takes effect on next chat query
      **Notes**: See Plan 10 Sprint 7 (frontend team selector).

---

## Cross-Plan — Platform Admin Additional

### API-112: Platform admin audit log

**Effort**: 4h
**Depends on**: API-001
**Method + Path**: GET /api/v1/platform/audit-log
**Auth**: platform_admin
**Description**: Cross-tenant searchable audit log for all platform admin actions.
**Request**: Query params: `actor`, `action`, `tenant_id`, `start_date`, `end_date`, `page`, `page_size`
**Response**: `{ "items": [{ "id": "uuid", "actor": "string", "action": "string", "tenant_id": "uuid|null", "resource_type": "string", "resource_id": "string", "details": {}, "timestamp": "ISO-8601" }], "total": int }`
**Acceptance criteria**:

- [ ] All platform admin actions logged
- [ ] Filterable by actor, action, tenant, date
- [ ] Includes tenant provisioning, suspension, LLM profile changes, quota overrides
      **Notes**: Separate from tenant audit log (API-087). Platform scope.

---

### API-113: Platform admin impersonation

**Effort**: 6h
**Depends on**: API-001
**Method + Path**: POST /api/v1/platform/impersonate
**Auth**: platform_admin (platform_admin role only, not operator/support/security)
**Description**: Start impersonation session for a tenant admin. Returns a scoped JWT with impersonation flag. All actions during impersonation are logged with original admin identity.
**Request**: `{ "tenant_id": "uuid", "reason": "string" }`
**Response**: `{ "impersonation_token": "string", "expires_in": 3600, "tenant_id": "uuid" }`
**Acceptance criteria**:

- [ ] Only platform_admin role (not operator, support, security)
- [ ] Impersonation JWT includes `impersonated_by` claim
- [ ] All actions logged with both real and impersonated identity
- [ ] Session expires in 1 hour max
- [ ] Reason required and logged
      **Notes**: See `24-platform-rbac-specification.md` for impersonation flow.

---

### API-114: End impersonation

**Effort**: 2h
**Depends on**: API-113
**Method + Path**: POST /api/v1/platform/impersonate/end
**Auth**: platform_admin (impersonation session)
**Description**: End an active impersonation session.
**Request**: none
**Response**: `{ "status": "ended", "duration_seconds": int }`
**Acceptance criteria**:

- [ ] Impersonation token invalidated
- [ ] Session end logged in audit trail
      **Notes**: Token also expires naturally after 1 hour.

---

### API-115: Platform daily digest configuration

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: PATCH /api/v1/platform/preferences
**Auth**: platform_admin
**Description**: Configure platform admin preferences including daily digest email, alert thresholds, default sort orders.
**Request**: `{ "daily_digest_enabled": bool, "daily_digest_time": "HH:MM", "alert_thresholds": { "cost_spike_pct": float, "health_score_min": int }, "notification_preferences": {} }`
**Response**: `{ ...updated preferences }`
**Acceptance criteria**:

- [ ] Daily digest enable/disable
- [ ] Alert threshold configuration
- [ ] Per-admin preferences (not global)
      **Notes**: See Plan 05 Phase D2 daily digest.

---

### API-116: GDPR deletion workflow (platform)

**Effort**: 6h
**Depends on**: API-001
**Method + Path**: POST /api/v1/platform/tenants/{id}/gdpr-delete
**Auth**: platform_admin
**Description**: Initiate verified GDPR deletion pipeline for a tenant. Deletes all data across all stores with confirmation report.
**Request**: `{ "confirmed": true, "deletion_reference": "string (legal ref)" }`
**Response**: `{ "job_id": "uuid", "status": "in_progress", "estimated_completion": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Requires explicit confirmation
- [ ] Deletes: PostgreSQL records, Redis keys, search indexes, object storage, vault secrets
- [ ] Generates deletion confirmation report
- [ ] Irreversible after completion
- [ ] Audit log entry with legal reference
      **Notes**: See Plan 05 Phase D2 GDPR deletion workflow.

---

## Cross-Plan — End User Additional

### API-117: List user's agents

**Effort**: 3h
**Depends on**: API-001
**Method + Path**: GET /api/v1/agents
**Auth**: end_user
**Description**: List agents accessible to the current user based on their role and KB permissions.
**Request**: Query params: `page`, `page_size`
**Response**: `{ "items": [{ "id": "uuid", "name": "string", "description": "string", "category": "string", "avatar": "string|null" }], "total": int }`
**Acceptance criteria**:

- [ ] Only agents the user has permission to access returned
- [ ] Agent access verified from JWT claims
- [ ] Published agents only (no drafts)
      **Notes**: Feeds the chat agent selector. "Workspaces" in sidebar is WRONG for end users -- correct term is "Agents".

---

### API-118: Notification preferences

**Effort**: 2h
**Depends on**: API-001
**Method + Path**: PATCH /api/v1/me/notification-preferences
**Auth**: end_user
**Description**: Update user notification preferences (in-app only / email only / both).
**Request**: `{ "in_app": bool, "email": bool, "issue_updates": bool, "access_requests": bool }`
**Response**: `{ ...updated preferences }`
**Acceptance criteria**:

- [ ] At least one channel must remain enabled
- [ ] Preferences applied to all future notifications
      **Notes**: See Plan 04 Phase 3 notification preferences.

---

### API-119: Read/mark notifications

**Effort**: 3h
**Depends on**: API-012
**Method + Path**: PATCH /api/v1/notifications/{id}
**Auth**: end_user
**Description**: Mark a notification as read.
**Request**: `{ "read": true }`
**Response**: `{ "id": "uuid", "read": true }`
**Acceptance criteria**:

- [ ] Only own notifications can be marked
- [ ] Unread count decremented in real-time
      **Notes**: Feeds notification bell badge count.

---

### API-120: List notifications

**Effort**: 2h
**Depends on**: API-012
**Method + Path**: GET /api/v1/notifications
**Auth**: end_user
**Description**: Paginated list of user notifications.
**Request**: Query params: `read` (bool filter), `page`, `page_size`
**Response**: `{ "items": [{ "id": "uuid", "type": "string", "title": "string", "body": "string", "link": "string|null", "read": bool, "created_at": "ISO-8601" }], "total": int, "unread_count": int }`
**Acceptance criteria**:

- [ ] Paginated, newest first
- [ ] Filter by read/unread
- [ ] Unread count returned for badge
- [ ] Tenant-scoped
      **Notes**: Complements the SSE stream (API-012) for fetching historical notifications.

---

## Summary

| Plan                          | Endpoints | IDs                |
| ----------------------------- | --------- | ------------------ |
| 01 - Foundation + Auth        | 7         | API-001 to API-007 |
| 01 - Chat + SSE               | 5         | API-008 to API-012 |
| 04 - Issue Reporting          | 11        | API-013 to API-023 |
| 05 - Platform Admin           | 19        | API-024 to API-042 |
| 06 - Tenant Admin             | 45        | API-043 to API-088 |
| 07 - HAR (Agent Registry)     | 10        | API-089 to API-098 |
| 08 - Profile & Memory         | 7         | API-099 to API-105 |
| 03 - Cache Analytics          | 4         | API-106 to API-109 |
| 09 - Glossary Pre-translation | 1         | API-110            |
| 10 - Teams Collaboration      | 1         | API-111            |
| Cross-Plan Platform Admin     | 5         | API-112 to API-116 |
| Cross-Plan End User           | 4         | API-117 to API-120 |
| Gap Remediation               | 5         | API-121 to API-125 |
| **Total**                     | **125**   |                    |

---

## Gap Remediation (from 07-gap-analysis.md)

### API-121: Stripe webhook handler

**Effort**: 6h
**Depends on**: API-001
**Method + Path**: POST /api/v1/webhooks/stripe
**Auth**: none (Stripe signature verification)
**Description**: Webhook endpoint for Stripe payment events. Verifies Stripe webhook signature using `STRIPE_WEBHOOK_SECRET` from env. Handles events: `payment_intent.succeeded`, `invoice.paid`, `invoice.payment_failed`, `subscription.updated`, `subscription.deleted`, `charge.failed`, `charge.refunded`. Maps Stripe events to internal billing table updates. Idempotent — duplicate event deliveries handled via `stripe_event_id` deduplication.
**Acceptance criteria**:

- [ ] Stripe signature verification using `STRIPE_WEBHOOK_SECRET` env var
- [ ] Rejects requests with invalid or missing signature (401)
- [ ] Idempotency: stores processed `stripe_event_id`, skips duplicates (200 OK, no re-processing)
- [ ] Maps `payment_intent.succeeded` to invoice status update in billing tables
- [ ] Maps `subscription.updated` to tenant plan change
- [ ] Maps `charge.failed` to payment failure record + platform admin notification
- [ ] Returns 200 immediately, processes asynchronously for long-running operations
- [ ] All secrets from env (never hardcoded)
      **Notes**: GAP-005. HIGH. Without this, billing tables (DB-045) remain permanently empty. No authentication middleware — uses Stripe signature instead.

### API-122: Global error handler middleware

**Effort**: 4h
**Depends on**: API-001
**Method + Path**: Middleware (all routes)
**Auth**: all roles
**Description**: Global exception handler that ensures all API responses follow the standard error format: `{"error": "code", "message": "human-readable", "request_id": "uuid", "details": {}}`. Handles Pydantic 422 validation errors (field-specific messages), HTTPException (mapped to error codes), and unhandled 500 errors (generic message, full details logged server-side only).
**Acceptance criteria**:

- [ ] All error responses match format: `{error, message, request_id, details}`
- [ ] Pydantic 422 errors: `details` contains field-specific validation messages
- [ ] HTTPException: `error` field is a machine-readable code (e.g., `tenant_suspended`, `rate_limited`)
- [ ] Unhandled 500: generic "Internal server error" message to client, full traceback logged server-side
- [ ] `request_id` is a UUID generated per request (matches X-Request-ID header)
- [ ] Error codes documented in OpenAPI schema
- [ ] No stack traces or internal details leaked to client in production
      **Notes**: GAP-009. HIGH. TEST-072 already expects this format but no middleware implements it.

### API-124: File transaction dispute

**Effort**: 4h
**Depends on**: API-094
**Method + Path**: POST /api/v1/registry/transactions/{id}/dispute
**Auth**: tenant_admin (transaction party)
**Description**: File a dispute against a HAR transaction. Only the buyer or seller party in the transaction can file. Includes reason, evidence upload (optional), and counterparty notification. Transitions transaction state to DISPUTED.
**Request**: `{ "reason": "string", "category": "quality|delivery|billing|terms|other", "evidence_urls": ["string"], "desired_resolution": "string" }`
**Response**: `{ "dispute_id": "uuid", "transaction_id": "uuid", "status": "open", "filed_at": "ISO-8601" }`
**Acceptance criteria**:

- [ ] Only transaction buyer or seller can file dispute
- [ ] Transaction state transitions to DISPUTED
- [ ] Counterparty notified via notification system
- [ ] Platform admin notified of new dispute
- [ ] Dispute reason and evidence stored
- [ ] Cannot dispute already-disputed or completed transactions older than 30 days
- [ ] Audit trail entry created
      **Notes**: GAP-036. HIGH. Phase 1: manual platform admin resolution. Critical for Tier 3 financial transaction trust.

### API-125: Resolve transaction dispute

**Effort**: 3h
**Depends on**: API-124
**Method + Path**: POST /api/v1/registry/transactions/{id}/dispute/resolve
**Auth**: platform_admin
**Description**: Platform admin resolves a disputed transaction. Resolution options: in favor of buyer, in favor of seller, mutual agreement, void transaction. Both parties notified of resolution.
**Request**: `{ "resolution": "buyer_favor|seller_favor|mutual|void", "resolution_notes": "string", "action_taken": "string" }`
**Response**: `{ "dispute_id": "uuid", "resolution": "string", "resolved_at": "ISO-8601", "resolved_by": "uuid" }`
**Acceptance criteria**:

- [ ] Only platform_admin can resolve disputes
- [ ] Transaction state transitions to RESOLVED
- [ ] Both parties notified of resolution outcome
- [ ] Resolution includes notes and action taken
- [ ] Void resolution reverses any fee records
- [ ] Audit trail entry with resolver identity
      **Notes**: GAP-036. HIGH. Phase 1: manual resolution only. Automated arbitration deferred to Phase 2+.

---

## Dependency Graph (Critical Path)

```
API-001 (JWT middleware) ──> ALL other endpoints
API-001 ──> API-008 (Chat) ──> API-110 (Glossary expansions)
API-001 ──> API-024 (Provision tenant) ──> API-026-031 (Tenant management)
API-001 ──> API-032 (LLM profiles) ──> API-034 (Publish) ──> API-073 (Deploy from library)
API-001 ──> API-050/052 (Document store) ──> API-054-056 (Sync)
API-013 (Issue reports) ──> API-019-023 (Issue queues)
API-057-062 (Glossary CRUD) ──> API-008 (Chat glossary injection)
API-089 (Registry agents) ──> API-094 (Transactions)
API-099 (Profile) ──> API-105 (GDPR erasure)
API-078 (Teams) ──> API-111 (Active team)
```

## Effort Estimate Summary

| Category                 | Total Effort |
| ------------------------ | ------------ |
| Foundation + Auth        | 21h          |
| Chat + SSE               | 30h          |
| Issue Reporting          | 50h          |
| Platform Admin           | 93h          |
| Tenant Admin             | 152h         |
| HAR (Agent Registry)     | 40h          |
| Profile & Memory         | 21h          |
| Cache Analytics          | 12h          |
| Glossary Pre-translation | 2h           |
| Teams Collaboration      | 2h           |
| Cross-Plan               | 26h          |
| Gap Remediation          | 17h          |
| **Grand Total**          | **~466h**    |
