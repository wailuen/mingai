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

// Raw shape returned by the backend
interface RawPlatformIssue {
  id: string;
  severity: IssueSeverity;
  tenant?: { id: string; name: string };
  tenant_name?: string;
  reporter?: { name: string };
  title: string;
  type?: string;
  status: IssueStatus;
  ai_classification?: string;
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

function mapRawIssue(raw: RawPlatformIssue): PlatformIssue {
  return {
    id: raw.id,
    severity: raw.severity,
    tenant_name: raw.tenant?.name ?? raw.tenant_name ?? "",
    title: raw.title,
    status: raw.status,
    ai_classification: raw.ai_classification ?? raw.type ?? "",
    created_at: raw.created_at,
  };
}

export function usePlatformIssues(filters?: IssueFilters) {
  return useQuery({
    queryKey: ["platform-issues", filters],
    queryFn: async () => {
      const res = await apiGet<
        { items: RawPlatformIssue[] } | RawPlatformIssue[]
      >(`/api/v1/platform/issues${buildFilterParams(filters)}`);
      const items = Array.isArray(res) ? res : res.items ?? [];
      return items.map(mapRawIssue);
    },
  });
}

// ---------------------------------------------------------------------------
// useIssueDetail
// ---------------------------------------------------------------------------

export function useIssueDetail(id: string | null) {
  return useQuery({
    queryKey: ["platform-issue-detail", id],
    queryFn: async () => {
      const raw = await apiGet<
        RawPlatformIssue & {
          description?: string;
          issue_type?: string;
          reporter_id?: string;
        }
      >(`/api/v1/platform/issues/${id}`);
      return {
        id: raw.id,
        severity: raw.severity ?? ("P3" as IssueSeverity),
        tenant_name: raw.tenant?.name ?? raw.tenant_name ?? "",
        title: raw.title ?? raw.issue_type ?? "",
        status: raw.status,
        ai_classification: raw.ai_classification ?? raw.type ?? "",
        created_at: raw.created_at,
        description: raw.description ?? "",
        session_data: "",
        browser_info: "",
        ai_assessment: "",
        reporter_email: raw.reporter?.name ?? "",
      } as IssueDetail;
    },
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
