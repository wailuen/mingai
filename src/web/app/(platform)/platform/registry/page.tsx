"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { RegistryAgentList } from "./elements/RegistryAgentList";
import { RegistryBrowser } from "./elements/RegistryBrowser";
import { cn } from "@/lib/utils";
import { type RegistryStatus } from "@/lib/hooks/useTenantRegistry";

type ManageTabValue = RegistryStatus | "all";
type TopTabValue = "browse" | "manage";

const MANAGE_TABS: { label: string; value: ManageTabValue }[] = [
  { label: "Published", value: "published" },
  { label: "Pending Review", value: "pending_review" },
  { label: "All", value: "all" },
];

const TOP_TABS: { label: string; value: TopTabValue }[] = [
  { label: "Browse Registry", value: "browse" },
  { label: "Manage", value: "manage" },
];

/**
 * FE-050 / HAR-005: Agent Registry (Platform Admin).
 * Browse tab: searchable HAR agent browser.
 * Manage tab: publish/unpublish workspace agents.
 */
export default function RegistryManagementPage() {
  const [topTab, setTopTab] = useState<TopTabValue>("browse");
  const [manageTab, setManageTab] = useState<ManageTabValue>("all");

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Agent Registry</h1>
          <p className="mt-1 text-body-default text-text-muted">
            Browse the Human-Agent Registry or manage published workspace agents
          </p>
        </div>

        {/* Top-level tabs */}
        <div className="mb-5 border-b border-border">
          <div className="flex gap-0">
            {TOP_TABS.map((tab) => (
              <button
                key={tab.value}
                type="button"
                onClick={() => setTopTab(tab.value)}
                className={cn(
                  "border-b-2 px-3.5 py-2 text-xs font-medium transition-colors",
                  topTab === tab.value
                    ? "border-accent text-text-primary"
                    : "border-transparent text-text-faint hover:text-text-muted",
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Browse tab */}
        {topTab === "browse" && (
          <ErrorBoundary>
            <RegistryBrowser />
          </ErrorBoundary>
        )}

        {/* Manage tab */}
        {topTab === "manage" && (
          <>
            {/* Sub-tabs */}
            <div className="mb-5 flex gap-2">
              {MANAGE_TABS.map((tab) => (
                <button
                  key={tab.value}
                  type="button"
                  onClick={() => setManageTab(tab.value)}
                  className={cn(
                    "rounded-control border px-3 py-1.5 text-xs font-medium transition-colors",
                    manageTab === tab.value
                      ? "border-accent bg-accent-dim text-accent"
                      : "border-border bg-bg-elevated text-text-muted hover:text-text-primary",
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <ErrorBoundary>
              <RegistryAgentList statusFilter={manageTab} />
            </ErrorBoundary>
          </>
        )}
      </div>
    </AppShell>
  );
}
