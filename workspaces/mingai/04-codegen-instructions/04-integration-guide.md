# 04 — Integration Guide: Backend ↔ Frontend

---

## Environment Configuration

Backend `.env`:

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/mingai
REDIS_URL=redis://localhost:6379/0
CLOUD_PROVIDER=local

# AI Models — from .env ONLY, never hardcode
PRIMARY_MODEL=gpt-5.2-chat
INTENT_MODEL=gpt-5-mini
EMBEDDING_MODEL=text-embedding-3-large

# Auth
JWT_SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
JWT_ALGORITHM=HS256

# Auth0 (Phase 2)
AUTH0_DOMAIN=
AUTH0_AUDIENCE=
AUTH0_MANAGEMENT_CLIENT_ID=
AUTH0_MANAGEMENT_CLIENT_SECRET=

# Platform
FRONTEND_URL=http://localhost:3022
MULTI_TENANT_ENABLED=true

# Optional (Phase 2+)
STRIPE_WEBHOOK_SECRET=
SENTRY_DSN=
```

Frontend `.env.local`:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8022
NEXT_PUBLIC_CLOUD_PROVIDER=local

# Auth0 (Phase 2)
AUTH0_DOMAIN=
AUTH0_CLIENT_ID=
AUTH0_CLIENT_SECRET=
AUTH0_AUDIENCE=
AUTH0_BASE_URL=http://localhost:3022
```

---

## Full API Contract

### Authentication (API-001 to API-010)

```
POST   /api/v1/auth/local/login          → {access_token, token_type, expires_in}
POST   /api/v1/auth/token/refresh        → {access_token, token_type, expires_in}
POST   /api/v1/auth/logout               → 204 No Content
GET    /api/v1/auth/current              → {id, email, name, tenant_id, roles, plan, scope}
GET    /api/v1/auth/auth0/callback       → Auth0 OAuth2 callback (Phase 2)
```

JWT payload shape:

```json
{
  "sub": "user-uuid",
  "tenant_id": "tenant-uuid",
  "roles": ["tenant_admin", "user"],
  "scope": "tenant",
  "plan": "professional",
  "exp": 1234567890
}
```

### Chat (API-011 to API-020)

```
POST   /api/v1/chat/stream               → SSE stream (see SSE Protocol below)
GET    /api/v1/conversations             → paginated list {items, total, page, limit}
POST   /api/v1/conversations             → {id, title, agent_id, created_at}
GET    /api/v1/conversations/{id}        → conversation detail
DELETE /api/v1/conversations/{id}        → 204 No Content
GET    /api/v1/conversations/{id}/messages → {items, total}
POST   /api/v1/feedback                  → thumbs up/down: {message_id, value: 1|-1, comment?}
```

### Memory + Profile (API-021 to API-035)

```
GET    /api/v1/me/profile                → user profile + memory notes
PATCH  /api/v1/me/profile                → update profile settings
GET    /api/v1/me/memory                 → memory notes list
DELETE /api/v1/me/memory/{note_id}       → delete single note
DELETE /api/v1/me/memory                 → clear all notes (GDPR)
DELETE /api/v1/me/profile/data           → GDPR erasure (all 3 stores)
GET    /api/v1/me/profile/export         → GDPR export (JSON)
PATCH  /api/v1/me/profile/privacy        → update privacy settings
```

### Users — Tenant Admin (API-036 to API-050)

```
GET    /api/v1/users                     → paginated user directory (tenant-scoped)
POST   /api/v1/users/invite              → invite user(s): {email} or {emails: string[]}
PATCH  /api/v1/users/{id}/role           → {role: "tenant_admin"|"user"}
PATCH  /api/v1/users/{id}/status         → {status: "active"|"suspended"}
DELETE /api/v1/users/{id}               → anonymize (not hard delete)
```

### Teams (API-051 to API-065)

```
GET    /api/v1/teams                     → list teams
POST   /api/v1/teams                     → create team
GET    /api/v1/teams/{id}                → team detail + members
PUT    /api/v1/teams/{id}                → update team
DELETE /api/v1/teams/{id}               → archive team
GET    /api/v1/teams/{id}/members        → member list
POST   /api/v1/teams/{id}/members        → add member(s)
DELETE /api/v1/teams/{id}/members/{uid}  → remove member
GET    /api/v1/teams/{id}/audit-log      → membership audit trail
PATCH  /api/v1/admin/teams/sync-settings → Auth0 group sync config (allowlist)
```

### Knowledge Base + Integrations (API-066 to API-080)

```
GET    /api/v1/integrations/sharepoint/status   → connection status
POST   /api/v1/integrations/sharepoint/connect  → save credentials + test
POST   /api/v1/integrations/sharepoint/sync     → trigger sync
GET    /api/v1/integrations/googledrive/status  → connection status
POST   /api/v1/integrations/googledrive/auth    → OAuth2 flow initiation
GET    /api/v1/integrations/googledrive/callback → OAuth2 callback
POST   /api/v1/sync/trigger                     → manual sync (any source)
GET    /api/v1/sync/status                      → sync status + failures
```

