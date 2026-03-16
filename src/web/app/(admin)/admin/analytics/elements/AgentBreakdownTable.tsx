"use client";

import { useState } from "react";
import { LineChart, Line, ResponsiveContainer } from "recharts";
import { ArrowUpDown } from "lucide-react";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { useSatisfactionFull } from "@/lib/hooks/useAnalytics";
import type { AgentBreakdownEntry } from "@/lib/hooks/useAnalytics";
import { CHART_COLORS } from "@/lib/chartColors";

type SortField = "satisfaction_pct" | "total_ratings";
type SortDir = "asc" | "desc";

function satisfactionColor(pct: number): string {
  if (pct >= 80) return "text-accent";
  if (pct >= 60) return "text-warn";
  return "text-alert";
}

function MiniSparkline({ data }: { data: number[] }) {
  const chartData = data.map((value, i) => ({ i, v: value }));

  return (
    <div className="h-[20px] w-[60px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData}>
          <Line
            type="monotone"
            dataKey="v"
            stroke={CHART_COLORS.accent}
            strokeWidth={1.5}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * FE-037: Per-agent satisfaction breakdown table with 7-day sparklines.
 *
 * Fetches agent_breakdown from the satisfaction API endpoint.
 * Columns: Agent Name, Satisfaction %, Total Ratings, 7-day Sparkline.
 * Sortable by satisfaction % and total ratings.
 */
export function AgentBreakdownTable() {
  const { data, isPending } = useSatisfactionFull();
  const [sortField, setSortField] = useState<SortField>("satisfaction_pct");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function toggleSort(field: SortField) {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  }

  const breakdown = data?.agent_breakdown ?? [];

  const sorted = [...breakdown].sort((a, b) => {
    const multiplier = sortDir === "asc" ? 1 : -1;
    return (a[sortField] - b[sortField]) * multiplier;
  });

  if (isPending) {
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-6">
        <div className="mb-4 h-5 w-48 animate-pulse rounded bg-bg-elevated" />
        <table className="w-full">
          <tbody>
            {Array.from({ length: 4 }).map((_, i) => (
              <TableRowSkeleton key={i} columns={4} />
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="rounded-card border border-border-faint bg-bg-surface p-6">
      <h2 className="mb-4 text-[15px] font-semibold text-text-primary">
        Agent Breakdown
      </h2>

      {sorted.length === 0 ? (
        <p className="text-sm text-text-muted">No agent data yet</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                  Agent
                </th>
                <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                  <button
                    onClick={() => toggleSort("satisfaction_pct")}
                    className="inline-flex items-center gap-1 transition-colors hover:text-text-muted"
                  >
                    Satisfaction
                    <ArrowUpDown size={10} />
                  </button>
                </th>
                <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                  <button
                    onClick={() => toggleSort("total_ratings")}
                    className="inline-flex items-center gap-1 transition-colors hover:text-text-muted"
                  >
                    Ratings
                    <ArrowUpDown size={10} />
                  </button>
                </th>
                <th className="hidden pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint sm:table-cell">
                  7-Day Trend
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((agent: AgentBreakdownEntry) => (
                <tr
                  key={agent.agent_id}
                  className="border-b border-border-faint transition-colors hover:bg-accent-dim"
                >
                  <td className="py-3 pr-4 text-[13px] font-medium text-text-primary">
                    {agent.agent_name}
                  </td>
                  <td
                    className={`py-3 pr-4 font-mono text-[13px] ${satisfactionColor(agent.satisfaction_pct)}`}
                  >
                    {agent.satisfaction_pct.toFixed(1)}%
                  </td>
                  <td className="py-3 pr-4 font-mono text-[13px] text-text-primary">
                    {agent.total_ratings.toLocaleString()}
                  </td>
                  <td className="hidden py-3 sm:table-cell">
                    {agent.trend_7d.length > 0 ? (
                      <MiniSparkline data={agent.trend_7d} />
                    ) : (
                      <span className="text-xs text-text-faint">--</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
