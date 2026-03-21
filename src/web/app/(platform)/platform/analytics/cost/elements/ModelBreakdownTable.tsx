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
import { ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useCostAnalyticsSummary,
  type CostAnalyticsSummaryEntry,
} from "@/lib/hooks/useCostUsage";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDollar(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatNumber(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 4 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          {Array.from({ length: 4 }).map((_, j) => (
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

/**
 * P2LLM-015: Cost Analytics Summary Table.
 * Shows per-tenant cost and token totals from GET /api/v1/platform/cost-analytics/summary.
 */
export function CostAnalyticsSummaryTable() {
  const { data, isPending, error } = useCostAnalyticsSummary();
  const [sorting, setSorting] = useState<SortingState>([
    { id: "total_cost_usd", desc: true },
  ]);

  const columns = useMemo<ColumnDef<CostAnalyticsSummaryEntry>[]>(
    () => [
      {
        accessorKey: "tenant_name",
        header: "Tenant",
        cell: (info) => (
          <span className="text-body-default font-medium text-text-primary">
            {info.getValue<string>()}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "total_tokens",
        header: "Total Tokens",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            {formatNumber(info.getValue<number>())}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "total_cost_usd",
        header: "Total Cost",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            {formatDollar(info.getValue<number>())}
          </span>
        ),
        enableSorting: true,
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
        Failed to load cost summary: {error.message}
      </p>
    );
  }

  return (
    <div className="rounded-card border border-border bg-bg-surface">
      <div className="border-b border-border px-5 py-3">
        <h3 className="text-section-heading text-text-primary">
          Cost Analytics Summary
        </h3>
      </div>

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
                  className="px-3.5 py-12 text-center text-body-default text-text-faint"
                >
                  No usage data available.
                </td>
              </tr>
            )}

            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className="border-b border-border-faint transition-colors hover:bg-accent-dim"
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3.5 py-3">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && data.length > 0 && (
        <div className="border-t border-border px-5 py-2.5">
          <p className="font-mono text-data-value text-text-faint">
            {data.length} tenant{data.length !== 1 ? "s" : ""}
          </p>
        </div>
      )}
    </div>
  );
}
