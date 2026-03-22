# TODO-17: Agent Studio Phase 1 — TA MCP Server Registration + Tool Catalog

**Status**: ACTIVE
**Priority**: MEDIUM
**Estimated Effort**: 3 days
**Phase**: Phase 1 — Tenant Admin Surfaces

---

## Description

Tenant admins can register their own private MCP servers, verify connectivity, and browse the resulting tenant-scoped tools. They can also browse platform-level tools from the platform tool catalog. All registered tools become available for attachment to tenant skills and custom agents.

This todo builds the TA-facing tool surface. It does NOT include the PA MCP Integration Builder (uploading API docs to generate tools) — that is TODO-22. The TA surface is simpler: register an existing MCP server endpoint and let the platform enumerate its tools via the MCP protocol.

---

## Acceptance Criteria

- [ ] TA navigates to Workspace > Tools and sees two tabs: "Platform Tools" and "My Tools"
- [ ] Platform Tools tab: read-only list of platform-scoped tools (built-ins + PA-created MCP tools) with name, description, executor type badge, plan gate badge, `credential_source` indicator
- [ ] Platform tools that require tenant-managed credentials show a "Requires credentials at agent deployment" note
- [ ] My Tools tab: list of tenant-registered MCP servers with their enumerated tools; [+ Register MCP Server] button
- [ ] TA registers a new MCP server: name, description, endpoint URL, transport type (SSE / Streamable HTTP), auth type (none / bearer / api_key), auth credential (stored in vault)
- [ ] Platform validates MCP server connectivity on save: attempts MCP `list_tools` handshake within 10s timeout
- [ ] On successful verification: server status = `verified`; tools enumerated and stored as tenant-scoped tool records
- [ ] On failed verification: server status = `error`; error message shown; TA can retry
- [ ] Verified server shows list of enumerated tools (name, description, input schema from MCP manifest)
- [ ] TA can manually re-verify any server ([Re-verify] button)
- [ ] TA can deactivate/delete a server (tools become unavailable to agents; agents using them show warning)
- [ ] Tenant MCP server tools appear in skill tool selector (TODO-16) and custom agent tool selector (TODO-18)
- [ ] Tool usage count shown per tool (how many agents/skills reference it)

---

## Backend Changes

### New Module: mcp_client.py

File: `src/backend/app/modules/agents/mcp_client.py`

```python
class MCPClient:
    """Thin async MCP client for server verification and tool enumeration."""

    async def verify_and_enumerate(
        self,
        endpoint_url: str,
        transport: str,  # 'sse' | 'streamable_http'
        auth_config: dict,  # resolved from vault at call time
        timeout: float = 10.0
    ) -> MCPVerifyResult:
        """
        1. Connect to MCP server endpoint with appropriate transport
        2. Send MCP initialize + list_tools request
        3. Parse tool manifest: extract name, description, inputSchema per tool
        4. Return MCPVerifyResult(
               success: bool,
               tools: list[MCPToolManifest],
               error: str | None,
               latency_ms: int
           )
        Never log auth tokens or credentials.
        """

    async def call_tool(
        self,
        endpoint_url: str,
        transport: str,
        auth_config: dict,
        tool_name: str,
        arguments: dict,
        timeout: float = 30.0
    ) -> MCPToolResult:
        """
        Execute a tool call via MCP protocol.
        Called by Tool Executor at agent query time with injected credentials.
        """
```

### New Route Module: tenant_tools_routes.py

File: `src/backend/app/modules/agents/tenant_tools_routes.py`

```python
# Platform tools (read-only for TAs)
GET  /tools                            # List platform tools (executor=builtin or http_wrapper, scope=platform)
GET  /tools/{tool_id}                  # Platform tool detail + usage stats

# Tenant MCP servers
GET  /admin/mcp-servers               # List tenant MCP servers
POST /admin/mcp-servers               # Register new MCP server
GET  /admin/mcp-servers/{server_id}   # Server detail + enumerated tools
PUT  /admin/mcp-servers/{server_id}   # Update server config (triggers re-verification)
DELETE /admin/mcp-servers/{server_id} # Delete server (warns if tools in use)
POST /admin/mcp-servers/{server_id}/verify  # Manual re-verification

# Tenant tools (auto-created from MCP enumeration — read-only to TA)
GET  /admin/tools                     # List tenant-scoped tools (from verified MCP servers)
GET  /admin/tools/{tool_id}           # Tool detail + usage (agents/skills using it)
```

