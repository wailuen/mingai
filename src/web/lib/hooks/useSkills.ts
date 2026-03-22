"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ExecutionPattern =
  | "prompt"
  | "tool_composing"
  | "sequential_pipeline";
export type InvocationMode = "llm_invoked" | "pipeline";
export type PlanRequired = "starter" | "professional" | "enterprise" | null;
export type SkillStatus = "published" | "draft" | "deprecated";

export interface PlatformSkill {
  id: string;
  name: string;
  description?: string;
  category?: string;
  execution_pattern: ExecutionPattern;
  invocation_mode: InvocationMode;
  plan_required?: PlanRequired;
  is_mandatory?: boolean;
  status: "published" | "draft";
  version: number;
  tool_dependencies?: string[];
  prompt_template?: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  adopted?: boolean;
  pinned_version?: string | null;
}

export interface TenantSkill {
  id: string;
  name: string;
  description?: string;
  category?: string;
  execution_pattern: "prompt" | "tool_composing";
  invocation_mode: InvocationMode;
  pipeline_trigger?: string | null;
  status: SkillStatus;
  version: number;
  prompt_template: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  tool_dependencies?: string[];
  llm_config?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface PlatformSkillsResponse {
  items: PlatformSkill[];
  total: number;
}

export interface TenantSkillsResponse {
  items: TenantSkill[];
  total: number;
}

export interface CreateSkillPayload {
  name: string;
  description?: string;
  category?: string;
  execution_pattern: "prompt" | "tool_composing";
  invocation_mode: InvocationMode;
  pipeline_trigger?: string | null;
  prompt_template: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  tool_dependencies?: string[];
  llm_config?: Record<string, unknown>;
}

export interface UpdateSkillPayload extends Partial<CreateSkillPayload> {}

export interface PinSkillVersionPayload {
  pinned_version: string | null;
}

export interface TestSkillPayload {
  input_values: Record<string, unknown>;
}

export interface TestSkillResult {
  output?: string;
  tokens_used?: number;
  latency_ms?: number;
  tool_calls?: Array<{
    name: string;
    args?: Record<string, unknown>;
    result?: unknown;
  }>;
  error?: string;
}

export interface PlatformSkillFilters {
  search?: string;
  category?: string;
  adopted?: boolean;
}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

const PLATFORM_SKILLS_KEY = "platform-skills";
const TENANT_SKILLS_KEY = "tenant-skills";

// ---------------------------------------------------------------------------
// Hooks — reads
// ---------------------------------------------------------------------------

/** GET /api/v1/skills — list platform skills with optional filters */
export function usePlatformSkills(filters?: PlatformSkillFilters) {
  const params = new URLSearchParams();
  if (filters?.search) params.set("search", filters.search);
  if (filters?.category) params.set("category", filters.category);
  if (filters?.adopted !== undefined)
    params.set("adopted", String(filters.adopted));
  const qs = params.toString();

  return useQuery({
    queryKey: [PLATFORM_SKILLS_KEY, filters ?? {}],
    queryFn: async () => {
      try {
        const res = await apiGet<PlatformSkillsResponse>(
          `/api/v1/skills${qs ? `?${qs}` : ""}`,
        );
        return res;
      } catch (err: unknown) {
        // 404 means no platform skills seeded — return empty gracefully
        if (
          err &&
          typeof err === "object" &&
          "status" in err &&
          (err as { status: number }).status === 404
        ) {
          return { items: [], total: 0 } as PlatformSkillsResponse;
        }
        throw err;
      }
    },
    staleTime: 2 * 60 * 1000,
  });
}

/** GET /api/v1/admin/skills — list tenant-authored skills */
export function useTenantSkills() {
  return useQuery({
    queryKey: [TENANT_SKILLS_KEY],
    queryFn: async () => {
      try {
        const res = await apiGet<TenantSkillsResponse>("/api/v1/admin/skills");
        return res;
      } catch (err: unknown) {
        if (
          err &&
          typeof err === "object" &&
          "status" in err &&
          (err as { status: number }).status === 404
        ) {
          return { items: [], total: 0 } as TenantSkillsResponse;
        }
        throw err;
      }
    },
    staleTime: 2 * 60 * 1000,
  });
}

/** GET /api/v1/admin/skills/{id} — get a single tenant skill */
export function useTenantSkill(skillId: string | null) {
  return useQuery({
    queryKey: [TENANT_SKILLS_KEY, skillId],
    queryFn: () => apiGet<TenantSkill>(`/api/v1/admin/skills/${skillId}`),
    enabled: !!skillId,
  });
}

// ---------------------------------------------------------------------------
// Hooks — mutations
// ---------------------------------------------------------------------------

/** POST /api/v1/skills/{id}/adopt */
export function useAdoptSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (skillId: string) =>
      apiPost<{ adopted: boolean }>(`/api/v1/skills/${skillId}/adopt`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PLATFORM_SKILLS_KEY] });
      queryClient.invalidateQueries({ queryKey: [TENANT_SKILLS_KEY] });
    },
  });
}

/** DELETE /api/v1/skills/{id}/adopt */
export function useUnadoptSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (skillId: string) =>
      apiDelete<{ adopted: boolean }>(`/api/v1/skills/${skillId}/adopt`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PLATFORM_SKILLS_KEY] });
      queryClient.invalidateQueries({ queryKey: [TENANT_SKILLS_KEY] });
    },
  });
}

/** PUT /api/v1/skills/{id}/pin */
export function usePinSkillVersion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      skillId,
      payload,
    }: {
      skillId: string;
      payload: PinSkillVersionPayload;
    }) =>
      apiPut<{ pinned_version: string | null }>(
        `/api/v1/skills/${skillId}/pin`,
        payload,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PLATFORM_SKILLS_KEY] });
    },
  });
}

/** POST /api/v1/admin/skills */
export function useCreateSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateSkillPayload) =>
      apiPost<TenantSkill>("/api/v1/admin/skills", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TENANT_SKILLS_KEY] });
    },
  });
}

/** PUT /api/v1/admin/skills/{id} */
export function useUpdateSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      skillId,
      payload,
    }: {
      skillId: string;
      payload: UpdateSkillPayload;
    }) => apiPut<TenantSkill>(`/api/v1/admin/skills/${skillId}`, payload),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: [TENANT_SKILLS_KEY] });
      queryClient.invalidateQueries({
        queryKey: [TENANT_SKILLS_KEY, variables.skillId],
      });
    },
  });
}

/** POST /api/v1/admin/skills/{id}/publish */
export function usePublishSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (skillId: string) =>
      apiPost<TenantSkill>(`/api/v1/admin/skills/${skillId}/publish`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TENANT_SKILLS_KEY] });
    },
  });
}

/** DELETE /api/v1/admin/skills/{id} */
export function useDeleteSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (skillId: string) =>
      apiDelete<{ deleted: boolean }>(`/api/v1/admin/skills/${skillId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TENANT_SKILLS_KEY] });
    },
  });
}

/** POST /api/v1/admin/skills/{id}/test */
export function useTestSkill() {
  return useMutation({
    mutationFn: ({
      skillId,
      payload,
    }: {
      skillId: string;
      payload: TestSkillPayload;
    }) =>
      apiPost<TestSkillResult>(`/api/v1/admin/skills/${skillId}/test`, payload),
  });
}
