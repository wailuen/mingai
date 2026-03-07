# Red Team Gap Analysis — mingai Todo Files

**Analyst**: deep-analyst (adversarial review)
**Date**: 2026-03-07
**Files reviewed**: 01-database-schema.md through 06-infrastructure.md (398 todos, ~1,594h)
**Gaps found**: 62 (7 CRITICAL, 18 HIGH, 24 MEDIUM, 13 LOW)
**Estimated remediation**: ~400h additional (total ~1,994h)

---

## Executive Summary

After adversarial review of all 6 active todo files, **62 gaps** were found across 10 analysis areas. The most dangerous cluster is in AI/ML Pipeline (4 CRITICAL/HIGH missing core services: chat orchestrator, embedding service, vector search service, confidence calculator). The second most dangerous is Security & Compliance (CORS missing = day-1 showstopper, AML screening absent for financial transactions). Third is Operational Readiness (zero runbooks, zero backup strategy, zero alerting rules).

---

## Area 1: Security & Compliance

### GAP-001: No CORS configuration todo

**Severity**: CRITICAL
**Affected files**: 02-api-endpoints.md, 06-infrastructure.md
**Plan reference**: Plan 01 (Foundation)
**Description**: Zero mention of CORS configuration. Frontend runs on port 3022, backend on 8022. Cross-origin requests will be blocked by every modern browser without explicit CORS middleware. Day-one showstopper.
**Missing todo**: FastAPI CORS middleware: allowed origins from `ALLOWED_ORIGINS` env var, allowed methods, Authorization header, credentials handling. SSE must not require preflight (EventSource uses GET).
**Suggested resolution**: Add `INFRA-051: CORS middleware configuration` to 06-infrastructure.md.

### GAP-002: No security headers middleware (CSP, HSTS, X-Frame-Options)

**Severity**: HIGH
**Affected files**: 02-api-endpoints.md, 06-infrastructure.md, 04-frontend.md
**Plan reference**: All plans
**Description**: No HTTP security headers: Content-Security-Policy, Strict-Transport-Security, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy. Enterprise customers will flag this in security assessments.
**Missing todo**: Security headers middleware for backend (FastAPI) and frontend (Next.js `next.config.js` headers). CSP must allow SSE connections, Recharts inline styles, Google Font loading.
**Suggested resolution**: Add `INFRA-052: HTTP security headers middleware`.

### GAP-003: No XSS protection for user-generated content in frontend

**Severity**: HIGH
**Affected files**: 04-frontend.md
**Plan reference**: Plan 04 (Issue Reporting), Plan 08 (Profile & Memory)
**Description**: Frontend renders user-generated content (memory notes, chat messages, glossary definitions, agent descriptions) with no output encoding or sanitization todo. React prevents most XSS but not all.
**Missing todo**: Install DOMPurify, create `SafeHTML` component. Policy: all user content rendered via `textContent` or sanitized before any `innerHTML`.
**Suggested resolution**: Add `FE-062: Install DOMPurify and create SafeHTML component`.

### GAP-004: No AML/sanctions screening for HAR financial transactions

**Severity**: CRITICAL
**Affected files**: 02-api-endpoints.md, 03-ai-services.md, 05-testing.md
**Plan reference**: Plan 07 (HAR)
**Description**: HAR supports Tier 3 financial transactions with $5,000+ human approval threshold. No mention of AML screening, sanctions list checking (OFAC, EU, UN), or Suspicious Activity Reports. Any platform facilitating financial transactions has regulatory obligations.
**Missing todo**: AML/sanctions screening service for Tier 3 transaction parties. Third-party compliance API integration (Dow Jones/Refinitiv/ComplyAdvantage). Gated on Phase 2.
**Suggested resolution**: Add `AI-052: AML/sanctions screening for HAR Tier 3` to 03-ai-services.md (Phase 2 gate).

### GAP-005: No Stripe webhook handler

**Severity**: HIGH
**Affected files**: 02-api-endpoints.md, 06-infrastructure.md
**Plan reference**: Plan 05 (Platform Admin), Plan 07 (HAR)
**Description**: DB-045 creates billing tables (invoices, line_items, payments) and INFRA-020 creates a Stripe customer on provisioning. But no webhook endpoint for Stripe payment events (payment_intent.succeeded, invoice.paid, subscription.updated, charge.failed). Billing tables will remain empty.
**Missing todo**: `API-121: Stripe webhook handler` at `POST /api/v1/webhooks/stripe` with signature verification, idempotency handling, internal status mapping.
**Suggested resolution**: Add to 02-api-endpoints.md Webhooks section.

### GAP-006: No rate limiting implementation todo

**Severity**: HIGH
**Affected files**: 02-api-endpoints.md, 06-infrastructure.md
**Plan reference**: Plan 01 (Foundation), Plan 04 (Issue Reporting)
**Description**: Multiple endpoints reference rate limits and 429 responses, `rate_limit_rpm` field exists in tenant_configs. But no infrastructure todo implements the actual rate limiting middleware. The field exists but nothing reads it at runtime.
**Missing todo**: `INFRA-053: Rate limiting middleware` using Redis sliding window. Read `rate_limit_rpm` from tenant config, enforce per-user and per-tenant limits, return 429 with `Retry-After` header.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-007: No GDPR data export format specification

