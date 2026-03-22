# TODO-13: Agent Studio Phase 1 — DB Schema Foundation

**Status**: ACTIVE
**Priority**: HIGH — all subsequent agent studio todos depend on this
**Estimated Effort**: 3 days
**Phase**: Phase 1 — Foundation (must complete before any other agent studio todo)

---

## Description

Create the complete database schema for the three-tier Agent Studio capability hierarchy: Tool Catalog (Tier 1), Skills Library (Tier 2), and extended Agent Templates (Tier 3). This is the prerequisite for all other agent studio work. No frontend changes in this todo — pure backend schema, migrations, and seed data.

The existing `agent_cards` table covers basic agent instances but lacks the new entity types (tools, skills, platform templates with full 7 dimensions). This todo adds those tables and extends existing ones without breaking current functionality.

---

## Acceptance Criteria

- [ ] Alembic migration `v047_tool_catalog.py` creates `tools` table with all required columns
- [ ] Alembic migration `v048_skills_library.py` creates `skills` and `skill_versions` tables
- [ ] Alembic migration `v049_agent_template_extensions.py` extends `agent_cards` with `llm_policy`, `kb_policy`, `attached_skills`, `attached_tools`, `a2a_interface`, `template_type` columns
- [ ] Alembic migration `v050_agent_template_versions.py` creates `agent_template_versions` table
- [ ] Alembic migration `v051_tenant_skill_adoptions.py` creates `tenant_skill_adoptions` join table
- [ ] Alembic migration `v052_tenant_mcp_servers.py` creates `tenant_mcp_servers` table
- [ ] All migrations run clean against fresh DB and against DB with existing data (4 seed templates survive)
- [ ] `alembic downgrade` works for every migration (reversible)
- [ ] Seed data script populates 11 built-in platform skills (from conceptual model)
- [ ] Seed data script populates built-in tools (web_search, document_ocr, calculator, data_formatter, file_reader)
- [ ] All new tables have correct indexes on FK columns and common query columns
- [ ] All JSONB columns have GIN indexes where appropriate
- [ ] Row-level security (RLS): tools with `scope = tenant_id` are only readable by that tenant
- [ ] Unit tests cover migration up/down cycle

---

## Backend Changes

### Migration v047: Tool Catalog

File: `src/backend/app/db/migrations/versions/v047_tool_catalog.py`

```sql
CREATE TABLE tools (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    input_schema    JSONB NOT NULL DEFAULT '{}',
    output_schema   JSONB NOT NULL DEFAULT '{}',
    executor        VARCHAR(32) NOT NULL CHECK (executor IN ('builtin', 'http_wrapper', 'mcp_sse')),
    endpoint_url    TEXT,
    credential_schema JSONB NOT NULL DEFAULT '[]',
    credential_source VARCHAR(32) NOT NULL DEFAULT 'none'
                    CHECK (credential_source IN ('none', 'platform_managed', 'tenant_managed')),
    rate_limit      JSONB NOT NULL DEFAULT '{"requests_per_minute": 60}',
    plan_required   VARCHAR(32) CHECK (plan_required IN ('starter', 'professional', 'enterprise')),
    scope           VARCHAR(255) NOT NULL DEFAULT 'platform',
    -- scope = 'platform' for PA-created tools, scope = tenant_id UUID for tenant private tools
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      UUID  -- NULL for seeded/built-in tools
);

CREATE INDEX idx_tools_scope ON tools(scope);
CREATE INDEX idx_tools_executor ON tools(executor);
CREATE INDEX idx_tools_is_active ON tools(is_active);
CREATE INDEX idx_tools_credential_schema ON tools USING GIN(credential_schema);
```

### Migration v048: Skills Library

File: `src/backend/app/db/migrations/versions/v048_skills_library.py`

