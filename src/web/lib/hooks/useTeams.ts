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
