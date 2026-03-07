"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types — match backend schema (tenants/routes.py)
// ---------------------------------------------------------------------------

export interface LLMProfile {
  id: string;
  tenant_id: string;
  name: string;
  provider: string;
  primary_model: string;
  intent_model: string;
  embedding_model: string;
  endpoint_url: string | null;
  is_default: boolean;
  created_at: string;
  updated_at?: string;
}

export interface CreateLLMProfilePayload {
  tenant_id: string;
  name: string;
  provider: string;
  primary_model: string;
  intent_model: string;
  embedding_model: string;
  endpoint_url?: string;
  api_key_ref?: string;
  is_default?: boolean;
}

export interface UpdateLLMProfilePayload {
  name?: string;
  provider?: string;
  primary_model?: string;
  intent_model?: string;
  embedding_model?: string;
  endpoint_url?: string;
  api_key_ref?: string;
  is_default?: boolean;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const PROFILES_KEY = ["platform-llm-profiles"] as const;

/** GET /api/v1/platform/llm-profiles */
export function useLLMProfiles() {
  return useQuery({
    queryKey: PROFILES_KEY,
    queryFn: () => apiGet<LLMProfile[]>("/api/v1/platform/llm-profiles"),
  });
}

/** GET /api/v1/platform/llm-profiles/:id */
export function useLLMProfile(id: string | null) {
  return useQuery({
    queryKey: ["platform-llm-profile", id],
    queryFn: () => apiGet<LLMProfile>(`/api/v1/platform/llm-profiles/${id}`),
    enabled: !!id,
  });
}

/** POST /api/v1/platform/llm-profiles */
export function useCreateLLMProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateLLMProfilePayload) =>
      apiPost<LLMProfile>("/api/v1/platform/llm-profiles", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROFILES_KEY });
    },
  });
}

/** PATCH /api/v1/platform/llm-profiles/:id */
export function useUpdateLLMProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: UpdateLLMProfilePayload;
    }) => apiPatch<LLMProfile>(`/api/v1/platform/llm-profiles/${id}`, payload),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: PROFILES_KEY });
      queryClient.invalidateQueries({
        queryKey: ["platform-llm-profile", variables.id],
      });
    },
  });
}

/** DELETE /api/v1/platform/llm-profiles/:id */
export function useDeleteLLMProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiDelete(`/api/v1/platform/llm-profiles/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROFILES_KEY });
    },
  });
}
