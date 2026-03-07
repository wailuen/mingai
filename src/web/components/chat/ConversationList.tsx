"use client";

import { useState, useEffect, useCallback } from "react";
import { Plus, MessageSquare, Search } from "lucide-react";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

interface ConversationsResponse {
  items: Conversation[];
  total: number;
  page: number;
  page_size: number;
}

interface ConversationListProps {
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
}

interface DateGroup {
  label: string;
  items: Conversation[];
}

/**
 * Conversation list sidebar for End User chat.
 * Fetches GET /api/v1/conversations on mount.
 * Groups by date: Today / Yesterday / This Week / Older.
 * Includes search, loading skeletons, and empty state.
 */
export function ConversationList({
  activeConversationId,
  onSelectConversation,
  onNewConversation,
}: ConversationListProps) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchConversations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiGet<ConversationsResponse>(
        "/api/v1/conversations?page=1&page_size=50",
      );
      setConversations(response.items);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load conversations";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  // Re-fetch when a new conversation is started (conversation ID changes)
  useEffect(() => {
    if (activeConversationId) {
      fetchConversations();
    }
  }, [activeConversationId, fetchConversations]);

  const filteredConversations = conversations.filter((c) =>
    (c.title || "New conversation")
      .toLowerCase()
      .includes(searchQuery.toLowerCase()),
  );

  const groupedConversations = groupByDate(filteredConversations);

  return (
    <div className="flex h-full flex-col">
      {/* Header with new chat button */}
      <div className="flex items-center justify-between px-4 pb-2">
        <span className="text-label-nav uppercase tracking-wider text-text-faint">
          History
        </span>
        <button
          onClick={onNewConversation}
          className="flex h-6 w-6 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
          aria-label="New conversation"
        >
          <Plus size={14} />
        </button>
      </div>

      {/* Search */}
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

      {/* Content area */}
      <div className="flex-1 overflow-y-auto px-2">
        {loading ? (
          <ConversationListSkeleton />
        ) : error ? (
          <div className="px-3 py-4 text-center">
            <p className="text-xs text-alert">{error}</p>
            <button
              onClick={fetchConversations}
              className="mt-2 text-xs text-text-muted transition-colors hover:text-text-primary"
            >
              Retry
            </button>
          </div>
        ) : groupedConversations.length === 0 ? (
          <ConversationListEmpty hasSearch={searchQuery.length > 0} />
        ) : (
          groupedConversations.map((group) => (
            <div key={group.label} className="mb-3">
              <div className="px-2 pb-1.5 text-label-nav uppercase tracking-wider text-text-faint">
                {group.label}
              </div>
              {group.items.map((conv) => (
                <ConversationItem
                  key={conv.id}
                  conversation={conv}
                  isActive={conv.id === activeConversationId}
                  onSelect={onSelectConversation}
                />
              ))}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/** Single conversation row with active state indicator. */
function ConversationItem({
  conversation,
  isActive,
  onSelect,
}: {
  conversation: Conversation;
  isActive: boolean;
  onSelect: (id: string) => void;
}) {
  const title = conversation.title || "New conversation";
  const timestamp = formatRelativeTime(conversation.updated_at);

  return (
    <button
      onClick={() => onSelect(conversation.id)}
      className={cn(
        "group flex w-full items-center gap-2 rounded-control px-3 py-1.5 text-left text-sm transition-colors",
        isActive
          ? "border-l-2 border-l-accent bg-accent-dim text-text-primary"
          : "text-text-muted hover:bg-bg-elevated hover:text-text-primary",
      )}
    >
      <div className="min-w-0 flex-1">
        <span className="line-clamp-1 block">{title}</span>
        <span className="block font-mono text-[10px] text-text-faint">
          {timestamp}
        </span>
      </div>
    </button>
  );
}

/** Loading skeleton: 3 rows matching conversation item height. */
function ConversationListSkeleton() {
  return (
    <div className="space-y-1 px-1">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="rounded-control px-3 py-2">
          <div className="mb-1.5 h-3.5 w-3/4 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="h-2.5 w-1/3 animate-pulse rounded-badge bg-bg-elevated" />
        </div>
      ))}
    </div>
  );
}

/** Empty state with icon and message. */
function ConversationListEmpty({ hasSearch }: { hasSearch: boolean }) {
  return (
    <div className="flex flex-col items-center px-3 py-8 text-center">
      <MessageSquare size={24} className="mb-2 text-text-faint" />
      <p className="text-xs text-text-faint">
        {hasSearch ? "No matching conversations" : "No conversations yet"}
      </p>
      {!hasSearch && (
        <p className="mt-1 text-[10px] text-text-faint">
          Start a conversation to see it here
        </p>
      )}
    </div>
  );
}

/** Group conversations into Today / Yesterday / This Week / Older. */
function groupByDate(conversations: Conversation[]): DateGroup[] {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayStart = new Date(todayStart.getTime() - 24 * 60 * 60 * 1000);
  const weekStart = new Date(todayStart.getTime() - 7 * 24 * 60 * 60 * 1000);

  const groups: DateGroup[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "This Week", items: [] },
    { label: "Older", items: [] },
  ];

  for (const conv of conversations) {
    const date = new Date(conv.updated_at);
    if (date >= todayStart) {
      groups[0].items.push(conv);
    } else if (date >= yesterdayStart) {
      groups[1].items.push(conv);
    } else if (date >= weekStart) {
      groups[2].items.push(conv);
    } else {
      groups[3].items.push(conv);
    }
  }

  return groups.filter((g) => g.items.length > 0);
}

/** Format timestamp as relative time string. */
function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffMin < 1) return "Just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}
