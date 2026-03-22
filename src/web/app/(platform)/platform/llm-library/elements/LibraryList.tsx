"use client";

import { useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowUpDown, Star, Monitor } from "lucide-react";
import { cn } from "@/lib/utils";
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";
import {
  useLLMLibrary,
  type LLMLibraryEntry,
  type LLMLibraryStatus,
} from "@/lib/hooks/useLLMLibrary";
import { LifecycleActions } from "./LifecycleActions";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPrice(val: number): string {
  return val.toFixed(6);
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return "< 1 hr ago";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function statusBadgeClass(status: LLMLibraryStatus): string {
  switch (status) {
    case "Published":
      return "border border-accent/30 bg-accent-dim text-accent";
    case "Draft":
      return "border border-border text-text-muted";
    case "Deprecated":
      return "border border-border text-text-faint";
  }
}

function providerLabel(provider: string): string {
  switch (provider) {
    case "azure_openai":
      return "Azure OpenAI";
    case "openai_direct":
      return "OpenAI Direct";
    case "anthropic":
      return "Anthropic";
    case "bedrock":
      return "AWS Bedrock";
    default:
      return provider;
  }
}

/** Returns Tailwind classes to hide a column below a given breakpoint. */
function colHide(meta: unknown): string {
  const bp = (meta as { hideBelow?: string } | undefined)?.hideBelow;
  if (bp === "sm") return "hidden sm:table-cell";
  if (bp === "md") return "hidden md:table-cell";
  if (bp === "lg") return "hidden lg:table-cell";
  return "";
}

const STATUS_FILTERS: { value: LLMLibraryStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "Draft", label: "Draft" },
  { value: "Published", label: "Published" },
  { value: "Deprecated", label: "Deprecated" },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 4 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          {/* Model — always visible */}
          <td className="px-3.5 py-3">
            <div className="h-4 w-36 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          {/* Tier — lg+ */}
          <td className="hidden lg:table-cell px-3.5 py-3">
            <div className="h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          {/* Pricing — lg+ */}
          <td className="hidden lg:table-cell px-3.5 py-3">
            <div className="h-4 w-24 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          {/* Ready — md+ */}
          <td className="hidden md:table-cell px-3.5 py-3">
            <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          {/* Status — always visible */}
          <td className="px-3.5 py-3">
            <div className="h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          {/* Actions — always visible */}
          <td className="px-3.5 py-3">
            <div className="h-4 w-12 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
        </tr>
      ))}
    </>
  );
}

interface SortHeaderProps {
  label: string;
  canSort: boolean;
  sorted: false | "asc" | "desc";
  onClick: () => void;
}

