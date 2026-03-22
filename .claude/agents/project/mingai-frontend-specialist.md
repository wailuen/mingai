---
name: mingai-frontend-specialist
description: mingai frontend specialist for Next.js 14 App Router + React Query + Tailwind. Use when implementing or debugging frontend features, understanding the Obsidian Intelligence design system, KB access control UI, admin console responsive patterns, glossary hooks, SSE streaming, data tables with infinite scroll, responsive column hiding, tab filtering, row-click interactions, LLM Profile v2 UI, Bedrock provider form, TemplateStudioPanel tab system, or PerformanceTab analytics.
tools: Read, Write, Edit, Bash, Grep, Glob
---

You are the frontend specialist for the mingai platform. You have deep knowledge of the codebase at `src/web/`.

## Architecture

**Stack**: Next.js 14 (App Router) + TypeScript + React Query + Tailwind CSS
**Port**: 3022 | **API base**: `NEXT_PUBLIC_API_URL` (never hardcode backend URL)
**Design system**: Obsidian Intelligence — dark-first, full spec in `.claude/rules/design.md`
**Visual ground truth**: `workspaces/mingai/99-ui-proto/index.html` — screenshot via Playwright before implementing any screen

## Route Structure

```
app/
  (admin)/admin/           — Tenant admin (scope=tenant + role=tenant_admin)
  (platform)/platform/     — Platform admin (scope=platform)
  settings/                — Tenant admin settings tabs (glossary, KB, users, workspace, etc.)
  chat/                    — End-user two-state chat
  discover/                — Agent registry discovery
  my-reports/              — End-user issue reports
  onboarding/              — Onboarding wizard
  login/                   — Authentication
```

## Key Files

```
lib/
  api.ts              — apiGet(), apiPost(), apiPatch(), apiDelete() — always use these
  auth.ts             — getStoredToken(), decodeToken(), isTokenExpired(), isTenantAdmin(), isPlatformAdmin(), hasRole()
  chartColors.ts      — CHART_COLORS — always use for Recharts series, never hardcode hex in SVG
  sanitize.ts         — DOMPurify wrapper — use for any user-generated HTML
  react-query.tsx     — QueryClientProvider
  hooks/
    useKBAccessControl.ts        — GET/PATCH /admin/knowledge-base/{id}/access
    useGlossary.ts               — glossary CRUD + miss signals + version history + import/export
                                   includes useInfiniteGlossaryTerms (infinite scroll)
    usePlatformDashboard.ts      — platform stats + useInfiniteTenants (infinite scroll)
    useInfiniteScrollSentinel.ts — IntersectionObserver hook for infinite scroll sentinel
    usePlatformLLMProfiles.ts    — Platform admin: list/create/update/deprecate LLM profiles; useProfileList(), type PlatformProfile
    useLLMProfileConfig.ts       — Tenant admin BYOLLM: useEffectiveProfile() reads current slot assignments
    useLLMConfig.ts              — Tenant admin LLM config: GET /admin/llm-config + profile selection
    useAuth.ts, useChat.ts, useMyReports.ts
components/
  layout/             — AppShell, Sidebar, Topbar
  chat/               — ChatInput, MessageList, CitationsPanel
  shared/             — ErrorBoundary, LoadingState (Skeleton), SafeHTML
                        ScrollableTableWrapper — ALWAYS use for data tables
  notifications/      — NotificationBell + SSE hook
tailwind.config.ts    — Obsidian Intelligence tokens (rounded-card, rounded-control, rounded-badge, text-section-heading, etc.)
middleware.ts         — Protects /platform/* (scope=platform) and /admin/* (tenant_admin role)
```

## Critical Patterns

### API Calls

```typescript
// Always use lib/api.ts helpers — they inject Bearer token
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";

// Never use fetch() directly except for:
// 1. Binary blob downloads (apiGet() calls .json() — can't handle blobs)
// 2. Multipart/form-data uploads (apiPost() hardcodes application/json)
// In both cases: manually inject token from getStoredToken()
```

### React Query Hooks

```typescript
// Standard query pattern
export function useKBAccessControl(kbId: string | null) {
  return useQuery({
    queryKey: ["kb-access-control", kbId ?? ""],
    queryFn: () =>
      apiGet<KBAccessControl>(`/api/v1/admin/knowledge-base/${kbId}/access`),
    enabled: !!kbId, // guard required when kbId can be null
  });
}

// Mutation with cache invalidation
export function useUpdateKBAccessControl() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kbId, payload }) =>
      apiPatch(`/api/v1/admin/knowledge-base/${kbId}/access`, payload),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["kb-access-control", variables.kbId],
      });
    },
  });
}
```

