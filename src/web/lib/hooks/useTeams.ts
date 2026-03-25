"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";

export interface Team {
  id: string;
  name: string;
  description: string | null;
  member_count: number;
  created_at: string;
  source?: "manual" | "auth0_sync";
}

export interface TeamDetail {
  id: string;
  name: string;
  description: string | null;
  member_count: number;
  created_at: string;
}

export interface TeamMemory {
  team_id: string;
  topics: string[];
  recent_queries: string[];
}

export interface CreateTeamPayload {
  name: string;
  description?: string;
}

export interface UpdateTeamPayload {
  name?: string;
  description?: string;
}

export interface AddMemberPayload {
  user_id: string;
}

export interface AddMemberResult {
  team_id: string;
  user_id: string;
}

export interface BulkAddMembersResult {
  added: number;
  team_id: string;
}

export interface MemoryConfig {
  enabled: boolean;
  ttl_days: number;
  entry_count: number;
  size_bytes: number;
}

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  actor: string;
  source: "manual" | "auth0_sync";
  action: "added" | "removed";
  member_name: string;
}

export interface AuditLogResponse {
  items: AuditLogEntry[];
  total: number;
  page: number;
  limit: number;
}

export interface WorkspaceUser {
  id: string;
  name: string;
  email: string;
}

const TEAMS_KEY = "teams";

export function useTeams() {
  return useQuery({
    queryKey: [TEAMS_KEY],
    queryFn: () => apiGet<Team[]>("/api/v1/teams"),
  });
}

export function useTeam(id: string | null) {
  return useQuery({
    queryKey: [TEAMS_KEY, id],
    queryFn: () => apiGet<TeamDetail>(`/api/v1/teams/${id}`),
    enabled: id !== null,
  });
}

export function useTeamMemory(id: string | null) {
  return useQuery({
    queryKey: [TEAMS_KEY, id, "memory"],
    queryFn: () => apiGet<TeamMemory>(`/api/v1/teams/${id}/memory`),
    enabled: id !== null,
  });
}

export function useCreateTeam() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateTeamPayload) =>
      apiPost<Team>("/api/v1/teams", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TEAMS_KEY] });
    },
  });
}

export function useUpdateTeam() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateTeamPayload }) =>
      apiPatch<TeamDetail>(`/api/v1/teams/${id}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TEAMS_KEY] });
    },
  });
}

export function useDeleteTeam() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/v1/teams/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TEAMS_KEY] });
    },
  });
}

export function useAddMember() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ teamId, userId }: { teamId: string; userId: string }) =>
      apiPost<AddMemberResult>(`/api/v1/teams/${teamId}/members`, {
        user_id: userId,
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: [TEAMS_KEY, variables.teamId],
      });
      queryClient.invalidateQueries({ queryKey: [TEAMS_KEY] });
    },
  });
}

export function useRemoveMember() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ teamId, userId }: { teamId: string; userId: string }) =>
      apiDelete(`/api/v1/teams/${teamId}/members/${userId}`),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: [TEAMS_KEY, variables.teamId],
      });
      queryClient.invalidateQueries({ queryKey: [TEAMS_KEY] });
    },
  });
}

export function useTeamMemoryConfig(teamId: string | null) {
  return useQuery({
    queryKey: [TEAMS_KEY, teamId, "memory-config"],
    queryFn: () =>
      apiGet<MemoryConfig>(`/api/v1/teams/${teamId}/memory-config`),
    enabled: teamId !== null,
  });
}

export function useUpdateMemoryConfig() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      teamId,
      payload,
    }: {
      teamId: string;
      payload: { enabled: boolean; ttl_days: number };
    }) =>
      apiPatch<MemoryConfig>(
        `/api/v1/teams/${teamId}/memory-config`,
        payload,
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: [TEAMS_KEY, variables.teamId, "memory-config"],
      });
    },
  });
}

interface RawAuditLogEntry {
  id: string;
  created_at: string; // backend sends created_at, not timestamp
  actor_email?: string | null; // backend sends actor_email, not actor
  source: "manual" | "auth0_sync";
  action: "added" | "removed";
  member_name?: string | null;
  member_email?: string | null;
}

interface RawAuditLogResponse {
  items: RawAuditLogEntry[];
  total: number;
  page: number;
  page_size: number; // backend sends page_size, not limit
}

export function useTeamAuditLog(
  teamId: string | null,
  page: number = 1,
  limit: number = 20,
) {
  return useQuery({
    queryKey: [TEAMS_KEY, teamId, "audit-log", page, limit],
    queryFn: async () => {
      const raw = await apiGet<RawAuditLogResponse>(
        `/api/v1/teams/${teamId}/audit-log?page=${page}&limit=${limit}`,
      );
      return {
        items: raw.items.map((e) => ({
          id: e.id,
          timestamp: e.created_at,
          actor: e.actor_email ?? "System",
          source: e.source,
          action: e.action,
          member_name: e.member_name ?? e.member_email ?? "Unknown",
        })) satisfies AuditLogEntry[],
        total: raw.total,
        page: raw.page,
        limit: raw.page_size,
      } satisfies AuditLogResponse;
    },
    enabled: teamId !== null,
  });
}

export function useWorkspaceUsers(search?: string) {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  const qs = params.toString();
  const path = `/api/v1/admin/users${qs ? `?${qs}` : ""}`;

  return useQuery({
    queryKey: ["workspace-users", search],
    queryFn: () => apiGet<{ items: WorkspaceUser[] }>(path),
    staleTime: 30 * 1000,
  });
}

export function useBulkAddMembers() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ teamId, userIds }: { teamId: string; userIds: string[] }) =>
      apiPost<BulkAddMembersResult>(`/api/v1/teams/${teamId}/members/bulk`, {
        user_ids: userIds,
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: [TEAMS_KEY, variables.teamId],
      });
      queryClient.invalidateQueries({ queryKey: [TEAMS_KEY] });
    },
  });
}
