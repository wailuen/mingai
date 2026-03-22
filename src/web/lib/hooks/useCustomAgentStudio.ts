"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost, apiPut } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SkillAttachment {
  skill_id: string;
  invocation_override?: string | null;
}

export interface GuardrailsSchema {
  blocked_topics?: string[];
  confidence_threshold?: number | null;
  max_response_length?: number | null;
}

export type AgentIconType =
  | "hr"
  | "finance"
  | "legal"
  | "it"
  | "search"
  | "custom";

export interface AccessRules {
  access_control: "workspace" | "role" | "user";
  allowed_roles?: string[];
  allowed_user_ids?: string[];
}

export interface CustomAgentFormData {
  name: string;
  description: string;
  category: string;
  icon: AgentIconType;
  system_prompt: string;
  kb_ids: string[];
  attached_skills: SkillAttachment[];
  attached_tools: string[];
  guardrails: GuardrailsSchema;
  access_rules?: AccessRules;
}

export interface StudioAgent {
  id: string;
  name: string;
  description?: string;
  category?: string;
  icon?: string;
  system_prompt?: string;
  status: "draft" | "published";
  kb_ids?: string[];
  attached_skills?: SkillAttachment[];
  attached_tools?: string[];
  guardrails?: GuardrailsSchema;
  access_rules?: AccessRules;
  is_studio_template: true;
  created_at?: string;
  updated_at?: string;
}

export interface StudioTestPayload {
  query: string;
}

export interface StudioTestResult {
  response?: string;
  confidence?: number;
  sources_count?: number;
  latency_ms?: number;
  error?: string;
}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

const TEMPLATES_KEY = "agent-templates";

// ---------------------------------------------------------------------------
// Hooks — mutations
// ---------------------------------------------------------------------------

/** POST /api/v1/admin/agents/studio/create */
export function useCreateCustomAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CustomAgentFormData) =>
      apiPost<StudioAgent>("/api/v1/admin/agents/studio/create", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TEMPLATES_KEY] });
    },
  });
}

/** PUT /api/v1/admin/agents/studio/{id} */
export function useUpdateCustomAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      agentId,
      payload,
    }: {
      agentId: string;
      payload: Partial<CustomAgentFormData>;
    }) =>
      apiPut<StudioAgent>(`/api/v1/admin/agents/studio/${agentId}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TEMPLATES_KEY] });
    },
  });
}

/** POST /api/v1/admin/agents/studio/{id}/test */
export function useTestCustomAgent() {
  return useMutation({
    mutationFn: ({
      agentId,
      payload,
    }: {
      agentId: string;
      payload: StudioTestPayload;
    }) =>
      apiPost<StudioTestResult>(
        `/api/v1/admin/agents/studio/${agentId}/test`,
        payload,
      ),
  });
}

/** POST /api/v1/admin/agents/studio/{id}/publish */
export function usePublishCustomAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      agentId,
      payload,
    }: {
      agentId: string;
      payload?: { access_rules?: AccessRules };
    }) =>
      apiPost<StudioAgent>(
        `/api/v1/admin/agents/studio/${agentId}/publish`,
        payload ?? {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TEMPLATES_KEY] });
    },
  });
}
