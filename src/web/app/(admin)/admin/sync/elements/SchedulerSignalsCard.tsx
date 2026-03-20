"use client";

import { useSyncStatus } from "@/lib/hooks/useSyncHealth";
import { Skeleton } from "@/components/shared/LoadingState";
import { CheckCircle2, AlertTriangle, AlertOctagon, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

function formatRelative(isoStr: string | null): string {
  if (!isoStr) return "Never";
  const date = new Date(isoStr);
  const diffMs = Date.now() - date.getTime();
  const diffHours = Math.floor(diffMs / 3_600_000);
  if (diffHours < 1) return "< 1 hour ago";
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

interface SignalRowProps {
  label: string;
  value: string;
  status?: "ok" | "warn" | "alert" | "neutral";
}

function SignalRow({ label, value, status = "neutral" }: SignalRowProps) {
  const Icon =
    status === "ok"
      ? CheckCircle2
      : status === "alert"
        ? AlertOctagon
        : status === "warn"
          ? AlertTriangle
          : Clock;
  const iconColor =
    status === "ok"
      ? "text-accent"
      : status === "warn"
        ? "text-warn"
        : status === "alert"
          ? "text-alert"
          : "text-text-faint";

  return (
    <div className="flex items-center justify-between py-2.5">
      <div className="flex items-center gap-2">
        <Icon size={13} className={cn(iconColor)} aria-hidden="true" />
        <span className="text-[13px] text-text-muted">{label}</span>
      </div>
      <span className="font-mono text-[13px] text-text-primary">{value}</span>
    </div>
  );
}

/**
 * SCHED-027: Displays scheduler health signals from GET /api/v1/tenant/sync-status.
 * Shows credential expiry, query warming, health score recency, and glossary count.
 */
export function SchedulerSignalsCard() {
  const { data, isPending, isError } = useSyncStatus();

  const expiryDays = data?.credentials_expiry_days_remaining;
  const expiryStatus =
    expiryDays === null || expiryDays === undefined
      ? "neutral"
      : expiryDays <= 7
        ? "alert"
        : expiryDays <= 30
          ? "warn"
          : "ok";
  const expiryValue =
    expiryDays !== null && expiryDays !== undefined
      ? `${expiryDays} days`
      : "—";

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <h3 className="mb-1 text-section-heading text-text-primary">
        Scheduler Signals
      </h3>
      <p className="mb-4 text-xs text-text-faint">
        Background job outcomes for this workspace
      </p>

      {isPending && (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      )}

      {isError && (
        <p className="text-sm text-alert">Failed to load scheduler signals.</p>
      )}

      {!isPending && !isError && data && (
        <div className="divide-y divide-border-faint">
          <SignalRow
            label="Credentials last checked"
            value={formatRelative(data.last_credentials_checked_at)}
            status={data.last_credentials_checked_at ? "ok" : "neutral"}
          />
          <SignalRow
            label="Credential expiry"
            value={expiryValue}
            status={expiryStatus}
          />
          <SignalRow
            label="Query cache warmed"
            value={formatRelative(data.last_query_warming_completed_at)}
            status={data.last_query_warming_completed_at ? "ok" : "neutral"}
          />
          <SignalRow
            label="Health score calculated"
            value={formatRelative(data.last_health_score_calculated_at)}
            status={data.last_health_score_calculated_at ? "ok" : "neutral"}
          />
          <SignalRow
            label="Glossary terms active"
            value={String(data.glossary_terms_active)}
            status="neutral"
          />
        </div>
      )}
    </div>
  );
}
