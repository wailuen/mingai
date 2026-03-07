"use client";

import { useState, useCallback } from "react";
import { Upload, X } from "lucide-react";

const MAX_FILE_SIZE = 2 * 1024 * 1024; // 2MB
const ACCEPTED_TYPES = ["image/png", "image/svg+xml", "image/jpeg"];

interface LogoUploadProps {
  currentLogo: string | null;
  onLogoChange: (file: File | null) => void;
}

/**
 * Drag-and-drop + file picker for workspace logo.
 * Accepts PNG/SVG/JPEG, max 2MB.
 * Shows preview after selection.
 */
export function LogoUpload({ currentLogo, onLogoChange }: LogoUploadProps) {
  const [preview, setPreview] = useState<string | null>(currentLogo);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const processFile = useCallback(
    (file: File) => {
      setError(null);

      if (!ACCEPTED_TYPES.includes(file.type)) {
        setError("Only PNG, SVG, and JPEG files are accepted");
        return;
      }

      if (file.size > MAX_FILE_SIZE) {
        setError("File must be smaller than 2MB");
        return;
      }

      const url = URL.createObjectURL(file);
      setPreview(url);
      onLogoChange(file);
    },
    [onLogoChange],
  );

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) processFile(file);
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) processFile(file);
  }

  function handleRemove() {
    setPreview(null);
    setError(null);
    onLogoChange(null);
  }

  return (
    <div>
      {preview ? (
        <div className="flex items-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-card border border-border bg-bg-elevated">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={preview}
              alt="Workspace logo"
              className="h-full w-full object-contain"
            />
          </div>
          <button
            onClick={handleRemove}
            className="flex items-center gap-1 text-sm text-text-faint transition-colors hover:text-alert"
          >
            <X size={14} />
            Remove
          </button>
        </div>
      ) : (
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={`block cursor-pointer rounded-card border border-dashed px-4 py-8 text-center transition-colors ${
            dragOver
              ? "border-accent bg-accent-dim"
              : "border-border hover:border-accent-ring hover:bg-bg-elevated"
          }`}
        >
          <Upload size={20} className="mx-auto mb-2 text-text-faint" />
          <span className="block text-sm text-text-muted">
            Drop logo here or click to browse
          </span>
          <span className="block text-xs text-text-faint">
            PNG, SVG, or JPEG - max 2MB
          </span>
          <input
            type="file"
            accept=".png,.svg,.jpeg,.jpg"
            className="hidden"
            onChange={handleFileInput}
          />
        </label>
      )}

      {error && <p className="mt-2 text-xs text-alert">{error}</p>}
    </div>
  );
}