### Request Schemas

```python
class RegisterMCPServerRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    endpoint_url: HttpUrl
    transport: Literal["sse", "streamable_http"] = "sse"
    auth_type: Literal["none", "bearer", "api_key"] = "none"
    auth_token: Optional[str] = None  # stored in vault; NEVER persisted to DB plaintext
    auth_header_name: Optional[str] = None  # for api_key auth
```

### MCP Server Registration Flow

POST /admin/mcp-servers handler:

1. Validate `endpoint_url` scheme is https (or http for localhost dev)
2. If `auth_token` provided: store in vault at `{tenant_id}/mcp-servers/{server_id}/auth_token`; store vault key reference (not token) in `tenant_mcp_servers.auth_config`
3. Set status = `pending`, INSERT server record
4. Launch async background task: call `mcp_client.verify_and_enumerate()`
5. On success: UPDATE status = `verified`, INSERT tool records into `tools` table with `scope = tenant_id`, `executor = 'mcp_sse'`, `endpoint_url = server.endpoint_url`
6. On failure: UPDATE status = `error`, `last_error = error_message`
7. Respond 202 immediately with server_id; client polls `GET /admin/mcp-servers/{id}` for status

### Tool Executor

File: `src/backend/app/modules/agents/tool_executor.py` (new)

```python
class ToolExecutor:
    """
    Executes tool calls from agent skill invocations.
    Dispatches based on tool.executor field:
    - 'builtin': calls platform Python function directly
    - 'http_wrapper': makes HTTP call to endpoint_url with credential injection
    - 'mcp_sse': calls mcp_client.call_tool() with credential injection
    Credentials fetched from vault at call time; NEVER cached in memory beyond request.
    """

    async def execute(
        self,
        tool_id: str,
        arguments: dict,
        tenant_id: str,
        agent_id: str
    ) -> ToolResult:
        ...
```

Built-in tool implementations (Python functions):
- `web_search(query: str) -> list[SearchResult]` — calls configured search API
- `document_ocr(document_url: str) -> str` — calls OCR service
- `calculator(expression: str) -> float` — safe expression evaluation (no eval; use `numexpr` or manual parser)
- `data_formatter(data: any, format: str) -> str` — JSON/CSV/markdown formatter
- `file_reader(file_url: str, page_range?: str) -> str` — reads document content

---

## Frontend Changes

### New Page

File: `src/web/app/settings/tools/page.tsx`

Two-tab layout: "Platform Tools" | "My Tools"

Register in sidebar navigation under Workspace section.

### New Components

#### `PlatformToolsTab.tsx`

Location: `src/web/app/settings/tools/elements/PlatformToolsTab.tsx`

- Table layout: Name, Executor Type, Credential Required, Plan Gate, Description
- Executor type badge: "Built-in" (accent-dim), "HTTP API" (bg-elevated), "MCP" (warn-dim)
- Plan gate: lock icon if gated
- Credential badge: "No credentials needed" / "Credentials at deployment"
- Row click: expands inline detail (input schema, output schema description, rate limit)

#### `TenantMCPServersTab.tsx`

Location: `src/web/app/settings/tools/elements/TenantMCPServersTab.tsx`

- [+ Register MCP Server] button opens `MCPServerRegistrationPanel`
- Server list: each server is an expandable card
  - Card header: server name, status badge (Pending / Verified / Error / Inactive), endpoint URL, transport badge
  - Expanded: tool list from enumeration; each tool shows name, description, input schema summary
  - Actions: [Re-verify], [Edit], [Deactivate], [Delete]
- Status badge colors: Verified (accent-dim), Error (alert-dim), Pending (warn-dim), Inactive (bg-elevated)
- Error state: shows `last_error` message with [Re-verify] button

#### `MCPServerRegistrationPanel.tsx`

