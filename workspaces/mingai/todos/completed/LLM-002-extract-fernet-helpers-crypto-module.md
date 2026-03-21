# TODO-LLM-002: Extract Fernet Helpers to app/core/crypto.py

## Status

Active

## Summary

Extract the `encrypt_api_key()` and `decrypt_api_key()` methods from `ProviderService` into a new shared module `app/core/crypto.py`. This enables both `llm_providers` routes and `llm_library` routes to use the same encryption primitives without coupling `llm_library` to the `llm_providers` service class.

## Context

Currently, `app/core/llm/provider_service.py` contains `encrypt_api_key()` and `decrypt_api_key()` as instance methods on `ProviderService`. These methods are thin wrappers around `app/modules/har/crypto.py::get_fernet()`. The `llm_library` routes cannot call `ProviderService` methods without taking an inappropriate dependency on the provider feature. The analysis (section 6) explicitly calls for extracting these to `app.core.crypto` as reusable utilities.

## Acceptance Criteria

- [ ] `src/backend/app/core/crypto.py` created with two public functions: `encrypt_api_key(plaintext: str) -> bytes` and `decrypt_api_key(encrypted: bytes) -> str`
- [ ] Both functions delegate to `get_fernet()` from `app.modules.har.crypto` (same key derivation — no separate secret)
- [ ] `decrypt_api_key` raises `ValueError` with the same message as the existing `ProviderService` implementation on `InvalidToken`
- [ ] `ProviderService.encrypt_api_key()` and `ProviderService.decrypt_api_key()` updated to delegate to `app.core.crypto` rather than duplicating logic
- [ ] All existing callers of `ProviderService.encrypt_api_key()` / `decrypt_api_key()` still pass without changes (they call the method on the instance; the instance now delegates internally)
- [ ] `app/core/crypto.py` has a module docstring explaining the security contract (key derivation source, caller responsibilities)
- [ ] Existing tests in `tests/unit/test_provider_service.py` and `tests/unit/test_credential_encryption.py` continue to pass without modification
- [ ] `app/core/__init__.py` does NOT auto-import `crypto` (lazy import — callers import explicitly)
- [ ] ProviderService.encrypt_api_key() and decrypt_api_key() continue to work identically (no caller changes needed)

## Implementation Notes

New file `app/core/crypto.py`:

```python
"""
Shared Fernet encryption utilities for API key storage.

Encryption is derived from JWT_SECRET_KEY via PBKDF2HMAC (see app.modules.har.crypto).
Security contract:
- Callers MUST clear decrypted keys (key = "") immediately after use.
- api_key_encrypted is NEVER returned in any API response.
- Only api_key_last4 (last 4 chars of plaintext before encryption) is safe to expose.
"""
from app.modules.har.crypto import get_fernet
from cryptography.fernet import InvalidToken


def encrypt_api_key(plaintext: str) -> bytes:
    """Encrypt a plaintext API key. Returns raw bytes for BYTEA column."""
    fernet = get_fernet()
    return fernet.encrypt(plaintext.encode("utf-8"))


def decrypt_api_key(encrypted: bytes) -> str:
    """
    Decrypt a BYTEA-stored encrypted API key.
    Caller MUST clear result (key = "") after use.
    Raises ValueError if decryption fails.
    """
    fernet = get_fernet()
    try:
        return fernet.decrypt(encrypted).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Failed to decrypt API key — Fernet token is invalid. "
            "This may indicate JWT_SECRET_KEY has changed since the key was stored."
        ) from exc
```

Update `ProviderService` to delegate:

```python
def encrypt_api_key(self, plaintext_key: str) -> bytes:
    from app.core.crypto import encrypt_api_key
    return encrypt_api_key(plaintext_key)

def decrypt_api_key(self, encrypted_bytes: bytes) -> str:
    from app.core.crypto import decrypt_api_key
    return decrypt_api_key(encrypted_bytes)
```

Use lazy imports inside the method bodies to avoid any circular import issues at module load time.

ProviderService.encrypt_api_key() and decrypt_api_key() methods MUST be preserved as thin wrappers calling app.core.crypto. Do NOT change method signatures — PVDR-001-020 routes call them as instance methods.

The new app/core/crypto.py must use the SAME PBKDF2 derivation and salt as app.modules.har.crypto.get_fernet() — do NOT create a new salt. All existing ProviderService keys remain decryptable.

## Dependencies

- Depends on: nothing (can be done in parallel with LLM-001)
- Blocks: LLM-005, LLM-008

## Test Requirements

- [ ] Unit test in `tests/unit/test_crypto.py`: encrypt/decrypt round-trip succeeds
- [ ] Unit test: `decrypt_api_key` raises `ValueError` on tampered ciphertext
- [ ] Unit test: `decrypt_api_key` raises `ValueError` when `JWT_SECRET_KEY` is absent (monkeypatch env)
- [ ] Existing tests `test_provider_service.py` and `test_credential_encryption.py` continue to pass (regression guard)
