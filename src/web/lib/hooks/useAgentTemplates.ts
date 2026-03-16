"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

export interface AgentTemplate {
  id: string;
  name: string;
  description: string | null;
  system_prompt: string;
  capabilities: string[];
  category?: string;
  status: "published" | "draft" | "Published" | "Draft";
  is_seed: boolean;
  version: number;
  variable_definitions?: {
    name: string;
    type: "text" | "number" | "select";
    label: string;
    required: boolean;
    options?: string[];
  }[];
  created_at?: string;
}

export interface AgentTemplatesResponse {
  items: AgentTemplate[];
  total: number;
  page: number;
  page_size: number;
}

export interface DeployFromLibraryPayload {
  template_id: string;
  name: string;
  description?: string;
  variable_values?: Record<string, string>;
  kb_ids?: string[];
  access_mode?: "workspace_wide" | "role_restricted" | "user_specific";
}

export interface DeployAgentResponse {
  id: string;
  name: string;
  status: string;
}

/** Legacy payload for the old deploy endpoint */
export interface DeployAgentPayload {
  name: string;
  access_control: "workspace" | "role" | "user";
  access_roles?: string[];
  access_user_ids?: string[];
  kb_selections?: { integration_id: string; mode: string }[];
}

const TEMPLATES_KEY = "agent-templates";

export function useAgentTemplates(category?: string) {
  const params = new URLSearchParams({ page: "1", page_size: "20" });
  if (category) params.set("category", category);

  return useQuery({
    queryKey: [TEMPLATES_KEY, category ?? "all"],
    queryFn: () =>
      apiGet<AgentTemplatesResponse>(
        `/api/v1/agents/templates?${params.toString()}`,
      ),
  });
}

export function useAgentTemplate(id: string | null) {
  return useQuery({
    queryKey: [TEMPLATES_KEY, id],
    queryFn: () => apiGet<AgentTemplate>(`/api/v1/agents/templates/${id}`),
    enabled: !!id,
  });
}

/** POST /api/v1/admin/agents/deploy — Deploy from template library (PA-023) */
export function useDeployFromLibrary() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: DeployFromLibraryPayload) =>
      apiPost<DeployAgentResponse>("/api/v1/admin/agents/deploy", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TEMPLATES_KEY] });
    },
  });
}

/** @deprecated Use useDeployFromLibrary instead */
export function useDeployAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      templateId,
      payload,
    }: {
      templateId: string;
      payload: DeployAgentPayload;
    }) =>
      apiPost<DeployAgentResponse>(
        `/api/v1/agents/templates/${templateId}/deploy`,
        payload,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TEMPLATES_KEY] });
    },
  });
}
