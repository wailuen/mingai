"use client";

import { sanitize } from "@/lib/sanitize";

interface SafeHTMLProps {
  /** Raw HTML string to sanitize and render */
  html: string;
  className?: string;
  /** HTML element to render as (default: "div") */
  as?: keyof JSX.IntrinsicElements;
}

/**
 * FE-062: XSS-safe HTML renderer.
 *
 * All user-generated HTML MUST go through this component.
 * Never use raw dangerouslySetInnerHTML elsewhere.
 *
 * Sanitization is handled by DOMPurify via @/lib/sanitize:
 * - Strips unsafe tags and event handlers
 * - Blocks javascript:/data: URIs
 * - Forces rel="noopener noreferrer" on links
 * - Server-side: strips all tags as safe fallback
 *
 * For plain text content, use React JSX text interpolation instead --
 * that is already XSS-safe and this component is not needed.
 */
export function SafeHTML({ html, className, as: Tag = "div" }: SafeHTMLProps) {
  const clean = sanitize(html);

  return (
    // biome-ignore lint/security/noDangerouslySetInnerHtml: content is sanitized via sanitize()
    <Tag className={className} dangerouslySetInnerHTML={{ __html: clean }} />
  );
}
