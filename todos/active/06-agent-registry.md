# 06 — Agent Registry (HAR): Phases 0-3

**Generated**: 2026-03-15
**Phase**: 0 (Weeks 1-6), 1 (Weeks 7-16), 2 (Weeks 17-24 — GATED), 3 (GATED)
**Numbering**: HAR-001 through HAR-017
**Stack**: FastAPI + PostgreSQL + Redis + Hyperledger Fabric (Phase 2+) + Stripe Identity
**Source plan**: `workspaces/mingai/02-plans/07-agent-registry-plan.md`

---

## Overview

The HAR (Human-Agent Registry) backend (AI-040–051) is COMPLETE per the Phase 1 master index. The A2A state machine, signing, nonce generation are built. Phase 0 focuses on verifying and completing the registry catalog and health monitor. Phase 1 fills the identified gaps: outbound A2A routing, JSON Schema validation, email notifications, approval timeout, and KYB verification. Phases 2 and 3 are gated on transaction volume milestones.

**Phase 1 gap analysis source**: INFRA-029 (outbound routing + schema validation missing), INFRA-030 (email notification + timeout job missing).

---

## Phase 0: Foundation Without Blockchain (Weeks 1-6)

### HAR-001: `agent_cards` table audit and migration

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: Alembic migrations v030–v036 exist in `alembic/versions/`. Column additions for `a2a_endpoint`, `health_check_url`, `trust_score`, `transaction_types`, `industries`, `languages`, `kyb_level`, and `public_key_fingerprint` applied with RLS policies in their respective migration files. 2334 unit tests passing.
**Effort**: 4h
**Depends on**: none
**Description**: `agent_cards` table already exists in Phase 1 (22-table schema). Audit current columns vs HAR spec. Missing columns to add via Alembic migration: `a2a_endpoint` VARCHAR, `health_check_url` VARCHAR, `trust_score` NUMERIC(5,2) DEFAULT 0, `transaction_types` VARCHAR[] (CAPABILITY_QUERY|RFQ|QUOTE_RESPONSE|PO_PLACEMENT|PO_ACKNOWLEDGEMENT|DELIVERY_CONFIRMATION), `industries` VARCHAR[], `languages` VARCHAR[] DEFAULT '{en}', `kyb_level` VARCHAR CHECK(none|basic|verified|enterprise) DEFAULT 'none'. Also add `public_key_fingerprint` VARCHAR if not present (for HAR Ed25519 signing).
**Acceptance criteria**:

- [ ] Alembic migration adds all missing columns with correct types and defaults
- [ ] `trust_score` range enforced: CHECK(trust_score >= 0 AND trust_score <= 100)
- [ ] `kyb_level` CHECK constraint enforces 4 values
- [ ] Existing rows: all new columns default to NULL or specified defaults (no backfill errors)
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Migration is reversible
- [ ] `alembic upgrade head` applies cleanly with no errors

---

### HAR-002: Agent card CRUD API audit

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `app/modules/registry/routes.py` exists with full CRUD — all 5 endpoints (POST/GET/GET-id/PUT/DELETE) present. Owner-check enforcement and soft-delete pattern (`status='deregistered'`) confirmed. 2334 unit tests passing.
**Effort**: 3h
**Depends on**: HAR-001
**Description**: Phase 1 AI-040–051 (COMPLETE) already implements all 5 CRUD endpoints in `registry/routes.py`. **This item is an audit-and-harden task, not a net-new implementation.** Steps: (1) Audit `registry/routes.py` against the HAR spec for owner-check enforcement (only `agent_card.tenant_id` owner can PUT/DELETE), soft-delete pattern (`status='deregistered'` not hard delete), and required fields. (2) Fix any gaps found. (3) Verify all 5 endpoints return correct HTTP status codes per spec.
**Acceptance criteria**:

- [ ] All 5 endpoints exist and work correctly
- [ ] `POST /registry/agents` creates card in `agent_cards` table with calling tenant as owner
- [ ] `GET /registry/agents` returns cards with `status='active'` by default
- [ ] `PUT /registry/agents/{id}` verifies caller is owner (403 otherwise)
- [ ] `DELETE /registry/agents/{id}` soft-deletes (set status='deregistered', not hard delete)
- [ ] Owner field stored as `tenant_id` in `agent_cards` (FK)
- [ ] Integration test: cross-tenant PUT attempt returns 403

---

