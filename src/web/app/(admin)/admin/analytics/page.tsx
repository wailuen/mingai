"use client";

import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { SatisfactionGauge } from "./elements/SatisfactionGauge";
import { SatisfactionTrend } from "./elements/SatisfactionTrend";
import { LowConfidenceList } from "./elements/LowConfidenceList";
import {
  useSatisfactionData,
  useLowConfidenceItems,
} from "@/lib/hooks/useAnalytics";

/**
 * FE-037: Feedback Monitoring / Analytics dashboard (Tenant Admin).
 * Orchestrator only -- business logic lives in elements/.
 *
 * Sections:
 * 1. SatisfactionGauge (7-day KPI)
 * 2. SatisfactionTrend (30-day area chart)
 * 3. LowConfidenceList (table of low-confidence responses)
 */
export default function AnalyticsPage() {
  const satisfaction = useSatisfactionData();
  const lowConfidence = useLowConfidenceItems();

  return (
    <AppShell>
      <div className="space-y-6 p-7">
        {/* Page header */}
        <div>
          <h1 className="text-page-title text-text-primary">Analytics</h1>
          <p className="mt-1 text-sm text-text-muted">
            Feedback monitoring and response quality insights
          </p>
        </div>

        {/* Error states */}
        {satisfaction.error && (
          <p className="text-sm text-alert">
            Failed to load satisfaction data: {satisfaction.error.message}
          </p>
        )}
        {lowConfidence.error && (
          <p className="text-sm text-alert">
            Failed to load low-confidence data: {lowConfidence.error.message}
          </p>
        )}

        {/* 7-day satisfaction KPI */}
        <ErrorBoundary>
          <SatisfactionGauge
            data={satisfaction.data}
            isPending={satisfaction.isPending}
          />
        </ErrorBoundary>

        {/* 30-day trend chart */}
        <ErrorBoundary>
          <SatisfactionTrend
            trend={satisfaction.data?.trend ?? []}
            isPending={satisfaction.isPending}
          />
        </ErrorBoundary>

        {/* Low confidence responses table */}
        <ErrorBoundary>
          <LowConfidenceList
            items={lowConfidence.data?.items ?? []}
            isPending={lowConfidence.isPending}
          />
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}
