"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TenantTable } from "./elements/TenantTable";
import { ProvisionTenantWizard } from "./elements/ProvisionTenantWizard";

/**
 * FE-041: Tenant List and Provisioning Wizard.
 * Lists all tenants with TanStack Table. Provides a wizard to provision new tenants.
 */
export default function TenantsPage() {
  const [showWizard, setShowWizard] = useState(false);

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-page-title text-text-primary">Tenants</h1>
            <p className="mt-1 text-sm text-text-muted">
              Manage tenant accounts and provisioning
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowWizard(true)}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={16} />
            New Tenant
          </button>
        </div>

        {/* Tenant table */}
        <ErrorBoundary>
          <TenantTable />
        </ErrorBoundary>

        {/* Provision wizard modal */}
        {showWizard && (
          <ProvisionTenantWizard onClose={() => setShowWizard(false)} />
        )}
      </div>
    </AppShell>
  );
}
