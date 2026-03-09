"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { Plus, Search } from "lucide-react";
import { TenantTable } from "./elements/TenantTable";
import { NewTenantWizard } from "./elements/NewTenantWizard";

/**
 * Platform Admin: Tenant management page.
 * Lists all tenants with search/filter, row click opens detail panel,
 * "New Tenant" button opens 2-step wizard modal.
 */
export default function TenantsPage() {
  const [showWizard, setShowWizard] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  return (
    <AppShell>
      <div className="p-7">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-page-title text-text-primary">Tenants</h1>
            <p className="mt-1 text-sm text-text-muted">
              Manage workspace tenants and their configurations
            </p>
          </div>
          <button
            onClick={() => setShowWizard(true)}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={16} />
            New Tenant
          </button>
        </div>

        {/* Search bar */}
        <div className="relative mb-5">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-faint"
          />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search tenants..."
            className="w-full max-w-sm rounded-control border border-border bg-bg-elevated py-2 pl-9 pr-3 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
          />
        </div>

        {/* Table */}
        <ErrorBoundary>
          <TenantTable searchQuery={searchQuery} />
        </ErrorBoundary>

        {/* New Tenant Wizard */}
        {showWizard && <NewTenantWizard onClose={() => setShowWizard(false)} />}
      </div>
    </AppShell>
  );
}
