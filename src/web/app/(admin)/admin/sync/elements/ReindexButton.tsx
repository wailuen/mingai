"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost } from "@/lib/api";
import { RefreshCw, Loader2 } from "lucide-react";

interface ReindexButtonProps {
  integrationId: string;
  documentCount: number;
}

/** Cost per document for text-embedding-3-small (approximate) */
const COST_PER_DOCUMENT = 0.00002;

/**
 * FE-034: Re-index button with cost estimate confirmation dialog.
 * Destructive action styled with --alert.
 */
export function ReindexButton({
  integrationId,
  documentCount,
}: ReindexButtonProps) {
  const [showDialog, setShowDialog] = useState(false);
  const queryClient = useQueryClient();

  const estimatedCost = (documentCount * COST_PER_DOCUMENT).toFixed(4);

  const mutation = useMutation({
    mutationFn: () =>
      apiPost<{ job_id: string; status: string }>(
        "/api/v1/sync/reindex",
        { integration_id: integrationId },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["sharepoint-integrations"],
      });
      queryClient.invalidateQueries({ queryKey: ["sync-jobs"] });
      setShowDialog(false);
    },
  });

  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setShowDialog(true);
        }}
        className="flex items-center gap-1.5 rounded-control border border-alert px-3 py-1.5 text-xs font-medium text-alert transition-colors hover:bg-alert-dim"
      >
        <RefreshCw size={12} />
        Re-index All Documents
      </button>

      {/* Confirmation dialog */}
      {showDialog && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40 bg-black/40"
            onClick={() => setShowDialog(false)}
            aria-hidden="true"
          />

          {/* Dialog */}
          <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-card border border-border bg-bg-surface p-6 shadow-lg animate-fade-in">
            <h3 className="text-section-heading text-text-primary">
              Confirm Re-index
            </h3>

            <p className="mt-3 text-sm text-text-muted">
              This will re-embed{" "}
              <span className="font-mono font-medium text-text-primary">
                {documentCount.toLocaleString()}
              </span>{" "}
              documents. Estimated cost:{" "}
              <span className="font-mono font-medium text-text-primary">
                ${estimatedCost}
              </span>
            </p>

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowDialog(false)}
                className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending}
                className="flex items-center gap-1.5 rounded-control bg-alert px-3 py-1.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-30"
              >
                {mutation.isPending && (
                  <Loader2 size={14} className="animate-spin" />
                )}
                Confirm Re-index
              </button>
            </div>

            {mutation.isError && (
              <p className="mt-3 text-xs text-alert">
                Re-index failed. Please try again.
              </p>
            )}
          </div>
        </>
      )}
    </>
  );
}
