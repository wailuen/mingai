# Platform Credential Vault — Implementation Plan

**Date**: 2026-03-23
**Analysis**: `01-analysis/19-platform-credential-vault/`
**Scope**: Phase 1 only — full end-to-end credential management for `platform_credentials` auth_mode

---

## Context

Agent templates with `auth_mode = "platform_credentials"` are currently non-functional:
- `agents/routes.py` returns 422 on deployment
- Test harness silently passes without credentials
- No vault path or storage for platform-level API keys

This plan delivers the minimum viable platform credential vault so that the PitchBook Intelligence Agent (and future platform-credentialed templates) can be fully tested, deployed, and used by tenants.

---

## Phases

### Phase A — Foundation (Backend Core)

**Goal**: Platform admin can store, rotate, and delete credentials. Test harness reports actual credential status.

#### Sprint A1: Database & CredentialManager Extension

**Migration: `v061_platform_credential_vault.py`**

```python
# New tables
platform_credential_metadata:
  id UUID PK
  template_id VARCHAR(64) FK → agent_templates.id ON DELETE RESTRICT
  key VARCHAR(64)
  allowed_domains JSONB NOT NULL DEFAULT '[]'  -- SSRF protection (C-02)
  description VARCHAR(256)
  version INTEGER NOT NULL DEFAULT 1           -- optimistic concurrency (C-03)
  created_at TIMESTAMPTZ
  created_by VARCHAR(128)
  updated_at TIMESTAMPTZ
  updated_by VARCHAR(128)
  deleted_at TIMESTAMPTZ
  deleted_by VARCHAR(128)
  retention_until TIMESTAMPTZ

# PARTIAL unique index — allows re-provision after soft-delete (M-01 fix)
CREATE UNIQUE INDEX uq_pcm_active ON platform_credential_metadata(template_id, key)
    WHERE deleted_at IS NULL;

platform_credential_audit:
  id UUID PK
  timestamp TIMESTAMPTZ
  actor_id VARCHAR(128)         -- user ID or "runtime"
  tenant_id VARCHAR(128)        -- tenant that triggered (runtime reads)
  request_id VARCHAR(128)       -- correlation ID (runtime reads)
  action VARCHAR(32)            -- store|rotate|delete|resolve|blocked
  template_id VARCHAR(64)
  key VARCHAR(64)
  source_ip INET
  metadata JSONB
```

**`app/modules/agents/credential_manager.py` additions:**

```python
def set_platform_credential(template_id, key, value, allowed_domains) -> None
def get_platform_credential(template_id, key) -> Optional[str]  # returns None if missing
def list_platform_credential_keys(template_id) -> list[str]
def delete_platform_credential(template_id, key) -> None
def resolve_platform_credentials(template_id, required_keys) -> dict[str, str]
    # raises MissingPlatformCredentialError if any key is missing
```

Vault path: `platform/templates/{template_id}/{key}`
Fernet file: `.credentials/platform_credentials.json.enc`
Fernet key: `PLATFORM_CREDENTIAL_ENCRYPTION_KEY` (separate from `CREDENTIAL_ENCRYPTION_KEY`)

**Startup validation (C-06)**: Add to `app/main.py` startup — raise if neither `PLATFORM_CREDENTIAL_ENCRYPTION_KEY` nor `VAULT_ADDR` is set.

**Reserved tenant IDs (C-07)**: Add validation in tenant creation endpoint: reject `platform`, `system`, `__platform__`, any `__*` prefix.

#### Sprint A2: CRUD Routes

New file: `app/modules/platform/credentials_routes.py`

```
POST   /platform/templates/{id}/credentials          — store (FR-01)
GET    /platform/templates/{id}/credentials          — list keys (FR-02)
PUT    /platform/templates/{id}/credentials/{key}    — rotate (FR-03, If-Match header, C-03)
DELETE /platform/templates/{id}/credentials/{key}    — soft-delete (FR-04)
GET    /platform/templates/{id}/credentials/health   — completeness (FR-06, FR-07)
```

