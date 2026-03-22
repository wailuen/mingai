"use client";

import { useCallback } from "react";
import {
  useReactTable,
  getCoreRowModel,
  createColumnHelper,
  flexRender,
} from "@tanstack/react-table";
import { useInfiniteQuery } from "@tanstack/react-query";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { apiGet, type PaginatedResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { UserActionMenu } from "./UserActionMenu";
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";
import { useInfiniteScrollSentinel } from "@/lib/hooks/useInfiniteScrollSentinel";

export interface UserRow {
  id: string;
  email: string;
  name: string;
  role: "tenant_admin" | "viewer" | "user" | "platform_admin";
  status: "active" | "invited" | "suspended" | "closed";
  last_login: string | null;
  created_at: string;
}

interface UserTableProps {
  searchQuery: string;
  roleFilter: string;
  statusFilter: string;
}

const PAGE_SIZE = 30;
const columnHelper = createColumnHelper<UserRow>();

const columns = [
  columnHelper.accessor("name", {
    header: "Name",
    cell: (info) => (
      <span className="text-body-default font-medium text-text-primary">
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
      const roleLabel =
        role === "tenant_admin"
          ? "Admin"
          : role === "platform_admin"
            ? "Platform Admin"
            : "User";
      const roleCls =
        role === "tenant_admin"
          ? "border-accent/30 bg-accent/10 text-accent"
          : role === "platform_admin"
            ? "border-warn/30 bg-warn-dim text-warn"
            : "border-border bg-bg-elevated text-text-muted";
      return (
        <span
          className={cn(
            "rounded-badge border px-2 py-0.5 text-[11px] font-medium font-mono",
            roleCls,
          )}
        >
          {roleLabel}
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
            "rounded-badge border px-2 py-0.5 text-[11px] font-medium font-mono capitalize",
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

/**
 * User directory table with infinite scroll.
 * Fetches pages of 30 users, loading more as the sentinel scrolls into view.
 */
export function UserTable({
  searchQuery,
  roleFilter,
  statusFilter,
}: UserTableProps) {
  const { data, isLoading, isFetchingNextPage, fetchNextPage, hasNextPage } =
    useInfiniteQuery({
      queryKey: ["users-infinite", searchQuery, roleFilter, statusFilter],
      queryFn: ({ pageParam = 1 }) => {
        const params = new URLSearchParams({
          page: String(pageParam),
          page_size: String(PAGE_SIZE),
        });
        if (searchQuery) params.set("search", searchQuery);
        if (roleFilter) params.set("role", roleFilter);
        if (statusFilter) params.set("status", statusFilter);
        return apiGet<PaginatedResponse<UserRow>>(
          `/api/v1/admin/users?${params.toString()}`,
        );
      },
      getNextPageParam: (lastPage) =>
        lastPage.page < lastPage.total_pages ? lastPage.page + 1 : undefined,
      initialPageParam: 1,
    });

  const rows = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const handleIntersect = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const sentinelRef = useInfiniteScrollSentinel(
    handleIntersect,
    hasNextPage && !isFetchingNextPage,
  );

  const footer = (
    <div className="px-4 py-2.5">
      <span className="font-mono text-data-value text-text-faint">
        {rows.length} of {total} users
      </span>
    </div>
  );

  return (
    <ScrollableTableWrapper footer={footer}>
      <table className="w-full">
        <thead className="sticky top-0 z-10 bg-bg-surface">
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
            Array.from({ length: 8 }).map((_, i) => (
              <TableRowSkeleton key={i} columns={6} />
            ))
          ) : rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3.5 py-8 text-center text-body-default text-text-faint"
              >
                No users yet. Invite your first team member.
              </td>
            </tr>
          ) : (
            <>
              {table.getRowModel().rows.map((row) => (
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
              ))}
              {/* Infinite scroll sentinel */}
              <tr>
                <td colSpan={columns.length} className="p-0">
                  <div ref={sentinelRef} className="h-1" />
                </td>
              </tr>
              {isFetchingNextPage &&
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRowSkeleton key={`fetch-${i}`} columns={6} />
                ))}
            </>
          )}
        </tbody>
      </table>
    </ScrollableTableWrapper>
  );
}
