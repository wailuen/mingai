# Architecture — mingai Backend

Decisions recorded here reflect what is in the code. Changing any of these requires updating both the implementation and this document.

---

## Multi-Tenancy via Row-Level Security

Every user-owned table carries a `tenant_id UUID NOT NULL` column. PostgreSQL Row-Level Security policies enforce that a session can only read and write rows where `tenant_id` matches the session variable `app.current_tenant_id`.

How it works at runtime:

1. `get_current_user` dependency extracts `tenant_id` from the JWT claim.
2. Before any query, the route calls `get_set_tenant_sql(tenant_id)` which returns `(sql, params)`.
3. The route executes `text(sql), params` to set `SET LOCAL app.current_tenant_id = '<uuid>'`.
4. All subsequent queries in that session are automatically filtered by the RLS policy.

Critical constraints:

- The application DB user must be `NOSUPERUSER`. Superusers bypass RLS.
- `get_set_tenant_sql()` returns a tuple — never pass it directly to `text()`.
- `validate_tenant_id()` rejects non-UUID strings before the SET executes.
- Tables with special RLS (e.g. `tenants` self-references `id`; `team_memberships` joins through `tenant_teams`) are listed in `SPECIAL_RLS_TABLES` in `core/database.py`.

RLS-scoped tables (as of Phase 1): users, conversations, messages, user_feedback, user_profiles, memory_notes, profile_learning_events, working_memory_snapshots, tenant_configs, llm_profiles, tenant_teams, team_memberships, glossary_terms, integrations, sync_jobs, issue_reports, issue_events, agent_cards, audit_log, har_transactions, har_transaction_events.

---

## JWT v2 Token Structure

Phase 1 issues local HS256 JWTs. Phase 2 will validate against Auth0 JWKS — the `decode_jwt_token` / `decode_jwt_token_v1_compat` split in `modules/auth/jwt.py` anticipates this.

JWT v2 payload:

```json
{
  "sub": "<user_id>",
  "tenant_id": "<uuid>",
  "roles": ["end_user"],
  "scope": "tenant",
  "plan": "professional",
  "email": "user@example.com",
  "exp": 1234567890,
  "iat": 1234567890,
  "token_version": 2
}
```

Roles and their access:

| Role | Scope | Can access |
|---|---|---|
| `end_user` | `tenant` | Chat, memory, own issues, own profile |
| `tenant_admin` | `tenant` | All above + user mgmt, glossary, workspace, all issues |
| `platform_admin` | `platform` | All above + tenant mgmt, LLM profiles, platform stats |

FastAPI dependencies for enforcement:

- `get_current_user` — any authenticated user
- `require_tenant_admin` — raises 403 if `tenant_admin` not in roles
- `require_platform_admin` — raises 403 if scope is not `platform`

v1 backward compat: `decode_jwt_token_v1_compat` accepts tokens without `token_version` claim (treats them as v1 with `scope="tenant"`).

---

## Cloud-Agnostic Storage

`CLOUD_PROVIDER` env var selects the storage backend for screenshot uploads. The selection happens at call time inside `core/storage.py`.

| Value | Backend | Notes |
|---|---|---|
| `aws` | S3 presigned PUT | Requires `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET` |
| `azure` | Azure Blob SAS URL | Requires `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_STORAGE_CONTAINER` |
| `gcp` | GCS signed URL | Requires `GCP_SERVICE_ACCOUNT_JSON`, `GCP_STORAGE_BUCKET` |
| `local` | HMAC-signed internal endpoint | Dev/test only. No cloud credentials needed. |

Storage path pattern: `screenshots/{tenant_id}/{uuid}/{sanitized_filename}`

All providers return the same `PresignedUpload` dataclass: `{ upload_url, blob_url, expires_in=300 }`.

The client PUTs directly to `upload_url`. The resulting permanent reference is `blob_url`. Allowed content types: `image/png`, `image/jpeg`.

Blur gate: `screenshot_url` is only accepted in issue create if `blur_acknowledged=True`. This check is in the route handler, not the DB helper, and must not be moved.

---

## Caching Strategy

Redis is used for three purposes:

**1. Glossary terms cache**

Key: `mingai:{tenant_id}:glossary_terms`

