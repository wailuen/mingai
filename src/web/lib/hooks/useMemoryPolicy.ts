"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch } from "@/lib/api";

export interface MemoryPolicy {
  profile_learning_enabled: boolean;
  working_memory_enabled: boolean;
  working_memory_ttl_days: number;
  memory_notes_enabled: boolean;
  memory_notes_auto_extract: boolean;
}

interface WorkspaceSettings {
  name: string;
  logo_url: string | null;
  timezone: string;
  locale: string;
  auth_mode: string;
  notification_preferences: Record<string, unknown>;
  memory_policy?: MemoryPolicy;
}

const MEMORY_POLICY_KEY = "memory-policy";

const DEFAULT_MEMORY_POLICY: MemoryPolicy = {
  profile_learning_enabled: true,
  working_memory_enabled: true,
  working_memory_ttl_days: 7,
  memory_notes_enabled: true,
  memory_notes_auto_extract: true,
};

/**
 * FE-052: Fetch memory policy from workspace settings.
 * GET /api/v1/admin/workspace -> memory_policy field
 */
export function useMemoryPolicy() {
  return useQuery({
    queryKey: [MEMORY_POLICY_KEY],
    queryFn: async () => {
      const workspace = await apiGet<WorkspaceSettings>(
        "/api/v1/admin/workspace",
      );
      return workspace.memory_policy ?? DEFAULT_MEMORY_POLICY;
    },
  });
}

/**
 * FE-052: Update memory policy via workspace settings.
 * PATCH /api/v1/admin/workspace with notification_preferences containing memory_policy
 *
 * Since memory_policy is stored within workspace settings, we use the
 * notification_preferences field as the carrier for JSON policy data,
 * or the workspace PATCH endpoint if the backend supports a memory_policy field.
 */
export function useUpdateMemoryPolicy() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (policy: Partial<MemoryPolicy>) =>
      apiPatch<WorkspaceSettings>("/api/v1/admin/workspace", {
        notification_preferences: {
          memory_policy: policy,
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [MEMORY_POLICY_KEY] });
    },
  });
}
