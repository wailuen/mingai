"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type GoogleDriveConnectionStatus =
  | "active"
  | "pending"
  | "error"
  | "disabled";

export interface GoogleDriveConnection {
  id: string;
  name: string;
  status: GoogleDriveConnectionStatus;
  folder_id: string;
  last_sync_at: string | null;
  last_sync_status: string | null;
}

export interface ConnectGoogleDrivePayload {
  name: string;
  folder_id: string;
  service_account_email: string;
  credential_ref: string;
}

export interface SyncHistoryEntry {
  id: string;
  started_at: string;
  completed_at: string | null;
  status: "success" | "error" | "in_progress";
  documents_synced: number;
  error_message: string | null;
}

// ---------------------------------------------------------------------------
// useGoogleDriveConnections — GET /api/v1/documents/google-drive
// ---------------------------------------------------------------------------

const GD_KEY = ["google-drive-connections"] as const;

export function useGoogleDriveConnections() {
  return useQuery({
    queryKey: GD_KEY,
    queryFn: () =>
      apiGet<GoogleDriveConnection[]>("/api/v1/documents/google-drive"),
  });
}

// ---------------------------------------------------------------------------
// useConnectGoogleDrive — POST /api/v1/documents/google-drive/connect
// ---------------------------------------------------------------------------

export function useConnectGoogleDrive() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: ConnectGoogleDrivePayload) =>
      apiPost<GoogleDriveConnection>(
        "/api/v1/documents/google-drive/connect",
        payload,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: GD_KEY });
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
    },
  });
}

// ---------------------------------------------------------------------------
// useTriggerGoogleDriveSync — POST /api/v1/documents/google-drive/{id}/sync
// ---------------------------------------------------------------------------

export function useTriggerGoogleDriveSync() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiPost<{ success: boolean }>(
        `/api/v1/documents/google-drive/${encodeURIComponent(id)}/sync`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: GD_KEY });
    },
  });
}

// ---------------------------------------------------------------------------
// useGoogleDriveSyncHistory — GET /api/v1/documents/google-drive/{id}/sync
// ---------------------------------------------------------------------------

export function useGoogleDriveSyncHistory(id: string | null) {
  return useQuery({
    queryKey: ["google-drive-sync-history", id],
    queryFn: () =>
      apiGet<SyncHistoryEntry[]>(
        `/api/v1/documents/google-drive/${encodeURIComponent(id!)}/sync`,
      ),
    enabled: !!id,
  });
}
