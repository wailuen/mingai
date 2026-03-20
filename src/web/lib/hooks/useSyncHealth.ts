"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

export interface Integration {
  id: string;
  name: string;
  status: string;
  site_url: string;
  library_name: string;
  last_sync_at: string | null;
  last_sync_status: string | null;
}

export interface IntegrationListResponse {
  items: Integration[];
}

export interface SyncJob {
  id: string;
  status: string;
  created_at: string;
}

export interface SyncJobsResponse {
  jobs: SyncJob[];
  total: number;
}

export interface TriggerSyncResponse {
  job_id: string;
  status: string;
}

export interface SyncStatusResponse {
  last_credentials_checked_at: string | null;
  credentials_expiry_days_remaining: number | null;
  last_query_warming_completed_at: string | null;
  last_health_score_calculated_at: string | null;
  glossary_terms_active: number;
}

const INTEGRATIONS_KEY = "sharepoint-integrations";
const SYNC_JOBS_KEY = "sync-jobs";
const SYNC_STATUS_KEY = "tenant-sync-status";

export function useSyncStatus() {
  return useQuery({
    queryKey: [SYNC_STATUS_KEY],
    queryFn: () => apiGet<SyncStatusResponse>("/api/v1/tenant/sync-status"),
    staleTime: 60_000,
  });
}

export function useIntegrations() {
  return useQuery({
    queryKey: [INTEGRATIONS_KEY],
    queryFn: () =>
      apiGet<IntegrationListResponse>("/api/v1/documents/sharepoint"),
  });
}

export function useSyncJobs(integrationId: string | null) {
  return useQuery({
    queryKey: [SYNC_JOBS_KEY, integrationId],
    queryFn: () =>
      apiGet<SyncJobsResponse>(
        `/api/v1/documents/sharepoint/${integrationId}/sync`,
      ),
    enabled: integrationId !== null,
  });
}

export function useTriggerSync() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (integrationId: string) =>
      apiPost<TriggerSyncResponse>(
        `/api/v1/documents/sharepoint/${integrationId}/sync`,
        {},
      ),
    onSuccess: (_data, integrationId) => {
      queryClient.invalidateQueries({ queryKey: [INTEGRATIONS_KEY] });
      queryClient.invalidateQueries({
        queryKey: [SYNC_JOBS_KEY, integrationId],
      });
    },
  });
}
