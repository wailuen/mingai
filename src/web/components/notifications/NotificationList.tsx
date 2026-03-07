"use client";

import type { Notification } from "@/lib/hooks/useNotifications";
import { NotificationItem } from "./NotificationItem";

interface NotificationListProps {
  notifications: Notification[];
  onMarkRead: (id: string) => void;
  onMarkAllRead: () => void;
}

function SkeletonRow() {
  return (
    <div className="flex items-start gap-3 border-b border-border-faint px-4 py-3">
      <div className="h-1 w-1 shrink-0 rounded-full bg-bg-elevated" />
      <div className="h-3.5 w-3.5 shrink-0 rounded-badge bg-bg-elevated" />
      <div className="flex-1 space-y-2">
        <div className="h-3 w-3/4 rounded-badge bg-bg-elevated" />
        <div className="h-2.5 w-full rounded-badge bg-bg-elevated" />
        <div className="h-2 w-16 rounded-badge bg-bg-elevated" />
      </div>
    </div>
  );
}

export function NotificationList({
  notifications,
  onMarkRead,
  onMarkAllRead,
}: NotificationListProps) {
  const hasUnread = notifications.some((n) => !n.read);

  return (
    <div className="w-80 overflow-hidden rounded-card border border-border bg-bg-surface shadow-lg">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <span className="text-[13px] font-semibold text-text-primary">
          Notifications
        </span>
        {hasUnread && (
          <button
            type="button"
            onClick={onMarkAllRead}
            className="text-[11px] font-medium text-text-muted transition-[background,color,border-color,box-shadow] duration-[220ms] ease-[ease] hover:text-text-primary"
          >
            Mark all read
          </button>
        )}
      </div>

      {/* List */}
      <div className="max-h-96 overflow-y-auto">
        {notifications.length === 0 ? (
          <div className="flex items-center justify-center py-10">
            <span className="text-sm text-text-faint">
              No notifications yet
            </span>
          </div>
        ) : (
          notifications.map((notification) => (
            <NotificationItem
              key={notification.id}
              notification={notification}
              onMarkRead={onMarkRead}
            />
          ))
        )}
      </div>
    </div>
  );
}

export { SkeletonRow as NotificationSkeleton };
