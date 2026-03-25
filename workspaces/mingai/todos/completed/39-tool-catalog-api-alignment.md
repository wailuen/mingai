# TODO-39: Tool Catalog API Alignment

**Phase**: Platform Admin — Tool Catalog
**Priority**: P1 — Frontend calls non-existent endpoints; retire and health features silently broken
**Effort**: 0.5 day backend
**Plan ref**: workspaces/mingai/02-plans/05-platform-admin-plan.md (PA-036)

---

## Context

The `useToolCatalog.ts` frontend hook defines three operations that reference endpoints which do not exist in the backend:

| Hook function        | Frontend calls                                     | Backend has                                 | Status     |
|---------------------|-----------------------------------------------------|---------------------------------------------|------------|
| `useRetireTool()`   | `POST /api/v1/platform/tool-catalog/{id}/retire`    | `DELETE /platform/tools/{id}` (wrong path)  | BROKEN     |
| `useToolHealthHistory()` | `GET /api/v1/platform/tool-catalog/{id}/health` | Nothing                                     | BROKEN     |
| (missing)           | (no single-tool fetch in hook)                      | `GET /platform/tools/{id}` exists           | OK         |

The backend has `DELETE /platform/tools/{id}` for deletion but the frontend calls `POST /platform/tool-catalog/{id}/retire`. These paths must be aligned. The simplest fix is to add the missing routes at the paths the frontend expects (or align the frontend to use the existing DELETE endpoint).

---

## Red-Team Findings (incorporated)

- **Use `is_active = FALSE` not `health_status = 'unavailable'`**: The health check job already uses `health_status = 'unavailable'` for tools that fail pings. Overloading it conflates automated degradation with manual retirement. The `is_active` column (added in v054) is the correct flag. Set both `is_active = FALSE` AND `health_status = 'unavailable'` on retire, so both the admin list and the health RLS filter correctly exclude the tool.
- **No health history table**: `tool_health_job.py` updates the row in-place. Need a `tool_health_checks` migration to store per-check history (required for the health history endpoint). ~288 rows/tool/day at 5-min intervals; add a 30-day retention cleanup.
- **Hard delete + soft delete coexist**: The existing `DELETE /platform/tools/{tool_id}` does a cascade hard-delete. Keep it for data cleanup but add a pre-check: if the tool has active `agent_template_tools` or `skill_tool_dependencies` rows, reject the hard delete with a 409 Conflict. Document that `retire` is the normal operational path and `DELETE` is for data cleanup only.
- **Confirmation modal**: The frontend must show a confirmation dialog before calling retire — it affects all tenants.
- **Audit log**: The retire endpoint must write to `audit_log`.

---

## Items

### TC-001: Migration — `tool_health_checks` table

**File**: `src/backend/alembic/versions/v061_tool_health_checks.py`

```sql
CREATE TABLE tool_health_checks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_id     UUID NOT NULL REFERENCES tool_catalog(id) ON DELETE CASCADE,
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status      VARCHAR(20) NOT NULL CHECK (status IN ('healthy', 'degraded', 'unavailable')),
    latency_ms  INTEGER,
    error_msg   TEXT
);
CREATE INDEX idx_tool_health_checks_tool_id_checked_at ON tool_health_checks (tool_id, checked_at DESC);
```

Modify `tool_health_job.py` to INSERT a row into `tool_health_checks` on every ping (in addition to the existing in-place UPDATE on `tool_catalog`). Add a daily cleanup query: `DELETE FROM tool_health_checks WHERE checked_at < NOW() - INTERVAL '30 days'`.

### TC-002: Add `POST /platform/tool-catalog/{id}/retire` endpoint

**File**: `src/backend/app/modules/platform/routes.py`

```python
@router.post("/platform/tool-catalog/{tool_id}/retire", status_code=200)
async def retire_tool(
    tool_id: str = Path(...),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    POST /platform/tool-catalog/{tool_id}/retire
    Soft-retire a tool: set is_active = FALSE and health_status = 'unavailable'.
    Preferred over hard-delete for operational decommissioning.
    platform_admin only.
    """
```

SQL:
```sql
UPDATE tool_catalog
   SET is_active = FALSE, health_status = 'unavailable', updated_at = NOW()
 WHERE id = :tool_id
RETURNING id, name, is_active, health_status
```

After update, write an audit_log entry: `{"action": "retire_tool", "tool_id": tool_id, "tool_name": row.name}`.

Return the updated tool row. 404 if not found, 403 if caller is not platform_admin.

