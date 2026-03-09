"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";

export interface GlossaryExpansionApplied {
  term: string;
  expansion: string;
}

interface TermsInterpretedProps {
  expansions: GlossaryExpansionApplied[];
}

/**
 * AI-029: Shows "N terms interpreted" indicator below AI response text.
 * Collapsed by default; click to expand the full term -> expansion list.
 */
export function TermsInterpreted({ expansions }: TermsInterpretedProps) {
  const [expanded, setExpanded] = useState(false);

  if (expansions.length === 0) return null;

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex items-center gap-1 text-[11px] text-text-faint transition-colors hover:text-text-muted"
      >
        <ChevronRight
          size={12}
          className={`transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
        />
        <span>
          <span className="font-mono">{expansions.length}</span> term{expansions.length !== 1 ? "s" : ""} interpreted
        </span>
      </button>

      {expanded && (
        <ul className="mt-1.5 space-y-0.5 pl-4">
          {expansions.map((exp) => (
            <li key={exp.term} className="font-mono text-xs">
              <span className="text-text-muted">{exp.term}</span>
              <span className="mx-1.5 text-text-faint">&rarr;</span>
              <span className="text-text-muted">{exp.expansion}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
