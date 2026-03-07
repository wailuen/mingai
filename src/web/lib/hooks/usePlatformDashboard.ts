"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

// ---------------------------------------------------------------------------
// Dashboard stats (GET /api/v1/admin/dashboard)
// ---------------------------------------------------------------------------

export interface DashboardStats {
  active_users: number;
  documents_indexed: number;
  queries_today: number;
  satisfaction_pct: number;
}

export function useDashboardStats() {
  return useQuery({
    queryKey: ["platform-dashboard-stats"],
    queryFn: () => apiGet<DashboardStats>("/api/v1/admin/dashboard"),
  });
}

// ---------------------------------------------------------------------------
// Platform stats (GET /api/v1/platform/stats)
// ---------------------------------------------------------------------------

export interface PlatformStats {
  total_tenants: number;
  active_tenants: number;
  total_users: number;
  queries_today: number;
}

export function usePlatformStats() {
  return useQuery({
    queryKey: ["platform-stats"],
    queryFn: () => apiGet<PlatformStats>("/api/v1/platform/stats"),
  });
}

// ---------------------------------------------------------------------------
// Tenants (GET /api/v1/platform/tenants)
// ---------------------------------------------------------------------------

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  plan: "starter" | "professional" | "enterprise";
  status: string;
  primary_contact_email: string;
  created_at: string;
}

export interface TenantsResponse {
  items: Tenant[];
  total: number;
  page: number;
  page_size: number;
}

export function useTenants(page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["platform-tenants", page, pageSize],
    queryFn: () =>
      apiGet<TenantsResponse>(
        `/api/v1/platform/tenants?page=${page}&page_size=${pageSize}`,
      ),
  });
}

// ---------------------------------------------------------------------------
// Tenant health (GET /api/v1/platform/tenants/:id/health)
// ---------------------------------------------------------------------------

export interface TenantHealthResponse {
  tenant_id: string;
  overall_score: number;
  category: string;
  at_risk: boolean;
  components: Record<
    string,
    {
      score: number;
      weight: number;
      details: Record<string, number>;
    }
  >;
}

export function useTenantHealth(tenantId: string | null) {
  return useQuery({
    queryKey: ["platform-tenant-health", tenantId],
    queryFn: () =>
      apiGet<TenantHealthResponse>(
        `/api/v1/platform/tenants/${tenantId}/health`,
      ),
    enabled: !!tenantId,
  });
}

// ---------------------------------------------------------------------------
// Create tenant (POST /api/v1/platform/tenants)
// ---------------------------------------------------------------------------

export interface CreateTenantPayload {
  name: string;
  plan: "starter" | "professional" | "enterprise";
  primary_contact_email: string;
  slug?: string;
}

export interface CreateTenantResponse extends Tenant {
  job_id: string;
}

export function useCreateTenant() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateTenantPayload) =>
      apiPost<CreateTenantResponse>("/api/v1/platform/tenants", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-tenants"] });
      queryClient.invalidateQueries({
        queryKey: ["platform-dashboard-stats"],
      });
      queryClient.invalidateQueries({ queryKey: ["platform-stats"] });
    },
  });
}