`GlossaryExpander` loads all terms from this key on each `expand()` call. Any write to the glossary (create, update, delete, bulk import) calls `_invalidate_glossary_cache(tenant_id)` which deletes the key. Next expand() call refills from DB. Cache misses are safe — fallback to DB query.

**2. Working memory (per user/agent)**

Key: `mingai:{tenant_id}:working_memory:{user_id}:{agent_id}`

`WorkingMemoryService` stores a JSON summary of recent query topics. Cleared on GDPR erasure and on explicit `DELETE /memory/working`.

**3. Team working memory**

Key: `mingai:{tenant_id}:team_memory:{team_id}`

`TeamWorkingMemoryService` stores anonymized team query topics. `user_id` is NEVER written here — only the string `"a team member asked: <truncated>"`. GDPR-isolated from individual user data.

**4. Notification delivery (per-user Pub/Sub)**

Channel: `mingai:{tenant_id}:notifications:{user_id}`

`publish_notification()` in `modules/notifications/publisher.py` writes to this channel. The SSE route subscribes and streams events to the connected client. When the client disconnects, the subscription is released in a `finally` block. This is ephemeral — no persistence; missed messages while the client is offline are not replayed.

**Redis key namespace convention**: `mingai:{tenant_id}:{service}:{id...}`

**CacheService / @cached decorator**: Available in `core/cache.py` for route-level caching. Not currently used on hot paths — added for future optimization.

---

## Screenshot Blur Pipeline

INFRA-019. Controlled by `modules/issues/blur_service.py`.

Flow:
1. Client requests presigned URL (`GET /issue-reports/presign`).
2. Client uploads screenshot directly to storage.
3. Client presents the `blob_url` and sets `blur_acknowledged=True` in the issue create request.
4. Route enforces the blur gate — rejects if `blur_acknowledged=False` when `screenshot_url` is present.
5. `ScreenshotBlurService` applies PIL Gaussian blur to the stored image (background task — Phase 1 inline, Phase 2 async worker).

The blur acknowledgement is a user-consent signal, not a guarantee of blur completion at submission time. The service processes asynchronously.

---

## Async Issue Triage Pipeline (Redis Streams)

INFRA-017/018. Issue reports flow through a Redis Stream for async triage by `IssueTriageAgent`.

**Producer** (`modules/issues/stream.py`):

- `publish_issue_to_stream(report_id, tenant_id, issue_type, severity_hint, redis)` — XADD to `issue_reports:incoming`, MAXLEN ~10,000.
- Called from the issue create route after DB commit.

**Consumer** (`modules/issues/worker.py`):

- `run_triage_worker(worker_id)` — XREADGROUP loop, consumer group `issue_triage_workers`, 5s blocking read, 10 messages per batch.
- `process_message(msg_id, fields, db_session, redis)` — calls IssueTriageAgent with 3-retry exponential backoff. XACK on success, NACK on permanent failure.
- `reclaim_abandoned_messages(consumer_id, redis, db_session)` — XCLAIM for messages idle >5 min from dead consumers.

Worker startup calls `ensure_stream_group(redis)` once (idempotent XGROUP CREATE MKSTREAM). The group must exist before any XREADGROUP call.

Design constraints:
- `STREAM_MAX_LEN = 10_000` keeps memory bounded (approximate trimming).
- Consumer group name is a module constant — never construct it dynamically.
- Workers are stateless; multiple instances share the same consumer group for horizontal scaling.

---

## GitHub Webhook Integration

`POST /webhooks/github` receives GitHub events and updates `issue_reports` status to track the fix lifecycle. HMAC-SHA256 signature validation is mandatory — the endpoint returns 503 (not 401) when `GITHUB_WEBHOOK_SECRET` is unset (fail-closed).

Event → status transitions update the linked `issue_reports` row. The mapping is a static dict in the route handler. Unrecognized events are acknowledged (200) without DB writes.

---

## Health Score Formula

`GET /platform/tenants/{id}/health` returns a composite score (0–100) computed from 4 components, each queried live from PostgreSQL over the past 30–60 days.

