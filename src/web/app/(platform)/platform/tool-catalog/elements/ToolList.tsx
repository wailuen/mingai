"use client";

import { Fragment, useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import {
  ArrowUpDown,
  Eye,
  Archive,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";
import {
  useTools,
  useRetireTool,
  type Tool,
  type HealthStatus,
} from "@/lib/hooks/useToolCatalog";
import { SafetyClassificationBadge } from "./SafetyClassificationBadge";
import { ToolHealthMonitor } from "./ToolHealthMonitor";

interface ToolListProps {
  onView: (tool: Tool) => void;
}

const HEALTH_DOT: Record<HealthStatus, string> = {
  healthy: "bg-accent",
  degraded: "bg-warn",
  unavailable: "bg-alert",
};

function formatDate(iso: string | null): string {
  if (!iso) return "--";
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          {Array.from({ length: 6 }).map((__, j) => (
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

function ToolUsageAnalytics({ tool }: { tool: Tool }) {
  return (
    <div className="border-t border-border bg-bg-elevated/50 px-6 py-4">
      <div className="grid grid-cols-3 gap-6">
        <div>
          <p className="text-[11px] uppercase tracking-wider text-text-faint">
            Invocations
          </p>
          <p className="mt-1 font-mono text-body-default text-text-primary">
            {tool.invocation_count.toLocaleString()}
          </p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wider text-text-faint">
            Error Rate
          </p>
          <p
            className={cn(
              "mt-1 font-mono text-body-default",
              tool.error_rate_pct > 5 ? "text-alert" : "text-text-primary",
            )}
          >
            {tool.error_rate_pct.toFixed(1)}%
          </p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wider text-text-faint">
            P50 Latency
          </p>
          <p className="mt-1 font-mono text-body-default text-text-primary">
            {tool.p50_latency_ms}ms
          </p>
        </div>
      </div>
      <div className="mt-3">
        <p className="text-[11px] uppercase tracking-wider text-text-faint">
          Health (Last 24 Checks)
        </p>
        <div className="mt-2">
          <ToolHealthMonitor
            toolId={tool.id}
            currentStatus={tool.health_status}
          />
        </div>
      </div>
    </div>
  );
}

export function ToolList({ onView }: ToolListProps) {
  const { data, isPending, error } = useTools();
  const retireMutation = useRetireTool();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});

  function toggleExpanded(id: string) {
    setExpandedRows((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  const columns = useMemo<ColumnDef<Tool>[]>(
    () => [
      {
        id: "expand",
        header: "",
        cell: (info) => {
          const isExpanded = expandedRows[info.row.original.id] ?? false;
          return (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                toggleExpanded(info.row.original.id);
              }}
              className="text-text-faint transition-colors hover:text-text-muted"
            >
              {isExpanded ? (
                <ChevronDown size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
            </button>
          );
        },
        enableSorting: false,
      },
      {
        accessorKey: "name",
        header: "Name",
        cell: (info) => (
          <span className="text-body-default font-medium text-text-primary">
            {info.getValue<string>()}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "provider",
        header: "Provider",
        cell: (info) => (
          <span className="text-body-default text-text-muted">
            {info.getValue<string>()}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "safety_class",
        header: "Safety",
        cell: (info) => (
          <SafetyClassificationBadge
            safetyClass={info.getValue<Tool["safety_class"]>()}
          />
        ),
        enableSorting: true,
      },
      {
        accessorKey: "health_status",
        header: "Health",
        cell: (info) => {
          const status = info.getValue<HealthStatus>();
          return (
            <div className="flex items-center gap-1.5">
              <span
                className={cn(
                  "inline-block h-2 w-2 rounded-full",
                  HEALTH_DOT[status],
                )}
              />
              <span className="text-xs capitalize text-text-muted">
                {status}
              </span>
            </div>
          );
        },
        enableSorting: true,
      },
      {
        accessorKey: "last_ping",
        header: "Last Ping",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            {formatDate(info.getValue<string | null>())}
          </span>
        ),
        enableSorting: false,
      },
      {
        id: "actions",
        header: "Actions",
        cell: (info) => {
          const row = info.row.original;
          return (
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onView(row);
                }}
                className="inline-flex items-center gap-1 rounded-control border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                <Eye size={11} />
                View
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  retireMutation.mutate(row.id);
                }}
                disabled={retireMutation.isPending}
                className="inline-flex items-center gap-1 rounded-control border border-alert/30 px-2 py-1 text-[11px] text-alert transition-colors hover:bg-alert-dim disabled:opacity-30"
              >
                <Archive size={11} />
                Retire
              </button>
            </div>
          );
        },
        enableSorting: false,
      },
    ],
    [expandedRows, onView, retireMutation],
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
        Failed to load tools: {error.message}
      </p>
    );
  }

  return (
    <ScrollableTableWrapper
      footer={
        data && data.length > 0 ? (
          <div className="px-5 py-2.5">
            <p className="font-mono text-data-value text-text-faint">
              {data.length} tool{data.length !== 1 ? "s" : ""} registered
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
                No tools registered yet
              </td>
            </tr>
          )}

          {table.getRowModel().rows.map((row) => {
            const isExpanded = expandedRows[row.original.id] ?? false;
            return (
              <Fragment key={row.id}>
                <tr
                  onClick={() => toggleExpanded(row.original.id)}
                  className="cursor-pointer border-b border-border-faint transition-colors hover:bg-accent-dim"
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
                {isExpanded && (
                  <tr>
                    <td colSpan={columns.length} className="p-0">
                      <ToolUsageAnalytics tool={row.original} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </ScrollableTableWrapper>
  );
}
