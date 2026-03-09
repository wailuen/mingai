"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";
import { getStoredToken } from "@/lib/auth";

// API response shape (raw from backend)
interface GlossaryTermRaw {
  id: string;
  term: string;
  full_form?: string | null;
  aliases?: Array<{ term?: string; note?: string }> | null;
  created_at: string;
}

export interface GlossaryTerm {
  id: string;
  term: string;
  full_form?: string | null;
  definition: string;
  aliases?: Array<{ term?: string; note?: string }> | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

function transformTerm(raw: GlossaryTermRaw): GlossaryTerm {
  const definition = raw.aliases?.[0]?.note ?? "";
  return {
    ...raw,
    definition,
    is_active: true, // terms in the DB are active by default (no status column)
    updated_at: raw.created_at,
  };
}

export interface GlossaryListResponse {
  items: GlossaryTerm[];
  total: number;
  page: number;
  page_size: number;
}

export interface CreateTermPayload {
  term: string;
  full_form?: string;
  definition: string;
  aliases?: string[];
}

export interface UpdateTermPayload {
  term?: string;
  full_form?: string;
  definition?: string;
  aliases?: string[];
  is_active?: boolean;
}

export interface ImportResult {
  imported: number;
  skipped: number;
  errors: string[];
}

const GLOSSARY_KEY = "glossary";

export function useGlossaryTerms(
  page: number,
  search: string,
  statusFilter: string,
) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: "50",
  });
  if (search) params.set("search", search);
  if (statusFilter === "active") params.set("is_active", "true");
  if (statusFilter === "inactive") params.set("is_active", "false");

  return useQuery({
    queryKey: [GLOSSARY_KEY, page, search, statusFilter],
    queryFn: async () => {
      const raw = await apiGet<{ items: GlossaryTermRaw[]; total: number; page: number; page_size: number }>(
        `/api/v1/glossary/?${params.toString()}`,
      );
      return {
        ...raw,
        items: raw.items.map(transformTerm),
      } as GlossaryListResponse;
    },
  });
}

export function useCreateTerm() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateTermPayload) =>
      apiPost<GlossaryTerm>("/api/v1/glossary", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [GLOSSARY_KEY] });
    },
  });
}

export function useUpdateTerm() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateTermPayload }) =>
      apiPatch<GlossaryTerm>(`/api/v1/glossary/${id}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [GLOSSARY_KEY] });
    },
  });
}

export function useDeleteTerm() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/v1/glossary/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [GLOSSARY_KEY] });
    },
  });
}

export interface VersionEntry {
  version_id: string;
  created_at: string;
  editor_email: string;
  change_summary: string;
}

export function useVersionHistory(termId: string | null) {
  return useQuery({
    queryKey: [GLOSSARY_KEY, "history", termId],
    queryFn: () =>
      apiGet<VersionEntry[]>(`/api/v1/glossary/${termId}/history`),
    enabled: !!termId,
  });
}

export function useRollbackTerm() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      termId,
      versionId,
    }: {
      termId: string;
      versionId: string;
    }) =>
      apiPost<GlossaryTerm>(`/api/v1/glossary/${termId}/rollback`, {
        version_id: versionId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [GLOSSARY_KEY] });
    },
  });
}

export interface MissSignal {
  term: string;
  occurrence_count: number;
  last_seen: string;
}

export function useMissSignals(limit = 20) {
  const params = new URLSearchParams({ limit: String(limit) });

  return useQuery({
    queryKey: [GLOSSARY_KEY, "miss-signals", limit],
    queryFn: () =>
      apiGet<{ items: MissSignal[] }>(
        `/api/v1/glossary/miss-signals?${params.toString()}`,
      ),
    staleTime: 5 * 60 * 1000,
  });
}

export function useExportGlossary() {
  const token = getStoredToken();
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  return useMutation({
    mutationFn: async (): Promise<void> => {
      const headers: Record<string, string> = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      // fetch() used directly: apiGet() calls .json() and cannot handle binary blobs
      const res = await fetch(`${API_URL}/api/v1/glossary/export`, {
        headers,
      });
      if (!res.ok) throw new Error("Export failed");

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "glossary.csv";
      a.click();
      URL.revokeObjectURL(url);
    },
  });
}

export function useImportGlossary() {
  const queryClient = useQueryClient();
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  return useMutation({
    mutationFn: async (file: File): Promise<ImportResult> => {
      const formData = new FormData();
      formData.append("file", file);

      const token = getStoredToken();
      const headers: Record<string, string> = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      // fetch() used directly: apiPost() hardcodes Content-Type: application/json
      // and cannot send multipart/form-data (let browser set boundary automatically)
      const res = await fetch(`${API_URL}/api/v1/glossary/import`, {
        method: "POST",
        headers,
        body: formData,
      });

      if (!res.ok) {
        const errorBody = await res.json().catch(() => ({
          error: "import_failed",
          message: `Import failed with status ${res.status}`,
          request_id: "",
        }));
        throw new Error(errorBody.message ?? "Import failed");
      }

      return res.json() as Promise<ImportResult>;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [GLOSSARY_KEY] });
    },
  });
}
