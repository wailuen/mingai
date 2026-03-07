# 04 — Issue Reporting: Implementation Plan

**Date**: 2026-03-05
**Status**: Draft — pending red team validation
**Estimated scope**: 6-8 sprints (12-16 weeks) across frontend, backend, and agent layers

---

## 1. Objectives and Success Metrics

### Primary Objectives

1. Provide end users a one-click mechanism to report bugs with automatic context capture
2. AI agent evaluates, enriches, and creates GitHub issues without manual intervention
3. Users receive automated status updates through the full fix lifecycle
4. Platform admins have cross-tenant quality visibility

### Success Metrics

| Metric                            | Target                                                                                                                                                                                                     | Measurement                         |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| Time to report (user action)      | < 60 seconds                                                                                                                                                                                               | Frontend analytics                  |
| Time to acknowledgment            | < 30 seconds                                                                                                                                                                                               | Notification delivery timestamp     |
| Time to SLA commitment            | < 5 minutes                                                                                                                                                                                                | Triage agent completion time        |
| GitHub issue creation rate        | > 99%                                                                                                                                                                                                      | Success/failure ratio               |
| Reporter satisfaction             | > 70% "issue resolved" confirmation                                                                                                                                                                        | Post-fix survey                     |
| SLA adherence rate                | **Deferred: Phase 4+ only.** Track resolution times silently for 3 months. Introduce SLA targets only when ≥ 90% natural adherence observed over 3 consecutive months. No SLA promises in Phase 1-3.       | Resolution time vs target           |
| Issue report adoption (voluntary) | ≥ 5% of active users/month (voluntary); ≥ 10% of error events auto-triggered. Note: 15% voluntary is an aspirational ceiling, not a launch target — red team calibrated realistic range at 5-8% voluntary. | Report volume vs user count         |
| Duplicate detection precision     | < 5% false positives                                                                                                                                                                                       | Manual review of flagged duplicates |
| Triage accuracy                   | > 85% correct severity                                                                                                                                                                                     | Engineer override rate              |

---

## 2. Phase Structure

```
Phase 1 (Sprints 1-2): Foundation — Data model, API, screenshot capture
Phase 2 (Sprints 3-4): AI Agent — Triage, duplicate detection, GitHub integration
Phase 3 (Sprints 5-6): Closed Loop — Webhooks, notifications, My Reports
Phase 4 (Sprints 7-8): Analytics & Admin — Dashboards, configuration, tenant settings
```

---

## 3. Phase 1: Foundation (Sprints 1-2, ~4 weeks)

### 3.1 Backend — Data Models and API

**Deliverables**:

- PostgreSQL table `issue_reports` via Alembic migration (tenant_id FK to tenants, RLS enabled)
- Object storage bucket `issue-screenshots` with tenant-scoped pre-signed URL support (uses ObjectStore abstraction — S3 on AWS, Azure Blob on Azure, GCS on GCP per CLOUD_PROVIDER)
- Pre-signed URL endpoint: `GET /api/v1/issue-reports/presign`
- Issue intake endpoint: `POST /api/v1/issue-reports`
- Rate limiting middleware (10/user/day, 50/tenant/day)
- Redis Stream `issue_reports:incoming` for async processing

**API Spec**:

```
POST /api/v1/issue-reports
Request:
{
  title: string (required, max 200)
  description: string (required, max 10000)
  type: "bug" | "performance" | "ux" | "feature"  // Note: "feature" type is routed separately — NOT to the bug triage queue. Feature requests go to product backlog channel; triage agent skips severity classification for type=feature.
  severity_hint: "high" | "medium" | "low" | "suggestion" | null
  screenshot_blob_url: string | null
  screenshot_annotations: Annotation[] | null
  session_context: IssueContextPayload
}

Response 201:
{
  id: "rpt_abc123"
  status: "received"
  message: "Report submitted successfully"
}

Response 429:
{
  error: "rate_limit_exceeded"
  retry_after: "2026-03-06T00:00:00Z"
}
```

