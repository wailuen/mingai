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
  description?: string;
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
  // Fields added in TODO-39/40
  executor_type: string;
  scope: "platform" | "tenant";
  source_mcp_server_id: string | null;
  is_active: boolean;
  endpoint_url?: string | null;
}

export interface RegisterToolPayload {
  name: string;
  provider: string;
  description: string;
  mcp_endpoint: string;
  auth_type: AuthType;
  safety_class: SafetyClass;
  capabilities: string[];
}

export interface DiscoveredTool {
  name: string;
  description: string;
  tags: string[];
  input_schema: Record<string, unknown>;
}

export interface DiscoverToolsResult {
  server_name: string | null;
  server_version: string | null;
  tools: DiscoveredTool[];
}

export interface ToolHealthCheck {
  timestamp: string;
  status: HealthStatus;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function classifyTools(tools: Tool[]): {
  builtins: Tool[];
  mcpIntegrations: Record<string, Tool[]>;
  tenantTools: Tool[];
} {
  const builtins: Tool[] = [];
  const mcpIntegrations: Record<string, Tool[]> = {};
  const tenantTools: Tool[] = [];

  for (const tool of tools) {
    if (tool.executor_type === "builtin") {
      builtins.push(tool);
    } else if (tool.scope === "tenant" || tool.source_mcp_server_id !== null) {
      tenantTools.push(tool);
    } else {
      // MCP integration — scope === 'platform' and not builtin
      const providerKey = tool.provider || "Unknown";
      if (!mcpIntegrations[providerKey]) {
        mcpIntegrations[providerKey] = [];
      }
      mcpIntegrations[providerKey].push(tool);
    }
  }

  return { builtins, mcpIntegrations, tenantTools };
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const TOOLS_KEY = ["platform-tools"] as const;

/** GET /api/v1/platform/tool-catalog — list all tools */
export function useTools() {
  return useQuery({
    queryKey: TOOLS_KEY,
    queryFn: async () => {
      const res = await apiGet<{ items: Tool[]; total: number } | Tool[]>(
        "/api/v1/platform/tool-catalog?page_size=100",
      );
      // Backend returns {items: [...], total: N} — extract the array
      return Array.isArray(res)
        ? res
        : ((res as { items: Tool[] }).items ?? []);
    },
  });
}

/** POST /api/v1/platform/tool-catalog — register new tool */
export function useRegisterTool() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: RegisterToolPayload) =>
      apiPost<Tool>("/api/v1/platform/tool-catalog", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TOOLS_KEY });
    },
  });
}

/** POST /api/v1/platform/tool-catalog/:id/retire — retire a tool */
export function useRetireTool() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiPost<Tool>(`/api/v1/platform/tool-catalog/${id}/retire`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TOOLS_KEY });
    },
  });
}

/** POST /api/v1/platform/tool-catalog/discover — probe MCP endpoint and list tools */
export function useDiscoverTools() {
  return useMutation({
    mutationFn: (payload: { endpoint: string; auth_header?: string }) =>
      apiPost<DiscoverToolsResult>("/api/v1/platform/tool-catalog/discover", payload),
  });
}

/** GET /api/v1/platform/tool-catalog/:id/health — health check history */
export function useToolHealthHistory(id: string | null) {
  return useQuery({
    queryKey: ["platform-tool-health", id],
    queryFn: () =>
      apiGet<ToolHealthCheck[]>(`/api/v1/platform/tool-catalog/${id}/health`),
    enabled: !!id,
    refetchInterval: 30_000,
  });
}
