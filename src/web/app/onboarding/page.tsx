"use client";

import { OnboardingWizard } from "./elements/OnboardingWizard";

/**
 * FE-038: Onboarding page.
 * Full-screen overlay displayed when onboarding_complete = false.
 * Orchestrator only -- step logic lives in elements/.
 */
export default function OnboardingPage() {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-base">
      <OnboardingWizard />
    </div>
  );
}
