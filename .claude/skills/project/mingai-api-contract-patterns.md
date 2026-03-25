---
name: mingai-api-contract-patterns
description: API contract patterns for mingai — field name mismatches between backend and frontend, URL prefix taxonomy, agent status lifecycle, UUID guard pattern, and SSE/dev environment pitfalls. Use when debugging "missing data" issues, implementing new hooks, or writing integration tests.
---

# mingai API Contract Patterns

These patterns were identified through 9 rounds of E2E testing. They are the most common sources of silent bugs — data exists in the database but never reaches the UI, or vice versa.

---

## 1. URL Prefix Taxonomy

The backend has two distinct admin roles with separate URL namespaces. **Never cross them.**

| Caller            | URL prefix               | Auth dependency              | Example                                      |
|-------------------|--------------------------|------------------------------|----------------------------------------------|
| Tenant admin      | `/api/v1/admin/...`      | `require_tenant_admin`       | `/api/v1/admin/skills`                       |
| Platform admin    | `/api/v1/platform/...`   | `require_platform_admin`     | `/api/v1/platform/agent-templates`           |
| Shared (any auth) | `/api/v1/{resource}/...` | `require_current_user`       | `/api/v1/teams/`, `/api/v1/glossary/`        |
| Skills library    | `/api/v1/skills/...`     | tenant_admin                 | `/api/v1/skills/{id}/adopt`                  |

**Common mistake**: Writing a platform admin hook that calls `/api/v1/admin/...` — this returns tenant-scoped data filtered by the JWT's `tenant_id`, not the platform-wide view. Platform admin endpoints use `/platform/` prefix and `scope=platform` auth.

---

## 2. Backend → Frontend Field Name Normalization

The backend returns some fields under names that differ from the TypeScript interface. These are NOT bugs — they are intentional naming conventions on each side. **Always normalize in the queryFn.**

### Known Mismatches (v059)

| Backend field    | TypeScript interface field | Hook file               | Transform                                       |
|------------------|---------------------------|-------------------------|-------------------------------------------------|
| `is_adopted`     | `adopted`                 | `useSkills.ts`          | `adopted: s.is_adopted ?? false`                |
| `actor_email`    | `actor`                   | `useTeams.ts`           | `actor: e.actor_email ?? "System"`              |
| `page_size`      | `limit`                   | `useTeams.ts`           | `limit: raw.page_size`                          |
| `created_at`     | `timestamp`               | `useTeams.ts`           | `timestamp: e.created_at`                       |
| `member_email`   | `member_name` (fallback)  | `useTeams.ts`           | `member_name: e.member_name ?? e.member_email ?? "Unknown"` |

### Normalization Pattern

```typescript
// Step 1: Define the raw backend shape
interface RawSkillItem extends Omit<PlatformSkill, "adopted"> {
  is_adopted?: boolean; // backend name
}

// Step 2: Fetch with the raw type
const raw = await apiGet<{ items: RawSkillItem[]; total: number }>(url);

// Step 3: Map to the TS interface
return {
  items: raw.items.map((s) => ({
    ...s,
    adopted: s.is_adopted ?? false, // normalize
  })) as PlatformSkill[],
  total: raw.total,
};
```

**Rule**: If a field is missing/undefined in the UI but present in the DevTools network response, check for a field name mismatch. The `adopted` button never toggling is the canonical example.

---

## 3. Agent Status Lifecycle

`agent_cards.status` has three states, not two:

```
draft → published → active
```

| Status      | Set by                                 | Visible to                        |
|-------------|----------------------------------------|-----------------------------------|
| `draft`     | Agent template creation                | Platform admin only               |
| `published` | Platform admin "Publish" action        | Tenant admins in library catalog  |
| `active`    | `deploy_from_library` (tenant deploys) | Both platform and tenant admin    |

**Critical rule**: Any query on `agent_cards` that should include deployed agents MUST filter:

```sql
-- CORRECT
WHERE status IN ('published', 'draft', 'active')

-- WRONG — silently drops all deployed agents
WHERE status IN ('published', 'draft')
```

