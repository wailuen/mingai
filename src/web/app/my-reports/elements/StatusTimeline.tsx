"use client";

import type { IssueStatus } from "@/lib/types/issues";

const STEPS = [
  { label: "Received", statuses: ["received"] },
  { label: "Triaging", statuses: ["triaging", "triaged"] },
  {
    label: "Fix In Progress",
    statuses: ["investigating", "fix_in_progress", "fix_merged"],
  },
  { label: "Resolved", statuses: ["fix_deployed", "resolved", "closed"] },
] as const;

function getStepIndex(status: IssueStatus): number {
  for (let i = 0; i < STEPS.length; i++) {
    if ((STEPS[i].statuses as readonly string[]).includes(status)) {
      return i;
    }
  }
  return 0;
}

interface StatusTimelineProps {
  status: IssueStatus;
}

export function StatusTimeline({ status }: StatusTimelineProps) {
  const currentStep = getStepIndex(status);

  return (
    <div className="flex items-center gap-0 py-4">
      {STEPS.map((step, idx) => {
        const isCompleted = idx < currentStep;
        const isCurrent = idx === currentStep;

        return (
          <div key={step.label} className="flex items-center">
            {/* Dot */}
            <div className="flex flex-col items-center">
              <div
                className={`h-3 w-3 rounded-full ${
                  isCompleted
                    ? "bg-accent"
                    : isCurrent
                      ? "bg-accent animate-pulse"
                      : "bg-bg-elevated border border-border"
                }`}
              />
              <span
                className={`mt-2 text-label-nav uppercase ${
                  isCompleted || isCurrent
                    ? "text-text-primary"
                    : "text-text-faint"
                }`}
              >
                {step.label}
              </span>
            </div>

            {/* Connecting line */}
            {idx < STEPS.length - 1 && (
              <div
                className={`mx-1 h-0.5 w-8 sm:w-12 ${
                  idx < currentStep ? "bg-accent" : "bg-border"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
