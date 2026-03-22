---
name: mingai-table-patterns
description: Responsive table patterns for mingai. Use when implementing any data table, list, or grid in the mingai web app. Covers ScrollableTableWrapper, useInfiniteScrollSentinel, useInfiniteQuery, tab filtering, responsive column hiding (multi-breakpoint), blur overlay for narrow viewports, and row-click interaction.
---

# mingai Table Patterns — Responsive + Infinite Scroll

All tables in `src/web/` use this pattern. It provides:
- Responsive height: fills the viewport minus topbar and surrounding UI chrome
- Responsive width: full-width with horizontal scroll when content overflows; columns hide at breakpoints
- Infinite scroll: load next page automatically as user scrolls to the bottom
- Sticky header: column labels stay visible while rows scroll
- Tab filters: instant client-side filtering, no extra network requests
- Row-click: primary interaction is clicking the row itself, not action buttons

---

## Shared Components

### `ScrollableTableWrapper` — `src/web/components/shared/ScrollableTableWrapper.tsx`

Wraps any `<table>` element. Provides the card container, scroll axes, and optional pinned footer.

```tsx
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";

// Default usage (uses built-in maxHeight formula)
<ScrollableTableWrapper footer={<div>N of M rows</div>}>
  <table className="w-full">...</table>
</ScrollableTableWrapper>

// Small card tables (TenantHealthTable, SyncJobHistory, etc.) — no height cap
<ScrollableTableWrapper maxHeight="none">
  <table className="w-full">...</table>
</ScrollableTableWrapper>
```

**Default `maxHeight`**: `calc(100svh - var(--topbar-h, 48px) - 180px)`
- `100svh` — small viewport height (handles mobile chrome correctly)
- `var(--topbar-h, 48px)` — CSS custom property from Obsidian Intelligence; falls back to 48px
- `180px` — accounts for page header, action bar, and footer chrome

**Component signature:**
```tsx
interface ScrollableTableWrapperProps {
  children: React.ReactNode;
  footer?: React.ReactNode;          // Pinned below scroll area, above border
  className?: string;
  maxHeight?: string;                // Default: calc formula above. Pass "none" for card tables.
}
```

**Internal layout:**
```tsx
<div className="flex flex-col rounded-card border border-border bg-bg-surface">
  {/* Scrollable area */}
  <div className="min-h-0 flex-1 overflow-x-auto overflow-y-auto" style={{ maxHeight }}>
    {children}   {/* <table> goes here */}
  </div>
  {/* Pinned footer (row count, pagination info) */}
  {footer && <div className="flex-none border-t border-border">{footer}</div>}
</div>
```

---

### `useInfiniteScrollSentinel` — `src/web/lib/hooks/useInfiniteScrollSentinel.ts`

Returns a `ref` to attach to a sentinel element. When the sentinel enters the viewport, calls `onIntersect`.

```typescript
import { useInfiniteScrollSentinel } from "@/lib/hooks/useInfiniteScrollSentinel";

const sentinelRef = useInfiniteScrollSentinel(
  handleIntersect,                         // () => void — called when sentinel visible
  hasNextPage && !isFetchingNextPage,       // enabled — skip observer when no more pages
);

// Attach to a sentinel row at the BOTTOM of <tbody>:
<tr>
  <td colSpan={columns.length} className="p-0">
    <div ref={sentinelRef} className="h-1" />
  </td>
</tr>
```

**IMPORTANT**: The sentinel `<div>` MUST be inside a `<tr><td>` — a bare `<div>` directly inside `<tbody>` is invalid HTML.

**Hook implementation:**
```typescript
export function useInfiniteScrollSentinel(onIntersect: () => void, enabled = true) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => { if (entries[0]?.isIntersecting) onIntersect(); },
      { threshold: 0.1 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [onIntersect, enabled]);
  return sentinelRef;
}
```

---

## `useInfiniteQuery` Hook Pattern

### Converting `useQuery` → `useInfiniteQuery`

