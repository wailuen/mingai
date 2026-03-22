"use client";

import { useMemo, useState, useCallback } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowUpDown, Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";
import {
  useTenantCostBreakdown,
  type CostPeriod,
  type TenantCost,
} from "@/lib/hooks/useCostAnalytics";

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

function marginColorClass(pct: number): string {
  if (pct >= 50) return "text-accent";
  if (pct >= 20) return "text-warn";
  return "text-alert";
}

/**
 * Sanitize a CSV cell to prevent formula injection.
 * Cells starting with =, +, -, or @ are prefixed with a single quote.
 */
function sanitizeCsvCell(value: string): string {
  if (/^[=+\-@]/.test(value)) {
    return `'${value}`;
  }
  return value;
}

function exportCsv(rows: TenantCost[]) {
  const headers = [
    "Tenant",
    "Plan",
    "Tokens",
    "LLM Cost",
    "Infra Cost",
    "Revenue",
    "Margin %",
  ];

  const csvRows = [
    headers.join(","),
    ...rows.map((r) =>
      [
        sanitizeCsvCell(r.tenant_name),
        sanitizeCsvCell(r.plan),
        r.tokens_consumed.toString(),
        r.llm_cost.toFixed(2),
        r.infra_cost.toFixed(2),
        r.plan_revenue.toFixed(2),
        r.gross_margin_pct.toFixed(1),
      ]
        .map((cell) => `"${cell.replace(/"/g, '""')}"`)
        .join(","),
    ),
  ];

  const blob = new Blob([csvRows.join("\n")], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "tenant-cost-breakdown.csv";
  link.click();
  URL.revokeObjectURL(url);
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

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          {Array.from({ length: 7 }).map((_, j) => (
            <td key={j} className="px-3.5 py-3">
              <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

interface TenantCostTableProps {
  period: CostPeriod;
}

export function TenantCostTable({ period }: TenantCostTableProps) {
  const { data, isPending, error } = useTenantCostBreakdown(period);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "gross_margin_pct", desc: false },
  ]);

  const columns = useMemo<ColumnDef<TenantCost>[]>(
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
        accessorKey: "plan",
        header: "Plan",
        cell: (info) => (
          <span className="text-body-default text-text-muted">
            {info.getValue<string>()}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "tokens_consumed",
        header: "Tokens",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            {formatNumber(info.getValue<number>())}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "llm_cost",
        header: "LLM Cost",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            {formatDollar(info.getValue<number>())}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "infra_cost",
        header: "Infra Cost",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            {formatDollar(info.getValue<number>())}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "plan_revenue",
        header: "Revenue",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            {formatDollar(info.getValue<number>())}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "gross_margin_pct",
        header: "Margin %",
        cell: (info) => {
          const pct = info.getValue<number>();
          return (
            <span
              className={cn(
                "font-mono text-data-value font-medium",
                marginColorClass(pct),
              )}
            >
              {pct.toFixed(1)}%
            </span>
          );
        },
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

  const handleExport = useCallback(() => {
    if (data) {
      exportCsv(data);
    }
  }, [data]);

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load tenant costs: {error.message}
      </p>
    );
  }

  return (
    <div className="rounded-card border border-border bg-bg-surface">
      {/* Header with export */}
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <h3 className="text-section-heading text-text-primary">
          Tenant Cost Breakdown
        </h3>
        <button
          type="button"
          onClick={handleExport}
          disabled={isPending || !data || data.length === 0}
          className="inline-flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-[11px] font-medium text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Download size={12} />
          Export CSV
        </button>
      </div>

      {/* Table */}
      <ScrollableTableWrapper
        footer={
          data && data.length > 0 ? (
            <div className="px-5 py-2.5">
              <p className="font-mono text-data-value text-text-faint">
                {data.length} tenant{data.length !== 1 ? "s" : ""}
              </p>
            </div>
          ) : undefined
        }
        className="rounded-none border-0"
      >
        <table className="w-full">
          <thead className="sticky top-0 z-10 bg-bg-surface">
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
                  No tenant cost data available for this period.
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
      </ScrollableTableWrapper>
    </div>
  );
}