**Severity**: MEDIUM
**Affected files**: 02-api-endpoints.md, 04-frontend.md
**Plan reference**: Plan 08 (Profile & Memory)
**Description**: API-115 and FE-020 reference data export but no todo specifies format, included data categories, size limits. GDPR Article 20 requires machine-readable format.
**Missing todo**: Export format: ZIP containing profile.json, conversations.json, memory_notes.json, feedback.json. Async generation for exports >10MB.
**Suggested resolution**: Add acceptance criteria to API-115.

### GAP-008: No consent record for team working memory data sharing

**Severity**: MEDIUM
**Affected files**: 03-ai-services.md, 01-database-schema.md
**Plan reference**: Plan 08 (Profile & Memory), Plan 10 (Teams)
**Description**: Team working memory aggregates anonymized query patterns from all team members and injects them into every member's system prompt — implicit data sharing not disclosed in privacy settings.
**Missing todo**: Disclosure in PrivacyDisclosureDialog about team working memory. Opt-out mechanism (user's queries not contributed to team bucket; still receives team context).
**Suggested resolution**: Add acceptance criteria to FE-016 and AI-013.

---

## Area 2: API Contracts & Integration

### GAP-009: No standard error response format todo

**Severity**: HIGH
**Affected files**: 02-api-endpoints.md, 06-infrastructure.md
**Plan reference**: Plan 01 (Foundation)
**Description**: TEST-072 references error format `{error, message, request_id}` but no backend todo implements the global exception handler. FastAPI default errors don't include request_id.
**Missing todo**: `API-122: Global error handler middleware` returning `{"error": "code", "message": "human-readable", "request_id": "uuid", "details": {}}`. Must handle: Pydantic 422 (field-specific), HTTPException, unhandled 500.
**Suggested resolution**: Add to 02-api-endpoints.md Foundation section.

### GAP-010: No API versioning strategy

**Severity**: MEDIUM
**Affected files**: 02-api-endpoints.md
**Plan reference**: All plans
**Description**: `/api/v1/` prefix exists but no strategy for v2 introduction, v1 sunset, or breaking change policy.
**Missing todo**: Document versioning policy: URL path versioning, minimum 6-month deprecation window, sunset headers, changelog automation.
**Suggested resolution**: Add as header note in 02-api-endpoints.md.

### GAP-011: No SSE Last-Event-ID resume support

**Severity**: MEDIUM
**Affected files**: 02-api-endpoints.md, 04-frontend.md
**Plan reference**: Plan 01 (Foundation)
**Description**: API-012 mentions auto-reconnect but no `Last-Event-ID` implementation. If connection drops mid-stream, client cannot request missed events.
**Missing todo**: Acceptance criteria on API-007 and API-012: monotonic event IDs, buffer last 100 events in Redis (5-min TTL), replay on reconnect with Last-Event-ID header.
**Suggested resolution**: Add acceptance criteria to API-007 and API-012.

### GAP-012: No OpenAPI schema generation todo

**Severity**: MEDIUM
**Affected files**: 02-api-endpoints.md
**Plan reference**: Plan 01 (Foundation)
**Description**: FastAPI auto-generates OpenAPI but no todo ensures schema is correct, customized, or CI-validated.
**Missing todo**: `API-123: OpenAPI schema configuration` with custom title, grouped tags, example values, CI snapshot diff to detect breaking changes.
**Suggested resolution**: Add to 02-api-endpoints.md.

### GAP-013: No pagination consistency enforcement

**Severity**: LOW
**Affected files**: 02-api-endpoints.md
**Plan reference**: All plans with list endpoints
**Description**: Mixed offset-based and cursor-based pagination across endpoints. No shared envelope type.
**Missing todo**: Define shared `PaginatedResponse[T]` type and rule: cursor for real-time feeds, offset for admin lists.
**Suggested resolution**: Add shared Pydantic model in 02-api-endpoints.md header.

### GAP-014: No request size limits documented

**Severity**: MEDIUM
**Affected files**: 02-api-endpoints.md, 06-infrastructure.md
**Plan reference**: Plan 04 (Issue Reporting), Plan 06 (Tenant Admin)
**Description**: No global request body size limit in FastAPI/ASGI. File uploads have no documented size limits.
**Missing todo**: `INFRA-054: Request body size limits`. Default 1MB for JSON, 10MB for file uploads. Per-endpoint overrides for CSV bulk import and screenshot upload.
**Suggested resolution**: Add to 06-infrastructure.md.

---

## Area 3: AI/ML Pipeline (MOST CRITICAL CLUSTER)

### GAP-015: No retrieval confidence score calculation service

**Severity**: HIGH
**Affected files**: 03-ai-services.md, 02-api-endpoints.md
**Plan reference**: Plan 01 (Foundation)
**Description**: Chat SSE includes `retrieval_confidence`, frontend displays it, tests validate it — but no service todo implements the calculation algorithm. Where does the number come from?
**Missing todo**: `AI-053: RetrievalConfidenceCalculator service`. Input: vector search results. Output: float 0.0-1.0. Algorithm: `mean(top_3_scores)*0.6 + min(result_count/5,1.0)*0.2 + recency_factor*0.2`. Label strictly as "retrieval quality proxy."
**Suggested resolution**: Add to 03-ai-services.md.

### GAP-016: No LLM circuit breaker pattern

**Severity**: HIGH
**Affected files**: 03-ai-services.md, 06-infrastructure.md
**Plan reference**: All plans with LLM calls
**Description**: LLM calls in 5+ places (chat, intent, profile learning, issue triage, glossary expansion). If provider has outage, all fail simultaneously. Only issue triage mentions retry backoff. No circuit breaker exists.
**Missing todo**: `INFRA-055: LLM circuit breaker`. Half-open/open/closed state per tenant per LLM slot. Open at 50% failure rate in 60s window. Expose circuit state in `/ready` endpoint and metrics.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-017: No embedding service todo

**Severity**: HIGH
**Affected files**: 03-ai-services.md
**Plan reference**: Plan 01 (Foundation), Plan 03 (Caching)
**Description**: RAG pipeline step 3 requires embedding generation. Caching stores embeddings with float16 compression. But no `EmbeddingService` exists in 03-ai-services.md.
**Missing todo**: `AI-054: EmbeddingService`. Methods: `embed_query(text, tenant_id)`, `embed_batch(texts, tenant_id)`. Read model from tenant config, float16 compression for cache storage, rate limit handling.
**Suggested resolution**: Add to 03-ai-services.md as a foundation service.

### GAP-018: No vector search service todo

**Severity**: HIGH
**Affected files**: 03-ai-services.md
**Plan reference**: Plan 01 (Foundation)
**Description**: RAG pipeline step 4 is vector search. No service todo implements the cloud-provider abstraction layer for OpenSearch/Azure AI Search/Vertex AI Search.
**Missing todo**: `AI-055: VectorSearchService`. Strategy pattern: `OpenSearchBackend`, `AzureAISearchBackend`, `VertexAISearchBackend` selected by `CLOUD_PROVIDER`. Parallel multi-index search, tenant-scoped indexes, result deduplication.
**Suggested resolution**: Add to 03-ai-services.md as a foundation service.

### GAP-019: No chat orchestration service todo

**Severity**: CRITICAL
**Affected files**: 03-ai-services.md, 02-api-endpoints.md
**Plan reference**: Plan 01 (Foundation)
**Description**: API-007 (POST /chat/stream) is the core endpoint but no service todo implements the RAG pipeline orchestrator that calls all 8 steps in sequence. Individual components exist but the orchestrator that ties them together is MISSING. This is the most critical gap.
**Missing todo**: `AI-056: ChatOrchestrationService (RAG pipeline orchestrator)`. 8-step pipeline: (0) glossary pre-translation, (1) JWT validation, (2) intent detection, (3) embedding generation, (4) parallel vector search, (5) SystemPromptBuilder, (6) LLM streaming synthesis, (7) confidence scoring, (8) SSE event emission + conversation persistence.
**Suggested resolution**: Add to 03-ai-services.md as the FIRST entry — all other AI services depend on it or feed into it.

### GAP-020: No intent detection service todo

**Severity**: MEDIUM
**Affected files**: 03-ai-services.md
**Plan reference**: Plan 01 (Foundation)
**Description**: RAG pipeline step 2 is intent detection. The "remember that" fast path implies intent exists, but general-purpose intent detection (rag_query vs greeting vs clarification vs feedback) is absent.
**Missing todo**: `AI-057: IntentDetectionService`. Classifies queries: rag_query, clarification, greeting, remember (→ fast path), feedback. Uses tenant's configured intent model.
**Suggested resolution**: Add to 03-ai-services.md.

### GAP-021: SystemPromptBuilder has no token budget warning/alerting

**Severity**: LOW
**Affected files**: 03-ai-services.md
**Plan reference**: Plan 08 (Profile & Memory)
**Description**: AI-033 implements truncation but no metric/alert when truncation happens frequently — a signal that a tenant's config is too aggressive.
**Missing todo**: Emit `system_prompt_truncation_total{tenant_id, layer}` Prometheus counter. Alert when truncation rate > 20% of queries over 24h.
**Suggested resolution**: Add acceptance criteria to AI-033.

---

## Area 4: Frontend

### GAP-022: No React Error Boundary implementation

**Severity**: HIGH
**Affected files**: 04-frontend.md
**Plan reference**: All plans with frontend
**Description**: 61 component todos, none mention Error Boundaries. Malformed SSE event could crash entire chat UI.
**Missing todo**: `FE-063: Global and route-level Error Boundaries`. `app/error.tsx` for global, component-level boundaries around SSE consumer, Recharts, TanStack Table.
**Suggested resolution**: Add to 04-frontend.md Project Setup section.

### GAP-023: No loading states / skeleton screens specification

**Severity**: MEDIUM
**Affected files**: 04-frontend.md
**Plan reference**: All plans with frontend
**Description**: FE-005 mentions skeleton for chat but no other component specifies loading states. Admin tables, dashboards, and forms will appear broken during data fetching.
**Missing todo**: Loading state specifications per major view. Shared `Skeleton` component. `app/(admin)/admin/loading.tsx`, `app/(platform)/platform/loading.tsx`.
**Suggested resolution**: Add acceptance criteria to FE-026, FE-040, FE-049.

### GAP-024: No offline/network error handling

**Severity**: MEDIUM
**Affected files**: 04-frontend.md
**Plan reference**: Plan 01 (Foundation)
**Description**: FE-022 mentions offline queue for issue reports but no global network error handling. Failed backend will cause silent failures or hanging requests.
**Missing todo**: `FE-064: Global network status handler`. Offline detection, "Connection lost" banner, IndexedDB queue for critical mutations, auto-retry on restore.
**Suggested resolution**: Add to 04-frontend.md.

### GAP-025: No accessibility (a11y) requirements

**Severity**: MEDIUM
**Affected files**: 04-frontend.md
**Plan reference**: All plans with frontend
**Description**: Zero WCAG mentions across all 61 frontend todos. Obsidian Intelligence dark theme contrast ratios unverified. Enterprise healthcare/government customers require WCAG 2.1 AA.
**Missing todo**: Accessibility criteria: keyboard navigation, ARIA labels on icon-only buttons, focus management in modals, 4.5:1 contrast ratio, skip-to-content link, screen reader announcements for streaming responses.
**Suggested resolution**: Add global a11y acceptance criteria in 04-frontend.md header + specific criteria per component.

### GAP-026: No frontend bundle size budget

**Severity**: LOW
**Affected files**: 04-frontend.md, 06-infrastructure.md
**Plan reference**: Plan 01 (Foundation)
**Description**: Many large dependencies installed (html2canvas ~300KB, Recharts ~200KB). No bundle size budget or analyzer.
**Missing todo**: Bundle size budget: main chunk <200KB gzipped, route chunks <100KB. `@next/bundle-analyzer` in CI.
**Suggested resolution**: Add to FE-001 acceptance criteria.

### GAP-027: No dark/light theme toggle

**Severity**: LOW
**Affected files**: 04-frontend.md
**Plan reference**: Plan 01 (Foundation)
**Description**: Dark-first but no light theme toggle. Some enterprise environments require light themes.
**Missing todo**: Note as Phase 2 consideration. Ensure CSS variables structured for future light theme.
**Suggested resolution**: Add note in 04-frontend.md header.

---

## Area 5: Infrastructure & DevOps

### GAP-028: No database backup and restore strategy

**Severity**: CRITICAL
**Affected files**: 06-infrastructure.md
**Plan reference**: Plan 02 (Migration)
**Description**: 44 tables including financial data, compliance records, user data — zero mention of backup, PITR, or restore testing. If migration fails, no documented rollback path.
**Missing todo**: `INFRA-056: Database backup and restore strategy`. RDS Aurora: automated backups 35-day retention, PITR, monthly restore testing. Pre-migration backup checkpoint in Alembic runner.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-029: No Redis persistence and recovery strategy

**Severity**: HIGH
**Affected files**: 06-infrastructure.md
**Plan reference**: Plan 03 (Caching)
**Description**: INFRA-039 sets `allkeys-lru` which evicts ANY key under memory pressure — including working memory (7-day TTL, no PostgreSQL backup) and query counters.
**Missing todo**: `INFRA-057: Redis persistence and data criticality policy`. Two Redis instances: cache (allkeys-lru) + durable data (noeviction + AOF). Document acceptable data loss scenarios.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-030: No monitoring/alerting rules

**Severity**: CRITICAL
**Affected files**: 06-infrastructure.md
**Plan reference**: All plans
**Description**: INFRA-045 collects metrics but zero alerting rules defined. Metrics without alerts are useless for operations. DB pool exhaustion, cache hit collapse, LLM outage — all go unnoticed.
**Missing todo**: `INFRA-058: Alerting rules and notification channels`. Critical alerts: DB pool >80%, Redis memory >80%, cache hit <50% sustained 15min, LLM error rate >10%, P99 latency >10s, disk <20%. PagerDuty/Slack/email.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-031: No operational runbook

**Severity**: HIGH
**Affected files**: 06-infrastructure.md
**Plan reference**: All plans
**Description**: Zero operational runbooks. On-call engineers have no documented procedures for common failures.
**Missing todo**: `INFRA-059: Operational runbook`. Restart procedures, stuck Redis Streams recovery, Alembic migration rollback, secret rotation, LLM outage fallback, RLS bypass investigation.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-032: No Redis connection pool configuration

**Severity**: MEDIUM
**Affected files**: 06-infrastructure.md
**Plan reference**: Plan 03 (Caching)
**Description**: INFRA-011 uses aioredis but no connection pool configuration. Default pool size may be exhausted under load. Redis used by nearly every service.
**Missing todo**: Redis pool config: max_connections=50, socket_timeout=5s, retry_on_timeout=True. Separate pool for pub/sub subscribers (long-lived connections).
**Suggested resolution**: Add acceptance criteria to INFRA-011.

### GAP-033: No graceful shutdown handler for background jobs

**Severity**: MEDIUM
**Affected files**: 06-infrastructure.md
**Plan reference**: Plan 03 (Caching), Plan 04 (Issue Reporting), Plan 08 (Profile & Memory)
**Description**: Background jobs (cache warming, triage worker, document sync, profile learning) don't document SIGTERM handling. Partial state possible on forced shutdown.
**Missing todo**: Graceful shutdown criteria on INFRA-047: SIGTERM handler, allow in-progress jobs to complete (with timeout), mark incomplete for retry, drain Redis Streams, close connections cleanly.
**Suggested resolution**: Add acceptance criteria to INFRA-047.

### GAP-034: No development seed data script

**Severity**: MEDIUM
**Affected files**: 06-infrastructure.md, 05-testing.md
**Plan reference**: All plans
**Description**: New developer clones repo, runs docker compose up, gets empty database. 30+ minutes of manual setup required. No seed script exists.
**Missing todo**: `INFRA-060: Development seed data script` (`scripts/seed-dev.py`). Creates: default tenant, admin user, 3 agents, 10 glossary terms, mock conversations. Idempotent.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-035: No Alembic migration rollback testing

**Severity**: MEDIUM
**Affected files**: 06-infrastructure.md, 05-testing.md
**Plan reference**: Plan 02 (Migration)
**Description**: 10+ Alembic migrations. Each has forward acceptance criteria but none verify `alembic downgrade` works. Untested downgrade functions risk inconsistent state.
**Missing todo**: `TEST-073: Alembic migration rollback tests`. Run upgrade + downgrade + upgrade for each migration file. Verify schema state after each direction.
**Suggested resolution**: Add to 05-testing.md and add downgrade criteria to DB-001 through DB-010.

---

## Area 6: HAR-Specific

### GAP-036: No dispute resolution mechanism

**Severity**: HIGH
**Affected files**: 02-api-endpoints.md, 03-ai-services.md
**Plan reference**: Plan 07 (HAR)
**Description**: Transaction state machine includes DISPUTED → RESOLVED but no API endpoint to file a dispute, no resolution workflow, no arbitration. Critical for Tier 3 financial transactions.
**Missing todo**: `API-124: File transaction dispute` (POST /registry/transactions/{id}/dispute) and `API-125: Resolve dispute` (platform admin only). Reason, evidence upload, counterparty notification, resolution timeline.
**Suggested resolution**: Add to 02-api-endpoints.md HAR section. Phase 1: manual platform admin resolution.

### GAP-037: No HAR agent card versioning

**Severity**: MEDIUM
**Affected files**: 01-database-schema.md, 02-api-endpoints.md
**Plan reference**: Plan 07 (HAR)
**Description**: Agent cards are overwritten on update. Existing transactions have no audit trail of card state at transaction time.
**Missing todo**: `agent_card_versions` table or `version INTEGER` column with `agent_card_history` table. Transaction records reference card version at creation time.
**Suggested resolution**: Add acceptance criteria to DB-037. Add `card_version` to har_transaction_events.

### GAP-038: No HAR Phase 0 pilot tenant operational tasks

**Severity**: LOW
**Affected files**: 06-infrastructure.md
**Plan reference**: Plan 07 (HAR)
**Description**: 100-transaction gate at Week 16 is aspirational without operational setup: pilot tenant invitations, demo agent cards, transaction monitoring.
**Missing todo**: Operational tasks for Phase 0: invite email template, demo agent cards, transaction volume dashboard, Week 16 gate check calendar reminder.
**Suggested resolution**: Add to 06-infrastructure.md HAR section.

### GAP-039: No HAR fee calculation service

**Severity**: MEDIUM
**Affected files**: 03-ai-services.md, 01-database-schema.md
**Plan reference**: Plan 07 (HAR)
**Description**: DB-038 has har_fee_records but no service calculates fees, applies basis point rates, or creates records.
**Missing todo**: `AI-058: HAR fee calculation service`. Apply fee schedule to completed Tier 3 transactions. Fee rate from platform config (not hardcoded). Handle edge cases: zero-value, disputed, failed.
**Suggested resolution**: Add to 03-ai-services.md HAR section.

---

## Area 7: Integration & Cross-System

### GAP-040: No Auth0 Management API token refresh strategy

**Severity**: HIGH
**Affected files**: 03-ai-services.md, 06-infrastructure.md
**Plan reference**: Plan 08 (Profile & Memory), Plan 06 (Tenant Admin)
**Description**: Auth0 Management API tokens expire after 24h, rate-limited to 2 req/sec. No todo addresses obtaining, caching, or refreshing Management API tokens.
**Missing todo**: `INFRA-061: Auth0 Management API token manager`. Client credentials grant, Redis cache 23h TTL, auto-refresh on expiry, retry backoff on 429. Singleton shared across all Management API consumers.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-041: No Microsoft Graph API token management

**Severity**: MEDIUM
**Affected files**: 06-infrastructure.md
**Plan reference**: Plan 06 (Tenant Admin)
**Description**: Graph API tokens expire after 1 hour. INFRA-025 syncs SharePoint but no per-tenant OAuth token management exists.
**Missing todo**: `INFRA-062: Microsoft Graph API token manager per tenant`. Read OAuth refresh tokens from secrets manager, cache access tokens 55min TTL, handle revocation, support multiple tenants.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-042: No Google Drive token management

**Severity**: MEDIUM
**Affected files**: 06-infrastructure.md
**Plan reference**: Plan 06 (Tenant Admin)
**Description**: Google Drive OAuth access tokens expire after 1 hour. DWD service account tokens generated per-user. No token management for either path.
**Missing todo**: `INFRA-063: Google Drive token manager`. OAuth refresh token flow + DWD service account JWT assertion. Per-tenant, per-user. DWD sync user must be a real Workspace user (not SA email).
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-043: No cross-service event taxonomy documentation

**Severity**: MEDIUM
**Affected files**: 03-ai-services.md, 06-infrastructure.md
**Plan reference**: All plans
**Description**: Each service invents its own integration pattern. No unified taxonomy: Redis Pub/Sub vs Redis Streams vs direct calls used inconsistently.
**Missing todo**: Document all inter-service events by type: (1) Pub/Sub for real-time invalidation, (2) Redis Streams for durable async, (3) direct calls for same-process. List all event types with schemas.
**Suggested resolution**: Add to 06-infrastructure.md General DevOps section.

### GAP-044: No email service abstraction

**Severity**: MEDIUM
**Affected files**: 02-api-endpoints.md, 06-infrastructure.md
**Plan reference**: Plan 04, 05, 06
**Description**: Multiple features send emails (invites, status updates, credential expiry). INFRA-042 lists SENDGRID_API_KEY but no email service implementation todo exists.
**Missing todo**: `INFRA-064: Email service abstraction`. Strategy pattern: SendGrid, AWS SES, Azure Communication Services. Methods: `send_template(to, template_id, context)`. Templates: tenant invite, issue status, user invitation, credential expiry.
**Suggested resolution**: Add to 06-infrastructure.md. MVP: SendGrid only. Abstraction enables future swap.

---

## Area 8: Performance

### GAP-045: No load testing or performance baseline

**Severity**: HIGH
**Affected files**: 05-testing.md, 06-infrastructure.md
**Plan reference**: All plans
**Description**: Zero load testing, no performance baselines. RAG pipeline has latency targets (intent <1s, total <3s) but no validation under load. First production spike reveals all bottlenecks simultaneously.
**Missing todo**: `TEST-074: Load testing suite` (k6 or Locust). Scenarios: 50 concurrent chat streams, 10 concurrent admin ops, 100 issue report burst, 5 concurrent document syncs. Baseline P50/P95/P99 per endpoint.
**Suggested resolution**: Add to 05-testing.md as separate section. Run nightly in CI, not every PR.

### GAP-046: No database query performance monitoring

**Severity**: MEDIUM
**Affected files**: 06-infrastructure.md
**Plan reference**: Plan 02 (Migration)
**Description**: RLS adds overhead to every query. No `pg_stat_statements`, no slow query logging, no EXPLAIN ANALYZE benchmarks.
**Missing todo**: `INFRA-065: Database query performance monitoring`. Enable pg_stat_statements, slow query logging (threshold 100ms), benchmark critical queries (conversation list, message history, user search) after RLS is applied.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-047: No CDN or static asset caching strategy

**Severity**: LOW
**Affected files**: 04-frontend.md, 06-infrastructure.md
**Plan reference**: Plan 01 (Foundation)
**Description**: No Cache-Control headers for static assets. Every page load fetches all JS bundles from origin.
**Missing todo**: Configure `next.config.js` headers: `_next/static/` with `max-age=31536000, immutable`.
**Suggested resolution**: Add to FE-001 or INFRA-041.

### GAP-048: No SSE connection keep-alive optimization

**Severity**: LOW
**Affected files**: 02-api-endpoints.md, 06-infrastructure.md
**Plan reference**: Plan 01 (Foundation)
**Description**: Enterprise proxies timeout idle connections after 60 seconds. No heartbeat pings or connection limits documented.
**Missing todo**: SSE keep-alive: `:heartbeat\n\n` comment every 30s to prevent proxy timeout. Max chat stream duration: 5 min. Per-user SSE connection limit: 3 concurrent max.
**Suggested resolution**: Add acceptance criteria to API-007 and API-012.

---

## Area 9: Operational

### GAP-049: No platform admin bootstrap/first-run script

**Severity**: HIGH
**Affected files**: 06-infrastructure.md, 02-api-endpoints.md
**Plan reference**: Plan 05 (Platform Admin)
**Description**: Chicken-and-egg: platform admin portal requires a platform admin user, but no mechanism to create the first one.
**Missing todo**: `INFRA-066: Platform admin bootstrap CLI`. `python manage.py create-platform-admin --email admin@company.com`. Or `BOOTSTRAP_ADMIN_EMAIL` env var on first startup. Idempotent, secure, no web attack surface.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-050: No secrets rotation procedure

**Severity**: HIGH
**Affected files**: 06-infrastructure.md
**Plan reference**: All plans
**Description**: No zero-downtime rotation procedure for: JWT signing key, DB password, Redis password, Auth0 client secret, SendGrid API key.
**Missing todo**: `INFRA-067: Secret rotation procedures`. JWT: JWKS with key rotation (dual-key acceptance window). DB: Aurora online rotation. Redis: AOF + coordinated restart. LLM keys: update in tenant_configs + invalidate config cache.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-051: No logging retention and rotation policy

**Severity**: MEDIUM
**Affected files**: 06-infrastructure.md
**Plan reference**: All plans
**Description**: INFRA-044 implements logging but no retention, rotation, or shipping policy. Logs will fill disks without rotation.
**Missing todo**: Log management: 90-day operational retention, 7-year audit retention (financial regulations), daily rotation + compress, ship to cloud logging, PII redaction verification.
**Suggested resolution**: Add acceptance criteria to INFRA-044 or create `INFRA-068`.

### GAP-052: No database migration pre-flight check

**Severity**: MEDIUM
**Affected files**: 06-infrastructure.md
**Plan reference**: Plan 02 (Migration)
**Description**: 10+ Alembic migrations modifying production data. No pre-migration checklist: backup exists? Connections drained? Maintenance mode active?
**Missing todo**: `INFRA-069: Migration pre-flight script`. Validates: recent backup (<1h), no long-running transactions, sufficient disk space, app in maintenance mode. Aborts if any check fails.
**Suggested resolution**: Add to 06-infrastructure.md.

### GAP-053: No tenant data isolation canary verification in production

**Severity**: MEDIUM
**Affected files**: 05-testing.md, 06-infrastructure.md
**Plan reference**: Plan 02 (Migration)
**Description**: Tests verify isolation but no production-time canary confirms RLS is working. Misconfigured DB connection could silently bypass RLS.
**Missing todo**: `INFRA-070: RLS canary health check`. Every 5 minutes: write row as tenant_A, read as tenant_B, verify zero rows returned, delete test row. Alert if isolation breach detected.
**Suggested resolution**: Add to 06-infrastructure.md or as acceptance criteria on INFRA-043.

---

## Area 10: Cross-Plan Tasks & Dependencies

### GAP-054: No conversation persistence service todo

**Severity**: HIGH
**Affected files**: 03-ai-services.md, 02-api-endpoints.md
**Plan reference**: Plan 01 (Foundation)
**Description**: API-006/008 read conversations from DB. But no service todo implements the write side: creating conversation records, persisting messages (both user + AI), storing tokens/model/confidence metadata, managing lifecycle.
**Missing todo**: `AI-059: ConversationPersistenceService`. Methods: `create_conversation`, `append_message`, `close_conversation`. Handle streaming (persist AI response after stream completes), title auto-generation.
**Suggested resolution**: Add to 03-ai-services.md as a foundation service.

### GAP-055: No document indexing pipeline todo

**Severity**: HIGH
**Affected files**: 03-ai-services.md
**Plan reference**: Plan 01 (Foundation), Plan 06 (Tenant Admin)
**Description**: INFRA-025 syncs files from cloud storage. But no service implements: document parsing (PDF/DOCX/PPTX), chunking, embedding per chunk, vector index upsert. Documents are synced but never searchable.
**Missing todo**: `AI-060: DocumentIndexingPipeline`. Steps: parse → chunk (512 tokens, 50 token overlap) → embed → upsert to search index with tenant metadata. Handle incremental updates (re-index changed only).
**Suggested resolution**: Add to 03-ai-services.md as a foundation service.

### GAP-056: No user management service todo

**Severity**: MEDIUM
**Affected files**: 03-ai-services.md, 02-api-endpoints.md
**Plan reference**: Plan 06 (Tenant Admin)
**Description**: 12+ user management API endpoints exist but no backend service todo implements the business logic (invitation flow, role assignment with RBAC validation, user anonymization cascade, bulk import).
**Missing todo**: `AI-061: UserManagementService`. Business logic: invitation link generation + email, role hierarchy validation, GDPR anonymization cascade, max users per plan enforcement, invitation expiry (48h).
**Suggested resolution**: Add to 03-ai-services.md.

### GAP-057: No tenant provisioning rollback verification

**Severity**: MEDIUM
**Affected files**: 06-infrastructure.md, 05-testing.md
**Plan reference**: Plan 05 (Platform Admin)
**Description**: INFRA-020 mentions rollback on failure but TEST-023 doesn't verify each step's rollback cleans up prior steps. Partial provisioning leaves orphaned resources.
**Missing todo**: 6 rollback test scenarios in TEST-023 (failure at each of 6 steps). Verify all prior steps cleaned up, tenant status = "failed", no orphaned resources.
**Suggested resolution**: Add rollback test cases to TEST-023 and specify cleanup order in INFRA-020.

### GAP-058: Token budget inconsistency between files

**Severity**: MEDIUM
**Affected files**: 03-ai-services.md, 05-testing.md
**Plan reference**: Plan 08 (Profile & Memory)
**Description**: Org Context Layer 2 budget referenced as "500 tokens" in some places, "100 tokens" in others. Canonical value is 100 tokens (per MEMORY.md confirmed decision).
**Missing todo**: Audit all token budget references. Fix TEST-057 Line 1180 (500 → 100 tokens). Canonical: Layer 2=100, Layer 3=200, Layer 4a=100, Layer 4b=150, Layer 6=removed.
**Suggested resolution**: Review and update any "500 token" references for Org Context.

### GAP-059: Billing tables created but no API endpoints use them

**Severity**: MEDIUM
**Affected files**: 01-database-schema.md, 02-api-endpoints.md
**Plan reference**: Plan 05 (Platform Admin)
**Description**: DB-045 creates billing tables but no API reads or writes to them (no Stripe webhook per GAP-005, no billing dashboard endpoint). Tables permanently empty.
**Missing todo**: Either add billing API endpoints or document DB-045 as "Phase 2 preparation" explicitly.
**Suggested resolution**: Mark DB-045 as Phase 2 preparation. Add placeholder API endpoints in Phase 2 section of 02-api-endpoints.md.

### GAP-060: No cross-file dependency ID references

**Severity**: LOW
**Affected files**: All 6 files
**Plan reference**: All plans
**Description**: Inter-file dependencies referenced by concept but not by ID (e.g., AI-002 says "depends on user_profiles table" but doesn't reference DB-013). Silent integration breaks possible.
**Missing todo**: Cross-file dependency map in 00-master-index.md listing all inter-file dependency chains with specific IDs.
**Suggested resolution**: Add "Cross-File Dependencies" section to 00-master-index.md.

### GAP-061: No LLM response streaming implementation todo

**Severity**: MEDIUM
**Affected files**: 02-api-endpoints.md, 03-ai-services.md
**Plan reference**: Plan 01 (Foundation)
**Description**: API-007 specifies SSE token streaming but no service implements the LLM streaming adapter: provider streaming API wrap, chunk emission, stream interruption handling, token counting during streaming.
**Missing todo**: LLM streaming adapter in chat orchestrator (GAP-019) acceptance criteria. Or separate `AI-062: LLMStreamingAdapter`.
**Suggested resolution**: Add as acceptance criteria to AI-056 (chat orchestrator).

### GAP-062: No tenant suspension propagation todo

**Severity**: MEDIUM
**Affected files**: 02-api-endpoints.md, 06-infrastructure.md
**Plan reference**: Plan 05 (Platform Admin)
**Description**: API-037 suspends a tenant and JWT middleware returns 403. But active SSE streams, background jobs, and scheduled tasks for suspended tenants are not stopped.
**Missing todo**: Acceptance criteria on API-037: active SSE connections closed within 30s via Redis pub/sub `tenant_suspended` event. Background jobs skip suspended tenants. Scheduled tasks skip suspended tenants.
**Suggested resolution**: Add acceptance criteria to API-037 and INFRA-048.

---

## Summary Table

| Severity  | Count  | Action Required                |
| --------- | ------ | ------------------------------ |
| CRITICAL  | 7      | Must fix before any deployment |
| HIGH      | 18     | Must fix before GA             |
| MEDIUM    | 24     | Should fix in Phase 1          |
| LOW       | 13     | Nice to have / Phase 2+        |
| **Total** | **62** |                                |

| Priority  | Gaps   | Additional Hours |
| --------- | ------ | ---------------- |
| CRITICAL  | 7      | ~80h             |
| HIGH      | 18     | ~160h            |
| MEDIUM    | 24     | ~120h            |
| LOW       | 13     | ~40h             |
| **Total** | **62** | **~400h**        |

**Revised project total**: ~1,994h (was ~1,594h, +25%)

---

## Critical Path Additions (Blocking ALL other work)

These gaps must be resolved before any implementation begins:

1. **GAP-019**: ChatOrchestrationService — the entire platform depends on this
2. **GAP-017**: EmbeddingService — dependency of chat, caching, and document indexing
3. **GAP-018**: VectorSearchService — dependency of chat and HAR search
4. **GAP-001**: CORS middleware — day-one browser showstopper
5. **GAP-028**: Database backup strategy — safety requirement before any migration
6. **GAP-054**: ConversationPersistenceService — chat cannot persist without it
7. **GAP-055**: DocumentIndexingPipeline — RAG is useless without document indexing
