# Platform Credential Vault — Gap & Risk Analysis

**Date**: 2026-03-23
**Status**: Complete
**Next**: See `02-requirements-and-adr.md`, `03-red-team-critique.md`, `04-ux-design-spec.md`

---

## Executive Summary

The mingai platform's `auth_mode = "platform_credentials"` feature is fully stub. The DB schema exists (columns, enum), but no vault path, no DB table, no routes, and no runtime injection have been implemented. The test harness silently marks credentials as resolved without retrieving anything. Deploying any template with `platform_credentials` mode returns HTTP 422.

**Root cause**: Credential storage abstraction was designed exclusively for tenant-scoped paths (`{tenant_id}/agents/{agent_id}/{key}`). No platform-level namespace exists.

**Complexity score**: 22 (Complex). Spans security, data architecture, multi-tenant isolation, and runtime injection.

---

## Current State

### What Exists

| Component | Description |
|---|---|
| `CredentialManager` class | Two backends: HashiCorp Vault KV v2 (prod) or Fernet-encrypted JSON (dev). Vault path schema: `{tenant_id}/agents/{agent_id}/{key}` |
| `app.core.secrets.VaultClient` | Azure Key Vault / LocalDB — used for HAR private keys only |
| `agent_templates.auth_mode` | DB column allows `none`, `tenant_credentials`, `platform_credentials` (migration v045) |
| `agent_templates.required_credentials` | JSONB column for credential key list |

### What's Missing

| Gap | Severity |
|---|---|
| No vault path for platform credentials | Critical — blocks all implementation |
| No `platform_credentials` DB metadata table | Critical |
| No CRUD routes for platform credential management | Critical |
| `agents/routes.py` returns 422 for `platform_credentials` | Critical — blocks agent deployment |
| Test harness stub (`pass`) marks resolved without retrieving | Critical — silent false positive |
| No runtime injection in orchestrator | Critical — agents would run without credentials |
| No publish gate (templates can publish without credentials) | Major |
| No audit trail for credential access | Major (compliance) |

---

## Architecture Decision

### Recommended: Option A — Extend CredentialManager

Add `platform/templates/{template_id}/{key}` path namespace to the existing `CredentialManager`.

**Why not Option B (new PostgreSQL table):** Encrypted values in DB creates a second secret surface. No audit trail. Violates the principle of keeping secrets out of the application database.

**Why not Option C (Azure Key Vault):** Cloud-specific, violates cloud-agnostic architecture. Dev/prod parity requires Azure emulator.

**Option A advantages:**
- Single credential abstraction for platform + tenant credentials
- Both dev (Fernet) and prod (Vault) backends work immediately
- Query-time resolution = credential rotation propagates instantly to all agents
- Vault ACL isolation via path prefix is standard practice

**Required safeguards with Option A:**
- Separate Fernet key: `PLATFORM_CREDENTIAL_ENCRYPTION_KEY` (separate from tenant key)
- Reserved namespace: reject tenant IDs `platform`, `system`, `__platform__`
- Vault ACL policy: `platform-admin-policy` with `read/create/update` on `secret/data/platform/*` only
- Platform credentials in separate Fernet file (`.credentials/platform_credentials.json.enc`)

---

## Data Architecture

### Vault Paths (Secret Values — Never in DB)

```
Production (HashiCorp Vault KV v2):
  secret/data/platform/templates/{template_id}/{credential_key}

Development (Fernet JSON):
  .credentials/platform_credentials.json.enc
  Key: PLATFORM_CREDENTIAL_ENCRYPTION_KEY
```

### New PostgreSQL Tables

```sql
-- Metadata only — no secret values ever stored here
CREATE TABLE platform_credential_metadata (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id     VARCHAR(64) NOT NULL,
    key             VARCHAR(64) NOT NULL,
    description     VARCHAR(256),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by      VARCHAR(128) NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by      VARCHAR(128) NOT NULL,
    deleted_at      TIMESTAMPTZ,           -- NULL = active; set = soft-deleted
    deleted_by      VARCHAR(128),
    retention_until TIMESTAMPTZ,           -- deleted_at + 30 days

    -- Partial unique index: allows re-use of a key name after soft-delete
    CONSTRAINT fk_template FOREIGN KEY (template_id)
        REFERENCES agent_templates(id) ON DELETE RESTRICT
);
-- PARTIAL unique: only active (non-deleted) rows must be unique
CREATE UNIQUE INDEX uq_pcm_active ON platform_credential_metadata(template_id, key)
    WHERE deleted_at IS NULL;
CREATE INDEX idx_pcm_template ON platform_credential_metadata(template_id)
    WHERE deleted_at IS NULL;

-- Audit log — append-only, no values ever
CREATE TABLE platform_credential_audit (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp     TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id      VARCHAR(128) NOT NULL,     -- user ID or "runtime"
    tenant_id     VARCHAR(128),              -- tenant that triggered (for runtime reads)
    request_id    VARCHAR(128),              -- correlation ID for runtime reads
    action        VARCHAR(32) NOT NULL,      -- store, rotate, delete, resolve, blocked
    template_id   VARCHAR(64) NOT NULL,
    key           VARCHAR(64) NOT NULL,
    source_ip     INET,
    metadata      JSONB
);
CREATE INDEX idx_pca_template ON platform_credential_audit(template_id, timestamp DESC);
```

