"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type A2AHealthDot = "green" | "yellow" | "red";

export interface PlatformA2AAgent {
  id: string;
  name: string;
  description?: string;
  source_card_url: string;
  a2a_scope: "platform" | "tenant";
  plan_required?: string | null;
  assigned_tenants: string[];
  guardrail_overlay: Record<string, unknown>;
  status: string;
  deprecation_at?: string | null;
  deprecated_by?: string | null;
  last_verified_at?: string | null;
  health_consecutive_failures?: number;
  last_health_http_status?: number | null;
  created_at?: string;
}

export interface A2ARegistrySummary {
  platform_count: number;
  tenant_count: number;
  total_invocations_30d: number;
}

export interface RegisterPlatformA2APayload {
  source_card_url: string;
  plan_required?: string | null;
  assigned_tenants?: string[];
  guardrail_overlay?: Record<string, unknown>;
  name_override?: string;
  description_override?: string;
}

export interface UpdatePlatformA2APayload {
  plan_required?: string | null;
  assigned_tenants?: string[];
  guardrail_overlay?: Record<string, unknown>;
  name?: string;
  description?: string;
}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

const PA_A2A_KEY = "platform-a2a-agents";
const PA_A2A_SUMMARY_KEY = "platform-a2a-summary";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function is404(err: unknown): boolean {
  return (
    err !== null &&
    typeof err === "object" &&
    "status" in err &&
    (err as { status: number }).status === 404
  );
}

export function calcHealthDot(agent: PlatformA2AAgent): A2AHealthDot {
  if (!agent.last_verified_at) return "red";
  const ageMs = Date.now() - new Date(agent.last_verified_at).getTime();
  const ageH = ageMs / (1000 * 60 * 60);
  if (ageH < 1 && (agent.health_consecutive_failures ?? 0) === 0)
    return "green";
  if (ageH < 24) return "yellow";
  return "red";
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function usePlatformA2AAgents() {
  return useQuery({
    queryKey: [PA_A2A_KEY],
    queryFn: async () => {
      try {
        return await apiGet<{ items: PlatformA2AAgent[]; total: number }>(
          "/api/v1/platform/a2a-agents",
        );
      } catch (err) {
        if (is404(err)) return { items: [], total: 0 };
        throw err;
      }
    },
    staleTime: 30 * 1000,
  });
}

export function useA2ARegistrySummary() {
  return useQuery({
    queryKey: [PA_A2A_SUMMARY_KEY],
    queryFn: async () => {
      try {
        return await apiGet<A2ARegistrySummary>(
          "/api/v1/platform/a2a-agents/registry-summary",
        );
      } catch (err) {
        if (is404(err)) {
          return {
            platform_count: 0,
            tenant_count: 0,
            total_invocations_30d: 0,
          };
        }
        throw err;
      }
    },
    staleTime: 60 * 1000,
  });
}

export function useRegisterPlatformA2AAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RegisterPlatformA2APayload) =>
      apiPost<PlatformA2AAgent>(
        "/api/v1/platform/a2a-agents/register",
        payload,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PA_A2A_KEY] });
      queryClient.invalidateQueries({ queryKey: [PA_A2A_SUMMARY_KEY] });
    },
  });
}

export function useUpdatePlatformA2AAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      agentId,
      payload,
    }: {
      agentId: string;
      payload: UpdatePlatformA2APayload;
    }) =>
      apiPut<PlatformA2AAgent>(
        `/api/v1/platform/a2a-agents/${agentId}`,
        payload,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PA_A2A_KEY] });
    },
  });
}

export function useVerifyPlatformA2AAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) =>
      apiPost<PlatformA2AAgent>(
        `/api/v1/platform/a2a-agents/${agentId}/verify`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PA_A2A_KEY] });
    },
  });
}

export function useDeprecatePlatformA2AAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) =>
      apiPost<PlatformA2AAgent>(
        `/api/v1/platform/a2a-agents/${agentId}/deprecate`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PA_A2A_KEY] });
      queryClient.invalidateQueries({ queryKey: [PA_A2A_SUMMARY_KEY] });
    },
  });
}

export function useDeletePlatformA2AAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) =>
      apiDelete<{ deleted: boolean }>(`/api/v1/platform/a2a-agents/${agentId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PA_A2A_KEY] });
      queryClient.invalidateQueries({ queryKey: [PA_A2A_SUMMARY_KEY] });
    },
  });
}
