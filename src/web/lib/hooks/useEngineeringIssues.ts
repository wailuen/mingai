"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost } from "@/lib/api";

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
      apiGet<TenantIssue>(`/api/v1/admin/issues/${encodeURIComponent(id!)}`),
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
      queryClient.invalidateQueries({ queryKey: ["platform-issue-queue"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Platform-level queue types
// ---------------------------------------------------------------------------

export type QueueFilter =
  | "incoming"
  | "triaged"
  | "in_progress"
  | "sla_at_risk"
  | "resolved";

export interface PlatformIssue extends TenantIssue {
  tenant_name: string;
  assigned_to: string | null;
  sla_at_risk: boolean;
}

export interface PlatformIssueQueueResponse {
  items: PlatformIssue[];
  counts: Record<QueueFilter, number>;
}

// ---------------------------------------------------------------------------
// usePlatformIssueQueue — GET /api/v1/platform/issues/queue
// ---------------------------------------------------------------------------

function buildQueueParams(filter: QueueFilter): string {
  return `?filter=${filter}`;
}

export function usePlatformIssueQueue(filter: QueueFilter) {
  return useQuery({
    queryKey: ["platform-issue-queue", filter],
    queryFn: () =>
      apiGet<PlatformIssueQueueResponse>(
        `/api/v1/platform/issues/queue${buildQueueParams(filter)}`,
      ),
  });
}

// ---------------------------------------------------------------------------
// useAcceptIssue — POST /api/v1/platform/issues/{id}/accept
// ---------------------------------------------------------------------------

export function useAcceptIssue() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id }: { id: string }) =>
      apiPost<PlatformIssue>(
        `/api/v1/platform/issues/${encodeURIComponent(id)}/accept`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-issue-queue"] });
    },
  });
}

// ---------------------------------------------------------------------------
// useOverrideSeverity — PATCH /api/v1/platform/issues/{id}/severity
// ---------------------------------------------------------------------------

export function useOverrideSeverity() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      severity,
      reason,
    }: {
      id: string;
      severity: TenantIssueSeverity;
      reason: string;
    }) =>
      apiPatch<PlatformIssue>(
        `/api/v1/platform/issues/${encodeURIComponent(id)}/severity`,
        { severity, reason },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-issue-queue"] });
    },
  });
}

// ---------------------------------------------------------------------------
// useWontFix — POST /api/v1/platform/issues/{id}/wont-fix
// ---------------------------------------------------------------------------

export function useWontFix() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      apiPost<PlatformIssue>(
        `/api/v1/platform/issues/${encodeURIComponent(id)}/wont-fix`,
        { reason },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-issue-queue"] });
    },
  });
}

// ---------------------------------------------------------------------------
// useAssignIssue — PATCH /api/v1/platform/issues/{id}/assign
// ---------------------------------------------------------------------------

export function useAssignIssue() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      assignee_email,
    }: {
      id: string;
      assignee_email: string;
    }) =>
      apiPatch<PlatformIssue>(
        `/api/v1/platform/issues/${encodeURIComponent(id)}/assign`,
        { assignee_email },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-issue-queue"] });
    },
  });
}

// ---------------------------------------------------------------------------
// useRequestInfo — POST /api/v1/platform/issues/{id}/request-info
// ---------------------------------------------------------------------------

export function useRequestInfo() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, message }: { id: string; message: string }) =>
      apiPost<PlatformIssue>(
        `/api/v1/platform/issues/${encodeURIComponent(id)}/request-info`,
        { message },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-issue-queue"] });
    },
  });
}
