"use client";

import { useState } from "react";
import { useSkipOnboardingStep } from "@/lib/hooks/useOnboarding";
import { StepWelcome } from "./StepWelcome";
import { StepProfile } from "./StepProfile";
import { StepKnowledgeBase } from "./StepKnowledgeBase";
import { StepAgents } from "./StepAgents";
import { StepInvite } from "./StepInvite";
import { StepComplete } from "./StepComplete";

const TOTAL_STEPS = 6;

const STEP_NAMES = [
  "welcome",
  "profile",
  "knowledge_base",
  "agents",
  "invite",
  "complete",
] as const;

/**
 * FE-038: 6-step onboarding wizard.
 * Orchestrates step navigation and skip tracking.
 */
export function OnboardingWizard() {
  const [currentStep, setCurrentStep] = useState(1);
  const skipMutation = useSkipOnboardingStep();

  function goNext() {
    if (currentStep < TOTAL_STEPS) setCurrentStep((s) => s + 1);
  }

  function goBack() {
    if (currentStep > 1) setCurrentStep((s) => s - 1);
  }

  function handleSkip() {
    const stepName = STEP_NAMES[currentStep - 1];
    skipMutation.mutate(stepName);
    goNext();
  }

  const progressPercent = (currentStep / TOTAL_STEPS) * 100;

  return (
    <div className="mx-auto w-full max-w-[680px] rounded-card border border-border bg-bg-surface">
      {/* Progress bar */}
      <div className="h-1 w-full overflow-hidden rounded-t-card bg-bg-elevated">
        <div
          className="h-full bg-accent transition-all duration-200"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      {/* Step label */}
      {currentStep < TOTAL_STEPS && (
        <div className="px-6 pt-4">
          <p className="text-[11px] text-text-faint">
            Step {currentStep} of {TOTAL_STEPS}
          </p>
        </div>
      )}

      {/* Step content */}
      <div className="px-6 pb-6">
        {currentStep === 1 && <StepWelcome onNext={goNext} />}
        {currentStep === 2 && <StepProfile onNext={goNext} onBack={goBack} />}
        {currentStep === 3 && (
          <StepKnowledgeBase
            onNext={goNext}
            onBack={goBack}
            onSkip={handleSkip}
          />
        )}
        {currentStep === 4 && (
          <StepAgents onNext={goNext} onBack={goBack} onSkip={handleSkip} />
        )}
        {currentStep === 5 && (
          <StepInvite onNext={goNext} onBack={goBack} onSkip={handleSkip} />
        )}
        {currentStep === 6 && <StepComplete onBack={goBack} />}
      </div>
    </div>
  );
}
