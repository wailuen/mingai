"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";
import { TrendingUp, Users, ShieldAlert, AlertCircle } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DailyMetric {
  date: string;
  satisfaction_rate: number | null;
  guardrail_trigger_rate: number | null;
  failure_count: number;
  session_count: number;
}

interface TemplateAnalytics {
  daily_metrics: DailyMetric[];
  tenant_count: number;
  top_failure_patterns: Array<{ issue_type: string; issue_count: number }>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

function useTemplateAnalytics(templateId: string) {
  return useQuery({
    queryKey: ["template-analytics", templateId],
    queryFn: () =>
      apiGet<TemplateAnalytics>(
        `/api/v1/platform/agent-templates/${templateId}/analytics`,
      ),
    staleTime: 5 * 60 * 1000,
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function avg(metrics: DailyMetric[], key: keyof DailyMetric): number | null {
  const vals = metrics
    .map((m) => m[key] as number | null)
    .filter((v): v is number => v != null);
  if (vals.length === 0) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function sum(
  metrics: DailyMetric[],
  key: "failure_count" | "session_count",
): number {
  return metrics.reduce((a, m) => a + (m[key] ?? 0), 0);
}

// ---------------------------------------------------------------------------
// KPI card
// ---------------------------------------------------------------------------

interface KPICardProps {
  label: string;
  value: string;
  icon: React.ReactNode;
  accent?: boolean;
  warn?: boolean;
}

function KPICard({ label, value, icon, accent, warn }: KPICardProps) {
  return (
    <div className="rounded-card border border-border bg-bg-surface px-4 py-4">
      <div className="mb-2 flex items-center gap-2">
        <span
          className={cn(
            "text-text-faint",
            accent && "text-accent",
            warn && "text-warn",
          )}
        >
          {icon}
        </span>
        <p className="text-label-nav uppercase tracking-wider text-text-faint">
          {label}
        </p>
      </div>
      <p
        className={cn(
          "font-mono text-[22px] font-semibold text-text-primary",
          accent && "text-accent",
          warn && "text-alert",
        )}
      >
        {value}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface PerformanceTabProps {
  templateId: string;
}

export function PerformanceTab({ templateId }: PerformanceTabProps) {
  const { data, isPending, error } = useTemplateAnalytics(templateId);

  if (error) {
    return (
      <div className="flex items-center gap-2 py-8 text-body-default text-alert">
        <AlertCircle size={16} />
        Failed to load performance data
      </div>
    );
  }

  if (isPending) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-card border border-border bg-bg-elevated"
            />
          ))}
        </div>
        <div className="h-48 animate-pulse rounded-card border border-border bg-bg-elevated" />
      </div>
    );
  }

  const {
    daily_metrics = [],
    tenant_count = 0,
    top_failure_patterns = [],
  } = data ?? {};

  const totalSessions = sum(daily_metrics, "session_count");
  const avgSatisfaction = avg(daily_metrics, "satisfaction_rate");
  const avgGuardrailRate = avg(daily_metrics, "guardrail_trigger_rate");
  const totalFailures = sum(daily_metrics, "failure_count");

  const isEmpty = totalSessions === 0;

  if (isEmpty) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <TrendingUp size={36} className="mb-3 text-text-faint" />
        <p className="text-body-default text-text-faint">
          No deployments yet. Performance data will appear once tenants deploy
          this template.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* KPI grid */}
      <div className="grid grid-cols-4 gap-4">
        <KPICard
          label="Active Tenants"
          value={String(tenant_count)}
          icon={<Users size={14} />}
          accent
        />
        <KPICard
          label="Sessions (30d)"
          value={totalSessions.toLocaleString()}
          icon={<TrendingUp size={14} />}
        />
        <KPICard
          label="Avg Satisfaction"
          value={pct(avgSatisfaction)}
          icon={<TrendingUp size={14} />}
          accent={avgSatisfaction != null && avgSatisfaction >= 0.8}
          warn={avgSatisfaction != null && avgSatisfaction < 0.6}
        />
        <KPICard
          label="Guardrail Trigger"
          value={pct(avgGuardrailRate)}
          icon={<ShieldAlert size={14} />}
          warn={avgGuardrailRate != null && avgGuardrailRate > 0.05}
        />
      </div>

      {/* Daily metrics table */}
      <div>
        <p className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
          Daily Metrics — Last 30 Days
        </p>
        <div className="overflow-hidden rounded-card border border-border bg-bg-surface">
          <table className="w-full">
            <thead className="bg-bg-elevated">
              <tr className="border-b border-border">
                {[
                  "Date",
                  "Sessions",
                  "Satisfaction",
                  "Guardrail Rate",
                  "Failures",
                ].map((h) => (
                  <th
                    key={h}
                    className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {daily_metrics.length === 0 ? (
                <tr>
                  <td
                    colSpan={5}
                    className="px-3.5 py-8 text-center text-body-default text-text-faint"
                  >
                    No daily data available
                  </td>
                </tr>
              ) : (
                [...daily_metrics].reverse().map((m) => (
                  <tr
                    key={m.date}
                    className="border-b border-border-faint hover:bg-accent-dim"
                  >
                    <td className="px-3.5 py-2.5 font-mono text-data-value text-text-muted">
                      {m.date}
                    </td>
                    <td className="px-3.5 py-2.5 font-mono text-data-value text-text-primary">
                      {m.session_count}
                    </td>
                    <td
                      className={cn(
                        "px-3.5 py-2.5 font-mono text-data-value",
                        m.satisfaction_rate != null &&
                          m.satisfaction_rate >= 0.8
                          ? "text-accent"
                          : m.satisfaction_rate != null &&
                              m.satisfaction_rate < 0.6
                            ? "text-alert"
                            : "text-text-muted",
                      )}
                    >
                      {pct(m.satisfaction_rate)}
                    </td>
                    <td
                      className={cn(
                        "px-3.5 py-2.5 font-mono text-data-value",
                        m.guardrail_trigger_rate != null &&
                          m.guardrail_trigger_rate > 0.05
                          ? "text-warn"
                          : "text-text-muted",
                      )}
                    >
                      {pct(m.guardrail_trigger_rate)}
                    </td>
                    <td
                      className={cn(
                        "px-3.5 py-2.5 font-mono text-data-value",
                        m.failure_count > 0 ? "text-alert" : "text-text-faint",
                      )}
                    >
                      {m.failure_count > 0 ? m.failure_count : "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Top failure patterns */}
      {top_failure_patterns.length > 0 && (
        <div>
          <p className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
            Top Failure Patterns (30d)
          </p>
          <div className="space-y-2">
            {top_failure_patterns.map((fp) => (
              <div
                key={fp.issue_type}
                className="flex items-center justify-between rounded-control border border-border-faint bg-bg-elevated px-4 py-2.5"
              >
                <div className="flex items-center gap-2">
                  <AlertCircle size={13} className="text-alert" />
                  <span className="text-body-default text-text-primary">
                    {fp.issue_type.replace(/_/g, " ")}
                  </span>
                </div>
                <span className="font-mono text-data-value text-alert">
                  {fp.issue_count.toLocaleString()} reports
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Failure summary */}
      {totalFailures > 0 && (
        <p className="text-body-default text-text-faint">
          {totalFailures} total failure{totalFailures !== 1 ? "s" : ""} recorded
          in the last 30 days across all tenant instances.
        </p>
      )}
    </div>
  );
}