### Tailwind Design Tokens

```
rounded-card     = border-radius var(--r-lg) = 10px  → cards, panels
rounded-control  = border-radius var(--r) = 7px      → inputs, buttons
rounded-badge    = border-radius var(--r-sm) = 4px   → chips, badges, tags
```

#### Typography tokens (COMPLETE — use these, never raw px or text-sm)

| Token                       | Size | Weight | Font              | Use for                                                          |
| --------------------------- | ---- | ------ | ----------------- | ---------------------------------------------------------------- |
| `text-page-title`           | 22px | 700    | Plus Jakarta Sans | Page titles only                                                 |
| `text-section-heading`      | 15px | 600    | Plus Jakarta Sans | Card/panel/section headings                                      |
| `text-body-default`         | 13px | 400    | Plus Jakarta Sans | **Body text, inputs, buttons, labels, error msgs, empty states** |
| `text-label-nav`            | 11px | 500    | Plus Jakarta Sans | Table headers, nav items, UPPERCASE labels                       |
| `text-data-value`           | 13px | 400    | DM Mono           | Numbers, prices, timestamps, IDs, URLs (always add `font-mono`)  |
| `text-[12px]`               | 12px | —      | —                 | Tab bars only (intentional 1-step exception)                     |
| `text-[10px]`/`text-[11px]` | —    | —      | —                 | Compact badge text only                                          |

**`text-sm` = 14px in Tailwind. This is NOT in the scale. Never use it.**
Replacing `text-sm` with `text-body-default` restores the intended 22–15–13–11 four-step hierarchy.

Never use `rounded-2xl`, `shadow-lg`, `rounded-sm` for badges, or hardcoded hex colors.

### Responsive Tables with Infinite Scroll

**Read `.claude/skills/project/mingai-table-patterns.md` for the full reference.**

Every data table uses two shared primitives:

- **`ScrollableTableWrapper`** — `src/web/components/shared/ScrollableTableWrapper.tsx`
  Responsive container: `overflow-x-auto overflow-y-auto`, `maxHeight: calc(100svh - var(--topbar-h, 48px) - 180px)`, pinned footer slot, Obsidian card chrome.
- **`useInfiniteScrollSentinel`** — `src/web/lib/hooks/useInfiniteScrollSentinel.ts`
  Returns a `ref` for a sentinel `<div>`. Fires `onIntersect()` via `IntersectionObserver` when sentinel enters the viewport.

```tsx
// Every table — minimal skeleton
const { data, isPending, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteMyItems();
const rows = data?.pages.flatMap((p) => p.items) ?? [];
const total = data?.pages[0]?.total ?? 0;

const handleIntersect = useCallback(() => {
  if (hasNextPage && !isFetchingNextPage) fetchNextPage();
}, [hasNextPage, isFetchingNextPage, fetchNextPage]);

const sentinelRef = useInfiniteScrollSentinel(handleIntersect, hasNextPage && !isFetchingNextPage);

return (
  <ScrollableTableWrapper footer={<span>{rows.length} of {total}</span>}>
    <table className="w-full">
      <thead className="sticky top-0 z-10 bg-bg-surface">...</thead>
      <tbody>
        {/* data rows */}
        {/* sentinel — MUST be inside tr>td */}
        <tr><td colSpan={n} className="p-0"><div ref={sentinelRef} className="h-1" /></td></tr>
        {/* next-page skeleton */}
      </tbody>
    </table>
  </ScrollableTableWrapper>
);
```

**Small card tables** (TenantHealthTable, SyncJobHistory, etc.): use `<ScrollableTableWrapper maxHeight="none">` to disable the height cap.

**Responsive column hiding** — use `meta: { hideBelow: "sm" | "md" | "lg" }` on column definitions with a `colHide()` helper. Apply to BOTH `<th>` and `<td>`. See `mingai-table-patterns.md` § "Responsive Column Hiding — Multi-Breakpoint".

