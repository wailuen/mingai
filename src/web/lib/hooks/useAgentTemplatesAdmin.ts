"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch } from "@/lib/api";
import { getStoredToken } from "@/lib/auth";

// ---------------------------------------------------------------------------
// Types — Platform Admin agent template management
// ---------------------------------------------------------------------------

export interface AgentTemplateVariable {
  name: string;
  type: "string" | "number" | "boolean";
  required: boolean;
  description?: string;
  // legacy fields kept for backward compat
  label?: string;
  options?: string[];
}

export interface GuardrailRule {
  name?: string;
  rule_type?: "keyword_block" | "regex_match" | "content_filter";
  pattern: string;
  action: "block" | "warn" | "redact";
  violation_action?: "block" | "warn" | "redact";
  user_message?: string;
  reason: string;
}

export interface CredentialSchema {
  key: string;
  label: string;
  type: "string" | "secret";
  sensitive: boolean;
}

export interface LLMPolicy {
  required_model?: string | null;
  allowed_providers?: string[];
  tenant_override_enabled?: boolean;
  temperature?: number;
  max_tokens?: number;
}

export interface KBPolicy {
  ownership_mode?: "tenant_managed" | "platform_managed" | "dedicated";
  recommended_categories?: string[];
  required_kb_ids?: string[];
}

export interface A2AOperation {
  name: string;
  description?: string;
  input_schema?: string;
  output_schema?: string;
}

export interface A2AInterface {
  enabled: boolean;
  operations?: A2AOperation[];
  auth_required?: boolean;
  caller_requires_plan?: string | null;
}

