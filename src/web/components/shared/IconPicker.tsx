"use client";

import {
  User,
  DollarSign,
  Scale,
  Monitor,
  Search,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { AgentIconType } from "@/lib/hooks/useCustomAgentStudio";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const ICON_OPTIONS: {
  value: AgentIconType;
  label: string;
  Icon: React.ElementType;
}[] = [
  { value: "hr", label: "HR", Icon: User },
  { value: "finance", label: "Finance", Icon: DollarSign },
  { value: "legal", label: "Legal", Icon: Scale },
  { value: "it", label: "IT", Icon: Monitor },
  { value: "search", label: "Search", Icon: Search },
  { value: "custom", label: "Custom", Icon: Sparkles },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface IconPickerProps {
  value: string;
  onChange: (icon: AgentIconType) => void;
}

export function IconPicker({ value, onChange }: IconPickerProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {ICON_OPTIONS.map(({ value: optValue, label, Icon }) => {
        const isSelected = value === optValue;
        return (
          <button
            key={optValue}
            type="button"
            onClick={() => onChange(optValue)}
            title={label}
            className={cn(
              "flex h-[52px] w-[52px] flex-col items-center justify-center gap-1 rounded-control border transition-colors",
              isSelected
                ? "border-accent bg-accent-dim text-accent"
                : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
            )}
          >
            <Icon size={18} />
            <span className="text-[10px] leading-none">{label}</span>
          </button>
        );
      })}
    </div>
  );
}
