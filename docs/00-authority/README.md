# mingai Authority Documents

Read these before touching any backend code. They contain non-negotiable architecture decisions and the constraints that keep the system consistent.

Last updated: 2026-03-08. Phase 1 COMPLETE. Phase 2 active — 1082+ tests passing. Pending: Registry (API-089–098), Platform extras (API-113–120), gap remediation (API-121–125).

## What is mingai

mingai is a multi-tenant enterprise AI assistant platform. End users query a RAG-backed AI agent. Tenant admins manage their workspace — users, documents, glossary, issues. Platform admins operate the platform — tenants, LLM profiles, dashboards.

This repository (`src/backend/`) is the FastAPI backend. Port 8022. All endpoints under `/api/v1/`.

## Document Map

| Document              | What it covers                                          | Read when                      |
| --------------------- | ------------------------------------------------------- | ------------------------------ |
| `CLAUDE.md`           | Stack, patterns, gotchas, security invariants           | Start of every backend session |
| `01-api-reference.md` | All endpoints — method, path, auth requirement          | Adding or changing endpoints   |
| `02-architecture.md`  | Multi-tenancy, JWT, storage, caching, streams decisions | Touching core infrastructure   |

## Phase Coverage

| Phase   | Status          | Modules                                                                                                                                                                                                                                                                                       |
| ------- | --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Phase 1 | COMPLETE        | Auth, Chat, Issues (CRUD), Memory, Admin, Glossary, Documents, Users, Teams, Tenants, Platform, Profile, HAR A2A (AI-040–AI-051), DocumentIndexingPipeline (AI-060)                                                                                                                           |
| Phase 2 | IN PROGRESS     | Notifications (SSE), Issues (triage stream, worker, admin queue, platform queue, GitHub webhook), Agents (studio + template deploy), Tool catalog, Analytics (satisfaction, engagement, cost, health, cache), Memory policy, Audit logs, Token budget, Agent templates, Redis key hardening    |
| Phase 2 | PENDING (S13)   | Registry (API-089–098 HAR agent registry), Platform extras (API-113–120: impersonation, GDPR deletion, notifications prefs), Gap remediation (API-121–125)                                                                                                                                    |

## Ship-Stopper Gates

These must pass before any feature is merged.

| Gate                                                     | What it protects                                 |
| -------------------------------------------------------- | ------------------------------------------------ |
| RLS cross-tenant isolation                               | Every endpoint that reads/writes per-tenant data |
| JWT v2 auth on all protected routes                      | All non-auth endpoints                           |
| Screenshot blur gate (`blur_acknowledged=True`)          | Issue create endpoint                            |
| `user_id` never in team memory                           | GDPR isolation                                   |
| Dynamic PATCH columns through allowlist                  | SQL injection prevention                         |
| `FRONTEND_URL != "*"`                                    | CORS lockdown                                    |
| Secrets from env only                                    | No hardcoded keys or model names                 |
| GitHub webhook HMAC-SHA256 verified; 503 if secret unset | Webhook endpoint                                 |
| Issue action validated against module-level allowlist    | Admin and platform action endpoints              |
| Redis key segments validated against `_SAFE_SEGMENT_RE`  | All Redis key construction                       |
| Ed25519 private keys Fernet-encrypted at rest            | HAR A2A agent keypairs                           |
| HAR nonce replay check (Redis SETNX TTL=600)             | All signed HAR events                            |
| HAR human approval gate for amounts ≥ $5,000             | HAR transaction commit path                      |
