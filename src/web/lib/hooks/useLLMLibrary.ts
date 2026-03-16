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
  created_at: string;
  updated_at?: string;
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
