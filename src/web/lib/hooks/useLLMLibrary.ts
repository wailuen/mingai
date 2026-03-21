"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type LLMLibraryProvider = "azure_openai" | "openai_direct" | "anthropic";
export type LLMLibraryStatus = "Draft" | "Published" | "Deprecated";
export type PlanTier = "starter" | "professional" | "enterprise";

export interface LLMLibraryEntry {
  id: string;
  provider: LLMLibraryProvider;
  model_name: string;
  display_name: string;
  plan_tier: PlanTier;
  is_recommended: boolean;
  status: LLMLibraryStatus;
  best_practices_md?: string;
  pricing_per_1k_tokens_in: number | null;
  pricing_per_1k_tokens_out: number | null;
  endpoint_url?: string;
  api_version?: string;
  key_present: boolean;
  api_key_last4?: string;
  last_test_passed_at?: string;
  created_at: string;
  updated_at?: string;
}

export interface TenantAssignment {
  tenant_id: string;
  tenant_name: string;
  assigned_at: string;
}

export interface TestPromptResult {
  prompt: string;
  response: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  estimated_cost_usd: number | null;
}

export interface TestEntryResult {
  tests: TestPromptResult[];
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
  endpoint_url?: string;
  api_key?: string;
  api_version?: string;
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
  endpoint_url?: string;
  api_key?: string;
  api_version?: string;
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
      apiPost<LLMLibraryEntry>("/api/v1/platform/llm-library", payload, {
        skipRedirectOn401: true,
      }),
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
      apiPatch<LLMLibraryEntry>(`/api/v1/platform/llm-library/${id}`, payload, {
        skipRedirectOn401: true,
      }),
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
        {},
        { skipRedirectOn401: true },
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
        {},
        { skipRedirectOn401: true },
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

/** Tests connectivity and basic prompts for a library entry. */
export function useTestProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiPost<TestEntryResult>(
        `/api/v1/platform/llm-library/${id}/test`,
        {},
        { skipRedirectOn401: true },
      ),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({
        queryKey: ["platform-llm-library-entry", id],
      });
      queryClient.invalidateQueries({ queryKey: LIBRARY_KEY });
    },
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
        `/api/v1/platform/llm-library/${id}/tenant-assignments`,
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
