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
  | "closed"
  // PA-017 platform action statuses
  | "open"
  | "triaged"
  | "awaiting_info"
  | "routed"
  | "in_progress"
  | "assigned";

export interface TenantIssue {
  id: string;
  severity: TenantIssueSeverity;
  title: string;
  description: string;
  status: TenantIssueStatus;
  reporter?: { id: string; name: string } | null;
  reporter_email?: string; // legacy field — use reporter.name if available
  created_at: string;
  updated_at?: string;
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

interface TenantIssuesResponse {
  items: TenantIssue[];
  total: number;
  page: number;
  page_size: number;
}

export function useTenantIssues(filters?: TenantIssueFilters) {
  return useQuery({
    queryKey: ["tenant-issues", filters],
    queryFn: async () => {
      const res = await apiGet<TenantIssuesResponse>(
        `/api/v1/admin/issues${buildFilterParams(filters)}`,
      );
      return res.items;
    },
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

// Backend uses action-based state machine: action → new status
// escalate → escalated, resolve → resolved, close_duplicate → closed, request_info → awaiting_info
const STATUS_TO_ACTION: Partial<Record<TenantIssueStatus, string>> = {
  escalated: "escalate",
  resolved: "resolve",
  closed: "close_duplicate",
  awaiting_info: "request_info",
};

export function useUpdateIssueStatus() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: TenantIssueStatus }) => {
      const action = STATUS_TO_ACTION[status];
      if (!action) throw new Error(`No backend action for status: ${status}`);
      return apiPatch<TenantIssue>(`/api/v1/admin/issues/${encodeURIComponent(id)}`, {
        action,
      });
    },
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

// ---------------------------------------------------------------------------
// useRouteIssue — POST /api/v1/platform/issues/{id}/route
// ---------------------------------------------------------------------------

export function useRouteIssue() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      notify_tenant = true,
      note = "",
    }: {
      id: string;
      notify_tenant?: boolean;
      note?: string;
    }) =>
      apiPost<{ id: string; status: string }>(
        `/api/v1/platform/issues/${encodeURIComponent(id)}/route`,
        { notify_tenant, note },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-issue-queue"] });
    },
  });
}

// ---------------------------------------------------------------------------
// useCloseDuplicate — POST /api/v1/platform/issues/{id}/close-duplicate
// ---------------------------------------------------------------------------

export function useCloseDuplicate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      duplicate_of,
      note = "",
    }: {
      id: string;
      duplicate_of: string;
      note?: string;
    }) =>
      apiPost<{ id: string; status: string; duplicate_of: string }>(
        `/api/v1/platform/issues/${encodeURIComponent(id)}/close-duplicate`,
        { duplicate_of, note },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-issue-queue"] });
    },
  });
}
