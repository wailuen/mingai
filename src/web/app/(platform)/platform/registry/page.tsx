"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { RegistryAgentList } from "./elements/RegistryAgentList";
import { cn } from "@/lib/utils";
import { type RegistryStatus } from "@/lib/hooks/useTenantRegistry";

type TabValue = RegistryStatus | "all";

const TABS: { label: string; value: TabValue }[] = [
  { label: "Published", value: "published" },
  { label: "Pending Review", value: "pending_review" },
  { label: "All", value: "all" },
];

/**
 * FE-050: Tenant Registry Management (Platform Admin).
 * Manages publishing/unpublishing agents in the public registry.
 */
export default function RegistryManagementPage() {
  const [activeTab, setActiveTab] = useState<TabValue>("all");

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">
            Agent Registry Management
          </h1>
          <p className="mt-1 text-sm text-text-muted">
            Manage agent publishing and visibility in the public registry
          </p>
        </div>

        {/* Tabs */}
        <div className="mb-5 border-b border-border">
          <div className="flex gap-0">
            {TABS.map((tab) => (
              <button
                key={tab.value}
                type="button"
                onClick={() => setActiveTab(tab.value)}
                className={cn(
                  "border-b-2 px-3.5 py-2 text-xs font-medium transition-colors",
                  activeTab === tab.value
                    ? "border-accent text-text-primary"
                    : "border-transparent text-text-faint hover:text-text-muted",
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Agent list */}
        <ErrorBoundary>
          <RegistryAgentList statusFilter={activeTab} />
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}
