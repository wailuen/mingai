"use client";

import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { IssueReportingForm } from "./elements/IssueReportingForm";

/**
 * FE-053: Issue Reporting Configuration (Tenant Admin settings tab).
 * Allows tenant admins to configure issue escalation, notifications, and integrations.
 */
export default function IssueReportingPage() {
  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Issue Reporting</h1>
          <p className="mt-1 text-sm text-text-muted">
            Configure how workspace issues are reported and escalated
          </p>
        </div>

        <div className="mx-auto max-w-2xl">
          <ErrorBoundary>
            <IssueReportingForm />
          </ErrorBoundary>
        </div>
      </div>
    </AppShell>
  );
}
