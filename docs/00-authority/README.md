# mingai Authority Documents

Read these before touching any code. They contain the architecture decisions, patterns, and constraints that keep the system consistent.

Last updated: 2026-03-17.

---

## What Is mingai

mingai is a multi-tenant enterprise AI assistant platform. Three roles share one codebase:

- **End users** — chat with a RAG-backed AI agent through a two-state chat interface
- **Tenant admins** — manage their workspace: users, documents, glossary, agents, issues, analytics
- **Platform admins** — operate the platform: tenants, LLM profiles, dashboards, registries

---

## Document Map

| Document              | What it covers                                                                                                                                                                           | Read when                       |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| `CLAUDE.md`           | Full codegen instructions: architecture, all key file paths, backend patterns (17 patterns + 18 gotchas), frontend structure, design system summary, env vars, security invariants (28)  | Start of every coding session   |
| `01-api-reference.md` | All endpoints — method, path, auth requirement, request/response shape                                                                                                                   | Adding or changing any endpoint |
| `02-architecture.md`  | Deep dives: multi-tenancy + RLS, JWT v2, cloud-agnostic storage, caching strategy, screenshot blur pipeline, issue triage stream, GitHub webhook, health score formula, HAR A2A protocol, **LLM provider credentials** (Fernet-encrypted BYTEA, DB-first resolution, bootstrap seed, background health job) | Touching core infrastructure    |

---

## Stack at a Glance

| Concern     | Technology                                                     | Port |
| ----------- | -------------------------------------------------------------- | ---- |
| Backend API | FastAPI + SQLAlchemy (async) + PostgreSQL (RLS) + Redis        | 8022 |
| Frontend    | Next.js 14 App Router + TypeScript + React Query + Tailwind    | 3022 |
| Auth        | JWT v2 HS256 (local) — Auth0 JWKS integration prepared         | —    |
| AI          | Azure OpenAI (`AsyncAzureOpenAI`), pgvector for embeddings     | —    |
| Async       | Redis Streams (issue triage), Redis Pub/Sub (notification SSE) | —    |

API prefix: `/api/v1/` on all backend endpoints.

---

## Key Source Locations

### Backend (`src/backend/`)

| Path                       | Purpose                                                              |
| -------------------------- | -------------------------------------------------------------------- |
| `app/core/config.py`       | All config from env via pydantic_settings                            |
| `app/core/database.py`     | `get_set_tenant_sql()`, `validate_tenant_id()`, RLS helpers          |
| `app/core/dependencies.py` | `get_current_user`, `require_tenant_admin`, `require_platform_admin` |
| `app/core/redis_client.py` | `build_redis_key()` — always use this, never f-string keys           |
| `app/api/router.py`        | Aggregates all module routers                                        |
| `app/modules/`             | One subdirectory per domain (auth, chat, issues, har, etc.)          |
| `tests/unit/`              | Tier 1 — mocked, 2087+ tests                                         |
| `tests/integration/`       | Tier 2 — real PostgreSQL + Redis (Docker)                            |
| `tests/e2e/`               | Tier 3 — Playwright, full stack                                      |
| `alembic/versions/`        | Database migrations v001–v039 (40 total)                             |
| `docker-compose.yml`       | PostgreSQL + Redis for local dev                                     |

### Frontend (`src/web/`)

| Path                       | Purpose                                             |
| -------------------------- | --------------------------------------------------- |
| `app/(admin)/admin/`       | Tenant admin routes                                 |
| `app/(platform)/platform/` | Platform admin routes                               |
| `app/chat/`                | End-user chat (two-state layout)                    |
| `components/layout/`       | AppShell, Sidebar, Topbar                           |
| `lib/api.ts`               | `apiClient` — Bearer token injection, all API calls |
| `lib/auth.ts`              | `getToken()`, `getCurrentUser()`, role helpers      |
| `lib/chartColors.ts`       | `CHART_COLORS` — always use for chart series        |
| `middleware.ts`            | Route protection by JWT scope/role                  |
| `tailwind.config.ts`       | Obsidian Intelligence design tokens                 |
| `app/globals.css`          | CSS custom properties                               |

### Project Config

