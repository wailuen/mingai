"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiDelete } from "@/lib/api";

export interface PrivacySettings {
  profile_learning_enabled: boolean;
  working_memory_enabled: boolean;
}

export interface ExportedData {
  profile: Record<string, unknown>;
  notes: Array<Record<string, unknown>>;
  working_memory: Record<string, unknown>;
  privacy_settings: PrivacySettings;
}

const PRIVACY_KEY = "privacy-settings";

/**
 * FE-051: Fetch user privacy settings.
 * Composed from GET /api/v1/memory/export which includes privacy_settings.
 */
export function usePrivacySettings() {
  return useQuery({
    queryKey: [PRIVACY_KEY],
    queryFn: async () => {
      const data = await apiGet<ExportedData>("/api/v1/memory/export");
      return data.privacy_settings;
    },
    staleTime: 60 * 1000,
  });
}

/**
 * FE-051: Update a privacy setting.
 * PATCH /api/v1/memory/privacy
 */
export function useUpdatePrivacySetting() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: PrivacySettings) =>
      apiPatch<PrivacySettings>("/api/v1/memory/privacy", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PRIVACY_KEY] });
    },
  });
}

/**
 * FE-051: Export all user data (GDPR).
 * GET /api/v1/memory/export
 */
export function useExportData() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (): Promise<ExportedData> => {
      const data = await apiGet<ExportedData>("/api/v1/memory/export");
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PRIVACY_KEY] });
    },
  });
}

/**
 * FE-051: Clear all user data (GDPR erasure).
 * DELETE /api/v1/memory/profile
 */
export function useClearAllData() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => apiDelete("/api/v1/memory/profile"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PRIVACY_KEY] });
      queryClient.invalidateQueries({ queryKey: ["user-memory"] });
      queryClient.invalidateQueries({ queryKey: ["user-profile"] });
    },
  });
}
