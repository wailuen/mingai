"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types -- Public Agent Registry (end-user facing)
// ---------------------------------------------------------------------------

export interface PublicAgent {
  id: string;
  name: string;
  description: string;
  category: string;
  publisher: string;
  satisfaction_rate: number;
  install_count: number;
  capabilities: string[];
  is_installed: boolean;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const PUBLIC_AGENTS_KEY = ["public-registry-agents"] as const;

/**
 * FE-049: Fetch public registry agents.
 * GET /api/v1/registry/agents
 * Optionally filter by search term and/or category.
 */
export function usePublicAgents(search?: string, category?: string) {
  return useQuery({
    queryKey: [...PUBLIC_AGENTS_KEY, search, category],
    queryFn: () => {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (category && category !== "All") params.set("category", category);
      const qs = params.toString();
      return apiGet<PublicAgent[]>(
        `/api/v1/registry/agents${qs ? `?${qs}` : ""}`,
      );
    },
  });
}

/**
 * FE-049: Request access to an agent.
 * POST /api/v1/registry/agents/{id}/request
 */
export function useRequestAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (agentId: string) =>
      apiPost<{ status: string }>(
        `/api/v1/registry/agents/${agentId}/request`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PUBLIC_AGENTS_KEY });
    },
  });
}
