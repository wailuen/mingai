---
id: TODO-42
title: CredentialManager platform methods + custom exceptions
status: pending
priority: high
phase: A1
dependencies: [TODO-41]
---

## Goal

Extend `app/modules/agents/credential_manager.py` with a platform credential namespace (`platform/templates/{template_id}/{key}`) and the five new methods needed to store, retrieve, list, delete, and resolve platform-level credentials. Add two new exception classes. Add a separate Fernet file and separate encryption key for platform credentials.

## Context

The existing `CredentialManager` stores tenant credentials at `{tenant_id}/agents/{agent_id}/{key}`. No platform-level namespace exists. The `platform_credentials` auth_mode is entirely non-functional because there is no vault path to write to or read from.

ADR-PC-001 (Option A) chose to extend the existing CredentialManager rather than introduce a separate PostgreSQL column-level store. This keeps a single credential abstraction for both tenant and platform credentials, with both dev (Fernet) and prod (Vault) backends supported immediately.

Reference: `workspaces/mingai/01-analysis/19-platform-credential-vault/02-requirements-and-adr.md` — ADR-PC-001, security requirements.

## Implementation

### New exception classes

Add to `credential_manager.py` (or a new `app/core/exceptions.py` if one exists — check first):

```python
class MissingPlatformCredentialError(Exception):
    """Raised when one or more required platform credentials are not stored."""
    def __init__(self, template_id: str, missing_keys: list[str]):
        self.template_id = template_id
        self.missing_keys = missing_keys
        super().__init__(
            f"Missing platform credentials for template {template_id}: {missing_keys}"
        )

class VaultUnavailableError(Exception):
    """Raised when the credential vault backend is unreachable."""
```

### New vault path helper

```python
def _build_platform_vault_path(template_id: str) -> str:
    return f"platform/templates/{template_id}"
```

### Separate Fernet store for platform credentials

The dev (Fernet JSON) backend MUST use a separate file and a separate encryption key from the tenant credential store:

- Env var for key: `PLATFORM_CREDENTIAL_ENCRYPTION_KEY`
- Default file path: `.credentials/platform_credentials.json.enc`
- Optional path override: `PLATFORM_CREDENTIAL_STORE_PATH`

When initialising `CredentialManager`, detect which backend to use:
- If `VAULT_ADDR` is set: use HashiCorp Vault with path prefix `secret/data/platform/templates/`
- Else if `PLATFORM_CREDENTIAL_ENCRYPTION_KEY` is set: use Fernet file at `PLATFORM_CREDENTIAL_STORE_PATH` or the default path
- Else: raise `RuntimeError` at call time (startup validation is handled separately in TODO-44)

### New public methods

```python
def set_platform_credential(
    self,
    template_id: str,
    key: str,
    value: str,
    allowed_domains: list[str],
    description: str | None,
    actor_id: str,
    injection_config: dict | None = None,
) -> None:
    """Store or overwrite a platform credential value in the vault.
    Does NOT write to PostgreSQL — caller (route handler) writes metadata.

    injection_config default: {"type": "header", "header_name": "Authorization", "header_format": "{value}"}
    """
    ...

def get_platform_credential(
    self,
    template_id: str,
    key: str,
) -> str | None:
    """Return the stored value or None if the key does not exist."""
    ...

def list_platform_credential_keys(
    self,
    template_id: str,
) -> list[dict]:
    """Return all stored key metadata for a template. Values are never returned.

    Each entry includes: key, version, injection_config, description, created_at, updated_at.
    """
    ...

def delete_platform_credential(
    self,
    template_id: str,
    key: str,
    actor_id: str,
) -> None:
    """Remove the value from the vault (called after soft-delete metadata update)."""
    ...

def resolve_platform_credentials(
    self,
    template_id: str,
    required_keys: list[str],
    tenant_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, dict]:
    """Resolve all required keys. Raises MissingPlatformCredentialError if any are absent.
    Writes one audit record per key to platform_credential_audit.

    Return type is dict[str, dict] where each value is:
        {"value": str, "injection_config": dict}

    Caller is responsible for scoping the lifetime of the returned dict — values must
    not be persisted beyond the current request.
    """
    ...

def get_platform_credential_health(
    self,
    template_id: str,
    required_keys: list[str],
) -> dict:
    """Return per-key status: 'stored' | 'missing' | 'revoked'.
    Consults platform_credential_metadata (soft-delete state) and vault presence."""
    ...
```

### Key validation

Reuse `_validate_credential_key()` for the `key` parameter in all new methods. The key regex is already `^[a-zA-Z0-9_.-]{1,128}$`.

For `template_id`, add a separate validator: only alphanumeric, hyphens, underscores; max 64 chars.

### No values in logs

All new methods MUST use `structlog` for logging. The `value` parameter MUST never appear in any log statement. Use structlog `bind` context for `template_id` and `key` only.

### Audit writes in resolve_platform_credentials

`resolve_platform_credentials` must obtain a database session (inject via parameter or use a context var — follow the existing pattern in the codebase) and insert rows into `platform_credential_audit` for each key resolved. Action = `"resolve"`, actor_id = `"runtime"`, include `tenant_id` and `request_id` if provided.

## Acceptance Criteria

- [ ] `set_platform_credential` stores value in the platform Fernet file (dev) or Vault path (prod)
- [ ] `set_platform_credential` accepts optional `injection_config` dict (defaults to `{"type": "header", "header_name": "Authorization", "header_format": "{value}"}`)
- [ ] `get_platform_credential` returns `None` for a key that was never stored (no exception)
- [ ] `list_platform_credential_keys` returns per-key metadata (including `version` and `injection_config`) — never values
- [ ] `delete_platform_credential` removes the value from the vault backend
- [ ] `resolve_platform_credentials` raises `MissingPlatformCredentialError` if any required key is absent
- [ ] `resolve_platform_credentials` returns `dict[str, dict]` where each value is `{"value": str, "injection_config": dict}`
- [ ] `resolve_platform_credentials` writes one audit record per key to `platform_credential_audit`
- [ ] `get_platform_credential_health` returns `{'stored', 'missing', 'revoked'}` per key
- [ ] Platform credentials use `PLATFORM_CREDENTIAL_ENCRYPTION_KEY`, NOT `CREDENTIAL_ENCRYPTION_KEY`
- [ ] When `PLATFORM_CREDENTIAL_STORE_PATH` is set, Fernet file is created at that path instead of default `.credentials/platform_credentials.json.enc`
- [ ] Platform Fernet file is separate from the tenant Fernet file
- [ ] No credential value appears in any structlog output (confirmed by unit test in TODO-55)
- [ ] `MissingPlatformCredentialError` and `VaultUnavailableError` are importable from the module
- [ ] All methods validate `template_id` and `key` before building vault paths
