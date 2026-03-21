"use client";

import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { PlatformKPICards } from "./elements/PlatformKPICards";
import { TenantHealthTable } from "./elements/TenantHealthTable";

/**
 * FE-040: Platform Admin Dashboard.
 * Shows KPI cards (active users, docs indexed, queries today, satisfaction)
 * and a tenant overview table.
 */
export default function PlatformDashboardPage() {
  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">
            Platform Dashboard
          </h1>
          <p className="mt-1 text-body-default text-text-muted">
            Overview of platform health and tenant activity
          </p>
        </div>

        {/* KPI Cards */}
        <ErrorBoundary>
          <PlatformKPICards />
        </ErrorBoundary>

        {/* Tenant Health Table */}
        <div className="mt-7">
          <ErrorBoundary>
            <TenantHealthTable />
          </ErrorBoundary>
        </div>
      </div>
    </AppShell>
  );
}