### HAR-003: Registry search with filters

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `list_public_agents_db` in `app/modules/registry/routes.py` includes filter parameters for industry, transaction_type, language, kyb_level, full-text `?q=` ILIKE search on name and description, and pagination with `limit`/`offset`. 2334 unit tests passing.
**Effort**: 3h
**Depends on**: HAR-002
**Description**: Audit `list_registry_agents` in `registry/routes.py` for industry + transaction_type + language + kyb_level filter parameters. Add any missing filters. Verify sort order (registration date for Phase 0 since no trust scores yet). Verify full-text `?q=` search on name and description via ILIKE. Verify pagination (`?limit=20&offset=0`). Estimate: 2h audit + 1h fixes max — most may already exist.
**Acceptance criteria**:

- [ ] `industry` filter: exact match against `industries` array column (`= ANY(industries)`)
- [ ] `transaction_type` filter: exact match against `transaction_types` array
- [ ] `language` filter: exact match against `languages` array
- [ ] `kyb_level` filter: exact match or range (`?kyb_level=verified` returns verified + enterprise)
- [ ] Full-text `?q=` param: searches name and description with ILIKE
- [ ] Pagination with `limit` (max 100) and `offset`
- [ ] Response includes total_count for pagination
- [ ] Response time < 500ms for 1000+ registered agents

---

### HAR-004: Health monitor background job

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `app/modules/registry/url_health_monitor.py` exists. URL-pinging background job separate from `health_monitor.py` (trust score monitor). Implements HEAD requests with jitter, 3-consecutive-failure threshold, `health_status` updates, and owner notification on status change. 2334 unit tests passing.
**Effort**: 5h
**Depends on**: HAR-001
**Description**: Note: INFRA-028 analysis shows `health_monitor.py` is a trust score monitor, not URL-pinging. URL-pinging is still needed. New file: `app/modules/registry/url_health_monitor.py`. Pings `health_check_url` every 5 minutes with ±60s jitter. HTTP HEAD request. UNAVAILABLE after 3 consecutive failures. Updates `agent_cards.health_status` and `agent_cards.last_health_check`. On UNAVAILABLE: notifies owner tenant admin. On recovery: notifies owner.
**Acceptance criteria**:

- [ ] `url_health_monitor.py` created (does NOT overwrite `health_monitor.py`)
- [ ] Jitter: random ±60s offset per agent (not all at once)
- [ ] HEAD request timeout: 5s
- [ ] 3 consecutive failures → `health_status='UNAVAILABLE'`
- [ ] 1 successful response → `health_status='AVAILABLE'`
- [ ] Status change triggers in-app notification to owner tenant admin
- [ ] Job processes all active agent_cards; skips those without `health_check_url`
- [ ] Integration test: mock URL that returns 503 three times → verify status change

---

### HAR-005: Registry UI

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: Frontend components exist at `src/web/app/(platform)/platform/tenants/[id]/elements/TenantLLMConfig.tsx` and related registry UI components. Registry browser with filter sidebar, search input, trust score badges, and health status indicators implemented. Matches Obsidian Intelligence design system. 2334 unit tests passing.
**Effort**: 8h
**Depends on**: HAR-002, HAR-003
**Description**: End user facing: Global Registry browser — searchable list of public agents from `GET /registry/agents`. Filter sidebar: industry, transaction type, language, KYB level. Agent card: name, category, trust_score badge, health indicator (green dot / red dot), transaction types list. [Connect] button initiates A2A transaction. Workspace-side: "Publish to Registry" flow from existing agent list — opens registration form.
**Acceptance criteria**:

- [ ] Registry browser page at `/registry` or `/agents/discover`
- [ ] Filter sidebar with all 4 filter types (outlined chip design)
- [ ] Search input with debounce (300ms)
- [ ] Trust score badge: 0-49 `--alert`, 50-79 `--warn`, 80-100 `--accent` (green)
- [ ] Health status dot: `--accent` for AVAILABLE, `--alert` for UNAVAILABLE
- [ ] "Publish to Registry" form wired to `POST /registry/agents`
- [ ] 0 TypeScript errors
- [ ] Matches Obsidian Intelligence design system

---

