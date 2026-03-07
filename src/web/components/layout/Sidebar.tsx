"use client";

import { useState } from "react";
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
  Search,
  Boxes,
  Shield,
  type LucideIcon,
} from "lucide-react";
import type { JWTClaims } from "@/lib/auth";
import { cn } from "@/lib/utils";

interface SidebarProps {
  claims: JWTClaims | null;
  conversations?: ConversationItem[];
  onConversationSelect?: (id: string) => void;
  activeConversationId?: string | null;
}

interface ConversationItem {
  id: string;
  title: string;
  updated_at: string;
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
 * End User sidebar: History only (no agent list, no routing navigation).
 * Mode selector lives in the input bar, not the sidebar.
 */
function EndUserSidebar({
  conversations = [],
  onConversationSelect,
  activeConversationId,
}: Pick<
  SidebarProps,
  "conversations" | "onConversationSelect" | "activeConversationId"
>) {
  const [searchQuery, setSearchQuery] = useState("");

  const filteredConversations = conversations.filter((c) =>
    c.title.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  const groupedConversations = groupByDate(filteredConversations);

  return (
    <div className="flex h-full flex-col">
      <div className="px-4 pb-2">
        <span className="text-label-nav uppercase tracking-wider text-text-faint">
          History
        </span>
      </div>
      <div className="px-3 pb-3">
        <div className="relative">
          <Search
            size={14}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-faint"
          />
          <input
            type="text"
            placeholder="Search history..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-control border border-border bg-bg-elevated py-1.5 pl-8 pr-3 text-xs text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-2">
        {groupedConversations.map((group) => (
          <div key={group.label} className="mb-3">
            <div className="px-2 pb-1.5 text-label-nav uppercase tracking-wider text-text-faint">
              {group.label}
            </div>
            {group.items.map((conv) => (
              <button
                key={conv.id}
                onClick={() => onConversationSelect?.(conv.id)}
                className={cn(
                  "w-full rounded-control px-3 py-1.5 text-left text-sm transition-colors",
                  conv.id === activeConversationId
                    ? "bg-accent-dim text-text-primary"
                    : "text-text-muted hover:bg-bg-elevated hover:text-text-primary",
                )}
              >
                <span className="line-clamp-1">{conv.title}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
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
  conversations,
  onConversationSelect,
  activeConversationId,
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
        <EndUserSidebar
          conversations={conversations}
          onConversationSelect={onConversationSelect}
          activeConversationId={activeConversationId}
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

/** Group conversations by relative date. */
function groupByDate(conversations: ConversationItem[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const sevenDaysAgo = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);

  const groups: { label: string; items: ConversationItem[] }[] = [
    { label: "Today", items: [] },
    { label: "Last 7 Days", items: [] },
    { label: "Earlier", items: [] },
  ];

  for (const conv of conversations) {
    const date = new Date(conv.updated_at);
    if (date >= today) {
      groups[0].items.push(conv);
    } else if (date >= sevenDaysAgo) {
      groups[1].items.push(conv);
    } else {
      groups[2].items.push(conv);
    }
  }

  return groups.filter((g) => g.items.length > 0);
}
