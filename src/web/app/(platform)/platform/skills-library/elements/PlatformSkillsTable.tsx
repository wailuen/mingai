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
import {
  ArrowUpDown,
  Lock,
  Pencil,
  Trash2,
  BookDown,
  ToggleLeft,
  ToggleRight,
  CheckCircle2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";
import {
  usePlatformSkillsAdmin,
  usePublishPlatformSkill,
  useDeprecatePlatformSkill,
  useMandatePlatformSkill,
  useRemoveMandatePlatformSkill,
  useDeletePlatformSkill,
  type PlatformSkillAdmin,
} from "@/lib/hooks/usePlatformSkillsAdmin";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          {Array.from({ length: 7 }).map((__, j) => (
            <td key={j} className="px-3.5 py-3">
              <div className="h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

function SortHeader({
  label,
  canSort,
  sorted,
  onClick,
}: {
  label: string;
  canSort: boolean;
  sorted: false | "asc" | "desc";
  onClick: () => void;
}) {
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

function StatusBadge({ status }: { status: PlatformSkillAdmin["status"] }) {
  const styles =
    status === "published"
      ? "border-accent/30 bg-accent/10 text-accent"
      : status === "deprecated"
        ? "border-border bg-bg-elevated text-text-faint"
        : "border-warn/30 bg-warn/10 text-warn";

  return (
    <span
      className={cn(
        "inline-block rounded-badge border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider",
        styles,
      )}
    >
      {status}
    </span>
  );
}

function PatternBadge({
  pattern,
}: {
  pattern: PlatformSkillAdmin["execution_pattern"];
}) {
  const labels: Record<PlatformSkillAdmin["execution_pattern"], string> = {
    prompt: "Prompt",
    tool_composing: "Tool",
    sequential_pipeline: "Pipeline",
  };

  return (
    <span className="font-mono text-data-value text-text-faint">
      {labels[pattern]}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Row actions
// ---------------------------------------------------------------------------

interface RowActionsProps {
  skill: PlatformSkillAdmin;
  onEdit: (skill: PlatformSkillAdmin) => void;
}

function RowActions({ skill, onEdit }: RowActionsProps) {
  const { mutate: publish, isPending: isPublishing } =
    usePublishPlatformSkill();
  const { mutate: deprecate, isPending: isDeprecating } =
    useDeprecatePlatformSkill();
  const { mutate: mandate, isPending: isMandating } = useMandatePlatformSkill();
  const { mutate: removeMandate, isPending: isRemovingMandate } =
    useRemoveMandatePlatformSkill();
  const { mutate: deleteDraft, isPending: isDeleting } =
    useDeletePlatformSkill();

  const isLoading =
    isPublishing ||
    isDeprecating ||
    isMandating ||
    isRemovingMandate ||
    isDeleting;

  return (
    <div
      className="flex items-center gap-1"
      onClick={(e) => e.stopPropagation()}
    >
      {/* Edit — always available */}
      <button
        type="button"
        title="Edit"
        onClick={() => onEdit(skill)}
        className="rounded p-1.5 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
      >
        <Pencil size={13} />
      </button>

      {/* Draft-only: Publish + Delete */}
      {skill.status === "draft" && (
        <>
          <button
            type="button"
            title="Publish"
            disabled={isLoading}
            onClick={() => publish({ id: skill.id })}
            className="rounded p-1.5 text-text-faint transition-colors hover:bg-accent-dim hover:text-accent disabled:opacity-50"
          >
            <CheckCircle2 size={13} />
          </button>
          <button
            type="button"
            title="Delete draft"
            disabled={isLoading}
            onClick={() => deleteDraft(skill.id)}
            className="rounded p-1.5 text-text-faint transition-colors hover:bg-alert-dim hover:text-alert disabled:opacity-50"
          >
            <Trash2 size={13} />
          </button>
        </>
      )}

      {/* Published-only: Deprecate + Toggle mandatory */}
      {skill.status === "published" && (
        <>
          <button
            type="button"
            title="Deprecate"
            disabled={isLoading}
            onClick={() => deprecate(skill.id)}
            className="rounded p-1.5 text-text-faint transition-colors hover:bg-alert-dim hover:text-alert disabled:opacity-50"
          >
            <BookDown size={13} />
          </button>
          {skill.mandatory ? (
            <button
              type="button"
              title="Remove mandatory"
              disabled={isLoading}
              onClick={() => removeMandate(skill.id)}
              className="rounded p-1.5 text-alert transition-colors hover:bg-alert-dim disabled:opacity-50"
            >
              <ToggleRight size={13} />
            </button>
          ) : (
            <button
              type="button"
              title="Mark mandatory"
              disabled={isLoading}
              onClick={() => mandate(skill.id)}
              className="rounded p-1.5 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-50"
            >
              <ToggleLeft size={13} />
            </button>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main table
// ---------------------------------------------------------------------------

interface PlatformSkillsTableProps {
  statusFilter: "all" | "draft" | "published" | "deprecated";
  onEdit: (skill: PlatformSkillAdmin) => void;
}

export function PlatformSkillsTable({
  statusFilter,
  onEdit,
}: PlatformSkillsTableProps) {
  const { data, isPending, error } = usePlatformSkillsAdmin(
    statusFilter === "all" ? undefined : statusFilter,
  );
  const [sorting, setSorting] = useState<SortingState>([]);

  const items = useMemo(() => data?.items ?? [], [data]);

  const columns = useMemo<ColumnDef<PlatformSkillAdmin>[]>(
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
        accessorKey: "execution_pattern",
        header: "Pattern",
        cell: (info) => (
          <PatternBadge
            pattern={info.getValue<PlatformSkillAdmin["execution_pattern"]>()}
          />
        ),
        enableSorting: false,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: (info) => (
          <StatusBadge status={info.getValue<PlatformSkillAdmin["status"]>()} />
        ),
        enableSorting: true,
      },
      {
        accessorKey: "version",
        header: "Version",
        cell: (info) => (
          <span className="font-mono text-data-value text-text-muted">
            {info.row.original.version_label
              ? info.row.original.version_label
              : `v${info.getValue<number>()}`}
          </span>
        ),
        enableSorting: false,
      },
      {
        accessorKey: "mandatory",
        header: "Mandatory",
        cell: (info) =>
          info.getValue<boolean>() ? (
            <span className="flex items-center gap-1 text-alert">
              <Lock size={11} />
              <span className="text-body-default">Mandatory</span>
            </span>
          ) : (
            <span className="text-body-default text-text-faint">—</span>
          ),
        enableSorting: false,
      },
      {
        accessorKey: "adoption_count",
        header: "Adoption",
        cell: (info) => {
          const val = info.getValue<number | undefined>();
          if (val == null)
            return <span className="text-body-default text-text-faint">—</span>;
          return (
            <span className="font-mono text-data-value text-text-muted">
              {val.toLocaleString()}
            </span>
          );
        },
        enableSorting: true,
      },
      {
        id: "actions",
        header: "Actions",
        cell: (info) => (
          <RowActions skill={info.row.original} onEdit={onEdit} />
        ),
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
        Failed to load skills: {error.message}
      </p>
    );
  }

  return (
    <ScrollableTableWrapper
      footer={
        data && items.length > 0 ? (
          <div className="px-5 py-2.5">
            <p className="font-mono text-data-value text-text-faint">
              Showing {items.length} of {data.total} skills
            </p>
          </div>
        ) : undefined
      }
    >
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
          {isPending && <SkeletonRows />}

          {data && items.length === 0 && (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3.5 py-12 text-center text-body-default text-text-faint"
              >
                No skills found
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
    </ScrollableTableWrapper>
  );
}
