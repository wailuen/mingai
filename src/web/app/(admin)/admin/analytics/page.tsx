"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { SatisfactionGauge } from "./elements/SatisfactionGauge";
import { SatisfactionTrend } from "./elements/SatisfactionTrend";
import { LowConfidenceList } from "./elements/LowConfidenceList";
import { AgentBreakdownTable } from "./elements/AgentBreakdownTable";
import { RootCausePanel } from "./elements/RootCausePanel";
import { IssueQueue } from "./elements/IssueQueue";
import { IssueResponseWorkflow } from "./elements/IssueResponseWorkflow";
import {
  useSatisfactionData,
  useLowConfidenceItems,
} from "@/lib/hooks/useAnalytics";
import type { Issue } from "@/lib/hooks/useAnalytics";

/**
 * FE-037: Feedback Monitoring / Analytics dashboard (Tenant Admin).
 * Orchestrator only -- business logic lives in elements/.
 *
 * Sections:
 * 1. SatisfactionGauge (7-day KPI)
 * 2. SatisfactionTrend (30-day area chart)
 * 3. AgentBreakdownTable (per-agent satisfaction)
 * 4. RootCausePanel (sync freshness vs satisfaction correlation)
 * 5. LowConfidenceList (table of low-confidence responses)
 * 6. IssueQueue + IssueResponseWorkflow (tenant issue management)
 */
export default function AnalyticsPage() {
  const satisfaction = useSatisfactionData();
  const lowConfidence = useLowConfidenceItems();
  const [selectedIssue, setSelectedIssue] = useState<Issue | null>(null);

  return (
    <AppShell>
      <div className="space-y-6 p-4 sm:p-7">
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

        {/* Per-agent satisfaction breakdown */}
        <ErrorBoundary>
          <AgentBreakdownTable />
        </ErrorBoundary>

        {/* Root cause analysis: sync freshness vs satisfaction */}
        <ErrorBoundary>
          <RootCausePanel />
        </ErrorBoundary>

        {/* Low confidence responses table */}
        <ErrorBoundary>
          <LowConfidenceList
            items={lowConfidence.data?.items ?? []}
            isPending={lowConfidence.isPending}
          />
        </ErrorBoundary>

        {/* Issue queue and response workflow */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_340px]">
          <ErrorBoundary>
            <IssueQueue
              onSelectIssue={setSelectedIssue}
              selectedIssueId={selectedIssue?.id ?? null}
            />
          </ErrorBoundary>
          <ErrorBoundary>
            <IssueResponseWorkflow issue={selectedIssue} />
          </ErrorBoundary>
        </div>
      </div>
    </AppShell>
  );
}
