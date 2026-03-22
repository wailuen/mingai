"use client";

import { useState } from "react";
import { Cpu, ArrowRight } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useAuth } from "@/hooks/useAuth";
import { useLLMConfig } from "@/lib/hooks/useLLMConfig";
import { cn } from "@/lib/utils";
import { LibraryModeTab } from "./elements/LibraryModeTab";
import { BYOLLMTab } from "./elements/BYOLLMTab";

type TabKey = "library" | "byollm";

const TABS: { key: TabKey; label: string }[] = [
  { key: "library", label: "Use Library Model" },
  { key: "byollm", label: "Bring Your Own LLM" },
];

function ConfigSkeleton() {
  return (
    <div className="space-y-4">
      <div className="h-10 w-64 animate-pulse rounded-control bg-bg-elevated" />
      <div className="h-32 animate-pulse rounded-card bg-bg-elevated" />
    </div>
  );
}

/**
 * P2LLM-014: Tenant LLM Setup UI.
 * Two tabs: Library mode (select from published profiles) and BYOLLM (enterprise only).
 */
export default function LLMSettingsPage() {
  const { claims } = useAuth();
  const { data: config, isPending, error } = useLLMConfig();
  const [activeTab, setActiveTab] = useState<TabKey>("library");

  const plan = claims?.plan ?? "starter";

  return (
    <AppShell>
      <div className="p-4 sm:p-7">
        {/* Deprecation banner */}
        <div className="mb-4 flex items-center justify-between gap-3 rounded-card border border-warn/30 bg-warn-dim px-4 py-3">
          <p className="text-body-default text-warn">
            This page is being replaced by{" "}
            <span className="font-medium">Settings &rsaquo; LLM Profile</span>.
          </p>
          <Link
            href="/settings/llm-profile"
            className="flex flex-shrink-0 items-center gap-1 text-[11px] font-medium text-warn transition-opacity hover:opacity-80"
          >
            Go to LLM Profile
            <ArrowRight size={12} />
          </Link>
        </div>

        {/* Desktop recommended banner for mobile */}
        <div className="mb-4 flex items-center gap-2 rounded-control border border-warn bg-warn-dim px-3 py-2 text-xs text-warn md:hidden">
          <span>
            Desktop recommended for editing. Some features may be limited on
            mobile.
          </span>
        </div>

        {/* Page header */}
        <div className="mb-6">
          <div className="mb-1 flex items-center gap-2.5">
            <Cpu size={18} className="text-accent" />
            <h1 className="text-page-title text-text-primary">LLM Settings</h1>
          </div>
          <p className="mt-1 text-body-default text-text-muted">
            Configure which language model powers your workspace
          </p>
        </div>

        {/* Tabs */}
        <div className="mb-5 flex gap-0 border-b border-border">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                "px-3.5 py-2 text-[12px] font-medium transition-colors",
                activeTab === tab.key
                  ? "border-b-2 border-accent text-text-primary"
                  : "border-b-2 border-transparent text-text-faint hover:text-text-muted",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        {error && (
          <p className="text-body-default text-alert">
            Failed to load LLM configuration: {error.message}
          </p>
        )}

        {isPending && <ConfigSkeleton />}

        {config && (
          <ErrorBoundary>
            {activeTab === "library" && <LibraryModeTab config={config} />}
            {activeTab === "byollm" && (
              <BYOLLMTab config={config} plan={plan} />
            )}
          </ErrorBoundary>
        )}
      </div>
    </AppShell>
  );
}
