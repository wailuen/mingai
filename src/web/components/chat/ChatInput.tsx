"use client";

import { useState, useRef, useCallback, type KeyboardEvent } from "react";
import { ArrowUp, Paperclip, ChevronDown } from "lucide-react";

interface ChatInputProps {
  onSend: (message: string, mode: string) => void;
  disabled?: boolean;
  placeholder?: string;
  showModeSelector?: boolean;
}

const MODES = [
  { id: "auto", label: "Auto" },
  { id: "research", label: "Research" },
];

export function ChatInput({
  onSend,
  disabled = false,
  placeholder = "Ask anything...",
  showModeSelector = true,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState("auto");
  const [showModes, setShowModes] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed, mode);
    setValue("");
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
    }
  }, [value, disabled, onSend]);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleInput() {
    const el = inputRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }
  }

  const activeMode = MODES.find((m) => m.id === mode);

  return (
    <div className="flex items-end gap-2 rounded-card border border-border bg-bg-surface px-3 py-2">
      {showModeSelector && (
        <div className="relative flex-shrink-0">
          <button
            onClick={() => setShowModes(!showModes)}
            className="flex items-center gap-1 rounded-control border border-border px-2.5 py-1.5 text-xs text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
          >
            {activeMode?.label}
            <ChevronDown size={12} />
          </button>
          {showModes && (
            <div className="absolute bottom-full left-0 mb-1 rounded-card border border-border bg-bg-surface p-1 shadow-lg">
              {MODES.map((m) => (
                <button
                  key={m.id}
                  onClick={() => {
                    setMode(m.id);
                    setShowModes(false);
                  }}
                  className="flex w-full items-center rounded-control px-3 py-1.5 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
                >
                  {m.id === "research" && (
                    <span className="mr-1.5 text-accent">Q</span>
                  )}
                  {m.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Attach button */}
      <button
        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-control text-text-faint transition-colors hover:text-text-muted"
        aria-label="Attach file"
      >
        <Paperclip size={16} />
      </button>

      {/* Text input */}
      <textarea
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
        placeholder={placeholder}
        disabled={disabled}
        rows={1}
        className="max-h-40 min-h-[36px] flex-1 resize-none bg-transparent text-sm text-text-primary placeholder:text-text-faint focus:outline-none"
      />

      {/* Send button */}
      <button
        onClick={handleSend}
        disabled={!value.trim() || disabled}
        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-control bg-accent text-bg-base transition-opacity disabled:opacity-30"
        aria-label="Send message"
      >
        <ArrowUp size={16} />
      </button>
    </div>
  );
}
