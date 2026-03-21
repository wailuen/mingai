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
import type {
  PlatformIssue,
  IssueFilters,
} from "@/lib/hooks/usePlatformIssues";
import { usePlatformIssues } from "@/lib/hooks/usePlatformIssues";
import { IssueSeverityBadge } from "./IssueSeverityBadge";

const SEVERITY_ORDER: Record<string, number> = {
  P0: 0,
  P1: 1,
  P2: 2,
  P3: 3,
  P4: 4,
};

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
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
          {Array.from({ length: 6 }).map((_, j) => (
            <td key={j} className="px-3.5 py-3">
              <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

function statusLabel(status: string): string {
  return status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

interface IssueQueueTableProps {
  filters?: IssueFilters;
  onSelectIssue: (id: string) => void;
}

export function IssueQueueTable({
  filters,
  onSelectIssue,
}: IssueQueueTableProps) {
  const { data, isPending, error } = usePlatformIssues(filters);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "severity", desc: false },
  ]);

  const columns = useMemo<ColumnDef<PlatformIssue>[]>(
    () => [
      {
        accessorKey: "severity",
        header: "Severity",
        cell: (info) => (
          <IssueSeverityBadge
            severity={info.getValue<PlatformIssue["severity"]>()}
          />
        ),
        sortingFn: (rowA, rowB) => {
          const a = SEVERITY_ORDER[rowA.original.severity] ?? 99;
          const b = SEVERITY_ORDER[rowB.original.severity] ?? 99;
          return a - b;
        },
        enableSorting: true,
      },
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
        accessorKey: "title",
        header: "Title",
        cell: (info) => (
          <span className="text-body-default text-text-primary">
            {info.getValue<string>()}
          </span>
        ),
        enableSorting: false,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: (info) => (
          <span className="text-body-default text-text-muted">
            {statusLabel(info.getValue<string>())}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "ai_classification",
        header: "AI Classification",
        cell: (info) => (
          <span className="text-body-default text-text-muted">
            {info.getValue<string>()}
          </span>
        ),
        enableSorting: false,
      },
      {
        accessorKey: "created_at",
        header: "Created",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            {formatDate(info.getValue<string>())}
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
        Failed to load issues: {error.message}
      </p>
    );
  }

  return (
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
                  className="px-3.5 py-12 text-center text-body-default text-text-faint"
                >
                  No issues found matching the current filters.
                </td>
              </tr>
            )}

            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                onClick={() => onSelectIssue(row.original.id)}
                className="cursor-pointer border-b border-border-faint transition-colors hover:bg-accent-dim"
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
            {data.length} issue{data.length !== 1 ? "s" : ""}
          </p>
        </div>
      )}
    </div>
  );
}