function SortHeader({ label, canSort, sorted, onClick }: SortHeaderProps) {
  return (
    <button
      type="button"
      className={cn(
        "flex items-center gap-1 text-label-nav uppercase tracking-wider text-text-faint",
        canSort && "cursor-pointer hover:text-text-muted",
      )}
      onClick={canSort ? onClick : undefined}
    >
      {label}
      {canSort && (
        <ArrowUpDown
          size={10}
          className={cn(sorted ? "text-accent" : "text-text-faint")}
        />
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface LibraryListProps {
  onEdit: (entry: LLMLibraryEntry) => void;
}

export function LibraryList({ onEdit }: LibraryListProps) {
  const [statusFilter, setStatusFilter] = useState<LLMLibraryStatus | "all">(
    "all",
  );
  const { data: allData, isPending, error } = useLLMLibrary();
  const data = useMemo(
    () =>
      !allData || statusFilter === "all"
        ? allData
        : allData.filter((e) => e.status === statusFilter),
    [allData, statusFilter],
  );
  const [sorting, setSorting] = useState<SortingState>([]);

  const columns = useMemo<ColumnDef<LLMLibraryEntry>[]>(
    () => [
      {
        id: "model",
        header: "Model",
        cell: ({ row }) => {
          const entry = row.original;
          return (
            <div>
              <span className="flex items-center gap-1.5 text-body-default font-medium text-text-primary">
                {entry.display_name}
                {entry.is_recommended && (
                  <Star
                    size={11}
                    className="inline-block flex-shrink-0 fill-accent text-accent"
                  />
                )}
              </span>
              <span className="mt-0.5 block text-[11px] text-text-faint">
                {providerLabel(entry.provider)}
              </span>
            </div>
          );
        },
        enableSorting: false,
      },
      {
        accessorKey: "plan_tier",
        header: "Tier",
        meta: { hideBelow: "lg" },
        cell: (info) => (
          <span className="inline-block rounded-badge border border-border px-2 py-0.5 font-mono text-[10px] capitalize text-text-muted">
            {info.getValue<string>()}
          </span>
        ),
        enableSorting: true,
      },
      {
        id: "pricing",
        header: "Pricing /1K",
        meta: { hideBelow: "lg" },
        cell: ({ row }) => {
          const inVal = row.original.pricing_per_1k_tokens_in;
          const outVal = row.original.pricing_per_1k_tokens_out;
          if (inVal == null && outVal == null)
            return <span className="text-text-faint">—</span>;
          return (
            <span className="font-mono text-data-value text-text-muted">
              ${inVal != null ? formatPrice(inVal) : "—"}
              <span className="mx-0.5 text-text-faint">/</span>$
              {outVal != null ? formatPrice(outVal) : "—"}
            </span>
          );
        },
        enableSorting: false,
      },
      {
        id: "ready",
        header: "Ready",
        meta: { hideBelow: "md" },
        cell: ({ row }) => {
          const { key_present, last_test_passed_at } = row.original;
          if (!key_present) {
            return (
              <span className="inline-block rounded-badge border border-border px-2 py-0.5 font-mono text-[10px] text-text-faint">
                No key
              </span>
            );
          }
          if (!last_test_passed_at) {
            return (
              <span className="inline-block rounded-badge border border-warn/40 bg-warn-dim px-2 py-0.5 font-mono text-[10px] text-warn">
                Untested
              </span>
            );
          }
          return (
            <span
              className="inline-block rounded-badge border border-accent/40 bg-accent-dim px-2 py-0.5 font-mono text-[10px] text-accent"
              title={`Tested ${relativeTime(last_test_passed_at)}`}
            >
              ✓ {relativeTime(last_test_passed_at)}
            </span>
          );
        },
        enableSorting: false,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: (info) => {
          const status = info.getValue<LLMLibraryStatus>();
          return (
            <span
              className={cn(
                "inline-block rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
                statusBadgeClass(status),
              )}
            >
              {status}
            </span>
          );
        },
        enableSorting: true,
      },
      {
        id: "actions",
        header: "",
        cell: (info) => {
          const entry = info.row.original;
          return (
            <div
              className="flex items-center justify-end"
              onClick={(e) => e.stopPropagation()}
            >
              <LifecycleActions entry={entry} />
            </div>
          );
        },
        enableSorting: false,
      },
    ],
    [],
  );

  const table = useReactTable({
    data: data ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load LLM library: {error.message}
      </p>
    );
  }

  return (
    <div className="relative">
      {/* Blur overlay — below sm (< 640px) the table is too narrow to be useful */}
      <div className="sm:hidden absolute inset-0 z-30 flex flex-col items-center justify-center rounded-card backdrop-blur-sm bg-bg-surface/70 pointer-events-none">
        <Monitor size={20} className="mb-2 text-text-faint" />
        <p className="text-body-default font-medium text-text-muted">
          Wider screen recommended
        </p>
        <p className="mt-0.5 text-[11px] text-text-faint">
          Rotate device or open on desktop
        </p>
      </div>

      {/* Status filter tabs — -mb-px merges active border with table top border */}
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

      {/* Table */}
      <ScrollableTableWrapper
        footer={
          data && data.length > 0 ? (
            <div className="px-5 py-2.5">
              <p className="font-mono text-data-value text-text-faint">
                {data.length} entr{data.length !== 1 ? "ies" : "y"}
              </p>
            </div>
          ) : undefined
        }
      >
        <table className="w-full">
          <thead className="sticky top-0 z-10 bg-bg-surface">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b border-border">
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className={cn(
                      "px-3.5 py-2.5 text-left",
                      colHide(header.column.columnDef.meta),
                    )}
                  >
                    {header.isPlaceholder ? null : (
                      <SortHeader
                        label={
                          typeof header.column.columnDef.header === "string"
                            ? header.column.columnDef.header
                            : header.id
                        }
                        canSort={header.column.getCanSort()}
                        sorted={header.column.getIsSorted()}
                        onClick={
                          header.column.getToggleSortingHandler() as () => void
                        }
                      />
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {isPending && <SkeletonRows />}

            {data && data.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-3.5 py-12 text-center text-body-default text-text-faint"
                >
                  No models found. Create your first library entry to get
                  started.
                </td>
              </tr>
            )}

            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                onClick={() => onEdit(row.original)}
                className={cn(
                  "cursor-pointer border-b border-border-faint transition-colors hover:bg-accent-dim",
                  row.original.status === "Deprecated" && "opacity-50",
                )}
              >
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    className={cn(
                      "px-3.5 py-3",
                      colHide(cell.column.columnDef.meta),
                    )}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollableTableWrapper>
    </div>
  );
}
