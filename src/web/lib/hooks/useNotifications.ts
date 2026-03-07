"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getStoredToken } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL;
const MAX_NOTIFICATIONS = 50;
const RECONNECT_BASE_DELAY_MS = 3000;
const RECONNECT_MAX_DELAY_MS = 60_000;
const MAX_RECONNECT_ATTEMPTS = 10;

export interface Notification {
  id: string;
  type: "issue_update" | "sync_complete" | "sync_failure" | "system";
  title: string;
  body: string;
  link?: string;
  created_at: string;
  read: boolean;
}

interface UseNotificationsReturn {
  notifications: Notification[];
  unreadCount: number;
  isConnected: boolean;
  markAsRead: (id: string) => void;
  markAllRead: () => void;
}

/**
 * SSE subscription hook for real-time notifications.
 *
 * Uses fetch + ReadableStream instead of EventSource to support
 * custom Authorization headers. Auto-reconnects on disconnect
 * with exponential backoff capped at MAX_RECONNECT_ATTEMPTS.
 */
export function useNotifications(): UseNotificationsReturn {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(
    null,
  );
  const reconnectAttempts = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const unreadCount = notifications.filter((n) => !n.read).length;

  const addNotification = useCallback((notification: Notification) => {
    setNotifications((prev) => {
      const exists = prev.some((n) => n.id === notification.id);
      if (exists) return prev;
      const next = [notification, ...prev];
      if (next.length > MAX_NOTIFICATIONS) {
        return next.slice(0, MAX_NOTIFICATIONS);
      }
      return next;
    });
  }, []);

  const markAsRead = useCallback((id: string) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n)),
    );
  }, []);

  const markAllRead = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  }, []);

  const connect = useCallback(async () => {
    const token = getStoredToken();
    if (!token || !API_URL) return;

    // Cancel any existing reader before creating a new connection
    readerRef.current?.cancel().catch(() => {});
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(`${API_URL}/api/v1/notifications/stream`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`SSE connection failed: ${response.status}`);
      }

      setIsConnected(true);
      reconnectAttempts.current = 0;

      const reader = response.body.getReader();
      readerRef.current = reader;
      const decoder = new TextDecoder();
      let buffer = "";

      while (mountedRef.current) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          const lines = part.split("\n");
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const jsonStr = line.slice(6).trim();
              if (!jsonStr) continue;
              try {
                const notification = JSON.parse(jsonStr) as Notification;
                addNotification(notification);
              } catch {
                // Skip malformed JSON lines
              }
            }
            // Ignore keepalive comments (lines starting with ":")
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        readerRef.current = null;
        return;
      }
      // Connection lost -- cancel reader then fall through to reconnect
      readerRef.current?.cancel().catch(() => {});
      readerRef.current = null;
    } finally {
      if (mountedRef.current) {
        setIsConnected(false);
      }
    }

    // Reconnect logic
    if (
      mountedRef.current &&
      reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS
    ) {
      reconnectAttempts.current += 1;
      const delay = Math.min(
        RECONNECT_BASE_DELAY_MS * 2 ** (reconnectAttempts.current - 1),
        RECONNECT_MAX_DELAY_MS,
      );
      reconnectTimer.current = setTimeout(() => {
        if (mountedRef.current) {
          void connect();
        }
      }, delay);
    }
  }, [addNotification]);

  useEffect(() => {
    mountedRef.current = true;
    void connect();

    return () => {
      mountedRef.current = false;
      readerRef.current?.cancel().catch(() => {});
      readerRef.current = null;
      abortRef.current?.abort();
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
    };
  }, [connect]);

  return { notifications, unreadCount, isConnected, markAsRead, markAllRead };
}
