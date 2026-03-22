# TODO-22: Agent Studio Phase 2 — PA MCP Integration Builder

**Status**: ACTIVE
**Priority**: MEDIUM (Phase 2)
**Estimated Effort**: 4 days
**Phase**: Phase 2 — Platform Admin Authoring Studio

---

## Description

Platform admins build MCP integrations from API documentation. The workflow: PA uploads an OpenAPI spec, Postman collection, or raw API docs → platform parses the API and presents an endpoint list → PA selects endpoints to expose as tools, names them, writes descriptions, defines credential schema, sets rate limits and plan gates → platform registers thin HTTP wrapper tools in the Tool Executor. These tools then appear in the platform tool catalog for use in skills and agent templates.

This is the PA-side companion to TODO-17 (TA MCP server registration). The key difference: PAs build tools FROM API docs (they define what tools exist); TAs register existing MCP servers (tools are enumerated from the server's own manifest).

---

## Acceptance Criteria

- [ ] PA navigates to Platform > Tool Catalog > [+ New Integration] and gets the MCP Integration Builder
- [ ] Step 1: PA uploads API doc (OpenAPI JSON, OpenAPI YAML, Postman Collection JSON) or pastes raw text documentation
- [ ] Platform parses uploaded doc and presents an endpoint list: HTTP method, path, summary
- [ ] PA selects which endpoints to turn into tools (multi-select checkboxes)
- [ ] For each selected endpoint: PA provides tool name (auto-suggested from endpoint path), description, rate limit, plan gate
- [ ] Platform generates input/output schema from OpenAPI parameter/response definitions (or leaves blank for raw docs)
- [ ] PA defines credential schema: what tenant must provide at deployment (e.g., API key, OAuth token)
- [ ] PA sets credential source: `platform_managed` (PA stores credentials) or `tenant_managed` (tenant provides at deployment)
- [ ] PA can preview generated tool records before confirming
- [ ] Confirm registers all tools into the `tools` table as `executor='http_wrapper'`, `scope='platform'`
- [ ] Registered tools appear in platform tool catalog immediately
- [ ] PA can edit individual tool records after creation (name, description, input/output schema, rate limit, plan gate)
- [ ] PA can deactivate a tool (sets `is_active=false`; agents using it show warning)
- [ ] PA can test a tool: enter credential values + input values, execute HTTP call, see raw response

---

## Backend Changes

### API Doc Parser

File: `src/backend/app/modules/agents/api_doc_parser.py`

```python
class APIDocParser:

    def parse(self, content: str, format_hint: str) -> ParsedAPIDoc:
        """
        Auto-detect format if format_hint='auto'.
        Supported: OpenAPI 3.x JSON, OpenAPI 3.x YAML, Swagger 2.x JSON/YAML, Postman Collection v2.1
        Returns: ParsedAPIDoc(
            format: str,
            title: str,
            base_url: str,
            endpoints: list[ParsedEndpoint]
        )
        ParsedEndpoint: method, path, summary, description, parameters, request_body_schema, response_schema
        """

    def _parse_openapi(self, doc: dict) -> list[ParsedEndpoint]: ...
    def _parse_postman(self, collection: dict) -> list[ParsedEndpoint]: ...
    def _parse_raw_text(self, text: str) -> list[ParsedEndpoint]:
        """
        LLM-assisted parsing for unstructured docs.
        Use platform LLM to extract: endpoint method + path + description + parameters.
        Cap: 50 endpoints extracted. Warn if doc > 100KB.
        """
```

### Tool Generation from Endpoints

File: `src/backend/app/modules/agents/tool_generator.py`

```python
def generate_tool_record(
    endpoint: ParsedEndpoint,
    tool_name: str,
    description: str,
    base_url: str,
    credential_schema: list[dict],
    credential_source: str,
    rate_limit: dict,
    plan_required: str | None
) -> dict:
    """
    Generate a tool record dict ready for INSERT into tools table.
    executor = 'http_wrapper'
    endpoint_url = f"{base_url}{endpoint.path}"
    input_schema = JSON Schema derived from endpoint.parameters + request_body_schema
    output_schema = JSON Schema derived from endpoint.response_schema
    """
```

### New Platform Tool Management Endpoints

File: `src/backend/app/modules/agents/platform_tools_routes.py`

```python
# MCP Integration Builder
POST /platform/integrations/parse        # Upload/paste API doc; returns parsed endpoint list
POST /platform/integrations/register     # Register selected endpoints as tools
GET  /platform/integrations              # List MCP integrations (grouped by API doc source)
DELETE /platform/integrations/{id}       # Delete integration + all associated tools (if no agents using them)

# Platform tool management
GET    /platform/tools                   # List all platform tools
GET    /platform/tools/{id}              # Tool detail + usage stats
PUT    /platform/tools/{id}              # Edit tool name, description, schema, rate limit, plan gate
PATCH  /platform/tools/{id}/status      # Activate/deactivate
POST   /platform/tools/{id}/test         # Test tool execution with provided credentials + input

# Built-in tools (read-only — can only be toggled active/inactive)
GET    /platform/tools/builtins          # List built-in tools
PATCH  /platform/tools/{id}/plan         # Change plan gate on any tool
```

### Tool Test Execution (PA)

`POST /platform/tools/{id}/test`:
- PA provides `credentials` dict + `input_values` dict
- Backend resolves tool record → dispatches via `ToolExecutor`
- Returns raw response, status code, latency
- Does NOT write credentials to any log
- Does NOT persist provided credentials (test-only; PA must provide manually each time)

### Integration Record

New table (migration v054): `platform_integrations`
```sql
CREATE TABLE platform_integrations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    source_format   VARCHAR(32) NOT NULL,  -- 'openapi', 'postman', 'raw_text'
    base_url        TEXT NOT NULL,
    created_by      UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

ALTER TABLE tools
    ADD COLUMN IF NOT EXISTS integration_id UUID REFERENCES platform_integrations(id);
CREATE INDEX idx_tools_integration_id ON tools(integration_id);
```

---

## Frontend Changes

### Entry Point

Add [+ New Integration] button to PA Tool Catalog page (TODO-23). Opens `MCPIntegrationBuilderWizard`.

### New Components

#### `MCPIntegrationBuilderWizard.tsx`

Location: `src/web/app/(platform)/platform/tool-catalog/elements/MCPIntegrationBuilderWizard.tsx`

- Full-screen overlay wizard (not a modal — complex enough to warrant full screen)
- 4 steps: Upload, Select Endpoints, Configure Tools, Review + Confirm
- Progress bar at top

**Step 1 — Upload API Doc:**
- File upload drop zone: accepts `.json`, `.yaml`, `.yml`; max 5MB
- OR "Paste documentation" textarea: for raw text docs
- OR URL input: "Fetch from URL" (fetches OpenAPI spec from public URL; validates HTTPS)
- Format auto-detected; PA can override format hint dropdown
- [Parse] button → calls `POST /platform/integrations/parse`
- Parsing spinner with "Analyzing API documentation..."

**Step 2 — Select Endpoints:**
- Table: checkbox, Method badge (GET/POST/PUT/DELETE in different bg-elevated shades), Path, Summary
- Group by tag if OpenAPI has tags
- Select All / Deselect All
- Filter by method type chips
- "N endpoints selected" count

**Step 3 — Configure Tools:**
- Accordion list of selected endpoints; each expandable
- Per tool: tool name input (pre-filled from auto-suggestion), description textarea
- Rate limit input (default: 60/min)
- Plan gate dropdown
- Input/output schema: read-only display of auto-generated JSON Schema; [Edit Schema] button opens JSON editor
- Credential Schema section: [+ Add Credential Field] table (same `CredentialSchemaEditor` from TODO-20)
- Credential source radio: Platform-managed / Tenant-managed

**Step 4 — Review + Confirm:**
- Summary table: tool name, endpoint, rate limit, plan gate, credential count
- Total: "N tools will be registered"
- [Register Tools] button (accent)

#### `PlatformToolEditPanel.tsx`

Location: `src/web/app/(platform)/platform/tool-catalog/elements/PlatformToolEditPanel.tsx`

- 480px slide-in from right
- Edit: name, description, input_schema (JSON editor), output_schema (JSON editor), rate_limit, plan_required
- [Test Tool] section: credential inputs (from credential_schema) + input_values form + [Execute] button
- Test result: raw JSON response, HTTP status, latency

### New Hooks

File: `src/web/hooks/usePlatformIntegrations.ts`

```typescript
parseAPIDoc(content: string | File, formatHint?: string)  → mutation → { endpoints }
registerIntegration(name, description, baseUrl, tools)     → mutation
usePlatformIntegrations()                                  → { integrations, isLoading }
deleteIntegration(id)                                      → mutation
updatePlatformTool(id, data)                               → mutation
testPlatformTool(id, credentials, inputValues)             → mutation → TestResult
```

---

## Dependencies

- TODO-13 (DB schema) — tools table
- TODO-20 (PA Template Studio) — CredentialSchemaEditor reused
- TODO-23 (PA Tool Catalog) — entry point for builder; tools registered here appear there

---

## Risk Assessment

- **HIGH**: SSRF in "Fetch from URL" — must validate HTTPS, block internal IP ranges, same protection as A2A card fetcher (TODO-19)
- **HIGH**: LLM-assisted parsing of raw text docs — LLM may extract incorrect endpoints; always require PA confirmation; never auto-register without review
- **MEDIUM**: Generated JSON Schema accuracy — OpenAPI parsing may miss nested objects or optional fields; provide [Edit Schema] escape hatch always
- **LOW**: Large API docs — cap at 5MB upload, 50 endpoints per integration; show warning if near limits

---

## Testing Requirements

- [ ] Unit test: `APIDocParser.parse` correctly parses PetStore OpenAPI 3.0 sample
- [ ] Unit test: `APIDocParser.parse` handles missing `summary` fields gracefully
- [ ] Unit test: URL fetch blocks internal IP ranges (SSRF)
- [ ] Unit test: `generate_tool_record` produces valid `executor='http_wrapper'` record with correct schemas
- [ ] Unit test: tool test does NOT log credential values
- [ ] Integration test: full builder flow — upload → select → configure → register → tools appear in catalog
- [ ] E2E test: PA uses builder to create PitchBook integration; TA sees tools in tool selector

---

## Definition of Done

- [ ] API doc parser handles OpenAPI 3.x, Swagger 2.x, Postman v2.1, and raw text (LLM-assisted)
- [ ] Builder wizard all 4 steps functional
- [ ] SSRF protection in URL fetcher
- [ ] CredentialSchemaEditor wired correctly
- [ ] Registered tools appear in platform tool catalog
- [ ] Tool edit and test panels functional
- [ ] All acceptance criteria met
