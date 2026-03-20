"use client";

import { useState } from "react";
import { ApiException } from "@/lib/api";
import { useTriggerJob, KNOWN_JOB_NAMES } from "@/lib/hooks/useJobHistory";

interface RunNowButtonProps {
  onNotify: (kind: "success" | "error", message: string) => void;
}

type JobName = (typeof KNOWN_JOB_NAMES)[number];

/**
 * TODO-13C: "Run Now" button that lets platform admins trigger a job on demand.
 * Opens a select to pick the job, then a confirmation dialog before triggering.
 */
export function RunNowButton({ onNotify }: RunNowButtonProps) {
  const [phase, setPhase] = useState<"idle" | "select" | "confirm">("idle");
  const [selectedJob, setSelectedJob] = useState<JobName>(KNOWN_JOB_NAMES[0]);

  const triggerJob = useTriggerJob();

  function handleSelectChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setSelectedJob(e.target.value as JobName);
  }

  function handleConfirm() {
    triggerJob.mutate(selectedJob, {
      onSuccess: () => {
        setPhase("idle");
        onNotify("success", `Job "${selectedJob}" triggered successfully.`);
      },
      onError: (err: unknown) => {
        setPhase("idle");
        // 409 = job already running
        if (err instanceof ApiException && err.status === 409) {
          onNotify(
            "error",
            "Job already running — wait for it to finish before triggering again.",
          );
        } else {
          const message = err instanceof Error ? err.message : "Unknown error";
          onNotify("error", `Failed to trigger job: ${message}`);
        }
      },
    });
  }

  return (
    <>
      {/* Idle: show "Run Now" button */}
      {phase === "idle" && (
        <button
          onClick={() => setPhase("select")}
          className="rounded-control bg-accent px-3 py-1.5 text-xs font-medium text-bg-base transition-opacity hover:opacity-90"
        >
          Run Now
        </button>
      )}

      {/* Select phase: inline select + confirm / cancel */}
      {phase === "select" && (
        <div className="flex items-center gap-2">
          <select
            value={selectedJob}
            onChange={handleSelectChange}
            className="rounded-control border border-border bg-bg-elevated px-2 py-1.5 font-mono text-[12px] text-text-primary focus:border-accent-ring focus:outline-none"
          >
            {KNOWN_JOB_NAMES.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <button
            onClick={() => setPhase("confirm")}
            className="rounded-control bg-accent px-3 py-1.5 text-xs font-medium text-bg-base transition-opacity hover:opacity-90"
          >
            Next
          </button>
          <button
            onClick={() => setPhase("idle")}
            className="rounded-control border border-border bg-transparent px-3 py-1.5 text-xs text-text-muted transition-colors hover:text-text-primary"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Confirm dialog overlay */}
      {phase === "confirm" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-base/60 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-card border border-border bg-bg-surface p-6">
            <h2 className="mb-2 text-section-heading text-text-primary">
              Trigger job?
            </h2>
            <p className="mb-1 text-[13px] text-text-muted">
              This will start a new run of:
            </p>
            <p className="mb-5 font-mono text-[13px] text-accent">
              {selectedJob}
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setPhase("select")}
                disabled={triggerJob.isPending}
                className="rounded-control border border-border bg-transparent px-4 py-2 text-sm text-text-muted transition-colors hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={triggerJob.isPending}
                className="rounded-control bg-accent px-4 py-2 text-sm font-medium text-bg-base transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {triggerJob.isPending ? "Triggering…" : "Trigger"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