Location: `src/web/app/settings/tools/elements/MCPServerRegistrationPanel.tsx`

- Slides in from right, 480px wide
- Header: "Register MCP Server" + × close
- Form fields:
  - Name (text input)
  - Description (textarea)
  - Endpoint URL (URL input with https:// validation)
  - Transport (radio: SSE / Streamable HTTP)
  - Auth Type (radio: None / Bearer Token / API Key)
  - Auth Token (password input with eye toggle, shown when bearer or api_key selected)
  - Header Name (text input, shown when api_key selected)
- [Save and Verify] button: submits form, shows "Verifying connection..." spinner
- Polling: poll server status every 2s after submit until verified or error (max 15s)
- Success state: "Connected. N tools found." with tool list preview
- Error state: error message + [Try Again] button

### New Hooks

File: `src/web/hooks/useMCPTools.ts`

```typescript
usePlatformTools()            → { tools, isLoading }
useTenantMCPServers()         → { servers, isLoading }
registerMCPServer(data)       → mutation → { server_id }
verifyMCPServer(serverId)     → mutation
deleteMCPServer(serverId)     → mutation
useTenantTools()              → { tools, isLoading }  // tools from verified MCP servers
```

---

## Dependencies

- TODO-13 (DB schema) — `tools` and `tenant_mcp_servers` tables
- TODO-16 (Skills) — tenant tools appear in skill tool selector after this todo

---

## Risk Assessment

- **HIGH**: MCP server connectivity — external services may be unreliable; 10s verification timeout must be enforced strictly; background task failure must update server status correctly
- **MEDIUM**: Auth token security — tokens must NEVER be returned to browser after save; masked display (••••••) only; re-entry required to update
- **LOW**: Tool naming collisions — tenant MCP tool names may clash with platform tool names; prefix tenant tools with server name in display

---

## Testing Requirements

- [ ] Unit test: `MCPClient.verify_and_enumerate` succeeds with mock MCP server returning tool list
- [ ] Unit test: verify enforces 10s timeout — mock slow server returns error, not hang
- [ ] Unit test: auth_token never persisted to `tenant_mcp_servers.auth_config` (only vault key reference)
- [ ] Unit test: ToolExecutor dispatches to correct executor type
- [ ] Unit test: built-in calculator rejects unsafe expressions (no eval)
- [ ] Integration test: register MCP server → verify → tools enumerated → appear in `/admin/tools`
- [ ] Integration test: tenant tools not visible to other tenants
- [ ] E2E test: TA registers MCP server, verifies, sees tools, attaches to skill

---

## Definition of Done

- [ ] Platform Tools tab reads from seeded tools (5 built-in)
- [ ] MCP server registration flow works end-to-end including background verification
- [ ] Tool Executor dispatches all three executor types
- [ ] Auth tokens stored in vault, never returned to browser
- [ ] Tenant tools appear in skill tool selector (integration with TODO-16)
- [ ] All acceptance criteria met

---

## Gap Patches Applied

### Gap 2: Tool Executor runtime — full dispatch specification

The `tool_executor.py` module was listed but its internal structure was underspecified. The following is the canonical implementation design.

**Module: `src/backend/app/modules/tools/executor.py`**

The `ToolExecutor` class has three executor implementations corresponding to the three `executor_type` values:

```
ToolExecutor
├── BuiltinExecutor      — executor_type = 'builtin'
├── HttpWrapperExecutor  — executor_type = 'http_wrapper'
└── McpSseExecutor       — executor_type = 'mcp_sse'
```

**`BuiltinExecutor`:**
- Maintains a static `REGISTRY: dict[str, Callable]` mapping tool `name` → async Python function
- Dispatcher: `await REGISTRY[tool.name](**input_data)`
- All builtin functions live in `app/modules/tools/builtins/` (see Gap 8 in TODO-13)
- If tool name not in registry: raise `ToolExecutionError(code='builtin_not_found')`

**`HttpWrapperExecutor`:**

```python
class HttpWrapperExecutor:
    PRIVATE_IP_RANGES = [
        "10.", "172.16.", "172.17.", ..., "172.31.",
        "192.168.", "127.", "169.254.", "::1", "fc00:", "fe80:"
    ]

    async def execute(self, tool, input_data, credentials):
        # 1. SSRF protection: resolve endpoint_url hostname, check against PRIVATE_IP_RANGES
        #    Raise ToolExecutionError(code='ssrf_blocked') if private IP detected
        # 2. Inject credentials per tool.credential_source:
        #    - 'platform_managed': injected from platform vault
        #    - 'tenant_managed': injected from per-agent vault path
        #    - 'none': no credential injection
        # 3. Make HTTP POST to tool.endpoint_url with httpx (async), timeout=30s
        #    Set follow_redirects=False — never follow redirects (SSRF vector)
        # 4. Validate response body against tool.output_schema (JSON Schema validation)
        # 5. Sanitize response: strip <script> tags, javascript: URI schemes from all string values
        # 6. Rate limit: check Redis counter key 'rate:{tenant_id}:{tool_id}' against tool.rate_limit_rpm
        #    Raise ToolExecutionError(code='rate_limit_exceeded') if over limit
        # 7. Return sanitized, validated output dict
```

Security requirements (non-negotiable):
- SSRF protection: block all requests to RFC 1918 private ranges, loopback, link-local, and IPv6 ULA — raise `ToolExecutionError(code='ssrf_blocked')` before any network call is made
- No redirect following: `follow_redirects=False` in all httpx calls
- Response sanitization: before injecting any tool response content into LLM context, strip `<script>...</script>` tags (case-insensitive), `javascript:` URI schemes, and HTML event handler attributes (`onload=`, `onclick=`, etc.)
- Credential masking: credential values must NEVER appear in log output; use `"*****"` replacement in all log messages that include request/response headers or bodies
- Rate limiting: enforced per `(tenant_id, tool_id)` pair using Redis `INCR` + `EXPIRE` pattern; failure to reach Redis is fail-open (log warning, proceed)

**`McpSseExecutor`:**

```python
class McpSseExecutor:
    async def execute(self, tool, input_data, credentials):
        # 1. Resolve MCP server record from tool.endpoint_url (via tenant_mcp_servers table)
        # 2. Inject credentials from vault (same SSRF protection as HttpWrapperExecutor)
        # 3. Call mcp_client.call_tool(endpoint_url, transport, auth_config, tool.name, input_data, timeout=30)
        # 4. Return MCPToolResult.output as dict
```

**Credential resolution strategy (`_resolve_credentials`):**

```python
async def _resolve_credentials(self, tool, tenant_id: str, agent_id: str) -> dict:
    if tool.credential_source == 'none':
        return {}
    elif tool.credential_source == 'platform_managed':
        # Fetch from platform vault: platform/tools/{tool.id}/{key}
        return await vault.get_all(f"platform/tools/{tool.id}")
    elif tool.credential_source == 'tenant_managed':
        # Fetch from per-agent vault path (see Gap 7 in TODO-15)
        return await vault.get_all(f"{tenant_id}/agents/{agent_id}")
    else:
        raise ToolExecutionError(code='unknown_credential_source')
```

**Add to Testing Requirements:**
- [ ] Unit test: `HttpWrapperExecutor` raises `ToolExecutionError(code='ssrf_blocked')` for 10.x.x.x endpoint
- [ ] Unit test: `HttpWrapperExecutor` raises `ToolExecutionError(code='ssrf_blocked')` for 192.168.x.x endpoint
- [ ] Unit test: `HttpWrapperExecutor` with `follow_redirects=False` — a 302 redirect to private IP does not execute (redirect not followed)
- [ ] Unit test: tool response containing `<script>alert(1)</script>` is sanitized before return — script tag absent from output
- [ ] Unit test: tool response containing `javascript:alert(1)` URI is sanitized
- [ ] Unit test: credential value `"supersecret"` does not appear in any log output during `execute()` call
- [ ] Unit test: rate limit exceeded returns `ToolExecutionError(code='rate_limit_exceeded')` without executing HTTP call
- [ ] Unit test: `BuiltinExecutor` with unknown tool name raises `ToolExecutionError(code='builtin_not_found')`