```sql
CREATE TABLE skills (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                VARCHAR(255) NOT NULL,
    description         TEXT,
    category            VARCHAR(100),
    version             VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    changelog           TEXT,
    input_schema        JSONB NOT NULL DEFAULT '{}',
    output_schema       JSONB NOT NULL DEFAULT '{}',
    prompt_template     TEXT,
    execution_pattern   VARCHAR(32) NOT NULL DEFAULT 'prompt'
                        CHECK (execution_pattern IN ('prompt', 'tool_composing', 'sequential_pipeline')),
    tool_dependencies   JSONB NOT NULL DEFAULT '[]',
    pipeline_steps      JSONB,  -- NULL unless execution_pattern = 'sequential_pipeline'
    invocation_mode     VARCHAR(32) NOT NULL DEFAULT 'llm_invoked'
                        CHECK (invocation_mode IN ('llm_invoked', 'pipeline')),
    pipeline_trigger    TEXT,  -- NULL unless invocation_mode = 'pipeline'
    llm_config          JSONB NOT NULL DEFAULT '{"temperature": 0.3, "max_tokens": 2000}',
    plan_required       VARCHAR(32) CHECK (plan_required IN ('starter', 'professional', 'enterprise')),
    scope               VARCHAR(255) NOT NULL DEFAULT 'platform',
    -- scope = 'platform' for PA-authored, scope = tenant_id for tenant-authored
    mandatory           BOOLEAN NOT NULL DEFAULT FALSE,
    status              VARCHAR(32) NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'published', 'deprecated')),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at        TIMESTAMPTZ,
    created_by          UUID
);

CREATE INDEX idx_skills_scope ON skills(scope);
CREATE INDEX idx_skills_status ON skills(status);
CREATE INDEX idx_skills_category ON skills(category);
CREATE INDEX idx_skills_mandatory ON skills(mandatory);
CREATE INDEX idx_skills_tool_dependencies ON skills USING GIN(tool_dependencies);

CREATE TABLE skill_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_id        UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    version_label   VARCHAR(20) NOT NULL,
    change_type     VARCHAR(10) NOT NULL CHECK (change_type IN ('initial', 'patch', 'minor', 'major')),
    changelog       TEXT NOT NULL,
    published_by    UUID NOT NULL,
    published_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snapshot        JSONB  -- full skill snapshot at publish time
);

CREATE INDEX idx_skill_versions_skill_id ON skill_versions(skill_id);
CREATE INDEX idx_skill_versions_published_at ON skill_versions(published_at DESC);
```

### Migration v049: Agent Template Extensions

File: `src/backend/app/db/migrations/versions/v049_agent_template_extensions.py`

Extends existing `agent_cards` table. Safe defaults maintain backward compatibility with 4 seed templates.

```sql
ALTER TABLE agent_cards
    ADD COLUMN IF NOT EXISTS template_type VARCHAR(32) NOT NULL DEFAULT 'rag'
        CHECK (template_type IN ('rag', 'skill_augmented', 'tool_augmented', 'credentialed', 'registered_a2a')),
    ADD COLUMN IF NOT EXISTS llm_policy JSONB NOT NULL DEFAULT
        '{"tenant_can_override": true, "defaults": {"temperature": 0.3, "max_tokens": 2000}}',
    ADD COLUMN IF NOT EXISTS kb_policy JSONB NOT NULL DEFAULT
        '{"ownership": "tenant_managed", "recommended_categories": [], "required_kb_ids": []}',
    ADD COLUMN IF NOT EXISTS attached_skills JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS attached_tools JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS a2a_interface JSONB NOT NULL DEFAULT
        '{"a2a_enabled": false, "operations": [], "auth_required": false}',
    ADD COLUMN IF NOT EXISTS source_card_url TEXT,  -- registered_a2a only
    ADD COLUMN IF NOT EXISTS imported_card JSONB;   -- registered_a2a only

CREATE INDEX idx_agent_cards_template_type ON agent_cards(template_type);
CREATE INDEX idx_agent_cards_attached_skills ON agent_cards USING GIN(attached_skills);
CREATE INDEX idx_agent_cards_attached_tools ON agent_cards USING GIN(attached_tools);
```

### Migration v050: Agent Template Versions

File: `src/backend/app/db/migrations/versions/v050_agent_template_versions.py`

```sql
CREATE TABLE agent_template_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id     UUID NOT NULL REFERENCES agent_cards(id) ON DELETE CASCADE,
    version_label   VARCHAR(20) NOT NULL,
    change_type     VARCHAR(10) NOT NULL CHECK (change_type IN ('initial', 'patch', 'minor', 'major')),
    changelog       TEXT NOT NULL,
    published_by    UUID NOT NULL,
    published_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snapshot        JSONB  -- full template snapshot at publish time (for diff/rollback)
);

CREATE INDEX idx_atv_template_id ON agent_template_versions(template_id);
CREATE INDEX idx_atv_published_at ON agent_template_versions(published_at DESC);
COMMENT ON TABLE agent_template_versions IS
    'Immutable changelog of every published version of a platform agent template.
     Tenants can pin their deployed instance to any version in this table.';
```

### Migration v051: Tenant Skill Adoptions

