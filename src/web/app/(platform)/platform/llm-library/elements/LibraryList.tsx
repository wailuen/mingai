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
import { ArrowUpDown, Pencil, Star } from "lucide-react";
import { cn } from "@/lib/utils";
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

function statusBadgeClass(status: LLMLibraryStatus): string {
  switch (status) {
    case "Published":
      return "border border-accent text-accent";
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
    default:
      return provider;
  }
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
          {Array.from({ length: 8 }).map((_, j) => (
            <td key={j} className="px-3.5 py-3">
              <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
            </td>
          ))}
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
  const queryStatus = statusFilter === "all" ? undefined : statusFilter;
  const { data, isPending, error } = useLLMLibrary(queryStatus);
  const [sorting, setSorting] = useState<SortingState>([]);

  const columns = useMemo<ColumnDef<LLMLibraryEntry>[]>(
    () => [
      {
        accessorKey: "display_name",
        header: "Display Name",
        cell: (info) => (
          <span className="text-[13px] font-medium text-text-primary">
            {info.getValue<string>()}
            {info.row.original.is_recommended && (
              <Star
                size={12}
                className="ml-1.5 inline-block fill-accent text-accent"
              />
            )}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "provider",
        header: "Provider",
        cell: (info) => (
          <span className="text-[13px] text-text-muted">
            {providerLabel(info.getValue<string>())}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "model_name",
        header: "Model Name",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            {info.getValue<string>()}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "plan_tier",
        header: "Plan Tier",
        cell: (info) => (
          <span className="text-[13px] capitalize text-text-muted">
            {info.getValue<string>()}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "pricing_per_1k_tokens_in",
        header: "Price In",
        cell: (info) => {
          const val = info.getValue<number | null>();
          return (
            <span className="font-mono text-data-value text-text-muted">
              {val != null ? `$${formatPrice(val)}` : "—"}
            </span>
          );
        },
        enableSorting: true,
      },
      {
        accessorKey: "pricing_per_1k_tokens_out",
        header: "Price Out",
        cell: (info) => {
          const val = info.getValue<number | null>();
          return (
            <span className="font-mono text-data-value text-text-muted">
              {val != null ? `$${formatPrice(val)}` : "—"}
            </span>
          );
        },
        enableSorting: true,
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
        header: "Actions",
        cell: (info) => {
          const entry = info.row.original;
          return (
            <div className="flex items-center gap-2">
              {entry.status !== "Deprecated" && (
                <button
                  type="button"
                  onClick={() => onEdit(entry)}
                  className="inline-flex items-center gap-1 rounded-control border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
                >
                  <Pencil size={12} />
                  Edit
                </button>
              )}
              <LifecycleActions entry={entry} />
            </div>
          );
        },
        enableSorting: false,
      },
    ],
    [onEdit],
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
      <p className="text-sm text-alert">
        Failed to load LLM library: {error.message}
      </p>
    );
  }

  return (
    <div>
      {/* Status filter tabs */}
      <div className="mb-5 flex gap-0 border-b border-border">
        {STATUS_FILTERS.map((sf) => (
          <button
            key={sf.value}
            type="button"
            onClick={() => setStatusFilter(sf.value)}
            className={cn(
              "px-3.5 py-2 text-[12px] font-medium transition-colors",
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
      <div className="rounded-card border border-border bg-bg-surface">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id} className="border-b border-border">
                  {headerGroup.headers.map((header) => (
                    <th key={header.id} className="px-3.5 py-2.5 text-left">
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
                    className="px-3.5 py-12 text-center text-sm text-text-faint"
                  >
                    No models found. Create your first library entry to get
                    started.
                  </td>
                </tr>
              )}

              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className={cn(
                    "border-b border-border-faint transition-colors",
                    row.original.status === "Deprecated"
                      ? "opacity-50"
                      : "hover:bg-accent-dim",
                  )}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-3.5 py-3">
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {data && data.length > 0 && (
          <div className="border-t border-border px-5 py-2.5">
            <p className="font-mono text-[11px] text-text-faint">
              {data.length} entr{data.length !== 1 ? "ies" : "y"}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
