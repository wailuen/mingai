"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import { WifiOff, Wifi } from "lucide-react";

/* ── Context ─────────────────────────────────────────────────────────── */

interface NetworkStatus {
  isOnline: boolean;
  /** True if the session went offline at least once since mount */
  wasOffline: boolean;
}

const NetworkStatusContext = createContext<NetworkStatus>({
  isOnline: true,
  wasOffline: false,
});

export function useNetworkStatus(): NetworkStatus {
  return useContext(NetworkStatusContext);
}

/* ── Toast banner (internal) ─────────────────────────────────────────── */

type ToastKind = "offline" | "online" | null;

function NetworkToast({ kind }: { kind: ToastKind }) {
  if (!kind) return null;

  const isOffline = kind === "offline";

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-0 left-0 z-50 flex w-full items-center gap-2 border-t px-4 py-2 text-xs font-medium animate-fade-in"
      style={{
        background: isOffline
          ? "var(--alert-dim)"
          : "var(--accent-dim)",
        borderColor: isOffline ? "var(--alert)" : "var(--accent)",
        color: isOffline ? "var(--alert)" : "var(--accent)",
      }}
    >
      {isOffline ? <WifiOff size={14} /> : <Wifi size={14} />}
      <span>
        {isOffline
          ? "You're offline \u2014 messages will send when reconnected"
          : "Back online"}
      </span>
    </div>
  );
}

/* ── Provider ────────────────────────────────────────────────────────── */

interface NetworkStatusProviderProps {
  children: ReactNode;
}

export function NetworkStatusProvider({
  children,
}: NetworkStatusProviderProps) {
  const [isOnline, setIsOnline] = useState(true);
  const [wasOffline, setWasOffline] = useState(false);
  const [toast, setToast] = useState<ToastKind>(null);
  const onlineTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleOffline = useCallback(() => {
    setIsOnline(false);
    setWasOffline(true);
    setToast("offline");
    // Clear any pending "back online" timer
    if (onlineTimerRef.current) {
      clearTimeout(onlineTimerRef.current);
      onlineTimerRef.current = null;
    }
  }, []);

  const handleOnline = useCallback(() => {
    setIsOnline(true);
    setToast("online");
    // Auto-dismiss "back online" toast after 3 seconds
    onlineTimerRef.current = setTimeout(() => {
      setToast(null);
      onlineTimerRef.current = null;
    }, 3000);
  }, []);

  useEffect(() => {
    // Initialize from current browser state
    if (typeof window !== "undefined") {
      setIsOnline(navigator.onLine);
      if (!navigator.onLine) {
        setWasOffline(true);
        setToast("offline");
      }
    }

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      if (onlineTimerRef.current) {
        clearTimeout(onlineTimerRef.current);
      }
    };
  }, [handleOnline, handleOffline]);

  return (
    <NetworkStatusContext.Provider value={{ isOnline, wasOffline }}>
      {children}
      <NetworkToast kind={toast} />
    </NetworkStatusContext.Provider>
  );
}
