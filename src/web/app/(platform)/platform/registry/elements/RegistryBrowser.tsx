"use client";

import { useState, useEffect } from "react";
import { Search } from "lucide-react";
import { useRegistryAgents } from "@/lib/hooks/useRegistry";
import type {
  HARAgent,
  RegistryFilters,
  KYBLevel,
} from "@/lib/hooks/useRegistry";
import { HARAgentCard, ConnectModal } from "./HARAgentCard";
import {
  RegistryFilterSidebar,
  type RegistryFilterState,
} from "./RegistryFilterSidebar";

const EMPTY_FILTERS: RegistryFilterState = {
  industry: "",
  transaction_type: "",
  language: "",
  kyb_level: "",
};

/**
 * HAR-005: HAR Registry Browser — filter sidebar + agent card grid.
 * Used on the Platform Admin Registry page (Browse tab).
 */
export function RegistryBrowser() {
  const [sidebarFilters, setSidebarFilters] =
    useState<RegistryFilterState>(EMPTY_FILTERS);
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [connectAgent, setConnectAgent] = useState<HARAgent | null>(null);

  // Debounce search 300ms
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchInput), 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const filters: RegistryFilters = {
    ...(sidebarFilters.industry && { industry: sidebarFilters.industry }),
    ...(sidebarFilters.transaction_type && {
      transaction_type: sidebarFilters.transaction_type,
    }),
    ...(sidebarFilters.language && { language: sidebarFilters.language }),
    ...(sidebarFilters.kyb_level && {
      kyb_level: sidebarFilters.kyb_level as KYBLevel,
    }),
    ...(debouncedSearch && { q: debouncedSearch }),
    limit: 50,
  };

  const { data, isPending, error } = useRegistryAgents(filters);

  const agents = data?.agents ?? [];
  const totalCount = data?.total_count ?? 0;

  function handleClearAll() {
    setSidebarFilters(EMPTY_FILTERS);
    setSearchInput("");
  }

  return (
    <div className="flex gap-6">
      {/* Filter sidebar */}
      <RegistryFilterSidebar
        filters={sidebarFilters}
        onChange={setSidebarFilters}
        onClear={() => setSidebarFilters(EMPTY_FILTERS)}
      />

      {/* Main content */}
      <div className="min-w-0 flex-1">
        {/* Search bar */}
        <div className="relative mb-5">
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-faint"
          />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search agents by name, description, or capability..."
            className="w-full rounded-control border border-border bg-bg-elevated py-2 pl-9 pr-3 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent-ring"
          />
        </div>

        {/* Result count */}
        {!isPending && !error && (
          <p className="mb-4 font-mono text-xs text-text-faint">
            {totalCount === 0
              ? "No agents found"
              : `${totalCount.toLocaleString()} agent${totalCount === 1 ? "" : "s"}`}
          </p>
        )}

        {/* Error */}
        {error && (
          <p className="text-sm text-alert">
            Failed to load registry: {error.message}
          </p>
        )}

        {/* Skeleton grid */}
        {isPending && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="h-56 animate-pulse rounded-card border border-border bg-bg-surface"
              />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!isPending && agents.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <p className="text-sm text-text-faint">
              No agents match the current filters
            </p>
            <button
              type="button"
              onClick={handleClearAll}
              className="mt-3 text-xs text-accent hover:underline"
            >
              Clear filters
            </button>
          </div>
        )}

        {/* Agent grid */}
        {!isPending && agents.length > 0 && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent) => (
              <HARAgentCard
                key={agent.id}
                agent={agent}
                onConnect={setConnectAgent}
              />
            ))}
          </div>
        )}
      </div>

      {/* Connect modal */}
      {connectAgent && (
        <ConnectModal
          agent={connectAgent}
          onClose={() => setConnectAgent(null)}
        />
      )}
    </div>
  );
}
