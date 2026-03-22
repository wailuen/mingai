"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiDelete } from "@/lib/api";
import type { ProviderType, ProviderStatus } from "./useLLMProviders";

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

/**
 * GET /api/v1/admin/llm-config
 * @deprecated Use `useEffectiveProfile` from `useLLMProfileConfig` instead (TODO-36).
 */
export function useLLMConfig() {
  return useQuery({
    queryKey: CONFIG_KEY,
    queryFn: () => apiGet<LLMConfig>("/api/v1/admin/llm-config"),
  });
}

// LibraryOption is a subset of LLMLibraryEntry — only published fields TA can see
export interface LibraryOption {
  id: string;
  provider: string;
  model_name: string;
  display_name: string;
  plan_tier: string;
  is_recommended: boolean;
  pricing_per_1k_tokens_in: number | null;
  pricing_per_1k_tokens_out: number | null;
}

/**
 * GET /api/v1/admin/llm-config/library-options — tenant-admin accessible
 * @deprecated Use `useAvailableProfiles` from `useLLMProfileConfig` instead (TODO-36).
 */
export function useLLMLibraryOptions() {
  return useQuery({
    queryKey: ["admin-llm-library-options"] as const,
    queryFn: () =>
      apiGet<LibraryOption[]>("/api/v1/admin/llm-config/library-options"),
  });
}

/**
 * PATCH /api/v1/admin/llm-config
 * @deprecated Use `useSelectProfile` from `useLLMProfileConfig` instead (TODO-36).
 */
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

/**
 * PATCH /api/v1/admin/llm-config/byollm
 * @deprecated Use `useCreateBYOLLMEntry` from `useLLMProfileConfig` instead (TODO-36).
 */
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

/**
 * DELETE /api/v1/admin/llm-config/byollm
 * @deprecated Use BYOLLM removal via `useLLMProfileConfig` hooks instead (TODO-36).
 */
export function useDeleteBYOLLM() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => apiDelete("/api/v1/admin/llm-config/byollm"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CONFIG_KEY });
    },
  });
}

// ---------------------------------------------------------------------------
// PVDR-016: Tenant provider selection
// ---------------------------------------------------------------------------

export interface AvailableProvider {
  id: string;
  provider_type: ProviderType;
  display_name: string;
  is_default: boolean;
  provider_status: ProviderStatus;
  slots_available?: string[];
}

export interface ProviderSelectionResponse {
  provider_id: string | null;
  using_default: boolean;
}

const AVAILABLE_PROVIDERS_KEY = ["admin-llm-available-providers"] as const;
const PROVIDER_SELECTION_KEY = ["admin-llm-provider-selection"] as const;

/** GET /api/v1/admin/llm-config/providers — list of enabled providers for tenant admin */
export function useAvailableProviders() {
  return useQuery({
    queryKey: AVAILABLE_PROVIDERS_KEY,
    queryFn: () =>
      apiGet<AvailableProvider[]>("/api/v1/admin/llm-config/providers"),
  });
}

/** PATCH /api/v1/admin/llm-config/provider — select or clear a provider */
export function useSelectProvider() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: { provider_id: string | null }) =>
      apiPatch<ProviderSelectionResponse>(
        "/api/v1/admin/llm-config/provider",
        payload,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CONFIG_KEY });
      queryClient.invalidateQueries({ queryKey: AVAILABLE_PROVIDERS_KEY });
      queryClient.invalidateQueries({ queryKey: PROVIDER_SELECTION_KEY });
    },
  });
}
