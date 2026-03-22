"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost, apiPatch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types — MCP Integration Builder (TODO-22)
// ---------------------------------------------------------------------------

export interface ParsedEndpoint {
  method: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
  path: string;
  summary?: string;
  description?: string;
  parameters?: Record<string, unknown>;
  request_body_schema?: Record<string, unknown>;
  response_schema?: Record<string, unknown>;
}

export interface ParsedAPIDoc {
  format: string;
  title?: string;
  base_url?: string;
  endpoints: ParsedEndpoint[];
}

export interface ParseAPIDocPayload {
  content: string;
  format: "auto" | "openapi_json" | "openapi_yaml" | "postman";
}

export interface ToolRegistration {
  endpoint_index: number;
  name: string;
  description: string;
  rate_limit_per_minute?: number;
  plan_required?: "starter" | "professional" | "enterprise" | null;
  credential_source: "none" | "platform_managed" | "tenant_managed";
}

export interface RegisterToolsPayload {
  parsed_doc: ParsedAPIDoc;
  registrations: ToolRegistration[];
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const TOOLS_KEY = ["platform-tools"] as const;

/**
 * POST /api/v1/platform/tools/parse-api-doc
 * Parses an uploaded API doc (OpenAPI JSON/YAML or Postman) and returns
 * a list of discovered endpoints.
 */
export function useParseAPIDoc() {
  return useMutation({
    mutationFn: (payload: ParseAPIDocPayload) =>
      apiPost<ParsedAPIDoc>("/api/v1/platform/tools/parse-api-doc", payload),
  });
}

/**
 * POST /api/v1/platform/tools/register-tools
 * Registers selected endpoints from a parsed API doc as platform tools.
 */
export function useRegisterPlatformTools() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: RegisterToolsPayload) =>
      apiPost<{ registered: number }>(
        "/api/v1/platform/tools/register-tools",
        payload,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TOOLS_KEY });
    },
  });
}

/**
 * PATCH /api/v1/platform/tools/{id}
 * Deactivates (or reactivates) a platform tool.
 */
export function useDeactivatePlatformTool() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      apiPatch<{ id: string; is_active: boolean }>(
        `/api/v1/platform/tools/${id}`,
        { is_active },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TOOLS_KEY });
    },
  });
}
