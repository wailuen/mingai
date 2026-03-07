"use client";

import Link from "next/link";
import { UserPlus, FileText, Bot } from "lucide-react";

interface QuickAction {
  label: string;
  href: string;
  icon: typeof UserPlus;
  description: string;
}

const QUICK_ACTIONS: QuickAction[] = [
  {
    label: "Invite Users",
    href: "/settings/users",
    icon: UserPlus,
    description: "Add team members to the workspace",
  },
  {
    label: "Connect Document Store",
    href: "/settings/knowledge-base",
    icon: FileText,
    description: "Link SharePoint or Google Drive",
  },
  {
    label: "Deploy Agent",
    href: "/settings/agents",
    icon: Bot,
    description: "Set up your first AI assistant",
  },
];

/**
 * Quick action buttons for common admin tasks.
 * Invite Users, Connect Document Store, Deploy Agent.
 */
export function QuickActions() {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <h2 className="mb-4 text-section-heading text-text-primary">
        Quick Actions
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {QUICK_ACTIONS.map((action) => {
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
