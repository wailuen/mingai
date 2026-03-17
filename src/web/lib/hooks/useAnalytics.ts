"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch } from "@/lib/api";

export interface SatisfactionTrendPoint {
  date: string;
  satisfaction_pct: number;
  total: number;
}

export interface AnalyticsSatisfactionResponse {
  trend: SatisfactionTrendPoint[];
  satisfaction_7d: number;
  not_enough_data?: boolean;
  total_ratings?: number;
}

export interface LowConfidenceItem {
  message_id: string;
  query_text: string;
  created_at: string;
  retrieval_confidence: number;
}

export interface LowConfidenceResponse {
  items: LowConfidenceItem[];
}

export interface AgentBreakdownEntry {
  agent_id: string;
  agent_name: string;
  satisfaction_pct: number;
  total_ratings: number;
  trend_7d: number[];
}

export interface AnalyticsSatisfactionFullResponse extends AnalyticsSatisfactionResponse {
  agent_breakdown?: AgentBreakdownEntry[];
}

export interface SyncStatusEntry {
  source_id: string;
  source_name: string;
  source_type: string;
  last_synced_at: string | null;
  freshness_days: number;
  status: string;
}

export interface SyncStatusResponse {
  items: SyncStatusEntry[];
}

export interface Issue {
  id: string;
  severity: "P0" | "P1" | "P2" | "P3" | "P4";
  title: string;
  description: string | null;
  status: "open" | "in_progress" | "resolved" | "escalated";
  created_at: string;
  updated_at: string;
  reporter_name: string | null;
}

export interface IssuesResponse {
  items: Issue[];
  total: number;
}

const ANALYTICS_KEY = "analytics";
const ISSUES_KEY = "admin-issues";

export function useSatisfactionData() {
  return useQuery({
    queryKey: [ANALYTICS_KEY, "satisfaction"],
    queryFn: () =>
      apiGet<AnalyticsSatisfactionResponse>(
        "/api/v1/admin/analytics/satisfaction",
      ),
    staleTime: 60 * 1000, // 1 minute
  });
}

export function useLowConfidenceItems(limit?: number) {
  const params = new URLSearchParams();
  if (limit !== undefined) {
    params.set("limit", String(limit));
  }
  const qs = params.toString();
  const path = `/api/v1/admin/analytics/low-confidence${qs ? `?${qs}` : ""}`;

  return useQuery({
    queryKey: [ANALYTICS_KEY, "low-confidence", limit],
    queryFn: () => apiGet<LowConfidenceResponse>(path),
    staleTime: 60 * 1000,
  });
}

export function useSatisfactionFull() {
  return useQuery({
    queryKey: [ANALYTICS_KEY, "satisfaction-full"],
    queryFn: () =>
      apiGet<AnalyticsSatisfactionFullResponse>(
        "/api/v1/admin/analytics/satisfaction",
      ),
    staleTime: 60 * 1000,
  });
}

export function useSyncStatus() {
  return useQuery({
    queryKey: [ANALYTICS_KEY, "sync-status"],
    queryFn: () => apiGet<SyncStatusResponse>("/api/v1/admin/sync/status"),
    staleTime: 60 * 1000,
  });
}

export function useIssues(filters?: { severity?: string; status?: string }) {
  const params = new URLSearchParams();
  if (filters?.severity) params.set("severity", filters.severity);
  if (filters?.status) params.set("status", filters.status);
  const qs = params.toString();
  const path = `/api/v1/admin/issues${qs ? `?${qs}` : ""}`;

  return useQuery({
    queryKey: [ISSUES_KEY, filters?.severity, filters?.status],
    queryFn: () => apiGet<IssuesResponse>(path),
    staleTime: 30 * 1000,
  });
}

export function useUpdateIssue() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: Record<string, unknown>;
    }) => apiPatch<Issue>(`/api/v1/admin/issues/${encodeURIComponent(id)}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ISSUES_KEY] });
    },
  });
}
