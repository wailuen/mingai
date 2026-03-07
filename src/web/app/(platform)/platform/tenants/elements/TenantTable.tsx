"use client";

import { useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useState } from "react";
import { ArrowUpDown, Eye } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTenants, type Tenant } from "@/lib/hooks/usePlatformDashboard";
import { TenantStatusBadge, TenantPlanBadge } from "./TenantStatusBadge";

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

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          <td className="px-3.5 py-3">
            <div className="h-4 w-32 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          <td className="px-3.5 py-3">
            <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          <td className="px-3.5 py-3">
            <div className="h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          <td className="px-3.5 py-3">
            <div className="h-4 w-40 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          <td className="px-3.5 py-3">
            <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
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

export function TenantTable() {
  const { data, isPending, error } = useTenants();
  const [sorting, setSorting] = useState<SortingState>([]);

  const columns = useMemo<ColumnDef<Tenant>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Name",
        cell: (info) => (
          <span className="text-[13px] font-medium text-text-primary">
            {info.getValue<string>()}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "plan",
        header: "Plan",
        cell: (info) => <TenantPlanBadge plan={info.getValue<string>()} />,
        enableSorting: true,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: (info) => <TenantStatusBadge status={info.getValue<string>()} />,
        enableSorting: true,
      },
      {
        accessorKey: "primary_contact_email",
        header: "Contact",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
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
        enableSorting: false,
      },
      {
        id: "actions",
        header: "Actions",
        cell: (info) => (
          <a
            href={`/platform/tenants/${info.row.original.id}`}
            className="inline-flex items-center gap-1 rounded-control border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <Eye size={12} />
            View
          </a>
        ),
        enableSorting: false,
      },
    ],
    [],
  );

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load tenants: {error.message}
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

            {data && data.items.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-3.5 py-12 text-center text-sm text-text-faint"
                >
                  No tenants found. Create your first tenant to get started.
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

      {/* Pagination info */}
      {data && data.total > 0 && (
        <div className="border-t border-border px-5 py-2.5">
          <p className="font-mono text-[11px] text-text-faint">
            Showing {data.items.length} of {data.total} tenants
          </p>
        </div>
      )}
    </div>
  );
}
