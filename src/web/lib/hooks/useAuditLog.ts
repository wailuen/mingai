"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet, type PaginatedResponse } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AuditEvent {
  id: string;
  timestamp: string; // normalized from created_at
  actor_type: "platform_admin" | "tenant_admin" | "system" | null;
  actor_email: string;
  action: string;
  resource_type: string;
  resource_id: string;
  tenant_name: string;
  outcome: "success" | "failure";
  ip_address: string;
}

// Raw shape from backend — field names differ from frontend types
interface RawAuditEvent {
  id: string;
  created_at: string; // backend sends created_at, not timestamp
  actor_type?: string | null;
  actor_id?: string;
  actor_email: string;
  action: string;
  resource_type?: string;
  resource_id?: string;
  tenant_name?: string;
  outcome?: string;
  ip_address?: string;
}

interface RawAuditLogResponse {
  items: RawAuditEvent[];
  total: number;
  page: number;
  page_size: number; // backend sends page_size, PaginatedResponse uses limit
  next_cursor?: string | null;
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
    queryFn: async () => {
      const raw = await apiGet<RawAuditLogResponse>(
        `/api/v1/platform/audit-log?${qs}`,
      );
      return {
        items: raw.items.map((e) => ({
          id: e.id,
          timestamp: e.created_at, // normalize field name
          actor_type: (e.actor_type ?? null) as AuditEvent["actor_type"],
          actor_email: e.actor_email,
          action: e.action,
          resource_type: e.resource_type ?? "",
          resource_id: e.resource_id ?? "",
          tenant_name: e.tenant_name ?? "",
          outcome: (e.outcome ?? "success") as AuditEvent["outcome"],
          ip_address: e.ip_address ?? "",
        })),
        total: raw.total,
        page: raw.page,
        limit: raw.page_size, // normalize field name
        total_pages: Math.ceil(raw.total / raw.page_size),
      } satisfies import("@/lib/api").PaginatedResponse<AuditEvent>;
    },
    staleTime: 15 * 1000,
  });
}
