"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiDelete } from "@/lib/api";

export interface MemoryNote {
  id: string;
  content: string;
  created_at: string;
  source?: string;
}

const MEMORY_KEY = "user-memory";

/**
 * FE-051: Fetch memory notes for the current user.
 * GET /api/v1/memory/notes
 */
export function useUserMemory() {
  return useQuery({
    queryKey: [MEMORY_KEY, "notes"],
    queryFn: () => apiGet<MemoryNote[]>("/api/v1/memory/notes"),
  });
}

/**
 * FE-051: Delete a single memory note.
 * DELETE /api/v1/memory/notes/{id}
 */
export function useDeleteMemoryNote() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (noteId: string) => apiDelete(`/api/v1/memory/notes/${noteId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [MEMORY_KEY] });
    },
  });
}

/**
 * FE-051: Clear all memory notes.
 * DELETE /api/v1/memory/notes
 */
export function useClearAllMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => apiDelete("/api/v1/memory/notes"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [MEMORY_KEY] });
    },
  });
}