**Before (paginated useQuery):**
```typescript
export function useTenants(page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["platform-tenants", page, pageSize],
    queryFn: () => apiGet<TenantsResponse>(`/api/v1/platform/tenants?page=${page}&page_size=${pageSize}`),
  });
}
```

**After (infinite scroll):**
```typescript
const PAGE_SIZE = 30;  // Larger page = fewer round-trips

export function useInfiniteTenants() {
  return useInfiniteQuery({
    queryKey: ["platform-tenants-infinite"],
    queryFn: ({ pageParam = 1 }) =>
      apiGet<TenantsResponse>(`/api/v1/platform/tenants?page=${pageParam}&page_size=${PAGE_SIZE}`),
    getNextPageParam: (lastPage) => {
      const totalPages = Math.ceil(lastPage.total / PAGE_SIZE);
      return lastPage.page < totalPages ? lastPage.page + 1 : undefined;
    },
    initialPageParam: 1,
  });
}
```

### Flattening pages into rows

```typescript
const { data, isPending, isFetchingNextPage, fetchNextPage, hasNextPage } = useInfiniteTenants();

const rows = data?.pages.flatMap((p) => p.items) ?? [];
const total = data?.pages[0]?.total ?? 0;  // total count is stable on first page
```

### Page size recommendations

| Table | Page size | Reason |
|-------|-----------|--------|
| Users, Tenants, Terms | 30–50 | Medium rows, common filter usage |
| Audit log, Job history | 20–30 | Tall rows with many columns |
| Small card tables | N/A | Use `useQuery`, no infinite scroll needed |

---

## Full Table Component Pattern

Complete example (adapt for any data table):

```tsx
"use client";

import { useCallback } from "react";
import { useReactTable, getCoreRowModel, flexRender, type ColumnDef } from "@tanstack/react-table";
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";
import { useInfiniteScrollSentinel } from "@/lib/hooks/useInfiniteScrollSentinel";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { useInfiniteMyItems } from "@/lib/hooks/useMyItems";

export function MyTable() {
  const { data, isPending, error, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteMyItems();

  const rows = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;

  const columns: ColumnDef<MyItem>[] = [
    { accessorKey: "name", header: "Name", ... },
    // ... other columns
  ];

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const handleIntersect = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const sentinelRef = useInfiniteScrollSentinel(
    handleIntersect,
    hasNextPage && !isFetchingNextPage,
  );

  if (error) return <p className="text-body-default text-alert">Failed to load: {error.message}</p>;

  const footer = (
    <div className="px-4 py-2.5">
      <span className="font-mono text-data-value text-text-faint">{rows.length} of {total}</span>
    </div>
  );

  return (
    <ScrollableTableWrapper footer={footer}>
      <table className="w-full">
        {/* MUST be sticky — prevents headers scrolling out of view */}
        <thead className="sticky top-0 z-10 bg-bg-surface">
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id} className="border-b border-border">
              {headerGroup.headers.map((header) => (
                <th key={header.id} className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {/* Loading skeleton — initial load */}
          {isPending && Array.from({ length: 8 }).map((_, i) => (
            <TableRowSkeleton key={i} columns={columns.length} />
          ))}

          {/* Empty state */}
          {!isPending && rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-3.5 py-12 text-center text-body-default text-text-faint">
                No items found.
              </td>
            </tr>
          )}

          {/* Data rows */}
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id} className="border-b border-border-faint transition-colors hover:bg-accent-dim">
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-3.5 py-3">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}

          {/* Infinite scroll sentinel — MUST be inside tr>td */}
          <tr>
            <td colSpan={columns.length} className="p-0">
              <div ref={sentinelRef} className="h-1" />
            </td>
          </tr>

          {/* Loading skeleton — next page fetch */}
          {isFetchingNextPage && Array.from({ length: 3 }).map((_, i) => (
            <TableRowSkeleton key={`fetch-${i}`} columns={columns.length} />
          ))}
        </tbody>
      </table>
    </ScrollableTableWrapper>
  );
}
```

---

## Responsive Column Hiding — Multi-Breakpoint

