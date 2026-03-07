# mingai Authority Documents

Read these before touching any backend code. They contain non-negotiable architecture decisions and the constraints that keep the system consistent.

## What is mingai

mingai is a multi-tenant enterprise AI assistant platform. End users query a RAG-backed AI agent. Tenant admins manage their workspace — users, documents, glossary, issues. Platform admins operate the platform — tenants, LLM profiles, dashboards.

This repository (`src/backend/`) is the FastAPI backend. Port 8022. All endpoints under `/api/v1/`.

## Document Map

| Document | What it covers | Read when |
|---|---|---|
| `CLAUDE.md` | Stack, patterns, gotchas, security invariants | Start of every backend session |
| `01-api-reference.md` | All endpoints — method, path, auth requirement | Adding or changing endpoints |
| `02-architecture.md` | Multi-tenancy, JWT, storage, caching decisions | Touching core infrastructure |

## Ship-Stopper Gates

These must pass before any feature is merged.

| Gate | What it protects |
|---|---|
| RLS cross-tenant isolation | Every endpoint that reads/writes per-tenant data |
| JWT v2 auth on all protected routes | All non-auth endpoints |
| Screenshot blur gate (`blur_acknowledged=True`) | Issue create endpoint |
| `user_id` never in team memory | GDPR isolation |
| Dynamic PATCH columns through allowlist | SQL injection prevention |
| `FRONTEND_URL != "*"` | CORS lockdown |
| Secrets from env only | No hardcoded keys or model names |
