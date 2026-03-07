"""
Unit tests for HAR A2A cryptography module (AI-040).

Tests Ed25519 key generation, signing, and verification.
Tier 1: Fast, isolated, no external dependencies.
"""
import base64
import os
from unittest.mock import patch

import pytest

# Test JWT secret must be >= 32 chars (config validator requirement)
TEST_JWT_SECRET = "a" * 64


@pytest.fixture(autouse=True)
def env_vars():
    """Set JWT_SECRET_KEY for all tests in this module."""
    with patch.dict(os.environ, {"JWT_SECRET_KEY": TEST_JWT_SECRET}):
        yield


class TestGenerateKeypair:
    """Test generate_agent_keypair() returns valid Ed25519 keypair."""

    def test_generate_keypair_returns_base64_strings(self):
        """Both public and private keys must be valid base64url-encoded strings."""
        from app.modules.har.crypto import generate_agent_keypair

        public_key_b64, private_key_enc_b64 = generate_agent_keypair()

        # Both must be non-empty strings
        assert isinstance(public_key_b64, str)
        assert isinstance(private_key_enc_b64, str)
        assert len(public_key_b64) > 0
        assert len(private_key_enc_b64) > 0

        # Public key must be valid base64url (raw 32 bytes → 44 chars with padding or 43 without)
        public_bytes = base64.urlsafe_b64decode(public_key_b64 + "==")
        assert (
            len(public_bytes) == 32
        ), f"Ed25519 public key must be 32 raw bytes, got {len(public_bytes)}"

    def test_encrypted_private_key_not_plaintext(self):
        """Private key enc must NOT contain the raw private key bytes in readable form.

        The encrypted token should be a Fernet token, not raw key material.
        """
        from app.modules.har.crypto import generate_agent_keypair

        public_key_b64, private_key_enc_b64 = generate_agent_keypair()

        # Fernet tokens start with 'gAAAAA' (base64 of version byte 0x80 + timestamp)
        # The encrypted value should be a valid Fernet token, not raw bytes
        assert private_key_enc_b64.startswith(
            "gAAAAA"
        ), "Encrypted private key should be a Fernet token (starts with gAAAAA)"

        # Decoding the enc key as-is should NOT yield 64 raw bytes (Ed25519 private key size)
        # because it's encrypted, not raw
        try:
            raw = base64.urlsafe_b64decode(private_key_enc_b64 + "==")
            # Fernet tokens are much larger than 64 bytes
            assert (
                len(raw) > 64
            ), "Encrypted private key should be larger than raw 64 bytes"
        except Exception:
            # If it can't be decoded as base64, that's fine — it's encrypted
            pass

    def test_generate_keypair_unique_each_call(self):
        """Each call must generate a different keypair."""
        from app.modules.har.crypto import generate_agent_keypair

        pub1, priv1 = generate_agent_keypair()
        pub2, priv2 = generate_agent_keypair()

        assert pub1 != pub2, "Each keypair must be unique"
        assert priv1 != priv2, "Each keypair must be unique"


class TestSignAndVerify:
    """Test sign_payload() and verify_signature() roundtrip."""

    def test_sign_and_verify_roundtrip(self):
        """Generate keypair, sign payload, verify → True."""
        from app.modules.har.crypto import (
            generate_agent_keypair,
            sign_payload,
            verify_signature,
        )

        public_key_b64, private_key_enc_b64 = generate_agent_keypair()

        payload = b"hello world"
        signature = sign_payload(private_key_enc_b64, payload)

        assert isinstance(signature, str)
        assert len(signature) > 0

        result = verify_signature(public_key_b64, payload, signature)
        assert result is True

    def test_verify_wrong_payload_returns_false(self):
        """Verify against different payload must return False, not raise."""
        from app.modules.har.crypto import (
            generate_agent_keypair,
            sign_payload,
            verify_signature,
        )

        public_key_b64, private_key_enc_b64 = generate_agent_keypair()

        signature = sign_payload(private_key_enc_b64, b"original message")

        result = verify_signature(public_key_b64, b"tampered message", signature)
        assert result is False

    def test_verify_bad_signature_returns_false(self):
        """Tampered signature must return False, not raise."""
        from app.modules.har.crypto import (
            generate_agent_keypair,
            verify_signature,
        )

        public_key_b64, _ = generate_agent_keypair()

        # A clearly invalid base64url signature
        bad_sig = base64.urlsafe_b64encode(b"x" * 64).decode()

        result = verify_signature(public_key_b64, b"hello world", bad_sig)
        assert result is False

    def test_verify_empty_signature_returns_false(self):
        """Empty/garbage signature must return False, not raise."""
        from app.modules.har.crypto import (
            generate_agent_keypair,
            verify_signature,
        )

        public_key_b64, _ = generate_agent_keypair()
        result = verify_signature(public_key_b64, b"hello", "")
        assert result is False

    def test_verify_invalid_public_key_returns_false(self):
        """Invalid public key must return False, not raise."""
        from app.modules.har.crypto import (
            generate_agent_keypair,
            sign_payload,
            verify_signature,
        )

        _, private_key_enc_b64 = generate_agent_keypair()
        signature = sign_payload(private_key_enc_b64, b"hello")

        bad_pub = base64.urlsafe_b64encode(b"x" * 32).decode()
        result = verify_signature(bad_pub, b"hello", signature)
        assert result is False


class TestGetFernet:
    """Test get_fernet() helper."""

    def test_get_fernet_returns_fernet_instance(self):
        """get_fernet() should return a Fernet instance."""
        from cryptography.fernet import Fernet

        from app.modules.har.crypto import get_fernet

        f = get_fernet()
        assert isinstance(f, Fernet)

    def test_get_fernet_raises_without_jwt_secret(self):
        """get_fernet() must raise when JWT_SECRET_KEY is not set."""
        from app.modules.har.crypto import get_fernet

        with patch.dict(os.environ, {"JWT_SECRET_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
                get_fernet()

    def test_get_fernet_deterministic_for_same_secret(self):
        """Same JWT_SECRET_KEY should produce the same Fernet key (deterministic KDF)."""
        from app.modules.har.crypto import get_fernet

        f1 = get_fernet()
        f2 = get_fernet()

        # Encrypt with f1, decrypt with f2 should work
        token = f1.encrypt(b"test data")
        decrypted = f2.decrypt(token)
        assert decrypted == b"test data"
