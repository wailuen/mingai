# Project Memory — mingai

## Active Project: mingai (multi-tenant SaaS)

**New product name**: mingai
**Source (legacy single-tenant)**: `/Users/wailuen/Development/aihub2`
**Workspace**: `/Users/wailuen/Development/mingai/workspaces/mingai/`
**Goal**: Build mingai — convert single-tenant RAG platform → multi-tenant SaaS with Kailash SDK

## Key Technical Facts (aihub2)

- **Stack**: Next.js 14 (port 3022) + FastAPI (port 8022) + Azure Cosmos DB + Azure AI Search + Redis
- **Auth**: Azure Entra ID SSO + local dev auth (JWT, 8h access / 7d refresh)
- **LLM**: Azure OpenAI ONLY — 4 deployments (GPT-5.2-chat primary `aihub2-main`, GPT-5 Mini intent `intent5`, text-embedding-3-large, gpt-vision). Supports `reasoning_effort` param. Source: `config.py` descriptions + `context_window.py`.
- **MCP Servers**: 9 servers confirmed from `src/mcp-servers/`: Bloomberg, CapIQ, Perplexity, Oracle Fusion, AlphaGeo, Teamworks, PitchBook, Azure AD, iLevel. Bloomberg/Perplexity/Oracle Fusion have their own Azure OpenAI deployments (agentic). Auth: Bloomberg=OAuth2 BSSO, Perplexity=API key, Oracle Fusion=JWT assertion OAuth2, Azure AD=OAuth2 OBO, others=none. Protocol: HTTP REST (FastAPI), NOT WebSocket.
- **RAG Pipeline**: Intent Detection → Parallel Search → Synthesis → Confidence Scoring (2-3s total)
- **RBAC**: 6 system roles, 9 system functions, additive permissions model
- **NO tenant_id**: Zero multi-tenant isolation — all partition keys use user_id

## Critical Gaps for Multi-Tenancy

1. No `tenant_id` anywhere in data models (Cosmos DB containers, search indexes, Redis)
2. LLM config is `@lru_cache` from env vars — cannot change at runtime
3. Only Azure OpenAI implemented — all other providers missing
4. Azure AD configured globally in .env — single org only
5. Search indexes not partitioned per tenant

## Agent Platform Architecture (doc 06 v2.0 — confirmed)

### All 9 MCP Servers = A2A Agents (NOT tool/agent split)

- All 9: natural language Task in → internal LLM → internal MCP tools → Artifact out
- Bloomberg/Perplexity/Oracle Fusion: confirmed own Azure OpenAI deployments (from configs)
- CapIQ/iLevel/AlphaGeo/Teamworks/PitchBook/Azure AD: also A2A agents (LLM reasons about tool calls)
- Previous error: classifying 6 as "MCP Tools" — WRONG, all 9 = A2A Agents

### Tool Catalog (separate from agents — deterministic, no LLM, direct calls)

- Only Tavily exists in aihub2: `INTERNET_SEARCH_TOOL` / `search_internet`
- mingai elevates to governed Tool Catalog + adds Calculator, Weather + extensible

### Credential Model

