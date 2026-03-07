"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch } from "@/lib/api";

export interface UserProfile {
  id: string;
  email?: string;
  name?: string;
  role?: string;
  status?: string;
  tenant_id?: string;
  technical_level?: string;
  communication_style?: string;
  interests?: string[];
}

export interface UpdateProfilePayload {
  name?: string;
  preferences?: Record<string, unknown>;
}

const PROFILE_KEY = "user-profile";

/**
 * FE-051: Fetch the current user's profile.
 * GET /api/v1/users/me
 */
export function useUserProfile() {
  return useQuery({
    queryKey: [PROFILE_KEY],
    queryFn: () => apiGet<UserProfile>("/api/v1/users/me"),
  });
}

/**
 * FE-051: Update the current user's profile.
 * PATCH /api/v1/users/me
 */
export function useUpdateProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: UpdateProfilePayload) =>
      apiPatch<UserProfile>("/api/v1/users/me", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PROFILE_KEY] });
    },
  });
}