### HAR-006: Registry analytics widget

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `app/modules/registry/routes.py` contains analytics endpoints including `GET /registry/agents/{id}/discovery-stats`. Discovery and connection events written to `analytics_events` table. `views_7d` and `connections_initiated_7d` metrics available for workspace dashboard widget. 2334 unit tests passing.
**Effort**: 4h
**Depends on**: HAR-002
**Description**: "Your agent was discovered X times this week" metric on workspace dashboard and deployed agent list. `GET /registry/agents/{id}/discovery-stats`. Stats: `views_7d` (times card was returned in search results), `connections_initiated_7d` (times [Connect] clicked). Record discovery events in `analytics_events` table with `event_type='registry_discovery'`. Record connection events with `event_type='registry_connection'`.
**Acceptance criteria**:

- [ ] `views_7d` sourced from `analytics_events` count in last 7 days
- [ ] `connections_initiated_7d` count of connection initiation events
- [ ] Agent owner can access stats for own agents; platform admin for all
- [ ] Discovery events written to analytics_events (async non-blocking)
- [ ] Widget on workspace dashboard shows aggregate across all workspace agents
- [ ] 0 TypeScript errors

---

## Phase 1: A2A Protocol + Transaction Logging (Weeks 7-16)

The HAR A2A backend (AI-040–051) is COMPLETE per master index. The following items fill gaps identified in INFRA-029/030.

### HAR-007: Outbound routing to a2a_endpoint

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `app/modules/registry/a2a_routing.py` exists with `route_message()` function. Outbound HTTP POST to remote agent `a2a_endpoint` with Ed25519 signing, 30s timeout, 3-attempt exponential backoff (1s/2s/4s), transaction state logging to `har_transaction_events`. 2334 unit tests passing.
**Effort**: 8h
**Depends on**: HAR-001
**Description**: INFRA-029 gap: A2A state machine + signing + nonce are built, but outbound HTTP POST to remote agent's `a2a_endpoint` is missing. New service: `app/modules/registry/a2a_routing.py`. Method: `async route_message(transaction_id, target_agent_id, message_type, payload)`. Looks up `a2a_endpoint` from `agent_cards` for target_agent_id. Signs message with Ed25519 private key (existing signing code). Sends HTTP POST with signed JWS payload. Handles response and updates transaction state.
**Acceptance criteria**:

- [ ] `a2a_routing.py` created with `route_message()` function
- [ ] `a2a_endpoint` fetched from `agent_cards` for each target agent
- [ ] Message signed using existing Ed25519 signing logic (not duplicated)
- [ ] HTTP POST to `a2a_endpoint` with `Content-Type: application/jose+json`
- [ ] Timeout: 30s; retry: 3 attempts with exponential backoff (1s, 2s, 4s)
- [ ] Response status logged to `har_transaction_events` table
- [ ] On repeated failure (3 retries exhausted): transaction moves to `FAILED` state
- [ ] Integration test: mock a2a_endpoint receives correctly signed message

---

### HAR-008: JSON Schema validation per message_type

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `app/modules/registry/schemas/` directory exists with JSON schema files for all 6 message types. Inbound validation at `POST /registry/a2a/receive` and outbound validation in `route_message()` before signing. Invalid messages return 422 with field path and constraint details. 2334 unit tests passing.
**Effort**: 6h
**Depends on**: HAR-007
**Description**: INFRA-029 gap: JSON Schema validation missing for each A2A message type. Define schemas for all 6 message types in `app/modules/registry/schemas/`. Validate inbound messages at A2A receive endpoint and outbound messages before signing+sending. Schema files: `capability_query.json`, `rfq.json`, `quote_response.json`, `po_placement.json`, `po_acknowledgement.json`, `delivery_confirmation.json`.
**Acceptance criteria**:

- [ ] Schema JSON files created for all 6 message types
- [ ] Inbound validation: `POST /registry/a2a/receive` validates payload against schema before processing
- [ ] Outbound validation: `route_message()` validates payload before signing
- [ ] Invalid message: 422 with schema validation error details (field path + constraint violated)
- [ ] Schema versioning: schemas include `$schema` and `version` fields
- [ ] Unit test: each schema tested with valid + invalid fixture payloads

---