- Platform defines: credential SCHEMA (type: OBO | JWT assertion | OAuth2 BSSO | API key)
- Tenant provides: credential VALUES (Bloomberg account, Oracle JWT, CapIQ key, etc.)
- User provides at runtime: OBO token (Azure AD only — user's identity auto-delegates)
- Azure AD: OBO means agent acts AS the user in MS Graph (not service account)
- Oracle Fusion: JWT assertion OAuth2 (RFC 7523) — tenant provides JWT private key

### LLM Configuration Model

- **Tenant-level, not per-agent**: LLM selection in Tenant Admin → Settings → LLM Configuration
- **Platform LLM Library**: Platform admin curates approved providers + models per plan tier
- **Tenant picks**: Option A = select from LLM Library (billed at markup); Option B = BYOLLM (Enterprise, tracking only)
- **All agents in tenant share** this single LLM configuration (no per-agent override)
- **Billing**: library LLM → token markup; BYOLLM → observability tracking only
- **Agent template `preferred_tier`**: "reasoning" | "standard" — hints which model tier to use; actual model resolved from tenant's LLM setup at runtime

### Agent Template (5 components — platform builds, tenant configures)

1. prompt (identity, expertise) + 2. guardrails (tenant CANNOT override)
2. mcp_url + 4. credential_schema (VALUES come from tenant) + 5. skills (AgentCard)

### DAG Orchestration

- Orchestrator owns full DAG; agents are task-blind (never see the plan)
- Each agent receives ONE atomic A2A Task (natural language only)
- Independent DAG nodes execute in parallel; artifacts feed synthesis

### Prompt Library = Designed Gap (required before production)

## Architecture Decisions (DB + RAG Analysis — docs 12 + 13)

### Database: Hybrid PostgreSQL + Cosmos DB (adopted Phase 1)

- **12 of 23 containers → PostgreSQL** (relational patterns, M:N joins, structured queries)
- **4 containers stay Cosmos DB**: messages, events, profile_learning_events, notifications (high-volume append-only)
- **PostgreSQL RLS** for categorical tenant isolation (superior to app-layer filtering)
- **pgvector** replaces Python cosine similarity in glossary service
- Cost: 1.4-2x advantage for PostgreSQL (NOT 3x — Azure AI Search cost was misattributed)
- **CRITICAL gap**: Cross-DB transaction atomicity (Cosmos write + PostgreSQL write) has no strategy yet
- Phase 1 timeline: 8 weeks (not 6) to accommodate hybrid migration
- Source: `12-database-architecture-analysis.md`

### RAG Pipeline: Current state + critical gaps

- Chunking: **fixed 1000-token** chunks (DocumentProcessor) + undocumented SemanticChunker (2000 chars)
- Embeddings: dual-model mismatch — ada-002 (1536d, legacy KB) vs text-embedding-3-large (3072d, new). IndexModelDetector handles this correctly at query time — not a bug but operational complexity
- Effective top_k: **9+ across multi-index** (3 indexes × 3 per-index), not the stated 5
- KB relevance pre-filter: `kb_relevance_checker.py` (threshold=0.6, Redis-cached) — not in existing pipeline docs
- Critical gaps to fix: semantic/adaptive chunking, cross-encoder reranking, tenant isolation at index layer
- RAG improvements: 17 weeks estimated (exceeds Phase 4 allocation of 5 weeks — needs re-phasing)
- Source: `13-rag-ingestion-analysis.md`

## Key Product Findings

**Genuine USPs** (product-analyst confirmed):

1. MCP Protocol for custom data source integration (strongest moat)
2. Deep granular RBAC with 9 system functions
3. Agent email communication channels
4. Comprehensive cost analytics per service/index

**Target Buyer**: Azure-committed enterprises with proprietary data sources needing full RAG pipeline control

**80/15/5 Rule**:

- 80% reusable: core chat, RBAC, RAG pipeline, analytics
- 15% configurable: roles, indexes, MCP server selection, LLM selection
- 5% custom: new MCP servers, custom LLM workflows

## Architecture Design Decisions (in progress)

**Admin Hierarchy**:

- Platform Admin: tenant provisioning, LLM provider config, global MCP, billing
- Tenant Admin: SSO config, user management, provider selection/BYOLLM, MCP enable/disable
- Plan tiers: Starter / Professional / Enterprise

**JWT Structure** (multi-tenant):

```json
{ "tenant_id": "uuid", "scope": "tenant|platform", "plan": "professional" }
```

**LLM Providers to support**: Azure OpenAI, OpenAI, Anthropic/Claude, Google Gemini, Deepseek, Alibaba DashScope (Qwen), Bytedance Ark (Doubao)

## Workspace Structure

```
workspaces/mingai/
├── 01-analysis/
│   ├── 01-research/     # 12 technical docs (complete, GPT-5 corrected)
│   ├── 02-product/      # 6 product docs (complete)
│   ├── 03-competitive/  # (covered in 02-product/02)
│   ├── 04-multi-tenant/ # 6 architecture docs (complete)
│   │   ├── 01-admin-hierarchy.md
│   │   ├── 02-data-isolation.md
│   │   ├── 03-auth-sso-strategy.md     (Auth0, multi-SSO)
│   │   ├── 04-llm-provider-management.md (7 providers, BYOLLM)
│   │   ├── 05-cloud-agnostic-deployment.md (4 clouds, 5 abstraction layers)
│   │   └── 06-a2a-mcp-agentic.md       (A2A, agentic RAG, MCP registry)
│   └── 05-red-team/     # 01-critique.md — 3 passes, 12 files corrected, 44KB
├── 02-plans/            # 2 plan docs (complete but need revision — see KNOWN ISSUES)
└── 03-user-flows/       # 4 flow docs (complete)
```

## Known Issues in 02-plans (must fix before implementation)

Red-team pass 2b found critical errors in `02-technical-migration-plan.md`:

1. ~~CRITICAL: Only 9 of 21 Cosmos DB containers covered~~ — FIXED: now 19 PostgreSQL tables documented
2. **HIGH**: RBAC system functions fabricated — actual functions: role:manage, user:manage, etc. (NOT chat/search/analyze)
3. **HIGH**: Role names fabricated — actual: Role Administrator, Index Administrator, etc.
4. ~~MEDIUM: `permissions` container doesn't exist~~ — FIXED: pure PostgreSQL plan eliminates this

`01-implementation-roadmap.md` is sound — phase ordering and approach verified correct.

Items 2 & 3 (fabricated RBAC) fixed in `03-auth-rbac.md`. `02-technical-migration-plan.md` RBAC section still needs review.

**Ground-truth RBAC** (from aihub2 source):

- 7 system roles: `default`, `role_admin`, `index_admin`, `user_admin`, `analytics_viewer`, `audit_viewer`, `admin`
- 9 system functions: `role:manage`, `user:manage`, `index:manage`, `analytics:view`, `audit:view`, `integration:manage`, `glossary:manage`, `feedback:view`, `sync:manage`
- Protected roles (cannot delete): `admin`, `default`
- `admin` has ALL 9 permissions; 4 functions have no dedicated role (integration, glossary, feedback, sync — only via admin)

## Red-Team Top Recommendations (before implementation)

1. Start Azure-only — cloud-agnostic is Phase 5, not Phase 1
2. Budget agentic RAG at 3-8x classical RAG cost
3. Prototype Auth0 before committing as SSO broker
4. Validate pricing model for 100-tenant scale
5. Cosmos DB partition key change = full container recreation (not ALTER TABLE)

## Agent Notes

- Explore agents CANNOT write files — use general-purpose for file creation tasks
- Plans-writer agents are prone to fabricating RBAC/schema details — always verify against source code
- Red-team is the most reliable verifier — always run after document generation
