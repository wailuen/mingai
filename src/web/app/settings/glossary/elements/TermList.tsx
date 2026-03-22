"use client";

import { useCallback } from "react";
import {
  useReactTable,
  getCoreRowModel,
  createColumnHelper,
  flexRender,
} from "@tanstack/react-table";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { cn } from "@/lib/utils";
import {
  useInfiniteGlossaryTerms,
  useDeleteTerm,
  type GlossaryTerm,
} from "@/lib/hooks/useGlossary";
import { VersionHistoryDrawer } from "./VersionHistoryDrawer";
import { Pencil, Trash2, History } from "lucide-react";
import { useState } from "react";
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";
import { useInfiniteScrollSentinel } from "@/lib/hooks/useInfiniteScrollSentinel";

interface TermListProps {
  searchQuery: string;
  statusFilter: string;
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
      <p className="mb-3 text-body-default text-text-primary">
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

export function TermList({ searchQuery, statusFilter, onEdit }: TermListProps) {
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [historyTerm, setHistoryTerm] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const deleteMutation = useDeleteTerm();

  const { data, isLoading, isFetchingNextPage, fetchNextPage, hasNextPage } =
    useInfiniteGlossaryTerms(searchQuery, statusFilter);

  const rows = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;

  function handleDelete(id: string) {
    deleteMutation.mutate(id, {
      onSuccess: () => setDeleteConfirmId(null),
    });
  }

  const columns = [
    columnHelper.accessor("term", {
      header: "Term",
      cell: (info) => (
        <span className="text-body-default font-medium text-text-primary">
          {info.getValue()}
        </span>
      ),
    }),
    columnHelper.accessor("definition", {
      header: "Full Form / Definition",
      meta: { hideOnMobile: true },
      cell: (info) => {
        const val = info.getValue() ?? "";
        const truncated = val.length > 60 ? `${val.slice(0, 60)}...` : val;
        return (
          <span className="text-body-default text-text-muted" title={val}>
            {truncated || "\u2014"}
          </span>
        );
      },
    }),
    columnHelper.accessor("aliases", {
      header: "Aliases",
      meta: { hideOnMobile: true },
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
              onClick={() => setHistoryTerm({ id: term.id, name: term.term })}
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
      <span className="font-mono text-xs text-text-faint">
        {rows.length} of {total} terms
      </span>
    </div>
  );

  return (
    <>
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
                <TableRowSkeleton key={i} columns={5} />
              ))
            ) : rows.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="px-3.5 py-12 text-center text-body-default text-text-faint"
                >
                  No glossary terms yet. Add your first term or import from CSV.
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
                  <td colSpan={5} className="p-0">
                    <div ref={sentinelRef} className="h-1" />
                  </td>
                </tr>
                {isFetchingNextPage &&
                  Array.from({ length: 3 }).map((_, i) => (
                    <TableRowSkeleton key={`fetch-${i}`} columns={5} />
                  ))}
              </>
            )}
          </tbody>
        </table>
      </ScrollableTableWrapper>

      <VersionHistoryDrawer
        termId={historyTerm?.id ?? null}
        termName={historyTerm?.name ?? ""}
        isOpen={historyTerm !== null}
        onClose={() => setHistoryTerm(null)}
      />
    </>
  );
}
