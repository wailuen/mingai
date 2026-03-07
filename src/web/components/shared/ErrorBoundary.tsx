"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

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
 * FE-063: Error boundary wrapper.
 *
 * Place around any section that might fail (data-fetching components,
 * chat rendering, SSE-driven components).
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

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex flex-col items-center justify-center rounded-card border border-border bg-bg-surface p-8 text-center">
          <p className="text-sm font-medium text-text-primary">
            Something went wrong
          </p>
          <p className="mt-1 font-mono text-xs text-text-muted">
            {this.state.error?.message ?? "An unexpected error occurred"}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="mt-4 rounded-control border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
