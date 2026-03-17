"""
TEST-P3AUTH-017: JWT v1/v2 dual acceptance integration tests.

Verifies that both HS256 local tokens AND RS256 Auth0 tokens are accepted
by the same protected endpoint (/api/v1/auth/current).

Tests:
1. HS256 v1 token (no tenant_id) accepted with default tenant_id="default"
2. HS256 v2 token (with tenant_id) accepted — correct tenant_id returned
3. RS256 Auth0 token accepted on same endpoint (if AUTH0_DOMAIN configured)
4. Both token types produce identical CurrentUser field keys in response
5. Expired HS256 token rejected with 401

Uses real JWT library signing — no mocking of token validation logic.
Auth0 RS256 tests use an ephemeral RSA keypair with a mocked JWKS endpoint
so they run without network access, but skip gracefully when AUTH0_DOMAIN
is absent from the environment.

Tier 2 (integration): uses the session-scoped TestClient from root conftest.
"""
import os
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
from jose.backends import RSAKey
from jose.constants import ALGORITHMS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AUTH0_DOMAIN = os.environ.get("AUTH0_DOMAIN", "")
_AUTH0_AUDIENCE = os.environ.get("AUTH0_AUDIENCE", "https://api.mingai.app")

_AUTH0_CONFIGURED = bool(_AUTH0_DOMAIN)

_AUTH0_SKIP_REASON = (
    "AUTH0_DOMAIN not configured — skipping Auth0 RS256 dual-acceptance tests"
)

# Test HS256 secret — isolated from production JWT_SECRET_KEY
_TEST_HS256_SECRET = "x" * 64
_TEST_ALGORITHM = "HS256"

# The protected endpoint under test
_ENDPOINT = "/api/v1/auth/current"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hs256_v1_token(user_id: str) -> str:
    """
    Build an HS256 v1 token (no tenant_id claim) signed with _TEST_HS256_SECRET.

    v1 tokens trigger the backward-compat path which injects tenant_id="default".
    """
    return jose_jwt.encode(
        {
            "sub": user_id,
            # Intentionally omit tenant_id to exercise v1 compat path
            "roles": ["user"],
            "scope": "tenant",
            "plan": "professional",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            "iat": datetime.now(timezone.utc),
        },
        _TEST_HS256_SECRET,
        algorithm=_TEST_ALGORITHM,
    )


def _make_hs256_v2_token(user_id: str, tenant_id: str) -> str:
    """
    Build an HS256 v2 token (with tenant_id claim) signed with _TEST_HS256_SECRET.
    """
    return jose_jwt.encode(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "roles": ["tenant_admin"],
            "scope": "tenant",
            "plan": "professional",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            "iat": datetime.now(timezone.utc),
            "token_version": 2,
        },
        _TEST_HS256_SECRET,
        algorithm=_TEST_ALGORITHM,
    )


def _make_expired_hs256_token(user_id: str, tenant_id: str) -> str:
    """Build an already-expired HS256 v2 token."""
    return jose_jwt.encode(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "roles": [],
            "scope": "tenant",
            "plan": "professional",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "token_version": 2,
        },
        _TEST_HS256_SECRET,
        algorithm=_TEST_ALGORITHM,
    )


def _gen_rsa_keypair():
    """Generate an ephemeral RSA-2048 key pair for RS256 test tokens."""
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


def _make_jwks(public_key, kid: str = "test-kid") -> dict:
    """Build a minimal JWKS dict from an RSA public key object."""
    rsa_key = RSAKey(public_key, ALGORITHMS.RS256)
    jwk_dict = rsa_key.to_dict()
    jwk_dict["kid"] = kid
    jwk_dict["use"] = "sig"
    return {"keys": [jwk_dict]}


