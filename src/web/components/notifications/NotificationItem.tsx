"use client";

import { useRouter } from "next/navigation";
import { AlertCircle, CheckCircle2, Info, XCircle } from "lucide-react";
import type { Notification } from "@/lib/hooks/useNotifications";

interface NotificationItemProps {
  notification: Notification;
  onMarkRead: (id: string) => void;
}

const TYPE_ICONS: Record<
  Notification["type"],
  { icon: typeof AlertCircle; className: string }
> = {
  issue_update: { icon: AlertCircle, className: "text-warn" },
  sync_complete: { icon: CheckCircle2, className: "text-accent" },
  sync_failure: { icon: XCircle, className: "text-alert" },
  system: { icon: Info, className: "text-text-muted" },
};

function formatRelativeTime(isoDate: string): string {
  const now = Date.now();
  const then = new Date(isoDate).getTime();
  const diffMs = now - then;

  if (diffMs < 0) return "just now";

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return "just now";

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;

  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

export function NotificationItem({
  notification,
  onMarkRead,
}: NotificationItemProps) {
  const router = useRouter();
  const { icon: Icon, className: iconClassName } =
    TYPE_ICONS[notification.type];

  function handleClick() {
    onMarkRead(notification.id);
    if (notification.link?.startsWith("/")) {
      router.push(notification.link);
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className="flex w-full items-start gap-3 border-b border-border-faint px-4 py-3 text-left transition-[background,color,border-color,box-shadow] duration-[220ms] ease-[ease] hover:bg-bg-elevated"
    >
      {/* Unread indicator */}
      <div className="flex shrink-0 items-center pt-1">
        {!notification.read ? (
          <span className="block h-1 w-1 rounded-full bg-accent" />
        ) : (
          <span className="block h-1 w-1" />
        )}
      </div>

      {/* Type icon */}
      <div className="shrink-0 pt-0.5">
        <Icon size={14} className={iconClassName} />
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium leading-snug text-text-primary">
          {notification.title}
        </p>
        <p className="mt-0.5 text-xs leading-snug text-text-muted">
          {notification.body}
        </p>
        <p className="mt-1 font-mono text-[11px] text-text-faint">
          {formatRelativeTime(notification.created_at)}
        </p>
      </div>
    </button>
  );
}
