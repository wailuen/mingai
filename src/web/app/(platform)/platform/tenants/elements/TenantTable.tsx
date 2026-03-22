"use client";

import { useCallback, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useState } from "react";
import { ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useInfiniteTenants,
  type Tenant,
} from "@/lib/hooks/usePlatformDashboard";
import { TenantStatusBadge, TenantPlanBadge } from "./TenantStatusBadge";
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";
import { useInfiniteScrollSentinel } from "@/lib/hooks/useInfiniteScrollSentinel";
import { TableRowSkeleton } from "@/components/shared/LoadingState";

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

export function TenantTable() {
  const {
    data,
    isPending,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteTenants();
  const [sorting, setSorting] = useState<SortingState>([]);

  const rows = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;

  const columns = useMemo<ColumnDef<Tenant>[]>(
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
    ],
    [],
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const handleIntersect = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const sentinelRef = useInfiniteScrollSentinel(
    handleIntersect,
    hasNextPage && !isFetchingNextPage,
  );

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load tenants: {error.message}
      </p>
    );
  }

  const footer = (
    <div className="px-5 py-2.5">
      <p className="font-mono text-data-value text-text-faint">
        {rows.length} of {total} tenants
      </p>
    </div>
  );

  return (
    <ScrollableTableWrapper footer={footer}>
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
          {isPending &&
            Array.from({ length: 8 }).map((_, i) => (
              <TableRowSkeleton key={i} columns={5} />
            ))}

          {!isPending && rows.length === 0 && (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3.5 py-12 text-center text-body-default text-text-faint"
              >
                No tenants found. Create your first tenant to get started.
              </td>
            </tr>
          )}

          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              onClick={() =>
                (window.location.href = `/platform/tenants/${row.original.id}`)
              }
              className="cursor-pointer border-b border-border-faint transition-colors hover:bg-accent-dim"
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-3.5 py-3">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}

          {/* Infinite scroll sentinel */}
          <tr>
            <td colSpan={columns.length} className="p-0">
              <div ref={sentinelRef} className="h-1" />
            </td>
          </tr>
          {isFetchingNextPage &&
            Array.from({ length: 3 }).map((_, i) => (
              <TableRowSkeleton key={`fetch-${i}`} columns={5} />
            ))}
        </tbody>
      </table>
    </ScrollableTableWrapper>
  );
}
