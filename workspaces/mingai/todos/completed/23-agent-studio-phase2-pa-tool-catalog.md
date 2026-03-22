# TODO-23: Agent Studio Phase 2 — PA Tool Catalog Management

**Status**: ACTIVE
**Priority**: MEDIUM (Phase 2)
**Estimated Effort**: 2 days
**Phase**: Phase 2 — Platform Admin Authoring Studio

---

## Description

Platform admins need a unified view of the entire platform tool catalog: built-in tools, MCP integrations (HTTP wrappers from TODO-22), and visibility into tenant MCP servers (aggregate stats — not tenant-specific data). This page is the management hub for tool lifecycle: activating/deactivating tools, changing plan gates, monitoring usage, and reviewing tool health.

This is lighter than TODO-22 (the builder). This todo focuses on the catalog view, management actions, and monitoring — not the integration creation workflow.

---

## Acceptance Criteria

- [ ] PA navigates to Platform > Intelligence > Tool Catalog and sees all platform tools
- [ ] Three sections: Built-in Tools, MCP Integrations (grouped by integration), Tenant Tools (aggregate stats only)
- [ ] Built-in Tools: table with name, description, status (always Active), "Available to all" badge
- [ ] MCP Integrations: grouped by integration name; each group expandable to show individual tools; integration-level status (all tools active / some inactive / all inactive)
- [ ] Per tool: name, executor badge, plan gate, credential_source, usage count (agents + skills referencing it), status toggle
- [ ] PA can activate/deactivate any platform tool; deactivation warns if tools are in use
- [ ] PA can change plan gate on any tool (affects immediately for new deployments; does not affect existing deployments)
- [ ] PA can view tool usage: how many agent templates and skills reference this tool
- [ ] Tenant Tools section: aggregate only — "N tenants have registered private MCP servers; M unique tools total"
- [ ] Usage analytics: top 5 most-used tools (by agent invocation count), trailing 30d
- [ ] [+ New Integration] button opens MCP Integration Builder (TODO-22)
- [ ] Tool health: built-in tools always show "Healthy"; HTTP wrapper tools show last test result status
- [ ] Platform admin can trigger a health test on any HTTP wrapper tool (uses platform test credentials if configured)

---

## Backend Changes

### Platform Tool Catalog Endpoints

(Most endpoints defined in TODO-22's `platform_tools_routes.py`. This todo focuses on aggregation and monitoring.)

```python
GET /platform/tools/usage-summary
    # Returns:
    # {
    #   builtin_count: int,
    #   integration_count: int,
    #   total_tool_count: int,
    #   tenant_server_count: int,  # aggregate
    #   tenant_tool_count: int,    # aggregate
    #   top_tools: [{ tool_id, tool_name, invocation_count_30d }]  # top 5
    # }

GET /platform/tools/{id}/usage
    # Returns:
    # {
    #   template_count: int,  # agent templates referencing this tool
    #   skill_count: int,     # skills referencing this tool
    #   agent_instance_count: int,  # deployed agent instances using this tool
    #   invocation_count_30d: int
    # }

POST /platform/tools/{id}/health-check
    # Manually trigger health check on http_wrapper tool
    # Uses stored platform test credentials (if configured)
    # Returns: { status: 'healthy'|'unhealthy', latency_ms, error? }
```

### Tool Usage Tracking

When `ToolExecutor` executes a tool call, increment usage counter in Redis:
```
Key: tool_invocations:{tool_id}:{YYYY-MM-DD}
Type: counter (INCR)
TTL: 35 days
```

Aggregate query for usage-summary: SUM INCR counters across last 30 days.

---

## Frontend Changes

### Update Existing Page

The PA Tool Catalog page already exists at:
`src/web/app/(platform)/platform/tool-catalog/elements/ToolHealthMonitor.tsx`

This file implements a health monitor. Extend the surrounding page (or check if there is a `page.tsx`).

File: `src/web/app/(platform)/platform/tool-catalog/page.tsx` (create if not exists)

### New Components

#### `PAToolCatalogPage.tsx`

Location: `src/web/app/(platform)/platform/tool-catalog/page.tsx`

- Header: "Tool Catalog" (page title) + [+ New Integration] button (accent)
- Usage summary bar: 4 KPI chips — Built-in Tools count, Integration count, Total Tool count, Tenant Tools (aggregate)
- Three sections with section headings

**Built-in Tools Section:**
- Compact table: Name, Description, Available To, Status
- "Platform (all tenants)" badge, always Active status
- Row expand: shows full description + input/output schema summary

**MCP Integrations Section:**
- Grouped by integration name with expand/collapse
- Integration row: integration name, tool count, overall health badge, created date
- Expanded: tool sub-table with Name, Executor, Plan Gate, Credential Source, Usage Count, Status toggle, [Health Check] button
- Status toggle: checkbox-style switch; deactivate shows confirmation if usage count > 0

**Tenant Tools Section (aggregate only):**
- Summary: "N tenants have registered private MCP servers"
- "M unique tools in use across tenant workspaces"
- No tool names, no tenant names, no per-tenant breakdown
- Purpose: PA situational awareness, not audit

**Usage Analytics Bar (bottom of page):**
- "Top 5 Most-Used Tools (trailing 30 days)"
- Horizontal bar chart or ranked list with tool name + invocation count

#### `ToolStatusToggle.tsx`

Location: `src/web/app/(platform)/platform/tool-catalog/elements/ToolStatusToggle.tsx`

- Toggle switch (active ↔ inactive)
- On deactivate: show confirmation tooltip/modal: "N agent templates and M skills use this tool. Deactivating will prevent new invocations but not break existing conversations."
- Optimistic update with rollback on API error

#### `ToolPlanGateEditor.tsx`

Location: `src/web/app/(platform)/platform/tool-catalog/elements/ToolPlanGateEditor.tsx`

- Inline dropdown: None / Starter / Professional / Enterprise
- Shows current gate; click to edit; save on blur
- Shows "Changes apply to new deployments only" helper text

### New Hooks

File: `src/web/hooks/usePAToolCatalog.ts`

```typescript
useToolCatalog()                              → { builtins, integrations, isLoading }
useToolUsageSummary()                         → { summary, isLoading }
useToolUsage(toolId)                          → { usage, isLoading }
updateToolStatus(toolId, isActive)            → mutation
updateToolPlanGate(toolId, planRequired)      → mutation
triggerToolHealthCheck(toolId)                → mutation → HealthCheckResult
```

---

## Dependencies

- TODO-13 (DB schema) — tools table with is_active, plan_required, integration_id columns
- TODO-22 (MCP Builder) — MCP integrations created there appear here
- TODO-17 (TA MCP Tools) — tenant tools aggregated here (no per-tenant data)

---

## Testing Requirements

- [ ] Unit test: usage-summary aggregates from Redis counters correctly
- [ ] Unit test: tool deactivation returns 409 if usage count > 0 without `force: true` flag
- [ ] Unit test: health check endpoint does not log credential values
- [ ] Unit test: tenant tools section returns only aggregate counts, no tool names or tenant IDs
- [ ] Integration test: ToolExecutor INCR increments Redis usage counter on each tool call
- [ ] E2E test: PA deactivates a tool; TA skill builder shows tool as unavailable

---

## Definition of Done

- [ ] PA Tool Catalog page renders all three sections correctly
- [ ] Built-in tools, MCP integrations, and tenant tools aggregate all visible
- [ ] Status toggle + plan gate editing functional
- [ ] Usage analytics bar shows top 5 tools
- [ ] Health check trigger works for HTTP wrapper tools
- [ ] All acceptance criteria met