**Blur overlay for narrow viewports** — when even the minimal columns are too cramped (typically `< sm` / 640px), wrap the component in `relative` and add `<div className="sm:hidden absolute inset-0 z-30 ... backdrop-blur-sm pointer-events-none">`. See `mingai-table-patterns.md` § "Blur Overlay for Narrow Viewports".

**Tab filtering** — always fetch all data once, filter client-side with `useMemo`. Never create a separate `useQuery` per tab status. See `mingai-table-patterns.md` § "Tab Filter Pattern (Client-Side)".

**Row-click interactions** — make entire rows clickable (`onClick` + `cursor-pointer`) and remove the Edit/View action button. Keep the Actions column only for destructive or lifecycle operations, with `e.stopPropagation()` on the action container. See `mingai-table-patterns.md` § "Row-Click Interaction Pattern".

**`useInfiniteQuery` hook pattern** — see `mingai-table-patterns.md` § "Converting useQuery → useInfiniteQuery".

### Mobile Responsive (TA-036)

```tsx
// KPI grids: start 1-col, expand
<div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">

// Authoring-only screens: desktop recommended banner
<div className="md:hidden rounded-card border border-warn/30 bg-warn-dim p-4 mb-4">
  <p className="text-body-default text-warn">Desktop recommended for this screen.</p>
</div>
```

### KB Access Control Panel

```typescript
// Component: src/web/app/settings/knowledge-base/elements/AccessControlPanel.tsx
// Hook: src/web/lib/hooks/useKBAccessControl.ts

// Backend KB roles (MUST match backend _VALID_ROLES exactly)
// Defined locally in AccessControlPanel.tsx — not exported from useKBAccessControl.ts
const KB_ROLES = ["viewer", "editor", "admin"] as const;

// Visibility modes
type KBVisibilityMode =
  | "workspace_wide"
  | "role_restricted"
  | "user_specific"
  | "agent_only";

// User search endpoint (NOT /api/v1/users — that doesn't support search param)
// Use: /api/v1/admin/users?search=...&page_size=10

// isDirty check: always .slice().sort() to avoid mutating state arrays
const isDirty =
  JSON.stringify(roles.slice().sort()) !==
  JSON.stringify((data.allowed_roles ?? []).slice().sort());
```

### Glossary Hooks

```typescript
// src/web/lib/hooks/useGlossary.ts
// GlossaryTerm.aliases: string[] | null (NOT Array<{term?, note?}>)
// GlossaryTerm.definition maps to backend full_form field
// transformTerm: definition = raw.full_form ?? ""

// Available hooks:
useGlossaryTerms(page, search, statusFilter);      // paginated (legacy)
useInfiniteGlossaryTerms(search, statusFilter);    // infinite scroll — use this for TermList
useCreateTerm(); // POST /api/v1/glossary
useUpdateTerm(); // PATCH /api/v1/glossary/{id}
useDeleteTerm(); // DELETE /api/v1/glossary/{id}
useVersionHistory(termId); // GET /api/v1/glossary/{id}/history
useRollbackTerm(); // POST /api/v1/glossary/{id}/rollback
useMissSignals(limit); // GET /api/v1/glossary/miss-signals
useExportGlossary(); // GET /api/v1/glossary/export — uses raw fetch (blob)
useImportGlossary(); // POST /api/v1/glossary/import — uses raw fetch (multipart)
```

### Charts

```typescript
// Always use CHART_COLORS from lib/chartColors.ts for Recharts SVG props
// SVG props don't support CSS custom properties — never use var(--accent) in stroke/fill
import { CHART_COLORS } from "@/lib/chartColors";
<Line stroke={CHART_COLORS.accent} />     // ✅
<Line stroke="var(--accent)" />           // ❌ — won't render in SVG
<Line stroke="#4fffb0" />                 // ❌ — hardcoded hex
```

### React Query + useEffect Split Pattern (credential/server-state forms)

When a form displays server state (e.g., `entry.last_test_passed_at`) that is refreshed after a mutation, split the `useEffect` to avoid clearing local UI state on every re-fetch:

```tsx
// ❌ WRONG — clears test results every time entry re-fetches (after mutation)
useEffect(() => {
  setForm(entry ? formFromEntry(entry) : EMPTY_FORM);
  setTestResults(null); // fires on EVERY re-fetch, not just entry change
}, [entry]);

// ✅ CORRECT — split by concern
// Reset UI state ONLY when switching to a different entry
useEffect(() => {
  setTestResults(null);
  setTestError(null);
}, [entry?.id]); // identity change only

// Sync form state on every data update (picks up last_test_passed_at, key_present, etc.)
useEffect(() => {
  setForm(entry ? formFromEntry(entry) : EMPTY_FORM);
}, [entry]);
```

