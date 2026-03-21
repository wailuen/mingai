"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { cn } from "@/lib/utils";
import { Building2 } from "lucide-react";
import { TenantDetailPanel } from "./TenantDetailPanel";

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  status: "active" | "suspended" | "draft";
  plan: string;
  primary_contact_email: string;
  created_at: string;
}

interface TenantListResponse {
  items: Tenant[];
  total: number;
  page: number;
  page_size: number;
}

function statusBadgeClass(status: Tenant["status"]): string {
  switch (status) {
    case "active":
      return "border-accent/30 bg-accent-dim text-accent";
    case "suspended":
      return "border-alert/30 bg-alert-dim text-alert";
    case "draft":
      return "border-warn/30 bg-warn-dim text-warn";
  }
}

interface TenantTableProps {
  searchQuery: string;
}

export function TenantTable({ searchQuery }: TenantTableProps) {
  const {
    data: tenants,
    isPending,
    error,
  } = useQuery<Tenant[]>({
    queryKey: ["platform-tenants"],
    queryFn: async () => {
      const res = await apiGet<TenantListResponse>(
        "/api/v1/platform/tenants"
      );
      return res.items;
    },
  });

  const [selectedTenantId, setSelectedTenantId] = useState<string | null>(null);

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load tenants: {error.message}
      </p>
    );
  }

  const filtered = tenants?.filter((t) =>
    t.name.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  const selectedTenant =
    selectedTenantId && tenants
      ? (tenants.find((t) => t.id === selectedTenantId) ?? null)
      : null;

  return (
    <>
      <div className="overflow-hidden rounded-card border border-border">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border bg-bg-surface">
              <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Name
              </th>
              <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Plan
              </th>
              <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Status
              </th>
              <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Slug
              </th>
              <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Contact
              </th>
              <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Created
              </th>
            </tr>
          </thead>
          <tbody>
            {isPending ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRowSkeleton key={i} columns={6} />
              ))
            ) : !filtered || filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3.5 py-16 text-center">
                  <div className="flex flex-col items-center gap-3">
                    <div className="flex h-12 w-12 items-center justify-center rounded-card bg-bg-elevated">
                      <Building2 size={24} className="text-text-faint" />
                    </div>
                    <p className="text-body-default font-medium text-text-muted">
                      No tenants found
                    </p>
                    <p className="text-xs text-text-faint">
                      {searchQuery
                        ? "Try adjusting your search query"
                        : "Create your first tenant to get started"}
                    </p>
                  </div>
                </td>
              </tr>
            ) : (
              filtered.map((tenant) => (
                <tr
                  key={tenant.id}
                  onClick={() => setSelectedTenantId(tenant.id)}
                  className="cursor-pointer border-b border-border-faint transition-colors hover:bg-accent-dim"
                >
                  <td className="px-3.5 py-3 text-body-default font-medium text-text-primary">
                    {tenant.name}
                  </td>
                  <td className="px-3.5 py-3">
                    <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 font-mono text-data-value text-text-muted">
                      {tenant.plan}
                    </span>
                  </td>
                  <td className="px-3.5 py-3">
                    <span
                      className={cn(
                        "inline-block rounded-badge border px-2 py-0.5 text-[11px] font-medium capitalize",
                        statusBadgeClass(tenant.status),
                      )}
                    >
                      {tenant.status}
                    </span>
                  </td>
                  <td className="px-3.5 py-3 font-mono text-data-value text-text-muted">
                    {tenant.slug}
                  </td>
                  <td className="px-3.5 py-3 text-body-default text-text-muted">
                    {tenant.primary_contact_email || "\u2014"}
                  </td>
                  <td className="px-3.5 py-3 font-mono text-data-value text-text-muted">
                    {new Date(tenant.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {selectedTenant && (
        <TenantDetailPanel
          tenant={selectedTenant}
          onClose={() => setSelectedTenantId(null)}
        />
      )}
    </>
  );
}