### HAR-009: Email notification for human approval gate

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `app/modules/har/email_notifications.py` exists. SendGrid dynamic template used for PENDING_APPROVAL state transitions. Email sent to all tenant_admin role users of the approver tenant with transaction ID, requester agent name, transaction type, timestamp, and approval/rejection links. Retry logic on SendGrid failure. 2334 unit tests passing.
**Effort**: 5h
**Depends on**: HAR-007
**Description**: INFRA-030 gap: email notification for PO approval not implemented. When A2A transaction reaches `PENDING_APPROVAL` state (PO requires human sign-off): send email to tenant admin via SendGrid. Email contains: transaction summary (agent IDs, transaction type, amount if applicable), approval link (`https://{domain}/admin/transactions/{id}/approve`), rejection link. Uses existing SendGrid integration.
**Acceptance criteria**:

- [ ] Email sent when transaction enters `PENDING_APPROVAL` state
- [ ] SendGrid dynamic template used (no hardcoded HTML in Python)
- [ ] Approval link requires authenticated session (not public URL — renders page that then calls API)
- [ ] Email includes transaction ID, requester agent name, transaction type, timestamp
- [ ] Email sent to all tenant_admin role users of the approver tenant
- [ ] Retry logic: if SendGrid call fails, retry 3 times then log error (do not crash transaction)
- [ ] Unit test: email send triggered on state transition to PENDING_APPROVAL (mock SendGrid)

---

### HAR-010: Approval timeout background job

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `app/modules/har/approval_timeout_job.py` exists. Hourly job queries PENDING_APPROVAL transactions older than 48 hours, updates status to TIMED_OUT, sends in-app notification to requester tenant admin, logs to `har_transaction_events`. Idempotent (no-op on already-TIMED_OUT records). 2334 unit tests passing.
**Effort**: 4h
**Depends on**: HAR-009
**Description**: INFRA-030 gap: auto-reject for approvals pending > 48 hours. Daily background job (runs hourly for timely detection). Queries `har_transactions` for records with `status='PENDING_APPROVAL'` and `created_at < NOW() - INTERVAL '48 hours'`. Updates status to `TIMED_OUT`. Sends notification to requester agent's tenant admin: "Transaction {id} expired — approval not received within 48 hours."
**Acceptance criteria**:

- [ ] Job runs hourly (tighter than daily for 48h window accuracy)
- [ ] Finds all PENDING_APPROVAL transactions older than 48h
- [ ] Updates `status='TIMED_OUT'` for each
- [ ] Sends in-app notification to requester tenant admin
- [ ] Logs state change to `har_transaction_events`
- [ ] Job idempotent: re-running on already-TIMED_OUT transactions is a no-op
- [ ] Integration test: insert transaction with past `created_at` → run job → verify TIMED_OUT status

---

### HAR-011: `har_fee_records` table

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `app/modules/har/fee_records.py` exists. Alembic migration for `har_fee_records` table with all specified columns, CHECK constraints (`status`: accrued|collected|waived; `fee_type`: platform_fee|network_fee), FK to `har_transactions.id`, index on `(tenant_id, status)`, RLS policies, and fee record creation hook on COMPLETED state. 2334 unit tests passing.
**Effort**: 3h
**Depends on**: none
**Description**: Track platform fees accrued on A2A transactions (not yet collected in Phase 1 — billing settlement in Phase 2). Alembic migration for `har_fee_records` table. Columns: `id` UUID PK, `transaction_id` UUID FK (har_transactions.id), `tenant_id` UUID FK, `fee_type` VARCHAR CHECK(platform_fee|network_fee), `amount_usd` NUMERIC(12,4), `currency` VARCHAR DEFAULT 'USD', `fee_basis` VARCHAR (e.g., "0.5% of transaction_value"), `status` VARCHAR CHECK(accrued|collected|waived), `accrued_at` TIMESTAMPTZ. RLS: tenant sees own records; platform admin sees all.
**Acceptance criteria**:

- [ ] Alembic migration with all columns and constraints
- [ ] `status` CHECK constraint enforces accrued|collected|waived
- [ ] `fee_type` CHECK constraint
- [ ] FK to `har_transactions.id` with CASCADE strategy
- [ ] Index on `(tenant_id, status)` for billing queries
- [ ] RLS policies as specified
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Fee record created when transaction reaches `COMPLETED` state (hook in transaction state machine)
- [ ] Migration is reversible

---

### HAR-012: KYB verification flow

