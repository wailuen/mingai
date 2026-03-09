"use client";

import Link from "next/link";
import {
  Building2,
  Cpu,
  AlertCircle,
  UserPlus,
  BookOpen,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { isPlatformAdmin } from "@/lib/auth";

interface QuickAction {
  label: string;
  href: string;
  icon: LucideIcon;
  description: string;
}

const PLATFORM_ADMIN_ACTIONS: QuickAction[] = [
  {
    label: "Provision Tenant",
    href: "/settings/tenants",
    icon: Building2,
    description: "Create and configure a new workspace",
  },
  {
    label: "Configure AI Models",
    href: "/settings/llm-profiles",
    icon: Cpu,
    description: "Set up LLM profiles for tenants",
  },
  {
    label: "Review Issues",
    href: "/settings/issue-queue",
    icon: AlertCircle,
    description: "Check reported issues and escalations",
  },
];

const TENANT_ADMIN_ACTIONS: QuickAction[] = [
  {
    label: "Invite Users",
    href: "/settings/users",
    icon: UserPlus,
    description: "Add team members to your workspace",
  },
  {
    label: "Manage Glossary",
    href: "/settings/glossary",
    icon: BookOpen,
    description: "Define domain-specific terminology",
  },
  {
    label: "View Issues",
    href: "/settings/issue-queue",
    icon: AlertCircle,
    description: "Check reported issues and escalations",
  },
];

/**
 * Quick action buttons — role-aware.
 * Platform Admin: Provision Tenant, Configure AI Models, Review Issues.
 * Tenant Admin: Invite Users, Manage Glossary, View Issues.
 */
export function QuickActions() {
  const { claims } = useAuth();
  const actions =
    claims && isPlatformAdmin(claims)
      ? PLATFORM_ADMIN_ACTIONS
      : TENANT_ADMIN_ACTIONS;
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <h2 className="mb-4 text-section-heading text-text-primary">
        Quick Actions
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {actions.map((action) => {
          const Icon = action.icon;
          return (
            <Link
              key={action.label}
              href={action.href}
              className="flex items-center gap-3 rounded-card border border-border px-4 py-3 transition-colors hover:border-accent-ring hover:bg-accent-dim"
            >
              <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-control bg-bg-elevated">
                <Icon size={16} className="text-accent" />
              </div>
              <div>
                <span className="block text-sm font-medium text-text-primary">
                  {action.label}
                </span>
                <span className="block text-xs text-text-faint">
                  {action.description}
                </span>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
