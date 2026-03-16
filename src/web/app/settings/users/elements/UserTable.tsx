"use client";

import {
  useReactTable,
  getCoreRowModel,
  createColumnHelper,
  flexRender,
} from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { apiGet, type PaginatedResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { UserActionMenu } from "./UserActionMenu";

export interface UserRow {
  id: string;
  email: string;
  name: string;
  role: "tenant_admin" | "viewer" | "user";
  status: "active" | "invited" | "suspended" | "closed";
  last_login: string | null;
  created_at: string;
}

interface UserTableProps {
  searchQuery: string;
  roleFilter: string;
  statusFilter: string;
  pagination: { pageIndex: number; pageSize: number };
  onPaginationChange: (
    updater:
      | { pageIndex: number; pageSize: number }
      | ((prev: { pageIndex: number; pageSize: number }) => {
          pageIndex: number;
          pageSize: number;
        }),
  ) => void;
}

const columnHelper = createColumnHelper<UserRow>();

/**
 * User directory table with server-side pagination.
 * Sort by name, email, role, last login.
 * One API call -- all filtering/pagination is server-side.
 */
export function UserTable({
  searchQuery,
  roleFilter,
  statusFilter,
  pagination,
  onPaginationChange,
}: UserTableProps) {
  const queryParams = new URLSearchParams({
    page: String(pagination.pageIndex + 1),
    page_size: String(pagination.pageSize),
  });
  if (searchQuery) queryParams.set("search", searchQuery);
  if (roleFilter) queryParams.set("role", roleFilter);
  if (statusFilter) queryParams.set("status", statusFilter);

  const { data, isLoading } = useQuery({
    queryKey: ["users", pagination, searchQuery, roleFilter, statusFilter],
    queryFn: () =>
      apiGet<PaginatedResponse<UserRow>>(
        `/api/v1/admin/users?${queryParams.toString()}`,
      ),
  });

  const columns = [
    columnHelper.accessor("name", {
      header: "Name",
      cell: (info) => (
        <span className="text-sm font-medium text-text-primary">
          {info.getValue()}
        </span>
      ),
    }),
    columnHelper.accessor("email", {
      header: "Email",
      meta: { hideOnMobile: true },
      cell: (info) => (
        <span className="font-mono text-data-value text-text-muted">
          {info.getValue()}
        </span>
      ),
    }),
    columnHelper.accessor("role", {
      header: "Role",
      cell: (info) => {
        const role = info.getValue();
        return (
          <span
            className={cn(
              "rounded-badge border px-2 py-0.5 text-xs font-medium",
              role === "tenant_admin"
                ? "border-accent/30 bg-accent/10 text-accent"
                : "border-border bg-bg-elevated text-text-muted",
            )}
          >
            {role === "tenant_admin" ? "Admin" : "User"}
          </span>
        );
      },
    }),
    columnHelper.accessor("status", {
      header: "Status",
      cell: (info) => {
        const status = info.getValue();
        const cls =
          status === "active"
            ? "border-accent/30 bg-accent/10 text-accent"
            : status === "invited"
              ? "border-warn/30 bg-warn-dim text-warn"
              : "border-alert/30 bg-alert/10 text-alert";
        return (
          <span
            className={cn(
              "rounded-badge border px-2 py-0.5 text-xs font-medium capitalize",
              cls,
            )}
          >
            {status}
          </span>
        );
      },
    }),
    columnHelper.accessor("last_login", {
      header: "Last Login",
      meta: { hideOnMobile: true },
      cell: (info) => {
        const val = info.getValue();
        return (
          <span className="font-mono text-data-value text-text-faint">
            {val ? new Date(val).toLocaleDateString() : "Never"}
          </span>
        );
      },
    }),
    columnHelper.display({
      id: "actions",
      cell: (info) => <UserActionMenu user={info.row.original} />,
    }),
  ];

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    pageCount: data?.total_pages ?? -1,
    state: { pagination },
    onPaginationChange: (updater) => {
      if (typeof updater === "function") {
        onPaginationChange(updater);
      } else {
        onPaginationChange(updater);
      }
    },
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="overflow-x-auto rounded-card border border-border">
      <table className="w-full">
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id} className="border-b border-border">
              {headerGroup.headers.map((header) => {
                const hideOnMobile = (
                  header.column.columnDef.meta as
                    | { hideOnMobile?: boolean }
                    | undefined
                )?.hideOnMobile;
                return (
                  <th
                    key={header.id}
                    className={cn(
                      "px-3.5 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint",
                      hideOnMobile && "hidden sm:table-cell",
                    )}
                  >
                    {flexRender(
                      header.column.columnDef.header,
                      header.getContext(),
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {isLoading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <TableRowSkeleton key={i} columns={6} />
            ))
          ) : table.getRowModel().rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3.5 py-8 text-center text-sm text-text-faint"
              >
                No users yet. Invite your first team member.
              </td>
            </tr>
          ) : (
            table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className="border-b border-border-faint transition-colors hover:bg-accent-dim"
              >
                {row.getVisibleCells().map((cell) => {
                  const hideOnMobile = (
                    cell.column.columnDef.meta as
                      | { hideOnMobile?: boolean }
                      | undefined
                  )?.hideOnMobile;
                  return (
                    <td
                      key={cell.id}
                      className={cn(
                        "px-3.5 py-3",
                        hideOnMobile && "hidden sm:table-cell",
                      )}
                    >
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </td>
                  );
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>

      {/* Pagination */}
      <div className="flex items-center justify-between border-t border-border px-4 py-3">
        <span className="font-mono text-xs text-text-faint">
          {data?.total ?? 0} total users
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
            className="rounded-control border border-border px-2.5 py-1 text-xs text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-30"
          >
            Previous
          </button>
          <span className="flex items-center px-2 font-mono text-xs text-text-faint">
            Page {pagination.pageIndex + 1} of {data?.total_pages ?? 1}
          </span>
          <button
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
            className="rounded-control border border-border px-2.5 py-1 text-xs text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-30"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
