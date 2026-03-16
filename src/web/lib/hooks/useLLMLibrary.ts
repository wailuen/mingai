"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type LLMLibraryProvider =
  | "azure_openai"
  | "openai_direct"
  | "anthropic";
export type LLMLibraryStatus = "Draft" | "Published" | "Deprecated";
export type PlanTier = "starter" | "professional" | "enterprise";

export type ModelSlotKey =
  | "intent_model"
  | "primary_model"
  | "vision_model"
  | "embedding_model";

export interface ModelSlot {
  provider: LLMLibraryProvider;
  deployment_name: string;
  override: boolean;
}

export interface LLMLibraryEntry {
  id: string;
  provider: LLMLibraryProvider;
  model_name: string;
  display_name: string;
  plan_tier: PlanTier;
  is_recommended: boolean;
  status: LLMLibraryStatus;
  best_practices_md: string;
  pricing_per_1k_tokens_in: number;
  pricing_per_1k_tokens_out: number;
  model_slots?: Record<ModelSlotKey, ModelSlot>;
  created_at: string;
  updated_at?: string;
}

export interface TenantAssignment {
  tenant_id: string;
  tenant_name: string;
  assigned_at: string;
}

export interface TestProfileResult {
  success: boolean;
  latency_ms: number;
  error?: string;
  slot_results: Record<ModelSlotKey, { reachable: boolean; latency_ms: number; error?: string }>;
}

export interface CreateLLMLibraryPayload {
  provider: LLMLibraryProvider;
  model_name: string;
  display_name: string;
  plan_tier: PlanTier;
  is_recommended?: boolean;
  best_practices_md?: string;
  pricing_per_1k_tokens_in: number;
  pricing_per_1k_tokens_out: number;
  model_slots?: Record<ModelSlotKey, ModelSlot>;
}

export interface UpdateLLMLibraryPayload {
  provider?: LLMLibraryProvider;
  model_name?: string;
  display_name?: string;
  plan_tier?: PlanTier;
  is_recommended?: boolean;
  best_practices_md?: string;
  pricing_per_1k_tokens_in?: number;
  pricing_per_1k_tokens_out?: number;
  model_slots?: Record<ModelSlotKey, ModelSlot>;
}

// ---------------------------------------------------------------------------
// Query Keys
// ---------------------------------------------------------------------------

const LIBRARY_KEY = ["platform-llm-library"] as const;

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** GET /api/v1/platform/llm-library?status=... */
export function useLLMLibrary(status?: LLMLibraryStatus) {
  const params = status ? `?status=${status}` : "";
  return useQuery({
    queryKey: [...LIBRARY_KEY, status ?? "all"],
    queryFn: () =>
      apiGet<LLMLibraryEntry[]>(`/api/v1/platform/llm-library${params}`),
  });
}

/** GET /api/v1/platform/llm-library/:id */
export function useLLMLibraryEntry(id: string | null) {
  return useQuery({
    queryKey: ["platform-llm-library-entry", id],
    queryFn: () =>
      apiGet<LLMLibraryEntry>(`/api/v1/platform/llm-library/${id}`),
    enabled: !!id,
  });
}

/** POST /api/v1/platform/llm-library — create Draft */
export function useCreateLLMLibraryEntry() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateLLMLibraryPayload) =>
      apiPost<LLMLibraryEntry>("/api/v1/platform/llm-library", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LIBRARY_KEY });
    },
  });
}

/** PATCH /api/v1/platform/llm-library/:id — update */
export function useUpdateLLMLibraryEntry() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: UpdateLLMLibraryPayload;
    }) =>
      apiPatch<LLMLibraryEntry>(
        `/api/v1/platform/llm-library/${id}`,
        payload
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: LIBRARY_KEY });
      queryClient.invalidateQueries({
        queryKey: ["platform-llm-library-entry", variables.id],
      });
    },
  });
}

/** POST /api/v1/platform/llm-library/:id/publish — Draft -> Published */
export function usePublishLLMLibraryEntry() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiPost<LLMLibraryEntry>(
        `/api/v1/platform/llm-library/${id}/publish`,
        {}
      ),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: LIBRARY_KEY });
      queryClient.invalidateQueries({
        queryKey: ["platform-llm-library-entry", id],
      });
    },
  });
}

/** POST /api/v1/platform/llm-library/:id/deprecate — Published -> Deprecated */
export function useDeprecateLLMLibraryEntry() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiPost<LLMLibraryEntry>(
        `/api/v1/platform/llm-library/${id}/deprecate`,
        {}
      ),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: LIBRARY_KEY });
      queryClient.invalidateQueries({
        queryKey: ["platform-llm-library-entry", id],
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Test Profile (POST /api/v1/platform/llm-library/:id/test)
// ---------------------------------------------------------------------------

/** Tests connectivity and latency for all model slots in a profile. */
export function useTestProfile() {
  return useMutation({
    mutationFn: (id: string) =>
      apiPost<TestProfileResult>(
        `/api/v1/platform/llm-library/${id}/test`,
        {}
      ),
  });
}

// ---------------------------------------------------------------------------
// Tenant Assignments (GET /api/v1/platform/llm-library/:id/tenant-assignments)
// ---------------------------------------------------------------------------

/** Returns list of tenants currently assigned to a given library entry. */
export function useTenantAssignments(id: string | null) {
  return useQuery({
    queryKey: ["platform-llm-library-assignments", id],
    queryFn: () =>
      apiGet<TenantAssignment[]>(
        `/api/v1/platform/llm-library/${id}/tenant-assignments`
      ),
    enabled: !!id,
  });
}

// ---------------------------------------------------------------------------
// Library options for tenant selectors (GET /api/v1/admin/llm-config/library-options)
// ---------------------------------------------------------------------------

export interface LibraryOption {
  id: string;
  display_name: string;
  provider: LLMLibraryProvider;
  model_name: string;
  best_practices_md: string;
}

/** Published library entries available for tenant assignment. */
export function useLLMLibraryOptions() {
  return useQuery({
    queryKey: ["llm-library-options"],
    queryFn: () =>
      apiGet<LibraryOption[]>("/api/v1/admin/llm-config/library-options"),
  });
}
