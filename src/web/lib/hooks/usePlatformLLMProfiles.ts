"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ProfileSlot = "chat" | "intent" | "vision" | "agent";
export type ProfileStatus = "active" | "draft" | "deprecated";
export type PlanTier = "starter" | "professional" | "enterprise";

export interface SlotAssignment {
  library_entry_id: string;
  model_name: string;
  display_name: string;
  provider: string;
  health_status: "healthy" | "degraded" | "unknown";
  test_passed_at: string | null;
  pricing_per_1k_tokens_in: number | null;
  pricing_per_1k_tokens_out: number | null;
}

export interface PlatformProfile {
  id: string;
  name: string;
  description: string | null;
  status: ProfileStatus;
  plan_tiers: PlanTier[];
  is_platform_default: boolean;
  slots: {
    chat: SlotAssignment | null;
    intent: SlotAssignment | null;
    vision: SlotAssignment | null;
    agent: SlotAssignment | null;
  };
  tenants_count: number;
  created_at: string;
  updated_at: string;
}

export interface AvailableModel {
  library_entry_id: string;
  model_name: string;
  display_name: string;
  provider: string;
  health_status: "healthy" | "degraded" | "unknown";
  test_passed_at: string | null;
  is_deprecated: boolean;
}

export interface ProfileTenant {
  tenant_id: string;
  tenant_name: string;
  plan_tier: PlanTier;
}

export interface SlotTestResult {
  slot: ProfileSlot;
  model_name: string;
  provider: string;
  latency_ms: number | null;
  tokens_used: number | null;
  response_snippet: string | null;
  error: string | null;
}

export interface TestProfileResult {
  profile_id: string;
  results: SlotTestResult[];
}

export interface CreateProfilePayload {
  name: string;
  description?: string;
  plan_tiers: PlanTier[];
  slots?: {
    chat?: string;
    intent?: string;
    vision?: string;
    agent?: string;
  };
}

export interface UpdateProfilePayload {
  name?: string;
  description?: string;
  plan_tiers?: PlanTier[];
  status?: ProfileStatus;
}

export interface AssignSlotPayload {
  library_entry_id: string;
}

// ---------------------------------------------------------------------------
// Query Keys
// ---------------------------------------------------------------------------

const PROFILES_KEY = ["platform-llm-profiles-v2"] as const;

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** GET /api/v1/platform/llm-profiles */
export function useProfileList() {
  return useQuery({
    queryKey: PROFILES_KEY,
    queryFn: () => apiGet<PlatformProfile[]>("/api/v1/platform/llm-profiles"),
    refetchInterval: 30_000,
  });
}

/** GET /api/v1/platform/llm-profiles/:id */
export function useProfileDetail(id: string | null) {
  return useQuery({
    queryKey: ["platform-llm-profile-detail", id],
    queryFn: () =>
      apiGet<PlatformProfile>(`/api/v1/platform/llm-profiles/${id}`),
    enabled: !!id,
  });
}

/** POST /api/v1/platform/llm-profiles */
export function useCreateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateProfilePayload) =>
      apiPost<PlatformProfile>("/api/v1/platform/llm-profiles", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROFILES_KEY });
    },
  });
}

/** PATCH /api/v1/platform/llm-profiles/:id */
export function useUpdateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: UpdateProfilePayload;
    }) =>
      apiPatch<PlatformProfile>(`/api/v1/platform/llm-profiles/${id}`, payload),
    onSuccess: (_data, { id }) => {
      queryClient.invalidateQueries({ queryKey: PROFILES_KEY });
      queryClient.invalidateQueries({
        queryKey: ["platform-llm-profile-detail", id],
      });
    },
  });
}

/** PATCH /api/v1/platform/llm-profiles/:id/slots/:slot */
export function useAssignSlot() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      profileId,
      slot,
      payload,
    }: {
      profileId: string;
      slot: ProfileSlot;
      payload: AssignSlotPayload;
    }) =>
      apiPatch<PlatformProfile>(
        `/api/v1/platform/llm-profiles/${profileId}/slots/${slot}`,
        payload,
      ),
    onSuccess: (_data, { profileId }) => {
      queryClient.invalidateQueries({ queryKey: PROFILES_KEY });
      queryClient.invalidateQueries({
        queryKey: ["platform-llm-profile-detail", profileId],
      });
    },
  });
}

/** POST /api/v1/platform/llm-profiles/:id/set-default */
export function useSetDefault() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (profileId: string) =>
      apiPost<PlatformProfile>(
        `/api/v1/platform/llm-profiles/${profileId}/set-default`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROFILES_KEY });
    },
  });
}

/** POST /api/v1/platform/llm-profiles/:id/test */
export function useTestProfile() {
  return useMutation({
    mutationFn: (profileId: string) =>
      apiPost<TestProfileResult>(
        `/api/v1/platform/llm-profiles/${profileId}/test`,
        {},
      ),
  });
}

/** GET /api/v1/platform/llm-profiles/available-models/:slot — fetched on demand */
export function useAvailableModels(slot: ProfileSlot | null) {
  return useQuery({
    queryKey: ["platform-llm-available-models", slot],
    queryFn: () =>
      apiGet<AvailableModel[]>(
        `/api/v1/platform/llm-profiles/available-models/${slot}`,
      ),
    enabled: !!slot,
    staleTime: 60_000,
  });
}

/** GET /api/v1/platform/llm-profiles/:id/tenants */
export function useProfileTenants(profileId: string | null) {
  return useQuery({
    queryKey: ["platform-llm-profile-tenants", profileId],
    queryFn: () =>
      apiGet<ProfileTenant[]>(
        `/api/v1/platform/llm-profiles/${profileId}/tenants`,
      ),
    enabled: !!profileId,
  });
}

// ---------------------------------------------------------------------------
// History and rollback
// ---------------------------------------------------------------------------

export interface ProfileHistoryEntry {
  id: string;
  action: string;
  actor_id: string | null;
  created_at: string | null;
  diff: {
    before?: Record<string, unknown>;
    after?: Record<string, unknown>;
    rolled_back_from_history_id?: string;
  };
}

/** GET /api/v1/platform/llm-profiles/:id/history */
export function useProfileHistory(profileId: string | null) {
  return useQuery({
    queryKey: ["platform-llm-profile-history", profileId],
    queryFn: () =>
      apiGet<ProfileHistoryEntry[]>(
        `/api/v1/platform/llm-profiles/${profileId}/history`,
      ),
    enabled: !!profileId,
    staleTime: 10_000,
  });
}

/** POST /api/v1/platform/llm-profiles/:id/rollback/:historyId */
export function useRollbackProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      profileId,
      historyId,
    }: {
      profileId: string;
      historyId: string;
    }) =>
      apiPost<PlatformProfile>(
        `/api/v1/platform/llm-profiles/${profileId}/rollback/${historyId}`,
        {},
      ),
    onSuccess: (_data, { profileId }) => {
      queryClient.invalidateQueries({ queryKey: PROFILES_KEY });
      queryClient.invalidateQueries({
        queryKey: ["platform-llm-profile-detail", profileId],
      });
      queryClient.invalidateQueries({
        queryKey: ["platform-llm-profile-history", profileId],
      });
    },
  });
}
