"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import type { CostPeriod } from "@/lib/hooks/useCostAnalytics";
import { PeriodSelector } from "./elements/PeriodSelector";
import { PlatformCostSummary } from "./elements/PlatformCostSummary";
import { MarginChart } from "./elements/MarginChart";
import { TenantCostTable } from "./elements/TenantCostTable";

/**
 * FE-046: Cross-Tenant Cost Analytics Dashboard.
 * Platform admin view of LLM costs, infrastructure costs, revenue,
 * and gross margin across all tenants.
 */
export default function CostAnalyticsPage() {
  const [period, setPeriod] = useState<CostPeriod>("30d");

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Cost Analytics</h1>
          <p className="mt-1 text-sm text-text-muted">
            Cross-tenant cost breakdown, revenue, and margin analysis
          </p>
        </div>

        {/* Period selector */}
        <div className="mb-6">
          <PeriodSelector value={period} onChange={setPeriod} />
        </div>

        {/* KPI cards */}
        <ErrorBoundary>
          <PlatformCostSummary period={period} />
        </ErrorBoundary>

        {/* Margin trend chart */}
        <div className="mt-7">
          <ErrorBoundary>
            <MarginChart period={period} />
          </ErrorBoundary>
        </div>

        {/* Tenant cost table */}
        <div className="mt-7">
          <ErrorBoundary>
            <TenantCostTable period={period} />
          </ErrorBoundary>
        </div>
      </div>
    </AppShell>
  );
}