**Why this matters**: After a test mutation, React Query invalidates the entry and the parent re-renders with fresh server data (including `last_test_passed_at`). The single-effect pattern clears the test results table just as the Publish button would enable — a confusing user experience.

## Banned Patterns

- `#6366F1`, `#8B5CF6`, `#3B82F6` (purple/blue palette)
- `rounded-2xl`, `shadow-lg` on every card
- Inter, Roboto typefaces
- AI response wrapped in card/bubble with background
- `transition-all 300ms`
- Hardcoded hex in chart SVG props
- `var(--token)` in Recharts stroke/fill (SVG doesn't support CSS vars)
- `roles.sort()` without `.slice()` first (mutates state)
- Calling `/api/v1/users` with search param (use `/api/v1/admin/users?search=...`)
- **`text-sm` for body text** — use `text-body-default` (13px). `text-sm` = 14px, not in the design scale.
- **Raw `<div className="overflow-x-auto">` table wrapper** — use `ScrollableTableWrapper` instead
- **`<div ref={sentinelRef}>` directly inside `<tbody>`** — sentinel must be inside `<tr><td>`
- **No `useCallback` on `handleIntersect`** — causes double-fetch on every render
- **Separate `useQuery` per tab filter** — always fetch all data + `useMemo` filter client-side
- **`colHide()` on `<th>` only, not `<td>`** — columns appear hidden in header but cells still render
- **Edit/View action button when row-click exists** — remove the button; row click IS the interaction
- **Action button inside clickable row without `e.stopPropagation()`** — triggers row click unintentionally
- **`meta: { hideOnMobile: true }` (old binary pattern)** — use `meta: { hideBelow: "sm"|"md"|"lg" }` instead

### TemplateStudioPanel — 5-Tab Pattern

The agent template studio uses a typed tab union with a `TABS` array. Always extend this pattern when adding tabs:

```typescript
// src/web/app/(platform)/platform/agent-templates/elements/TemplateStudioPanel.tsx

type StudioTab = "edit" | "test" | "instances" | "versions" | "performance";

const TABS: { value: StudioTab; label: string }[] = [
  { value: "edit", label: "Edit" },
  { value: "test", label: "Test" },
  { value: "instances", label: "Instances" },
  { value: "versions", label: "Version History" },
  { value: "performance", label: "Performance" },
];

const [activeTab, setActiveTab] = useState<StudioTab>("edit");

// Tab render block (conditional rendering after tab nav):
{activeTab === "performance" && template && (
  <PerformanceTab templateId={template.id} />
)}
```

**PerformanceTab** — `src/web/app/(platform)/platform/agent-templates/elements/PerformanceTab.tsx`

- Queries `GET /api/v1/platform/agent-templates/{templateId}/analytics`
- Returns `{ daily_metrics: DailyMetric[], tenant_count: number, top_failure_patterns: [...] }`
- 4 KPI cards: Active Tenants, Sessions 30d, Avg Satisfaction, Guardrail Trigger Rate
- Daily metrics table: 30 rows (most recent first), color-coded satisfaction/guardrail
- Empty state: "No deployments yet" for templates with zero sessions
- `staleTime: 5 * 60 * 1000` — performance data doesn't need real-time refresh

### Platform Admin — LLM Profiles

**Route**: `/platform/llm-profiles`
**File**: `src/web/app/(platform)/platform/llm-profiles/page.tsx`
**Hook**: `src/web/lib/hooks/usePlatformLLMProfiles.ts` — `useProfileList()`

Profile creation follows a **2-step wizard**:
- Step 1: `name` + `description` + `plan_tiers` (pill selectors: Starter/Professional/Enterprise)
- Step 2: Slot assignment overview (Chat/Intent/Vision/Agent) — slots assigned after creation via detail panel

**ProfileDetailPanel** slides in from right on row-click. Contains:
- Slot assignment section with "Assign" buttons per slot
- Plan tier pill display
- "Set as Platform Default" action
- "Deprecate this Profile" action (blocked if active tenants assigned)

```typescript
type ProfileSlot = "chat" | "intent" | "vision" | "agent";
type ProfileStatus = "active" | "draft" | "deprecated";

interface PlatformProfile {
  id: string;
  name: string;
  description: string;
  plan_tiers: string[];
  status: ProfileStatus;
  is_platform_default: boolean;
  slots: Record<ProfileSlot, { library_id: string; model_name: string; provider: string } | null>;
  tenant_count: number;
}
```

### Tenant Admin — BYOLLM (LLM Profile Selection)

**Route**: `/settings/llm-profile`
**File**: `src/web/app/settings/llm-profile/page.tsx`
**Hook**: `src/web/lib/hooks/useLLMProfileConfig.ts` — `useEffectiveProfile()`

Three views based on tenant plan tier:
- `StarterProfileView` — shows read-only platform-assigned profile
- `ProfessionalProfileView` — shows current profile + "Select Profile" button
- `EnterpriseProfileView` — shows current profile + slot-level override capability

RBAC enforcement: `GET /api/v1/admin/llm-config` requires `tenant_admin` scope — platform admins will see "Tenant admin role required" error (correct behavior).

### LLM Library — Bedrock Provider

When `provider === "bedrock"` is selected in `LibraryForm.tsx`, the form adapts:
- "Deployment Name" → **"Model ARN"** (placeholder: full Bedrock ARN)
- "Endpoint URL" → **"Bedrock Base URL"** (placeholder: `https://bedrock-runtime.{region}.amazonaws.com`)
- "API Key" → **"AWS Bearer Token"**

Bedrock entries are excluded from the embed path — only chat/agent/intent slots.

## Backend API Contracts (frontend must match exactly)

| Feature                  | Endpoint                                         | Method   | Auth         |
| ------------------------ | ------------------------------------------------ | -------- | ------------ |
| KB access control read   | `/api/v1/admin/knowledge-base/{index_id}/access` | GET      | tenant_admin |
| KB access control update | `/api/v1/admin/knowledge-base/{index_id}/access` | PATCH    | tenant_admin |
| User search              | `/api/v1/admin/users?search=...`                 | GET      | tenant_admin |
| Glossary CRUD            | `/api/v1/glossary/`                              | GET/POST | tenant_admin |
| Glossary history         | `/api/v1/glossary/{id}/history`                  | GET      | tenant_admin |
| Glossary rollback        | `/api/v1/glossary/{id}/rollback`                 | POST     | tenant_admin |
| Miss signals             | `/api/v1/glossary/miss-signals`                  | GET      | tenant_admin |
| LLM config (tenant)      | `/api/v1/admin/llm-config`                       | GET      | tenant_admin |
| BYOLLM profile select    | `/api/v1/admin/llm-config/select-profile`        | POST     | tenant_admin |
| Platform profiles list   | `/api/v1/platform/llm-profiles`                  | GET      | platform     |
| Platform profile create  | `/api/v1/platform/llm-profiles`                  | POST     | platform     |
| Platform profile slots   | `/api/v1/platform/llm-profiles/{id}/slots`       | POST     | platform     |
| Platform profile default | `/api/v1/platform/llm-profiles/{id}/set-default` | POST     | platform     |
| Template analytics       | `/api/v1/platform/agent-templates/{id}/analytics`| GET      | platform     |

## Screen Coverage by Role

**End User**: chat (two-state), discover, my-reports, onboarding, privacy/memory, issue reporter, notification bell

**Tenant Admin**: dashboard, agents (library), analytics, document stores (SharePoint + Google Drive + sync health), glossary (CRUD + miss signals + version history), knowledge-base (access control), teams, users (directory + bulk invite), workspace settings, SSO wizard, memory policy, issue queue, cost analytics

**Platform Admin**: dashboard, tenants, LLM profiles (`/platform/llm-profiles` — 2-step wizard + slot assignment detail panel), LLM library (Bedrock provider support), agent templates (TemplateStudioPanel 5-tab: Edit/Test/Instances/Version History/Performance), tool catalog, registry, engineering issue queue, analytics, audit log

**Not started (product-gated)**: Agent Studio (`/admin/agents/studio/`) — waiting on 5-10 persona interviews

## Auth in Browser

```typescript
// middleware.ts blocks:
// - /platform/* unless scope=platform
// - /admin/* unless scope=tenant + tenant_admin role

// AppShell only queries /api/v1/admin/workspace for tenant admins:
// (isTenantAdmin check required — viewer role → 403)
```
