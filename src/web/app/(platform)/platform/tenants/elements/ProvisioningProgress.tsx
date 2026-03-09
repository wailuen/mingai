"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Check, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ProvisioningProgressProps {
  tenantId: string;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

type StepStatus = "pending" | "active" | "done" | "failed";

interface ProvisionStep {
  id: string;
  label: string;
  status: StepStatus;
}

const STEP_DEFINITIONS: Array<{ id: string; label: string }> = [
  { id: "database", label: "Creating Database" },
  { id: "auth", label: "Setting up Auth" },
  { id: "knowledge_base", label: "Configuring KBs" },
  { id: "seed_data", label: "Seeding Data" },
  { id: "ready", label: "Ready" },
];

interface TenantStatusResponse {
  id: string;
  status: string;
  provisioning_step?: string;
  provisioning_error?: string;
}

function deriveSteps(
  tenantStatus: string,
  provisioningStep?: string,
  provisioningError?: string,
): ProvisionStep[] {
  const stepIndex = provisioningStep
    ? STEP_DEFINITIONS.findIndex((s) => s.id === provisioningStep)
    : -1;

  const isFailed = tenantStatus === "provisioning_failed";
  const isReady = tenantStatus === "active";

  return STEP_DEFINITIONS.map((def, i) => {
    let status: StepStatus = "pending";

    if (isReady) {
      status = "done";
    } else if (isFailed && i === stepIndex) {
      status = "failed";
    } else if (i < stepIndex) {
      status = "done";
    } else if (i === stepIndex && !isFailed) {
      status = "active";
    }

    return { ...def, status };
  });
}

function StepIndicator({ status }: { status: StepStatus }) {
  const base =
    "flex h-7 w-7 items-center justify-center rounded-full border-2 text-xs font-semibold transition-colors";

  switch (status) {
    case "done":
      return (
        <div className={cn(base, "border-accent bg-accent text-bg-base")}>
          <Check size={14} />
        </div>
      );
    case "active":
      return (
        <div
          className={cn(
            base,
            "border-accent bg-accent-dim text-accent animate-pulse",
          )}
        >
          <span className="h-2 w-2 rounded-full bg-accent" />
        </div>
      );
    case "failed":
      return (
        <div className={cn(base, "border-alert bg-alert-dim text-alert")}>
          <X size={14} />
        </div>
      );
    default:
      return <div className={cn(base, "border-border bg-bg-elevated text-text-faint")} />;
  }
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function ProvisioningProgress({
  tenantId,
  onComplete,
  onError,
}: ProvisioningProgressProps) {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());
  const completedRef = useRef(false);
  const erroredRef = useRef(false);

  const { data } = useQuery({
    queryKey: ["tenant-provisioning-status", tenantId],
    queryFn: () =>
      apiGet<TenantStatusResponse>(`/api/v1/platform/tenants/${tenantId}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "active" || status === "provisioning_failed") {
        return false;
      }
      return 2000;
    },
  });

  const steps = deriveSteps(
    data?.status ?? "provisioning",
    data?.provisioning_step,
    data?.provisioning_error,
  );

  const doneCount = steps.filter((s) => s.status === "done").length;
  const progressPct = (doneCount / steps.length) * 100;
  const isComplete = data?.status === "active";
  const isFailed = data?.status === "provisioning_failed";

  const handleComplete = useCallback(() => {
    onComplete?.();
  }, [onComplete]);

  const handleError = useCallback(
    (msg: string) => {
      onError?.(msg);
    },
    [onError],
  );

  useEffect(() => {
    if (isComplete && !completedRef.current) {
      completedRef.current = true;
      handleComplete();
    }
    if (isFailed && !erroredRef.current) {
      erroredRef.current = true;
      handleError(data?.provisioning_error ?? "Provisioning failed");
    }
  }, [isComplete, isFailed, handleComplete, handleError, data?.provisioning_error]);

  useEffect(() => {
    if (isComplete || isFailed) return;

    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
    }, 1000);

    return () => clearInterval(timer);
  }, [isComplete, isFailed]);

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      {/* Progress bar */}
      <div className="mb-5 h-1.5 w-full overflow-hidden rounded-full bg-bg-elevated">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-300",
            isFailed ? "bg-alert" : "bg-accent",
          )}
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Steps */}
      <div className="space-y-0">
        {steps.map((step, i) => (
          <div key={step.id} className="flex items-start gap-3">
            {/* Vertical line + indicator */}
            <div className="flex flex-col items-center">
              <StepIndicator status={step.status} />
              {i < steps.length - 1 && (
                <div
                  className={cn(
                    "h-6 w-0.5",
                    step.status === "done" ? "bg-accent" : "bg-border",
                  )}
                />
              )}
            </div>

            {/* Label + status */}
            <div className="flex min-h-[28px] items-center gap-2 pb-6">
              <span
                className={cn(
                  "text-[13px] font-medium",
                  step.status === "done" && "text-text-primary",
                  step.status === "active" && "text-accent",
                  step.status === "failed" && "text-alert",
                  step.status === "pending" && "text-text-faint",
                )}
              >
                {step.label}
              </span>

              {step.status === "active" && (
                <span className="rounded-badge bg-accent-dim px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-accent">
                  In Progress
                </span>
              )}
              {step.status === "failed" && (
                <span className="rounded-badge bg-alert-dim px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-alert">
                  Failed
                </span>
              )}
              {step.status === "done" && (
                <span className="rounded-badge bg-accent-dim px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-accent">
                  Done
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Elapsed time */}
      <div className="mt-2 flex items-center justify-between border-t border-border-faint pt-3">
        <span className="text-[11px] uppercase tracking-wider text-text-faint">
          Elapsed
        </span>
        <span className="font-mono text-data-value text-text-muted">
          {formatElapsed(elapsed)}
        </span>
      </div>
    </div>
  );
}