**Implementation tasks**:

- [ ] Define PostgreSQL `issue_reports` schema and create table via Alembic migration (DataFlow model, RLS policy)
- [ ] Implement object storage pre-sign endpoint with tenant-scoped path isolation
- [ ] Implement intake endpoint with JWT validation, schema validation, rate limiting
- [ ] Implement Redis Stream enqueue
- [ ] Write unit tests for validation, rate limiting
- [ ] Write integration tests against real PostgreSQL and Redis

### 3.2 Frontend — Reporter Widget

**Deliverables**:

- Floating "Report Issue" button (position: fixed, bottom-right, z-index: 9999)
- Issue reporter dialog with screenshot preview and annotation toolbar
- Session context collector (auto-captures current URL, last query, console errors)
- Screenshot capture via html2canvas (primary) with manual upload fallback
- **RAG response area blurred by default** in screenshot preview; user must explicitly confirm un-blur before upload (CRITICAL: prevents accidental leakage of sensitive retrieved content — R4.1)
- PII auto-redaction (password fields, pattern matching)
- Form validation and submission
- Offline queue (IndexedDB) for network failure resilience

**Implementation tasks**:

- [ ] Create `IssueReporterButton` component (floating trigger)
- [ ] Create `IssueReporterDialog` component (modal with form + annotation canvas)
- [ ] Implement `ScreenshotCapture` service (html2canvas + pre-sign upload)
- [ ] Implement `SessionContextCollector` hook (reads RAG context from React state/store)
- [ ] Implement `AnnotationCanvas` component (highlight, arrow, text, redact tools)
- [ ] Implement PII auto-redaction in screenshot
- [ ] Implement offline queue using IndexedDB
- [ ] Add keyboard shortcut listener (Ctrl+Shift+F)
- [ ] Error detection monitor for 5xx responses (auto-prompt)
- [ ] Write component tests (unit)

### 3.3 Success Criteria for Phase 1

- [ ] User can click button, fill form, see screenshot, and submit
- [ ] Screenshot uploaded to Azure Blob in < 5 seconds
- [ ] Issue stored in PostgreSQL `issue_reports` table with all context fields
- [ ] Redis queue receives the message
- [ ] Rate limiting correctly blocks at 10/day

---

## 4. Phase 2: AI Agent — Triage and GitHub Integration (Sprints 3-4, ~4 weeks)

### 4.1 AI Triage Agent (Kaizen)

**Deliverables**:

- Issue Triage Agent registered in A2A platform
- Consumes from Redis Stream `issue_reports:incoming`
- Duplicate detection using vector similarity (pgvector on `issue_embeddings` table in PostgreSQL)
- Severity classification (P0-P4) with reasoning
- Category classification with root cause hypothesis
- GitHub issue creation via GitHub API (bot account)
- SLA calculation and storage
- PostgreSQL `issue_reports` update with triage result

**Implementation tasks**:

- [ ] Add `issue_embeddings` table with pgvector extension (HNSW index on embedding column, tenant_id RLS)
- [ ] Implement embedding generation for issue descriptions
- [ ] Implement duplicate detection logic with configurable threshold (0.88)
- [ ] Implement severity classification prompt (using model from .env `TRIAGE_MODEL`)
- [ ] Implement category + root cause hypothesis prompt
- [ ] Build GitHub API client with bot account credentials (read from .env)
- [ ] Implement GitHub issue template generation with session context
- [ ] Implement SLA calculation matrix
- [ ] Register triage agent in A2A worker registry
- [ ] Implement PostgreSQL `issue_reports` update after triage
- [ ] Write integration tests (real PostgreSQL with pgvector, real Redis, mocked GitHub API in Tier 2)
- [ ] Write E2E tests with real GitHub test repository (Tier 3)

**A2A Agent Registration**:

