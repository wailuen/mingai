"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiDelete, ApiException } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface A2AOperation {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
}

export interface A2ACard {
  name: string;
  description?: string;
  operations: A2AOperation[];
}

export type A2AAgentStatus = "active" | "unhealthy" | "unverified" | "archived";

export interface TenantA2AAgent {
  id: string;
  name: string;
  description?: string;
  status: A2AAgentStatus;
  template_type: "registered_a2a";
  source_card_url?: string;
  imported_card?: A2ACard;
  last_verified_at?: string;
  created_at?: string;
}

interface A2AAgentsResponse {
  items: TenantA2AAgent[];
  total: number;
}

export interface RegisterA2APayload {
  name: string;
  description?: string;
  source_card_url: string;
  icon?: string;
  access_control?: "workspace" | "role" | "user";
  allowed_roles?: string[];
  allowed_user_ids?: string[];
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const QUERY_KEY = ["tenant-a2a-agents"] as const;

/**
 * Fetch the list of registered A2A agents.
 * Tries GET /api/v1/admin/agents/a2a first.
 * If the endpoint returns 404 (not yet provisioned), resolves to an empty list.
 */
export function useTenantA2AAgents() {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: async (): Promise<TenantA2AAgent[]> => {
      try {
        const res = await apiGet<A2AAgentsResponse | TenantA2AAgent[]>(
          "/api/v1/admin/agents/a2a",
        );
        // Normalise: backend may return paginated { items } or plain array
        if (Array.isArray(res)) return res;
        return (res as A2AAgentsResponse).items ?? [];
      } catch (err) {
        if (err instanceof ApiException && err.status === 404) {
          return [];
        }
        throw err;
      }
    },
  });
}

/**
 * Register an external A2A agent by card URL.
 * POST /api/v1/admin/agents/a2a/register
 */
export function useRegisterA2AAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RegisterA2APayload) =>
      apiPost<TenantA2AAgent>("/api/v1/admin/agents/a2a/register", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

/**
 * Re-verify an existing A2A agent (re-fetches its card).
 * POST /api/v1/admin/agents/a2a/{id}/verify
 */
export function useVerifyA2AAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiPost<TenantA2AAgent>(`/api/v1/admin/agents/a2a/${id}/verify`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

/**
 * Soft-delete (deregister) a registered A2A agent.
 * DELETE /api/v1/admin/agents/a2a/{id}
 */
export function useDeregisterA2AAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiDelete<void>(`/api/v1/admin/agents/a2a/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}
