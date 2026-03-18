"use client";

import { useState, useCallback } from "react";
import { getStoredToken } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

interface UploadDocumentResult {
  conversation_id: string;
  file_name: string;
  chunks_indexed: number;
  index_id: string;
}

interface UseUploadDocumentReturn {
  upload: (conversationId: string, file: File) => Promise<UploadDocumentResult>;
  uploading: boolean;
  progress: number; // 0–100
  error: string | null;
  result: UploadDocumentResult | null;
  reset: () => void;
}

const ERROR_MAP: Record<number, string> = {
  413: "File too large (max 20 MB)",
  422: "Unsupported file type. Accepted: PDF, DOCX, PPTX, TXT",
  404: "Conversation not found",
  403: "You do not have permission to upload to this conversation",
};

export function useUploadDocument(): UseUploadDocumentReturn {
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadDocumentResult | null>(null);

  const upload = useCallback(
    async (
      conversationId: string,
      file: File,
    ): Promise<UploadDocumentResult> => {
      setUploading(true);
      setProgress(0);
      setError(null);
      setResult(null);

      const token = getStoredToken();
      const formData = new FormData();
      formData.append("file", file);

      try {
        setProgress(30);
        // Use raw fetch (NOT apiGet/apiPost) — apiPost forces Content-Type: application/json
        // which breaks multipart/form-data boundary. Let browser set boundary automatically.
        const res = await fetch(
          `${API_URL}/api/v1/conversations/${conversationId}/documents`,
          {
            method: "POST",
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            body: formData,
          },
        );
        setProgress(80);

        if (!res.ok) {
          let detail = ERROR_MAP[res.status];
          if (!detail) {
            try {
              const body = await res.json();
              detail =
                body.detail ?? body.message ?? `Upload failed (${res.status})`;
            } catch {
              detail = `Upload failed (${res.status})`;
            }
          }
          setError(detail);
          setUploading(false);
          setProgress(0);
          throw new Error(detail);
        }

        const data: UploadDocumentResult = await res.json();
        setProgress(100);
        setResult(data);
        setUploading(false);
        return data;
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Upload failed";
        // Only set error if not already set above
        setError((prev) => prev ?? msg);
        setUploading(false);
        setProgress(0);
        throw err;
      }
    },
    [],
  );

  const reset = useCallback(() => {
    setUploading(false);
    setProgress(0);
    setError(null);
    setResult(null);
  }, []);

  return { upload, uploading, progress, error, result, reset };
}
