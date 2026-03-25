# TODO-40: Tool Catalog 3-Section UI Redesign

**Phase**: Platform Admin — Tool Catalog (PA-036 product spec)
**Priority**: P2 — Current flat table diverges from product specification
**Effort**: 1 day frontend
**Plan ref**: `workspaces/mingai/02-plans/05-platform-admin-plan.md` (PA-036), product spec TODO-23

---

## Context

The user question "Is this how MCP is to be presented?" triggered a product doc check. The current tool catalog page is a flat table of all tools. The product spec (TODO-23 / PA-036) requires a **3-section layout**:

1. **Built-ins** — First-party tools bundled with the platform (e.g., Pitchbook MCP)
2. **MCP Integrations** — Third-party integrations, grouped by integration name with:
   - Integration header row: name, tool count, health badge, expand/collapse chevron
   - When expanded: per-tool sub-table rows with executor badge, plan gate, credential source
3. **Tenant Tools** — Aggregate view of tools registered by individual tenants (count + drill-down)

The current `ToolList.tsx` shows a flat table with all tools undifferentiated.

---

## Items

### UI-001: Redesign `ToolList.tsx` — 3-section layout

**File**: `src/web/app/(platform)/platform/tool-catalog/elements/ToolList.tsx`

Replace the current flat table with three sections:

#### Section 1: Built-ins
- Header: "Built-in Tools" (section heading, text-section-heading)
- Simple card grid or compact table showing platform-bundled tools
- Pitchbook MCP shows here with its safety classification badge + health indicator
- No expand/collapse (always visible, fixed set)

#### Section 2: MCP Integrations
- Header: "MCP Integrations" (section heading)
- Each integration rendered as an **IntegrationGroupRow** (expandable):
  ```
  [chevron] [Integration Name]   [N tools]   [health badge]   [• healthy]
  ```
  When expanded, shows per-tool sub-rows:
  ```
  [tool name]   [executor badge]   [plan gate]   [credential source]   [last ping]
  ```
- Group tools by `provider` field from tool_catalog (same provider = same integration)
- Executor badge: "MCP" pill in accent-dim
- Plan gate: shows `plan_required` value or "All plans"
- Credential source: "API Key", "OAuth 2.0", or "None"

#### Section 3: Tenant Tools
- Header: "Tenant Tools" (section heading)
- Shows aggregate: "X tools registered across Y tenants" with a [View Details] link
- Clicking View Details opens a slide-in panel (or navigates to a filtered view)
- This section shows tools registered BY tenants (not by platform admins)
- If no tenant tools exist, show empty state: "No tenant tools registered yet."

**Design tokens to use**:
- Section headers: `text-section-heading text-text-primary mb-3`
- Integration group row: `border-b border-border py-3 flex items-center gap-4`
- Expand chevron: `ChevronRight` → `ChevronDown` (lucide-react), 220ms ease transition
- Expanded sub-table: `bg-bg-elevated rounded-control mx-4 mb-2`
- Executor badge: `rounded-badge bg-accent-dim text-accent text-[10px] px-2 py-0.5 font-semibold`

### UI-001b: Backend — expose classification columns in tool list response

**File**: `src/backend/app/modules/platform/routes.py`

The `list_tool_catalog` SELECT query currently returns: `id, name, provider, description, auth_type, capabilities, safety_classification, health_status, last_health_check, mcp_endpoint, created_at`.

Add three columns required for client-side section classification:
- `executor_type` (v054 column: `'builtin'`, `'mcp_sse'`, `'http_wrapper'`, etc.)
- `scope` (v054 column: `'platform'` vs `'tenant'`)
- `source_mcp_server_id` (v056 column: non-null for tenant-registered tools)

Also update the `Tool` TypeScript interface in `useToolCatalog.ts`:
```typescript
export interface Tool {
  // ... existing fields ...
  executor_type: string;
  scope: "platform" | "tenant";
  source_mcp_server_id: string | null;
}
```

### UI-002: Update data classification in `useTools()`

**File**: `src/web/lib/hooks/useToolCatalog.ts`

Add a helper to classify tools into sections:

```typescript
export function classifyTools(tools: Tool[]): {
  builtins: Tool[];
  mcpIntegrations: Record<string, Tool[]>; // keyed by provider
  tenantTools: Tool[];
}
```

Classification rules (using fields added in UI-001b):
- Built-ins: `executor_type === 'builtin'`
- Tenant Tools: `scope === 'tenant'` OR `source_mcp_server_id !== null`
- MCP Integrations: all others (`scope === 'platform'` and `executor_type !== 'builtin'`), grouped by `provider`

### UI-003: `IntegrationGroupRow.tsx` component

**File**: `src/web/app/(platform)/platform/tool-catalog/elements/IntegrationGroupRow.tsx` (new)

```typescript
interface IntegrationGroupRowProps {
  provider: string;
  tools: Tool[];
  isExpanded: boolean;
  onToggle: () => void;
}
```

Renders the collapsible group row + expanded sub-table.

### UI-004: Update `ToolRegistrationForm.tsx` — section hint

**File**: `src/web/app/(platform)/platform/tool-catalog/elements/ToolRegistrationForm.tsx`

After the `provider` field, add a hint:
```
Tools registered here appear in the "MCP Integrations" section, grouped by provider name.
```

### UI-005: Empty states for each section

Each section shows a meaningful empty state:
- Built-ins empty: "No built-in tools configured. Contact support." (should not appear in production)
- MCP Integrations empty: "No MCP integrations registered. Use 'Register Tool' to add one."
- Tenant Tools empty: "No tenant tools registered yet."

---

## Definition of Done

- [ ] Backend list query returns `executor_type`, `scope`, `source_mcp_server_id`
- [ ] `Tool` TypeScript interface extended with three new fields
- [ ] Tool catalog page shows 3 visually distinct sections
- [ ] `classifyTools()` correctly routes each tool to its section using `executor_type` and `scope`
- [ ] MCP Integrations section: tools grouped by provider with expand/collapse rows
- [ ] Built-ins section: Pitchbook shown; correct empty state if none
- [ ] Tenant Tools section: aggregate count or empty state
- [ ] Expanded sub-rows show executor badge, plan gate, credential source
- [ ] Existing filter chips (safety class, status) still work across all sections
- [ ] Retired (`is_active = FALSE`) tools show greyed-out with "Retired" badge rather than being hidden
- [ ] Collapse/expand animation uses `--t` transition (220ms ease)
- [ ] No TypeScript errors
- [ ] Design tokens match Obsidian Intelligence system
