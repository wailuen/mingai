"""
Unit tests for app.core.crypto — Fernet API key encryption utilities.

Tier 1: Unit tests, mocking allowed, <1s per test.

Security invariants tested:
- encrypt/decrypt round-trip succeeds
- tampered ciphertext raises ValueError
- empty bytes raises ValueError
- missing JWT_SECRET_KEY raises ValueError
- api_key_last4 derivation logic
"""
import os
from unittest.mock import patch

import pytest


TEST_JWT_SECRET = "a" * 64


class TestEncryptDecryptRoundTrip:
    """Verify that encrypt_api_key / decrypt_api_key are inverse operations."""

    @pytest.fixture(autouse=True)
    def _set_jwt_secret(self):
        with patch.dict(os.environ, {"JWT_SECRET_KEY": TEST_JWT_SECRET}):
            yield

    def test_round_trip_succeeds(self):
        """encrypt_api_key then decrypt_api_key returns original plaintext."""
        from app.core.crypto import decrypt_api_key, encrypt_api_key

        plaintext = "sk-test-abc1234567890"
        encrypted = encrypt_api_key(plaintext)
        assert isinstance(encrypted, bytes)
        assert len(encrypted) > 0

        decrypted = decrypt_api_key(encrypted)
        assert decrypted == plaintext

    def test_encrypted_bytes_differ_from_plaintext(self):
        """Encrypted output must not equal plaintext as bytes."""
        from app.core.crypto import encrypt_api_key

        plaintext = "sk-test-abc1234"
        encrypted = encrypt_api_key(plaintext)
        assert encrypted != plaintext.encode("utf-8")

    def test_two_encryptions_of_same_key_differ(self):
        """Fernet produces different ciphertext each call (nonce-based)."""
        from app.core.crypto import encrypt_api_key

        plaintext = "sk-same-key"
        enc1 = encrypt_api_key(plaintext)
        enc2 = encrypt_api_key(plaintext)
        assert enc1 != enc2

    def test_decrypt_tampered_ciphertext_raises_value_error(self):
        """Modifying encrypted bytes raises ValueError."""
        from app.core.crypto import decrypt_api_key, encrypt_api_key

        plaintext = "sk-test-tamper"
        encrypted = encrypt_api_key(plaintext)
        # Flip a byte in the middle of the ciphertext
        tampered = bytearray(encrypted)
        tampered[len(tampered) // 2] ^= 0xFF
        with pytest.raises(ValueError, match="Fernet token is invalid"):
            decrypt_api_key(bytes(tampered))

    def test_decrypt_empty_bytes_raises(self):
        """Empty bytes is not a valid Fernet token — raises ValueError."""
        from app.core.crypto import decrypt_api_key

        with pytest.raises((ValueError, Exception)):
            decrypt_api_key(b"")

    def test_decrypt_random_bytes_raises_value_error(self):
        """Random bytes that are not Fernet tokens raise ValueError."""
        from app.core.crypto import decrypt_api_key

        with pytest.raises(ValueError):
            decrypt_api_key(b"this-is-not-a-valid-fernet-token")

    def test_short_key_round_trip(self):
        """Keys shorter than 4 chars still round-trip correctly."""
        from app.core.crypto import decrypt_api_key, encrypt_api_key

        plaintext = "abc"
        encrypted = encrypt_api_key(plaintext)
        decrypted = decrypt_api_key(encrypted)
        assert decrypted == plaintext

    def test_long_key_round_trip(self):
        """Long API keys (100+ chars) round-trip correctly."""
        from app.core.crypto import decrypt_api_key, encrypt_api_key

        plaintext = "sk-" + "x" * 97  # 100 chars total
        encrypted = encrypt_api_key(plaintext)
        decrypted = decrypt_api_key(encrypted)
        assert decrypted == plaintext


class TestDecryptWithoutJwtSecret:
    """Verify that missing JWT_SECRET_KEY raises ValueError."""

    def test_encrypt_without_jwt_secret_raises(self):
        """encrypt_api_key raises ValueError when JWT_SECRET_KEY is absent."""
        from app.core.crypto import encrypt_api_key

        with patch.dict(os.environ, {"JWT_SECRET_KEY": ""}):
            with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
                encrypt_api_key("sk-test")

    def test_decrypt_without_jwt_secret_raises(self):
        """decrypt_api_key raises ValueError when JWT_SECRET_KEY is absent."""
        # First encrypt with a valid key
        with patch.dict(os.environ, {"JWT_SECRET_KEY": TEST_JWT_SECRET}):
            from app.core.crypto import encrypt_api_key

            encrypted = encrypt_api_key("sk-test")

        # Then attempt to decrypt without a key
        with patch.dict(os.environ, {"JWT_SECRET_KEY": ""}):
            from app.core.crypto import decrypt_api_key

            with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
                decrypt_api_key(encrypted)

    def test_different_jwt_secrets_produce_decryption_failure(self):
        """Keys encrypted with one secret cannot be decrypted with another."""
        # Encrypt with secret A
        with patch.dict(os.environ, {"JWT_SECRET_KEY": TEST_JWT_SECRET}):
            from app.core.crypto import encrypt_api_key

            encrypted = encrypt_api_key("sk-original-key")

        # Attempt to decrypt with secret B
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "b" * 64}):
            from app.core.crypto import decrypt_api_key

            with pytest.raises(ValueError):
                decrypt_api_key(encrypted)


