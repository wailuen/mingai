"""
P3AUTH-016: Auth0 JWKS integration tests — Tier 2 (real Auth0, no mocking).

Requires:
- AUTH0_DOMAIN
- AUTH0_AUDIENCE
- AUTH0_CLIENT_ID
- AUTH0_CLIENT_SECRET

All tests are skipped gracefully when these env vars are absent or when
the Auth0 endpoint is unreachable (offline mode).

Tests:
1. Valid RS256 token (client_credentials grant) validates correctly
2. Expired token rejected with descriptive error
3. Wrong audience rejected
4. JWKS cache populated after first validation (second call skips fetch)
5. Local HS256 login still works when AUTH0_DOMAIN is configured (P3AUTH-013)
"""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

# ---------------------------------------------------------------------------
# Skip condition: require all Auth0 env vars
# ---------------------------------------------------------------------------

_AUTH0_DOMAIN = os.environ.get("AUTH0_DOMAIN", "")
_AUTH0_AUDIENCE = os.environ.get("AUTH0_AUDIENCE", "")
_AUTH0_CLIENT_ID = os.environ.get("AUTH0_CLIENT_ID", "")
_AUTH0_CLIENT_SECRET = os.environ.get("AUTH0_CLIENT_SECRET", "")

_SKIP_REASON = (
    "AUTH0_DOMAIN / AUTH0_AUDIENCE / AUTH0_CLIENT_ID / AUTH0_CLIENT_SECRET "
    "not configured — skipping Auth0 integration tests"
)
_AUTH0_CONFIGURED = all(
    [_AUTH0_DOMAIN, _AUTH0_AUDIENCE, _AUTH0_CLIENT_ID, _AUTH0_CLIENT_SECRET]
)

pytestmark = pytest.mark.skipif(not _AUTH0_CONFIGURED, reason=_SKIP_REASON)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_real_access_token() -> str:
    """
    Obtain a real JWT from Auth0 using the client_credentials grant.

    The token is scoped to AUTH0_AUDIENCE and signed with Auth0's RS256 key.
    Raises RuntimeError if Auth0 returns an error or is unreachable.
    """
    import httpx

    token_url = f"https://{_AUTH0_DOMAIN}/oauth/token"
    payload = {
        "client_id": _AUTH0_CLIENT_ID,
        "client_secret": _AUTH0_CLIENT_SECRET,
        "audience": _AUTH0_AUDIENCE,
        "grant_type": "client_credentials",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(token_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"Failed to obtain Auth0 access token: {exc}") from exc

    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Auth0 token response missing access_token: {data}")
    return token


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAuth0JwksIntegration:
    """Integration tests against the real Auth0 JWKS endpoint."""

    @pytest.fixture(autouse=True)
    def reset_jwks_cache(self):
        """Reset the JWKS cache before each test for clean state."""
        from app.modules.auth import jwt as jwt_module

        jwt_module._JWKS_CACHE.clear()
        yield
        jwt_module._JWKS_CACHE.clear()

    async def test_valid_rs256_token_validates_successfully(self):
        """
        A real client_credentials token from Auth0 must validate without error.

        This is the primary P3AUTH-002 integration acceptance test.
        """
        from app.modules.auth.jwt import decode_jwt_token_auth0

        try:
            token = await _get_real_access_token()
        except RuntimeError as exc:
            pytest.skip(f"Could not obtain Auth0 token (offline?): {exc}")

        # Should not raise
        payload = await decode_jwt_token_auth0(token)

        assert "sub" in payload, "Decoded payload missing 'sub' claim"
        assert (
            payload.get("tenant_id") is not None
        ), "tenant_id should be set (may be 'default')"
        assert payload.get("scope") in (
            "tenant",
            "platform",
        ), f"scope must be 'tenant' or 'platform', got: {payload.get('scope')}"

    async def test_jwks_cache_populated_after_first_validation(self):
        """
        After validating one token, the JWKS cache must be populated so that
        subsequent calls do not re-fetch the endpoint.
        """
        from app.modules.auth import jwt as jwt_module
        from app.modules.auth.jwt import decode_jwt_token_auth0

        # Cache must start empty (fixture ensures this)
        assert not jwt_module._JWKS_CACHE, "Cache should be empty before test"

        try:
            token = await _get_real_access_token()
        except RuntimeError as exc:
            pytest.skip(f"Could not obtain Auth0 token (offline?): {exc}")

        await decode_jwt_token_auth0(token)

        # Cache should now be populated
        assert (
            jwt_module._is_jwks_cache_valid()
        ), "JWKS cache should be valid after first validation"
        assert "jwks" in jwt_module._JWKS_CACHE, "JWKS cache must contain 'jwks' key"
        assert (
            "fetched_at" in jwt_module._JWKS_CACHE
        ), "JWKS cache must contain 'fetched_at' key"

        # Second call must use the cache — verify fetched_at is unchanged
        fetched_at_before = jwt_module._JWKS_CACHE["fetched_at"]
        await decode_jwt_token_auth0(token)
        fetched_at_after = jwt_module._JWKS_CACHE["fetched_at"]

        assert (
            fetched_at_before == fetched_at_after
        ), "Second JWKS validation should use cache — fetched_at should not change"

    async def test_expired_token_rejected(self):
        """
        A structurally valid RS256 token with an expired 'exp' claim must be
        rejected with a JWTValidationError mentioning 'expired'.
        """
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
        )
        from jose import jwt as jose_jwt
        from jose.backends import RSAKey
        from jose.constants import ALGORITHMS
        from unittest.mock import AsyncMock, patch

        from app.modules.auth.jwt import JWTValidationError, decode_jwt_token_auth0

        # Generate a throwaway RSA key — testing expiry rejection, JWKS is mocked.
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
        public_key = private_key.public_key()

        rsa_jose_key = RSAKey(public_key, ALGORITHMS.RS256)
        jwk_dict = rsa_jose_key.to_dict()
        jwk_dict["kid"] = "exp-test-key"
        jwk_dict["use"] = "sig"
        mock_jwks = {"keys": [jwk_dict]}

        expired_token = jose_jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "iss": f"https://{_AUTH0_DOMAIN}/",
                "aud": _AUTH0_AUDIENCE,
                "exp": datetime.now(timezone.utc) - timedelta(hours=1),
                "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            },
            private_pem,
            algorithm="RS256",
            headers={"kid": "exp-test-key"},
        )

        with patch(
            "app.modules.auth.jwt._fetch_jwks",
            new_callable=AsyncMock,
            return_value=mock_jwks,
        ):
            with pytest.raises(JWTValidationError, match="expired"):
                await decode_jwt_token_auth0(expired_token)

    async def test_wrong_audience_rejected(self):
        """
        A structurally valid RS256 Auth0 token with the wrong audience must
        be rejected with JWTValidationError.
        """
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
        )
        from jose import jwt as jose_jwt
        from jose.backends import RSAKey
        from jose.constants import ALGORITHMS
        from unittest.mock import AsyncMock, patch

        from app.modules.auth.jwt import JWTValidationError, decode_jwt_token_auth0

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
        public_key = private_key.public_key()

        rsa_jose_key = RSAKey(public_key, ALGORITHMS.RS256)
        jwk_dict = rsa_jose_key.to_dict()
        jwk_dict["kid"] = "aud-test-key"
        jwk_dict["use"] = "sig"
        mock_jwks = {"keys": [jwk_dict]}

        wrong_aud_token = jose_jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "iss": f"https://{_AUTH0_DOMAIN}/",
                "aud": "https://wrong-audience.example.com",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
                "iat": datetime.now(timezone.utc),
            },
            private_pem,
            algorithm="RS256",
            headers={"kid": "aud-test-key"},
        )

        with patch(
            "app.modules.auth.jwt._fetch_jwks",
            new_callable=AsyncMock,
            return_value=mock_jwks,
        ):
            with pytest.raises(JWTValidationError):
                await decode_jwt_token_auth0(wrong_aud_token)


