"""
Unit tests for auth routes (API-003 to API-006).

Tests the FastAPI auth endpoints using httpx TestClient.
Tier 1: Fast, isolated, can use mocking for JWT/env vars.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt


# Test constants - NEVER use in production
TEST_JWT_SECRET = "a" * 64  # 64 chars, well above 32-char minimum
TEST_JWT_ALGORITHM = "HS256"
TEST_PLATFORM_EMAIL = "admin@test.mingai.io"
TEST_PLATFORM_PASS = "test-secure-password-123"


def _make_test_token(
    user_id: str = "00000000-0000-0000-0000-000000000001",
    tenant_id: str = "default",
    roles: list[str] | None = None,
    scope: str = "platform",
    plan: str = "enterprise",
    email: str = TEST_PLATFORM_EMAIL,
    expired: bool = False,
) -> str:
    """Create a test JWT token with given claims."""
    if roles is None:
        roles = ["platform_admin"]

    now = datetime.now(timezone.utc)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)

    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": plan,
        "email": email,
        "exp": exp,
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


@pytest.fixture
def env_vars():
    """Set required environment variables for auth routes.

    AUTH0_DOMAIN is explicitly cleared so that the local HS256 JWT path is
    exercised throughout these tests.  Auth0-specific behaviour is tested in
    test_auth0_jwks.py.
    """
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": "15",
        "PLATFORM_ADMIN_EMAIL": TEST_PLATFORM_EMAIL,
        "PLATFORM_ADMIN_PASS": TEST_PLATFORM_PASS,
        "SEED_TENANT_NAME": "default",
        "FRONTEND_URL": "http://localhost:3022",
        # Force local auth path — disable Auth0 integration for these tests
        "AUTH0_DOMAIN": "",
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture
def client(env_vars):
    """Create test client with the FastAPI app including auth routes."""
    from app.main import app

    return TestClient(app)


@pytest.fixture
def client_with_router(env_vars):
    """Create test client that includes the API router with auth endpoints."""
    from fastapi import FastAPI

    from app.api.router import router

    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


class TestLocalLogin:
    """API-003: POST /api/v1/auth/local/login tests."""

    def test_login_with_valid_credentials_returns_token(self, client_with_router):
        """Successful login returns JWT access token with bearer type."""
        response = client_with_router.post(
            "/api/v1/auth/local/login",
            json={"email": TEST_PLATFORM_EMAIL, "password": TEST_PLATFORM_PASS},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 15 * 60  # 15 minutes in seconds

    def test_login_token_contains_required_claims(self, client_with_router):
        """Returned JWT token contains all required v2 claims."""
        response = client_with_router.post(
            "/api/v1/auth/local/login",
            json={"email": TEST_PLATFORM_EMAIL, "password": TEST_PLATFORM_PASS},
        )
        token = response.json()["access_token"]
        payload = jwt.decode(token, TEST_JWT_SECRET, algorithms=[TEST_JWT_ALGORITHM])

        assert payload["sub"] == "00000000-0000-0000-0000-000000000001"
        assert payload["tenant_id"] == "default"
        assert payload["roles"] == ["platform_admin"]
        assert payload["scope"] == "platform"
        assert payload["plan"] == "enterprise"
        assert payload["token_version"] == 2

    def test_login_with_wrong_password_returns_401(self, client_with_router):
        """Wrong password returns 401 with generic error message."""
        response = client_with_router.post(
            "/api/v1/auth/local/login",
            json={"email": TEST_PLATFORM_EMAIL, "password": "wrong-password"},
        )
        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["detail"]

    def test_login_with_wrong_email_returns_401(self, client_with_router):
        """Wrong email returns 401 with same generic error (no user enumeration)."""
        response = client_with_router.post(
            "/api/v1/auth/local/login",
            json={"email": "wrong@test.com", "password": TEST_PLATFORM_PASS},
        )
        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["detail"]

    def test_login_with_empty_email_returns_422(self, client_with_router):
        """Empty email fails validation with 422."""
        response = client_with_router.post(
            "/api/v1/auth/local/login",
            json={"email": "", "password": TEST_PLATFORM_PASS},
        )
        assert response.status_code == 422

    def test_login_with_invalid_email_format_returns_422(self, client_with_router):
        """Email without @ fails validation with 422."""
        response = client_with_router.post(
            "/api/v1/auth/local/login",
            json={"email": "not-an-email", "password": TEST_PLATFORM_PASS},
        )
        assert response.status_code == 422

    def test_login_with_empty_password_returns_422(self, client_with_router):
        """Empty password fails validation with 422."""
        response = client_with_router.post(
            "/api/v1/auth/local/login",
            json={"email": TEST_PLATFORM_EMAIL, "password": ""},
        )
        assert response.status_code == 422

    def test_login_normalizes_email_to_lowercase(self, client_with_router):
        """Login accepts email in any case and normalizes to lowercase."""
        response = client_with_router.post(
            "/api/v1/auth/local/login",
            json={
                "email": TEST_PLATFORM_EMAIL.upper(),
                "password": TEST_PLATFORM_PASS,
            },
        )
        assert response.status_code == 200

    def test_login_without_jwt_secret_returns_500(self, client_with_router):
        """Missing JWT_SECRET_KEY returns 500 server error."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": ""}, clear=False):
            response = client_with_router.post(
                "/api/v1/auth/local/login",
                json={
                    "email": TEST_PLATFORM_EMAIL,
                    "password": TEST_PLATFORM_PASS,
                },
            )
            assert response.status_code == 500

    def test_login_without_platform_credentials_returns_401(self, client_with_router):
        """Missing PLATFORM_ADMIN_EMAIL/PASS env vars returns 401."""
        with patch.dict(
            os.environ,
            {"PLATFORM_ADMIN_EMAIL": "", "PLATFORM_ADMIN_PASS": ""},
            clear=False,
        ):
            response = client_with_router.post(
                "/api/v1/auth/local/login",
                json={
                    "email": TEST_PLATFORM_EMAIL,
                    "password": TEST_PLATFORM_PASS,
                },
            )
            assert response.status_code == 401