```python
# Issue Triage Agent — A2A worker
class IssueTriageAgent(BaseAgent):
    name = "issue-triage-agent"
    consumes = "issue_reports:incoming"    # Redis Stream
    model = os.environ["TRIAGE_MODEL"]    # GPT-5 Mini from .env
    max_retries = 3
    timeout = 120  # 2 minutes before fallback to P3/bug default
```

### 4.2 Duplicate Resolution Flow

**Deliverables**:

- Duplicate linking in PostgreSQL (parent_issue_id, duplicate_confidence columns on `issue_reports`)
- Reporter subscription to parent issue notifications
- Priority boost logic (report count thresholds)

**Implementation tasks**:

- [ ] Implement duplicate linking (update child report with parent reference)
- [ ] Implement reporter notification subscription to parent issue
- [ ] Implement priority boost: 5 reports → flag for review, 10 reports → auto-escalate
- [ ] Test duplicate detection accuracy with historical issue scenarios

### 4.3 Success Criteria for Phase 2

- [ ] Triage agent processes 100% of queued reports within 5 minutes
- [ ] GitHub issue created with all context fields
- [ ] Semantic duplicate detection achieves < 5% false positive rate (manual review)
- [ ] Fallback to P3/bug for triage timeout works correctly
- [ ] SLA committed via notification within 5 minutes of submission

---

## 5. Phase 3: Closed Loop — Webhooks and Notifications (Sprints 5-6, ~4 weeks)

### 5.1 GitHub Webhook Handler

**Deliverables**:

- Webhook endpoint: `POST /api/v1/webhooks/github`
- HMAC-SHA256 signature validation
- Event mapping: issues.labeled, pull_request.opened, pull_request.merged, release.published
- Issue record status updates on each event
- Notification dispatch on each status change

**Implementation tasks**:

- [ ] Implement webhook endpoint with signature validation
- [ ] Implement event-to-status mapping logic
- [ ] Implement PostgreSQL `issue_reports` status update per event
- [ ] Implement notification dispatch (in-app + email) per event
- [ ] Register webhook URL in GitHub repository settings (via GitHub API)
- [ ] Write integration tests for each event type

### 5.2 In-App Notification System

**Deliverables**:

- Notification bell in header with unread count badge
- Real-time delivery via SSE (Server-Sent Events)
- Notification list panel with read/unread state
- Link from notification to report detail view
- User notification preferences (in-app only / email only / both)

**Implementation tasks**:

- [ ] Create `NotificationBell` component with SSE subscription
- [ ] Implement `NotificationList` panel (dropdown or drawer)
- [ ] Implement notification preferences API and settings page section
- [ ] Backend: SSE endpoint `/api/v1/notifications/stream` (per-user stream)
- [ ] Backend: Notification record stored in PostgreSQL `notifications` table (already exists per 02-technical-migration-plan.md)
- [ ] Test SSE delivery latency < 2 seconds

### 5.3 My Reports Dashboard (User-Facing)

**Deliverables**:

- Route: `/my-reports`
- List of user's submitted reports with status badges
- Report detail view: timeline, AI triage result, GitHub issue link, SLA
- "Still happening?" confirmation flow (after fix notification)
- Follow-up comment capability

**Implementation tasks**:

- [ ] Create `MyReports` page with paginated list
- [ ] Create `ReportDetail` view with status timeline
- [ ] Implement "Still happening?" prompt (post-resolution)
- [ ] Implement comment/additional-info submission
- [ ] Implement engineer → user information request (notify user with question)

### 5.4 Email Notification Templates

**Deliverables**:

- Acknowledgment email template
- SLA commitment email template
- Fix status update email templates (one per stage)
- Won't Fix email template
- All templates use SendGrid dynamic templates

**Implementation tasks**:

- [ ] Design email templates (minimal, informative, branded)
- [ ] Implement SendGrid template IDs in backend notification service
- [ ] Test email delivery for each template

### 5.5 Success Criteria for Phase 3

