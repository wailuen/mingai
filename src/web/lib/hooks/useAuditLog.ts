"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet, type PaginatedResponse } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AuditEvent {
  id: string;
  timestamp: string;
  actor_type: "platform_admin" | "tenant_admin" | "system" | null;
  actor_email: string;
  action: string;
  resource_type: string;
  resource_id: string;
  tenant_name: string;
  outcome: "success" | "failure";
  ip_address: string;
}

export interface AuditLogFilters {
  actor_type?: "platform_admin" | "tenant_admin" | "system";
  action_category?: string;
  tenant_id?: string;
  from?: string;
  to?: string;
}

// ---------------------------------------------------------------------------
// useAuditLog
// ---------------------------------------------------------------------------

export function useAuditLog(
  page: number,
  limit: number,
  filters?: AuditLogFilters,
) {
  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("limit", String(limit));

  if (filters?.actor_type) params.set("actor_type", filters.actor_type);
  if (filters?.action_category)
    params.set("action_category", filters.action_category);
  if (filters?.tenant_id) params.set("tenant_id", filters.tenant_id);
  if (filters?.from) params.set("from", filters.from);
  if (filters?.to) params.set("to", filters.to);

  const qs = params.toString();

  return useQuery({
    queryKey: ["platform-audit-log", page, limit, filters],
    queryFn: () =>
      apiGet<PaginatedResponse<AuditEvent>>(`/api/v1/platform/audit-log?${qs}`),
    staleTime: 15 * 1000,
  });
}
