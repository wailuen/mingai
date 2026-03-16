"use client";

import { useState, useEffect } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  UserPlus,
  MessageSquare,
  ArrowUpRight,
  Copy,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useAcceptIssue,
  useWontFix,
  useRouteIssue,
  type PlatformIssue,
} from "@/lib/hooks/useEngineeringIssues";

// ---------------------------------------------------------------------------
// IssueActionBar
// ---------------------------------------------------------------------------

interface IssueActionBarProps {
  selectedIssue: PlatformIssue | null;
  onOverrideSeverity: () => void;
  onRequestInfo: () => void;
  onAssign: () => void;
  onCloseDuplicate: () => void;
}

export function IssueActionBar({
  selectedIssue,
  onOverrideSeverity,
  onRequestInfo,
  onAssign,
  onCloseDuplicate,
}: IssueActionBarProps) {
  const acceptMutation = useAcceptIssue();
  const wontFixMutation = useWontFix();
  const routeMutation = useRouteIssue();
  const [showWontFixConfirm, setShowWontFixConfirm] = useState(false);
  const [showRouteConfirm, setShowRouteConfirm] = useState(false);

  // Reset confirm states when the selected issue changes to prevent
  // accidental destructive actions on the wrong issue.
  useEffect(() => {
    setShowWontFixConfirm(false);
    setShowRouteConfirm(false);
  }, [selectedIssue?.id]);

  const disabled = !selectedIssue;
  const isProcessing =
    acceptMutation.isPending ||
    wontFixMutation.isPending ||
    routeMutation.isPending;

  function handleAccept() {
    if (!selectedIssue) return;
    acceptMutation.mutate({ id: selectedIssue.id });
  }

  function handleWontFix() {
    if (!selectedIssue) return;
    if (!showWontFixConfirm) {
      setShowWontFixConfirm(true);
      return;
    }
    wontFixMutation.mutate(
      { id: selectedIssue.id, reason: "Marked as won't fix by platform admin" },
      { onSuccess: () => setShowWontFixConfirm(false) },
    );
  }

  function handleRoute() {
    if (!selectedIssue) return;
    if (!showRouteConfirm) {
      setShowRouteConfirm(true);
      return;
    }
    routeMutation.mutate(
      { id: selectedIssue.id, notify_tenant: true },
      { onSuccess: () => setShowRouteConfirm(false) },
    );
  }

  return (
    <div className="flex items-center gap-2 rounded-card border border-border bg-bg-surface px-4 py-2.5">
      <span className="mr-2 text-[11px] font-medium uppercase tracking-wider text-text-faint">
        Actions
      </span>

      {/* Accept */}
      <button
        type="button"
        disabled={disabled || isProcessing}
        onClick={handleAccept}
        className={cn(
          "flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-xs font-medium transition-colors",
          disabled
            ? "cursor-not-allowed border-border bg-bg-elevated text-text-faint"
            : "border-accent/30 text-accent hover:bg-accent-dim",
        )}
      >
        <CheckCircle2 size={14} />
        {acceptMutation.isPending ? "Accepting..." : "Accept"}
      </button>

      {/* Override Severity */}
      <button
        type="button"
        disabled={disabled}
        onClick={onOverrideSeverity}
        className={cn(
          "flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-xs font-medium transition-colors",
          disabled
            ? "cursor-not-allowed border-border bg-bg-elevated text-text-faint"
            : "border-warn/30 text-warn hover:bg-warn-dim",
        )}
      >
        <AlertTriangle size={14} />
        Override Severity
      </button>

      {/* Assign */}
      <button
        type="button"
        disabled={disabled}
        onClick={onAssign}
        className={cn(
          "flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-xs font-medium transition-colors",
          disabled
            ? "cursor-not-allowed border-border bg-bg-elevated text-text-faint"
            : "border-border text-text-muted hover:border-accent-ring hover:text-text-primary",
        )}
      >
        <UserPlus size={14} />
        Assign
      </button>

      {/* Request Info */}
      <button
        type="button"
        disabled={disabled}
        onClick={onRequestInfo}
        className={cn(
          "flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-xs font-medium transition-colors",
          disabled
            ? "cursor-not-allowed border-border bg-bg-elevated text-text-faint"
            : "border-border text-text-muted hover:border-accent-ring hover:text-text-primary",
        )}
      >
        <MessageSquare size={14} />
        Request Info
      </button>

      {/* Route to Tenant */}
      <button
        type="button"
        disabled={disabled || isProcessing}
        onClick={handleRoute}
        className={cn(
          "flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-xs font-medium transition-colors",
          disabled
            ? "cursor-not-allowed border-border bg-bg-elevated text-text-faint"
            : showRouteConfirm
              ? "border-accent bg-accent-dim text-accent"
              : "border-border text-text-muted hover:border-accent-ring hover:text-text-primary",
        )}
      >
        <ArrowUpRight size={14} />
        {showRouteConfirm
          ? "Confirm Route"
          : routeMutation.isPending
            ? "Routing..."
            : "Route to Tenant"}
      </button>

      {/* Close as Duplicate */}
      <button
        type="button"
        disabled={disabled}
        onClick={onCloseDuplicate}
        className={cn(
          "flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-xs font-medium transition-colors",
          disabled
            ? "cursor-not-allowed border-border bg-bg-elevated text-text-faint"
            : "border-border text-text-muted hover:border-accent-ring hover:text-text-primary",
        )}
      >
        <Copy size={14} />
        Close as Duplicate
      </button>

      {/* Won't Fix (destructive) */}
      <button
        type="button"
        disabled={disabled || isProcessing}
        onClick={handleWontFix}
        className={cn(
          "ml-auto flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-xs font-medium transition-colors",
          disabled
            ? "cursor-not-allowed border-border bg-bg-elevated text-text-faint"
            : showWontFixConfirm
              ? "border-alert bg-alert/15 text-alert"
              : "border-alert/30 text-alert hover:bg-alert-dim",
        )}
      >
        <XCircle size={14} />
        {showWontFixConfirm
          ? "Confirm Won't Fix"
          : wontFixMutation.isPending
            ? "Closing..."
            : "Won't Fix"}
      </button>
    </div>
  );
}
