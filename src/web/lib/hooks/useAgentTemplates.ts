"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

/**
 * Structured capabilities object returned on agent cards (ATA-056 Phase A).
 * Replaces the old untyped `capabilities: string[]` on the wire.
 */
export interface AgentCapabilities {
  kb_ids?: string[];
  tools?: string[];
  guardrails?: {
    blocked_topics?: string[];
    max_response_length?: number;
    require_sources?: boolean;
  };
}

export interface AgentTemplate {
  id: string;
  name: string;
  description: string | null;
  system_prompt: string;
  /** Legacy flat list kept for display-only badge rendering in AgentCard / TemplatePreviewModal. */
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
  // ----- ATA-056 Phase A additions -----
  /** Credential keys the tenant must configure before deploying (e.g. "sharepoint_oauth"). */
  required_credentials: string[];
  /** Auth mechanism required by this template. */
  auth_mode: "none" | "tenant_credentials" | "platform_credentials";
  /** Minimum plan required to deploy; null means no restriction. */
  plan_required: "starter" | "professional" | "enterprise" | null;
  // ----- Library/discovery fields -----
  /** Classification of the template capability model. */
  template_type?: "rag" | "skill_augmented" | "tool_augmented" | "credentialed" | "registered_a2a";
  /** Emoji or URL icon for the template. */
  icon?: string | null;
  /** Searchable tags. */
  tags?: string[];
  /** Skills attached to this template. */
  attached_skills?: Array<{ skill_id?: string; skill_name?: string; name?: string }>;
  /** Tools attached to this template. */
  attached_tools?: Array<{ tool_id?: string; tool_name?: string; name?: string }>;
  /** Number of deployed instances of this template across the tenant. */
  instance_count?: number;
  /** Variable schema (new canonical field). */
  variable_schema?: Array<{ name: string; type: string; required: boolean; description: string }>;
  /** LLM policy settings. */
  llm_policy?: {
    tenant_can_override: boolean;
    defaults?: { temperature?: number; max_tokens?: number };
    required_model?: string | null;
  };
  /** Knowledge base policy. */
  kb_policy?: {
    ownership: string;
    recommended_categories: string[];
    required_kb_ids: string[];
  };
  /** A2A interface definition. */
  a2a_interface?: { a2a_enabled: boolean; operations: unknown[]; auth_required: boolean };
  /** Changelog entries. */
  changelog?: unknown[];
  /** Guardrails list. */
  guardrails?: unknown[];
  /** Whether this is a platform-level template. */
  is_platform?: boolean;
  /** Whether this was created in the Studio. */
  is_studio_template?: boolean;
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
  /**
   * ATA-056 Phase A: access control scope for the deployed agent.
   * Defaults to "workspace" on the backend when omitted.
   */
  access_control?: "workspace" | "role" | "user";
  /** Required when access_control === "role". */
  allowed_roles?: string[];
  /** Required when access_control === "user". */
  allowed_user_ids?: string[];
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
  const params = new URLSearchParams({ page: "1", page_size: "50" });
  if (category) params.set("category", category);

  return useQuery({
    queryKey: [TEMPLATES_KEY, category ?? "all"],
    queryFn: () =>
      apiGet<AgentTemplatesResponse>(
        `/api/v1/agents/templates?${params.toString()}`,
      ),
    staleTime: 5 * 60 * 1000, // 5 minutes
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
