"use client";

import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { HealthSummaryCards } from "./elements/HealthSummaryCards";
import { SetupChecklist } from "./elements/SetupChecklist";
import { QuickActions } from "./elements/QuickActions";

/**
 * FE-026: Tenant admin dashboard.
 * Orchestrator only -- business logic lives in elements/.
 * KPI cards, setup checklist, quick actions.
 */
export default function TenantDashboardPage() {
  return (
    <AppShell>
      <div className="space-y-6 p-4 sm:p-7">
        <h1 className="text-page-title text-text-primary">Dashboard</h1>

        <ErrorBoundary>
          <HealthSummaryCards />
        </ErrorBoundary>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <ErrorBoundary>
            <SetupChecklist />
          </ErrorBoundary>

          <ErrorBoundary>
            <QuickActions />
          </ErrorBoundary>
        </div>
      </div>
    </AppShell>
  );
}
