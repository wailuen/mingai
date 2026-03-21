"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import {
  useCacheSummary,
  type CachePeriod,
} from "@/lib/hooks/useCacheAnalytics";
import { CachePeriodSelector } from "./elements/CachePeriodSelector";
import {
  CacheSummaryKPIs,
  CacheSummaryKPIsSkeleton,
} from "./elements/CacheSummaryKPIs";
import { CacheByIndexTable } from "./elements/CacheByIndexTable";
import { TopQueriesTable } from "./elements/TopQueriesTable";
import { DailySavingsChart } from "./elements/DailySavingsChart";

function CacheSummarySection({ period }: { period: CachePeriod }) {
  const { data, isPending, error } = useCacheSummary(period);

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load cache summary: {error.message}
      </p>
    );
  }

  if (isPending) {
    return <CacheSummaryKPIsSkeleton />;
  }

  if (!data) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-12 text-center">
        <p className="text-body-default text-text-muted">
          No cache data available yet. Cache analytics will appear here once the
          system starts processing queries.
        </p>
      </div>
    );
  }

  return <CacheSummaryKPIs data={data} />;
}

/**
 * CACHE-017: Tenant Admin cache analytics page.
 * Wired to real API endpoints with period selection.
 */
export default function TenantCacheAnalyticsPage() {
  const [period, setPeriod] = useState<CachePeriod>("7d");

  return (
    <AppShell>
      <div className="space-y-6 p-7">
        {/* Page header */}
        <div>
          <h1 className="text-page-title text-text-primary">Cache Analytics</h1>
          <p className="mt-1 text-body-default text-text-muted">
            Monitor semantic cache performance, hit rates, and cost savings
          </p>
        </div>

        {/* Period selector */}
        <CachePeriodSelector value={period} onChange={setPeriod} />

        {/* KPI cards */}
        <ErrorBoundary>
          <CacheSummarySection period={period} />
        </ErrorBoundary>

        {/* Daily savings chart */}
        <ErrorBoundary>
          <DailySavingsChart period={period} />
        </ErrorBoundary>

        {/* Two-column: by-index table + top queries */}
        <div className="grid gap-6 lg:grid-cols-2">
          <ErrorBoundary>
            <CacheByIndexTable period={period} />
          </ErrorBoundary>
          <ErrorBoundary>
            <TopQueriesTable period={period} />
          </ErrorBoundary>
        </div>
      </div>
    </AppShell>
  );
}
