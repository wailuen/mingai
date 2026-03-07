"use client";

import { useState, useCallback } from "react";
import { X, Upload, Download, CheckCircle2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { useImportGlossary, type ImportResult } from "@/lib/hooks/useGlossary";

interface BulkImportDialogProps {
  onClose: () => void;
}

interface ParsedRow {
  term: string;
  full_form: string;
  definition: string;
  aliases: string;
  valid: boolean;
  error: string;
}

type ImportStep = "upload" | "preview" | "result";

function parseCSV(text: string): ParsedRow[] {
  const lines = text.trim().split("\n");
  const rows: ParsedRow[] = [];

  // Skip header row
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;

    // Simple CSV split (handles basic cases without quoted commas)
    const parts = line.split(",").map((s) => s.trim());
    const term = parts[0] ?? "";
    const full_form = parts[1] ?? "";
    const definition = parts[2] ?? "";
    const aliases = parts[3] ?? "";

    let valid = true;
    let error = "";

    if (!term) {
      valid = false;
      error = "Term is required";
    } else if (!definition) {
      valid = false;
      error = "Definition is required";
    } else if (definition.length > 200) {
      valid = false;
      error = "Definition exceeds 200 characters";
    }

    rows.push({ term, full_form, definition, aliases, valid, error });
  }

  return rows;
}