| Component | Weight | Source |
|---|---|---|
| Usage trend | 30% | Recent vs prior 30-day query volume |
| Feature breadth | 20% | Fraction of 5 core features active |
| Satisfaction | 35% | Positive feedback percentage |
| Error rate | 15% | Open issues count (capped at 10 = 100%) |

Categories: `healthy` (≥70), `warning` (50–69), `critical` (<50). `at_risk` flag is true for warning or critical.

---

## Database Migrations

Tool: Alembic. Config: `src/backend/alembic.ini`.

```bash
cd src/backend
alembic upgrade head   # apply all migrations
alembic revision --autogenerate -m "description"  # generate new migration
```

6 migrations applied as of Phase 1. Migration files: `alembic/versions/`.

---

## Structlog JSON Logging

All modules use `structlog.get_logger()`. Output is structured JSON in production, human-readable in dev (`DEBUG=true`).

Log invariants:
- Never log passwords, tokens, or API keys.
- Never log `user_id` in team memory context.
- All log events use snake_case event names: `user_login`, `issue_created`, `tenant_suspended`.

---

## Route Registration Order

FastAPI matches routes in registration order. Specific path segments must always be registered before parameterized segments:

```python
# Correct
@router.patch("/issues/{id}/status")   # specific sub-path first
@router.get("/issues/{id}")            # parameterized last

# Also correct
@router.get("/users/me")               # /me before /{id}
@router.get("/users/{id}")
```

This applies in: issues, users, teams, glossary (`/import` before `/{id}`), documents.

---

## HAR A2A Protocol — Agent-to-Agent Transactions

HAR (Human-Augmented Reasoning, Agent-to-Agent) enables cryptographically-signed transactions between agents with a human approval gate for high-value commitments.

### Key Components

| Component | File | Responsibility |
|-----------|------|----------------|
| Keypair generation | `har/crypto.py` | Ed25519 keypair per agent, Fernet-encrypted private key at rest |
| Signed events | `har/signing.py` | Create/verify signed events; nonce replay protection; hash chain |
| State machine | `har/state_machine.py` | Strict state transitions; unsigned events for human actions |
| API routes | `har/routes.py` | CRUD + transition + approve/reject |
| Trust scoring | `har/trust.py` | KYB points + completed transactions − disputed penalty |
| Health monitor | `har/health_monitor.py` | Background asyncio task, hourly recomputation |

### Cryptographic Chain

1. **Keypair**: `generate_agent_keypair()` → Ed25519 via `cryptography` library. Private key seed encrypted with Fernet (key derived from `JWT_SECRET_KEY` via PBKDF2HMAC, 200k iterations).

2. **Signing**: Each event gets a `nonce` (64 hex chars), a canonical JSON payload (sorted keys), Ed25519 signature, and `event_hash = SHA256(canonical_bytes + signature)`.

3. **Chain**: Each event's `prev_event_hash` must equal the previous event's `event_hash`. `verify_event_chain()` validates the full chain. `har_transactions.chain_head_hash` tracks the latest hash.

4. **Nonce replay**: Redis SETNX with key `{tenant_id}:nonce:{nonce}` and TTL=600s. Duplicate nonce → rejected.

### State Machine

```
DRAFT → OPEN → NEGOTIATING → COMMITTED → EXECUTING → COMPLETED
                     ↓            ↓           ↓
                 ABANDONED    ABANDONED   DISPUTED → RESOLVED
```

All transitions validated against `VALID_TRANSITIONS` dict. Invalid transitions raise HTTP 400.

### Human Approval Gate

Transactions with `amount ≥ 5000.0` set `requires_human_approval=true` and `approval_deadline = NOW() + 48h`. The COMMITTED state is only reachable via `POST /har/transactions/{id}/approve` for these transactions.

### Trust Score

```
score = max(0, min(100, kyb_pts + min(30, completed_count) - min(30, disputed_count × 10)))
kyb_pts: {0→0, 1→15, 2→30, 3→40}
```

`AgentHealthMonitor` runs every 3600s via `asyncio.create_task()` at startup, recomputing scores for all published agents.

### RLS Tables Added

`har_transactions` and `har_transaction_events` both have:
- `tenant_isolation` policy: `tenant_id = current_setting('app.current_tenant_id')::uuid`
- `platform_admin_bypass` policy: `current_setting('app.scope', true) = 'platform'`