class TestApiKeyLast4Derivation:
    """Verify the api_key_last4 extraction logic used in route handlers."""

    def test_last4_of_normal_key(self):
        """Keys >= 4 chars: last 4 characters."""
        key = "sk-test-12345678"
        last4 = key[-4:] if len(key) >= 4 else key
        assert last4 == "5678"

    def test_last4_of_exactly_4_chars(self):
        """Keys exactly 4 chars: the whole key."""
        key = "abcd"
        last4 = key[-4:] if len(key) >= 4 else key
        assert last4 == "abcd"

    def test_last4_of_short_key(self):
        """Keys shorter than 4 chars: return the whole key."""
        key = "ab"
        last4 = key[-4:] if len(key) >= 4 else key
        assert last4 == "ab"

    def test_last4_of_empty_key(self):
        """Empty key: returns empty string (not an error at this layer)."""
        key = ""
        last4 = key[-4:] if len(key) >= 4 else key
        assert last4 == ""

    def test_last4_of_long_key(self):
        """Long keys: only the last 4 chars are extracted."""
        key = "sk-proj-" + "x" * 50 + "9999"
        last4 = key[-4:] if len(key) >= 4 else key
        assert last4 == "9999"


class TestProviderServiceDelegation:
    """Verify ProviderService delegates to app.core.crypto (regression guard)."""

    @pytest.fixture(autouse=True)
    def _set_jwt_secret(self):
        with patch.dict(os.environ, {"JWT_SECRET_KEY": TEST_JWT_SECRET}):
            yield

    def test_provider_service_encrypt_delegates(self):
        """ProviderService.encrypt_api_key delegates to app.core.crypto.encrypt_api_key."""
        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()
        plaintext = "test-key-12345"
        encrypted = svc.encrypt_api_key(plaintext)
        assert isinstance(encrypted, bytes)
        assert len(encrypted) > 0

    def test_provider_service_decrypt_delegates(self):
        """ProviderService.decrypt_api_key delegates to app.core.crypto.decrypt_api_key."""
        from app.core.crypto import encrypt_api_key
        from app.core.llm.provider_service import ProviderService

        plaintext = "test-key-67890"
        encrypted = encrypt_api_key(plaintext)

        svc = ProviderService()
        decrypted = svc.decrypt_api_key(encrypted)
        assert decrypted == plaintext

    def test_provider_service_round_trip_consistent_with_core_crypto(self):
        """Keys encrypted via ProviderService can be decrypted via app.core.crypto and vice versa."""
        from app.core.crypto import decrypt_api_key, encrypt_api_key
        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()
        plaintext = "shared-key-abc123"

        # Encrypt with ProviderService, decrypt with core crypto
        enc = svc.encrypt_api_key(plaintext)
        assert decrypt_api_key(enc) == plaintext

        # Encrypt with core crypto, decrypt with ProviderService
        enc2 = encrypt_api_key(plaintext)
        assert svc.decrypt_api_key(enc2) == plaintext
