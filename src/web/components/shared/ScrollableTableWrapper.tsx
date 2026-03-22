"use client";

import { type ReactNode, forwardRef } from "react";
import { cn } from "@/lib/utils";

interface ScrollableTableWrapperProps {
  children: ReactNode;
  /** Extra content rendered below the table (e.g. count bar, pagination info). */
  footer?: ReactNode;
  className?: string;
  /**
   * CSS max-height for the scroll area.
   * Defaults to fill the visible viewport below the topbar and typical page chrome.
   * Override per-table when the surrounding layout differs.
   */
  maxHeight?: string;
}

/**
 * Wraps any <table> in a responsive, scrollable container:
 * - Horizontal scroll: overflow-x-auto
 * - Vertical scroll: overflow-y-auto capped at maxHeight
 * - Sticky thead: thead cells must carry `sticky top-0 z-10 bg-bg-surface`
 * - Optional fixed footer pinned below the scroll area
 *
 * Usage:
 *   <ScrollableTableWrapper footer={<CountBar />}>
 *     <table>...</table>
 *   </ScrollableTableWrapper>
 */
export const ScrollableTableWrapper = forwardRef<
  HTMLDivElement,
  ScrollableTableWrapperProps
>(function ScrollableTableWrapper(
  {
    children,
    footer,
    className,
    maxHeight = "calc(100svh - var(--topbar-h, 48px) - 180px)",
  },
  ref,
) {
  return (
    <div
      className={cn(
        "flex flex-col rounded-card border border-border bg-bg-surface",
        className,
      )}
    >
      {/* Scrollable body — both axes */}
      <div
        ref={ref}
        className="min-h-0 flex-1 overflow-x-auto overflow-y-auto"
        style={{ maxHeight }}
      >
        {children}
      </div>

      {/* Footer: count bar, load-more indicator, etc. */}
      {footer && (
        <div className="flex-none border-t border-border">{footer}</div>
      )}
    </div>
  );
});
