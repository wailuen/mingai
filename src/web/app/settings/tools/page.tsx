"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { PlatformToolsTab } from "./elements/PlatformToolsTab";
import { TenantMCPServersTab } from "./elements/TenantMCPServersTab";
import { cn } from "@/lib/utils";

type TabId = "platform" | "my-tools";

const TABS: { id: TabId; label: string }[] = [
  { id: "platform", label: "Platform Tools" },
  { id: "my-tools", label: "My Tools" },
];

export default function ToolsPage() {
  const [activeTab, setActiveTab] = useState<TabId>("platform");

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Tools</h1>
          <p className="mt-1 text-body-default text-text-muted">
            Browse platform tools and connect your own MCP servers to extend
            agent capabilities
          </p>
        </div>

        {/* Tab bar */}
        <div className="mb-6 border-b border-border">
          <div className="flex gap-1">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "border-b-2 px-4 pb-2.5 text-[12px] font-medium transition-colors",
                  activeTab === tab.id
                    ? "border-accent text-text-primary"
                    : "border-transparent text-text-faint hover:text-text-muted",
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tab content */}
        {activeTab === "platform" && <PlatformToolsTab />}
        {activeTab === "my-tools" && <TenantMCPServersTab />}
      </div>
    </AppShell>
  );
}