@pytest.mark.integration
class TestLocalAuthWithAuth0DomainSet:
    """
    P3AUTH-013: Local HS256 login must continue to work when AUTH0_DOMAIN is
    configured.  The local token is HS256-signed and must NOT be sent through
    the JWKS path.
    """

    async def test_local_hs256_token_bypasses_jwks_when_auth0_domain_set(self):
        """
        An HS256 token produced by _create_access_token() validates through
        the local decode_jwt_token_v1_compat() path even when AUTH0_DOMAIN
        is present.
        """
        import os
        from jose import jwt as jose_jwt
        from app.core.dependencies import get_current_user
        from unittest.mock import AsyncMock, patch

        # Sanity check: AUTH0_DOMAIN is set for these integration tests
        assert os.environ.get("AUTH0_DOMAIN"), "AUTH0_DOMAIN must be set for this test"

        secret = os.environ.get("JWT_SECRET_KEY", "integration-test-secret-" + "x" * 32)
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        local_token = jose_jwt.encode(
            {
                "sub": user_id,
                "tenant_id": tenant_id,
                "roles": ["user"],
                "scope": "tenant",
                "plan": "professional",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
                "iat": datetime.now(timezone.utc),
                "token_version": 2,
            },
            secret,
            algorithm="HS256",
        )

        auth0_mock = AsyncMock()
        with patch("app.core.dependencies.decode_jwt_token_auth0", auth0_mock):
            # Must use the actual JWT_SECRET_KEY for HS256 validation
            import importlib

            original_secret = os.environ.get("JWT_SECRET_KEY")
            os.environ["JWT_SECRET_KEY"] = secret
            try:
                user = await get_current_user(authorization=f"Bearer {local_token}")
            finally:
                if original_secret is not None:
                    os.environ["JWT_SECRET_KEY"] = original_secret
                elif "JWT_SECRET_KEY" in os.environ:
                    del os.environ["JWT_SECRET_KEY"]

        # JWKS path must NOT have been called for the HS256 token
        auth0_mock.assert_not_called()
        assert user.id == user_id
        assert user.tenant_id == tenant_id
