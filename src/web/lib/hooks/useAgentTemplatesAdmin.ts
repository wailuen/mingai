"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types — Platform Admin agent template management
// ---------------------------------------------------------------------------

export interface AgentTemplateVariable {
  name: string;
  type: "text" | "number" | "select";
  required: boolean;
}

export interface AgentTemplateGuardrails {
  blocked_topics: string;
  confidence_threshold: number;
}

export interface AgentTemplateAdmin {
  id: string;
  name: string;
  category: string;
  status: "published" | "draft";
  version: number;
  satisfaction_rate: number | null;
  tenant_adoption_count: number;
  system_prompt: string;
  variables: AgentTemplateVariable[];
  guardrails: AgentTemplateGuardrails;
  created_at: string;
  updated_at?: string;
}

export interface AgentTemplateVersion {
  version: number;
  changelog: string;
  published_at: string;
  is_current: boolean;
}

export interface CreateAgentTemplatePayload {
  name: string;
  category: string;
  system_prompt: string;
  variables: AgentTemplateVariable[];
  guardrails: AgentTemplateGuardrails;
}

export interface UpdateAgentTemplatePayload {
  name?: string;
  category?: string;
  system_prompt?: string;
  variables?: AgentTemplateVariable[];
  guardrails?: AgentTemplateGuardrails;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const TEMPLATES_KEY = ["platform-agent-templates"] as const;

/** GET /api/v1/platform/agent-templates — list all templates across tenants */
export function useAgentTemplatesAdmin() {
  return useQuery({
    queryKey: TEMPLATES_KEY,
    queryFn: () =>
      apiGet<AgentTemplateAdmin[]>("/api/v1/platform/agent-templates"),
  });
}

/** POST /api/v1/platform/agent-templates — create new template */
export function useCreateAgentTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateAgentTemplatePayload) =>
      apiPost<AgentTemplateAdmin>("/api/v1/platform/agent-templates", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY });
    },
  });
}

/** PATCH /api/v1/platform/agent-templates/:id — update template */
export function useUpdateAgentTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: UpdateAgentTemplatePayload;
    }) =>
      apiPatch<AgentTemplateAdmin>(
        `/api/v1/platform/agent-templates/${id}`,
        payload,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY });
    },
  });
}

/** POST /api/v1/platform/agent-templates/:id/publish — publish template */
export function usePublishAgentTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiPost<AgentTemplateAdmin>(
        `/api/v1/platform/agent-templates/${id}/publish`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY });
    },
  });
}

/** GET /api/v1/platform/agent-templates/:id/versions — version history */
export function useAgentTemplateVersions(id: string | null) {
  return useQuery({
    queryKey: ["platform-agent-template-versions", id],
    queryFn: () =>
      apiGet<AgentTemplateVersion[]>(
        `/api/v1/platform/agent-templates/${id}/versions`,
      ),
    enabled: !!id,
  });
}
