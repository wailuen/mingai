---
id: TODO-44
title: CredentialScrubber + file permissions + startup validation
status: pending
priority: high
phase: A3
dependencies: [TODO-42]
---

## Goal

Implement three security hardening measures that are independent of the route layer: (1) `CredentialScrubber` class that redacts live credential values from strings, (2) file permission enforcement on the platform Fernet file, (3) startup-time validation that fails loudly if no platform credential encryption backend is configured.

## Context

Risk C-01 (third-party error message leaks credential value) and risk C-06 (silent plaintext fallback) are P0 risks identified in the gap analysis. These three controls together ensure credentials cannot leak through error paths or be stored unencrypted.

Reference: `workspaces/mingai/01-analysis/19-platform-credential-vault/01-gap-and-risk-analysis.md` — Risk Register, C-01 and C-06.

## Implementation

### 1. CredentialScrubber

New file: `app/core/credential_scrubber.py`

```python
"""
CredentialScrubber — redacts resolved credential values from strings.

Usage:
    scrubber = CredentialScrubber(resolved_credentials)
    safe_text = scrubber.scrub(raw_tool_error_message)

Security contract:
    - Only values with len > 4 are tracked (avoids thrashing on short env strings)
    - scrub() replaces exact substring matches with "[REDACTED]"
    - The scrubber instance is request-scoped — not shared across requests
    - Values are held in memory only for the lifetime of the request
"""
from __future__ import annotations


class CredentialScrubber:
    def __init__(self, resolved: dict[str, str]) -> None:
        # Only track values longer than 4 characters to avoid false positives
        self._values: list[str] = [
            v for v in resolved.values() if v and len(v) > 4
        ]

    def scrub(self, text: str) -> str:
        """Replace any known credential value in text with '[REDACTED]'."""
        for val in self._values:
            text = text.replace(val, "[REDACTED]")
        return text
```

The scrubber is consumed in TODO-46 (orchestrator integration). This todo only creates the class and its unit test.

### 2. File permissions on platform Fernet file

In `credential_manager.py`, in the method responsible for saving the platform Fernet file (the `_save()` or equivalent method in the local encrypted store), add:

```python
import os
os.chmod(fernet_file_path, 0o600)
```

This must be called on every write to the platform credentials file, not just on first creation. The pattern should mirror whatever the existing tenant credentials Fernet file does (check `_LocalEncryptedStore._save()` or equivalent). Apply the chmod call AFTER the atomic write completes.

The tenant Fernet file already applies `0o600` — this extends the same protection to the platform file.

### 3. Startup validation

In `app/main.py`, in the application startup event (lifespan or `@app.on_event("startup")`), add:

```python
from app.core.startup_checks import validate_platform_credential_config

# In startup handler:
validate_platform_credential_config()
```

New file: `app/core/startup_checks.py`

```python
import os


def validate_platform_credential_config() -> None:
    """Raise RuntimeError at startup if no platform credential backend is configured.

    Either PLATFORM_CREDENTIAL_ENCRYPTION_KEY (dev Fernet) or VAULT_ADDR (prod Vault)
    must be set. Absence of both means credentials would be silently lost or unencrypted.
    """
    has_fernet = bool(os.environ.get("PLATFORM_CREDENTIAL_ENCRYPTION_KEY"))
    has_vault = bool(os.environ.get("VAULT_ADDR"))

    if not has_fernet and not has_vault:
        raise RuntimeError(
            "Platform credential vault is not configured. "
            "Set PLATFORM_CREDENTIAL_ENCRYPTION_KEY (dev) or VAULT_ADDR (prod). "
            "Refusing to start without a credential backend."
        )
```

The startup check must run BEFORE the application starts accepting requests. It should not crash the test suite when neither var is set — integration tests will set `PLATFORM_CREDENTIAL_ENCRYPTION_KEY` in their fixture environment. The test for this behaviour is in TODO-55 (`test_startup_without_encryption_key`).

Wrap the startup check in `if not _testing:` to prevent test suite failures. The `_testing` flag pattern is already present in `main.py`:

```python
_testing = os.environ.get("TESTING", "false").lower() == "true"

# In lifespan startup:
if not _testing:
    validate_platform_credential_config()
```

If the existing `app/main.py` already has a startup check mechanism (e.g., a `startup_checks` module), integrate into that rather than creating a duplicate pattern.

### 4. `.env.example` update

Add the following to `src/backend/.env.example`:

```
# Platform Credential Vault (separate from tenant credentials)
# Required if VAULT_ADDR is not set — generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
PLATFORM_CREDENTIAL_ENCRYPTION_KEY=
PLATFORM_CREDENTIAL_STORE_PATH=.credentials/platform_credentials.json.enc
```

## Acceptance Criteria

- [ ] `CredentialScrubber` is importable from `app.core.credential_scrubber`
- [ ] `scrub()` replaces all occurrences of a tracked value with `"[REDACTED]"`
- [ ] `scrub()` does not modify text that contains no tracked values
- [ ] Values of length 4 or fewer are not tracked (no false positives on short strings)
- [ ] The scrubber is a plain Python class with no framework dependencies (testable without FastAPI)
- [ ] Platform Fernet file has permissions `0o600` after every write (not just on creation)
- [ ] Startup raises `RuntimeError` when neither `PLATFORM_CREDENTIAL_ENCRYPTION_KEY` nor `VAULT_ADDR` is set
- [ ] Startup proceeds normally when either variable is set
- [ ] Startup validation runs before the application begins serving requests
- [ ] Startup check is wrapped in `if not _testing:` to prevent test suite crashes
- [ ] `validate_platform_credential_config` is importable from `app.core.startup_checks`
- [ ] The startup check does not write or read any credential values
- [ ] `src/backend/.env.example` includes both `PLATFORM_CREDENTIAL_ENCRYPTION_KEY` and `PLATFORM_CREDENTIAL_STORE_PATH` with documentation comments
