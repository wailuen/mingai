"use client";

interface StepWelcomeProps {
  onNext: () => void;
}

const PRODUCT_NAME = "mingai";

export function StepWelcome({ onNext }: StepWelcomeProps) {
  return (
    <div className="flex flex-col items-center py-8 text-center">
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-card bg-accent-dim">
        <span className="text-2xl font-bold text-accent">m</span>
      </div>

      <h2 className="text-page-title text-text-primary">
        Welcome to {PRODUCT_NAME}
      </h2>
      <p className="mt-2 max-w-md text-body-default leading-relaxed text-text-muted">
        Your AI-powered workspace for intelligent document retrieval,
        multi-agent collaboration, and streamlined workflows. Let us help you
        get set up.
      </p>

      <button
        onClick={onNext}
        className="mt-8 rounded-control bg-accent px-6 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
      >
        Let&apos;s get started
      </button>
    </div>
  );
}