---

## Security Invariants

| Invariant | Enforcement |
|---|---|
| Values never in API responses | Write-only API pattern; no GET returning values |
| Values never in logs | No credential values passed through any logging path |
| Tenant admins have zero access | Route-level RBAC: `require_platform_admin` on all credential routes |
| Platform admins see keys + metadata only | API returns key names, timestamps, status — never values |
| Runtime reads are internal only | `resolve_platform_credentials()` is a Python call, not an HTTP endpoint |
| All reads are audited | Audit record on every vault read, including runtime resolution |
| Credentials injected into tool context | Never into LLM prompt (would appear in conversation history) |

### Access Control Matrix

| Actor | List Keys | Read Value | Write Value | Rotate | Delete |
|---|---|---|---|---|---|
| Platform Admin | ✓ | ✗ (masked) | ✓ | ✓ | ✓ |
| Platform Operator | ✓ | ✗ | ✗ | ✗ | ✗ |
| Tenant Admin | ✗ | ✗ | ✗ | ✗ | ✗ |
| Runtime (orchestrator) | ✗ | ✓ internal | ✗ | ✗ | ✗ |
| Test Harness | ✗ | ✓ internal | ✗ | ✗ | ✗ |

---

## Credential Lifecycle

### Query-Time Resolution (Key Design Decision)

Credentials are resolved **at query time**, not at deployment time. Agent instances store `template_id` + reference to credential keys. The orchestrator calls `resolve_platform_credentials(template_id)` at the start of each orchestration.

**Why this matters:**
- Credential rotation propagates to all active agents at next query (within cache TTL — see below)
- No per-agent update required on rotation
- Revoked credentials take effect immediately

### Rotation Propagation SLA

A short-lived in-memory cache (TTL: 5 minutes, configurable) reduces vault load. After rotation, the new value propagates to all agents within 5 minutes maximum.

### Template Publish Gate

When `auth_mode = 'platform_credentials'` template is published:
1. Query `platform_credential_metadata` for all keys matching `template.required_credentials`
2. If any key is missing (no active record), block publish with error:
   `"Cannot publish: missing platform credentials: ['PITCHBOOK_API_KEY']"`

---

## Risk Register Summary

| ID | Risk | Severity | Priority |
|---|---|---|---|
| C-01 | Third-party error message leaks credential value | Critical | P0 |
| C-02 | SSRF via credential injection to attacker endpoint | Critical | P0 |
| C-03 | Concurrent rotation — no last-writer-wins protection | Critical | P0 |
| C-04 | Mid-execution credential deletion | Critical | P0 |
| C-05 | Platform admin compromise = total exfiltration | Critical | P1 |
| C-06 | Fernet key loss = permanent credential loss | Critical | P0 |
| C-07 | Tenant ID "platform" namespace collision | Critical | P0 |
| M-01 | Soft-delete UNIQUE constraint blocks immediate re-provisioning | Major | P0 (fix: partial unique index) |
| M-02 | No cross-template credential sharing | Major | P2 (deferred) |
| M-03 | Template deprecation orphans credentials | Major | P2 |
| M-04 | Audit records lack tenant context for runtime resolutions | Major | P1 |
| M-05 | Dev/prod backend parity gap | Major | P1 |
| M-06 | Template versioning credential migration undefined | Major | P2 |
| M-08 | Plaintext in POST body at load balancer | Major | P1 |
| S-02 | No caching — every query hits vault | Significant | P1 |
| S-07 | No credential connectivity test (ping the API) | Significant | P2 |
| S-12 | Memory residency of decrypted values | Significant | P2 |

**Full detail on all risks**: see `03-red-team-critique.md`.

---

## Files Requiring Changes

| File | Change |
|---|---|
| `app/modules/agents/credential_manager.py` | Add `get_platform_credential()`, `set_platform_credential()`, `delete_platform_credential()`, `list_platform_credentials()`, `resolve_platform_credentials()` |
| `app/modules/platform/routes.py` | New credential CRUD endpoints |
| `app/modules/agents/routes.py` | Remove 422 rejection; add credential resolution in deployment flow |
| `app/modules/chat/orchestrator.py` | Eager resolution of platform credentials at orchestration start |
| `app/api/router.py` | Register new credential routes |
| `alembic/versions/` | New migration: `platform_credential_metadata` + `platform_credential_audit` tables |
| `src/web/app/(platform)/platform/agent-templates/elements/` | New `CredentialsTab.tsx` component |
| `src/web/app/(platform)/platform/agent-templates/elements/TestHarnessTab.tsx` | Credential status display |
| `src/web/app/(platform)/platform/agent-templates/elements/TemplateStudioPanel.tsx` | Add Credentials tab |
| `src/web/lib/hooks/useAgentTemplatesAdmin.ts` | New hooks for credential CRUD |