| Path                                                   | Purpose                                              |
| ------------------------------------------------------ | ---------------------------------------------------- |
| `.env`                                                 | All secrets and model names (single source of truth) |
| `.claude/agents/project/mingai-backend-specialist.md`  | Backend specialist agent                             |
| `.claude/agents/project/mingai-frontend-specialist.md` | Frontend specialist agent                            |
| `.claude/skills/project/backend-status.md`             | Quick status check skill                             |
| `workspaces/mingai/99-ui-proto/index.html`             | Visual ground truth for all UI                       |
| `todos/active/`                                        | Active work items by domain                          |

---

## Architecture Quick Reference

### Multi-Tenancy (RLS)

Every user-owned table has `tenant_id UUID NOT NULL`. PostgreSQL RLS enforces tenant isolation at the database level. Before any query, routes execute:

```python
sql, params = get_set_tenant_sql(tenant_id)
await db.execute(text(sql), params)
```

The application DB user must be `NOSUPERUSER` — superusers bypass RLS.

### JWT v2 Claims

```json
{
  "sub": "<user_id>",
  "tenant_id": "<uuid>",
  "roles": ["end_user"],
  "scope": "tenant",
  "plan": "professional",
  "token_version": 2
}
```

### Redis Key Pattern

```
mingai:{tenant_id}:{service}:{id...}
```

Always constructed via `build_redis_key()` — raises `ValueError` if any segment contains a colon.

### HAR A2A

Agent-to-agent transactions with Ed25519 cryptographic signing, nonce replay protection, and a human approval gate for amounts >= $5,000. State machine: `DRAFT → OPEN → NEGOTIATING → COMMITTED → EXECUTING → COMPLETED`.

---

## Ship-Stopper Security Gates

These must pass before any feature is merged:

| Gate                                                     | Protects                         |
| -------------------------------------------------------- | -------------------------------- |
| RLS cross-tenant isolation                               | All per-tenant DB reads/writes   |
| JWT v2 auth on all protected routes                      | Non-auth endpoints               |
| Screenshot blur gate (`blur_acknowledged=True`)          | Issue create endpoint            |
| `user_id` never in team working memory                   | GDPR isolation                   |
| Dynamic PATCH columns through allowlist                  | SQL injection                    |
| `FRONTEND_URL != "*"`                                    | CORS                             |
| Secrets from env only                                    | No hardcoded keys or model names |
| GitHub webhook HMAC-SHA256 verified; 503 if secret unset | Webhook endpoint                 |
| Issue actions validated against module-level allowlist   | Admin/platform action endpoints  |
| Redis key segments validated against `_SAFE_SEGMENT_RE`  | All Redis key construction       |
| Ed25519 private keys Fernet-encrypted at rest            | HAR agent keypairs               |
| LLM provider API keys Fernet-encrypted (BYTEA); `api_key_encrypted` never returned in any API response | `/platform/providers` all responses |
| HAR nonce replay check (Redis SETNX TTL=600)             | All signed HAR events            |
| HAR human approval gate for amounts >= $5,000            | HAR transaction commit path      |

---

## Design System

**Obsidian Intelligence** — dark-first enterprise AI. Full spec in `.claude/rules/design-system.md`. Visual ground truth: `workspaces/mingai/99-ui-proto/index.html` (screenshot via Playwright before implementing any screen).

Critical rules:

- Accent `#4fffb0` only for active states and positive metrics — never decorative
- AI chat responses: no card, no bubble, no background — text on `--bg-base` directly
- Typefaces: Plus Jakarta Sans (UI), DM Mono (data/numbers) — never Inter or Roboto
- Purple/blue palette (`#6366F1`, `#8B5CF6`, `#3B82F6`) is banned
- End-user sidebar: History only — never show agent list or workspace navigation

---

## Where to Go for More

- **Patterns and gotchas**: `CLAUDE.md` in this directory
- **Endpoint reference**: `01-api-reference.md` in this directory
- **Architecture decisions**: `02-architecture.md` in this directory
- **Active work items**: `todos/active/` at repo root
- **Design system full spec**: `.claude/rules/design-system.md`
- **Backend specialist agent**: `.claude/agents/project/mingai-backend-specialist.md`
- **Proto UI**: `workspaces/mingai/99-ui-proto/index.html`