File: `src/backend/app/db/migrations/versions/v051_tenant_skill_adoptions.py`

```sql
CREATE TABLE tenant_skill_adoptions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    skill_id        UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    pinned_version  VARCHAR(20),  -- NULL = always latest; set = pinned to this version
    adopted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    adopted_by      UUID NOT NULL,
    UNIQUE (tenant_id, skill_id)
);

CREATE INDEX idx_tsa_tenant_id ON tenant_skill_adoptions(tenant_id);
CREATE INDEX idx_tsa_skill_id ON tenant_skill_adoptions(skill_id);
```

### Migration v052: Tenant MCP Servers

File: `src/backend/app/db/migrations/versions/v052_tenant_mcp_servers.py`

```sql
CREATE TABLE tenant_mcp_servers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    endpoint_url    TEXT NOT NULL,
    transport       VARCHAR(32) NOT NULL DEFAULT 'sse'
                    CHECK (transport IN ('sse', 'streamable_http')),
    auth_type       VARCHAR(32) NOT NULL DEFAULT 'none'
                    CHECK (auth_type IN ('none', 'bearer', 'api_key', 'oauth2')),
    auth_config     JSONB NOT NULL DEFAULT '{}',
    -- auth_config stores: header_name, token_env_var_ref (vault key), etc. NOT the token itself.
    status          VARCHAR(32) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'verified', 'error', 'inactive')),
    last_verified_at TIMESTAMPTZ,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      UUID NOT NULL,
    UNIQUE (tenant_id, name)
);

CREATE INDEX idx_tenant_mcp_tenant_id ON tenant_mcp_servers(tenant_id);
CREATE INDEX idx_tenant_mcp_status ON tenant_mcp_servers(status);
```

### Seed Data Module

File: `src/backend/app/core/seeds_agent_studio.py`

Populate:
- 5 built-in tools: `web_search`, `document_ocr`, `calculator`, `data_formatter`, `file_reader` (executor=`builtin`, scope=`platform`, credential_source=`none`, no plan gate)
- 11 platform built-in skills: Summarization, Entity Extraction, Sentiment Analysis, Document Q&A, Comparison, Citation Formatter, Translation, Risk Assessment, Market Research, Financial Summary, Company Intelligence (see conceptual model for exact definitions)
- Market Research skill: tool_dependencies includes `web_search` tool ref
- Financial Summary skill: tool_dependencies includes `calculator` tool ref
- Company Intelligence skill: tool_dependencies includes `web_search` (PitchBook not seeded — requires PA MCP integration)
- All seeded skills: scope=`platform`, status=`published`, mandatory=`false`

---

## Dependencies

- No other agent studio todos block this one
- Plan 14 (Agent Template A2A Compliance) may be in parallel — no conflict expected; these migrations are additive

---

## Testing Requirements

- [ ] Unit test: `test_v047_migration_up_down` — verify tools table creation and reversal
- [ ] Unit test: `test_v048_migration_up_down` — verify skills and skill_versions
- [ ] Unit test: `test_v049_migration_existing_data` — verify 4 seed templates survive with safe defaults
- [ ] Unit test: `test_seed_agent_studio` — verify all 5 tools and 11 skills seeded correctly
- [ ] Integration test: `test_tools_scope_isolation` — tenant-scoped tool not visible to other tenants
- [ ] Integration test: `test_skill_adoption_unique_constraint` — duplicate adoption returns 409

---

## Definition of Done

- [ ] All 6 migrations apply cleanly (`alembic upgrade head`)
- [ ] All migrations reverse cleanly (`alembic downgrade -1` for each)
- [ ] 4 seed templates untouched after v049 (verified via SELECT query in test)
- [ ] 16 seed records (5 tools + 11 skills) present after seed run
- [ ] All acceptance criteria checked
- [ ] No stubs or placeholder implementations

---

## Gap Patches Applied

### Gap 1: Corrected migration numbering and explicit table DDL

The gap analysis identified that the original todo used a different migration numbering scheme and column naming convention from the canonical target schema. The following clarifications are canonical and override the earlier DDL where they differ:

**v047: `tool_catalog` table (canonical DDL)**

The `tools` table defined above is the correct implementation target. Column name `executor` maps to `executor_type` in API responses for clarity. The `rate_limit` JSONB column must expose `rate_limit_rpm` as its top-level integer key for uniform consumption by the Tool Executor. The `health_status` column (`unknown` default) and `created_by UUID REFERENCES users(id)` foreign key must be present — both were missing from the original spec.

