"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types -- match backend schema exactly (KBAccessResponse)
// ---------------------------------------------------------------------------

export type KBVisibilityMode =
  | "workspace_wide"
  | "role_restricted"
  | "user_specific"
  | "agent_only";

export interface KBAccessControl {
  index_id: string;
  visibility_mode: KBVisibilityMode;
  allowed_roles: string[];
  allowed_user_ids: string[];
}

export interface UpdateKBAccessControlPayload {
  visibility_mode: KBVisibilityMode;
  allowed_roles?: string[];
  allowed_user_ids?: string[];
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

function kbAccessControlKey(kbId: string) {
  return ["kb-access-control", kbId] as const;
}

/** GET /api/v1/admin/knowledge-base/:kb_id/access */
export function useKBAccessControl(kbId: string | null) {
  return useQuery({
    queryKey: kbAccessControlKey(kbId ?? ""),
    queryFn: () =>
      apiGet<KBAccessControl>(`/api/v1/admin/knowledge-base/${kbId}/access`),
    enabled: !!kbId,
  });
}

/** PATCH /api/v1/admin/knowledge-base/:kb_id/access */
export function useUpdateKBAccessControl() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      kbId,
      payload,
    }: {
      kbId: string;
      payload: UpdateKBAccessControlPayload;
    }) =>
      apiPatch<KBAccessControl>(
        `/api/v1/admin/knowledge-base/${kbId}/access`,
        payload,
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: kbAccessControlKey(variables.kbId),
      });
    },
  });
}
