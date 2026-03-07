"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TenantIssueSeverity = "P0" | "P1" | "P2" | "P3" | "P4";
export type TenantIssueStatus =
  | "new"
  | "in_review"
  | "escalated"
  | "resolved"
  | "closed";

export interface TenantIssue {
  id: string;
  severity: TenantIssueSeverity;
  title: string;
  description: string;
  status: TenantIssueStatus;
  reporter_email: string;
  created_at: string;
  updated_at: string;
}

export interface TenantIssueFilters {
  severity?: TenantIssueSeverity[];
  status?: TenantIssueStatus[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildFilterParams(filters?: TenantIssueFilters): string {
  if (!filters) return "";
  const params = new URLSearchParams();
  if (filters.severity && filters.severity.length > 0) {
    params.set("severity", filters.severity.join(","));
  }
  if (filters.status && filters.status.length > 0) {
    params.set("status", filters.status.join(","));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

// ---------------------------------------------------------------------------
// useTenantIssues — GET /api/v1/admin/issues
// ---------------------------------------------------------------------------

export function useTenantIssues(filters?: TenantIssueFilters) {
  return useQuery({
    queryKey: ["tenant-issues", filters],
    queryFn: () =>
      apiGet<TenantIssue[]>(
        `/api/v1/admin/issues${buildFilterParams(filters)}`,
      ),
  });
}

// ---------------------------------------------------------------------------
// useIssueStatus — GET /api/v1/admin/issues/{id}
// ---------------------------------------------------------------------------

export function useIssueStatus(id: string | null) {
  return useQuery({
    queryKey: ["tenant-issue-detail", id],
    queryFn: () =>
      apiGet<TenantIssue>(`/api/v1/admin/issues/${encodeURIComponent(id)}`),
    enabled: !!id,
  });
}

// ---------------------------------------------------------------------------
// useUpdateIssueStatus — PATCH /api/v1/admin/issues/{id}
// ---------------------------------------------------------------------------

export function useUpdateIssueStatus() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: TenantIssueStatus }) =>
      apiPatch<TenantIssue>(`/api/v1/admin/issues/${encodeURIComponent(id)}`, {
        status,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tenant-issues"] });
    },
  });
}
