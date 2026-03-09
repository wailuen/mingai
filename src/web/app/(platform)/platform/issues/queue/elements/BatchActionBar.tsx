"use client";

import { useState } from "react";
import { CheckSquare, Route, XCircle, Loader2, UserPlus } from "lucide-react";
import { cn } from "@/lib/utils";
import { useWontFix, useAssignIssue } from "@/lib/hooks/useEngineeringIssues";
import { apiPost } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { AssignDialog } from "./AssignDialog";

interface BatchActionBarProps {
  selectedIds: string[];
  onClearSelection: () => void;
}

/**
 * FE-054: Bulk actions bar — visible when 2+ issues are selected.
 * Actions: bulk close (won't fix), bulk assign, bulk route to tenant.
 * Surfaces partial-failure counts if some mutations fail.
 */
export function BatchActionBar({
  selectedIds,
  onClearSelection,
}: BatchActionBarProps) {
  const queryClient = useQueryClient();
  const wontFixMutation = useWontFix();
  const assignMutation = useAssignIssue();
  const [isRouting, setIsRouting] = useState(false);
  const [isClosing, setIsClosing] = useState(false);
  const [isAssigning, setIsAssigning] = useState(false);
  const [showAssignDialog, setShowAssignDialog] = useState(false);
  const [partialFailure, setPartialFailure] = useState<string | null>(null);

  const isProcessing = isRouting || isClosing || isAssigning;

  async function handleBulkClose() {
    setIsClosing(true);
    setPartialFailure(null);
    const reason = "Bulk closed by platform admin";
    let failCount = 0;
    for (const id of selectedIds) {
      try {
        await wontFixMutation.mutateAsync({ id, reason });
      } catch {
        failCount++;
      }
    }
    queryClient.invalidateQueries({ queryKey: ["platform-issue-queue"] });
    if (failCount > 0) {
      setPartialFailure(
        `${selectedIds.length - failCount} of ${selectedIds.length} closed. ${failCount} failed.`,
      );
    } else {
      onClearSelection();
    }
    setIsClosing(false);
  }

  async function handleBulkAssign(email: string) {
    setShowAssignDialog(false);
    setIsAssigning(true);
    setPartialFailure(null);
    let failCount = 0;
    for (const id of selectedIds) {
      try {
        await assignMutation.mutateAsync({ id, assignee_email: email });
      } catch {
        failCount++;
      }
    }
    queryClient.invalidateQueries({ queryKey: ["platform-issue-queue"] });
    if (failCount > 0) {
      setPartialFailure(
        `${selectedIds.length - failCount} of ${selectedIds.length} assigned. ${failCount} failed.`,
      );
    } else {
      onClearSelection();
    }
    setIsAssigning(false);
  }

  async function handleBulkRoute() {
    setIsRouting(true);
    setPartialFailure(null);
    const results = await Promise.allSettled(
      selectedIds.map((id) =>
        apiPost(`/api/v1/platform/issues/${encodeURIComponent(id)}/route`, {
          notify_tenant: true,
        }),
      ),
    );
    const failCount = results.filter((r) => r.status === "rejected").length;
    queryClient.invalidateQueries({ queryKey: ["platform-issue-queue"] });
    if (failCount > 0) {
      setPartialFailure(
        `${selectedIds.length - failCount} of ${selectedIds.length} routed. ${failCount} failed.`,
      );
    } else {
      onClearSelection();
    }
    setIsRouting(false);
  }

  return (
    <>
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-3 rounded-card border border-accent/20 bg-accent-dim px-4 py-2.5">
          {/* Selection count */}
          <div className="flex items-center gap-1.5">
            <CheckSquare size={14} className="text-accent" />
            <span className="font-mono text-xs font-semibold text-accent">
              {selectedIds.length}
            </span>
            <span className="text-xs text-text-muted">selected</span>
          </div>

          <div className="mx-1 h-4 w-px bg-border" />

          {/* Bulk Route */}
          <button
            type="button"
            disabled={isProcessing}
            onClick={handleBulkRoute}
            className={cn(
              "flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-xs font-medium transition-colors",
              isProcessing
                ? "cursor-not-allowed border-border text-text-faint"
                : "border-border text-text-muted hover:border-accent-ring hover:text-text-primary",
            )}
          >
            {isRouting ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Route size={13} />
            )}
            Route to Tenant
          </button>

          {/* Bulk Assign */}
          <button
            type="button"
            disabled={isProcessing}
            onClick={() => setShowAssignDialog(true)}
            className={cn(
              "flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-xs font-medium transition-colors",
              isProcessing
                ? "cursor-not-allowed border-border text-text-faint"
                : "border-border text-text-muted hover:border-accent-ring hover:text-text-primary",
            )}
          >
            {isAssigning ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <UserPlus size={13} />
            )}
            Assign
          </button>

          {/* Bulk Close */}
          <button
            type="button"
            disabled={isProcessing}
            onClick={handleBulkClose}
            className={cn(
              "flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-xs font-medium transition-colors",
              isProcessing
                ? "cursor-not-allowed border-border text-text-faint"
                : "border-alert/30 text-alert hover:bg-alert-dim",
            )}
          >
            {isClosing ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <XCircle size={13} />
            )}
            Close Selected
          </button>

          {/* Clear */}
          <button
            type="button"
            onClick={onClearSelection}
            className="ml-auto text-xs text-text-faint transition-colors hover:text-text-primary"
          >
            Clear selection
          </button>
        </div>

        {/* Partial-failure notice */}
        {partialFailure && (
          <div className="flex items-center justify-between rounded-control border border-alert/20 bg-alert-dim px-3 py-1.5 text-xs text-alert">
            <span>{partialFailure}</span>
            <button
              type="button"
              onClick={() => {
                setPartialFailure(null);
                onClearSelection();
              }}
              className="ml-4 text-text-faint hover:text-text-primary"
            >
              Dismiss
            </button>
          </div>
        )}
      </div>

      {showAssignDialog && (
        <AssignDialog
          count={selectedIds.length}
          onConfirm={handleBulkAssign}
          onClose={() => setShowAssignDialog(false)}
        />
      )}
    </>
  );
}
