"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch } from "@/lib/api";
import { getStoredToken } from "@/lib/auth";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PlanTier = "starter" | "professional" | "enterprise";
export type ProfileSlot = "chat" | "intent" | "vision" | "agent";

export interface SlotInfo {
  library_entry_id: string | null;
  model_name: string | null;
  display_name: string | null;
  provider: string | null;
  test_passed_at: string | null;
  is_available_on_plan: boolean;
}

export interface EffectiveProfile {
  profile_id: string;
  profile_name: string;
  description: string | null;
  plan_tier: PlanTier;
  is_byollm: boolean;
  slots: {
    chat: SlotInfo;
    intent: SlotInfo;
    vision: SlotInfo;
    agent: SlotInfo;
  };
  available_profiles_count: number;
}

export interface AvailableProfile {
  id: string;
  name: string;
  description: string | null;
  plan_tiers: PlanTier[];
  estimated_cost_per_1k_queries: number | null;
  slots: {
    chat: {
      model_name: string | null;
      display_name: string | null;
      provider: string | null;
    };
    intent: {
      model_name: string | null;
      display_name: string | null;
      provider: string | null;
    };
    vision: {
      model_name: string | null;
      display_name: string | null;
      provider: string | null;
    };
    agent: {
      model_name: string | null;
      display_name: string | null;
      provider: string | null;
    };
  };
}

export interface BYOLLMEntry {
  id: string;
  slot: ProfileSlot;
  provider: string;
  model_name: string;
  display_name: string | null;
  endpoint_url: string | null;
  test_passed_at: string | null;
  created_at: string;
}

export interface CreateBYOLLMEntryPayload {
  slot: ProfileSlot;
  provider: "azure_openai" | "openai" | "anthropic" | "google";
  endpoint_url?: string;
  api_key: string;
  api_version?: string;
  model_name: string;
  display_name?: string;
}

export interface TestBYOLLMResult {
  passed: boolean;
  latency_ms: number | null;
  error_code: string | null;
  error_message: string | null;
}

export interface RotateKeyPayload {
  api_key: string;
}

// ---------------------------------------------------------------------------
// Query Keys
// ---------------------------------------------------------------------------

const EFFECTIVE_PROFILE_KEY = ["admin-llm-effective-profile"] as const;
const AVAILABLE_PROFILES_KEY = ["admin-llm-available-profiles"] as const;
const BYOLLM_ENTRIES_KEY = ["admin-byollm-entries"] as const;

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** GET /api/v1/admin/llm-config */
export function useEffectiveProfile() {
  return useQuery({
    queryKey: EFFECTIVE_PROFILE_KEY,
    queryFn: () => apiGet<EffectiveProfile>("/api/v1/admin/llm-config"),
  });
}

/** GET /api/v1/admin/llm-config/available-profiles */
export function useAvailableProfiles() {
  return useQuery({
    queryKey: AVAILABLE_PROFILES_KEY,
    queryFn: () =>
      apiGet<AvailableProfile[]>("/api/v1/admin/llm-config/available-profiles"),
  });
}

/** POST /api/v1/admin/llm-config/select-profile */
export function useSelectProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (profileId: string) =>
      apiPost<EffectiveProfile>("/api/v1/admin/llm-config/select-profile", {
        profile_id: profileId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EFFECTIVE_PROFILE_KEY });
      queryClient.invalidateQueries({ queryKey: AVAILABLE_PROFILES_KEY });
    },
  });
}

/** GET /api/v1/admin/byollm/library-entries */
export function useBYOLLMEntries() {
  return useQuery({
    queryKey: BYOLLM_ENTRIES_KEY,
    queryFn: () =>
      apiGet<BYOLLMEntry[]>("/api/v1/admin/byollm/library-entries"),
  });
}

/** POST /api/v1/admin/byollm/library-entries */
export function useCreateBYOLLMEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateBYOLLMEntryPayload) =>
      apiPost<BYOLLMEntry>("/api/v1/admin/byollm/library-entries", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: BYOLLM_ENTRIES_KEY });
    },
  });
}

/** POST /api/v1/admin/byollm/library-entries/:id/test */
export function useTestBYOLLMEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiPost<TestBYOLLMResult>(
        `/api/v1/admin/byollm/library-entries/${id}/test`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: BYOLLM_ENTRIES_KEY });
    },
  });
}

/** PATCH /api/v1/admin/byollm/library-entries/:id/rotate-key */
export function useRotateBYOLLMKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: RotateKeyPayload }) =>
      apiPatch<BYOLLMEntry>(
        `/api/v1/admin/byollm/library-entries/${id}/rotate-key`,
        payload,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: BYOLLM_ENTRIES_KEY });
    },
  });
}

/** POST /api/v1/admin/byollm/profiles/:id/activate */
export function useActivateBYOLLMProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiPost<EffectiveProfile>(
        `/api/v1/admin/byollm/profiles/${id}/activate`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EFFECTIVE_PROFILE_KEY });
      queryClient.invalidateQueries({ queryKey: BYOLLM_ENTRIES_KEY });
    },
  });
}

// ---------------------------------------------------------------------------
// Test connection (inline, no id required yet — used in AddEndpointModal)
// Uses raw fetch with multipart-style because we need to test before creating the entry
// ---------------------------------------------------------------------------

export interface TestConnectionPayload {
  provider: "azure_openai" | "openai" | "anthropic" | "google";
  endpoint_url?: string;
  api_key: string;
  api_version?: string;
  model_name: string;
}

export interface TestConnectionResult {
  passed: boolean;
  latency_ms: number | null;
  error_code: string | null;
  error_message: string | null;
}

/** POST /api/v1/admin/byollm/test-connection — inline test before creating entry */
export async function testConnection(
  payload: TestConnectionPayload,
): Promise<TestConnectionResult> {
  const token = getStoredToken();
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  const res = await fetch(`${apiUrl}/api/v1/admin/byollm/test-connection`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    return {
      passed: false,
      latency_ms: null,
      error_code: "request_failed",
      error_message: body?.message ?? "Request failed",
    };
  }
  return res.json();
}