function downloadTemplate() {
  const header = "term,full_form,definition,aliases";
  const example1 =
    "API,Application Programming Interface,A set of protocols for building software,REST API;Web API";
  const example2 =
    "SLA,Service Level Agreement,A commitment between a service provider and a client,";
  const content = [header, example1, example2].join("\n");
  const blob = new Blob([content], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "glossary_template.csv";
  link.click();
  URL.revokeObjectURL(url);
}

export function BulkImportDialog({ onClose }: BulkImportDialogProps) {
  const [step, setStep] = useState<ImportStep>("upload");
  const [parsedRows, setParsedRows] = useState<ParsedRow[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const importMutation = useImportGlossary();

  const validCount = parsedRows.filter((r) => r.valid).length;
  const invalidCount = parsedRows.filter((r) => !r.valid).length;

  const handleFile = useCallback((file: File) => {
    setSelectedFile(file);
    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      const rows = parseCSV(text);
      setParsedRows(rows);
      setStep("preview");
    };
    reader.readAsText(file);
  }, []);

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file?.name.endsWith(".csv")) {
      handleFile(file);
    }
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(true);
  }

  function handleDragLeave() {
    setDragOver(false);
  }

  async function handleImport() {
    if (!selectedFile) return;

    try {
      const importResult = await importMutation.mutateAsync(selectedFile);
      setResult(importResult);
      setStep("result");
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : "Import failed";
      setResult({
        imported: 0,
        skipped: 0,
        errors: [errorMessage],
      });
      setStep("result");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-[640px] rounded-card border border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Import Glossary Terms
            </h2>
            <p className="mt-0.5 text-xs text-text-faint">
              {step === "upload" && "Step 1 of 3 \u2014 Upload CSV file"}
              {step === "preview" && "Step 2 of 3 \u2014 Review and confirm"}
              {step === "result" && "Step 3 of 3 \u2014 Import complete"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Progress bar */}
        <div className="h-1 w-full bg-bg-elevated">
          <div
            className="h-full bg-accent transition-all"
            style={{
              width:
                step === "upload" ? "33%" : step === "preview" ? "66%" : "100%",
            }}
          />
        </div>

        <div className="p-5">
          {/* Step 1: Upload */}
          {step === "upload" && (
            <div className="space-y-4">
              <label
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                className={cn(
                  "block cursor-pointer rounded-card border border-dashed px-4 py-10 text-center transition-colors",
                  dragOver
                    ? "border-accent bg-accent-dim"
                    : "border-border hover:border-accent-ring hover:bg-bg-elevated",
                )}
              >
                <Upload
                  size={24}
                  className={cn(
                    "mx-auto mb-3",
                    dragOver ? "text-accent" : "text-text-faint",
                  )}
                />
                <p className="text-sm text-text-muted">
                  Drop a CSV file here, or click to browse
                </p>
                <p className="mt-1 text-xs text-text-faint">
                  Accepts .csv files only
                </p>
                <input
                  type="file"
                  accept=".csv"
                  className="hidden"
                  onChange={handleFileInput}
                />
              </label>

              <div className="flex items-center justify-between rounded-control border border-border-faint bg-bg-elevated px-3 py-2">
                <span className="text-xs text-text-faint">
                  CSV format: term, full_form, definition, aliases
                </span>
                <button
                  type="button"
                  onClick={downloadTemplate}
                  className="flex items-center gap-1 text-xs text-accent transition-opacity hover:opacity-80"
                >
                  <Download size={12} />
                  Download template
                </button>
              </div>
            </div>
          )}

          {/* Step 2: Preview */}
          {step === "preview" && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <span className="font-mono text-xs text-accent">
                  {validCount} valid
                </span>
                {invalidCount > 0 && (
                  <span className="font-mono text-xs text-alert">
                    {invalidCount} invalid
                  </span>
                )}
                <span className="text-xs text-text-faint">
                  Showing first {Math.min(parsedRows.length, 5)} of{" "}
                  {parsedRows.length} rows
                </span>
              </div>

              <div className="max-h-56 overflow-y-auto rounded-card border border-border">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                        Term
                      </th>
                      <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                        Full Form
                      </th>
                      <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                        Definition
                      </th>
                      <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                        Status
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {parsedRows.slice(0, 5).map((row, i) => (
                      <tr key={i} className="border-b border-border-faint">
                        <td className="px-3 py-1.5 text-sm text-text-primary">
                          {row.term || "\u2014"}
                        </td>
                        <td className="px-3 py-1.5 text-sm text-text-muted">
                          {row.full_form || "\u2014"}
                        </td>
                        <td className="max-w-[200px] truncate px-3 py-1.5 text-sm text-text-muted">
                          {row.definition || "\u2014"}
                        </td>
                        <td className="px-3 py-1.5 text-xs">
                          {row.valid ? (
                            <span className="text-accent">Valid</span>
                          ) : (
                            <span className="text-alert">{row.error}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Step 3: Result */}
          {step === "result" && result && (
            <div className="space-y-4 py-4 text-center">
              {result.imported > 0 ? (
                <CheckCircle2 size={40} className="mx-auto text-accent" />
              ) : (
                <AlertCircle size={40} className="mx-auto text-alert" />
              )}

              <div className="space-y-1">
                <p className="text-sm text-text-primary">
                  <span className="font-mono text-accent">
                    {result.imported}
                  </span>{" "}
                  terms imported
                </p>
                {result.skipped > 0 && (
                  <p className="text-sm text-text-muted">
                    <span className="font-mono">{result.skipped}</span> skipped
                    (duplicates)
                  </p>
                )}
              </div>

              {result.errors.length > 0 && (
                <div className="mx-auto max-w-md rounded-control border border-alert/30 bg-alert-dim p-3 text-left">
                  <p className="mb-1 text-xs font-medium text-alert">Errors:</p>
                  <ul className="space-y-0.5">
                    {result.errors.map((err, i) => (
                      <li key={i} className="text-xs text-alert">
                        {err}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
          {step === "upload" && (
            <button
              onClick={onClose}
              className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
            >
              Cancel
            </button>
          )}

          {step === "preview" && (
            <>
              <button
                onClick={() => {
                  setStep("upload");
                  setParsedRows([]);
                  setSelectedFile(null);
                }}
                className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
              >
                Back
              </button>
              <button
                onClick={handleImport}
                disabled={validCount === 0 || importMutation.isPending}
                className="rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
              >
                {importMutation.isPending
                  ? "Importing..."
                  : `Import ${validCount} Term${validCount !== 1 ? "s" : ""}`}
              </button>
            </>
          )}

          {step === "result" && (
            <button
              onClick={onClose}
              className="rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
            >
              Close
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