### Glossary (API-081 to API-090)

```
GET    /api/v1/glossary                  → all terms (tenant-scoped, cached)
POST   /api/v1/glossary                  → create term
PUT    /api/v1/glossary/{id}             → update term
DELETE /api/v1/glossary/{id}            → delete term
POST   /api/v1/glossary/import          → CSV import (multipart/form-data)
GET    /api/v1/glossary/export          → CSV export
```

### Platform Admin (API-091 to API-110)

```
GET    /api/v1/admin/tenants                    → paginated tenant list
POST   /api/v1/admin/tenants                    → provision tenant (async → job_id)
GET    /api/v1/admin/tenants/{id}               → tenant detail
PATCH  /api/v1/admin/tenants/{id}/status        → suspend/activate
GET    /api/v1/admin/tenants/{id}/quota         → quota usage
PATCH  /api/v1/admin/tenants/{id}/quota         → update limits
GET    /api/v1/admin/provisioning/{job_id}      → SSE provisioning status
GET    /api/v1/admin/llm-profiles               → list LLM profiles
POST   /api/v1/admin/llm-profiles               → create profile
PUT    /api/v1/admin/llm-profiles/{id}          → update profile
DELETE /api/v1/admin/llm-profiles/{id}         → delete profile
GET    /api/v1/admin/cost-analytics             → cross-tenant token costs
GET    /api/v1/admin/issue-queue                → platform issue queue
PATCH  /api/v1/admin/issues/{id}/status         → escalate/resolve
```

### Memory Policy — Tenant Admin (API-111 to API-115)

```
GET    /api/v1/admin/memory-policy       → get tenant memory settings
PATCH  /api/v1/admin/memory-policy       → update settings
```

### Webhooks (API-121 to API-125)

```
POST   /api/v1/webhooks/stripe           → Stripe events (API-121)
POST   /api/v1/webhooks/auth0            → Auth0 events (group sync)
```

### HAR — Hosted Agent Registry (API-116 to API-120, Phase 2)

```
GET    /api/v1/registry/agents           → discover agents (public registry)
POST   /api/v1/registry/agents           → publish agent
GET    /api/v1/registry/agents/{id}      → agent detail + audit trail
POST   /api/v1/registry/agents/{id}/transactions  → initiate transaction
GET    /api/v1/registry/transactions     → tenant's transaction history
POST   /api/v1/registry/transactions/{id}/dispute → raise dispute (API-124)
PATCH  /api/v1/registry/transactions/{id}/dispute/{did}/resolve → resolve (API-125)
```

---

## Error Response Format

All errors use this shape:

```json
{
  "error": "snake_case_error_code",
  "message": "Human-readable description",
  "request_id": "req_abc123"
}
```

HTTP status codes:

| Status | Meaning                                   |
| ------ | ----------------------------------------- |
| 400    | Validation error                          |
| 401    | Not authenticated                         |
| 403    | Not authorized (wrong role/scope)         |
| 404    | Resource not found                        |
| 422    | Unprocessable entity (invalid body shape) |
| 429    | Rate limit exceeded                       |
| 500    | Internal server error                     |

---

## SSE Chat Protocol

The chat stream endpoint returns Server-Sent Events. Frontend MUST handle all event types:

```
event: status
data: {"stage": "searching", "message": "Searching knowledge base..."}

event: status
data: {"stage": "building_context", "message": "Building your response..."}

event: sources
data: {"sources": [{"title": "HR Policy v3", "score": 0.91, "url": "...", "excerpt": "..."}]}

event: response_chunk
data: {"text": "Based on the annual leave policy,"}

event: response_chunk
data: {"text": " you are entitled to 14 days per year."}

event: metadata
data: {
  "retrieval_confidence": 0.87,
  "tokens_used": 1240,
  "model": "from .env — never hardcoded",
  "glossary_expansions": ["AL → Annual Leave", "HR → Human Resources"],
  "profile_context_used": true,
  "layers_active": ["org_context", "profile", "working_memory"]
}

event: memory_saved
data: {"note_id": "uuid", "content": "User prefers concise answers"}

event: profile_context_used
data: {"layers_active": ["org_context", "profile", "working_memory"]}

event: done
data: {"conversation_id": "uuid", "message_id": "uuid"}

event: error
data: {"code": "llm_timeout", "message": "Response generation timed out"}
```

**Critical label**: `retrieval_confidence` must be labeled "retrieval confidence" in UI — NOT "AI confidence" or "answer quality".

**Glossary expansions**: Non-empty list → show `GlossaryExpansionIndicator` (mandatory).

---

## Paginated Response Format

All list endpoints follow this shape:

```json
{
  "items": [...],
  "total": 247,
  "page": 1,
  "limit": 25,
  "total_pages": 10
}
```

