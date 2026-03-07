"""
HAR A2A Cryptography — Ed25519 key generation, signing, and verification (AI-040).

Private keys are encrypted at rest using Fernet symmetric encryption derived
from the JWT_SECRET_KEY environment variable via PBKDF2HMAC.

All secrets come from environment variables — NEVER hardcoded.
"""
import base64
import os

import structlog
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = structlog.get_logger()

# Fixed salt for deterministic key derivation from JWT_SECRET_KEY.
# This is NOT a password hash — the salt provides domain separation,
# not per-user uniqueness. Changing this salt invalidates all encrypted keys.
_KDF_SALT = b"mingai-har-v1"
_KDF_ITERATIONS = 200_000


def get_fernet() -> Fernet:
    """
    Create a Fernet instance from JWT_SECRET_KEY env var.

    Uses PBKDF2HMAC with SHA256, 200k iterations, fixed salt.
    Raises ValueError if JWT_SECRET_KEY is not set or empty.
    """
    jwt_secret = os.environ.get("JWT_SECRET_KEY", "")
    if not jwt_secret:
        raise ValueError(
            "JWT_SECRET_KEY environment variable is not set or empty. "
            "Cannot derive encryption key for HAR private keys. "
            "Set JWT_SECRET_KEY in .env"
        )

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=_KDF_ITERATIONS,
    )
    derived_key = kdf.derive(jwt_secret.encode("utf-8"))
    fernet_key = base64.urlsafe_b64encode(derived_key)
    return Fernet(fernet_key)


def generate_agent_keypair() -> tuple[str, str]:
    """
    Generate an Ed25519 keypair for agent signing.

    Returns:
        (public_key_b64, encrypted_private_key_b64)
        - public_key_b64: base64url-encoded raw 32-byte public key
        - encrypted_private_key_b64: Fernet-encrypted raw 64-byte private key (base64url token)

    The private key is encrypted at rest — it MUST be decrypted only
    when signing a payload, then immediately discarded from memory.
    """
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Raw 32-byte public key
    public_bytes = public_key.public_bytes_raw()
    public_key_b64 = base64.urlsafe_b64encode(public_bytes).decode("ascii")

    # Raw 64-byte private key (seed + public), encrypted with Fernet
    private_bytes = private_key.private_bytes_raw()
    # Ed25519 private_bytes_raw() returns 32-byte seed; we store the full 64 bytes
    # by concatenating seed + public for compatibility
    full_private = private_bytes + public_bytes  # 64 bytes total

    fernet = get_fernet()
    encrypted_private = fernet.encrypt(full_private)
    encrypted_private_b64 = encrypted_private.decode("ascii")

    return public_key_b64, encrypted_private_b64


def sign_payload(private_key_enc_b64: str, payload: bytes) -> str:
    """
    Decrypt the private key and sign payload with Ed25519.

    Args:
        private_key_enc_b64: Fernet-encrypted private key (base64url token)
        payload: bytes to sign

    Returns:
        base64url-encoded Ed25519 signature

    Raises:
        ValueError: If private key cannot be decrypted or is malformed
    """
    if not private_key_enc_b64:
        raise ValueError(
            "private_key_enc_b64 is empty — cannot sign payload without a private key"
        )

    fernet = get_fernet()
    try:
        decrypted = fernet.decrypt(private_key_enc_b64.encode("ascii"))
    except InvalidToken:
        raise ValueError(
            "Failed to decrypt private key — Fernet token is invalid. "
            "This may indicate JWT_SECRET_KEY has changed since the key was generated."
        )

    if len(decrypted) != 64:
        raise ValueError(
            f"Decrypted private key is {len(decrypted)} bytes, expected 64. "
            "Key data may be corrupted."
        )

    # First 32 bytes are the seed (private key), last 32 are public key
    seed = decrypted[:32]
    private_key = Ed25519PrivateKey.from_private_bytes(seed)

    signature = private_key.sign(payload)
    return base64.urlsafe_b64encode(signature).decode("ascii")


def verify_signature(public_key_b64: str, payload: bytes, signature_b64: str) -> bool:
    """
    Verify an Ed25519 signature.

    Args:
        public_key_b64: base64url-encoded raw 32-byte public key
        payload: original bytes that were signed
        signature_b64: base64url-encoded signature

    Returns:
        True if signature is valid, False otherwise.
        Never raises on invalid input — returns False.
    """
    try:
        if not public_key_b64 or not signature_b64:
            return False

        # Pad base64url if needed
        public_bytes = base64.urlsafe_b64decode(
            public_key_b64 + "=" * (4 - len(public_key_b64) % 4)
            if len(public_key_b64) % 4
            else public_key_b64
        )
        if len(public_bytes) != 32:
            logger.warning(
                "verify_signature_invalid_public_key_length",
                expected=32,
                actual=len(public_bytes),
            )
            return False

        signature_bytes = base64.urlsafe_b64decode(
            signature_b64 + "=" * (4 - len(signature_b64) % 4)
            if len(signature_b64) % 4
            else signature_b64
        )

        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        public_key.verify(signature_bytes, payload)
        return True

    except Exception as exc:
        logger.debug(
            "verify_signature_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return False
