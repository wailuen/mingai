"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types — HAR Registry (Human-Agent Registry)
// ---------------------------------------------------------------------------

export type KYBLevel = "none" | "basic" | "verified" | "enterprise";
export type HealthStatus = "AVAILABLE" | "UNAVAILABLE" | "UNKNOWN";

export interface HARAgent {
  id: string;
  name: string;
  description: string;
  industries: string[];
  transaction_types: string[];
  languages: string[];
  kyb_level: KYBLevel;
  trust_score: number;
  health_status: HealthStatus;
  created_at: string;
}

export interface HARAgentListResponse {
  agents: HARAgent[];
  total_count: number;
}

export interface RegistryFilters {
  industry?: string;
  transaction_type?: string;
  language?: string;
  kyb_level?: KYBLevel;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface PublishToRegistryPayload {
  name: string;
  description: string;
  a2a_endpoint: string;
  health_check_url?: string;
  transaction_types: string[];
  industries: string[];
  languages: string[];
}

export interface DiscoveryStats {
  views_7d: number;
  connections_initiated_7d: number;
}

// ---------------------------------------------------------------------------
// Query key factory
// ---------------------------------------------------------------------------

const registryKeys = {
  all: ["har-registry"] as const,
  agents: (filters: RegistryFilters) =>
    ["har-registry", "agents", filters] as const,
  stats: (agentId: string) => ["har-registry", "stats", agentId] as const,
};

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/**
 * HAR-005: List registry agents with filters.
 * GET /api/v1/registry/agents
 */
export function useRegistryAgents(filters: RegistryFilters) {
  return useQuery({
    queryKey: registryKeys.agents(filters),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (filters.industry) params.set("industry", filters.industry);
      if (filters.transaction_type)
        params.set("transaction_type", filters.transaction_type);
      if (filters.language) params.set("language", filters.language);
      if (filters.kyb_level) params.set("kyb_level", filters.kyb_level);
      if (filters.q) params.set("q", filters.q);
      if (filters.limit != null) params.set("limit", String(filters.limit));
      if (filters.offset != null) params.set("offset", String(filters.offset));

      const qs = params.toString();
      return apiGet<HARAgentListResponse>(
        `/api/v1/registry/agents${qs ? `?${qs}` : ""}`,
      );
    },
  });
}

/**
 * HAR-005: Publish an agent to the registry.
 * POST /api/v1/registry/agents
 */
export function usePublishToRegistry() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: PublishToRegistryPayload) =>
      apiPost<HARAgent>("/api/v1/registry/agents", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: registryKeys.all });
    },
  });
}

/**
 * HAR-006: Fetch discovery stats for a single registry agent.
 * GET /api/v1/registry/agents/{id}/discovery-stats
 */
export function useDiscoveryStats(agentId: string | null) {
  return useQuery({
    queryKey: registryKeys.stats(agentId ?? ""),
    queryFn: () =>
      apiGet<DiscoveryStats>(
        `/api/v1/registry/agents/${agentId}/discovery-stats`,
      ),
    enabled: !!agentId,
  });
}

export interface InitiateConnectionPayload {
  from_agent_id: string;
  to_agent_id: string;
  message_type: "CAPABILITY_QUERY" | "RFQ";
  payload?: Record<string, unknown>;
}

export interface InitiateConnectionResult {
  txn_id: string;
  status: string;
  message_id: string;
}

/**
 * HAR-007: Initiate an A2A connection request to a registry agent.
 * POST /api/v1/registry/transactions
 * from_agent_id must belong to the caller's tenant.
 */
export function useInitiateConnection() {
  return useMutation({
    mutationFn: (payload: InitiateConnectionPayload) =>
      apiPost<InitiateConnectionResult>(
        "/api/v1/registry/transactions",
        payload,
      ),
  });
}

/**
 * HAR-006: Fetch aggregate discovery stats across all registered agents.
 * Used on the tenant admin dashboard.
 * GET /api/v1/registry/agents/discovery-stats/aggregate
 */
export function useAggregateDiscoveryStats() {
  return useQuery({
    queryKey: ["har-registry", "stats-aggregate"],
    queryFn: () =>
      apiGet<DiscoveryStats>(
        "/api/v1/registry/agents/discovery-stats/aggregate",
      ),
  });
}
