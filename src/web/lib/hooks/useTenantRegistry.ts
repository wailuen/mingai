"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types -- Platform Admin Registry Management
// ---------------------------------------------------------------------------

export type RegistryStatus = "published" | "draft" | "pending_review";

export interface RegistryAgent {
  id: string;
  name: string;
  category: string;
  publisher_tenant: string;
  status: RegistryStatus;
  install_count: number;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const REGISTRY_AGENTS_KEY = ["platform-registry-agents"] as const;

interface RegistryAgentPage {
  items: RegistryAgent[];
  total: number;
  limit: number;
  offset: number;
}

/** GET /api/v1/registry/agents -- list all registry agents */
export function useRegistryAgents() {
  return useQuery({
    queryKey: REGISTRY_AGENTS_KEY,
    queryFn: async () => {
      const result = await apiGet<RegistryAgentPage | RegistryAgent[]>("/api/v1/registry/agents");
      return Array.isArray(result) ? result : (result as RegistryAgentPage).items ?? [];
    },
  });
}

/** POST /api/v1/registry/agents/{id}/publish -- publish an agent */
export function usePublishAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (agentId: string) =>
      apiPost<RegistryAgent>(
        `/api/v1/registry/agents/${agentId}/publish`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: REGISTRY_AGENTS_KEY });
    },
  });
}

/** POST /api/v1/registry/agents/{id}/unpublish -- unpublish an agent */
export function useUnpublishAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (agentId: string) =>
      apiPost<RegistryAgent>(
        `/api/v1/registry/agents/${agentId}/unpublish`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: REGISTRY_AGENTS_KEY });
    },
  });
}
