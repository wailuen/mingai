"use client";

import { useState } from "react";
import { Flag } from "lucide-react";
import { IssueReporterDialog } from "./IssueReporterDialog";

/**
 * FE-021: Floating button (bottom-right, always visible).
 * Opens the issue reporter dialog on click.
 */
export function IssueReporterButton() {
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <>
      <button
        onClick={() => setDialogOpen(true)}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-card border border-border bg-bg-surface px-4 py-2.5 text-sm text-text-muted shadow-lg transition-colors hover:border-accent-ring hover:text-text-primary"
        aria-label="Report Issue"
      >
        <Flag size={14} />
        <span>Report Issue</span>
      </button>

      {dialogOpen && (
        <IssueReporterDialog onClose={() => setDialogOpen(false)} />
      )}
    </>
  );
}
