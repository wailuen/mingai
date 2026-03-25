# Platform Credential Vault — Requirements & ADR

**Date**: 2026-03-23
**Status**: Complete
**References**: `01-gap-and-risk-analysis.md`

---

## ADR-PC-001: Platform Credential Storage Strategy

**Status**: Decided

### Decision

**Extend the existing `CredentialManager` with a platform credential namespace** (`platform/templates/{template_id}/{key}`). A metadata-only PostgreSQL table tracks key names, soft-delete state, and audit fields. Credential values never touch the database.

### Alternatives Rejected

| Option | Rejection Reason |
|---|---|
| Option B: PostgreSQL column-level encryption | Secrets in application DB. DIY key management. No native audit trail. Violates principle of keeping secrets out of DB backups. |
| Option C: Azure Key Vault | Cloud-specific — violates cloud-agnostic architecture. Requires Azure emulator in dev. |

### Implementation Phases

| Phase | Scope |
|---|---|
| Phase 1 (this plan) | CRUD routes, metadata table, audit table, publish gate, query-time resolution, test harness diagnostic |
| Phase 2 | Per-tenant usage metering, bulk operations, credential health dashboard |
| Phase 3 | Auto-rotation integration, HSM backing, cross-region vault |

---

## Functional Requirements

### MUST — Phase 1 Blockers

| ID | Requirement | Auth | Edge Cases |
|---|---|---|---|
| FR-01 | Store credential (template_id, key, value) | platform_admin | Dup key → 409. Template not found → 404. Empty value → 400. |
| FR-02 | List credential keys + metadata (never values) | platform_admin | No creds → empty array (not 404). Soft-deleted excluded by default. |
| FR-03 | Rotate credential (overwrite with new value) | platform_admin | Key not found → 404. Rotated soft-deleted key → 400. |
| FR-04 | Delete credential (soft-delete, 30-day retention) | platform_admin | Active agents → 409 with count. `?force=true` override. |
| FR-05 | Resolve at query time — inject into agent tool context | runtime only | Missing → 503 to user ("Agent temporarily unavailable"). Vault down → 503. |
| FR-06 | Publish gate — block if any required credential missing | system | Template with no required_credentials: always pass. |
| FR-07 | Test harness status — stored/missing per key (no values) | platform_admin | Return diagnostic, not value. Link to Credentials tab if missing. |
| FR-08 | Audit all writes and runtime reads | system | tenant_id + request_id on runtime reads. Values never in audit. |

### SHOULD — Phase 1 if scope allows

| ID | Requirement |
|---|---|
| FR-09 | Bulk store — accept multiple key-value pairs atomically |
| FR-10 | Credential health check — per-template completeness summary for dashboard |
| FR-11 | Cascade impact preview on delete — count agents + tenants affected |

### MAY — Phase 2+

| ID | Requirement |
|---|---|
| FR-12 | Per-tenant usage metering for cost attribution |
| FR-13 | Vault auto-rotation integration |
| FR-14 | Credential versioning and rollback |

---

## API Contract

**Base path**: `/api/v1/platform/templates/{template_id}/credentials`
**Auth required**: platform_admin role on all endpoints

### POST — Store Credential

```
POST /api/v1/platform/templates/{template_id}/credentials

Request:
{
  "key": "PITCHBOOK_API_KEY",          // ^[a-zA-Z][a-zA-Z0-9_]{1,63}$
  "value": "sk-live-abc123...",
  "description": "PitchBook Data API"  // optional, max 256 chars
}

Response 201:
{
  "key": "PITCHBOOK_API_KEY",
  "template_id": "...",
  "description": "...",
  "created_at": "2026-03-23T10:00:00Z",
  "created_by": "user_abc"
}
```

### GET — List Keys

```
GET /api/v1/platform/templates/{template_id}/credentials

Response 200:
{
  "template_id": "...",
  "credentials": [
    {
      "key": "PITCHBOOK_API_KEY",
      "description": "...",
      "created_at": "...",
      "updated_at": "...",
      "created_by": "..."
    }
  ]
}
```

### PUT — Rotate

