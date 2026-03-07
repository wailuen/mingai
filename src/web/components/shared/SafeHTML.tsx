"use client";

import DOMPurify from "dompurify";

interface SafeHTMLProps {
  html: string;
  className?: string;
}

/**
 * XSS-safe HTML renderer. All user-generated HTML MUST go through this component.
 * Never use raw dangerouslySetInnerHTML.
 */
export function SafeHTML({ html, className }: SafeHTMLProps) {
  const clean = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      "p",
      "strong",
      "em",
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
    ],
    ALLOWED_ATTR: ["href", "target", "rel", "class"],
  });

  return (
    <div className={className} dangerouslySetInnerHTML={{ __html: clean }} />
  );
}
