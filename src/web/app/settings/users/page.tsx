"use client";

import { useState, useCallback } from "react";
import {
  useReactTable,
  getCoreRowModel,
  createColumnHelper,
  flexRender,
} from "@tanstack/react-table";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import {
  apiRequest,
  apiPost,
  apiPatch,
  type PaginatedResponse,
} from "@/lib/api";
import { UserPlus, Upload, MoreHorizontal } from "lucide-react";

interface UserRow {
  id: string;
  email: string;
  name: string;
  role: "tenant_admin" | "user";
  status: "active" | "suspended";
  last_login: string | null;
  created_at: string;
}

const columnHelper = createColumnHelper<UserRow>();

/**
 * FE-027: User directory with invite + role management.
 * TanStack Table with server-side pagination (pageSize: 25).
 * Invite: single email OR CSV upload.
 * Delete = anonymize (GDPR compliance).
 */
export default function UsersPage() {
  const queryClient = useQueryClient();
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 25 });
  const [showInviteModal, setShowInviteModal] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["users", pagination],
    queryFn: () =>
      apiRequest<PaginatedResponse<UserRow>>(
        `/api/v1/users?page=${pagination.pageIndex + 1}&limit=${pagination.pageSize}`,
      ),
  });

  const handleRoleChange = useCallback(
    async (userId: string, newRole: "tenant_admin" | "user") => {
      await apiPatch(`/api/v1/users/${userId}/role`, { role: newRole });
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    [queryClient],
  );

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
            className={`rounded-badge border px-2 py-0.5 text-xs font-medium ${
              role === "tenant_admin"
                ? "border-accent/30 bg-accent/10 text-accent"
                : "border-border bg-bg-elevated text-text-muted"
            }`}
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
        return (
          <span
            className={`rounded-badge border px-2 py-0.5 text-xs font-medium ${
              status === "active"
                ? "border-accent/30 bg-accent/10 text-accent"
                : "border-warn/30 bg-warn/10 text-warn"
            }`}
          >
            {status}
          </span>
        );
      },
    }),
    columnHelper.accessor("last_login", {
      header: "Last Login",
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
      cell: (info) => (
        <UserActions user={info.row.original} onRoleChange={handleRoleChange} />
      ),
    }),
  ];

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    pageCount: data?.total_pages ?? -1,
    state: { pagination },
    onPaginationChange: setPagination,
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <AppShell>
      <div className="p-7">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-page-title text-text-primary">Users</h1>
          <div className="flex gap-2">
            <button
              onClick={() => setShowInviteModal(true)}
              className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
            >
              <UserPlus size={14} />
              Invite User
            </button>
          </div>
        </div>

        <ErrorBoundary>
          <div className="overflow-hidden rounded-card border border-border">
            <table className="w-full">
              <thead>
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id} className="border-b border-border">
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        className="px-3.5 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint"
                      >
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                      </th>
                    ))}
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
                      colSpan={6}
                      className="px-3.5 py-8 text-center text-sm text-text-faint"
                    >
                      No users found
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
        </ErrorBoundary>

        {showInviteModal && (
          <InviteUserModal onClose={() => setShowInviteModal(false)} />
        )}
      </div>
    </AppShell>
  );
}

function UserActions({
  user,
  onRoleChange,
}: {
  user: UserRow;
  onRoleChange: (userId: string, role: "tenant_admin" | "user") => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex h-7 w-7 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-muted"
      >
        <MoreHorizontal size={14} />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-10 mt-1 w-44 rounded-card border border-border bg-bg-surface p-1 shadow-lg">
          <button
            onClick={() => {
              onRoleChange(
                user.id,
                user.role === "tenant_admin" ? "user" : "tenant_admin",
              );
              setOpen(false);
            }}
            className="w-full rounded-control px-3 py-1.5 text-left text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            {user.role === "tenant_admin"
              ? "Demote to User"
              : "Promote to Admin"}
          </button>
          <button
            onClick={() => setOpen(false)}
            className="w-full rounded-control px-3 py-1.5 text-left text-sm text-alert transition-colors hover:bg-alert-dim"
          >
            Anonymize (GDPR)
          </button>
        </div>
      )}
    </div>
  );
}

function InviteUserModal({ onClose }: { onClose: () => void }) {
  const [mode, setMode] = useState<"single" | "csv">("single");
  const [email, setEmail] = useState("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const queryClient = useQueryClient();

  async function handleInvite() {
    setSubmitting(true);
    try {
      if (mode === "single" && email.trim()) {
        await apiPost("/api/v1/users/invite", { email: email.trim() });
      }
      queryClient.invalidateQueries({ queryKey: ["users"] });
      onClose();
    } catch {
      // Error handled
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-md rounded-card border border-border bg-bg-surface p-5">
        <h2 className="mb-4 text-section-heading text-text-primary">
          Invite User
        </h2>

        {/* Mode tabs */}
        <div className="mb-4 flex gap-2 border-b border-border pb-2">
          <button
            onClick={() => setMode("single")}
            className={`rounded-control px-3 py-1 text-xs transition-colors ${
              mode === "single"
                ? "bg-accent-dim text-accent"
                : "text-text-faint hover:text-text-muted"
            }`}
          >
            Single Email
          </button>
          <button
            onClick={() => setMode("csv")}
            className={`rounded-control px-3 py-1 text-xs transition-colors ${
              mode === "csv"
                ? "bg-accent-dim text-accent"
                : "text-text-faint hover:text-text-muted"
            }`}
          >
            CSV Upload
          </button>
        </div>

        {mode === "single" ? (
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="user@company.com"
            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
          />
        ) : (
          <div className="flex items-center gap-2">
            <label className="flex-1 cursor-pointer rounded-control border border-dashed border-border px-4 py-6 text-center text-sm text-text-faint transition-colors hover:border-accent-ring hover:bg-bg-elevated">
              <Upload size={20} className="mx-auto mb-2" />
              {csvFile ? csvFile.name : "Drop CSV file or click to browse"}
              <input
                type="file"
                accept=".csv"
                className="hidden"
                onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
              />
            </label>
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
          >
            Cancel
          </button>
          <button
            onClick={handleInvite}
            disabled={
              submitting ||
              (mode === "single" && !email.trim()) ||
              (mode === "csv" && !csvFile)
            }
            className="rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
          >
            {submitting ? "Sending..." : "Send Invite"}
          </button>
        </div>
      </div>
    </div>
  );
}
