# Integration Guide: Backend ↔ Frontend

---

## API Contract (Phase 1)

The backend exposes a REST API at port 8022. The frontend at port 3022 consumes it.

### Auth Endpoints

```
POST /api/v1/auth/local/login        → {access_token, token_type, expires_in}
POST /api/v1/auth/token/refresh      → {access_token, token_type, expires_in}
POST /api/v1/auth/logout             → 204 No Content
GET  /api/v1/auth/current            → {id, email, name, tenant_id, roles, plan, scope}
```

### Platform Admin Endpoints (scope=platform required)

```
GET    /api/v1/admin/tenants                   → paginated tenant list
POST   /api/v1/admin/tenants                   → provision new tenant (async, returns job_id)
GET    /api/v1/admin/tenants/{id}              → tenant detail
PATCH  /api/v1/admin/tenants/{id}/status       → {status: "suspended" | "active"}
GET    /api/v1/admin/tenants/{id}/quota        → {tokens_used, tokens_limit, ...}
PATCH  /api/v1/admin/tenants/{id}/quota        → update quota limits
GET    /api/v1/admin/provisioning/{job_id}     → provisioning job status (SSE stream)
GET    /api/v1/admin/llm-profiles              → list published LLM profiles
```

### Tenant Admin Endpoints (scope=tenant + admin role required)

```
GET    /api/v1/workspace                       → workspace settings
PATCH  /api/v1/workspace                       → update name, logo, timezone
GET    /api/v1/users                           → user directory (tenant-scoped)
POST   /api/v1/users/invite                    → single or bulk invite
PATCH  /api/v1/users/{id}/role                 → change role
PATCH  /api/v1/users/{id}/status               → suspend/activate
DELETE /api/v1/users/{id}                      → delete (anonymize)
GET    /api/v1/integrations/sharepoint/status  → connection status
POST   /api/v1/integrations/sharepoint/connect → test + save connection
POST   /api/v1/integrations/sharepoint/sync    → trigger sync
GET    /api/v1/integrations/googledrive/status → connection status
POST   /api/v1/integrations/googledrive/auth   → OAuth2 flow initiation
POST   /api/v1/sync/trigger                    → manual sync trigger
GET    /api/v1/sync/status                     → sync status + failure list
```

### End User Endpoints

```
POST   /api/v1/chat/stream                     → SSE stream (chat responses)
GET    /api/v1/conversations                   → user's conversation list
POST   /api/v1/conversations                   → create conversation
GET    /api/v1/conversations/{id}/messages     → message history
POST   /api/v1/feedback                        → thumbs up/down on message
GET    /api/v1/my-reports                      → user's issue reports (Phase 3+)
```

---

## Error Format (Consistent Across All Endpoints)

```json
{
  "error": "resource_not_found",
  "message": "Tenant not found",
  "request_id": "req_abc123"
}
```

HTTP status codes: 400 (validation), 401 (auth), 403 (permission), 404 (not found), 429 (rate limit), 500 (server error).

---

## SSE Chat Protocol

The chat endpoint returns Server-Sent Events. Frontend must handle all event types:

```
event: status
data: {"stage": "searching", "message": "Searching knowledge base..."}

event: sources
data: {"sources": [{"title": "HR Policy", "score": 0.91, "url": "..."}]}

event: response_chunk
data: {"text": "Based on the policy..."}

event: metadata
data: {"retrieval_confidence": 0.87, "tokens_used": 450, "model": "gpt-5.2-chat"}

event: done
data: {"conversation_id": "uuid", "message_id": "uuid"}
```

**Critical**: label `retrieval_confidence` score as "retrieval confidence" in UI (canonical spec — not "answer quality" or "AI confidence").

---

## Tenant Isolation Verification (Integration Test)

The following integration test must pass before Phase 1 is considered complete. Run this test as the final gate.

```python
# tests/integration/test_tenant_isolation.py
import pytest

def test_cross_tenant_data_isolation(tenant_a_client, tenant_b_client, db):
    # Tenant A creates a conversation
    conv = tenant_a_client.post("/api/v1/conversations", json={"title": "test"})
    conv_id = conv.json()["id"]

    # Tenant B tries to access it — must get 404
    response = tenant_b_client.get(f"/api/v1/conversations/{conv_id}")
    assert response.status_code == 404

def test_rls_prevents_direct_db_access(db, tenant_a_id, tenant_b_id):
    # Set DB context to tenant B
    with db.set_tenant(tenant_b_id):
        # Try to query tenant A's conversations directly
        rows = db.execute("SELECT * FROM conversations").fetchall()
        # RLS must return zero rows for tenant A's data
        tenant_a_rows = [r for r in rows if r["tenant_id"] == tenant_a_id]
        assert len(tenant_a_rows) == 0
```

---

## CORS Configuration

Backend must allow frontend origin:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ["FRONTEND_URL"]],  # never wildcard in production
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

---

## Environment Variables Required (Both Services)

Backend `.env`:

```
DATABASE_URL=...
REDIS_URL=...
CLOUD_PROVIDER=...
PRIMARY_MODEL=...           # read from .env — never hardcode
INTENT_MODEL=...
EMBEDDING_MODEL=...
JWT_SECRET_KEY=...
FRONTEND_URL=http://localhost:3022
MULTI_TENANT_ENABLED=false
```

Frontend `.env.local`:

```
NEXT_PUBLIC_API_URL=http://localhost:8022
NEXT_PUBLIC_CLOUD_PROVIDER=...
```

---

## Phase 1 Integration Sequence

1. Backend: run migrations (`alembic upgrade head`)
2. Backend: start with `MULTI_TENANT_ENABLED=false` (single-tenant mode, regression safe)
3. Frontend: verify all existing pages work unchanged
4. Backend: flip `MULTI_TENANT_ENABLED=true` on staging
5. Run tenant isolation test suite — all must pass
6. Frontend: verify platform admin pages appear for platform_admin JWT
7. Run full E2E Playwright suite
8. Phase 1 complete ✓
