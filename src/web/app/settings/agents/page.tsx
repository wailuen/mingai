"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Globe } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";
import { DiscoveryStatsWidget } from "@/components/registry/DiscoveryStatsWidget";
import { PublishToRegistryModal } from "./elements/PublishToRegistryModal";

interface Agent {
  id: string;
  name: string;
  description: string;
  category: string;
  status: string;
  version: number;
  satisfaction_rate: number | null;
  user_count: number;
  created_at: string;
}

interface AgentsResponse {
  items: Agent[];
  total: number;
}

function statusColor(status: string): string {
  if (status === "published") return "text-accent bg-accent-dim";
  if (status === "draft") return "text-warn bg-warn-dim";
  return "text-text-faint bg-bg-elevated";
}

interface PublishTarget {
  id: string;
  name: string;
  description: string;
}

export default function AgentsPage() {
  const { data, isPending, error } = useQuery({
    queryKey: ["admin-agents"],
    queryFn: () => apiGet<AgentsResponse>("/api/v1/admin/agents"),
  });

  const [publishTarget, setPublishTarget] = useState<PublishTarget | null>(
    null,
  );

  const agents = data?.items ?? [];

  return (
    <AppShell>
      <div className="p-7">
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Agents</h1>
          <p className="mt-1 text-body-default text-text-muted">
            AI agents deployed in your workspace
          </p>
        </div>

        {error && (
          <p className="text-body-default text-alert">
            Failed to load agents: {String(error)}
          </p>
        )}

        {isPending && (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-20 animate-pulse rounded-card border border-border bg-bg-surface"
              />
            ))}
          </div>
        )}

        {!isPending && agents.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <p className="text-body-default text-text-faint">
              No agents deployed yet. Contact your platform administrator to
              deploy agents.
            </p>
          </div>
        )}

        {!isPending && agents.length > 0 && (
          <div className="rounded-card border border-border bg-bg-surface">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border">
                    <th className="px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint">
                      Name
                    </th>
                    <th className="hidden px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint sm:table-cell">
                      Category
                    </th>
                    <th className="px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint">
                      Status
                    </th>
                    <th className="hidden px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint md:table-cell">
                      Version
                    </th>
                    <th className="hidden px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint md:table-cell">
                      Users
                    </th>
                    <th className="hidden px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint md:table-cell">
                      Satisfaction
                    </th>
                    <th className="hidden px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint lg:table-cell">
                      Discovery (7d)
                    </th>
                    <th className="px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((agent) => (
                    <tr
                      key={agent.id}
                      className="border-b border-border-faint last:border-0 hover:bg-accent-dim/30"
                    >
                      <td className="px-4 py-3">
                        <div>
                          <p className="text-body-default font-medium text-text-primary">
                            {agent.name}
                          </p>
                          <p className="mt-0.5 line-clamp-1 text-body-default text-text-faint">
                            {agent.description}
                          </p>
                        </div>
                      </td>
                      <td className="hidden px-4 py-3 sm:table-cell">
                        <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 font-mono text-data-value text-text-muted">
                          {agent.category}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            "rounded-badge px-2 py-0.5 font-mono text-data-value uppercase",
                            statusColor(agent.status),
                          )}
                        >
                          {agent.status}
                        </span>
                      </td>
                      <td className="hidden px-4 py-3 font-mono text-data-value text-text-muted md:table-cell">
                        v{agent.version}
                      </td>
                      <td className="hidden px-4 py-3 font-mono text-data-value text-text-muted md:table-cell">
                        {agent.user_count}
                      </td>
                      <td className="hidden px-4 py-3 font-mono text-data-value text-text-muted md:table-cell">
                        {agent.satisfaction_rate != null
                          ? `${Math.round(agent.satisfaction_rate * 100)}%`
                          : "—"}
                      </td>
                      <td className="hidden px-4 py-3 lg:table-cell">
                        <DiscoveryStatsWidget agentId={agent.id} />
                      </td>
                      <td className="px-4 py-3">
                        {agent.status === "published" && (
                          <button
                            type="button"
                            onClick={() =>
                              setPublishTarget({
                                id: agent.id,
                                name: agent.name,
                                description: agent.description,
                              })
                            }
                            className="flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1.5 text-xs font-medium text-text-muted transition-colors hover:border-accent-ring hover:text-accent"
                          >
                            <Globe size={12} />
                            Publish to Registry
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Publish to Registry modal */}
      {publishTarget && (
        <PublishToRegistryModal
          agentId={publishTarget.id}
          agentName={publishTarget.name}
          agentDescription={publishTarget.description}
          onClose={() => setPublishTarget(null)}
          onPublished={() => setPublishTarget(null)}
        />
      )}
    </AppShell>
  );
}
