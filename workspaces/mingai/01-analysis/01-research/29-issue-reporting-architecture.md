# 29 — In-App Issue Reporting: Technical Architecture

**Date**: 2026-03-05
**Status**: Draft — Red team reviewed 2026-03-05 (see 09-05 for findings). Implementation plan is `02-plans/04-issue-reporting-plan.md`. **NOTE: All persistent storage uses PostgreSQL, not Cosmos DB. See `12-database-architecture-analysis.md`.**
**Feature**: AI-powered user issue reporting with screenshot capture, agent triage, GitHub integration, and closed-loop notifications

---

## 1. Overview

Users of the mingai platform encounter bugs, unexpected behaviors, or have improvement ideas. Today there is no structured channel — issues go to email, Slack, or get lost entirely. This feature provides an in-app mechanism to:

1. Capture the issue with a screenshot and contextual metadata
2. AI agent evaluates the report (severity, category, duplicate detection)
3. Agent creates a structured GitHub issue with full reproduction context
4. Fix is scheduled and SLA is communicated back to the user
5. User receives automated status updates as the fix progresses

Because mingai owns the full session context (RAG query, model used, data sources, confidence scores, tenant config), the issue reports are richer than any standalone feedback tool can produce.

---

## 2. System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Issue Reporter Widget                              │    │
│  │  ├── Trigger Button (floating, keyboard shortcut)   │    │
│  │  ├── Screenshot Capture (html2canvas / native API)  │    │
│  │  ├── Annotation Canvas (draw, highlight, redact)    │    │
│  │  ├── Issue Form (type, description, severity hint)  │    │
│  │  └── Session Context Collector                      │    │
│  └─────────────────────────────────────────────────────┘    │
└────────────────────────┬────────────────────────────────────┘
                         │ POST /api/v1/issue-reports
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI)                          │
│  ┌──────────────────────┐  ┌──────────────────────────┐    │
│  │  Issue Intake API    │  │  Blob Storage             │    │
│  │  ├── Auth validation │  │  (Azure Blob / S3)        │    │
│  │  ├── Payload schema  │  │  Screenshot storage       │    │
│  │  ├── Rate limiting   │  │  with tenant isolation    │    │
│  │  └── Queue dispatch  │  └──────────────────────────┘    │
│  └──────────┬───────────┘                                   │
│             │ Enqueue to Redis Stream                        │
│  ┌──────────▼───────────────────────────────────────────┐   │
│  │  Issue Triage Agent (Kaizen / A2A)                   │   │
│  │  ├── Context enrichment (session data injection)     │   │
│  │  ├── Duplicate detection (vector similarity search)  │   │
│  │  ├── Severity scoring (P0-P4 classification)         │   │
│  │  ├── Category classification (bug/perf/ux/feature)   │   │
│  │  ├── Reproduction steps generation                   │   |
│  │  └── GitHub issue creation (via GitHub API)          │   │
│  └──────────┬───────────────────────────────────────────┘   │
│             │ Write to PostgreSQL (issue_reports table)       │
│  ┌──────────▼───────────────────────────────────────────┐   │
│  │  Notification Agent                                  │   │
│  │  ├── In-app notification (WebSocket / SSE)           │   │
│  │  ├── Email summary (SendGrid)                        │   │
│  │  └── SLA calculation and commitment message          │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                GitHub / GitLab                               │
│  ├── Issue created with structured template                  │
│  ├── Labels: severity, category, tenant-id (hashed)         │
│  ├── Milestone assigned based on SLA                        │
│  └── Webhook → backend → user notification on PR merge      │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Session Context Payload

When a user submits a report, the frontend automatically attaches:

```typescript
interface IssueContextPayload {
  // User context
  user_id: string; // hashed for privacy
  tenant_id: string;
  user_role: string;
  page_url: string; // current URL
  page_component: string; // active React component name

  // RAG session context (if applicable)
  last_query?: string;
  last_query_id?: string;
  model_used?: string; // from env slot, not hardcoded name
  data_sources_queried?: string[]; // index names
  confidence_score?: number;
  tokens_consumed?: number;
  response_time_ms?: number;

  // Browser context
  browser_name: string;
  browser_version: string;
  viewport_width: number;
  viewport_height: number;
  device_pixel_ratio: number;
  user_agent: string;

  // Frontend error context
  console_errors?: string[]; // last 10 console.error() calls
  network_failures?: {
    url: string;
    status: number;
    method: string;
  }[];

  // Screenshot
  screenshot_blob_url: string; // pre-signed Azure Blob URL
  screenshot_annotations: Annotation[];
}
```

This payload is the fundamental competitive differentiator — no standalone issue reporting tool has access to this context automatically.

---

## 4. Issue Triage Agent Design

### 4.1 Duplicate Detection

