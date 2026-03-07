"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";
import { getStoredToken } from "@/lib/auth";

export interface GlossaryTerm {
  id: string;
  term: string;
  full_form?: string;
  definition: string;
  aliases?: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
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
    queryFn: () =>
      apiGet<GlossaryListResponse>(`/api/v1/glossary?${params.toString()}`),
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
