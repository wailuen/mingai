"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiPatch } from "@/lib/api";
import { X, Building2, Users, Calendar, Shield, Pencil } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Tenant } from "./TenantTable";

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

interface TenantDetailPanelProps {
  tenant: Tenant;
  onClose: () => void;
}

export function TenantDetailPanel({ tenant, onClose }: TenantDetailPanelProps) {
  const [suspending, setSuspending] = useState(false);
  const queryClient = useQueryClient();

  async function handleSuspendToggle() {
    setSuspending(true);
    try {
      const newStatus = tenant.status === "suspended" ? "active" : "suspended";
      await apiPatch(`/api/v1/platform/tenants/${tenant.id}`, {
        status: newStatus,
      });
      queryClient.invalidateQueries({ queryKey: ["platform-tenants"] });
      onClose();
    } catch {
      // Error surfaced by API layer
    } finally {
      setSuspending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-bg-deep/50">
      <div className="absolute inset-0" onClick={onClose} role="presentation" />
      <div className="relative z-10 flex h-full w-full max-w-md flex-col border-l border-border bg-bg-surface animate-slide-in-right">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-3">
            <h2 className="text-section-heading text-text-primary">
              {tenant.name}
            </h2>
            <span
              className={cn(
                "inline-block rounded-badge border px-2 py-0.5 text-[11px] font-medium capitalize",
                statusBadgeClass(tenant.status),
              )}
            >
              {tenant.status}
            </span>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5">
          {/* Identity */}
          <section className="mb-6">
            <h3 className="mb-3 text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Identity
            </h3>
            <div className="space-y-3">
              <DetailRow
                icon={Building2}
                label="Plan"
                value={tenant.plan}
                mono
              />
              <DetailRow
                icon={Users}
                label="Slug"
                value={tenant.slug}
                mono
              />
              <DetailRow
                icon={Calendar}
                label="Created"
                value={new Date(tenant.created_at).toLocaleDateString()}
                mono
              />
              <DetailRow
                icon={Shield}
                label="Tenant ID"
                value={tenant.id}
                mono
              />
            </div>
          </section>

          {/* Contact */}
          <section className="mb-6">
            <h3 className="mb-3 text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Contact
            </h3>
            <div className="rounded-card border border-border bg-bg-elevated p-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-text-muted">
                  Primary Contact
                </span>
                <span className="font-mono text-data-value text-text-primary">
                  {tenant.primary_contact_email || "\u2014"}
                </span>
              </div>
            </div>
          </section>

          {/* Quick Actions */}
          <section>
            <h3 className="mb-3 text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Quick Actions
            </h3>
            <div className="space-y-2">
              <button className="flex w-full items-center gap-2 rounded-control border border-border px-3 py-2 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary">
                <Pencil size={14} />
                Edit Tenant
              </button>

              <div className="my-3 border-t border-border-faint" />

              <button
                onClick={handleSuspendToggle}
                disabled={suspending}
                className="flex w-full items-center gap-2 rounded-control border border-alert/30 px-3 py-2 text-sm text-alert transition-colors hover:bg-alert-dim disabled:opacity-50"
              >
                <Shield size={14} />
                {suspending
                  ? "Processing..."
                  : tenant.status === "suspended"
                    ? "Reactivate Tenant"
                    : "Suspend Tenant"}
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function DetailRow({
  icon: Icon,
  label,
  value,
  mono,
}: {
  icon: typeof Building2;
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center gap-3">
      <Icon size={14} className="flex-shrink-0 text-text-faint" />
      <span className="text-xs text-text-faint">{label}</span>
      <span
        className={cn(
          "ml-auto text-sm text-text-primary",
          mono && "font-mono text-data-value",
        )}
      >
        {value}
      </span>
    </div>
  );
}
