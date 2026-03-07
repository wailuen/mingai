# Frontend (Web) Implementation Instructions (Phase 1)

**Worktree**: web
**Branch**: `feat/phase-1-web`
**Source reference**: `/Users/wailuen/Development/aihub2` — existing Next.js frontend

---

## Pre-Implementation Checklist

- [ ] Screenshot `workspaces/mingai/99-ui-proto/index.html` via Playwright — study every screen, panel, and state transition before writing a single component
- [ ] Read `workspaces/mingai/03-user-flows/01-platform-admin-flows.md` — what platform admin can do
- [ ] Read `workspaces/mingai/03-user-flows/02-tenant-admin-flows.md` — what tenant admin can do
- [ ] Read `workspaces/mingai/03-user-flows/03-end-user-flows.md` — what end users do
- [ ] Read `workspaces/mingai/design/01-design-language.md` — **Obsidian Intelligence** design system (tokens + rules)
- [ ] Read `workspaces/mingai/04-codegen-instructions/07-design-system.md` — implementation reference

---

## Design System (Non-Negotiable)

**Proto UI is the visual ground truth — not the design doc.**
Every screen MUST visually match `workspaces/mingai/99-ui-proto/index.html`.
Screenshot it via Playwright before implementing each screen.
The design doc explains tokens and rules; the prototype defines layout, spacing, and state transitions.
If the proto and the design doc conflict, the proto wins.

From `workspaces/mingai/design/01-design-language.md`:

| Token         | Value                                                                 |
| ------------- | --------------------------------------------------------------------- |
| Background    | `--bg-base: #0C0E14`                                                  |
| Accent        | `--accent: #4FFFB0`                                                   |
| Typography    | Plus Jakarta Sans (display + body) + DM Mono (numbers/data)           |
| Border radius | Controls: `7px`; Cards: `10px`; Badges: `4px`                         |
| Filter chips  | Outlined neutral — NOT filled accent                                  |
| KB hint       | "SharePoint · Google Drive · 2,081 documents indexed" — never "RAG ·" |
| Agent sidebar | Label: "Agents" (not "Workspaces")                                    |

Component library: **Shadcn/UI** (install configured for dark theme matching design system).
Charts: **Recharts**.
Tables: **TanStack Table** (server-side pagination for all admin lists).

---

## Project Setup

```bash
npx create-next-app@14 src/web --typescript --tailwind --app --no-src-dir
cd src/web
npx shadcn@latest init  # configure for dark theme
```

Install:

```bash
npm install @tanstack/react-table recharts next-auth @radix-ui/react-* lucide-react
```

---

## Phase 1 Pages to Implement

### Platform Admin Section (`/admin/*`)

Middleware: check JWT `scope === 'platform'` + valid platform role. Redirect to `/` if not.

**`/admin/tenants`** — Tenant list

- Table: tenant name, plan, status badge, health (placeholder "—"), creation date, actions
- Actions: View, Suspend, Delete
- "New Tenant" button → opens provisioning wizard

**`/admin/tenants/new`** — Provisioning wizard (4 steps)

1. Basic Info: name, primary contact email, plan tier
2. LLM Profile: select from published profiles (API: GET /admin/llm-profiles)
3. Quotas: set monthly token limit, rate limit
4. Review & Provision

**`/admin/tenants/[id]`** — Tenant detail

- Status, plan, contact, creation date, LLM profile assigned
- Suspend / Reactivate / Schedule Deletion actions
- Quota usage bar

### Tenant Admin Section (`/settings/*` and `/admin/workspace/*`)

Middleware: check JWT `scope === 'tenant'` + tenant admin role. Redirect if not.

**`/settings/workspace`** — Workspace settings

- Display name, logo upload, timezone, locale

**`/settings/users`** — User management

- User directory table: name, email, role, last login, status
- Invite button (single email or CSV upload)
- Role change (dropdown, immediate effect)
- Suspend / Delete user

**`/settings/knowledge-base`** — Knowledge base

- SharePoint connection status + wizard button
- Google Drive connection status + wizard button (OAuth only in Phase A)
- Per-source: document count, last sync, error count
- "Sync Now" button, sync failure list

**`/settings/glossary`** — Glossary management (Phase B — stub in Phase 1)

- Placeholder: "Glossary management coming in Phase B"

### End User Section

**Chat interface** (`/chat`) — adapt from existing aihub2 implementation:

- Two-state layout: empty state (centered input) → active state (bottom-fixed input)
- Thumbs up/down on every AI response (wire to `POST /api/v1/feedback`)
- Source citations with retrieval confidence score (label: "retrieval confidence" — canonical spec)
- Agent selector in sidebar labeled "Agents" (not "Workspaces")

---

## API Integration

Backend base URL from env: `NEXT_PUBLIC_API_URL` (never hardcode).

API client pattern:

```typescript
// lib/api.ts
const apiClient = async (path: string, options?: RequestInit) => {
  const token = getToken(); // from session/cookie
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) throw new ApiError(res.status, await res.json());
  return res.json();
};
```

SSE streaming for chat (existing pattern from aihub2):

```typescript
const response = await fetch(`${API_URL}/api/v1/chat/stream`, {
  method: "POST",
  body,
  headers,
});
const reader = response.body.getReader();
// parse SSE chunks: status, sources, response_chunk, metadata
```

---

## Auth Integration (Phase 1)

Phase 1 uses JWT auth only (no Auth0 yet — that is Phase 3).

- Login page: `POST /api/v1/auth/local/login` for dev; Azure AD OAuth for production
- Store JWT in httpOnly cookie (not localStorage)
- Middleware: check cookie, redirect to `/login` if expired

---

## Testing

Playwright E2E tests in `src/web/tests/`:

- Test all platform admin flows end-to-end (use real backend)
- Test tenant admin workspace setup flow
- Test chat with thumbs up/down feedback submission
- Cross-tenant isolation: log in as tenant A, verify tenant B data not visible in any API call

```typescript
// tests/platform-admin.spec.ts
test("platform admin can provision new tenant", async ({ page }) => {
  await page.goto("/login");
  // login as platform_admin
  await page.fill("[name=email]", process.env.PLATFORM_ADMIN_EMAIL!);
  // ... complete provisioning wizard
  // verify tenant appears in list
});
```

---

## Role-Based UI

The same Next.js app serves all three role views. Use JWT claims to show/hide sections:

| JWT claim                   | Show              | Hide                          |
| --------------------------- | ----------------- | ----------------------------- |
| `scope=platform`            | `/admin/*` nav    | Tenant workspace, chat        |
| `scope=tenant` + admin role | `/settings/*` nav | Platform admin, other tenants |
| `scope=tenant` + user role  | Chat, My Reports  | Admin settings                |
