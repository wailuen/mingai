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
import { ArrowUpDown, Pencil } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useAgentTemplatesAdmin,
  type AgentTemplateAdmin,
} from "@/lib/hooks/useAgentTemplatesAdmin";

interface TemplateListProps {
  statusFilter: "all" | "published" | "draft" | "deprecated";
  onEdit: (template: AgentTemplateAdmin) => void;
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

function StatusBadge({
  status,
}: {
  status: "Draft" | "Published" | "Deprecated";
}) {
  const styles =
    status === "Published"
      ? "bg-accent-dim text-accent"
      : status === "Deprecated"
        ? "bg-alert-dim text-alert"
        : "bg-warn-dim text-warn";

  return (
    <span
      className={cn(
        "inline-block rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
        styles,
      )}
    >
      {status}
    </span>
  );
}

export function TemplateList({ statusFilter, onEdit }: TemplateListProps) {
  const { data, isPending, error } = useAgentTemplatesAdmin(statusFilter);
  const [sorting, setSorting] = useState<SortingState>([]);

  const items = useMemo(() => data?.items ?? [], [data]);

  const columns = useMemo<ColumnDef<AgentTemplateAdmin>[]>(
    () => [
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
        accessorKey: "category",
        header: "Category",
        cell: (info) => (
          <span className="text-body-default text-text-muted">
            {info.getValue<string | null>() ?? "--"}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "version",
        header: "Version",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            v{info.getValue<number>()}
          </span>
        ),
        enableSorting: false,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: (info) => (
          <StatusBadge
            status={info.getValue<"Draft" | "Published" | "Deprecated">()}
          />
        ),
        enableSorting: true,
      },
      {
        accessorKey: "created_at",
        header: "Created",
        cell: (info) => {
          const val = info.getValue<string | null>();
          if (!val) return <span className="text-text-faint">--</span>;
          return (
            <span className="font-mono text-data-value text-text-faint">
              {new Date(val).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })}
            </span>
          );
        },
        enableSorting: true,
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
                  onEdit(row);
                }}
                className="inline-flex items-center gap-1 rounded-control border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                <Pencil size={11} />
                Edit
              </button>
            </div>
          );
        },
        enableSorting: false,
      },
    ],
    [onEdit],
  );

  const table = useReactTable({
    data: items,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load templates: {error.message}
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

            {data && items.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-3.5 py-12 text-center text-body-default text-text-faint"
                >
                  No templates yet
                </td>
              </tr>
            )}

            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                onClick={() => onEdit(row.original)}
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

      {data && items.length > 0 && (
        <div className="border-t border-border px-5 py-2.5">
          <p className="font-mono text-data-value text-text-faint">
            Showing {items.length} of {data.total} templates
          </p>
        </div>
      )}
    </div>
  );
}
