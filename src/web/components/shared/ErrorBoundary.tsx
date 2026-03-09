"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { WifiOff } from "lucide-react";

interface ErrorBoundaryProps {
  children: ReactNode;
  /** Custom fallback UI to display when an error is caught */
  fallback?: ReactNode;
  /** Callback fired when an error is caught (for logging/telemetry) */
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

/**
 * Detect whether the error is likely network-related.
 * Checks common fetch/network error patterns and browser online status.
 */
function isNetworkError(error: Error | null): boolean {
  if (typeof navigator !== "undefined" && !navigator.onLine) return true;
  if (!error) return false;
  const msg = error.message.toLowerCase();
  return (
    msg.includes("failed to fetch") ||
    msg.includes("network") ||
    msg.includes("load failed") ||
    msg.includes("net::err") ||
    msg.includes("aborted") ||
    msg.includes("timeout")
  );
}

/**
 * FE-063 / GAP-024: Error boundary wrapper with offline awareness.
 *
 * Place around any section that might fail (data-fetching components,
 * chat rendering, SSE-driven components).
 *
 * When the browser is offline the fallback displays a connection-specific
 * message and waits for online status before allowing retry.
 *
 * Note: Does NOT catch errors in event handlers or async code.
 * Use try/catch or mutation error states for those.
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[ErrorBoundary]", error, info);
    this.props.onError?.(error, info);
  }

  private handleRetry = () => {
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      // Still offline — do nothing; the user will see the offline message
      return;
    }
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      const offline = isNetworkError(this.state.error);

      return (
        <div className="flex flex-col items-center justify-center rounded-card border border-border bg-bg-surface p-8 text-center">
          {offline ? (
            <>
              <WifiOff size={24} className="mb-2 text-alert" />
              <p className="text-sm font-medium text-text-primary">
                Check your connection
              </p>
              <p className="mt-1 font-mono text-xs text-text-muted">
                You appear to be offline. Reconnect and try again.
              </p>
            </>
          ) : (
            <>
              <p className="text-sm font-medium text-text-primary">
                Something went wrong
              </p>
              <p className="mt-1 font-mono text-xs text-text-muted">
                {this.state.error?.message ?? "An unexpected error occurred"}
              </p>
            </>
          )}
          <button
            onClick={this.handleRetry}
            className="mt-4 rounded-control border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            {offline ? "Retry when online" : "Try again"}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
