"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type { JobRunRow, JobHistoryResponse } from "./useJobHistory";

export type { JobRunRow, JobHistoryResponse };

export interface TenantJobHistoryFilters {
  status?: string;
  from_date?: string;
  to_date?: string;
}

export function useTenantJobHistory(
  offset: number,
  limit: number,
  filters?: TenantJobHistoryFilters,
) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (filters?.status) params.set("status", filters.status);
  if (filters?.from_date) params.set("from_date", filters.from_date);
  if (filters?.to_date) params.set("to_date", filters.to_date);

  return useQuery({
    queryKey: ["tenant-job-history", offset, limit, filters],
    queryFn: () =>
      apiGet<JobHistoryResponse>(`/api/v1/tenant/jobs?${params.toString()}`),
    staleTime: 30_000,
    refetchInterval: (query) => {
      const items = query.state.data?.items;
      return items?.some((r) => r.status === "running") ? 15_000 : 60_000;
    },
  });
}
