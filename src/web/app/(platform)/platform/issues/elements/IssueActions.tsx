"use client";

import { useState } from "react";
import { Send, XCircle, MessageCircle } from "lucide-react";
import {
  useRouteIssue,
  useCloseIssue,
  useRequestMoreInfo,
} from "@/lib/hooks/usePlatformIssues";

interface IssueActionsProps {
  issueId: string;
  onActionComplete: () => void;
}

export function IssueActions({ issueId, onActionComplete }: IssueActionsProps) {
  const routeMutation = useRouteIssue();
  const closeMutation = useCloseIssue();
  const requestInfoMutation = useRequestMoreInfo();
  const [closeNote, setCloseNote] = useState("");
  const [showCloseInput, setShowCloseInput] = useState(false);

  const isAnyLoading =
    routeMutation.isPending ||
    closeMutation.isPending ||
    requestInfoMutation.isPending;

  function handleRoute() {
    routeMutation.mutate(issueId, {
      onSuccess: onActionComplete,
    });
  }

  function handleClose() {
    if (!showCloseInput) {
      setShowCloseInput(true);
      return;
    }
    closeMutation.mutate(
      { id: issueId, note: closeNote || "Closed as duplicate" },
      {
        onSuccess: () => {
          setShowCloseInput(false);
          setCloseNote("");
          onActionComplete();
        },
      },
    );
  }

  function handleRequestInfo() {
    requestInfoMutation.mutate(issueId, {
      onSuccess: onActionComplete,
    });
  }

  return (
    <div className="space-y-3">
      {/* Close note input */}
      {showCloseInput && (
        <div className="space-y-2">
          <input
            type="text"
            value={closeNote}
            onChange={(e) => setCloseNote(e.target.value)}
            placeholder="Reason for closing..."
            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
          />
        </div>
      )}

      {/* Error display */}
      {(routeMutation.error ||
        closeMutation.error ||
        requestInfoMutation.error) && (
        <p className="text-xs text-alert">
          {routeMutation.error?.message ||
            closeMutation.error?.message ||
            requestInfoMutation.error?.message}
        </p>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleRoute}
          disabled={isAnyLoading}
          className="inline-flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-[11px] font-semibold text-bg-base transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Send size={12} />
          Route to Tenant
        </button>

        <button
          type="button"
          onClick={handleClose}
          disabled={isAnyLoading}
          className="inline-flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-[11px] font-medium text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <XCircle size={12} />
          {showCloseInput ? "Confirm Close" : "Close"}
        </button>

        <button
          type="button"
          onClick={handleRequestInfo}
          disabled={isAnyLoading}
          className="inline-flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-[11px] font-medium text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <MessageCircle size={12} />
          Request Info
        </button>
      </div>
    </div>
  );
}
