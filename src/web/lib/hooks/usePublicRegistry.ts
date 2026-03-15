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
  satisfaction_rate: number | null;
  install_count: number;
  capabilities: string[];
  is_installed: boolean;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const PUBLIC_AGENTS_KEY = ["public-registry-agents"] as const;

interface AgentListRaw {
  id: string;
  name: string;
  description: string;
  category: string;
  avatar?: string | null;
}

/**
 * FE-049: Fetch agents available in this workspace.
 * Uses /api/v1/agents which is accessible to all authenticated users (viewers included).
 */
export function usePublicAgents(search?: string, category?: string) {
  return useQuery({
    queryKey: [...PUBLIC_AGENTS_KEY, search, category],
    queryFn: async () => {
      const res = await apiGet<{ items: AgentListRaw[] }>("/api/v1/agents");
      let items: AgentListRaw[] = res.items ?? [];

      // Client-side filtering
      if (search) {
        const q = search.toLowerCase();
        items = items.filter(
          (a) =>
            a.name.toLowerCase().includes(q) ||
            a.description.toLowerCase().includes(q),
        );
      }
      if (category && category !== "All") {
        items = items.filter((a) => a.category === category);
      }

      return items.map(
        (a): PublicAgent => ({
          id: a.id,
          name: a.name,
          description: a.description,
          category: a.category,
          publisher: "mingai Platform",
          satisfaction_rate: null,
          install_count: 0,
          capabilities: [],
          is_installed: true,
        }),
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
