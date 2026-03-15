"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useTenantDetail } from "@/lib/hooks/usePlatformDashboard";
import { TenantHeader } from "./elements/TenantHeader";
import { TenantActions } from "./elements/TenantActions";
import { HealthBreakdown } from "./elements/HealthBreakdown";
import { QuotaUsageBar } from "./elements/QuotaUsageBar";
import { TenantDetailSkeleton } from "./elements/TenantDetailSkeleton";

/**
 * FE-042: Tenant Detail page with health breakdown.
 * Route: /platform/tenants/[id]
 *
 * Orchestrator only -- each section fetches its own data via dedicated hooks.
 * TenantHeader and TenantActions receive props from the parent query.
 * HealthBreakdown and QuotaUsageBar each own their own API calls.
 */
export default function TenantDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const { id } = params;
  const { data: tenant, isPending, error } = useTenantDetail(id);

  return (
    <AppShell>
      <div className="p-7">
        {/* Back link */}
        <Link
          href="/platform/tenants"
          className="mb-5 inline-flex items-center gap-1.5 text-sm text-text-muted transition-colors hover:text-text-primary"
        >
          <ArrowLeft size={14} />
          Back to Tenants
        </Link>

        {/* Loading state */}
        {isPending && <TenantDetailSkeleton />}

        {/* Error state */}
        {error && (
          <p className="text-sm text-alert">
            Failed to load tenant: {error.message}
          </p>
        )}

        {/* Tenant detail content */}
        {tenant && (
          <div className="space-y-6">
            {/* Header */}
            <TenantHeader
              name={tenant.name}
              status={tenant.status}
              plan={tenant.plan}
              primaryContactEmail={tenant.primary_contact_email}
              createdAt={tenant.created_at}
            />

            {/* Actions */}
            <TenantActions tenantId={id} status={tenant.status} />

            {/* Health + Quota grid */}
            <div className="grid gap-6 lg:grid-cols-2">
              <ErrorBoundary>
                <HealthBreakdown tenantId={id} />
              </ErrorBoundary>

              <ErrorBoundary>
                <QuotaUsageBar tenantId={id} />
              </ErrorBoundary>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
