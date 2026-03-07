"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AlertSeverity = "critical" | "high" | "medium" | "low";

export interface PlatformAlert {
  id: string;
  severity: AlertSeverity;
  type: string;
  message: string;
  tenant_name: string;
  created_at: string;
  acknowledged_at: string | null;
  threshold: number;
  current_value: number;
}

export interface AlertConfigPayload {
  threshold: number;
}

// ---------------------------------------------------------------------------
// usePlatformAlerts
// ---------------------------------------------------------------------------

const ALERTS_KEY = ["platform-alerts"];

export function usePlatformAlerts() {
  return useQuery({
    queryKey: ALERTS_KEY,
    queryFn: () => apiGet<PlatformAlert[]>("/api/v1/platform/alerts"),
    staleTime: 15 * 1000,
  });
}

// ---------------------------------------------------------------------------
// useAcknowledgeAlert
// ---------------------------------------------------------------------------

export function useAcknowledgeAlert() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiPost<PlatformAlert>(`/api/v1/platform/alerts/${id}/acknowledge`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ALERTS_KEY });
    },
  });
}

// ---------------------------------------------------------------------------
// useConfigureAlert
// ---------------------------------------------------------------------------

export function useConfigureAlert() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, config }: { id: string; config: AlertConfigPayload }) =>
      apiPatch<PlatformAlert>(`/api/v1/platform/alerts/${id}/config`, config),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ALERTS_KEY });
    },
  });
}
