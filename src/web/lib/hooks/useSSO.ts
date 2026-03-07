"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

export interface SAMLConfig {
  entity_id: string;
  acs_url: string;
  metadata_url: string;
}

export interface OIDCConfig {
  client_id: string;
  discovery_url: string;
  client_secret_ref: string;
}

export interface SSOConfig {
  provider: "saml" | "oidc" | null;
  status: "configured" | "not_configured" | "error";
  saml?: SAMLConfig;
  oidc?: OIDCConfig;
}

export interface SSOTestResult {
  success: boolean;
  message: string;
}

const SSO_KEY = "sso-config";

export function useSSOConfig() {
  return useQuery({
    queryKey: [SSO_KEY],
    queryFn: () => apiGet<SSOConfig>("/api/v1/admin/sso"),
  });
}

export function useSaveSSOConfig() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (config: {
      provider: "saml" | "oidc";
      saml?: SAMLConfig;
      oidc?: OIDCConfig;
    }) => apiPost<SSOConfig>("/api/v1/admin/sso", config),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [SSO_KEY] });
    },
  });
}

export function useTestSSOConnection() {
  return useMutation({
    mutationFn: (config: {
      provider: "saml" | "oidc";
      saml?: SAMLConfig;
      oidc?: OIDCConfig;
    }) => apiPost<SSOTestResult>("/api/v1/admin/sso/test", config),
  });
}