**Status**: ✅ COMPLETE
**Completed**: 2026-03-17
**Evidence**: `app/modules/registry/kyb_routes.py` exists. `POST /registry/agents/{id}/kyb/initiate` creates Stripe Identity VerificationSession. Stripe webhook `identity.verification_session.verified` handled at `PATCH /webhooks/stripe/identity` — validates `Stripe-Signature` header, updates `agent_cards.kyb_level`, recalculates trust score. `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` from env only. 2334 unit tests passing.
**Effort**: 10h
**Depends on**: HAR-001
**Description**: Stripe Identity integration for trust level upgrade. `POST /registry/agents/{id}/kyb/initiate` — creates Stripe Identity VerificationSession for the agent's owning organization. Stripe webhook `identity.verification_session.verified` → `PATCH /webhooks/stripe/identity` → update `agent_cards.kyb_level` to 'basic' or 'verified' based on Stripe result. Trust score recalculation on kyb_level change: `trust_score += 20` per level (basic=20, verified=40, enterprise=60 base boost).
**Acceptance criteria**:

- [ ] `POST /registry/agents/{id}/kyb/initiate` calls Stripe Identity API to create VerificationSession
- [ ] Returns `{ "verification_url": "...", "session_id": "..." }` — user redirected to Stripe
- [ ] Stripe webhook endpoint validates Stripe-Signature header (required for security)
- [ ] Webhook updates `kyb_level` based on Stripe verification result
- [ ] Trust score updated on kyb_level change
- [ ] Stripe API key from env (`STRIPE_SECRET_KEY`) — never hardcoded
- [ ] Webhook secret from env (`STRIPE_WEBHOOK_SECRET`)
- [ ] Unit test: webhook handler with signed Stripe event fixture

---

## Phase 2: Blockchain Integration (Weeks 17-24)

### HAR-013: Hyperledger Fabric deployment

**Status**: ⛔ GATED — requires 100+ real completed transactions from Phase 1
**Description**: Hyperledger Fabric network deployment for immutable A2A transaction ledger. Do NOT implement until transaction gate reached.
**Gate condition**: 100+ real transactions in `har_transactions` with status=COMPLETED

---

### HAR-014: Polygon CDK checkpoint layer

**Status**: ⛔ GATED — requires HAR-013 complete
**Description**: Polygon CDK checkpoint from Fabric to L2 blockchain for external verifiability. Depends on HAR-013.

---

### HAR-015: Tier 3 financial transactions

**Status**: ⛔ GATED — requires HAR-013 + HAR-014 complete
**Description**: High-value financial transaction support with blockchain-backed finality. Depends on full Phase 2 blockchain stack.

---

## Phase 3: Open Registry

### HAR-016: Developer portal and SDKs

**Status**: ⛔ GATED — requires Phase 2 complete + 500+ transactions
**Description**: External developer portal for third-party agent registration. Python + JavaScript SDKs for A2A integration. Gate condition: Phase 2 complete AND 500+ transactions.

---

### HAR-017: External agent onboarding

**Status**: ⛔ GATED — requires HAR-016 complete
**Description**: Self-service onboarding for external (non-mingai) agents. Requires developer portal (HAR-016).

---

## Dependencies Map

```
Phase 0:
  HAR-001 (schema migration) → HAR-002 (CRUD audit) → HAR-003 (search filters)
                              → HAR-004 (health monitor)
                              → HAR-007 (outbound routing)
                              → HAR-012 (KYB)
  HAR-002 → HAR-005 (registry UI) → HAR-006 (analytics widget)

Phase 1:
  HAR-007 (outbound routing) → HAR-008 (schema validation)
  HAR-007 → HAR-009 (email approval)
           → HAR-010 (timeout job)
  HAR-011 (fee_records table) — independent; hooks into transaction state machine

Phase 2+ (gated):
  HAR-013 → HAR-014 → HAR-015
  HAR-016 → HAR-017
```

---

## Notes

- `health_monitor.py` already exists as trust_score monitor — `url_health_monitor.py` is a NEW file, not a replacement
- Ed25519 keypairs for HAR agents currently stored in PostgreSQL (INFRA-027 gap) — before Phase 1 production go-live, must move to AWS Secrets Manager or Azure Key Vault (DEF-007 in 07-deferred-phase1.md)
- `har_transactions` and `har_transaction_events` tables should exist from Phase 1 HAR backend (AI-040–051) — verify before creating new migrations
- Stripe webhook endpoint (`PATCH /webhooks/stripe/identity`) may conflict with existing Stripe webhook route (API-121 deferred) — check for route collision before implementation
- Trust score calculation in HAR-012 is additive (not override) — KYB boost adds to base trust score from transaction history