All routes: `require_platform_admin`.
All write routes: append to `platform_credential_audit`.
PUT rotate: validates `If-Match: {version}` header → 409 on version mismatch.
DELETE: pre-check active agents → 409 with `affected_agent_count` unless `?force=true`.

Register in `app/api/router.py`.

#### Sprint A3: Security Hardening

**`CredentialScrubber` (C-01)**:

```python
# app/core/credential_scrubber.py
class CredentialScrubber:
    def __init__(self, resolved: dict[str, str]):
        self._values = [v for v in resolved.values() if v and len(v) > 4]

    def scrub(self, text: str) -> str:
        for val in self._values:
            text = text.replace(val, "[REDACTED]")
        return text
```

All tool execution error messages, log entries from the tool executor, and LLM context injections MUST pass through scrubber before leaving the execution boundary.

**`allowed_domains` validation (C-02)**: Stored with each credential. Orchestrator validates tool endpoint URL against `allowed_domains` before injecting credential. Mismatch: block + `credential_injection_blocked` audit event.

**File permissions (S-10)**: `os.chmod(fernet_file_path, 0o600)` in `_LocalEncryptedStore._save()` for platform credentials file. (Already done for tenant credentials — extend pattern.)

---

### Phase B — Runtime Integration

**Goal**: Tenants can deploy and use templates with `platform_credentials` auth_mode. Agents resolve credentials at query time.

#### Sprint B1: Orchestrator Integration

**`app/modules/chat/orchestrator.py` changes:**

At orchestration start, before any tool call:
1. Check `template.auth_mode`
2. If `platform_credentials`: call `resolve_platform_credentials(template_id, required_keys)`
   - If any key missing: `raise MissingPlatformCredentialError` → 503 to user ("Agent temporarily unavailable — contact your administrator")
   - If all resolved: store in request-scoped execution context (not cached across requests — C-04 fix)
3. Pass resolved credentials + `CredentialScrubber` into tool executor context
4. Write audit record: `action=resolve, actor_id="runtime", tenant_id=..., request_id=...`

**Audit tenant context (M-04)**: Thread/context-var based tenant_id + request correlation ID propagated to `resolve_platform_credentials`.

#### Sprint B2: Deployment Flow Fix

**`app/modules/agents/routes.py`**:
- Remove the 422 rejection for `auth_mode='platform_credentials'` (lines 340-345)
- On deployment of `platform_credentials` template: call `GET /credentials/health` internally
  - If incomplete: return 422 with `"Cannot deploy: missing platform credentials: [key_names]"`
  - If complete: proceed with deployment

#### Sprint B3: Publish Gate

**`app/modules/platform/routes.py`** — in the PATCH/publish endpoint:

When status changes to "published" and `auth_mode = 'platform_credentials'`:
1. Query `platform_credential_metadata` for all active keys matching `template.required_credentials`
2. If any missing: return 422 `"Cannot publish: missing platform credentials: [key_names]"`

---

### Phase C — Frontend

**Goal**: Platform admin has full credential management UI embedded in the Template Studio Panel.

#### Sprint C1: Credentials Tab

New file: `src/web/app/(platform)/platform/agent-templates/elements/CredentialsTab.tsx`

Components:
- `CredentialRow` — summary line + status badge + actions
- `CredentialInlineForm` — password input, warnings, save/cancel
- `DeleteConfirmation` — inline impact count + confirm
- `CompletenessHeader` — badge: "All configured" / "2/3 configured" / "Unconfigured"

New hooks in `useAgentTemplatesAdmin.ts`:
- `useTemplateCredentials(templateId)` — GET /credentials
- `useStoreCredential()` — POST mutation
- `useRotateCredential()` — PUT mutation (passes If-Match version header)
- `useDeleteCredential()` — DELETE mutation
- `useCredentialHealth(templateId)` — GET /credentials/health