Ensure migration v047 creates the `tool_catalog` table with these columns present:
- `executor_type VARCHAR(20) NOT NULL CHECK (executor_type IN ('builtin','http_wrapper','mcp_sse'))` — use this name (not `executor`) in the physical table
- `rate_limit_rpm INT NOT NULL DEFAULT 60` — flat integer, not JSONB
- `health_status VARCHAR(20) NOT NULL DEFAULT 'unknown'`
- `created_by UUID REFERENCES users(id)` — nullable (built-in tools have no creator)

**v048: `skills` and `skill_versions` tables (join-table DDL)**

The original migration stores `tool_dependencies` as a JSONB array inside the `skills` row. The canonical design uses explicit join tables for relational integrity. Migration v048 must also create:

```sql
CREATE TABLE skill_tool_dependencies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  skill_id UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
  tool_id UUID NOT NULL REFERENCES tool_catalog(id) ON DELETE CASCADE,
  required BOOLEAN NOT NULL DEFAULT true,
  UNIQUE(skill_id, tool_id)
);
```

The JSONB `tool_dependencies` column on `skills` should remain for fast read access (denormalised cache), but `skill_tool_dependencies` is the authoritative source. Both must be kept in sync on write.

**v049: Additional join tables**

Beyond the `agent_template_extensions` ALTER TABLE, migration v049 must also create:

```sql
CREATE TABLE tenant_skills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  skill_id UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
  pinned_version VARCHAR(20),
  adopted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(tenant_id, skill_id)
);

CREATE TABLE agent_template_skills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  template_id UUID NOT NULL REFERENCES agent_cards(id) ON DELETE CASCADE,
  skill_id UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
  pinned_version VARCHAR(20),
  invocation_override JSONB,
  UNIQUE(template_id, skill_id)
);

CREATE TABLE agent_template_tools (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  template_id UUID NOT NULL REFERENCES agent_cards(id) ON DELETE CASCADE,
  tool_id UUID NOT NULL REFERENCES tool_catalog(id) ON DELETE CASCADE,
  UNIQUE(template_id, tool_id)
);
```

Note: `tenant_skill_adoptions` (v051 in original) and `tenant_skills` above are the same concept. Use `tenant_skills` as the canonical table name. Update the v051 migration file name to `v051_tenant_skills.py` and create the table as `tenant_skills`.

**v050: Seed data migration**

Migration v050 is a data migration (not schema). It must insert:
- 6 built-in tools: `web_search`, `document_ocr`, `calculator`, `data_formatter`, `file_reader`, `text_translator` (note: `text_translator` was missing from the original seed list; it is required)
- 11 platform skills: Summarization, Entity Extraction, Sentiment Analysis, Document Q&A, Comparison, Citation Formatter, Translation, Risk Assessment, Market Research (tool dep: web_search), Financial Summary (tool dep: calculator), Company Intelligence (tool dep: web_search)
- Each skill: `status='published'`, `mandatory=false`, `scope='platform'`
- Insert corresponding `skill_tool_dependencies` rows for Market Research, Financial Summary, Company Intelligence

**v051: `mcp_integration_imports` table**

Add this new table in migration v051 (alongside `tenant_skills`):

```sql
CREATE TABLE mcp_integration_imports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id),  -- NULL = platform-level import
  source_type VARCHAR(20) NOT NULL CHECK (source_type IN ('openapi', 'postman', 'raw_text')),
  source_filename TEXT,
  source_url TEXT,
  parsed_endpoints JSONB,
  selected_endpoints JSONB,
  generated_tool_ids UUID[],
  imported_by UUID REFERENCES users(id),
  imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_mcp_imports_tenant_id ON mcp_integration_imports(tenant_id);
CREATE INDEX idx_mcp_imports_imported_at ON mcp_integration_imports(imported_at DESC);
```

This table records every PA MCP Integration Builder import session (TODO-22) and is created here so the PA module has a stable schema from the start.

---

### Gap 6: Row-level security for tenant skill isolation

Add to the security section of the DB schema implementation:

**RLS policy on `skills` table:**

```sql
-- Enable RLS
ALTER TABLE skills ENABLE ROW LEVEL SECURITY;

-- Platform-scoped skills: visible to all authenticated users
CREATE POLICY skills_platform_read ON skills
  FOR SELECT
  USING (scope = 'platform');

-- Tenant-scoped skills: visible only to users whose tenant_id matches scope
CREATE POLICY skills_tenant_read ON skills
  FOR SELECT
  USING (scope = current_setting('app.current_tenant_id', true));

-- Write policies: platform skills writable by platform admins only (role check done at API layer)
-- Tenant skills writable by that tenant's admin only (enforced by scope + API layer)
```