- [ ] GitHub webhook events correctly update PostgreSQL `issue_reports` status
- [ ] SSE delivers notifications within 2 seconds of event
- [ ] Email delivered within 60 seconds of event
- [ ] User can view all their reports and history in My Reports
- [ ] "Still happening?" flow correctly creates regression report

---

## 6. Phase 4: Analytics and Admin Configuration (Sprints 7-8, ~4 weeks)

### 6.1 Platform Admin Issues Dashboard

**Deliverables**:

- Route: `/admin/issues`
- Issue heatmap: volume by tenant, severity, category
- Cross-tenant duplicate view
- SLA adherence metrics
- MTTR by severity
- Top 10 bugs by report volume
- Time series trend charts (week-over-week)

**Implementation tasks**:

- [ ] Design dashboard layout (following existing admin dashboard patterns)
- [ ] Implement issues analytics API: `GET /api/v1/admin/issues/stats`
- [ ] Implement cross-tenant duplicate view
- [ ] Implement SLA adherence calculation
- [ ] Implement MTTR calculation
- [ ] Create chart components (reuse existing chart library)
- [ ] Add CSV export for monthly report

### 6.2 Engineering Queue View

**Deliverables**:

- Route: `/admin/issues/queue`
- Incoming, triaged, in-progress, SLA-at-risk, resolved views
- Per-issue action buttons: Accept, Override Severity, Won't Fix, Request Info, Assign
- Batch actions: assign multiple to sprint, mark multiple as reviewed

**Implementation tasks**:

- [ ] Create queue view with filter tabs
- [ ] Implement per-issue action endpoints (PATCH /api/v1/issue-reports/:id)
- [ ] Implement batch action endpoint
- [ ] Implement "Request Information" flow (message to reporter)
- [ ] Implement sprint/milestone assignment (GitHub API call)

### 6.3 Tenant Configuration

**Deliverables**:

- Route: `/settings/issue-reporting`
- GitHub/GitLab/Jira/Linear integration setup
- Notification recipient configuration
- Custom categories
- Custom SLA targets
- Widget appearance settings

**Implementation tasks**:

- [ ] Create settings page section for issue reporting
- [ ] Implement integration configuration API (store in `tenant_configs` table, config_type='issue_reporting')
- [ ] Implement triage agent: use tenant's repo if configured, else platform default
- [ ] Implement tenant admin issues view (tenant-scoped version of admin dashboard)
- [ ] Test each integration type (GitHub, GitLab, Jira, Linear) with real APIs

### 6.4 SLA Management System

**Deliverables**:

- Platform-level SLA defaults configurable by platform admin
- Tenant-level SLA overrides
- SLA breach alerting (email/Slack when approaching deadline)
- SLA breach reporting in analytics

**Implementation tasks**:

- [ ] Implement SLA configuration API
- [ ] Implement SLA monitoring background job (check every hour)
- [ ] Implement SLA breach alert dispatch
- [ ] Track SLA adherence in issue records

### 6.5 Success Criteria for Phase 4

- [ ] Platform admin can view cross-tenant issue heatmap
- [ ] SLA adherence rate visible and trackable
- [ ] Tenant admin can configure GitHub integration in < 15 minutes
- [ ] Engineering queue shows all actionable states
- [ ] SLA at-risk alerts fire 24 hours before breach

---

## 7. Non-Functional Requirements

### 7.1 Performance

- Screenshot capture: < 2 seconds (html2canvas on typical page)
- Screenshot upload: < 5 seconds (client-to-blob direct upload)
- API response for intake: < 500ms
- Triage agent processing: < 5 minutes (P99)
- SSE notification delivery: < 2 seconds

### 7.2 Availability

- Issue intake API: 99.9% uptime (separate from main RAG API — degraded mode OK)
- Triage agent: async (queue-based) — 5-minute delay acceptable on agent downtime
- GitHub API failure: graceful fallback — store in queue, retry, notify admin

### 7.3 Security

