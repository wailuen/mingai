"""
TEST-P3AUTH-002: Auth0 JWKS validation — unit tests (mock-based, Tier 1).

Covers:
- decode_jwt_token_auth0() validates RS256 tokens using mocked JWKS
- JWKS cache TTL logic (populated after first call, not re-fetched within TTL)
- JWKS cache auto-invalidation on signature error + single retry
- Expired token rejected with descriptive error
- Wrong audience rejected
- Missing AUTH0_DOMAIN raises JWTValidationError
- _is_auth0_token() heuristic routing helper
- get_current_user() routes Auth0 tokens to JWKS path and HS256 tokens to local path

All HTTP calls are mocked — no real Auth0 network requests in unit tests.
"""
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from jose import jwt as jose_jwt

# ---------------------------------------------------------------------------
# Helpers: generate a throwaway RSA key pair for test tokens
# ---------------------------------------------------------------------------


def _gen_rsa_keypair():
    """
    Generate an ephemeral RSA-2048 key pair.

    Returns (private_pem_bytes, public_key_object).
    private_pem_bytes can be passed directly to jose_jwt.encode().
    public_key_object is used to build JWKS via jose's RSAKey.
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    private_pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=NoEncryption(),
    )
    return private_pem, private_key.public_key()


def _make_jwks_from_public_key(public_key, kid: str = "test-kid-1") -> dict:
    """Build a minimal JWKS dict from an RSA public_key object."""
    from jose.backends import RSAKey
    from jose.constants import ALGORITHMS

    rsa_key = RSAKey(public_key, ALGORITHMS.RS256)
    jwk_dict = rsa_key.to_dict()
    jwk_dict["kid"] = kid
    jwk_dict["use"] = "sig"
    return {"keys": [jwk_dict]}


def _make_rs256_token(
    private_pem: bytes,
    claims: dict,
    kid: str = "test-kid-1",
    auth0_domain: str = "test.auth0.example.com",
) -> str:
    """Sign a JWT with the provided PEM-encoded RSA private key."""
    defaults = {
        "sub": str(uuid.uuid4()),
        "iss": f"https://{auth0_domain}/",
        "aud": "https://api.test.example.com",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        "scope": "",
    }
    defaults.update(claims)
    return jose_jwt.encode(
        defaults, private_pem, algorithm="RS256", headers={"kid": kid}
    )


# ---------------------------------------------------------------------------
# _is_auth0_token tests
# ---------------------------------------------------------------------------


class TestIsAuth0Token:
    """Tests for the _is_auth0_token() routing heuristic."""

    def test_rs256_with_matching_issuer_returns_true(self):
        from app.modules.auth.jwt import _is_auth0_token

        private_pem, _ = _gen_rsa_keypair()
        domain = "mingai-dev.jp.auth0.com"
        token = _make_rs256_token(private_pem, {}, auth0_domain=domain)
        assert _is_auth0_token(token, domain) is True

    def test_hs256_token_returns_false(self):
        from app.modules.auth.jwt import _is_auth0_token

        hs256_token = jose_jwt.encode(
            {
                "sub": "user1",
                "tenant_id": "t1",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            },
            "secret",
            algorithm="HS256",
        )
        assert _is_auth0_token(hs256_token, "mingai-dev.jp.auth0.com") is False

    def test_rs256_with_wrong_issuer_returns_false(self):
        from app.modules.auth.jwt import _is_auth0_token

        private_pem, _ = _gen_rsa_keypair()
        token = _make_rs256_token(private_pem, {}, auth0_domain="other.auth0.com")
        assert _is_auth0_token(token, "mingai-dev.jp.auth0.com") is False

    def test_empty_token_returns_false(self):
        from app.modules.auth.jwt import _is_auth0_token

        assert _is_auth0_token("", "mingai-dev.jp.auth0.com") is False

    def test_garbage_token_returns_false(self):
        from app.modules.auth.jwt import _is_auth0_token

        assert _is_auth0_token("not.a.jwt", "mingai-dev.jp.auth0.com") is False


# ---------------------------------------------------------------------------
# decode_jwt_token_auth0 tests
# ---------------------------------------------------------------------------


class TestDecodeJwtTokenAuth0:
    """Tests for decode_jwt_token_auth0() with mocked JWKS endpoint."""

    @pytest.fixture(autouse=True)
    def reset_jwks_cache(self):
        """Clear the JWKS cache before each test to avoid cross-test pollution."""
        from app.modules.auth import jwt as jwt_module

        jwt_module._JWKS_CACHE.clear()
        yield
        jwt_module._JWKS_CACHE.clear()

    @pytest.fixture
    def keypair(self):
        private_pem, public_key = _gen_rsa_keypair()
        return private_pem, public_key

    @pytest.fixture
    def auth0_env(self, monkeypatch):
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.example.com")
        monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.test.example.com")

    async def test_valid_rs256_token_validates_successfully(self, keypair, auth0_env):
        """Valid RS256 token signed with matching key passes JWKS validation."""
        from app.modules.auth.jwt import decode_jwt_token_auth0

        private_pem, public_key = keypair
        kid = "key-001"
        jwks = _make_jwks_from_public_key(public_key, kid=kid)
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        token = _make_rs256_token(
            private_pem,
            {
                "sub": user_id,
                "https://mingai.app/tenant_id": tenant_id,
                "aud": "https://api.test.example.com",
                "iss": "https://test.auth0.example.com/",
            },
            kid=kid,
            auth0_domain="test.auth0.example.com",
        )

        with patch(
            "app.modules.auth.jwt._fetch_jwks",
            new_callable=AsyncMock,
            return_value=jwks,
        ):
            payload = await decode_jwt_token_auth0(token)

        assert payload["sub"] == user_id
        assert payload["tenant_id"] == tenant_id
        assert payload["scope"] == "tenant"

    async def test_tenant_id_falls_back_to_default_when_absent(
        self, keypair, auth0_env
    ):
        """Auth0 token without custom tenant claim falls back to 'default'."""
        from app.modules.auth.jwt import decode_jwt_token_auth0

        private_pem, public_key = keypair
        kid = "key-002"
        jwks = _make_jwks_from_public_key(public_key, kid=kid)

        token = _make_rs256_token(
            private_pem,
            {
                "aud": "https://api.test.example.com",
                "iss": "https://test.auth0.example.com/",
            },
            kid=kid,
            auth0_domain="test.auth0.example.com",
        )

        with patch(
            "app.modules.auth.jwt._fetch_jwks",
            new_callable=AsyncMock,
            return_value=jwks,
        ):
            payload = await decode_jwt_token_auth0(token)

        assert payload["tenant_id"] == "default"

    async def test_platform_scope_extracted_from_scope_string(self, keypair, auth0_env):
        """Auth0 token with 'platform' in scope string sets scope=platform."""
        from app.modules.auth.jwt import decode_jwt_token_auth0

        private_pem, public_key = keypair
        kid = "key-003"
        jwks = _make_jwks_from_public_key(public_key, kid=kid)

        token = _make_rs256_token(
            private_pem,
            {
                "scope": "openid platform read:all",
                "aud": "https://api.test.example.com",
                "iss": "https://test.auth0.example.com/",
            },
            kid=kid,
            auth0_domain="test.auth0.example.com",
        )

        with patch(
            "app.modules.auth.jwt._fetch_jwks",
            new_callable=AsyncMock,
            return_value=jwks,
        ):
            payload = await decode_jwt_token_auth0(token)

        assert payload["scope"] == "platform"

    async def test_expired_token_raises_jwt_validation_error(self, keypair, auth0_env):
        """Expired token raises JWTValidationError with 'expired' in message."""
        from app.modules.auth.jwt import JWTValidationError, decode_jwt_token_auth0

        private_pem, public_key = keypair
        kid = "key-004"
        jwks = _make_jwks_from_public_key(public_key, kid=kid)

        token = _make_rs256_token(
            private_pem,
            {
                "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
                "aud": "https://api.test.example.com",
                "iss": "https://test.auth0.example.com/",
            },
            kid=kid,
            auth0_domain="test.auth0.example.com",
        )

        with patch(
            "app.modules.auth.jwt._fetch_jwks",
            new_callable=AsyncMock,
            return_value=jwks,
        ):
            with pytest.raises(JWTValidationError, match="expired"):
                await decode_jwt_token_auth0(token)

    async def test_wrong_audience_raises_jwt_validation_error(self, keypair, auth0_env):
        """Token with wrong audience raises JWTValidationError."""
        from app.modules.auth.jwt import JWTValidationError, decode_jwt_token_auth0

        private_pem, public_key = keypair
        kid = "key-005"
        jwks = _make_jwks_from_public_key(public_key, kid=kid)

        token = _make_rs256_token(
            private_pem,
            {
                "aud": "https://wrong-audience.example.com",
                "iss": "https://test.auth0.example.com/",
            },
            kid=kid,
            auth0_domain="test.auth0.example.com",
        )

        with patch(
            "app.modules.auth.jwt._fetch_jwks",
            new_callable=AsyncMock,
            return_value=jwks,
        ):
            with pytest.raises(JWTValidationError):
                await decode_jwt_token_auth0(token)

    async def test_missing_auth0_domain_raises_error(self, monkeypatch):
        """Missing AUTH0_DOMAIN env var raises JWTValidationError."""
        from app.modules.auth.jwt import JWTValidationError, decode_jwt_token_auth0

        monkeypatch.delenv("AUTH0_DOMAIN", raising=False)

        with pytest.raises(JWTValidationError, match="AUTH0_DOMAIN"):
            await decode_jwt_token_auth0("some.token.value")

    async def test_empty_token_raises_error(self, auth0_env):
        """Empty token raises JWTValidationError."""
        from app.modules.auth.jwt import JWTValidationError, decode_jwt_token_auth0

        with pytest.raises(JWTValidationError, match="empty"):
            await decode_jwt_token_auth0("")

    async def test_unknown_kid_raises_error(self, keypair, auth0_env):
        """Token with kid not in JWKS raises JWTValidationError."""
        from app.modules.auth.jwt import JWTValidationError, decode_jwt_token_auth0

        private_pem, public_key = keypair
        # JWKS contains "known-kid" but token uses "unknown-kid"
        jwks = _make_jwks_from_public_key(public_key, kid="known-kid")

        token = _make_rs256_token(
            private_pem,
            {
                "aud": "https://api.test.example.com",
                "iss": "https://test.auth0.example.com/",
            },
            kid="unknown-kid",
            auth0_domain="test.auth0.example.com",
        )

        with patch(
            "app.modules.auth.jwt._fetch_jwks",
            new_callable=AsyncMock,
            return_value=jwks,
        ):
            with pytest.raises(JWTValidationError):
                await decode_jwt_token_auth0(token)


# ---------------------------------------------------------------------------
# JWKS cache behaviour tests
# ---------------------------------------------------------------------------


class TestJwksCache:
    """Tests for JWKS in-process cache TTL and invalidation behaviour."""

    @pytest.fixture(autouse=True)
    def reset_jwks_cache(self):
        from app.modules.auth import jwt as jwt_module

        jwt_module._JWKS_CACHE.clear()
        yield
        jwt_module._JWKS_CACHE.clear()

    def test_cache_valid_within_ttl(self):
        """_is_jwks_cache_valid() returns True within TTL window."""
        from app.modules.auth import jwt as jwt_module

        jwt_module._JWKS_CACHE["jwks"] = {"keys": []}
        jwt_module._JWKS_CACHE["fetched_at"] = time.monotonic() - 100  # 100s ago

        assert jwt_module._is_jwks_cache_valid() is True

    def test_cache_invalid_after_ttl(self):
        """_is_jwks_cache_valid() returns False after TTL expires."""
        from app.modules.auth import jwt as jwt_module

        jwt_module._JWKS_CACHE["jwks"] = {"keys": []}
        jwt_module._JWKS_CACHE["fetched_at"] = (
            time.monotonic() - jwt_module._JWKS_CACHE_TTL_SECONDS - 1
        )

        assert jwt_module._is_jwks_cache_valid() is False

    def test_cache_empty_returns_invalid(self):
        """_is_jwks_cache_valid() returns False when cache is empty."""
        from app.modules.auth import jwt as jwt_module

        assert jwt_module._is_jwks_cache_valid() is False

    def test_clear_jwks_cache_empties_dict(self):
        """_clear_jwks_cache() removes all entries from the cache."""
        from app.modules.auth import jwt as jwt_module

        jwt_module._JWKS_CACHE["jwks"] = {"keys": []}
        jwt_module._JWKS_CACHE["fetched_at"] = time.monotonic()
        jwt_module._clear_jwks_cache()

        assert jwt_module._JWKS_CACHE == {}

    async def test_second_call_uses_cache_no_extra_fetch(self, monkeypatch):
        """Valid cache prevents _fetch_jwks from being called again."""
        from app.modules.auth import jwt as jwt_module

        jwks = {"keys": [{"kid": "k1"}]}
        jwt_module._JWKS_CACHE["jwks"] = jwks
        jwt_module._JWKS_CACHE["fetched_at"] = time.monotonic()  # Just fetched

        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.example.com")

        fetch_mock = AsyncMock(return_value={"keys": []})
        with patch("app.modules.auth.jwt._fetch_jwks", fetch_mock):
            result = await jwt_module._get_jwks("test.auth0.example.com")

        assert result == jwks
        fetch_mock.assert_not_called()

    async def test_stale_cache_triggers_fetch(self, monkeypatch):
        """Stale cache causes _fetch_jwks to be called."""
        from app.modules.auth import jwt as jwt_module

        fresh_jwks = {"keys": [{"kid": "new-key"}]}
        jwt_module._JWKS_CACHE["jwks"] = {"keys": [{"kid": "old-key"}]}
        jwt_module._JWKS_CACHE["fetched_at"] = (
            time.monotonic() - jwt_module._JWKS_CACHE_TTL_SECONDS - 10
        )

        fetch_mock = AsyncMock(return_value=fresh_jwks)
        with patch("app.modules.auth.jwt._fetch_jwks", fetch_mock):
            result = await jwt_module._get_jwks("test.auth0.example.com")

        assert result == fresh_jwks
        fetch_mock.assert_called_once_with("test.auth0.example.com")

    async def test_signature_error_triggers_cache_invalidation_and_retry(
        self, monkeypatch
    ):
        """JWTError containing 'signature' clears cache and triggers one re-fetch."""
        from app.modules.auth import jwt as jwt_module

        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.example.com")
        monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.test.example.com")

        private_pem1, public_key1 = _gen_rsa_keypair()
        private_pem2, public_key2 = _gen_rsa_keypair()
        kid = "rotating-key"

        # JWKS initially has key1's public; token is signed with key2's private
        old_jwks = _make_jwks_from_public_key(public_key1, kid=kid)
        new_jwks = _make_jwks_from_public_key(public_key2, kid=kid)

        token = _make_rs256_token(
            private_pem2,
            {
                "aud": "https://api.test.example.com",
                "iss": "https://test.auth0.example.com/",
            },
            kid=kid,
            auth0_domain="test.auth0.example.com",
        )

        fetch_calls: list[str] = []

        async def _fetch_side_effect(domain):
            if not fetch_calls:
                fetch_calls.append("old")
                jwt_module._JWKS_CACHE["jwks"] = old_jwks
                jwt_module._JWKS_CACHE["fetched_at"] = time.monotonic()
                return old_jwks
            else:
                fetch_calls.append("new")
                jwt_module._JWKS_CACHE["jwks"] = new_jwks
                jwt_module._JWKS_CACHE["fetched_at"] = time.monotonic()
                return new_jwks

        with patch("app.modules.auth.jwt._fetch_jwks", side_effect=_fetch_side_effect):
            payload = await jwt_module.decode_jwt_token_auth0(token)

        assert payload["sub"] is not None
        assert (
            len(fetch_calls) == 2
        ), f"Expected 2 fetch calls (initial + retry), got: {fetch_calls}"


# ---------------------------------------------------------------------------
# get_current_user routing tests
# ---------------------------------------------------------------------------


class TestGetCurrentUserRouting:
    """Tests confirming get_current_user() routes to the correct validation path."""

    @pytest.fixture(autouse=True)
    def reset_jwks_cache(self):
        from app.modules.auth import jwt as jwt_module

        jwt_module._JWKS_CACHE.clear()
        yield
        jwt_module._JWKS_CACHE.clear()

    async def test_hs256_token_uses_local_path_when_auth0_domain_set(self, monkeypatch):
        """HS256 local tokens bypass JWKS even when AUTH0_DOMAIN is configured."""
        from app.core.dependencies import get_current_user

        monkeypatch.setenv("AUTH0_DOMAIN", "mingai-dev.jp.auth0.com")
        monkeypatch.setenv("JWT_SECRET_KEY", "a" * 64)
        monkeypatch.setenv("JWT_ALGORITHM", "HS256")

        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        token = jose_jwt.encode(
            {
                "sub": user_id,
                "tenant_id": tenant_id,
                "roles": ["user"],
                "scope": "tenant",
                "plan": "professional",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
                "iat": datetime.now(timezone.utc),
            },
            "a" * 64,
            algorithm="HS256",
        )

        auth0_mock = AsyncMock()
        with patch("app.core.dependencies.decode_jwt_token_auth0", auth0_mock):
            user = await get_current_user(authorization=f"Bearer {token}")

        auth0_mock.assert_not_called()
        assert user.id == user_id
        assert user.tenant_id == tenant_id

    async def test_rs256_auth0_token_uses_jwks_path(self, monkeypatch):
        """RS256 Auth0 tokens are routed to decode_jwt_token_auth0()."""
        from app.core.dependencies import get_current_user

        domain = "mingai-dev.jp.auth0.com"
        monkeypatch.setenv("AUTH0_DOMAIN", domain)

        private_pem, _ = _gen_rsa_keypair()
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        token = _make_rs256_token(
            private_pem,
            {
                "sub": user_id,
                "https://mingai.app/tenant_id": tenant_id,
                "aud": "https://api.mingai.app",
                "iss": f"https://{domain}/",
            },
            auth0_domain=domain,
        )

        fake_payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "roles": ["user"],
            "scope": "tenant",
            "plan": "professional",
            "email": "user@example.com",
        }

        auth0_mock = AsyncMock(return_value=fake_payload)
        with patch("app.core.dependencies.decode_jwt_token_auth0", auth0_mock):
            user = await get_current_user(authorization=f"Bearer {token}")

        auth0_mock.assert_called_once_with(token)
        assert user.id == user_id
        assert user.tenant_id == tenant_id

    async def test_no_auth0_domain_always_uses_local_path(self, monkeypatch):
        """AUTH0_DOMAIN absent means all tokens go to local HS256 path."""
        from app.core.dependencies import get_current_user

        monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
        monkeypatch.setenv("JWT_SECRET_KEY", "b" * 64)
        monkeypatch.setenv("JWT_ALGORITHM", "HS256")

        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        token = jose_jwt.encode(
            {
                "sub": user_id,
                "tenant_id": tenant_id,
                "roles": [],
                "scope": "tenant",
                "plan": "professional",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
                "iat": datetime.now(timezone.utc),
            },
            "b" * 64,
            algorithm="HS256",
        )

        auth0_mock = AsyncMock()
        with patch("app.core.dependencies.decode_jwt_token_auth0", auth0_mock):
            user = await get_current_user(authorization=f"Bearer {token}")

        auth0_mock.assert_not_called()
        assert user.id == user_id

    async def test_missing_authorization_header_raises_401(self):
        """Missing Authorization header raises 401."""
        from app.core.dependencies import get_current_user
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(authorization=None)

        assert exc_info.value.status_code == 401

    async def test_bearer_scheme_enforced(self):
        """Non-Bearer Authorization scheme raises 401."""
        from app.core.dependencies import get_current_user
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(authorization="Basic dXNlcjpwYXNz")

        assert exc_info.value.status_code == 401
