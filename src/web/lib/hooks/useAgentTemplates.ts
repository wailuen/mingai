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
  status: "published" | "draft";
  is_seed: boolean;
  version: number;
  created_at?: string;
}

export interface AgentTemplatesResponse {
  items: AgentTemplate[];
  total: number;
  page: number;
  page_size: number;
}

export interface DeployAgentPayload {
  name: string;
  access_control: "workspace" | "role" | "user";
  kb_ids: string[];
}

export interface DeployAgentResponse {
  id: string;
  name: string;
  status: string;
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
