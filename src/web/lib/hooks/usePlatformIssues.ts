"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type IssueSeverity = "P0" | "P1" | "P2" | "P3" | "P4";
export type IssueStatus = "open" | "in_progress" | "closed" | "waiting_info";

export interface PlatformIssue {
  id: string;
  severity: IssueSeverity;
  tenant_name: string;
  title: string;
  status: IssueStatus;
  ai_classification: string;
  created_at: string;
}

export interface IssueDetail extends PlatformIssue {
  description: string;
  session_data: string;
  browser_info: string;
  ai_assessment: string;
  reporter_email: string;
}

export interface IssueFilters {
  severity?: IssueSeverity[];
  status?: IssueStatus[];
}

// ---------------------------------------------------------------------------
// usePlatformIssues
// ---------------------------------------------------------------------------

function buildFilterParams(filters?: IssueFilters): string {
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

export function usePlatformIssues(filters?: IssueFilters) {
  return useQuery({
    queryKey: ["platform-issues", filters],
    queryFn: () =>
      apiGet<PlatformIssue[]>(
        `/api/v1/platform/issues${buildFilterParams(filters)}`,
      ),
  });
}

// ---------------------------------------------------------------------------
// useIssueDetail
// ---------------------------------------------------------------------------

export function useIssueDetail(id: string | null) {
  return useQuery({
    queryKey: ["platform-issue-detail", id],
    queryFn: () => apiGet<IssueDetail>(`/api/v1/platform/issues/${id}`),
    enabled: !!id,
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useRouteIssue() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiPost<{ success: boolean }>(`/api/v1/platform/issues/${id}/route`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-issues"] });
    },
  });
}

export function useCloseIssue() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      apiPost<{ success: boolean }>(`/api/v1/platform/issues/${id}/close`, {
        note,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-issues"] });
    },
  });
}

export function useRequestMoreInfo() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiPost<{ success: boolean }>(
        `/api/v1/platform/issues/${id}/request-info`,
        {},
      ),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({
        queryKey: ["platform-issue-detail", id],
      });
      queryClient.invalidateQueries({ queryKey: ["platform-issues"] });
    },
  });
}