export interface AgentTemplateAdmin {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  status: "Draft" | "Published" | "Deprecated";
  version: number;
  version_label?: string | null;
  system_prompt: string;
  variable_definitions: AgentTemplateVariable[];
  guardrails: GuardrailRule[];
  confidence_threshold: number | null;
  changelog: string | null;
  parent_id: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string | null;
  etag?: string | null;
  // ATA-056 Phase A
  required_credentials: string[];
  auth_mode: "none" | "tenant_credentials" | "platform_credentials";
  plan_required: "starter" | "professional" | "enterprise" | null;
  // Phase 2 extended fields
  icon?: string | null;
  tags?: string[];
  llm_policy?: LLMPolicy | null;
  kb_policy?: KBPolicy | null;
  attached_skills?: string[];
  attached_tools?: string[];
  credential_schema?: CredentialSchema[];
  a2a_interface?: A2AInterface | null;
  citation_mode?: "inline" | "footnote" | "none";
  max_response_length?: number | null;
  pii_masking_enabled?: boolean;
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
  version_label?: string | null;
  status: string;
  change_type?: "Initial" | "Patch" | "Minor" | "Major";
  changelog: string | null;
  system_prompt_preview: string;
  publisher?: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TemplateInstance {
  tenant_name: string;
  pinned_version?: string | null;
  status: "Active" | "Paused" | "Outdated";
  last_active_at?: string | null;
}

export interface CreateAgentTemplatePayload {
  name: string;
  description?: string;
  category?: string;
  icon?: string;
  tags?: string[];
  system_prompt: string;
  variable_definitions?: AgentTemplateVariable[];
  guardrails?: GuardrailRule[];
  confidence_threshold?: number;
  required_credentials?: string[];
  auth_mode?: "none" | "tenant_credentials" | "platform_credentials";
  plan_required?: "starter" | "professional" | "enterprise" | null;
  llm_policy?: LLMPolicy;
  kb_policy?: KBPolicy;
  attached_skills?: string[];
  attached_tools?: string[];
  credential_schema?: CredentialSchema[];
  a2a_interface?: A2AInterface;
  citation_mode?: "inline" | "footnote" | "none";
  max_response_length?: number;
  pii_masking_enabled?: boolean;
}

export interface UpdateAgentTemplatePayload {
  name?: string;
  description?: string;
  category?: string;
  icon?: string;
  tags?: string[];
  system_prompt?: string;
  variable_definitions?: AgentTemplateVariable[];
  guardrails?: GuardrailRule[];
  confidence_threshold?: number;
  status?: "Published" | "Deprecated";
  changelog?: string;
  required_credentials?: string[];
  auth_mode?: "none" | "tenant_credentials" | "platform_credentials";
  plan_required?: "starter" | "professional" | "enterprise" | null;
  llm_policy?: LLMPolicy;
  kb_policy?: KBPolicy;
  attached_skills?: string[];
  attached_tools?: string[];
  credential_schema?: CredentialSchema[];
  a2a_interface?: A2AInterface;
  citation_mode?: "inline" | "footnote" | "none";
  max_response_length?: number;
  pii_masking_enabled?: boolean;
}

export interface PublishTemplatePayload {
  version_label: string;
  changelog: string;
}

// ---------------------------------------------------------------------------
// Test Harness types
// ---------------------------------------------------------------------------

export interface TestTemplatePayload {
  query: string;
  variable_values?: Record<string, string>;
  test_prompts?: string[];
}

export interface GuardrailEvent {
  rule_name?: string;
  action: string;
  matched?: string;
}

export interface TemplateTestResult {
  response: string;
  confidence: number;
  sources?: string[];
  kb_queries?: string[];
  guardrail_events?: GuardrailEvent[];
  latency_ms: number;
  // legacy
  prompt?: string;
  tokens_in?: number;
  tokens_out?: number;
  guardrail_triggered?: boolean;
  guardrail_reason?: string;
  timed_out?: boolean;
}

export interface TemplateTestResponse {
  result?: TemplateTestResult;
  tests?: TemplateTestResult[];
}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

const TEMPLATES_KEY = ["platform-agent-templates"] as const;
const TEMPLATE_KEY = (id: string) =>
  ["platform-agent-template", id] as const;
const VERSIONS_KEY = (id: string) =>
  ["platform-agent-template-versions", id] as const;
const INSTANCES_KEY = (id: string) =>
  ["platform-agent-template-instances", id] as const;

// ---------------------------------------------------------------------------
// Hooks — queries
// ---------------------------------------------------------------------------

/** GET /api/v1/platform/agent-templates — list all templates */
export function useAgentTemplatesAdmin(statusFilter?: string) {
  const params = new URLSearchParams({ page: "1", page_size: "100" });
  if (statusFilter && statusFilter !== "all") {
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

/** GET /api/v1/platform/agent-templates/:id — single template with ETag */
export function useAgentTemplate(id: string | null) {
  return useQuery({
    queryKey: TEMPLATE_KEY(id ?? ""),
    queryFn: async () => {
      const token = getStoredToken();
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/platform/agent-templates/${id}`,
        {
          headers: {
            Authorization: `Bearer ${token ?? ""}`,
            "Content-Type": "application/json",
          },
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ??
            `HTTP ${res.status}`,
        );
      }
      const etag = res.headers.get("ETag");
      const data = (await res.json()) as AgentTemplateAdmin;
      return { ...data, etag };
    },
    enabled: !!id,
  });
}

/** GET /api/v1/platform/agent-templates/:id/versions */
export function useAgentTemplateVersions(id: string | null) {
  return useQuery({
    queryKey: VERSIONS_KEY(id ?? ""),
    queryFn: async () => {
      const data = await apiGet<
        { versions: AgentTemplateVersion[] } | AgentTemplateVersion[]
      >(`/api/v1/platform/agent-templates/${id}/versions`);
      return Array.isArray(data) ? data : data.versions;
    },
    enabled: !!id,
  });
}

/** GET /api/v1/platform/agent-templates/:id/instances */
export function useAgentTemplateInstances(id: string | null) {
  return useQuery({
    queryKey: INSTANCES_KEY(id ?? ""),
    queryFn: () =>
      apiGet<{ instances: TemplateInstance[] }>(
        `/api/v1/platform/agent-templates/${id}/instances`,
      ),
    enabled: !!id,
  });
}

// ---------------------------------------------------------------------------
// Hooks — mutations
// ---------------------------------------------------------------------------

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

/**
 * PUT /api/v1/platform/agent-templates/:id — update all fields.
 * Sends If-Match header for optimistic concurrency; throws on 409.
 */
export function useUpdateAgentTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      id,
      payload,
      etag,
    }: {
      id: string;
      payload: UpdateAgentTemplatePayload;
      etag?: string | null;
    }) => {
      const token = getStoredToken();
      const headers: Record<string, string> = {
        Authorization: `Bearer ${token ?? ""}`,
        "Content-Type": "application/json",
      };
      if (etag) {
        headers["If-Match"] = etag;
      }

      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/platform/agent-templates/${id}`,
        {
          method: "PUT",
          headers,
          body: JSON.stringify(payload),
        },
      );

      if (res.status === 409) {
        throw new Error(
          "This template was modified by another admin. Please reload and try again.",
        );
      }

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ?? `HTTP ${res.status}`,
        );
      }

      return (await res.json()) as AgentTemplateAdmin;
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY });
      queryClient.invalidateQueries({
        queryKey: TEMPLATE_KEY(variables.id),
      });
    },
  });
}

/** PATCH /api/v1/platform/agent-templates/:id — partial update (status changes) */
export function usePatchAgentTemplate() {
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
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY });
      queryClient.invalidateQueries({
        queryKey: TEMPLATE_KEY(variables.id),
      });
    },
  });
}

/** POST /api/v1/platform/agent-templates/:id/publish */
export function usePublishAgentTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      version_label,
      changelog,
    }: {
      id: string;
      version_label: string;
      changelog: string;
    }) =>
      apiPost<AgentTemplateAdmin>(
        `/api/v1/platform/agent-templates/${id}/publish`,
        { version_label, changelog },
      ).catch(() =>
        // Fallback: backend may use PATCH-based publish
        apiPatch<AgentTemplateAdmin>(`/api/v1/platform/agent-templates/${id}`, {
          status: "Published",
          changelog,
        }),
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY });
      queryClient.invalidateQueries({
        queryKey: TEMPLATE_KEY(variables.id),
      });
      queryClient.invalidateQueries({
        queryKey: VERSIONS_KEY(variables.id),
      });
    },
  });
}

/** Deprecate a template */
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

/** POST /api/v1/platform/agent-templates/:id/test */
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
    },
  });
}
