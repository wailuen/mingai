"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Team {
  id: string;
  name: string;
}

interface TeamsResponse {
  items: Team[];
}

interface ActiveTeamSelectorProps {
  onTeamChange: (teamId: string | null) => void;
  selectedTeamId: string | null;
}

/**
 * FE-011: Dropdown to select which team context to use.
 * Shows "Personal" (no team) as default, lists teams from GET /api/v1/teams.
 */
export function ActiveTeamSelector({
  onTeamChange,
  selectedTeamId,
}: ActiveTeamSelectorProps) {
  const { data, isPending } = useQuery({
    queryKey: ["teams"],
    queryFn: () => apiGet<TeamsResponse>("/api/v1/teams"),
  });

  const teams = data?.items ?? [];

  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const value = e.target.value;
    onTeamChange(value === "" ? null : value);
  }

  return (
    <select
      value={selectedTeamId ?? ""}
      onChange={handleChange}
      disabled={isPending}
      className={cn(
        "rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-sm text-text-muted",
        "focus:border-accent focus:outline-none",
        "transition-colors",
        isPending && "cursor-wait opacity-50",
      )}
    >
      <option value="">Personal</option>
      {teams.map((team) => (
        <option key={team.id} value={team.id}>
          {team.name}
        </option>
      ))}
    </select>
  );
}
