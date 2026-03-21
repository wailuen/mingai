"""
Shared Fernet encryption utilities for API key storage.

Encryption is derived from JWT_SECRET_KEY via PBKDF2HMAC — delegates to
app.modules.har.crypto.get_fernet() for key derivation so all encrypted
values share the same salt and key material.

Security contract:
- Callers MUST clear decrypted keys (key = "") immediately after use.
- api_key_encrypted is NEVER returned in any API response.
- Only api_key_last4 (last 4 chars of plaintext before encryption) is
  safe to expose in responses.

Used by: llm_library routes (LLM-002), ProviderService (thin wrappers).
"""
from cryptography.fernet import InvalidToken


def encrypt_api_key(plaintext: str) -> bytes:
    """
    Encrypt a plaintext API key using Fernet derived from JWT_SECRET_KEY.

    Returns raw bytes suitable for storing in a BYTEA column.
    The plaintext should be cleared by the caller after this call.
    """
    from app.modules.har.crypto import get_fernet

    fernet = get_fernet()
    return fernet.encrypt(plaintext.encode("utf-8"))


def decrypt_api_key(encrypted: bytes) -> str:
    """
    Decrypt a BYTEA-stored encrypted API key.

    Returns the plaintext key string.
    Caller MUST clear the returned string (key = "") after use.
    Raises ValueError if decryption fails (invalid token or wrong JWT_SECRET_KEY).
    """
    from app.modules.har.crypto import get_fernet

    fernet = get_fernet()
    try:
        return fernet.decrypt(encrypted).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Failed to decrypt API key — Fernet token is invalid. "
            "This may indicate JWT_SECRET_KEY has changed since the key was stored."
        ) from exc
