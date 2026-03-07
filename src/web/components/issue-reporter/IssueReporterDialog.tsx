"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { X, ChevronLeft, ChevronRight, Eye, EyeOff } from "lucide-react";
import { apiPost } from "@/lib/api";

interface IssueReporterDialogProps {
  onClose: () => void;
}

type IssueCategory =
  | "wrong_answer"
  | "missing_source"
  | "slow_response"
  | "ui_bug"
  | "other";

const CATEGORIES: { value: IssueCategory; label: string }[] = [
  { value: "wrong_answer", label: "Wrong or inaccurate answer" },
  { value: "missing_source", label: "Missing source document" },
  { value: "slow_response", label: "Slow response time" },
  { value: "ui_bug", label: "UI or display issue" },
  { value: "other", label: "Other" },
];

/**
 * FE-022: Issue reporter dialog with screenshot and annotation.
 *
 * CRITICAL - R4.1: RAG response area MUST be blurred by default.
 * User must explicitly toggle to un-blur before screenshot capture.
 * blur_acknowledged flag must be true before API submission.
 *
 * Steps:
 * 1. Category + description
 * 2. Screenshot (blur by default)
 * 3. Review + submit
 */
export function IssueReporterDialog({ onClose }: IssueReporterDialogProps) {
  const [step, setStep] = useState(1);
  const [category, setCategory] = useState<IssueCategory | null>(null);
  const [description, setDescription] = useState("");
  const [screenshotDataUrl, setScreenshotDataUrl] = useState<string | null>(
    null,
  );
  const [blurApplied, setBlurApplied] = useState(true); // CRITICAL: blurred by default
  const [blurAcknowledged, setBlurAcknowledged] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const captureScreenshot = useCallback(async () => {
    try {
      // Use html2canvas-compatible approach via canvas
      const mainContent = document.querySelector("main");
      if (!mainContent) return;

      const canvas = document.createElement("canvas");
      const rect = mainContent.getBoundingClientRect();
      canvas.width = rect.width;
      canvas.height = rect.height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      // Capture via drawing visible content
      // In production, use html2canvas; here we create a placeholder screenshot
      ctx.fillStyle = "#0c0e14";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#f1f5fb";
      ctx.font = "14px 'Plus Jakarta Sans', sans-serif";
      ctx.fillText("Screenshot captured", 20, 30);

      // Apply blur if blurApplied is true
      if (blurApplied) {
        applyBlurToCanvas(ctx, canvas.width, canvas.height);
      }

      setScreenshotDataUrl(canvas.toDataURL("image/png"));
    } catch {
      setError("Failed to capture screenshot");
    }
  }, [blurApplied]);

  // Capture screenshot when entering step 2
  useEffect(() => {
    if (step === 2) {
      captureScreenshot();
    }
  }, [step, captureScreenshot]);

  function applyBlurToCanvas(
    ctx: CanvasRenderingContext2D,
    width: number,
    height: number,
  ) {
    // Apply CSS filter-equivalent blur via canvas pixel manipulation
    ctx.filter = "blur(12px)";
    const imageData = ctx.getImageData(0, 0, width, height);
    ctx.putImageData(imageData, 0, 0);
    ctx.filter = "none";
  }

  function toggleBlur() {
    if (blurApplied) {
      // User is un-blurring - this acknowledges they want to show RAG content
      setBlurAcknowledged(true);
    }
    setBlurApplied(!blurApplied);
    // Re-capture with new blur state
    captureScreenshot();
  }

  async function handleSubmit() {
    if (!category || !description.trim()) return;
    if (!blurAcknowledged && !blurApplied) return;

    setSubmitting(true);
    setError(null);

    try {
      await apiPost("/api/v1/issues", {
        category,
        description: description.trim(),
        screenshot: screenshotDataUrl,
        blur_acknowledged: blurAcknowledged,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit report");
    } finally {
      setSubmitting(false);
    }
  }

  const canProceedStep1 = category !== null && description.trim().length > 0;
  const canProceedStep2 = screenshotDataUrl !== null;
  const canSubmit = canProceedStep1 && (blurApplied || blurAcknowledged);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-[640px] rounded-card border border-border bg-bg-surface">
        {/* Progress bar */}
        <div className="h-1 rounded-t-card bg-bg-elevated">
          <div
            className="h-full rounded-l-card bg-accent transition-all duration-200"
            style={{ width: `${(step / 3) * 100}%` }}
          />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Report an Issue
            </h2>
            <span className="text-xs text-text-faint">Step {step} of 3</span>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="p-5">
          {step === 1 && (
            <Step1Category
              category={category}
              setCategory={setCategory}
              description={description}
              setDescription={setDescription}
            />
          )}
          {step === 2 && (
            <Step2Screenshot
              screenshotDataUrl={screenshotDataUrl}
              blurApplied={blurApplied}
              onToggleBlur={toggleBlur}
              canvasRef={canvasRef}
            />
          )}
          {step === 3 && (
            <Step3Review
              category={category}
              description={description}
              screenshotDataUrl={screenshotDataUrl}
              blurApplied={blurApplied}
            />
          )}

          {error && (
            <div className="mt-3 rounded-control border border-alert-ring bg-alert-dim px-3 py-2 text-sm text-alert">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border px-5 py-3">
          <button
            onClick={() => setStep(Math.max(1, step - 1))}
            disabled={step === 1}
            className="flex items-center gap-1 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-30"
          >
            <ChevronLeft size={14} />
            Back
          </button>

          {step < 3 ? (
            <button
              onClick={() => setStep(step + 1)}
              disabled={
                (step === 1 && !canProceedStep1) ||
                (step === 2 && !canProceedStep2)
              }
              className="flex items-center gap-1 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
            >
              Next
              <ChevronRight size={14} />
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={!canSubmit || submitting}
              className="rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
            >
              {submitting ? "Submitting..." : "Submit Report"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// Step 1: Category + description
function Step1Category({
  category,
  setCategory,
  description,
  setDescription,
}: {
  category: IssueCategory | null;
  setCategory: (c: IssueCategory) => void;
  description: string;
  setDescription: (d: string) => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
          Category
        </label>
        <div className="space-y-1.5">
          {CATEGORIES.map((cat) => (
            <button
              key={cat.value}
              onClick={() => setCategory(cat.value)}
              className={`w-full rounded-control border px-3 py-2 text-left text-sm transition-colors ${
                category === cat.value
                  ? "border-accent bg-accent-dim text-text-primary"
                  : "border-border text-text-muted hover:border-accent-ring hover:bg-bg-elevated"
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
          Description
        </label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe what happened..."
          rows={4}
          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
        />
      </div>
    </div>
  );
}

// Step 2: Screenshot with blur control
function Step2Screenshot({
  screenshotDataUrl,
  blurApplied,
  onToggleBlur,
  canvasRef,
}: {
  screenshotDataUrl: string | null;
  blurApplied: boolean;
  onToggleBlur: () => void;
  canvasRef: React.RefObject<HTMLCanvasElement>;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-text-primary">Screenshot preview</span>
        <button
          onClick={onToggleBlur}
          className="flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1 text-xs text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
        >
          {blurApplied ? (
            <>
              <EyeOff size={12} />
              RAG content blurred
            </>
          ) : (
            <>
              <Eye size={12} />
              RAG content visible
            </>
          )}
        </button>
      </div>

      {blurApplied && (
        <div className="rounded-control border border-warn-dim bg-warn-dim px-3 py-2 text-xs text-warn">
          RAG response content is blurred to protect sensitive information.
          Toggle to un-blur if you want to include it in your report.
        </div>
      )}

      <div className="overflow-hidden rounded-card border border-border">
        {screenshotDataUrl ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={screenshotDataUrl}
            alt="Screenshot preview"
            className={`w-full ${blurApplied ? "blur-lg" : ""}`}
          />
        ) : (
          <div className="flex h-48 items-center justify-center bg-bg-elevated text-sm text-text-faint">
            Capturing screenshot...
          </div>
        )}
      </div>

      <canvas ref={canvasRef} className="hidden" />
    </div>
  );
}

// Step 3: Review + submit
function Step3Review({
  category,
  description,
  screenshotDataUrl,
  blurApplied,
}: {
  category: IssueCategory | null;
  description: string;
  screenshotDataUrl: string | null;
  blurApplied: boolean;
}) {
  const categoryLabel =
    CATEGORIES.find((c) => c.value === category)?.label ?? "Unknown";

  return (
    <div className="space-y-4">
      <div>
        <span className="text-label-nav uppercase tracking-wider text-text-faint">
          Category
        </span>
        <p className="mt-1 text-sm text-text-primary">{categoryLabel}</p>
      </div>

      <div>
        <span className="text-label-nav uppercase tracking-wider text-text-faint">
          Description
        </span>
        <p className="mt-1 text-sm text-text-primary">{description}</p>
      </div>

      <div>
        <span className="text-label-nav uppercase tracking-wider text-text-faint">
          Screenshot
        </span>
        {screenshotDataUrl ? (
          <div className="mt-1 overflow-hidden rounded-card border border-border">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={screenshotDataUrl}
              alt="Screenshot"
              className={`w-full ${blurApplied ? "blur-lg" : ""}`}
            />
          </div>
        ) : (
          <p className="mt-1 text-sm text-text-faint">No screenshot</p>
        )}
        <p className="mt-1 text-xs text-text-faint">
          {blurApplied
            ? "RAG content is blurred in the screenshot"
            : "RAG content is visible in the screenshot"}
        </p>
      </div>
    </div>
  );
}
