"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";
import { getStoredToken } from "@/lib/auth";

// ---------------------------------------------------------------------------
// Types — Platform Admin skills management
// ---------------------------------------------------------------------------

export interface PlatformSkillAdmin {
  id: string;
  name: string;
  description?: string;
  category?: string;
  execution_pattern: "prompt" | "tool_composing" | "sequential_pipeline";
  status: "draft" | "published" | "deprecated";
  version: number;
  version_label?: string;
  mandatory: boolean;
  plan_required?: "starter" | "professional" | "enterprise" | null;
  adoption_count?: number;
  scope: "platform";
  created_at?: string;
  updated_at?: string;
}

export interface PlatformSkillListResponse {
  items: PlatformSkillAdmin[];
  total: number;
}

export interface CreatePlatformSkillPayload {
  name: string;
  description?: string;
  category?: string;
  execution_pattern: "prompt" | "tool_composing" | "sequential_pipeline";
  prompt_template?: string;
  plan_required?: "starter" | "professional" | "enterprise" | null;
  mandatory?: boolean;
}

export interface UpdatePlatformSkillPayload {
  name?: string;
  description?: string;
  category?: string;
  execution_pattern?: "prompt" | "tool_composing" | "sequential_pipeline";
  prompt_template?: string;
  plan_required?: "starter" | "professional" | "enterprise" | null;
}

export interface PublishPlatformSkillPayload {
  version_label?: string;
  changelog?: string;
}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

const PLATFORM_SKILLS_KEY = ["platform-skills-admin"] as const;
const PLATFORM_SKILL_KEY = (id: string) =>
  ["platform-skill-admin", id] as const;

// ---------------------------------------------------------------------------
// Helper — try /api/v1/platform/skills, fall back to /api/v1/skills
// ---------------------------------------------------------------------------

async function fetchPlatformSkills(
  statusFilter?: string,
): Promise<PlatformSkillListResponse> {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const params = new URLSearchParams();
  if (statusFilter && statusFilter !== "all") {
    params.set("status", statusFilter);
  }
  const qs = params.toString() ? `?${params.toString()}` : "";

  const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

  // Attempt PA-specific endpoint first
  const primaryRes = await fetch(`${baseUrl}/api/v1/platform/skills${qs}`, {
    headers,
  });

  if (primaryRes.ok) {
    const data = await primaryRes.json();
    // Normalise: backend may return array or {items, total}
    if (Array.isArray(data)) {
      return { items: data as PlatformSkillAdmin[], total: data.length };
    }
    return data as PlatformSkillListResponse;
  }

  if (primaryRes.status !== 404) {
    const body = await primaryRes.json().catch(() => ({}));
    throw new Error(
      (body as { detail?: string }).detail ?? `HTTP ${primaryRes.status}`,
    );
  }

  // 404 — fall back to tenant-readable skills endpoint
  const fallbackRes = await fetch(`${baseUrl}/api/v1/skills${qs}`, { headers });

  if (!fallbackRes.ok) {
    const body = await fallbackRes.json().catch(() => ({}));
    throw new Error(
      (body as { detail?: string }).detail ?? `HTTP ${fallbackRes.status}`,
    );
  }

  const fallbackData = await fallbackRes.json();
  if (Array.isArray(fallbackData)) {
    return {
      items: fallbackData as PlatformSkillAdmin[],
      total: fallbackData.length,
    };
  }
  return fallbackData as PlatformSkillListResponse;
}

// ---------------------------------------------------------------------------
// Hooks — queries
// ---------------------------------------------------------------------------

/**
 * List all platform skills.
 * Tries GET /api/v1/platform/skills first; falls back to GET /api/v1/skills on 404.
 */
export function usePlatformSkillsAdmin(statusFilter?: string) {
  return useQuery({
    queryKey: [...PLATFORM_SKILLS_KEY, statusFilter ?? "all"],
    queryFn: () => fetchPlatformSkills(statusFilter),
  });
}

/** GET /api/v1/platform/skills/:id */
export function usePlatformSkillAdmin(id: string | null) {
  return useQuery({
    queryKey: PLATFORM_SKILL_KEY(id ?? ""),
    queryFn: () => apiGet<PlatformSkillAdmin>(`/api/v1/platform/skills/${id}`),
    enabled: !!id,
  });
}

// ---------------------------------------------------------------------------
// Hooks — mutations
// ---------------------------------------------------------------------------

/** POST /api/v1/platform/skills */
export function useCreatePlatformSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreatePlatformSkillPayload) =>
      apiPost<PlatformSkillAdmin>("/api/v1/platform/skills", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PLATFORM_SKILLS_KEY });
    },
  });
}

/** PUT /api/v1/platform/skills/:id */
export function useUpdatePlatformSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      payload,
    }: {
      id: string;
      payload: UpdatePlatformSkillPayload;
    }) => {
      const token = getStoredToken();
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/platform/skills/${id}`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(payload),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ?? `HTTP ${res.status}`,
        );
      }
      return (await res.json()) as PlatformSkillAdmin;
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: PLATFORM_SKILLS_KEY });
      queryClient.invalidateQueries({
        queryKey: PLATFORM_SKILL_KEY(variables.id),
      });
    },
  });
}

/** POST /api/v1/platform/skills/:id/publish */
export function usePublishPlatformSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload?: PublishPlatformSkillPayload;
    }) =>
      apiPost<PlatformSkillAdmin>(
        `/api/v1/platform/skills/${id}/publish`,
        payload ?? {},
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: PLATFORM_SKILLS_KEY });
      queryClient.invalidateQueries({
        queryKey: PLATFORM_SKILL_KEY(variables.id),
      });
    },
  });
}

/** POST /api/v1/platform/skills/:id/deprecate */
export function useDeprecatePlatformSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiPost<PlatformSkillAdmin>(
        `/api/v1/platform/skills/${id}/deprecate`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PLATFORM_SKILLS_KEY });
    },
  });
}

/** POST /api/v1/platform/skills/:id/mandate — mark mandatory */
export function useMandatePlatformSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiPost<PlatformSkillAdmin>(`/api/v1/platform/skills/${id}/mandate`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PLATFORM_SKILLS_KEY });
    },
  });
}

/** DELETE /api/v1/platform/skills/:id/mandate — remove mandatory flag */
export function useRemoveMandatePlatformSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiDelete<PlatformSkillAdmin>(`/api/v1/platform/skills/${id}/mandate`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PLATFORM_SKILLS_KEY });
    },
  });
}

/** DELETE /api/v1/platform/skills/:id — delete draft skill */
export function useDeletePlatformSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiDelete<void>(`/api/v1/platform/skills/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PLATFORM_SKILLS_KEY });
    },
  });
}
