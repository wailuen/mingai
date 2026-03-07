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

const INTEGRATIONS_KEY = "sharepoint-integrations";
const SYNC_JOBS_KEY = "sync-jobs";

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
