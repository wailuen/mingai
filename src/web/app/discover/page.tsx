"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import {
  usePublicAgents,
  useRequestAgent,
} from "@/lib/hooks/usePublicRegistry";
import { AgentCard } from "./elements/AgentCard";
import {
  RegistryCategoryFilter,
  type RegistryCategory,
} from "./elements/RegistryCategoryFilter";

/**
 * FE-049: Public Agent Registry Discovery Page.
 * End-user facing page for browsing and requesting agents.
 */
export default function DiscoverPage() {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<RegistryCategory>("All");

  const {
    data: agents,
    isPending,
    error,
  } = usePublicAgents(
    search.length >= 2 ? search : undefined,
    category !== "All" ? category : undefined,
  );

  const requestMutation = useRequestAgent();
  const [requestingId, setRequestingId] = useState<string | null>(null);

  function handleRequestAccess(agentId: string) {
    setRequestingId(agentId);
    requestMutation.mutate(agentId, {
      onSettled: () => setRequestingId(null),
    });
  }

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Agent Registry</h1>
          <p className="mt-1 text-body-default text-text-muted">
            Discover AI agents for your workspace
          </p>
        </div>

        {/* Search input */}
        <div className="relative mb-4">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-faint"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search agents by name or description..."
            className="w-full rounded-control border border-border bg-bg-elevated py-2 pl-9 pr-3 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent-ring"
          />
        </div>

        {/* Category filter */}
        <div className="mb-6">
          <RegistryCategoryFilter selected={category} onSelect={setCategory} />
        </div>

        {/* Error state */}
        {error && (
          <p className="text-body-default text-alert">
            Failed to load agents: {error.message}
          </p>
        )}

        {/* Loading skeletons */}
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

        {/* Agent grid */}
        {!isPending && agents && agents.length > 0 && (
          <ErrorBoundary>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {agents.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  onRequestAccess={handleRequestAccess}
                  requesting={requestingId === agent.id}
                />
              ))}
            </div>
          </ErrorBoundary>
        )}

        {/* Empty state */}
        {!isPending && agents && agents.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <p className="text-body-default text-text-faint">
              No agents found matching your search
            </p>
          </div>
        )}
      </div>
    </AppShell>
  );
}
