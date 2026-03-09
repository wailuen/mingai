"use client";

import {
  useReactTable,
  getCoreRowModel,
  createColumnHelper,
  flexRender,
} from "@tanstack/react-table";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { cn } from "@/lib/utils";
import {
  useGlossaryTerms,
  useDeleteTerm,
  type GlossaryTerm,
} from "@/lib/hooks/useGlossary";
import { VersionHistoryDrawer } from "./VersionHistoryDrawer";
import { Pencil, Trash2, History } from "lucide-react";
import { useState } from "react";

interface TermListProps {
  searchQuery: string;
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
  onEdit: (term: GlossaryTerm) => void;
}

function DeleteConfirmPopover({
  termName,
  onConfirm,
  onCancel,
  isDeleting,
}: {
  termName: string;
  onConfirm: () => void;
  onCancel: () => void;
  isDeleting: boolean;
}) {
  return (
    <div className="absolute right-0 top-full z-20 mt-1 w-64 rounded-card border border-border bg-bg-surface p-3">
      <p className="mb-3 text-sm text-text-primary">
        Delete <span className="font-semibold">{termName}</span>? This cannot be
        undone.
      </p>
      <div className="flex justify-end gap-2">
        <button
          onClick={onCancel}
          className="rounded-control border border-border px-2.5 py-1 text-xs text-text-muted transition-colors hover:bg-bg-elevated"
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          disabled={isDeleting}
          className="rounded-control bg-alert px-2.5 py-1 text-xs font-medium text-white transition-opacity disabled:opacity-30"
        >
          {isDeleting ? "Deleting..." : "Delete"}
        </button>
      </div>
    </div>
  );
}

const columnHelper = createColumnHelper<GlossaryTerm>();

export function TermList({
  searchQuery,
  statusFilter,
  pagination,
  onPaginationChange,
  onEdit,
}: TermListProps) {
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [historyTerm, setHistoryTerm] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const deleteMutation = useDeleteTerm();

  const { data, isLoading } = useGlossaryTerms(
    pagination.pageIndex + 1,
    searchQuery,
    statusFilter,
  );

  const filteredItems = data?.items ?? [];
  const totalPages = data ? Math.ceil(data.total / (data.page_size || 50)) : 1;

  function handleDelete(id: string) {
    deleteMutation.mutate(id, {
      onSuccess: () => setDeleteConfirmId(null),
    });
  }

  const columns = [
    columnHelper.accessor("term", {
      header: "Term",
      cell: (info) => (
        <span className="text-sm font-medium text-text-primary">
          {info.getValue()}
        </span>
      ),
    }),
    columnHelper.accessor("full_form", {
      header: "Full Form",
      cell: (info) => (
        <span className="text-sm text-text-muted">
          {info.getValue() ?? "\u2014"}
        </span>
      ),
    }),
    columnHelper.accessor("definition", {
      header: "Definition",
      cell: (info) => {
        const val = info.getValue();
        const truncated = val.length > 60 ? `${val.slice(0, 60)}...` : val;
        return (
          <span className="text-sm text-text-muted" title={val}>
            {truncated}
          </span>
        );
      },
    }),
    columnHelper.accessor("aliases", {
      header: "Aliases",
      cell: (info) => {
        const aliases = info.getValue();
        const count = aliases?.length ?? 0;
        return (
          <span className="font-mono text-data-value text-text-faint">
            {count}
          </span>
        );
      },
    }),
    columnHelper.accessor("is_active", {
      header: "Status",
      cell: (info) => {
        const active = info.getValue();
        return (
          <span className="flex items-center gap-1.5 text-xs">
            <span
              className={cn(
                "inline-block h-1.5 w-1.5 rounded-full",
                active ? "bg-accent" : "bg-text-faint",
              )}
            />
            <span className={active ? "text-accent" : "text-text-faint"}>
              {active ? "Active" : "Inactive"}
            </span>
          </span>
        );
      },
    }),
    columnHelper.display({
      id: "actions",
      cell: (info) => {
        const term = info.row.original;
        return (
          <div className="relative flex items-center gap-1">
            <button
              onClick={() =>
                setHistoryTerm({ id: term.id, name: term.term })
              }
              className="flex h-7 w-7 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
              aria-label={`History ${term.term}`}
            >
              <History size={14} />
            </button>
            <button
              onClick={() => onEdit(term)}
              className="flex h-7 w-7 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
              aria-label={`Edit ${term.term}`}
            >
              <Pencil size={14} />
            </button>
            <button
              onClick={() => setDeleteConfirmId(term.id)}
              className="flex h-7 w-7 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-alert-dim hover:text-alert"
              aria-label={`Delete ${term.term}`}
            >
              <Trash2 size={14} />
            </button>
            {deleteConfirmId === term.id && (
              <DeleteConfirmPopover
                termName={term.term}
                onConfirm={() => handleDelete(term.id)}
                onCancel={() => setDeleteConfirmId(null)}
                isDeleting={deleteMutation.isPending}
              />
            )}
          </div>
        );
      },
    }),
  ];

  const table = useReactTable({
    data: filteredItems,
    columns,
    pageCount: totalPages,
    state: { pagination },
    onPaginationChange,
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
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
                className="px-3.5 py-12 text-center text-sm text-text-faint"
              >
                No glossary terms yet. Add your first term or import from CSV.
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
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
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
          {data?.total ?? 0} total terms
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
            Page {pagination.pageIndex + 1} of {totalPages}
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

      {/* Version History Drawer */}
      <VersionHistoryDrawer
        termId={historyTerm?.id ?? null}
        termName={historyTerm?.name ?? ""}
        isOpen={historyTerm !== null}
        onClose={() => setHistoryTerm(null)}
      />
    </div>
  );
}
