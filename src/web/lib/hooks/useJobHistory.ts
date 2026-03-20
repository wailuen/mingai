"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface JobRunRow {
  id: string;
  job_name: string;
  instance_id: string | null;
  tenant_id: string | null;
  status: "running" | "completed" | "failed" | "abandoned" | "skipped";
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  records_processed: number | null;
  error_message: string | null;
}

export interface JobHistoryResponse {
  items: JobRunRow[];
  total_count: number;
  limit: number;
  offset: number;
}

export interface JobHistoryFilters {
  job_name?: string;
  status?: string;
  from_date?: string;
  to_date?: string;
}

// ---------------------------------------------------------------------------
// useJobHistory
// ---------------------------------------------------------------------------

export function useJobHistory(
  offset: number,
  limit: number,
  filters?: JobHistoryFilters,
) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));

  if (filters?.job_name) params.set("job_name", filters.job_name);
  if (filters?.status) params.set("status", filters.status);
  if (filters?.from_date) params.set("from_date", filters.from_date);
  if (filters?.to_date) params.set("to_date", filters.to_date);

  const qs = params.toString();

  return useQuery({
    queryKey: ["platform-job-history", offset, limit, filters],
    queryFn: () =>
      apiGet<JobHistoryResponse>(`/api/v1/platform/jobs/history?${qs}`),
    staleTime: 30 * 1000,
    refetchInterval: (query) => {
      const items = query.state.data?.items;
      return items?.some((r) => r.status === "running") ? 15_000 : 60_000;
    },
  });
}

// ---------------------------------------------------------------------------
// useTriggerJob
// ---------------------------------------------------------------------------

export interface TriggerJobResponse {
  job_name: string;
  run_id: string | null;
  status: "triggered";
}

export function useTriggerJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobName: string) =>
      apiPost<TriggerJobResponse>(
        `/api/v1/platform/jobs/${jobName}/trigger`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-job-history"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Known job names (for dropdown)
// ---------------------------------------------------------------------------

export const KNOWN_JOB_NAMES = [
  "health_score",
  "cost_summary",
  "azure_cost",
  "cost_alert",
  "miss_signals",
  "credential_expiry",
  "query_warming",
  "semantic_cache_cleanup",
  "provider_health",
  "tool_health",
  "url_health_monitor",
  "har_approval_timeout",
  "agent_health",
] as const;