def _make_rs256_token(
    private_pem: bytes,
    user_id: str,
    tenant_id: str,
    auth0_domain: str,
    kid: str = "test-kid",
    audience: str = _AUTH0_AUDIENCE,
    expired: bool = False,
) -> str:
    """Sign a JWT with the provided PEM-encoded RSA private key."""
    exp = (
        datetime.now(timezone.utc) - timedelta(hours=1)
        if expired
        else datetime.now(timezone.utc) + timedelta(minutes=15)
    )
    claims = {
        "sub": user_id,
        "iss": f"https://{auth0_domain}/",
        "aud": audience,
        "iat": datetime.now(timezone.utc),
        "exp": exp,
        # Custom claim for tenant_id (Auth0 namespace)
        "https://mingai.app/tenant_id": tenant_id,
        "scope": "",
    }
    return jose_jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestJwtDualAcceptance:
    """
    P3AUTH-017: Both HS256 local tokens and RS256 Auth0 tokens are accepted
    by the same protected endpoint.
    """

    @pytest.fixture(autouse=True)
    def _patch_jwt_secret(self, monkeypatch):
        """
        Override JWT_SECRET_KEY to use the isolated test secret for HS256 tests.

        This ensures these tests are fully hermetic and do not depend on whether
        a real JWT_SECRET_KEY is present in the environment.
        """
        monkeypatch.setenv("JWT_SECRET_KEY", _TEST_HS256_SECRET)
        monkeypatch.setenv("JWT_ALGORITHM", _TEST_ALGORITHM)

    @pytest.fixture(autouse=True)
    def _clear_jwks_cache(self):
        """Reset JWKS in-process cache before and after each test."""
        from app.modules.auth import jwt as jwt_module

        jwt_module._JWKS_CACHE.clear()
        yield
        jwt_module._JWKS_CACHE.clear()

    # ------------------------------------------------------------------
    # Test 1: HS256 v1 token (no tenant_id) → tenant_id defaults to "default"
    # ------------------------------------------------------------------

    def test_v1_hs256_token_accepted_with_default_tenant(self, client):
        """
        An HS256 token without a tenant_id claim is accepted.
        The response tenant_id must be 'default' (v1 compat fallback).
        """
        user_id = str(uuid.uuid4())
        token = _make_hs256_v1_token(user_id)

        response = client.get(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {token}"},
        )

        assert (
            response.status_code == 200
        ), f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert data["id"] == user_id
        assert data["tenant_id"] == "default", (
            f"v1 token without tenant_id must default to 'default', "
            f"got: {data['tenant_id']}"
        )

    # ------------------------------------------------------------------
    # Test 2: HS256 v2 token (with tenant_id) accepted
    # ------------------------------------------------------------------

    def test_v2_hs256_token_accepted(self, client):
        """
        An HS256 v2 token with an explicit tenant_id is accepted.
        The response tenant_id must match the token claim exactly.
        """
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        token = _make_hs256_v2_token(user_id, tenant_id)

        response = client.get(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {token}"},
        )

        assert (
            response.status_code == 200
        ), f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert data["id"] == user_id
        assert (
            data["tenant_id"] == tenant_id
        ), f"v2 token tenant_id mismatch: expected {tenant_id}, got {data['tenant_id']}"

    # ------------------------------------------------------------------
    # Test 3: RS256 Auth0 token accepted (skipped when AUTH0_DOMAIN absent)
    # ------------------------------------------------------------------

    @pytest.mark.skipif(not _AUTH0_CONFIGURED, reason=_AUTH0_SKIP_REASON)
    def test_rs256_auth0_token_accepted(self, client, monkeypatch):
        """
        An RS256 token (signed with a throwaway RSA keypair, JWKS mocked) is
        accepted by the same endpoint when AUTH0_DOMAIN is configured.

        Real JWKS fetch is intercepted so this test runs without network access.
        The Auth0 routing heuristic (_is_auth0_token) is exercised end-to-end.
        """
        private_pem, public_key = _gen_rsa_keypair()
        kid = "p3auth017-test-kid"
        jwks = _make_jwks(public_key, kid=kid)

        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        monkeypatch.setenv("AUTH0_DOMAIN", _AUTH0_DOMAIN)
        monkeypatch.setenv("AUTH0_AUDIENCE", _AUTH0_AUDIENCE)

        token = _make_rs256_token(
            private_pem,
            user_id=user_id,
            tenant_id=tenant_id,
            auth0_domain=_AUTH0_DOMAIN,
            kid=kid,
            audience=_AUTH0_AUDIENCE,
        )

        with patch(
            "app.modules.auth.jwt._fetch_jwks",
            new_callable=AsyncMock,
            return_value=jwks,
        ):
            response = client.get(
                _ENDPOINT,
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200, (
            f"RS256 Auth0 token rejected — expected 200, got "
            f"{response.status_code}: {response.text}"
        )

        data = response.json()
        assert data["id"] == user_id
        assert data["tenant_id"] == tenant_id

    # ------------------------------------------------------------------
    # Test 4: Both token types produce identical CurrentUser field keys
    # ------------------------------------------------------------------

    @pytest.mark.skipif(not _AUTH0_CONFIGURED, reason=_AUTH0_SKIP_REASON)
    def test_both_token_types_produce_identical_user_structure(
        self, client, monkeypatch
    ):
        """
        An HS256 v2 token and an RS256 Auth0 token must yield responses with
        identical field keys (the schema must not diverge between auth paths).
        """
        # --- HS256 response ---
        hs_user_id = str(uuid.uuid4())
        hs_tenant_id = str(uuid.uuid4())
        hs_token = _make_hs256_v2_token(hs_user_id, hs_tenant_id)

        hs_response = client.get(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {hs_token}"},
        )
        assert (
            hs_response.status_code == 200
        ), f"HS256 token rejected: {hs_response.status_code} {hs_response.text}"
        hs_fields = set(hs_response.json().keys())

        # --- RS256 response ---
        private_pem, public_key = _gen_rsa_keypair()
        kid = "p3auth017-struct-kid"
        jwks = _make_jwks(public_key, kid=kid)

        rs_user_id = str(uuid.uuid4())
        rs_tenant_id = str(uuid.uuid4())

        monkeypatch.setenv("AUTH0_DOMAIN", _AUTH0_DOMAIN)
        monkeypatch.setenv("AUTH0_AUDIENCE", _AUTH0_AUDIENCE)

        rs_token = _make_rs256_token(
            private_pem,
            user_id=rs_user_id,
            tenant_id=rs_tenant_id,
            auth0_domain=_AUTH0_DOMAIN,
            kid=kid,
            audience=_AUTH0_AUDIENCE,
        )

        with patch(
            "app.modules.auth.jwt._fetch_jwks",
            new_callable=AsyncMock,
            return_value=jwks,
        ):
            rs_response = client.get(
                _ENDPOINT,
                headers={"Authorization": f"Bearer {rs_token}"},
            )

        assert (
            rs_response.status_code == 200
        ), f"RS256 token rejected: {rs_response.status_code} {rs_response.text}"
        rs_fields = set(rs_response.json().keys())

        assert hs_fields == rs_fields, (
            f"HS256 and RS256 responses have divergent field sets.\n"
            f"  HS256-only fields : {hs_fields - rs_fields}\n"
            f"  RS256-only fields : {rs_fields - hs_fields}"
        )

    # ------------------------------------------------------------------
    # Test 5: Expired HS256 token rejected with 401
    # ------------------------------------------------------------------

    def test_expired_hs256_token_rejected(self, client):
        """
        An expired HS256 token must be rejected with HTTP 401.
        """
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        token = _make_expired_hs256_token(user_id, tenant_id)

        response = client.get(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 401, (
            f"Expired token should return 401, got {response.status_code}: "
            f"{response.text}"
        )