#### Sprint C2: Tab Integration & Cross-Tab Communication

**`TemplateStudioPanel.tsx`**:
- Add "Credentials" to tab list
- Tab badge: show orange dot with missing count when `auth_mode = 'platform_credentials'` and any credentials missing
- Publish gate: on Publish click, check credential health → show warning block if incomplete

**`TestHarnessTab.tsx`**:
- Call `useCredentialHealth` when `auth_mode = 'platform_credentials'`
- Update banner: green "N/N configured" or orange "N missing" with link to Credentials tab
- Disable Run Test when any credentials missing

---

## Technical Constraints

| Constraint | Handling |
|---|---|
| Vault unavailable | `resolve_platform_credentials` raises `VaultUnavailableError` → 503 to user |
| Fernet key missing | Startup error (C-06 fix) |
| Template has no `required_credentials` | Health check returns `status: "not_required"`, deploy proceeds |
| `auth_mode = 'none'` | No credential resolution, no changes |
| `auth_mode = 'tenant_credentials'` | Existing flow unchanged |
| Template versioning | Phase 1: credentials are per `template_id`, shared across versions |
| Deletion of template with credentials | `ON DELETE RESTRICT` FK blocks — admin must delete credentials first |

---

## New ENV Variables

| Variable | Purpose | Required |
|---|---|---|
| `PLATFORM_CREDENTIAL_ENCRYPTION_KEY` | Fernet key for dev platform credential file | If no `VAULT_ADDR` |
| `PLATFORM_CREDENTIAL_STORE_PATH` | Dev credential file path | Optional (default: `.credentials/platform_credentials.json.enc`) |

---

## Migration File

`src/backend/alembic/versions/v061_platform_credential_vault.py`

---

## Test Plan

| Test | Type | Validates |
|---|---|---|
| `test_platform_credential_crud` | Integration | POST, GET, PUT, DELETE via API |
| `test_platform_credential_acl` | Integration | Tenant admin gets 403 on all endpoints |
| `test_platform_credential_rotation_concurrency` | Integration | Concurrent PUT → one 409, one 200, no silent data loss |
| `test_platform_credential_partial_unique_index` | Integration | Re-provision after soft-delete succeeds |
| `test_credential_scrubber` | Unit | Credential value stripped from error strings |
| `test_allowed_domains_validation` | Integration | Tool call to non-allowed domain blocked |
| `test_startup_without_encryption_key` | Integration | Startup raises error when neither key nor vault configured |
| `test_publish_gate_missing_credentials` | Integration | Publish → 422 when required credentials missing |
| `test_deployment_missing_credentials` | Integration | Deploy → 422 when required credentials missing |
| `test_orchestrator_eager_resolution` | Integration | Credentials resolved before first tool call; missing → fast fail |
| `test_audit_record_tenant_context` | Integration | Runtime audit records include tenant_id + request_id |
| `test_reserved_tenant_id_rejection` | Unit | `platform`, `system`, `__platform__` rejected at tenant creation |
| `test_credential_not_in_logs` | Integration | No credential value appears in structlog output |

---

## Phase 2 Backlog (Not in This Plan)

| Item | Rationale |
|---|---|
| Cross-template shared credentials (M-02) | Reduces rotation burden for enterprise API keys used by N templates |
| MFA step-up on credential writes (C-05) | Requires Auth0 step-up integration work |
| Short-lived resolve cache (S-02) | 5-min TTL reduces vault load at scale; Redis invalidation on rotate |
| Credential connectivity ping/test (S-07) | POST /credentials/test — makes real HTTP probe to validate key works |
| Vault integration test suite (M-05) | Docker Vault dev server in CI |
| Template deprecation credential cleanup (M-03) | Orphan credential cleanup |
| Memory scrubbing for decrypted values (S-12) | SecretStr wrapper, zero on GC |
