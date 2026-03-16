"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types — Platform Admin tool catalog management
// ---------------------------------------------------------------------------

export type SafetyClass = "read_only" | "write" | "destructive";
export type HealthStatus = "healthy" | "degraded" | "unavailable";
export type AuthType = "none" | "api_key" | "oauth2";

export interface Tool {
  id: string;
  name: string;
  provider: string;
  mcp_endpoint: string;
  auth_type: AuthType;
  safety_class: SafetyClass;
  health_status: HealthStatus;
  last_ping: string | null;
  invocation_count: number;
  error_rate_pct: number;
  p50_latency_ms: number;
  capabilities: string[];
  created_at: string;
  updated_at?: string;
}

export interface RegisterToolPayload {
  name: string;
  mcp_endpoint: string;
  auth_type: AuthType;
  safety_class: SafetyClass;
  capabilities: string[];
}

export interface ToolHealthCheck {
  timestamp: string;
  status: HealthStatus;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const TOOLS_KEY = ["platform-tools"] as const;

/** GET /api/v1/platform/tools — list all tools */
export function useTools() {
  return useQuery({
    queryKey: TOOLS_KEY,
    queryFn: async () => {
      const res = await apiGet<{ tools: Tool[] } | Tool[]>(
        "/api/v1/platform/tools",
      );
      // Backend returns {tools: [...], total: N} — extract the array
      return Array.isArray(res) ? res : (res as { tools: Tool[] }).tools ?? [];
    },
  });
}

/** POST /api/v1/platform/tools — register new tool */
export function useRegisterTool() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: RegisterToolPayload) =>
      apiPost<Tool>("/api/v1/platform/tools", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TOOLS_KEY });
    },
  });
}

/** POST /api/v1/platform/tools/:id/retire — retire a tool */
export function useRetireTool() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiPost<Tool>(`/api/v1/platform/tools/${id}/retire`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TOOLS_KEY });
    },
  });
}

/** GET /api/v1/platform/tools/:id/health — health check history */
export function useToolHealthHistory(id: string | null) {
  return useQuery({
    queryKey: ["platform-tool-health", id],
    queryFn: () =>
      apiGet<ToolHealthCheck[]>(`/api/v1/platform/tools/${id}/health`),
    enabled: !!id,
    refetchInterval: 30_000,
  });
}
