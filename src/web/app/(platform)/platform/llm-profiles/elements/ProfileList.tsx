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
import { ArrowUpDown, Pencil, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useLLMProfiles,
  useDeleteLLMProfile,
  type LLMProfile,
} from "@/lib/hooks/useLLMProfiles";

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
      {Array.from({ length: 4 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          <td className="px-3.5 py-3">
            <div className="h-4 w-36 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          <td className="px-3.5 py-3">
            <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          <td className="px-3.5 py-3">
            <div className="h-4 w-28 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          <td className="px-3.5 py-3">
            <div className="h-4 w-24 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          <td className="px-3.5 py-3">
            <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
          </td>
          <td className="px-3.5 py-3">
            <div className="h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" />
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

function DefaultBadge({ isDefault }: { isDefault: boolean }) {
  if (!isDefault) return null;
  return (
    <span className="ml-2 inline-block rounded-badge bg-accent-dim px-2 py-0.5 font-mono text-[10px] uppercase text-accent">
      default
    </span>
  );
}

interface ProfileListProps {
  onEdit: (profile: LLMProfile) => void;
}

export function ProfileList({ onEdit }: ProfileListProps) {
  const { data, isPending, error } = useLLMProfiles();
  const deleteMutation = useDeleteLLMProfile();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  function handleDelete(profile: LLMProfile) {
    if (
      !window.confirm(
        `Delete profile "${profile.name}"? This cannot be undone.`,
      )
    ) {
      return;
    }
    setDeletingId(profile.id);
    deleteMutation.mutate(profile.id, {
      onSettled: () => setDeletingId(null),
    });
  }

  const columns = useMemo<ColumnDef<LLMProfile>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Name",
        cell: (info) => (
          <span className="text-body-default font-medium text-text-primary">
            {info.getValue<string>()}
            <DefaultBadge isDefault={info.row.original.is_default} />
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "provider",
        header: "Provider",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            {info.getValue<string>()}
          </span>
        ),
        enableSorting: true,
      },
      {
        accessorKey: "primary_model",
        header: "Primary Model",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            {info.getValue<string>()}
          </span>
        ),
        enableSorting: false,
      },
      {
        accessorKey: "intent_model",
        header: "Intent Model",
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
        enableSorting: true,
      },
      {
        id: "actions",
        header: "Actions",
        cell: (info) => {
          const profile = info.row.original;
          const isDeleting = deletingId === profile.id;
          return (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onEdit(profile)}
                className="inline-flex items-center gap-1 rounded-control border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                <Pencil size={12} />
                Edit
              </button>
              <button
                type="button"
                disabled={isDeleting}
                onClick={() => handleDelete(profile)}
                className="inline-flex items-center gap-1 rounded-control border border-border px-2 py-1 text-[11px] text-alert transition-colors hover:bg-alert-dim disabled:opacity-40"
              >
                <Trash2 size={12} />
                {isDeleting ? "..." : "Delete"}
              </button>
            </div>
          );
        },
        enableSorting: false,
      },
    ],
    [deletingId, onEdit],
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
        Failed to load LLM profiles: {error.message}
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
                  No LLM profiles found. Create your first profile to get
                  started.
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

      {data && data.length > 0 && (
        <div className="border-t border-border px-5 py-2.5">
          <p className="font-mono text-data-value text-text-faint">
            {data.length} profile{data.length !== 1 ? "s" : ""}
          </p>
        </div>
      )}
    </div>
  );
}
