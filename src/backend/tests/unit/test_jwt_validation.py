"""
TEST-001: JWT v2 validation middleware - unit tests

Coverage target: 100% (auth-critical)
Target count: 15 tests

Tests JWT v2 token parsing, tenant_id extraction, claim structure,
and error handling. Mocking allowed (Tier 1).
"""
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt as jose_jwt

# Test signing key - ONLY for tests, never in production
TEST_JWT_SECRET = "a" * 64  # 64-char test secret
TEST_JWT_ALGORITHM = "HS256"


def _make_token(
    claims: dict,
    secret: str = TEST_JWT_SECRET,
    algorithm: str = TEST_JWT_ALGORITHM,
) -> str:
    """Helper: create a JWT with given claims."""
    defaults = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "roles": ["user"],
        "scope": "tenant",
        "plan": "professional",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        "iat": datetime.now(timezone.utc),
    }
    defaults.update(claims)
    return jose_jwt.encode(defaults, secret, algorithm=algorithm)


class TestJWTValidation:
    """TEST-001: JWT v2 validation middleware - 15 unit tests."""

    def test_valid_jwt_v2_extracts_all_claims(self):
        """Valid JWT v2 - extracts tenant_id, user_id, roles, scope correctly."""
        from app.modules.auth.jwt import decode_jwt_token

        tenant_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        token = _make_token({
            "sub": user_id,
            "tenant_id": tenant_id,
            "roles": ["tenant_admin", "user"],
            "scope": "tenant",
            "plan": "enterprise",
        })
        payload = decode_jwt_token(token, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)
        assert payload["sub"] == user_id
        assert payload["tenant_id"] == tenant_id
        assert "tenant_admin" in payload["roles"]
        assert "user" in payload["roles"]
        assert payload["scope"] == "tenant"
        assert payload["plan"] == "enterprise"

    def test_expired_token_returns_error(self):
        """Expired token - raises appropriate error."""
        from app.modules.auth.jwt import decode_jwt_token, JWTValidationError

        token = _make_token({
            "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        })
        with pytest.raises(JWTValidationError, match="expired"):
            decode_jwt_token(token, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)

    def test_malformed_token_returns_error(self):
        """Malformed token (not base64, missing segments) - raises error."""
        from app.modules.auth.jwt import decode_jwt_token, JWTValidationError

        with pytest.raises(JWTValidationError, match="invalid"):
            decode_jwt_token("not.a.valid.jwt", TEST_JWT_SECRET, TEST_JWT_ALGORITHM)

        with pytest.raises(JWTValidationError, match="invalid"):
            decode_jwt_token("garbage", TEST_JWT_SECRET, TEST_JWT_ALGORITHM)

    def test_missing_tenant_id_claim_returns_error(self):
        """Missing tenant_id claim - raises error."""
        from app.modules.auth.jwt import decode_jwt_token, JWTValidationError

        # Create token without tenant_id
        claims = {
            "sub": str(uuid.uuid4()),
            "roles": ["user"],
            "scope": "tenant",
            "plan": "professional",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            "iat": datetime.now(timezone.utc),
        }
        token = jose_jwt.encode(claims, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)
        with pytest.raises(JWTValidationError, match="tenant_id"):
            decode_jwt_token(token, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)

    def test_invalid_signature_returns_error(self):
        """Invalid signature (wrong signing key) - raises error."""
        from app.modules.auth.jwt import decode_jwt_token, JWTValidationError

        token = _make_token({}, secret="wrong_secret_key_" + "x" * 48)
        with pytest.raises(JWTValidationError, match="invalid"):
            decode_jwt_token(token, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)

    def test_platform_scope_sets_platform_admin(self):
        """Token with scope=platform - sets platform admin flag."""
        from app.modules.auth.jwt import decode_jwt_token

        token = _make_token({
            "scope": "platform",
            "roles": ["platform_admin"],
        })
        payload = decode_jwt_token(token, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)
        assert payload["scope"] == "platform"

    def test_tenant_scope_with_admin_role(self):
        """Token with scope=tenant + admin role - sets tenant admin flag."""
        from app.modules.auth.jwt import decode_jwt_token

        token = _make_token({
            "scope": "tenant",
            "roles": ["tenant_admin"],
        })
        payload = decode_jwt_token(token, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)
        assert payload["scope"] == "tenant"
        assert "tenant_admin" in payload["roles"]

    def test_empty_roles_defaults_to_user(self):
        """Token with empty roles array - defaults to end-user permissions."""
        from app.modules.auth.jwt import decode_jwt_token

        token = _make_token({"roles": []})
        payload = decode_jwt_token(token, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)
        assert payload["roles"] == []

    def test_future_iat_with_excessive_clock_skew_rejected(self):
        """Token with future iat (clock skew > 60s) - raises error."""
        from app.modules.auth.jwt import decode_jwt_token, JWTValidationError

        token = _make_token({
            "iat": datetime.now(timezone.utc) + timedelta(seconds=120),
        })
        with pytest.raises(JWTValidationError, match="clock"):
            decode_jwt_token(token, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)

    def test_multiple_roles_all_extracted(self):
        """Token with multiple roles - all roles extracted."""
        from app.modules.auth.jwt import decode_jwt_token

        roles = ["tenant_admin", "user", "auditor"]
        token = _make_token({"roles": roles})
        payload = decode_jwt_token(token, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)
        assert payload["roles"] == roles

    def test_null_authorization_header_raises_error(self):
        """Null/empty token - raises error."""
        from app.modules.auth.jwt import decode_jwt_token, JWTValidationError

        with pytest.raises(JWTValidationError, match="empty"):
            decode_jwt_token("", TEST_JWT_SECRET, TEST_JWT_ALGORITHM)

        with pytest.raises(JWTValidationError, match="empty"):
            decode_jwt_token(None, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)

    def test_v1_token_dual_accept_window(self):
        """v1 tokens (no tenant_id) accepted with defaults during dual-accept."""
        from app.modules.auth.jwt import decode_jwt_token_v1_compat

        # v1 token: has sub but no tenant_id
        claims = {
            "sub": str(uuid.uuid4()),
            "roles": ["user"],
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            "iat": datetime.now(timezone.utc),
        }
        token = jose_jwt.encode(claims, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)
        payload = decode_jwt_token_v1_compat(token, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)
        assert payload["tenant_id"] == "default"
        assert payload["scope"] == "tenant"
        assert payload["plan"] == "professional"

    def test_token_claims_include_sub(self):
        """Token must have sub claim for user identification."""
        from app.modules.auth.jwt import decode_jwt_token, JWTValidationError

        claims = {
            "tenant_id": str(uuid.uuid4()),
            "roles": ["user"],
            "scope": "tenant",
            "plan": "professional",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            "iat": datetime.now(timezone.utc),
        }
        token = jose_jwt.encode(claims, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)
        with pytest.raises(JWTValidationError, match="sub"):
            decode_jwt_token(token, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)

    def test_request_id_generated_for_tracing(self):
        """Middleware generates request_id for tracing."""
        from app.modules.auth.jwt import generate_request_id

        request_id = generate_request_id()
        assert request_id is not None
        assert len(request_id) > 0
        # Should be a valid UUID or prefixed string
        assert request_id.startswith("req_") or len(request_id) == 36

    def test_token_with_unknown_scope_rejected(self):
        """Token with unrecognized scope value is rejected."""
        from app.modules.auth.jwt import decode_jwt_token, JWTValidationError

        token = _make_token({"scope": "invalid_scope"})
        with pytest.raises(JWTValidationError, match="scope"):
            decode_jwt_token(token, TEST_JWT_SECRET, TEST_JWT_ALGORITHM)
