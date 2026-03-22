"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ToolExecutor = "builtin" | "http_wrapper" | "mcp_sse";
export type PlanRequired = "starter" | "professional" | "enterprise" | null;
export type CredentialSource = "none" | "tenant_managed" | "platform_managed";
export type MCPTransport = "sse" | "streamable_http";
export type MCPAuthType = "none" | "bearer" | "api_key";
export type MCPServerStatus = "pending" | "verified" | "error" | "inactive";

export interface PlatformTool {
  id: string;
  name: string;
  description?: string;
  executor_type: ToolExecutor;
  plan_required?: PlanRequired;
  credential_source?: CredentialSource;
  input_schema?: Record<string, unknown>;
  rate_limit_rpm?: number | null;
}

export interface MCPTool {
  id: string;
  name: string;
  description?: string;
  input_schema?: Record<string, unknown>;
  usage_count?: number;
}

export interface MCPServer {
  id: string;
  name: string;
  description?: string;
  endpoint_url: string;
  transport: MCPTransport;
  auth_type: MCPAuthType;
  status: MCPServerStatus;
  last_error?: string | null;
  last_verified_at?: string | null;
  tools?: MCPTool[];
  created_at?: string;
}

export interface TenantTool {
  id: string;
  name: string;
  description?: string;
  executor: "mcp_sse";
  server_id?: string;
  server_name?: string;
  usage_count?: number;
  input_schema?: Record<string, unknown>;
}

export interface PlatformToolsResponse {
  items: PlatformTool[];
  total: number;
}

export interface MCPServersResponse {
  items: MCPServer[];
  total: number;
}

export interface TenantToolsResponse {
  items: TenantTool[];
  total: number;
}

export interface RegisterMCPServerPayload {
  name: string;
  description?: string;
  endpoint_url: string;
  transport: MCPTransport;
  auth_type: MCPAuthType;
  auth_token?: string;
  auth_header_name?: string;
}

export interface UpdateMCPServerPayload extends Partial<RegisterMCPServerPayload> {}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

const PLATFORM_TOOLS_KEY = "platform-tools";
const MCP_SERVERS_KEY = "mcp-servers";
const TENANT_TOOLS_KEY = "tenant-tools";

// ---------------------------------------------------------------------------
// Helper — normalise 404 → empty list
// ---------------------------------------------------------------------------

function is404(err: unknown): boolean {
  return (
    err !== null &&
    typeof err === "object" &&
    "status" in err &&
    (err as { status: number }).status === 404
  );
}

// ---------------------------------------------------------------------------
// Hooks — platform tools
// ---------------------------------------------------------------------------

/** GET /api/v1/tools — list platform tools (graceful 404 → empty) */
export function usePlatformTools() {
  return useQuery({
    queryKey: [PLATFORM_TOOLS_KEY],
    queryFn: async () => {
      try {
        return await apiGet<PlatformToolsResponse>("/api/v1/tools");
      } catch (err) {
        if (is404(err)) {
          return { items: [], total: 0 } as PlatformToolsResponse;
        }
        throw err;
      }
    },
    staleTime: 2 * 60 * 1000,
  });
}

// ---------------------------------------------------------------------------
// Hooks — MCP servers
// ---------------------------------------------------------------------------

/** GET /api/v1/admin/mcp-servers — list tenant MCP servers */
export function useMCPServers() {
  return useQuery({
    queryKey: [MCP_SERVERS_KEY],
    queryFn: async () => {
      try {
        return await apiGet<MCPServersResponse>("/api/v1/admin/mcp-servers");
      } catch (err) {
        if (is404(err)) {
          return { items: [], total: 0 } as MCPServersResponse;
        }
        throw err;
      }
    },
    staleTime: 30 * 1000,
  });
}

/** GET /api/v1/admin/mcp-servers/{id} — server detail + enumerated tools */
export function useMCPServer(serverId: string | null) {
  return useQuery({
    queryKey: [MCP_SERVERS_KEY, serverId],
    queryFn: () => apiGet<MCPServer>(`/api/v1/admin/mcp-servers/${serverId}`),
    enabled: !!serverId,
  });
}

/** POST /api/v1/admin/mcp-servers — register a new MCP server (returns 202) */
export function useRegisterMCPServer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RegisterMCPServerPayload) =>
      apiPost<MCPServer>("/api/v1/admin/mcp-servers", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [MCP_SERVERS_KEY] });
    },
  });
}

/** PUT /api/v1/admin/mcp-servers/{id} — update server */
export function useUpdateMCPServer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      serverId,
      payload,
    }: {
      serverId: string;
      payload: UpdateMCPServerPayload;
    }) => apiPut<MCPServer>(`/api/v1/admin/mcp-servers/${serverId}`, payload),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: [MCP_SERVERS_KEY] });
      queryClient.invalidateQueries({
        queryKey: [MCP_SERVERS_KEY, variables.serverId],
      });
    },
  });
}

/** DELETE /api/v1/admin/mcp-servers/{id} — delete server */
export function useDeleteMCPServer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) =>
      apiDelete<{ deleted: boolean }>(`/api/v1/admin/mcp-servers/${serverId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [MCP_SERVERS_KEY] });
      queryClient.invalidateQueries({ queryKey: [TENANT_TOOLS_KEY] });
    },
  });
}

/** POST /api/v1/admin/mcp-servers/{id}/verify — manual re-verify */
export function useReverifyMCPServer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) =>
      apiPost<MCPServer>(`/api/v1/admin/mcp-servers/${serverId}/verify`, {}),
    onSuccess: (_data, serverId) => {
      queryClient.invalidateQueries({ queryKey: [MCP_SERVERS_KEY] });
      queryClient.invalidateQueries({
        queryKey: [MCP_SERVERS_KEY, serverId],
      });
      queryClient.invalidateQueries({ queryKey: [TENANT_TOOLS_KEY] });
    },
  });
}

// ---------------------------------------------------------------------------
// Hooks — tenant tools
// ---------------------------------------------------------------------------

/** GET /api/v1/admin/tools — list tenant tools enumerated from MCP servers */
export function useTenantTools() {
  return useQuery({
    queryKey: [TENANT_TOOLS_KEY],
    queryFn: async () => {
      try {
        return await apiGet<TenantToolsResponse>("/api/v1/admin/tools");
      } catch (err) {
        if (is404(err)) {
          return { items: [], total: 0 } as TenantToolsResponse;
        }
        throw err;
      }
    },
    staleTime: 30 * 1000,
  });
}
