"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  LayoutDashboard,
  Users,
  FileText,
  BookOpen,
  Bot,
  BarChart3,
  Settings,
  Building2,
  Cpu,
  DollarSign,
  AlertCircle,
  Boxes,
  Shield,
  type LucideIcon,
} from "lucide-react";
import type { JWTClaims } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { ConversationList } from "@/components/chat/ConversationList";

interface SidebarProps {
  claims: JWTClaims | null;
  activeConversationId?: string | null;
  onSelectConversation?: (id: string) => void;
  onNewConversation?: () => void;
}

interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

/**
 * Tenant Admin sidebar: Workspace | Insights sections.
 */
const TENANT_ADMIN_SECTIONS: NavSection[] = [
  {
    title: "Workspace",
    items: [
      {
        label: "Dashboard",
        href: "/settings/dashboard",
        icon: LayoutDashboard,
      },
      { label: "Documents", href: "/settings/knowledge-base", icon: FileText },
      { label: "Users", href: "/settings/users", icon: Users },
      { label: "Agents", href: "/settings/agents", icon: Bot },
      { label: "Glossary", href: "/settings/glossary", icon: BookOpen },
    ],
  },
  {
    title: "Insights",
    items: [
      { label: "Analytics", href: "/settings/analytics", icon: BarChart3 },
      { label: "Issues", href: "/settings/issues", icon: AlertCircle },
      { label: "Settings", href: "/settings/workspace", icon: Settings },
    ],
  },
];

/**
 * Platform Admin sidebar: Operations | Intelligence | Finance.
 */
const PLATFORM_ADMIN_SECTIONS: NavSection[] = [
  {
    title: "Operations",
    items: [
      { label: "Dashboard", href: "/admin/dashboard", icon: LayoutDashboard },
      { label: "Tenants", href: "/admin/tenants", icon: Building2 },
      { label: "Issue Queue", href: "/admin/issue-queue", icon: AlertCircle },
    ],
  },
  {
    title: "Intelligence",
    items: [
      { label: "LLM Profiles", href: "/admin/llm-profiles", icon: Cpu },
      { label: "Agent Templates", href: "/admin/agent-templates", icon: Bot },
      { label: "Analytics", href: "/admin/analytics", icon: BarChart3 },
      { label: "Tool Catalog", href: "/admin/tool-catalog", icon: Boxes },
    ],
  },
  {
    title: "Finance",
    items: [
      {
        label: "Cost Analytics",
        href: "/admin/cost-analytics",
        icon: DollarSign,
      },
    ],
  },
];

function AdminSidebar({ sections }: { sections: NavSection[] }) {
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      {sections.map((section) => (
        <div key={section.title} className="mb-4">
          <div className="px-4 pb-2 text-label-nav uppercase tracking-wider text-text-faint">
            {section.title}
          </div>
          <div className="space-y-0.5 px-2">
            {section.items.map((item) => {
              const Icon = item.icon;
              const isActive = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2.5 rounded-control px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-accent-dim text-accent"
                      : "text-text-muted hover:bg-bg-elevated hover:text-text-primary",
                  )}
                >
                  <Icon size={16} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export function Sidebar({
  claims,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
}: SidebarProps) {
  const isPlatform = claims?.scope === "platform";
  const isTenantAdmin =
    claims?.scope === "tenant" && claims.roles.includes("tenant_admin");

  return (
    <aside className="flex h-full w-sidebar-w flex-col border-r border-border bg-bg-surface pt-3">
      {isPlatform ? (
        <AdminSidebar sections={PLATFORM_ADMIN_SECTIONS} />
      ) : isTenantAdmin ? (
        <AdminSidebar sections={TENANT_ADMIN_SECTIONS} />
      ) : (
        <ConversationList
          activeConversationId={activeConversationId ?? null}
          onSelectConversation={onSelectConversation ?? (() => {})}
          onNewConversation={onNewConversation ?? (() => {})}
        />
      )}

      {/* End user quick links at bottom */}
      {!isPlatform && !isTenantAdmin && (
        <div className="border-t border-border-faint px-2 py-2">
          <Link
            href="/settings/privacy"
            className="flex items-center gap-2.5 rounded-control px-3 py-2 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <Shield size={16} />
            <span>Privacy</span>
          </Link>
        </div>
      )}
    </aside>
  );
}