```
PUT /api/v1/platform/templates/{template_id}/credentials/{key}

Request: { "value": "sk-live-newkey..." }
Concurrency: "If-Match: {version}" header required

Response 200:
{ "key": "...", "template_id": "...", "updated_at": "...", "updated_by": "...", "version": 2 }
```

### DELETE — Soft-Delete

```
DELETE /api/v1/platform/templates/{template_id}/credentials/{key}?force=true

Response 200:
{ "key": "...", "deleted_at": "...", "retention_until": "...", "affected_agents": 0 }

409 Conflict: { "error": "active_agents", "affected_agent_count": 12, "force_available": true }
```

### GET /health — Completeness Check

```
GET /api/v1/platform/templates/{template_id}/credentials/health

Response 200:
{
  "template_id": "...",
  "required_credentials": ["PITCHBOOK_API_KEY"],
  "status": "complete" | "incomplete" | "not_required",
  "keys": {
    "PITCHBOOK_API_KEY": "stored" | "missing" | "revoked"
  }
}
```

---

## Security Requirements

### Credential Scrubber (C-01)

Before any tool response, log entry, or LLM context injection passes through the orchestrator, a `CredentialScrubber` MUST scan and redact any substring matching a known credential value for the current request scope.

```python
# Pattern: replace credential values with [REDACTED:key_name]
scrubber = CredentialScrubber(resolved_credentials)
safe_error = scrubber.scrub(raw_error_from_tool)
```

### Allowed Domains (C-02 — SSRF Prevention)

Each stored credential MUST have an `allowed_domains` field (e.g., `["api.pitchbook.com"]`). The orchestrator MUST validate tool endpoint URLs against this list before injecting the credential. Mismatch → block with `credential_injection_blocked` audit event.

Platform admin sets `allowed_domains` at store time. Tenant admins MUST NOT be able to modify this field.

### Optimistic Concurrency (C-03)

PUT /rotate MUST require `If-Match: {version}` header. Mismatch → 409 Conflict. Version returned in every write response.

### Eager Resolution (C-04)

The orchestrator MUST resolve ALL required platform credentials at orchestration START (before any tool call). If any are missing, fail fast. Resolved values are request-scoped (not cached across requests).

### Startup Validation (C-06)

If `PLATFORM_CREDENTIAL_ENCRYPTION_KEY` is not set and `VAULT_ADDR` is not set, the application MUST raise a startup error. No silent fallback to plaintext.

### Reserved Tenant IDs (C-07)

Tenant creation MUST reject: `platform`, `system`, `__platform__`, any ID starting with `__`.

### Partial Unique Index (M-01)

The UNIQUE constraint on `(template_id, key)` MUST be a partial index (`WHERE deleted_at IS NULL`) to allow re-provisioning a key immediately after accidental soft-delete.

---

## Scope Boundary

### In Phase 1

- `CredentialManager` platform methods
- Migration: `platform_credential_metadata` + `platform_credential_audit`
- API routes (CRUD + health)
- Publish gate
- Query-time resolution in orchestrator
- Test harness diagnostic (stored/missing, no values)
- RBAC enforcement
- Hard-delete scheduler (background task, 30-day retention)
- `CredentialScrubber` (C-01)
- `allowed_domains` validation (C-02)
- Optimistic concurrency (C-03)
- Eager resolution (C-04)
- Startup validation (C-06)
- Reserved tenant ID check (C-07)
- Partial unique index (M-01)

### Deferred to Phase 2

- Per-tenant usage metering
- Bulk credential store
- Credential health dashboard widget
- Template versioning credential migration
- MFA step-up on credential writes (C-05)
- Cross-template shared credentials (M-02)
- Orphan cleanup on template deprecation (M-03)
- Vault integration tests (M-05)
- Credential connectivity ping/test (S-07)
- Short-lived resolve cache (S-02)
- Memory scrubbing (S-12)

### Explicitly Out of Scope

- HSM-backed storage
- Per-key Vault ACLs
- Cross-region credential replication
- Client-side encryption of POST payloads (handled via TLS + infrastructure policy)
