"use client";

import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/AppShell";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";

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

export default function AgentsPage() {
  const { data, isPending, error } = useQuery({
    queryKey: ["admin-agents"],
    queryFn: () => apiGet<AgentsResponse>("/api/v1/admin/agents"),
  });

  const agents = data?.items ?? [];

  return (
    <AppShell>
      <div className="p-7">
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Agents</h1>
          <p className="mt-1 text-sm text-text-muted">
            AI agents deployed in your workspace
          </p>
        </div>

        {error && (
          <p className="text-sm text-alert">Failed to load agents: {String(error)}</p>
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
            <p className="text-sm text-text-faint">
              No agents deployed yet. Contact your platform administrator to deploy agents.
            </p>
          </div>
        )}

        {!isPending && agents.length > 0 && (
          <div className="rounded-card border border-border bg-bg-surface">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint">
                    Name
                  </th>
                  <th className="px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint">
                    Category
                  </th>
                  <th className="px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint">
                    Version
                  </th>
                  <th className="px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint">
                    Users
                  </th>
                  <th className="px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint">
                    Satisfaction
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
                        <p className="text-[13px] font-medium text-text-primary">
                          {agent.name}
                        </p>
                        <p className="mt-0.5 text-[12px] text-text-faint line-clamp-1">
                          {agent.description}
                        </p>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 font-mono text-[11px] text-text-muted">
                        {agent.category}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "rounded-badge px-2 py-0.5 font-mono text-[11px] uppercase",
                          statusColor(agent.status),
                        )}
                      >
                        {agent.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-[13px] text-text-muted">
                      v{agent.version}
                    </td>
                    <td className="px-4 py-3 font-mono text-[13px] text-text-muted">
                      {agent.user_count}
                    </td>
                    <td className="px-4 py-3 font-mono text-[13px] text-text-muted">
                      {agent.satisfaction_rate != null
                        ? `${Math.round(agent.satisfaction_rate * 100)}%`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppShell>
  );
}
