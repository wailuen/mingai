---
id: TODO-49
title: Frontend hooks — useTemplateCredentials, useCredentialHealth, and credential mutations
status: pending
priority: medium
phase: C2
dependencies: [TODO-43]
---

## Goal

Add five new React Query hooks to `src/web/lib/hooks/useAgentTemplatesAdmin.ts` (or a new co-located file) for the full credential management API surface: list keys, health check, store, rotate, and delete mutations. These hooks are consumed by the CredentialsTab (TODO-50), the Test tab enhancement (TODO-54), and the publish gate warning (TODO-53).

## Context

The frontend has no API integration layer for platform credentials yet. All five hooks must follow the existing hook patterns in `src/web/lib/hooks/` (React Query, typed responses, error handling) and target the endpoints created in TODO-43.

Reference: `workspaces/mingai/02-plans/18-platform-credential-vault-plan.md` — Sprint C1, hook list.

## Implementation

### File placement

Check whether `src/web/lib/hooks/useAgentTemplatesAdmin.ts` already exists. If it does, add the new hooks to it. If it does not, create it. Follow the naming and structure pattern of the nearest existing hook file (e.g., `useSkills.ts` or `useLLMLibrary.ts`).

### TypeScript types

Define response types for all API contracts:

```typescript
export interface CredentialMetadata {
  key: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  created_by: string;
  version: number;
}

export interface CredentialListResponse {
  template_id: string;
  credentials: CredentialMetadata[];
}

export type CredentialStatus = "stored" | "missing" | "revoked";

export interface CredentialHealthResponse {
  template_id: string;
  required_credentials: string[];
  status: "complete" | "incomplete" | "not_required";
  keys: Record<string, CredentialStatus>;
}
```

### useTemplateCredentials(templateId: string)

```typescript
// GET /api/v1/platform/templates/{templateId}/credentials
// Returns: CredentialListResponse
// Enabled only when templateId is truthy
// Cache key: ["platform", "credentials", templateId]
```

### useCredentialHealth(templateId: string)

```typescript
// GET /api/v1/platform/templates/{templateId}/credentials/health
// Returns: CredentialHealthResponse
// Enabled only when templateId is truthy
// Cache key: ["platform", "credentials", templateId, "health"]
// Used by: CredentialsTab (CompletenessHeader), TestHarnessTab, TemplateStudioPanel (badge)
```

### useStoreCredential()

```typescript
// POST /api/v1/platform/templates/{templateId}/credentials
// Body: { key, value, description?, allowed_domains? }
// On success: invalidate ["platform", "credentials", templateId] + health
// On error: expose error message for inline form display
```

### useRotateCredential()

```typescript
// PUT /api/v1/platform/templates/{templateId}/credentials/{key}
// Body: { value }
// Headers: { "If-Match": String(version) }
// On success: invalidate list + health
// 409 on version mismatch — surface to caller for user-facing error
```

### useDeleteCredential()

```typescript
// DELETE /api/v1/platform/templates/{templateId}/credentials/{key}?force={force}
// force: boolean (default false)
// On success: invalidate list + health
// 409 with affected_agent_count when active agents exist — caller decides whether to retry with force=true
```

### Cache invalidation strategy

After any successful mutation (store, rotate, delete), invalidate both:
- `["platform", "credentials", templateId]` (list)
- `["platform", "credentials", templateId, "health"]` (health)

This ensures the CompletenessHeader and tab badge update immediately after a credential is stored.

### Error handling

All mutations should return a structured error object that includes:
- HTTP status code
- Error detail string from the response body
- `affected_agent_count` for 409 on delete (parsed from the response body)

Do NOT throw unhandled errors — the consuming component needs to display inline errors without crashing.

### No credential values in hook return types

The `value` field must never appear in any type definition or hook return value. The API contract guarantees this server-side; the TypeScript types enforce it client-side.

## Acceptance Criteria

- [ ] `useTemplateCredentials(templateId)` fetches and returns `CredentialListResponse`
- [ ] `useCredentialHealth(templateId)` fetches and returns `CredentialHealthResponse`
- [ ] `useStoreCredential()` sends POST with body and invalidates list + health on success
- [ ] `useRotateCredential()` sends PUT with `If-Match` header and invalidates on success
- [ ] `useDeleteCredential()` sends DELETE with optional `force` query param
- [ ] Delete mutation surfaces `affected_agent_count` from 409 response to the caller
- [ ] All hooks follow the existing React Query patterns in `src/web/lib/hooks/`
- [ ] `CredentialHealthResponse` and `CredentialMetadata` types are exported for use by components
- [ ] No `value` field appears in any TypeScript type or hook return value
- [ ] Hooks are importable from the hooks directory without circular dependencies