API-layer enforcement (in addition to RLS):
- `GET /skills` query: always WHERE `scope = 'platform' OR scope = :tenant_id`
- Never return `scope` values from other tenants in API responses
- Test: tenant A cannot see tenant B's `scope=tenant_B_id` skills even if RLS is misconfigured (belt-and-suspenders)

Add to Testing Requirements:
- [ ] Integration test: `GET /skills` for tenant A does not include skills with `scope = tenant_B_id`
- [ ] Integration test: direct DB query as tenant A role returns zero rows for tenant B skills (RLS enforced at DB level)

---

### Gap 8: Built-in tool implementations and platform skill seed data

Add explicit implementation tasks to the Backend Changes section:

**Seed Task 1: Built-in tool implementations**

Create `src/backend/app/modules/tools/builtins/` package with one file per built-in tool:

- `web_search.py` — wraps the existing web search capability already used in RAG pipeline; input: `{ query: str, max_results: int = 5 }`; output: `{ results: list[{ title, url, snippet }] }`
- `calculator.py` — evaluates mathematical expressions safely; MUST use Python `ast` module to parse expression tree and evaluate only numeric literals and arithmetic operators (`+`, `-`, `*`, `/`, `**`, `%`); MUST NOT use `eval()` or `exec()`; input: `{ expression: str }`; output: `{ result: float, expression_parsed: str }`
- `document_ocr.py` — extracts text from PDF or image files by URL; wraps the OCR service already used in document ingestion; input: `{ document_url: str, page_range: str | None }`; output: `{ text: str, page_count: int }`
- `data_formatter.py` — normalises structured data between formats; input: `{ data: any, input_format: str, output_format: str }`; supported formats: `json`, `csv`, `markdown_table`; output: `{ formatted: str }`
- `file_reader.py` — reads text content from an uploaded file URL (must be within tenant's storage scope); input: `{ file_url: str }`; output: `{ content: str, char_count: int }`
- `text_translator.py` — translates text; if `TRANSLATION_API_KEY` env var is set, calls translation API; otherwise falls back to LLM-based translation; input: `{ text: str, target_language: str, source_language: str | None }`; output: `{ translated: str, detected_source_language: str | None }`

Each builtin module must export a single async function matching the tool's `name` field in the seed data. The `BuiltinExecutor` in `tool_executor.py` dispatches to these by name via `REGISTRY = { "web_search": web_search, ... }`.

**Seed Task 2: Platform skill prompt templates**

The v050 seed migration must include carefully crafted prompt templates for each of the 11 platform skills. Templates must:
- Use `{{input.field_name}}` syntax for variable substitution
- Be free of injection patterns (validated by SystemPromptValidator before insertion)
- Fit within the 3000-character skill prompt limit
- Have correct `input_schema` and `output_schema` defined

Minimum prompt template quality bar per skill:
- Summarization: summarise `{{input.text}}` to `{{input.max_sentences}}` sentences
- Entity Extraction: extract named entities (persons, orgs, locations, dates) from `{{input.text}}`
- Sentiment Analysis: classify sentiment of `{{input.text}}` as positive/negative/neutral with confidence
- Document Q&A: answer `{{input.question}}` using only the provided `{{input.context}}`
- Comparison: compare `{{input.item_a}}` and `{{input.item_b}}` across `{{input.dimensions}}`
- Citation Formatter: format `{{input.citation_data}}` in `{{input.citation_style}}` style
- Translation: translate `{{input.text}}` from `{{input.source_language}}` to `{{input.target_language}}`
- Risk Assessment: identify key risks in `{{input.scenario}}` and rate likelihood/impact
- Market Research: research `{{input.topic}}` using web search; return structured market overview
- Financial Summary: calculate `{{input.expression}}` and summarise `{{input.financial_data}}`
- Company Intelligence: research `{{input.company_name}}` and return structured intelligence brief

Add to Definition of Done:
- [ ] All 6 built-in tool implementations present in `builtins/` package with no `eval()` usage
- [ ] `text_translator` present (was missing from original seed count — 6 tools not 5)
- [ ] All 11 platform skill prompt templates pass SystemPromptValidator
- [ ] `skill_tool_dependencies` rows inserted correctly for the 3 tool-dependent skills
