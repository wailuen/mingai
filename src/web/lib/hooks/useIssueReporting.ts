"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types -- Tenant Admin Issue Reporting Configuration
// ---------------------------------------------------------------------------

export interface IssueReportingConfig {
  enabled: boolean;
  notify_email: string;
  auto_escalate_p0: boolean;
  auto_escalate_p1: boolean;
  escalation_threshold_hours: number;
  slack_webhook_url?: string;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const ISSUE_REPORTING_KEY = ["admin-issue-reporting"] as const;

const DEFAULT_CONFIG: IssueReportingConfig = {
  enabled: false,
  notify_email: "",
  auto_escalate_p0: true,
  auto_escalate_p1: false,
  escalation_threshold_hours: 4,
  slack_webhook_url: "",
};

/** GET /api/v1/admin/settings/issue-reporting */
export function useIssueReportingConfig() {
  return useQuery({
    queryKey: ISSUE_REPORTING_KEY,
    queryFn: async () => {
      const config = await apiGet<IssueReportingConfig | null>(
        "/api/v1/admin/settings/issue-reporting",
      );
      return config ?? DEFAULT_CONFIG;
    },
  });
}

/** PATCH /api/v1/admin/settings/issue-reporting */
export function useUpdateIssueReportingConfig() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (config: Partial<IssueReportingConfig>) =>
      apiPatch<IssueReportingConfig>(
        "/api/v1/admin/settings/issue-reporting",
        config,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ISSUE_REPORTING_KEY });
    },
  });
}