Use `meta: { hideBelow: "sm" | "md" | "lg" }` on column definitions. A shared `colHide()` helper maps the breakpoint to the correct Tailwind show/hide pair. Apply the class to BOTH `<th>` and `<td>`.

**Essential columns principle**: Only show what a user needs to identify and act on a row in a list. Reserve detailed fields for the detail/edit panel. When in doubt, omit.

```tsx
// 1. Helper — place once per file, before the component
function colHide(meta: unknown): string {
  const bp = (meta as { hideBelow?: string } | undefined)?.hideBelow;
  if (bp === "sm") return "hidden sm:table-cell";
  if (bp === "md") return "hidden md:table-cell";
  if (bp === "lg") return "hidden lg:table-cell";
  return "";
}

// 2. Column definitions — add meta to non-essential columns
const columns: ColumnDef<MyItem>[] = [
  { accessorKey: "name",   header: "Name"       },                     // always visible
  { accessorKey: "status", header: "Status"     },                     // always visible
  { accessorKey: "ready",  header: "Ready",  meta: { hideBelow: "md" } }, // md+ (768px+)
  { accessorKey: "tier",   header: "Tier",   meta: { hideBelow: "lg" } }, // lg+ (1024px+)
  { accessorKey: "price",  header: "Price",  meta: { hideBelow: "lg" } }, // lg+ (1024px+)
];

// 3. Apply in <th> rendering
{headerGroup.headers.map((header) => (
  <th
    key={header.id}
    className={cn("px-3.5 py-2.5 text-left", colHide(header.column.columnDef.meta))}
  >
    ...
  </th>
))}

// 4. Apply in <td> rendering
{row.getVisibleCells().map((cell) => (
  <td
    key={cell.id}
    className={cn("px-3.5 py-3", colHide(cell.column.columnDef.meta))}
  >
    {flexRender(cell.column.columnDef.cell, cell.getContext())}
  </td>
))}

// 5. SkeletonRows must match — hardcode the same responsive classes
function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 4 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          <td className="px-3.5 py-3"><div className="h-4 w-36 animate-pulse rounded-badge bg-bg-elevated" /></td>             {/* always */}
          <td className="px-3.5 py-3"><div className="h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" /></td>             {/* always */}
          <td className="hidden md:table-cell px-3.5 py-3"><div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" /></td> {/* md+ */}
          <td className="hidden lg:table-cell px-3.5 py-3"><div className="h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" /></td> {/* lg+ */}
          <td className="hidden lg:table-cell px-3.5 py-3"><div className="h-4 w-24 animate-pulse rounded-badge bg-bg-elevated" /></td> {/* lg+ */}
        </tr>
      ))}
    </>
  );
}
```

**Recommended breakpoint strategy for most admin tables:**

| Priority | Column type | Breakpoint |
|---|---|---|
| Always | Name, Status, Actions | (no meta) |
| Medium | Operational badge (Ready, Health) | `hideBelow: "md"` |
| Low | Numeric detail (Price, Count), Category badge | `hideBelow: "lg"` |
| Never in list | Technical IDs, long text, audit fields | Move to detail panel |

---

## Blur Overlay for Narrow Viewports

When even the minimal column set is too cramped to be useful (typically `< sm` / 640px), show a blur overlay instead of a broken layout. Wrap the entire component in `relative`, then overlay with `sm:hidden`.

```tsx
// Wrap the entire return in a relative container
return (
  <div className="relative">
    {/* Blur overlay — shown below sm (< 640px) */}
    <div className="sm:hidden absolute inset-0 z-30 flex flex-col items-center justify-center rounded-card backdrop-blur-sm bg-bg-surface/70 pointer-events-none">
      <Monitor size={20} className="mb-2 text-text-faint" />
      <p className="text-body-default font-medium text-text-muted">
        Wider screen recommended
      </p>
      <p className="mt-0.5 text-[11px] text-text-faint">
        Rotate device or open on desktop
      </p>
    </div>

    {/* Normal table content */}
    <ScrollableTableWrapper ...>
      ...
    </ScrollableTableWrapper>
  </div>
);
```

