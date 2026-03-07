"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

export interface OnboardingStatus {
  completed: boolean;
  current_step: number;
  steps_completed: string[];
}

const ONBOARDING_KEY = "onboarding-status";

export function useOnboardingStatus() {
  return useQuery({
    queryKey: [ONBOARDING_KEY],
    queryFn: () => apiGet<OnboardingStatus>("/api/v1/users/onboarding"),
  });
}

export function useCompleteOnboarding() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      apiPost<{ completed: boolean }>("/api/v1/users/onboarding/complete", {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ONBOARDING_KEY] });
    },
  });
}

export function useSkipOnboardingStep() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (step: string) =>
      apiPost<OnboardingStatus>(
        `/api/v1/users/onboarding/skip/${encodeURIComponent(step)}`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ONBOARDING_KEY] });
    },
  });
}
