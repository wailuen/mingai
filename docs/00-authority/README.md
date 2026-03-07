# mingai Authority Documents

Read these first before touching any code. They contain the non-negotiable constraints and architecture decisions.

## Navigation

| Document | What it covers | Read when |
|---|---|---|
| `CLAUDE.md` | Architecture, patterns, gotchas, security gates | Start of every session |
| `../01-database-schema.md` | 44-table multi-tenant schema with RLS | Adding tables, migrations |
| `../02-api-endpoints.md` | All 120 API endpoints with acceptance criteria | Adding/changing endpoints |
| `../03-ai-services.md` | AI pipeline services (RAG, memory, glossary, triage) | Touching AI layer |
| `../04-frontend.md` | Next.js frontend with Obsidian Intelligence design system | All frontend work |
| `../05-testing.md` | 3-tier test strategy, security gates | Writing or running tests |
| `../06-infrastructure.md` | Migrations, infra, DevOps | Schema or infra changes |
| `../07-gap-analysis.md` | Known gaps and risk items | Before shipping a feature |

## Blocking Security Gates (ship-stoppers)

These MUST pass before the feature ships. No exceptions.

| Gate | Test | Blocks |
|---|---|---|
| RLS cross-tenant isolation | TEST-002, TEST-003 | Everything |
| JWT v2 auth | TEST-001 | All endpoints |
| Screenshot blur | TEST-015 | Issue reporting |
| GDPR erasure (working memory) | TEST-054 | EU tenants |
| Cache key isolation | TEST-009 | All caching |
| Glossary injection sanitization | TEST-030 | Glossary feature |
