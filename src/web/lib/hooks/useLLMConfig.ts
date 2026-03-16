"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiDelete } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LLMConfig {
  model_source: "library" | "byollm";
  llm_library_id: string | null;
  byollm: {
    provider: string | null;
    key_present: boolean;
  };
}

export interface UpdateLLMConfigPayload {
  model_source: "library" | "byollm";
  llm_library_id?: string;
}

export interface UpdateBYOLLMPayload {
  provider: string;
  api_key: string;
  endpoint?: string;
}

// ---------------------------------------------------------------------------
// Query Keys
// ---------------------------------------------------------------------------

const CONFIG_KEY = ["admin-llm-config"] as const;

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** GET /api/v1/admin/llm-config */
export function useLLMConfig() {
  return useQuery({
    queryKey: CONFIG_KEY,
    queryFn: () => apiGet<LLMConfig>("/api/v1/admin/llm-config"),
  });
}

/** PATCH /api/v1/admin/llm-config */
export function useUpdateLLMConfig() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: UpdateLLMConfigPayload) =>
      apiPatch<LLMConfig>("/api/v1/admin/llm-config", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CONFIG_KEY });
    },
  });
}

/** PATCH /api/v1/admin/llm-config/byollm */
export function useUpdateBYOLLM() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: UpdateBYOLLMPayload) =>
      apiPatch<LLMConfig>("/api/v1/admin/llm-config/byollm", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CONFIG_KEY });
    },
  });
}

/** DELETE /api/v1/admin/llm-config/byollm */
export function useDeleteBYOLLM() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => apiDelete("/api/v1/admin/llm-config/byollm"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CONFIG_KEY });
    },
  });
}
