"use client";

import { useState } from "react";
import {
  MessageSquare,
  CheckCircle,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { useUpdateIssue } from "@/lib/hooks/useAnalytics";
import type { Issue } from "@/lib/hooks/useAnalytics";

interface IssueResponseWorkflowProps {
  issue: Issue | null;
}

type WorkflowAction = "respond" | "resolve" | "escalate" | null;

const ESCALATE_SEVERITY_OPTIONS: Issue["severity"][] = [
  "P0",
  "P1",
  "P2",
  "P3",
  "P4",
];

/**
 * FE-037: Issue response workflow actions.
 *
 * Three actions: Respond to Reporter, Resolve with Note, Escalate to Platform.
 * Shows inline forms for resolve (note) and escalate (confirmation + severity).
 * Requires an issue to be selected; disabled state otherwise.
 */
export function IssueResponseWorkflow({ issue }: IssueResponseWorkflowProps) {
  const [activeAction, setActiveAction] = useState<WorkflowAction>(null);
  const [resolveNote, setResolveNote] = useState("");
  const [escalateSeverity, setEscalateSeverity] =
    useState<Issue["severity"]>("P1");
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  const updateMutation = useUpdateIssue();

  function resetState() {
    setActiveAction(null);
    setResolveNote("");
    setEscalateSeverity("P1");
    setError("");
    setSuccessMessage("");
  }

  async function handleResolve() {
    if (!issue) return;
    if (!resolveNote.trim()) {
      setError("Resolution note is required");
      return;
    }
    setError("");

    try {
      await updateMutation.mutateAsync({
        id: issue.id,
        payload: {
          status: "resolved",
          resolution_note: resolveNote.trim(),
        },
      });
      setSuccessMessage("Issue resolved successfully");
      setActiveAction(null);
      setResolveNote("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to resolve issue");
    }
  }

  async function handleEscalate() {
    if (!issue) return;
    setError("");

    try {
      await updateMutation.mutateAsync({
        id: issue.id,
        payload: {
          status: "escalated",
          severity: escalateSeverity,
        },
      });
      setSuccessMessage("Issue escalated to platform");
      setActiveAction(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to escalate issue");
    }
  }

  const isDisabled = !issue;
  const isAlreadyResolved = issue?.status === "resolved";
  const isAlreadyEscalated = issue?.status === "escalated";

  return (
    <div className="rounded-card border border-border-faint bg-bg-surface p-6">
      <h2 className="mb-4 text-[15px] font-semibold text-text-primary">
        Issue Actions
      </h2>

      {!issue ? (
        <p className="text-body-default text-text-faint">
          Select an issue from the queue to take action
        </p>
      ) : (
        <>
          {/* Selected issue info */}
          <div className="mb-4 rounded-control border border-border bg-bg-elevated px-3 py-2">
            <p className="text-body-default font-medium text-text-primary">
              {issue.title}
            </p>
            <p className="mt-0.5 font-mono text-xs text-text-faint">
              {issue.severity} / {issue.status}
            </p>
          </div>

          {/* Success message */}
          {successMessage && (
            <div className="mb-4 rounded-control border border-accent/30 bg-accent-dim px-3 py-2 text-body-default text-accent">
              {successMessage}
            </div>
          )}

          {/* Error message */}
          {error && (
            <div className="mb-4 rounded-control border border-alert/30 bg-alert-dim px-3 py-2 text-body-default text-alert">
              {error}
            </div>
          )}

          {/* Action buttons */}
          <div className="space-y-2">
            {/* Respond to Reporter */}
            <button
              disabled={isDisabled}
              onClick={() => {
                resetState();
                setActiveAction("respond");
              }}
              className="flex w-full items-center gap-2 rounded-control border border-border bg-transparent px-3 py-2 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-30"
            >
              <MessageSquare size={14} />
              Respond to Reporter
            </button>

            {/* Resolve with Note */}
            <button
              disabled={isDisabled || isAlreadyResolved}
              onClick={() => {
                resetState();
                setActiveAction("resolve");
              }}
              className="flex w-full items-center gap-2 rounded-control border border-border bg-transparent px-3 py-2 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-30"
            >
              <CheckCircle size={14} />
              Resolve with Note
            </button>

            {/* Escalate to Platform */}
            <button
              disabled={isDisabled || isAlreadyEscalated}
              onClick={() => {
                resetState();
                setActiveAction("escalate");
              }}
              className="flex w-full items-center gap-2 rounded-control border border-alert/30 bg-transparent px-3 py-2 text-body-default text-alert transition-colors hover:bg-alert-dim disabled:opacity-30"
            >
              <AlertTriangle size={14} />
              Escalate to Platform
            </button>
          </div>

          {/* Respond form */}
          {activeAction === "respond" && (
            <div className="mt-4 rounded-control border border-border bg-bg-deep p-4">
              <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.06em] text-text-faint">
                Respond to Reporter
              </p>
              <textarea
                placeholder="Type your response message..."
                rows={3}
                className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
              <div className="mt-2 flex justify-end gap-2">
                <button
                  onClick={() => setActiveAction(null)}
                  className="rounded-control border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:bg-bg-elevated"
                >
                  Cancel
                </button>
                <button className="rounded-control bg-accent px-3 py-1.5 text-xs font-semibold text-bg-base transition-opacity hover:opacity-90">
                  Send Response
                </button>
              </div>
            </div>
          )}

          {/* Resolve form */}
          {activeAction === "resolve" && (
            <div className="mt-4 rounded-control border border-border bg-bg-deep p-4">
              <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.06em] text-text-faint">
                Resolution Note
              </p>
              <textarea
                value={resolveNote}
                onChange={(e) => setResolveNote(e.target.value)}
                placeholder="Describe how this issue was resolved..."
                rows={3}
                className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
              <div className="mt-2 flex justify-end gap-2">
                <button
                  onClick={() => setActiveAction(null)}
                  className="rounded-control border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:bg-bg-elevated"
                >
                  Cancel
                </button>
                <button
                  onClick={handleResolve}
                  disabled={!resolveNote.trim() || updateMutation.isPending}
                  className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-xs font-semibold text-bg-base transition-opacity disabled:opacity-30"
                >
                  {updateMutation.isPending && (
                    <Loader2 size={12} className="animate-spin" />
                  )}
                  Resolve Issue
                </button>
              </div>
            </div>
          )}

          {/* Escalate confirmation */}
          {activeAction === "escalate" && (
            <div className="mt-4 rounded-control border border-alert/20 bg-alert-dim p-4">
              <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.06em] text-text-faint">
                Escalate to Platform
              </p>
              <p className="mb-3 text-body-default text-text-muted">
                This will escalate the issue to the platform operations team.
                Select the severity level for escalation.
              </p>
              <div className="mb-3">
                <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.06em] text-text-faint">
                  Escalation Severity
                </label>
                <select
                  value={escalateSeverity}
                  onChange={(e) =>
                    setEscalateSeverity(e.target.value as Issue["severity"])
                  }
                  className="rounded-control border border-border bg-bg-elevated px-2 py-1.5 text-xs text-text-primary transition-colors focus:border-accent focus:outline-none"
                >
                  {ESCALATE_SEVERITY_OPTIONS.map((sev) => (
                    <option key={sev} value={sev}>
                      {sev}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => setActiveAction(null)}
                  className="rounded-control border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:bg-bg-elevated"
                >
                  Cancel
                </button>
                <button
                  onClick={handleEscalate}
                  disabled={updateMutation.isPending}
                  className="flex items-center gap-1.5 rounded-control bg-alert px-3 py-1.5 text-xs font-semibold text-white transition-opacity disabled:opacity-30"
                >
                  {updateMutation.isPending && (
                    <Loader2 size={12} className="animate-spin" />
                  )}
                  Confirm Escalation
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