Before creating a GitHub issue, the agent checks for duplicates:

```python
# Pseudo-code (Kaizen agent signature)
async def check_duplicate(description: str, tenant_id: str) -> DuplicateResult:
    embedding = await embed(description)
    similar = await vector_search(
        embedding,
        index="issue_reports",
        filters={"status": ["open", "in_progress"]},
        top_k=5,
        min_score=0.88   # threshold for "likely duplicate"
    )
    return DuplicateResult(
        is_duplicate=len(similar) > 0,
        parent_issue_id=similar[0].github_issue_id if similar else None,
        similarity_score=similar[0].score if similar else 0.0
    )
```

Cross-tenant duplicate detection requires careful data handling:

- Embeddings are stored WITHOUT tenant PII
- Description text is NOT stored cross-tenant
- Only embedding vector + category label + severity + github_issue_id are shared

### 4.2 Severity Classification

```
P0 — Critical/System Down
  Criteria: service unavailable, data loss risk, security breach
  SLA: 4 hours fix, immediate notification

P1 — High/Core Function Broken
  Criteria: core RAG function fails, auth broken, data corruption
  SLA: 24 hours fix, daily notification

P2 — Medium/Degraded Experience
  Criteria: slow responses, UI broken on specific browser, partial failures
  SLA: 1 week fix, weekly notification

P3 — Low/Cosmetic or Minor
  Criteria: typos, minor UI misalignments, non-critical UX issues
  SLA: 1 month, notification on release

P4 — Enhancement/Feature Request
  Criteria: new functionality, improvements
  SLA: roadmap evaluation, notification on roadmap update
```

### 4.3 GitHub Issue Template

```markdown
## Summary

[AI-generated 1-paragraph summary]

## Steps to Reproduce

1. [AI-generated from session context]
2. ...

## Expected Behavior

[User description]

## Actual Behavior

[User description + AI enrichment from console errors]

## Environment

- Tenant: [hashed tenant ID]
- Browser: Chrome 121 / macOS 14.3
- Page: /workspace/knowledge-base
- Component: DocumentUploadPanel

## RAG Context (if applicable)

- Query: "[last user query]"
- Model: [model slot name]
- Data Sources: [list]
- Confidence Score: 0.72
- Response Time: 3240ms

## Severity Classification

**P2 — Degraded Experience**
Rationale: [AI-generated rationale]

## Screenshot

![Screenshot]([azure-blob-presigned-url])

## Session Metadata

- Report ID: rpt_abc123
- Submitted: 2026-03-05T14:23:00Z
- User Role: end_user
```

---

## 5. Data Model

### 5.1 Cosmos DB Collection: `issue_reports`

```json
{
  "id": "rpt_abc123",
  "tenant_id": "ten_xyz",
  "user_id_hash": "u_hash_789",
  "status": "open", // open | triaged | in_progress | resolved | closed | wont_fix
  "category": "bug", // bug | performance | ux | feature
  "severity": "P2",
  "title": "Document upload fails silently on large PDFs",
  "description": "...",
  "github_issue_id": 4521,
  "github_issue_url": "https://github.com/org/repo/issues/4521",
  "github_pr_id": null,
  "sla_target": "2026-03-12T00:00:00Z",
  "sla_communicated_at": "2026-03-05T14:24:00Z",
  "duplicate_of": null,
  "duplicate_confidence": null,
  "screenshot_blob_url": "https://...",
  "session_context": {
    /* IssueContextPayload */
  },
  "ai_triage_result": {
    "severity_reasoning": "...",
    "category_reasoning": "...",
    "duplicate_check": { "is_duplicate": false },
    "triage_model": "gpt-5-mini",
    "triage_at": "2026-03-05T14:23:45Z"
  },
  "notifications_sent": [
    { "type": "acknowledgment", "at": "2026-03-05T14:24:00Z" },
    { "type": "sla_commitment", "at": "2026-03-05T14:24:00Z" }
  ],
  "created_at": "2026-03-05T14:23:00Z",
  "updated_at": "2026-03-05T14:24:00Z",
  "_partitionKey": "ten_xyz"
}
```

### 5.2 Vector Index (Azure AI Search): `issue_embeddings`

```json
{
  "id": "rpt_abc123",
  "embedding": [...],           // 1536-dim vector
  "category": "bug",
  "severity": "P2",
  "status": "open",
  "github_issue_id": 4521,
  "created_at": "2026-03-05T14:23:00Z"
}
```

Note: NO tenant PII, NO user data — only for cross-tenant duplicate detection.

---

## 6. GitHub Webhook Integration

For closed-loop notifications, GitHub webhooks fire on:

| Event                 | Action                           |
| --------------------- | -------------------------------- |
| `issues.labeled`      | Confirm triage received          |
| `pull_request.opened` | Notify "fix in progress"         |
| `pull_request.merged` | Notify "fix deployed to staging" |
| `release.published`   | Notify "fix live in production"  |

