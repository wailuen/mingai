"use client";

import { useEffect, useRef } from "react";

/**
 * Attaches an IntersectionObserver to a sentinel element.
 * When the sentinel enters the viewport, calls `onIntersect` (e.g. fetchNextPage).
 * Returns a ref to attach to the sentinel div.
 */
export function useInfiniteScrollSentinel(
  onIntersect: () => void,
  enabled = true,
) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const el = sentinelRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          onIntersect();
        }
      },
      { threshold: 0.1 },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [onIntersect, enabled]);

  return sentinelRef;
}
