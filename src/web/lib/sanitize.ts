"use client";

import DOMPurify from "dompurify";

/**
 * Allowed HTML tags for user-generated content (chat messages,
 * markdown output, rich descriptions). Anything not listed is stripped.
 */
const ALLOWED_TAGS = [
  "p",
  "strong",
  "em",
  "b",
  "i",
  "ul",
  "ol",
  "li",
  "br",
  "code",
  "pre",
  "a",
  "h1",
  "h2",
  "h3",
  "h4",
  "blockquote",
  "table",
  "thead",
  "tbody",
  "tr",
  "th",
  "td",
];

const ALLOWED_ATTR = ["href", "target", "rel", "class", "title"];

// Register the link-safety hook once at module load (not per-call) to prevent
// hook stacking when sanitize() is called concurrently from multiple renders.
if (typeof window !== "undefined") {
  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A") {
      node.setAttribute("rel", "noopener noreferrer");
      node.setAttribute("target", "_blank");
    }
  });
}

/**
 * Sanitize an HTML string to prevent XSS.
 *
 * - Strips all tags not in ALLOWED_TAGS
 * - Strips all attributes not in ALLOWED_ATTR
 * - Blocks javascript:/data:/vbscript: URIs (DOMPurify default)
 * - Forces rel="noopener noreferrer" and target="_blank" on <a> tags
 * - Server-side: strips ALL tags as a safe fallback
 *
 * Usage:
 *   import { sanitize } from "@/lib/sanitize";
 *   const clean = sanitize(userHtml);
 */
export function sanitize(html: string): string {
  if (typeof window === "undefined") {
    // Server-side: strip all tags (safe fallback, no DOM available)
    return html.replace(/<[^>]*>/g, "");
  }

  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
  });
}