This applies to:
- Tenant agent catalog (`list_agent_templates_db`)
- Platform agent grid (shows all)
- Any COUNT query that should include live deployments

The `active` status is set in `deploy_from_library()` in `app/modules/agents/routes.py`. The INSERT uses `status='active'` directly, not a transition from `published`.

---

## 4. UUID Guard for Path Parameters

PostgreSQL UUID columns reject non-UUID strings with `InvalidTextRepresentationError`. URL path segments can legally contain values like `"auto"`, `"new"`, `"me"` that are valid URL paths but invalid UUIDs.

**Always validate before executing FK queries:**

```python
import uuid
from fastapi import HTTPException

@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, ...):
    # Validate BEFORE the DB query
    try:
        uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID format")

    # Safe to use in SQL now
    result = await db.execute(
        text("SELECT * FROM agent_cards WHERE id = :id"),
        {"id": agent_id}
    )
```

**Affected routes**: Any route with `/{id}` or `/{agent_id}` path params where the ID is used in a FK join or WHERE clause against a UUID column.

---

## 5. Null Name Fallback

The `users.name` column is nullable in the schema. Any component that displays a user's name or initial MUST use a three-level fallback:

```typescript
// CORRECT
const initial = (user.name ?? user.email ?? "?").charAt(0).toUpperCase();
const displayName = user.name ?? user.email ?? "Unknown User";

// WRONG — crashes or shows "null" when name is not set
user.name.charAt(0).toUpperCase()
user.name
```

This applies to: avatar chips, member lists, audit log tables, user directory rows, team member displays.

---

## 6. Pagination Field Names

The backend returns pagination in two different shapes depending on the endpoint:

| Backend shape                              | Frontend shape     | Notes                                      |
|--------------------------------------------|--------------------|--------------------------------------------|
| `{ items, total, page, page_size }`        | `{ items, total, page, limit }` | Most list endpoints — normalize `page_size → limit` |
| `{ items, total }`                         | `{ items, total }` | Simple list endpoints (no page/limit)      |

Always check the actual response shape in DevTools. Do not assume `limit` is returned — it's often `page_size`.

---

## 7. SSE / Dev Environment

### uvicorn + SSE Deadlock

Open SSE connections (`/api/v1/notifications/stream`, `/api/v1/chat/stream`, provision SSE) hold the uvicorn process open. After Ctrl+C:

- `--reload` cannot restart (process still running)
- New uvicorn start fails with "Address already in use"

**Fix:**
```bash
lsof -ti:8022 | xargs kill -9
# Then restart normally
```

### bcrypt in Shell — Use Heredoc

Bcrypt hashes contain backslashes. Shell one-liners eat backslashes and produce a silently wrong hash that no password will ever match:

```bash
# CORRECT — heredoc preserves all characters
python3 - << 'EOF'
import bcrypt
print(bcrypt.hashpw(b"your_password", bcrypt.gensalt()).decode())
EOF

# WRONG — output backslashes get mangled by shell
python3 -c "import bcrypt; print(bcrypt.hashpw(b'your_password', bcrypt.gensalt()).decode())"
```

---

## 8. Platform Admin vs Tenant Admin — Common Confusion Points

| Feature                    | Platform admin endpoint                         | Tenant admin endpoint                        |
|----------------------------|-------------------------------------------------|----------------------------------------------|
| LLM profiles               | `GET /api/v1/platform/llm-profiles`             | `GET /api/v1/admin/llm-config`               |
| Agent templates            | `GET /api/v1/platform/agent-templates`          | `GET /api/v1/admin/agents` (deployed only)   |
| Skills library (read)      | `GET /api/v1/skills` (platform library)         | `GET /api/v1/admin/skills` (tenant custom)   |
| Users                      | `GET /api/v1/platform/users` (all tenants)      | `GET /api/v1/admin/users` (tenant scope)     |
| Analytics                  | `GET /api/v1/platform/analytics`                | `GET /api/v1/admin/analytics`                |

**Key signal**: If a platform admin hook returns an empty array or 403, check whether it's calling `/admin/` instead of `/platform/`.