Webhook handler route: `POST /api/v1/webhooks/github`

- Validates `X-Hub-Signature-256` header
- Maps `github_issue_id` to `issue_report` record
- Triggers notification to user(s) who reported

---

## 7. Screenshot Capture Architecture

### Frontend Implementation

```typescript
// Option A: html2canvas (CSS-based, no browser permission needed)
import html2canvas from "html2canvas";

async function captureScreen(): Promise<Blob> {
  const canvas = await html2canvas(document.body, {
    allowTaint: false,
    useCORS: true,
    scale: window.devicePixelRatio,
  });
  return new Promise((resolve) => canvas.toBlob(resolve, "image/png", 0.85));
}

// Option B: Screen Capture API (requires user permission, higher fidelity)
async function captureScreenNative(): Promise<Blob> {
  const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
  const track = stream.getVideoTracks()[0];
  const imageCapture = new ImageCapture(track);
  const bitmap = await imageCapture.grabFrame();
  track.stop();
  // convert bitmap to blob
}
```

**Chosen approach**: html2canvas as primary (no permission prompt, works immediately), Screen Capture API as optional upgrade for pixel-perfect fidelity.

### Privacy: PII Redaction

Before screenshot upload:

1. The annotation canvas allows users to manually redact sensitive areas (draw black boxes)
2. Auto-redaction: scan for input fields with type=password and blur them programmatically
3. Redact known PII patterns: email fields, credit card inputs, SSN patterns

### Upload Flow

```
1. User submits → frontend captures screenshot
2. POST /api/v1/issue-reports/presign → get pre-signed Azure Blob upload URL (30s TTL)
3. PUT screenshot directly to Azure Blob (client-to-blob, no backend bandwidth)
4. Screenshot URL included in issue payload
5. After 90 days: screenshots moved to cold storage; after 1 year: deleted
```

---

## 8. Rate Limiting and Abuse Prevention

- Per-user: max 10 issue reports per 24 hours
- Per-tenant: max 50 issue reports per 24 hours
- Duplicate submission: if identical description within 5 minutes → reject with "possible duplicate" message
- AI triage budget: use GPT-5 Mini for triage (low cost), not GPT-5.2-chat
- Screenshot max size: 5MB (compressed to target); reject if > 10MB

---

## 9. Notification Channels

| Notification Type        | Channel                     | Timing                |
| ------------------------ | --------------------------- | --------------------- |
| Acknowledgment           | In-app toast + email        | Immediate (<30s)      |
| SLA commitment           | In-app + email              | After triage (<5 min) |
| Fix in progress          | In-app notification         | On PR open            |
| Fix deployed to staging  | In-app notification         | On PR merge           |
| Fix live in production   | In-app notification + email | On release            |
| Issue closed (won't fix) | In-app + email              | Manual trigger        |

---

## 10. Tenant Isolation and Multi-Tenancy

- Issue reports are partitioned by `tenant_id` in Cosmos DB
- Screenshots stored in per-tenant Azure Blob container with tenant-scoped SAS tokens
- Platform admins can see ALL tenants' issues (for duplicate correlation)
- Tenant admins can see their tenant's issues only
- Cross-tenant duplicate detection uses embeddings only (no text leakage)
- GitHub issues: single repository for platform issues, tenant identified by hashed label only

---

## 11. Integration Points with Existing Architecture

| Component          | Integration                                                   |
| ------------------ | ------------------------------------------------------------- |
| Auth (JWT)         | Issue reports require valid JWT; user_id extracted from token |
| Redis              | Issue report queue (Redis Stream `issue_reports:incoming`)    |
| Azure AI Search    | Duplicate embedding search (new index `issue_embeddings`)     |
| Azure Blob         | Screenshot storage (new container `issue-screenshots`)        |
| Cosmos DB          | Issue records (new collection `issue_reports`)                |
| A2A Agent Platform | Triage agent registered as A2A worker                         |
| Kaizen             | Issue triage agent implementation                             |
| GitHub API         | Issue creation, label management, milestone assignment        |
| SendGrid           | Email notifications                                           |
| WebSocket / SSE    | Real-time in-app notifications                                |

---

## 12. Security Considerations

- Screenshots may contain PII → tenant-scoped storage, pre-signed URLs with 24h TTL
- GitHub issue creation uses a dedicated bot account (not admin credentials)
- Bot account has write access to issues only, not code
- Console error logs sanitized: remove tokens, passwords, API keys before inclusion
- Cross-tenant embedding search: all embeddings normalized, no tenant metadata in vector store
- Webhook signature validation mandatory (HMAC-SHA256)
- Issue description limited to 10,000 characters to prevent prompt injection via user input
