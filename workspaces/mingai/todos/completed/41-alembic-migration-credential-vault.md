---
id: TODO-41
title: Alembic migration v061 — platform_credential_metadata + platform_credential_audit
status: pending
priority: high
phase: A1
dependencies: []
---

## Goal

Create the database migration that adds the two new tables required by the Platform Credential Vault: `platform_credential_metadata` (key-level tracking, soft-delete, SSRF fields) and `platform_credential_audit` (append-only audit log).

## Context

`auth_mode = 'platform_credentials'` is currently fully stub. No metadata table exists, so there is nowhere to record which credential keys have been provisioned, who provisioned them, or when they were rotated or deleted. The audit table is required for SOC 2 compliance.

This migration is the dependency of every other backend todo (TODO-42 through TODO-48). It must land first.

Reference: `workspaces/mingai/01-analysis/19-platform-credential-vault/01-gap-and-risk-analysis.md` — Data Architecture section.

## Implementation

Create `src/backend/alembic/versions/v061_platform_credential_vault.py`.

### platform_credential_metadata

```sql
CREATE TABLE platform_credential_metadata (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id      VARCHAR(64) NOT NULL,
    key              VARCHAR(64) NOT NULL,
    allowed_domains  JSONB NOT NULL DEFAULT '[]',
    description      VARCHAR(256),
    version          INTEGER NOT NULL DEFAULT 1,
    injection_config JSONB NOT NULL DEFAULT '{"type": "header", "header_name": "Authorization", "header_format": "{value}"}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by       VARCHAR(128) NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by       VARCHAR(128) NOT NULL,
    deleted_at       TIMESTAMPTZ,
    deleted_by       VARCHAR(128),
    retention_until  TIMESTAMPTZ,
    CONSTRAINT fk_pcm_template
        FOREIGN KEY (template_id)
        REFERENCES agent_templates(id)
        ON DELETE RESTRICT
);
```

The `injection_config` column stores HOW the credential is injected into outbound requests. Supported patterns:

- `{"type": "bearer", "header_name": "Authorization"}` → `Authorization: Bearer {value}`
- `{"type": "header", "header_name": "X-Api-Key", "header_format": "{value}"}` → `X-Api-Key: {value}`
- `{"type": "header", "header_name": "Authorization", "header_format": "ApiKey {value}"}` → `Authorization: ApiKey {value}`
- `{"type": "query_param", "param_name": "api_key"}` → appended as `?api_key={value}`
- `{"type": "basic_auth"}` → `Authorization: Basic base64({value})`

Indexes:
- `CREATE UNIQUE INDEX uq_pcm_active ON platform_credential_metadata(template_id, key) WHERE deleted_at IS NULL;`
  — PARTIAL unique index: allows re-provisioning the same key name immediately after soft-delete (risk M-01 fix)
- `CREATE INDEX idx_pcm_template ON platform_credential_metadata(template_id) WHERE deleted_at IS NULL;`
  — fast lookup of active keys for a given template

### platform_credential_audit

```sql
CREATE TABLE platform_credential_audit (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id    VARCHAR(128) NOT NULL,
    tenant_id   VARCHAR(128),
    request_id  VARCHAR(128),
    action      VARCHAR(32) NOT NULL,
    template_id VARCHAR(64) NOT NULL,
    key         VARCHAR(64) NOT NULL,
    source_ip   INET,
    metadata    JSONB
);
CREATE INDEX idx_pca_template ON platform_credential_audit(template_id, timestamp DESC);
```

Action values: `store`, `rotate`, `delete`, `resolve`, `blocked`.

### downgrade

Drop both tables and their indexes in reverse order (audit first, metadata second). The partial unique index and FK must be dropped before the table.

### Validation rules to verify in tests

- `ON DELETE RESTRICT`: inserting a credential for a non-existent template must fail with a FK violation.
- PARTIAL unique index: two rows with the same `(template_id, key)` but one with `deleted_at IS NOT NULL` must both insert successfully; two active rows must fail.
- `allowed_domains` column defaults to `'[]'` (empty JSONB array) when not provided.
- `version` defaults to 1.

## Acceptance Criteria

- [ ] Migration file exists at `src/backend/alembic/versions/v061_platform_credential_vault.py`
- [ ] `alembic upgrade head` applies cleanly against a fresh test database
- [ ] `alembic downgrade -1` removes both tables without error
- [ ] `platform_credential_metadata` has FK to `agent_templates(id) ON DELETE RESTRICT`
- [ ] PARTIAL unique index `uq_pcm_active` prevents duplicate active keys but allows re-use after soft-delete
- [ ] `platform_credential_audit` has the correct `idx_pca_template` index
- [ ] `allowed_domains` column type is JSONB with default `'[]'`
- [ ] `version` column is INTEGER NOT NULL DEFAULT 1
- [ ] `injection_config` JSONB column present with default `{"type": "header", "header_name": "Authorization", "header_format": "{value}"}`
- [ ] No credential values are stored in either table (metadata and audit only)
- [ ] Migration follows the existing `v0XX_` naming convention used in `src/backend/alembic/versions/`
