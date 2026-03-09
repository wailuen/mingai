"use client";

import {
  useReactTable,
  getCoreRowModel,
  createColumnHelper,
  flexRender,
} from "@tanstack/react-table";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { useTeams, useDeleteTeam, type Team } from "@/lib/hooks/useTeams";
import { Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

interface TeamListProps {
  onEdit: (team: Team) => void;
  onSelect: (teamId: string, teamName: string) => void;
}

function DeleteConfirmPopover({
  teamName,
  onConfirm,
  onCancel,
  isDeleting,
}: {
  teamName: string;
  onConfirm: () => void;
  onCancel: () => void;
  isDeleting: boolean;
}) {
  return (
    <div className="absolute right-0 top-full z-20 mt-1 w-64 rounded-card border border-border bg-bg-surface p-3">
      <p className="mb-3 text-sm text-text-primary">
        Delete <span className="font-semibold">{teamName}</span>? This cannot be
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

const columnHelper = createColumnHelper<Team>();

export function TeamList({ onEdit, onSelect }: TeamListProps) {
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const deleteMutation = useDeleteTeam();

  const { data, isLoading } = useTeams();
  const teams = data ?? [];

  function handleDelete(id: string) {
    deleteMutation.mutate(id, {
      onSuccess: () => setDeleteConfirmId(null),
    });
  }

  const columns = [
    columnHelper.accessor("name", {
      header: "Name",
      cell: (info) => (
        <button
          onClick={() => onSelect(info.row.original.id, info.row.original.name)}
          className="text-sm font-medium text-text-primary transition-colors hover:text-accent"
        >
          {info.getValue()}
        </button>
      ),
    }),
    columnHelper.accessor("description", {
      header: "Description",
      cell: (info) => {
        const val = info.getValue();
        if (!val)
          return <span className="text-sm text-text-faint">{"\u2014"}</span>;
        const truncated = val.length > 60 ? `${val.slice(0, 60)}...` : val;
        return (
          <span className="text-sm text-text-muted" title={val}>
            {truncated}
          </span>
        );
      },
    }),
    columnHelper.accessor("member_count", {
      header: "Members",
      cell: (info) => (
        <span className="font-mono text-data-value text-text-primary">
          {info.getValue()}
        </span>
      ),
    }),
    columnHelper.display({
      id: "source",
      header: "Source",
      cell: (info) => {
        const source = info.row.original.source ?? "manual";
        const label = source === "auth0_sync" ? "Auth0" : "Manual";
        return (
          <span className="rounded-badge border border-border bg-bg-elevated px-1.5 py-0.5 text-[10px] text-text-faint">
            {label}
          </span>
        );
      },
    }),
    columnHelper.display({
      id: "actions",
      cell: (info) => {
        const team = info.row.original;
        return (
          <div className="relative flex items-center gap-1">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onEdit(team);
              }}
              className="flex h-7 w-7 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
              aria-label={`Edit ${team.name}`}
            >
              <Pencil size={14} />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setDeleteConfirmId(team.id);
              }}
              className="flex h-7 w-7 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-alert-dim hover:text-alert"
              aria-label={`Delete ${team.name}`}
            >
              <Trash2 size={14} />
            </button>
            {deleteConfirmId === team.id && (
              <DeleteConfirmPopover
                teamName={team.name}
                onConfirm={() => handleDelete(team.id)}
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
    data: teams,
    columns,
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
              <TableRowSkeleton key={i} columns={5} />
            ))
          ) : table.getRowModel().rows.length === 0 ? (
            <tr>
              <td
                colSpan={5}
                className="px-3.5 py-12 text-center text-sm text-text-faint"
              >
                No teams yet. Create your first team.
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

      {/* Footer count */}
      <div className="flex items-center border-t border-border px-4 py-3">
        <span className="font-mono text-xs text-text-faint">
          {teams.length} total teams
        </span>
      </div>
    </div>
  );
}
