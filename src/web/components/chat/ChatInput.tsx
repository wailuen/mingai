"use client";

import { useState, useRef, useCallback, type KeyboardEvent } from "react";
import {
  ArrowUp,
  Paperclip,
  ChevronDown,
  FileText,
  X,
  Loader2,
} from "lucide-react";
import { useUploadDocument } from "@/hooks/useUploadDocument";

interface ChatInputProps {
  onSend: (message: string, mode: string) => void;
  disabled?: boolean;
  placeholder?: string;
  showModeSelector?: boolean;
  /** Conversation ID for document upload. Upload button is disabled without it. */
  conversationId?: string | null;
  /** Whether the chat stream is currently active (prevents upload during streaming) */
  isStreaming?: boolean;
}

const MODES = [
  { id: "auto", label: "Auto" },
  { id: "research", label: "Research" },
];

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".pptx", ".txt"];
const MAX_BYTES = 20 * 1024 * 1024; // 20 MB

export function ChatInput({
  onSend,
  disabled = false,
  placeholder = "Ask anything...",
  showModeSelector = true,
  conversationId,
  isStreaming = false,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState("auto");
  const [showModes, setShowModes] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const {
    upload,
    uploading,
    progress,
    result: uploadResult,
    reset: resetUpload,
  } = useUploadDocument();

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed, mode);
    setValue("");
    resetUpload(); // clear success chip on send
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
    }
  }, [value, disabled, onSend, mode, resetUpload]);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
    // Clear upload error on next keypress
    if (uploadError) setUploadError(null);
  }

  function handleInput() {
    const el = inputRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }
  }

  function handleAttachClick() {
    if (!conversationId) {
      if (isStreaming) {
        setUploadError("Please wait for the response before attaching a file");
      } else {
        setUploadError("Send your first message before attaching a file");
      }
      return;
    }
    setUploadError(null);
    fileInputRef.current?.click();
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    // Reset the file input so the same file can be re-selected
    e.target.value = "";

    // Client-side validation
    if (file.size > MAX_BYTES) {
      setUploadError("File too large (max 20 MB)");
      return;
    }
    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      setUploadError("Unsupported file type. Accepted: PDF, DOCX, PPTX, TXT");
      return;
    }

    setUploadError(null);

    if (!conversationId) return; // guard (already checked above)

    try {
      await upload(conversationId, file);
    } catch (err) {
      // Surface the hook's error message via uploadError
      const msg = err instanceof Error ? err.message : "Upload failed";
      setUploadError(msg);
    }
  }

  const activeMode = MODES.find((m) => m.id === mode);
  const uploadDisabled = disabled || uploading || isStreaming;

  return (
    <div className="flex flex-col gap-1.5">
      {/* Success chip — shows uploaded file name and chunk count */}
      {uploadResult && (
        <div className="flex items-center gap-1.5 rounded-control border border-border bg-bg-elevated px-2 py-1 text-xs text-text-muted w-fit">
          <FileText size={12} className="flex-shrink-0 text-accent" />
          <span className="truncate max-w-[200px]">
            {uploadResult.file_name}
          </span>
          <span className="font-mono text-text-faint">
            {uploadResult.chunks_indexed} chunks
          </span>
          <button
            onClick={resetUpload}
            className="ml-0.5 text-text-faint transition-colors hover:text-alert"
            aria-label="Remove attachment"
          >
            <X size={10} />
          </button>
        </div>
      )}

      {/* Upload progress bar */}
      {uploading && (
        <div className="h-0.5 w-full overflow-hidden rounded-full bg-bg-elevated">
          <div
            className="h-full rounded-full bg-accent transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}

      {/* Error message (client-side or server-side) */}
      {uploadError && <p className="text-xs text-alert">{uploadError}</p>}

      {/* Main input row */}
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

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="hidden"
          onChange={handleFileChange}
          aria-hidden="true"
        />

        {/* Attach button */}
        <button
          onClick={handleAttachClick}
          disabled={uploadDisabled}
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-control text-text-faint transition-colors hover:text-text-muted disabled:cursor-not-allowed disabled:opacity-40"
          aria-label={uploading ? "Uploading..." : "Attach file"}
          title={
            !conversationId
              ? isStreaming
                ? "Please wait for the response"
                : "Send a message first"
              : "Attach a file (PDF, DOCX, PPTX, TXT)"
          }
        >
          {uploading ? (
            <Loader2 size={16} className="animate-spin text-accent" />
          ) : (
            <Paperclip size={16} />
          )}
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
    </div>
  );
}
