"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";
import type {
  MyReportsResponse,
  IssueReport,
  RegressionResponse,
} from "@/lib/types/issues";

export function useMyReports(page: number) {
  return useQuery<MyReportsResponse>({
    queryKey: ["my-reports", "list", page],
    queryFn: () =>
      apiGet<MyReportsResponse>(`/api/v1/my-reports?page=${page}&page_size=20`),
  });
}

export function useReportDetail(id: string) {
  return useQuery<IssueReport>({
    queryKey: ["my-reports", "detail", id],
    queryFn: () => apiGet<IssueReport>(`/api/v1/my-reports/${id}`),
    enabled: !!id,
  });
}

export function useReportRegression() {
  const queryClient = useQueryClient();

  return useMutation<
    RegressionResponse,
    Error,
    { id: string; comment?: string }
  >({
    mutationFn: ({ id, comment }) =>
      apiPost<RegressionResponse>(
        `/api/v1/issue-reports/${id}/still-happening`,
        { comment },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-reports"] });
    },
  });
}