**Rules:**
- `pointer-events-none` — the overlay is informational only; don't block all interaction
- `z-30` — sits above sticky `thead` (z-10) and any inline z-index
- `rounded-card` on the overlay — matches the `ScrollableTableWrapper` card chrome
- Use `sm:hidden` (not `hidden sm:block`) — overlay is shown at xs, hidden at sm+
- Import `Monitor` from `lucide-react` for the icon

---

## Tab Filter Pattern (Client-Side)

**Never** create a separate `useQuery` per tab status — this causes loading flicker and breaks if the backend ignores the `?status=` parameter. Instead, fetch all data once and filter client-side with `useMemo`.

```tsx
// ✅ CORRECT — single fetch, instant client-side filter
const [statusFilter, setStatusFilter] = useState<Status | "all">("all");
const { data: allData, isPending, error } = useMyItems();   // no status param

const data = useMemo(
  () =>
    !allData || statusFilter === "all"
      ? allData
      : allData.filter((item) => item.status === statusFilter),
  [allData, statusFilter],
);

// ❌ WRONG — separate query per tab
const queryStatus = statusFilter === "all" ? undefined : statusFilter;
const { data } = useMyItems(queryStatus);  // new cache key per tab → flicker
```

**Tab UI pattern** — `-mb-px` makes the active `border-b-2` overlap the container's `border-b border-border`, replacing the gray line with the accent color at the active position:

```tsx
const STATUS_FILTERS = [
  { value: "all", label: "All" },
  { value: "Draft", label: "Draft" },
  { value: "Published", label: "Published" },
  { value: "Deprecated", label: "Deprecated" },
] as const;

<div className="flex gap-0 border-b border-border">
  {STATUS_FILTERS.map((sf) => (
    <button
      key={sf.value}
      type="button"
      onClick={() => setStatusFilter(sf.value)}
      className={cn(
        "-mb-px px-3.5 py-2 text-[12px] font-medium transition-colors",
        statusFilter === sf.value
          ? "border-b-2 border-accent text-text-primary"
          : "border-b-2 border-transparent text-text-faint hover:text-text-muted",
      )}
    >
      {sf.label}
    </button>
  ))}
</div>
```

**Why `-mb-px` works:** A flex item with `margin-bottom: -1px` extends 1px past the container's padding edge, allowing its `border-b-2` to visually overlap and replace the container's `border-b` at that position. Requires the parent to have `overflow: visible` (the flex default).

---

## Row-Click Interaction Pattern

For detail/edit actions, make the **entire row clickable** rather than adding a dedicated "Edit" or "View" button. Remove the Actions column entirely when row-click is the only action.

```tsx
// ✅ Row click → open edit panel
{table.getRowModel().rows.map((row) => (
  <tr
    key={row.id}
    onClick={() => onEdit(row.original)}
    className="cursor-pointer border-b border-border-faint transition-colors hover:bg-accent-dim"
  >
    {row.getVisibleCells().map((cell) => (
      <td key={cell.id} className={cn("px-3.5 py-3", colHide(cell.column.columnDef.meta))}>
        {flexRender(cell.column.columnDef.cell, cell.getContext())}
      </td>
    ))}
  </tr>
))}

// ✅ Row click → navigate (tenants, items with their own page)
onClick={() => (window.location.href = `/platform/tenants/${row.original.id}`)}

// ✅ Action buttons INSIDE a clickable row — stop propagation on the container
{
  id: "actions",
  cell: (info) => (
    <div
      className="flex items-center gap-2"
      onClick={(e) => e.stopPropagation()}   // ← REQUIRED
    >
      <button onClick={() => handleDelete(info.row.original.id)}>Delete</button>
    </div>
  ),
}
```

**Decision guide:**
| Situation | Pattern |
|---|---|
| Row opens a slide-in panel | `onClick={() => onEdit(row.original)}` — remove Actions column |
| Row navigates to a detail page | `onClick={() => window.location.href = '/...'}` — remove View button |
| Row has destructive actions (Delete) | Keep Actions column with `e.stopPropagation()`; remove Edit button |
| Row has lifecycle actions (Publish/Deprecate) | Keep `<LifecycleActions>` in Actions cell with `e.stopPropagation()` |