---

## Auth0 Integration (Phase 2)

### JWT Validation Flow

```
Request → Extract Bearer token → Decode header (kid) → Fetch JWKS from Auth0
       → Find matching key → Verify signature → Extract claims → Set tenant context
```

Claims mapping from Auth0 to mingai:

```json
{
  "sub": "auth0|...",
  "https://mingai.io/tenant_id": "tenant-uuid",
  "https://mingai.io/roles": ["tenant_admin"],
  "https://mingai.io/scope": "tenant",
  "https://mingai.io/plan": "professional"
}
```

### Auth0 Group Sync on Login

When user logs in with Auth0 JWT containing `groups` claim:

1. Read `tenant_settings.auth0_group_allowlist` for current tenant
2. If allowlist is empty → skip (default behavior: no auto-sync)
3. For each group in `groups` claim that matches allowlist pattern:
   - Find or create `tenant_teams` record with `source=auth0_sync`
   - Sync membership: add user if not member, remove from auth0_sync teams if no longer in group
   - NEVER overwrite `manual` source records
4. Write to `team_membership_audit` with `source=auth0_sync`

### OrgContext from Auth0 (Auth0OrgContextSource)

```python
class Auth0OrgContextSource(OrgContextSource):
    async def get_org_context(self, user_id: str, auth0_profile: dict) -> OrgContextData:
        # Extract from Auth0 user profile (fetched from Management API at login)
        # Map per tenant's configured field mapping
        return OrgContextData(
            job_title=auth0_profile.get(tenant_config.job_title_field),
            department=auth0_profile.get(tenant_config.department_field),
            company=auth0_profile.get(tenant_config.company_field, tenant.name),
            country=auth0_profile.get(tenant_config.country_field),
            manager_name=auth0_profile.get(tenant_config.manager_field) if user.share_manager_info else None
        )
```

---

## Tenant Isolation Verification (Gate: Must Pass)

```python
# tests/integration/test_tenant_isolation.py

def test_cross_tenant_data_isolation(tenant_a_client, tenant_b_client, db):
    """Tenant B cannot access Tenant A's conversations."""
    conv = tenant_a_client.post("/api/v1/conversations", json={"title": "test"})
    conv_id = conv.json()["id"]
    response = tenant_b_client.get(f"/api/v1/conversations/{conv_id}")
    assert response.status_code == 404

def test_rls_prevents_direct_query_across_tenants(db, tenant_a_id, tenant_b_id):
    """RLS returns zero rows for tenant A's data when context is tenant B."""
    with db.set_tenant(tenant_b_id):
        rows = db.execute("SELECT * FROM conversations").fetchall()
        tenant_a_rows = [r for r in rows if r["tenant_id"] == str(tenant_a_id)]
        assert len(tenant_a_rows) == 0

def test_redis_keys_isolated_by_tenant(redis_client, tenant_a_id, tenant_b_id):
    """Redis keys include tenant_id prefix and are not accessible cross-tenant."""
    redis_client.set(f"mingai:{tenant_a_id}:working_memory:user1:agent1", "data")
    # Tenant B should not be able to read tenant A's key via any API
    tenant_b_response = tenant_b_client.get(f"/api/v1/me/working-memory")
    assert tenant_b_response.json()["topics"] != ["data"]

def test_memory_note_200_char_limit(tenant_a_client):
    """Memory note content must be rejected if > 200 chars."""
    long_note = "x" * 201
    resp = tenant_a_client.post("/api/v1/me/memory", json={"content": long_note})
    assert resp.status_code == 422

def test_gdpr_erasure_clears_working_memory(tenant_a_client, redis_client, tenant_a_id):
    """Working memory MUST be cleared on GDPR erasure (aihub2 bug fix)."""
    # Simulate working memory in Redis
    redis_client.set(f"mingai:{tenant_a_id}:working_memory:user1:agent1", "topics")
    # Trigger erasure
    tenant_a_client.delete("/api/v1/me/profile/data")
    # Verify cleared
    key = f"mingai:{tenant_a_id}:working_memory:user1:*"
    assert len(list(redis_client.scan_iter(key))) == 0
```

---

## Integration Test Sequence (Pre-Deployment Gate)

Run in this order before any deployment:

```bash
# 1. Migrate
alembic upgrade head

# 2. CORS test
curl -H "Origin: http://evil.com" http://localhost:8022/api/v1/auth/current
# Must return 403 or missing CORS headers (not 200 with wildcard)

# 3. Tenant isolation
pytest tests/integration/test_tenant_isolation.py -v

# 4. GDPR erasure
pytest tests/integration/test_gdpr.py -v

# 5. Memory note limit
pytest tests/integration/test_memory_notes.py::test_200_char_limit -v

# 6. Rate limiting
pytest tests/integration/test_rate_limiting.py -v

# 7. Full E2E
npx playwright test --reporter=html
```

All 7 must pass. Any failure = do not deploy.