class TestTokenRefresh:
    """API-004: POST /api/v1/auth/token/refresh tests."""

    def test_refresh_with_valid_token_returns_new_token(self, client_with_router):
        """Token refresh with valid Bearer token returns a new access token."""
        token = _make_test_token()
        response = client_with_router.post(
            "/api/v1/auth/token/refresh",
            json={"refresh_token": "dummy-refresh-token"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        # New token should be different from old one (different iat/exp)
        assert data["access_token"] != token

    def test_refresh_without_auth_returns_401(self, client_with_router):
        """Token refresh without Authorization header returns 401."""
        response = client_with_router.post(
            "/api/v1/auth/token/refresh",
            json={"refresh_token": "dummy-refresh-token"},
        )
        assert response.status_code == 401

    def test_refresh_with_expired_token_returns_401(self, client_with_router):
        """Token refresh with expired Bearer token returns 401."""
        expired_token = _make_test_token(expired=True)
        response = client_with_router.post(
            "/api/v1/auth/token/refresh",
            json={"refresh_token": "dummy-refresh-token"},
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401


class TestLogout:
    """API-005: POST /api/v1/auth/logout tests."""

    def test_logout_with_valid_token_returns_204(self, client_with_router):
        """Logout with valid Bearer token returns 204 No Content."""
        token = _make_test_token()
        response = client_with_router.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204

    def test_logout_without_auth_returns_401(self, client_with_router):
        """Logout without Authorization header returns 401."""
        response = client_with_router.post("/api/v1/auth/logout")
        assert response.status_code == 401


class TestGetCurrentUser:
    """API-006: GET /api/v1/auth/current tests."""

    def test_get_current_user_returns_user_info(self, client_with_router):
        """Get current user returns all expected fields."""
        token = _make_test_token()
        response = client_with_router.get(
            "/api/v1/auth/current",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "00000000-0000-0000-0000-000000000001"
        assert data["tenant_id"] == "default"
        assert data["roles"] == ["platform_admin"]
        assert data["scope"] == "platform"
        assert data["plan"] == "enterprise"

    def test_get_current_user_without_auth_returns_401(self, client_with_router):
        """Get current user without auth returns 401."""
        response = client_with_router.get("/api/v1/auth/current")
        assert response.status_code == 401

    def test_get_current_user_with_invalid_token_returns_401(self, client_with_router):
        """Get current user with invalid token returns 401."""
        response = client_with_router.get(
            "/api/v1/auth/current",
            headers={"Authorization": "Bearer invalid-token-here"},
        )
        assert response.status_code == 401

    def test_get_current_user_with_tenant_scope(self, client_with_router):
        """Get current user with tenant scope returns correct scope."""
        token = _make_test_token(
            user_id="user-123",
            tenant_id="tenant-abc",
            roles=["user"],
            scope="tenant",
            plan="professional",
        )
        response = client_with_router.get(
            "/api/v1/auth/current",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["scope"] == "tenant"
        assert data["plan"] == "professional"