**Do NOT use `useRouter().push()` inside a table cell** — it requires `"use client"` + extra imports and the `onClick` pattern with `window.location.href` is equivalent for non-SPA navigation.

---

## Existing Infinite Scroll Tables in mingai

Tables that are fully converted (as of 2026-03-21):

| Table | Hook | Location |
|-------|------|----------|
| `TenantTable` | `useInfiniteTenants()` | `app/(platform)/platform/tenants/elements/` |
| `TermList` | `useInfiniteGlossaryTerms()` | `app/settings/glossary/elements/` |
| `UserTable` | `useInfiniteUsers()` | `app/settings/users/elements/` |

All other tables are wrapped in `ScrollableTableWrapper` with sticky thead (no `useInfiniteQuery` needed — either small enough or load-all data).

---

## Common Mistakes

```tsx
// ❌ WRONG — bare div inside tbody (invalid HTML)
<tbody>
  <div ref={sentinelRef} className="h-1" />
</tbody>

// ✅ CORRECT — sentinel inside tr>td
<tbody>
  <tr><td colSpan={n} className="p-0"><div ref={sentinelRef} className="h-1" /></td></tr>
</tbody>

// ❌ WRONG — forgetting useCallback on handleIntersect (double-fetch on every render)
const handleIntersect = () => { if (hasNextPage && !isFetchingNextPage) fetchNextPage(); };

// ✅ CORRECT — stable reference
const handleIntersect = useCallback(() => {
  if (hasNextPage && !isFetchingNextPage) fetchNextPage();
}, [hasNextPage, isFetchingNextPage, fetchNextPage]);

// ❌ WRONG — total from last page (changes as pages accumulate)
const total = data?.pages[data.pages.length - 1]?.total ?? 0;

// ✅ CORRECT — total from first page (stable, set by backend on first query)
const total = data?.pages[0]?.total ?? 0;

// ❌ WRONG — using ScrollableTableWrapper for tiny card tables
<ScrollableTableWrapper>  {/* caps at calc(100svh - 228px) */}

// ✅ CORRECT — disable height cap for small embedded tables
<ScrollableTableWrapper maxHeight="none">

// ❌ WRONG — separate useQuery per tab status (flicker, breaks if backend ignores param)
const { data } = useMyItems(statusFilter === "all" ? undefined : statusFilter);

// ✅ CORRECT — single fetch + client-side useMemo filter
const { data: allData } = useMyItems();
const data = useMemo(
  () => !allData || statusFilter === "all" ? allData : allData.filter(i => i.status === statusFilter),
  [allData, statusFilter],
);

// ❌ WRONG — colHide() applied only to <th>, not to <td>
// Column appears hidden in header but cells are still visible
<th className={cn("px-3.5 py-2.5", colHide(header.column.columnDef.meta))}>...
<td className="px-3.5 py-3">...   // ← missing colHide()

// ✅ CORRECT — apply colHide() to both th AND td
<th className={cn("px-3.5 py-2.5", colHide(header.column.columnDef.meta))}>...
<td className={cn("px-3.5 py-3",   colHide(cell.column.columnDef.meta))}>...

// ❌ WRONG — action button inside clickable row without stopPropagation
<tr onClick={() => onEdit(row.original)}>
  <td><button onClick={() => handleDelete(id)}>Delete</button></td>  // triggers onEdit too
</tr>

// ✅ CORRECT — stopPropagation on the action container
<tr onClick={() => onEdit(row.original)}>
  <td>
    <div onClick={(e) => e.stopPropagation()}>
      <button onClick={() => handleDelete(id)}>Delete</button>
    </div>
  </td>
</tr>

// ❌ WRONG — keeping a View/Edit button column when row-click already opens the panel
{ id: "actions", cell: () => <button>Edit →</button> }  // redundant; remove the column

// ✅ CORRECT — row click IS the edit; only keep Actions column for destructive/lifecycle ops
<tr onClick={() => onEdit(row.original)} className="cursor-pointer ...">
```
