"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { cn } from "@/lib/utils";
import type { AnalyticsPeriod } from "@/lib/hooks/useIssueAnalytics";
import { IssueSummaryKPIs } from "./elements/IssueSummaryKPIs";
import { IssuesByTenantTable } from "./elements/IssuesByTenantTable";
import { SeverityBreakdown } from "./elements/SeverityBreakdown";
import { MTTRChart } from "./elements/MTTRChart";
import { TopBugsTable } from "./elements/TopBugsTable";
import { TrendChart } from "./elements/TrendChart";
import { DuplicateView } from "./elements/DuplicateView";
import { SLAAdherence } from "./elements/SLAAdherence";

// ---------------------------------------------------------------------------
// Period selector (same pattern as cost analytics)
// ---------------------------------------------------------------------------

const PERIODS: { value: AnalyticsPeriod; label: string }[] = [
  { value: "7d", label: "7 Days" },
  { value: "30d", label: "30 Days" },
  { value: "90d", label: "90 Days" },
];

function PeriodSelector({
  value,
  onChange,
}: {
  value: AnalyticsPeriod;
  onChange: (p: AnalyticsPeriod) => void;
}) {
  return (
    <div className="flex items-center border-b border-border">
      {PERIODS.map((period) => (
        <button
          key={period.value}
          type="button"
          onClick={() => onChange(period.value)}
          className={cn(
            "border-b-2 px-3.5 py-2 text-xs font-medium transition-colors",
            value === period.value
              ? "border-b-accent text-text-primary"
              : "border-b-transparent text-text-faint hover:text-accent",
          )}
        >
          {period.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

/**
 * FE-055: Platform Issues Analytics Dashboard.
 * Cross-tenant issue metrics with period-selectable KPIs,
 * per-tenant breakdown, and severity distribution.
 */
export default function IssueAnalyticsPage() {
  const [period, setPeriod] = useState<AnalyticsPeriod>("30d");

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">
            Issues Analytics
          </h1>
          <p className="mt-1 text-sm text-text-muted">
            Cross-tenant issue metrics, SLA compliance, and severity trends
          </p>
        </div>

        {/* Period selector */}
        <div className="mb-6">
          <PeriodSelector value={period} onChange={setPeriod} />
        </div>

        {/* KPI cards */}
        <ErrorBoundary>
          <IssueSummaryKPIs period={period} />
        </ErrorBoundary>

        {/* Issues by tenant */}
        <div className="mt-7">
          <ErrorBoundary>
            <IssuesByTenantTable period={period} />
          </ErrorBoundary>
        </div>

        {/* Severity breakdown + SLA adherence side-by-side */}
        <div className="mt-7 grid grid-cols-1 gap-7 lg:grid-cols-2">
          <ErrorBoundary>
            <SeverityBreakdown period={period} />
          </ErrorBoundary>
          <ErrorBoundary>
            <SLAAdherence period={period} />
          </ErrorBoundary>
        </div>

        {/* MTTR chart + Trend chart side-by-side */}
        <div className="mt-7 grid grid-cols-1 gap-7 lg:grid-cols-2">
          <ErrorBoundary>
            <MTTRChart period={period} />
          </ErrorBoundary>
          <ErrorBoundary>
            <TrendChart period={period} />
          </ErrorBoundary>
        </div>

        {/* Top bugs */}
        <div className="mt-7">
          <ErrorBoundary>
            <TopBugsTable period={period} />
          </ErrorBoundary>
        </div>

        {/* Duplicate clusters */}
        <div className="mt-7">
          <ErrorBoundary>
            <DuplicateView period={period} />
          </ErrorBoundary>
        </div>
      </div>
    </AppShell>
  );
}
