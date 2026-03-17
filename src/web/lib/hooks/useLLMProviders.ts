"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types — match backend schema (providers/routes.py)
// ---------------------------------------------------------------------------

export type ProviderType =
  | "azure_openai"
  | "openai"
  | "anthropic"
  | "deepseek"
  | "dashscope"
  | "doubao"
  | "gemini";

export type ProviderStatus = "healthy" | "error" | "unchecked";

export interface Provider {
  id: string;
  provider_type: ProviderType;
  display_name: string;
  description?: string;
  endpoint?: string;
  models: Record<string, string>;
  options: Record<string, string>;
  is_enabled: boolean;
  is_default: boolean;
  provider_status: ProviderStatus;
  last_health_check_at?: string;
  health_error?: string;
  key_present: boolean;
  slots_available?: string[];
}

export interface ProvidersResponse {
  providers: Provider[];
  bootstrap_active: boolean;
}

export interface ProviderHealthSummary {
  total: number;
  healthy: number;
  error: number;
  unchecked: number;
  last_checked_at?: string;
}

export interface ProviderTestResult {
  success: boolean;
  latency_ms: number;
  error: string | null;
}

export interface CreateProviderPayload {
  provider_type: ProviderType;
  display_name: string;
  description?: string;
  endpoint?: string;
  models?: Record<string, string>;
  options?: Record<string, string>;
  is_enabled?: boolean;
  is_default?: boolean;
  api_key: string;
}

export interface UpdateProviderPayload {
  display_name?: string;
  description?: string;
  endpoint?: string;
  models?: Record<string, string>;
  options?: Record<string, string>;
  is_enabled?: boolean;
  is_default?: boolean;
  api_key?: string;
}

// ---------------------------------------------------------------------------
// Query Keys
// ---------------------------------------------------------------------------

const PROVIDERS_KEY = ["platform-providers"] as const;
const HEALTH_SUMMARY_KEY = ["platform-providers-health-summary"] as const;

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** GET /api/v1/platform/providers */
export function useLLMProviders() {
  return useQuery({
    queryKey: PROVIDERS_KEY,
    queryFn: () => apiGet<ProvidersResponse>("/api/v1/platform/providers"),
  });
}

/** GET /api/v1/platform/providers/health-summary */
export function useLLMProviderHealthSummary() {
  return useQuery({
    queryKey: HEALTH_SUMMARY_KEY,
    queryFn: () =>
      apiGet<ProviderHealthSummary>(
        "/api/v1/platform/providers/health-summary",
      ),
  });
}

/** POST /api/v1/platform/providers */
export function useCreateProvider() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateProviderPayload) =>
      apiPost<Provider>("/api/v1/platform/providers", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
      queryClient.invalidateQueries({ queryKey: HEALTH_SUMMARY_KEY });
    },
  });
}

/** PATCH /api/v1/platform/providers/:id */
export function useUpdateProvider() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: UpdateProviderPayload;
    }) => apiPatch<Provider>(`/api/v1/platform/providers/${id}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
      queryClient.invalidateQueries({ queryKey: HEALTH_SUMMARY_KEY });
    },
  });
}

/** DELETE /api/v1/platform/providers/:id */
export function useDeleteProvider() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/v1/platform/providers/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
      queryClient.invalidateQueries({ queryKey: HEALTH_SUMMARY_KEY });
    },
  });
}

/** POST /api/v1/platform/providers/:id/test */
export function useTestProvider() {
  return useMutation({
    mutationFn: (id: string) =>
      apiPost<ProviderTestResult>(`/api/v1/platform/providers/${id}/test`, {}),
  });
}

/** POST /api/v1/platform/providers/:id/set-default */
export function useSetDefaultProvider() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiPost<Provider>(`/api/v1/platform/providers/${id}/set-default`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
    },
  });
}
