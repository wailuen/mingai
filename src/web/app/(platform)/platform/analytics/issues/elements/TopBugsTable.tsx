"use client";

import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { cn } from "@/lib/utils";
import {
  useTopBugs,
  type AnalyticsPeriod,
  type TopBug,
} from "@/lib/hooks/useIssueAnalytics";
import { TableRowSkeleton } from "@/components/shared/LoadingState";

// ---------------------------------------------------------------------------
// Status badge styling
// ---------------------------------------------------------------------------

function statusBadgeClass(status: string): string {
  switch (status) {
    case "new":
      return "border-accent/30 bg-accent-dim text-accent";
    case "in_review":
      return "border-warn/30 bg-warn-dim text-warn";
    case "escalated":
      return "border-alert/30 bg-alert-dim text-alert";
    case "resolved":
      return "border-border bg-bg-elevated text-text-muted";
    case "closed":
      return "border-border bg-bg-elevated text-text-faint";
    default:
      return "border-border bg-bg-elevated text-text-muted";
  }
}

function formatStatusLabel(status: string): string {
  return status
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// ---------------------------------------------------------------------------
// Column definitions
// ---------------------------------------------------------------------------

const columnHelper = createColumnHelper<TopBug & { rank: number }>();

const columns = [
  columnHelper.accessor("rank", {
    header: "#",
    cell: (info) => (
      <span className="font-mono text-xs text-text-muted">
        {info.getValue()}
      </span>
    ),
    size: 48,
  }),
  columnHelper.accessor("title", {
    header: "Title",
    cell: (info) => (
      <span className="text-body-default font-medium text-text-primary">
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.accessor("report_count", {
    header: "Reports",
    cell: (info) => (
      <span className="font-mono text-body-default text-text-primary">
        {info.getValue().toLocaleString()}
      </span>
    ),
    size: 96,
  }),
  columnHelper.accessor("tenant_count", {
    header: "Tenants",
    cell: (info) => (
      <span className="font-mono text-body-default text-text-primary">
        {info.getValue()}
      </span>
    ),
    size: 96,
  }),
  columnHelper.accessor("status", {
    header: "Status",
    cell: (info) => (
      <span
        className={cn(
          "inline-block rounded-badge border px-1.5 py-0.5 text-[11px] font-medium",
          statusBadgeClass(info.getValue()),
        )}
      >
        {formatStatusLabel(info.getValue())}
      </span>
    ),
    size: 120,
  }),
];

// ---------------------------------------------------------------------------
// TopBugsTable
// ---------------------------------------------------------------------------

interface TopBugsTableProps {
  period: AnalyticsPeriod;
}

export function TopBugsTable({ period }: TopBugsTableProps) {
  const { data: bugs, isPending, error } = useTopBugs(period);

  const tableData = (bugs ?? []).map((bug, i) => ({
    ...bug,
    rank: i + 1,
  }));

  const table = useReactTable({
    data: tableData,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load top bugs: {error.message}
      </p>
    );
  }

  return (
    <div>
      <h2 className="mb-3 text-section-heading text-text-primary">
        Top Bugs by Report Volume
      </h2>
      <div className="overflow-hidden rounded-card border border-border">
        <table className="w-full">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr
                key={headerGroup.id}
                className="border-b border-border bg-bg-surface"
              >
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint"
                    style={
                      header.getSize() !== 150
                        ? { width: header.getSize() }
                        : undefined
                    }
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {isPending ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRowSkeleton key={i} columns={5} />
              ))
            ) : tableData.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="px-3.5 py-12 text-center text-body-default text-text-faint"
                >
                  No bug data available for this period.
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className="border-b border-border-faint transition-colors hover:bg-accent-dim"
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
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
