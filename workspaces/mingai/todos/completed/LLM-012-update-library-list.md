# TODO-LLM-012: Update LibraryList.tsx — Add Credential Columns and Test Status

## Status

Active

## Summary

Update `LibraryList.tsx` to add three new columns to the table: a truncated `Endpoint` column (azure_openai entries only, dash for others), a `Key` badge column showing `key_present` status, and a `Tested` column showing `last_test_passed_at` as a relative date or "Never". The column count increases from 8 to the appropriate number following TanStack Table column definition patterns.

## Context

The list view currently shows: Provider, Deployment, Display Name, Plan, Pricing In, Pricing Out, Status, Actions. After the redesign, a platform admin needs to see at a glance whether each entry has credentials configured and has been tested — without opening the edit form. The `LifecycleActions` component (rendered in the Actions column) is updated separately in LLM-013.

## Acceptance Criteria

- [ ] New column `Endpoint` added: shows first 40 chars of `endpoint_url` in DM Mono, truncated with `…` if longer; shows `—` (em dash) for non-azure providers or when null
- [ ] New column `Key` added: shows `key_present` as a badge — accent color (filled) when `true` ("Key set"), faint border badge when `false` ("No key")
- [ ] New column `Tested` added: shows `last_test_passed_at` as a relative date string (e.g. "2 hours ago") when set; shows `Never` in `text-text-faint` when null
- [ ] Column order: Provider | Deployment | Display Name | Plan | Price In | Price Out | Endpoint | Key | Tested | Status | Actions
- [ ] `SkeletonRows` updated to match new column count (currently hardcoded to 8 columns)
- [ ] `LLMLibraryEntry` usage in this file continues to compile (the type now has the new fields from LLM-010)
- [ ] Table remains horizontally scrollable on narrow screens (existing `overflow-x-auto` wrapper retained)

## Implementation Notes

File to edit: `src/web/app/(platform)/platform/llm-library/elements/LibraryList.tsx`

Read the full file before editing — the column definition structure uses TanStack `ColumnDef<LLMLibraryEntry>` objects. Add the three new column defs following the same pattern.

Column def for Endpoint:

```typescript
{
  id: "endpoint_url",
  header: "Endpoint",
  cell: ({ row }) => {
    const url = row.original.endpoint_url;
    if (!url) return <span className="text-text-faint">—</span>;
    const display = url.length > 40 ? url.slice(0, 40) + "…" : url;
    return <span className="font-mono text-[11px] text-text-muted">{display}</span>;
  },
},
```

Column def for Key:

```typescript
{
  id: "key_present",
  header: "Key",
  cell: ({ row }) => {
    const present = row.original.key_present;
    return present ? (
      <span className="inline-flex items-center gap-1 rounded-badge border border-accent bg-accent-dim px-2 py-0.5 text-[10px] text-accent">
        Key set
      </span>
    ) : (
      <span className="inline-flex items-center rounded-badge border border-border px-2 py-0.5 text-[10px] text-text-faint">
        No key
      </span>
    );
  },
},
```

Column def for Tested — use a simple relative time formatter:

```typescript
function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return "< 1 hr ago";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
```

Update `SkeletonRows` column count from hardcoded `8` to match the actual column count.

## Dependencies

- Depends on: LLM-010 (types updated so LLMLibraryEntry has new fields)
- Blocks: LLM-016

## Test Requirements

- [ ] `tsc --noEmit` passes
- [ ] Manual: list page shows new columns for entries with/without credentials
- [ ] Manual: `endpoint_url` truncation correct at 40 chars
- [ ] Skeleton rows match column count (no layout misalignment)
