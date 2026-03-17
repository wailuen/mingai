"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types — aligned to actual backend response from /admin/access-requests
// ---------------------------------------------------------------------------

export type AccessRequestStatus = "pending" | "approved" | "denied";
export type AccessRequestResourceType = "kb" | "agent";

export interface AccessRequestItem {
  id: string;
  tenant_id: string;
  user_id: string;
  requester_email: string | null;
  requester_name: string | null;
  resource_id: string;
  resource_type: AccessRequestResourceType;
  justification: string;
  status: AccessRequestStatus;
  admin_note: string | null;
  created_at: string;
}

export interface AccessRequestsResponse {
  items: AccessRequestItem[];
  total: number;
}

export interface UpdateAccessRequestPayload {
  status: "approved" | "denied";
  note?: string;
}

export interface UpdateAccessRequestResult {
  id: string;
  status: string;
  admin_note: string | null;
}

// ---------------------------------------------------------------------------
// Query Keys
// ---------------------------------------------------------------------------

const ACCESS_REQUESTS_KEY = ["admin-access-requests"] as const;

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** GET /api/v1/admin/access-requests?status=... */
export function useAccessRequests(statusFilter?: AccessRequestStatus | "all") {
  const params = new URLSearchParams();
  if (statusFilter && statusFilter !== "all") {
    params.set("status", statusFilter);
  }

  return useQuery({
    queryKey: [...ACCESS_REQUESTS_KEY, statusFilter ?? "all"],
    queryFn: () =>
      apiGet<AccessRequestsResponse>(
        `/api/v1/admin/access-requests?${params.toString()}`,
      ),
  });
}

/** PATCH /api/v1/admin/access-requests/:id — approve or deny */
export function useUpdateAccessRequest() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: UpdateAccessRequestPayload;
    }) =>
      apiPatch<UpdateAccessRequestResult>(
        `/api/v1/admin/access-requests/${id}`,
        payload,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ACCESS_REQUESTS_KEY });
    },
  });
}
