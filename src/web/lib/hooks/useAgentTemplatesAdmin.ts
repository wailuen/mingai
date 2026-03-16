"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types — Platform Admin agent template management
// ---------------------------------------------------------------------------

export interface AgentTemplateVariable {
  name: string;
  type: "text" | "number" | "select";
  label: string;
  required: boolean;
  options?: string[];
}

export interface GuardrailRule {
  pattern: string;
  action: "block" | "warn";
  reason: string;
}

export interface AgentTemplateAdmin {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  status: "Draft" | "Published" | "Deprecated";
  version: number;
  system_prompt: string;
  variable_definitions: AgentTemplateVariable[];
  guardrails: GuardrailRule[];
  confidence_threshold: number | null;
  changelog: string | null;
  parent_id: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string | null;
}

/** Response wrapper for paginated list endpoint */
export interface AgentTemplateListResponse {
  items: AgentTemplateAdmin[];
  total: number;
  page: number;
  page_size: number;
}

export interface AgentTemplateVersion {
  id: string;
  version: number;
  status: string;
  changelog: string | null;
  system_prompt_preview: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface CreateAgentTemplatePayload {
  name: string;
  description?: string;
  category?: string;
  system_prompt: string;
  variable_definitions?: AgentTemplateVariable[];
  guardrails?: GuardrailRule[];
  confidence_threshold?: number;
}

export interface UpdateAgentTemplatePayload {
  name?: string;
  description?: string;
  category?: string;
  system_prompt?: string;
  variable_definitions?: AgentTemplateVariable[];
  guardrails?: GuardrailRule[];
  confidence_threshold?: number;
  status?: "Published" | "Deprecated";
  changelog?: string;
}

// ---------------------------------------------------------------------------
// Test Harness types (PA-021)
// ---------------------------------------------------------------------------

export interface TestTemplatePayload {
  variable_values: Record<string, string>;
  test_prompts: string[];
}

export interface TemplateTestResult {
  prompt: string;
  response: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  guardrail_triggered: boolean;
  guardrail_reason: string;
  timed_out: boolean;
}

export interface TemplateTestResponse {
  tests: TemplateTestResult[];
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const TEMPLATES_KEY = ["platform-agent-templates"] as const;

/** GET /api/v1/platform/agent-templates — list all templates across tenants */
export function useAgentTemplatesAdmin(statusFilter?: string) {
  const params = new URLSearchParams({ page: "1", page_size: "100" });
  if (statusFilter && statusFilter !== "all") {
    // Backend expects title-case status values
    const titleCase =
      statusFilter.charAt(0).toUpperCase() + statusFilter.slice(1);
    params.set("status", titleCase);
  }

  return useQuery({
    queryKey: [...TEMPLATES_KEY, statusFilter ?? "all"],
    queryFn: () =>
      apiGet<AgentTemplateListResponse>(
        `/api/v1/platform/agent-templates?${params.toString()}`,
      ),
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

/** PATCH /api/v1/platform/agent-templates/:id — update template fields or status */
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

/**
 * Publish a template: PATCH with status=Published and changelog.
 * Uses the same PATCH endpoint — no separate /publish route on the backend.
 */
export function usePublishAgentTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, changelog }: { id: string; changelog: string }) =>
      apiPatch<AgentTemplateAdmin>(`/api/v1/platform/agent-templates/${id}`, {
        status: "Published",
        changelog,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY });
    },
  });
}

/**
 * Deprecate a template: PATCH with status=Deprecated.
 */
export function useDeprecateAgentTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiPatch<AgentTemplateAdmin>(`/api/v1/platform/agent-templates/${id}`, {
        status: "Deprecated",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY });
    },
  });
}

/** POST /api/v1/platform/agent-templates/:id/new-version — create draft version */
export function useCreateTemplateVersion() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiPost<AgentTemplateAdmin>(
        `/api/v1/platform/agent-templates/${id}/new-version`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY });
      queryClient.invalidateQueries({
        queryKey: ["platform-agent-template-versions"],
      });
    },
  });
}

/** GET /api/v1/platform/agent-templates/:id/versions — version history */
export function useAgentTemplateVersions(id: string | null) {
  return useQuery({
    queryKey: ["platform-agent-template-versions", id],
    queryFn: async () => {
      const data = await apiGet<{ versions: AgentTemplateVersion[] }>(
        `/api/v1/platform/agent-templates/${id}/versions`,
      );
      return data.versions;
    },
    enabled: !!id,
  });
}

/** POST /api/v1/platform/agent-templates/:id/test — test harness */
export function useTestAgentTemplate() {
  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: TestTemplatePayload;
    }) =>
      apiPost<TemplateTestResponse>(
        `/api/v1/platform/agent-templates/${id}/test`,
        payload,
      ),
  });
}
