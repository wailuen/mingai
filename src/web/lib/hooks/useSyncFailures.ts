"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

export interface SyncFailure {
  job_id: string;
  integration_id: string;
  integration_name: string;
  integration_type: "sharepoint" | "google_drive";
  error_message: string;
  failed_at: string;
  document_count_attempted: number;
  document_count_failed: number;
}

export interface SyncFailuresResponse {
  items: SyncFailure[];
  total: number;
}

export interface RetrySyncResponse {
  job_id: string;
  status: string;
}

const SYNC_FAILURES_KEY = "sync-failures";

export function useSyncFailures(sourceId?: string) {
  const params = sourceId ? `?source_id=${encodeURIComponent(sourceId)}` : "";

  return useQuery({
    queryKey: [SYNC_FAILURES_KEY, sourceId ?? "all"],
    queryFn: () =>
      apiGet<SyncFailuresResponse>(`/api/v1/admin/sync/failures${params}`),
    enabled: sourceId !== undefined ? !!sourceId : true,
  });
}

export function useRetrySyncJob() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (jobId: string) =>
      apiPost<RetrySyncResponse>(
        `/api/v1/admin/sync/jobs/${encodeURIComponent(jobId)}/retry`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [SYNC_FAILURES_KEY] });
    },
  });
}