- JWT required for all issue report endpoints
- Screenshot blob access via tenant-scoped SAS tokens (24h TTL)
- GitHub bot account: issues-only write permission (no code access)
- Console error log sanitization: remove credentials, tokens before inclusion
- Input length limits: title 200 chars, description 10,000 chars
- Webhook HMAC-SHA256 validation mandatory

### 7.4 Scalability

- Redis Stream handles burst traffic (spikes during product launches, incidents)
- Triage agent: horizontal scaling — multiple workers can consume from stream
- Issue embedding index: pgvector HNSW on `issue_embeddings` table, filtered by category in query predicate
- PostgreSQL: Row-Level Security enforces tenant_id isolation at database level (no application-layer filtering needed)

### 7.5 Privacy and Compliance

- Screenshots stored for 90 days active, 1 year cold storage, then deleted
- PII auto-redaction before upload (password fields, known PII patterns)
- Cross-tenant embedding index: no tenant PII, no issue text — vectors only
- GDPR: user can request deletion of all their issue reports (admin API)

---

## 8. Technical Dependencies

| Dependency         | Type     | Already Available | Notes                                                                           |
| ------------------ | -------- | ----------------- | ------------------------------------------------------------------------------- |
| PostgreSQL         | Existing | Yes               | New `issue_reports` and `issue_embeddings` tables via Alembic migration         |
| Object Storage     | Existing | Yes               | New tenant-scoped bucket/container via ObjectStore abstraction (CLOUD_PROVIDER) |
| pgvector           | New      | No                | PostgreSQL extension for vector similarity — enable on DB instance              |
| Redis              | Existing | Yes               | New stream key                                                                  |
| A2A Agent Platform | Existing | Yes               | New worker registration                                                         |
| Kaizen             | Existing | Yes               | Triage agent implementation                                                     |
| SendGrid           | Existing | Yes               | New templates needed                                                            |
| GitHub API         | New      | No                | Bot account + OAuth app setup                                                   |
| html2canvas (npm)  | New      | No                | No server dependency                                                            |
| SSE backend        | New      | No                | Extend FastAPI with SSE endpoint                                                |

---

## 9. Risk Assessment

| Risk                                   | Probability | Impact | Mitigation                                                       |
| -------------------------------------- | ----------- | ------ | ---------------------------------------------------------------- |
| html2canvas fails on complex pages     | Medium      | Medium | Manual screenshot fallback; clear user instruction               |
| GitHub API rate limits                 | Low         | Medium | Rate-limited bot account; exponential backoff retry              |
| AI triage quality below 85% accuracy   | Medium      | Medium | Human review queue; override capability for engineers            |
| SLA breach alerts not actioned by team | Medium      | High   | Escalation chain: email → Slack → PagerDuty for P0/P1            |
| Low reporter adoption (< 5% users)     | Medium      | High   | Auto-trigger on errors; admin policy to require in-app reporting |
| Cross-tenant dedup false positives     | Low         | High   | Threshold tuning; false positive monitor; manual override        |
| GDPR deletion requests                 | Low         | Low    | Admin deletion API from day 1                                    |

---

## 10. Phased Rollout Strategy

### Phase 1 Rollout: Internal Beta (After Phase 2)

- Deploy to mingai's internal team only
- Team uses it to report platform issues
- Validate triage agent quality and GitHub integration

### Phase 2 Rollout: Tenant Beta (After Phase 3)

- 2-3 trusted tenant admins enabled
- Monitor adoption, triage quality, notification delivery
- Collect qualitative feedback on reporter UX

### Phase 3 Rollout: General Availability (After Phase 4)

- Enable for all tenants
- Announce to users via in-app tooltip + email
- Dashboard visible to all platform admins

### Rollback Plan

- Feature flag: `FEATURE_ISSUE_REPORTING_ENABLED` (per-tenant)
- If critical issue: disable flag, revert to email channel
- No data loss: PostgreSQL `issue_reports` records preserved
