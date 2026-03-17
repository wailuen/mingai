"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { getStoredToken } from "@/lib/auth";

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

// ---------------------------------------------------------------------------
// Admin SSO Config (P3AUTH-003) — enable/disable toggle
// Response: { provider_type, auth0_connection_id, enabled } or null
// ---------------------------------------------------------------------------

export type SSOProviderType = "entra" | "google" | "okta" | "saml" | "oidc";

export interface AdminSSOConfig {
  provider_type: SSOProviderType;
  auth0_connection_id: string;
  enabled: boolean;
}

const ADMIN_SSO_CONFIG_KEY = "admin-sso-config";

export function useAdminSSOConfig() {
  return useQuery({
    queryKey: [ADMIN_SSO_CONFIG_KEY],
    queryFn: () => apiGet<AdminSSOConfig | null>("/api/v1/admin/sso/config"),
  });
}

export function useUpdateAdminSSOConfig() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: Partial<AdminSSOConfig>) =>
      apiPatch<AdminSSOConfig>("/api/v1/admin/sso/config", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ADMIN_SSO_CONFIG_KEY] });
    },
  });
}

// ---------------------------------------------------------------------------
// Group Sync Config (P3AUTH-015)
// ---------------------------------------------------------------------------

export type GroupRole = "admin" | "editor" | "viewer" | "user";

export interface GroupSyncConfig {
  allowed_groups: string[];
  group_role_mapping: Record<string, GroupRole>;
}

const GROUP_SYNC_KEY = "group-sync-config";

export function useGroupSyncConfig() {
  return useQuery({
    queryKey: [GROUP_SYNC_KEY],
    queryFn: () =>
      apiGet<GroupSyncConfig>("/api/v1/admin/sso/group-sync/config"),
  });
}

export function useUpdateGroupSyncConfig() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: GroupSyncConfig) =>
      apiPatch<GroupSyncConfig>("/api/v1/admin/sso/group-sync/config", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [GROUP_SYNC_KEY] });
    },
  });
}

// ---------------------------------------------------------------------------
// P3AUTH-014: Provider-specific configure + test hooks
// ---------------------------------------------------------------------------

export interface SAMLConfigurePayload {
  metadata_url?: string;
  metadata_xml?: string;
}

export interface OIDCConfigurePayload {
  issuer: string;
  client_id: string;
  client_secret: string;
}

export interface GoogleConfigurePayload {
  client_id: string;
  client_secret: string;
}

export interface OktaConfigurePayload {
  okta_domain: string;
  client_id: string;
  client_secret: string;
}

export interface ConfigureResult {
  connection_id: string;
  provider_type: string;
  status: string;
}

export interface TestConnectionResult {
  test_url: string;
}

const SSO_WIZARD_KEY = "sso-wizard-config";

export function useConfigureSAML() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SAMLConfigurePayload) =>
      apiPost<ConfigureResult>("/api/v1/admin/sso/saml/configure", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ADMIN_SSO_CONFIG_KEY] });
      queryClient.invalidateQueries({ queryKey: [SSO_WIZARD_KEY] });
    },
  });
}

export function useTestSAMLConnection() {
  return useMutation({
    mutationFn: () =>
      apiPost<TestConnectionResult>("/api/v1/admin/sso/saml/test", {}),
  });
}

/**
 * Downloads the SP metadata XML as a blob.
 * Uses raw fetch because apiGet() calls .json() and cannot handle XML blobs.
 */
export async function fetchSAMLSPMetadata(): Promise<Blob> {
  const token = getStoredToken();
  const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "";
  const res = await fetch(`${baseUrl}/api/v1/admin/sso/saml/sp-metadata`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch SP metadata: ${res.status}`);
  }
  return res.blob();
}

export function useConfigureOIDC() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: OIDCConfigurePayload) =>
      apiPost<ConfigureResult>("/api/v1/admin/sso/oidc/configure", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ADMIN_SSO_CONFIG_KEY] });
      queryClient.invalidateQueries({ queryKey: [SSO_WIZARD_KEY] });
    },
  });
}

export function useTestOIDCConnection() {
  return useMutation({
    mutationFn: () =>
      apiPost<TestConnectionResult>("/api/v1/admin/sso/oidc/test", {}),
  });
}

export function useConfigureGoogle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: GoogleConfigurePayload) =>
      apiPost<ConfigureResult>("/api/v1/admin/sso/google/configure", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ADMIN_SSO_CONFIG_KEY] });
      queryClient.invalidateQueries({ queryKey: [SSO_WIZARD_KEY] });
    },
  });
}

export function useConfigureOkta() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: OktaConfigurePayload) =>
      apiPost<ConfigureResult>("/api/v1/admin/sso/okta/configure", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ADMIN_SSO_CONFIG_KEY] });
      queryClient.invalidateQueries({ queryKey: [SSO_WIZARD_KEY] });
    },
  });
}