**Success criteria**:
- `POST /api/v1/platform/tool-catalog/{id}/retire` returns 200 with updated tool row
- `GET /platform/tool-catalog` shows the tool with `health_status = "unavailable"`
- 404 returned if tool_id not found
- 403 returned if caller is not platform_admin

### TC-003: Add `GET /platform/tool-catalog/{id}/health` endpoint

**File**: `src/backend/app/modules/platform/routes.py`

Returns the health check history for a tool (from `tool_health_checks` table if it exists, otherwise returns last_ping + current status as a single entry).

```python
@router.get("/platform/tool-catalog/{tool_id}/health")
async def get_tool_health_history(
    tool_id: str = Path(...),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """GET /platform/tool-catalog/{tool_id}/health — health check history for a tool."""
```

Response shape matching `ToolHealthCheck[]` in `useToolCatalog.ts`:
```json
[
  { "timestamp": "2026-03-23T07:00:00Z", "status": "healthy" },
  { "timestamp": "2026-03-23T06:00:00Z", "status": "degraded" }
]
```

If no `tool_health_checks` table exists: return `[{ timestamp: last_ping, status: health_status }]` from the tool_catalog row itself.

**Success criteria**:
- `GET /api/v1/platform/tool-catalog/{id}/health` returns 200 with array of health check entries
- Returns empty array `[]` if no health history exists
- 404 returned if tool_id not found

### TC-004: Hard-delete guard for active assignments

**File**: `src/backend/app/modules/platform/routes.py`

Modify the existing `DELETE /platform/tools/{tool_id}` to pre-check for active assignments:

```python
# Check for active template/skill assignments before hard delete
result = await session.execute(
    text("SELECT COUNT(*) FROM agent_template_tools WHERE tool_id = :id UNION ALL SELECT COUNT(*) FROM skill_tool_dependencies WHERE tool_id = :id"),
    {"id": tool_id}
)
if any(r[0] > 0 for r in result.fetchall()):
    raise HTTPException(status_code=409, detail="Tool has active template or skill assignments. Use retire instead.")
```

Document at the endpoint: "For operational decommissioning, use POST /platform/tool-catalog/{id}/retire (soft-delete). DELETE is for data cleanup only."

### TC-005: Retire confirmation modal (frontend)

**File**: `src/web/app/(platform)/platform/tool-catalog/elements/ToolList.tsx` (or wherever the Retire button is)

Before calling `retireMutation.mutate(id)`, show a confirmation dialog:
```
"Retire [tool name]? This removes it from all tenant agent assignments. This cannot be undone."
[Cancel] [Retire Tool]
```

Use the existing pattern from other destructive actions in the codebase.

### TC-006: Unit tests for new endpoints

**File**: `tests/unit/test_platform_tool_catalog.py` (create if not exists)

Tests:
- `test_retire_tool_sets_is_active_false` — verify `is_active=FALSE` and `health_status='unavailable'`
- `test_retire_tool_writes_audit_log` — verify audit_log entry written
- `test_retire_tool_not_found` — verify 404
- `test_retire_tool_requires_platform_admin` — verify 403 for tenant user
- `test_retire_tool_idempotent` — retiring an already-retired tool returns 200 (no error)
- `test_hard_delete_blocked_with_active_assignments` — verify 409 when template/skill refs exist
- `test_tool_health_history_returns_list` — verify response shape matches `ToolHealthCheck[]`
- `test_tool_health_history_not_found` — verify 404

### TC-007: Verify `useToolHealthHistory` refetch interval

**File**: `src/web/lib/hooks/useToolCatalog.ts`

The hook has `refetchInterval: 30_000`. Verify the `ToolHealthMonitor.tsx` component in the platform tool-catalog page correctly calls `useToolHealthHistory(id)` with the selected tool ID. If not wired, wire it.

---

## Definition of Done

- [ ] v061 migration: `tool_health_checks` table created with index
- [ ] `tool_health_job.py` inserts a row per check + 30-day cleanup
- [ ] `POST /platform/tool-catalog/{id}/retire` sets `is_active = FALSE`, writes audit_log, returns 200
- [ ] `GET /platform/tool-catalog/{id}/health` returns `ToolHealthCheck[]` from `tool_health_checks`
- [ ] `DELETE /platform/tools/{id}` returns 409 when active template/skill assignments exist
- [ ] Frontend retire button shows confirmation modal before calling retire
- [ ] Unit tests: 8 tests passing
- [ ] No TypeScript errors
