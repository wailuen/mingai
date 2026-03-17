"""
Unit tests for P3AUTH-005/006/007/019 — OIDC/Google/Okta SSO wizard.

Tests:
 1. OIDC discovery extracts authorization_endpoint, token_endpoint, jwks_uri
 2. OIDC discovery missing required fields → 422
 3. OIDC discovery timeout → 422 with timeout message
 4. Client secret not present in returned response after configuration (vault ref replaces it)
 5. OIDC connection already configured → 409
 6. Google configuration creates connection with correct strategy "google-oauth2"
 7. Okta configuration constructs discovery URL from okta_domain
 8. Okta invalid domain (timeout) → 422
 9. OIDC test endpoint returns correct URL format

All DB calls and HTTP calls are mocked (Tier 1 unit tests).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "c" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "bbbbcccc-dddd-eeee-ffff-aaaabbbbcccc"
TEST_ACTOR_ID = "actor-user-oidc-001"

_GOOD_DISCOVERY_DOC = {
    "issuer": "https://accounts.google.com",
    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_endpoint": "https://oauth2.googleapis.com/token",
    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
    "response_types_supported": ["code", "token", "id_token"],
}


# ---------------------------------------------------------------------------
# JWT factories
# ---------------------------------------------------------------------------


def _make_tenant_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": TEST_ACTOR_ID,
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "enterprise",
        "email": "admin@example.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_viewer_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "viewer-oidc-id",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["viewer"],
        "scope": "tenant",
        "plan": "professional",
        "email": "viewer@example.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
        "AUTH0_DOMAIN": "mingai-dev.jp.auth0.com",
        "AUTH0_CLIENT_ID": "test-client-id",
        "AUTH0_AUDIENCE": "https://api.mingai.app",
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture
def client(env_vars):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {_make_tenant_admin_token()}"}


@pytest.fixture
def viewer_headers():
    return {"Authorization": f"Bearer {_make_viewer_token()}"}


# ---------------------------------------------------------------------------
# Helper: make a mock httpx response for discovery
# ---------------------------------------------------------------------------


def _mock_discovery_response(doc: dict, status_code: int = 200) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = doc
    mock_resp.raise_for_status = MagicMock()
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=mock_resp,
        )
    return mock_resp


# ---------------------------------------------------------------------------
# Test 1: OIDC discovery extracts required fields
# ---------------------------------------------------------------------------


class TestOIDCDiscovery:
    """Tests for _validate_oidc_discovery helper behaviour."""

    @pytest.mark.asyncio
    async def test_discovery_extracts_required_fields(self):
        """
        Successful discovery returns a dict containing all three required fields.
        """
        from app.modules.admin.sso_oidc import _validate_oidc_discovery

        mock_resp = _mock_discovery_response(_GOOD_DISCOVERY_DOC)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http

            doc = await _validate_oidc_discovery("https://accounts.google.com")

        assert "authorization_endpoint" in doc
        assert "token_endpoint" in doc
        assert "jwks_uri" in doc

    @pytest.mark.asyncio
    async def test_discovery_missing_required_fields_raises_422(self):
        """Discovery document missing jwks_uri raises HTTPException 422."""
        from fastapi import HTTPException

        from app.modules.admin.sso_oidc import _validate_oidc_discovery

        incomplete_doc = {
            "issuer": "https://example.com",
            "authorization_endpoint": "https://example.com/auth",
            # token_endpoint and jwks_uri are missing
        }
        mock_resp = _mock_discovery_response(incomplete_doc)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http

            with pytest.raises(HTTPException) as exc_info:
                await _validate_oidc_discovery("https://example.com")

        assert exc_info.value.status_code == 422
        assert "OIDC discovery missing required fields" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_discovery_timeout_raises_422(self):
        """TimeoutException from httpx raises HTTPException 422 with timeout message."""
        from fastapi import HTTPException

        from app.modules.admin.sso_oidc import _validate_oidc_discovery

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http

            with pytest.raises(HTTPException) as exc_info:
                await _validate_oidc_discovery("https://slow-idp.example.com")

        assert exc_info.value.status_code == 422
        assert "timed out" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Test 4: Client secret not in returned response (vault ref replaces it)
# ---------------------------------------------------------------------------


class TestOIDCSecretNotExposed:
    """Client secret must never appear in API responses."""

    def test_configure_oidc_response_does_not_contain_client_secret(
        self, client, admin_headers
    ):
        """
        POST /admin/sso/oidc/configure response body must not contain client_secret.
        Vault ref replaces the plaintext before any storage or Auth0 call.
        """
        payload = {
            "issuer": "https://accounts.google.com",
            "client_id": "my-client-id",
            "client_secret": "super-secret-value-12345",
        }

        with (
            patch(
                "app.modules.admin.sso_oidc._validate_oidc_discovery",
                new_callable=AsyncMock,
                return_value=_GOOD_DISCOVERY_DOC,
            ),
            patch(
                "app.modules.admin.sso_oidc._encrypt_client_secret",
                return_value="local://dmF1bHQ=",
            ),
            patch(
                "app.modules.admin.sso_oidc._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_oidc.management_api_request",
                new_callable=AsyncMock,
                return_value={"id": "con_TestOIDC1234"},
            ),
            patch(
                "app.modules.admin.sso_oidc._upsert_sso_provider_config_db",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                "/api/v1/admin/sso/oidc/configure",
                json=payload,
                headers=admin_headers,
            )

        assert resp.status_code == 200
        response_text = resp.text
        # The raw client_secret must not appear in the response
        assert "super-secret-value-12345" not in response_text
        data = resp.json()
        assert "client_secret" not in data
        assert data["connection_id"] == "con_TestOIDC1234"
        assert data["issuer_validated"] is True


# ---------------------------------------------------------------------------
# Test 5: Duplicate OIDC connection → 409
# ---------------------------------------------------------------------------


class TestOIDCDuplicateConnection:
    """Attempting to configure a second OIDC connection returns 409."""

    def test_oidc_duplicate_returns_409(self, client, admin_headers):
        existing_config = {
            "provider_type": "oidc",
            "auth0_connection_id": "con_ExistingOIDC",
            "enabled": True,
        }
        payload = {
            "issuer": "https://accounts.google.com",
            "client_id": "client-id",
            "client_secret": "client-secret",
        }

        with (
            patch(
                "app.modules.admin.sso_oidc._validate_oidc_discovery",
                new_callable=AsyncMock,
                return_value=_GOOD_DISCOVERY_DOC,
            ),
            patch(
                "app.modules.admin.sso_oidc._encrypt_client_secret",
                return_value="local://dmF1bHQ=",
            ),
            patch(
                "app.modules.admin.sso_oidc._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=existing_config,
            ),
        ):
            resp = client.post(
                "/api/v1/admin/sso/oidc/configure",
                json=payload,
                headers=admin_headers,
            )

        assert resp.status_code == 409
        assert "already configured" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test 6: Google configuration uses "google-oauth2" strategy
# ---------------------------------------------------------------------------


class TestGoogleSSOConfiguration:
    """POST /admin/sso/google/configure creates Auth0 connection with google-oauth2 strategy."""

    def test_google_configure_uses_google_oauth2_strategy(self, client, admin_headers):
        """Auth0 Management API is called with strategy=google-oauth2."""
        payload = {
            "client_id": "google-client-id.apps.googleusercontent.com",
            "client_secret": "google-client-secret",
        }

        captured_body = {}

        async def _capture_management_request(method, path, body=None):
            captured_body.update(body or {})
            return {"id": "con_GoogleTest1234"}

        with (
            patch(
                "app.modules.admin.sso_oidc._encrypt_client_secret",
                return_value="local://Z29vZ2xl",
            ),
            patch(
                "app.modules.admin.sso_oidc._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_oidc.management_api_request",
                side_effect=_capture_management_request,
            ),
            patch(
                "app.modules.admin.sso_oidc._upsert_sso_provider_config_db",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                "/api/v1/admin/sso/google/configure",
                json=payload,
                headers=admin_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["connection_id"] == "con_GoogleTest1234"
        assert "google_auth_url" in data
        # Verify strategy was google-oauth2
        assert captured_body.get("strategy") == "google-oauth2"

    def test_google_configure_duplicate_returns_409(self, client, admin_headers):
        """Second Google configuration attempt returns 409."""
        existing_config = {
            "provider_type": "google",
            "auth0_connection_id": "con_ExistingGoogle",
            "enabled": True,
        }
        payload = {
            "client_id": "google-client-id",
            "client_secret": "secret",
        }

        with (
            patch(
                "app.modules.admin.sso_oidc._encrypt_client_secret",
                return_value="local://Z29vZ2xl",
            ),
            patch(
                "app.modules.admin.sso_oidc._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=existing_config,
            ),
        ):
            resp = client.post(
                "/api/v1/admin/sso/google/configure",
                json=payload,
                headers=admin_headers,
            )

        assert resp.status_code == 409

    def test_google_auth_url_in_response(self, client, admin_headers):
        """google_auth_url in response contains AUTH0_DOMAIN and connection_id."""
        payload = {
            "client_id": "google-client-id",
            "client_secret": "google-secret",
        }

        with (
            patch(
                "app.modules.admin.sso_oidc._encrypt_client_secret",
                return_value="local://Z29vZ2xl",
            ),
            patch(
                "app.modules.admin.sso_oidc._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_oidc.management_api_request",
                new_callable=AsyncMock,
                return_value={"id": "con_GoogleURL999"},
            ),
            patch(
                "app.modules.admin.sso_oidc._upsert_sso_provider_config_db",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                "/api/v1/admin/sso/google/configure",
                json=payload,
                headers=admin_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "mingai-dev.jp.auth0.com" in data["google_auth_url"]
        assert "con_GoogleURL999" in data["google_auth_url"]


# ---------------------------------------------------------------------------
# Test 7 & 8: Okta configuration
# ---------------------------------------------------------------------------


class TestOktaSSOConfiguration:
    """POST /admin/sso/okta/configure"""

    def test_okta_constructs_discovery_url_from_domain(self, client, admin_headers):
        """
        Discovery is called with https://{okta_domain} as the issuer.
        """
        payload = {
            "okta_domain": "mycompany.okta.com",
            "client_id": "okta-client-id",
            "client_secret": "okta-client-secret",
        }

        discovery_issuer_seen = []

        async def _mock_discovery(issuer: str) -> dict:
            discovery_issuer_seen.append(issuer)
            return _GOOD_DISCOVERY_DOC

        with (
            patch(
                "app.modules.admin.sso_oidc._validate_oidc_discovery",
                side_effect=_mock_discovery,
            ),
            patch(
                "app.modules.admin.sso_oidc._encrypt_client_secret",
                return_value="local://b2t0YQ==",
            ),
            patch(
                "app.modules.admin.sso_oidc._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_oidc.management_api_request",
                new_callable=AsyncMock,
                return_value={"id": "con_OktaTest1234"},
            ),
            patch(
                "app.modules.admin.sso_oidc._upsert_sso_provider_config_db",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                "/api/v1/admin/sso/okta/configure",
                json=payload,
                headers=admin_headers,
            )

        assert resp.status_code == 200
        # Discovery URL must be constructed from okta_domain
        assert len(discovery_issuer_seen) == 1
        assert discovery_issuer_seen[0] == "https://mycompany.okta.com"

    def test_okta_invalid_domain_returns_422(self, client, admin_headers):
        """
        If Okta OIDC discovery fails (e.g. timeout), endpoint returns 422
        with 'Okta domain not reachable or invalid OIDC configuration'.
        """
        from fastapi import HTTPException

        payload = {
            "okta_domain": "invalid.nonexistent-okta-domain.example",
            "client_id": "okta-client-id",
            "client_secret": "okta-client-secret",
        }

        async def _mock_discovery_timeout(issuer: str) -> dict:
            raise HTTPException(
                status_code=422,
                detail="OIDC discovery request timed out",
            )

        with patch(
            "app.modules.admin.sso_oidc._validate_oidc_discovery",
            side_effect=_mock_discovery_timeout,
        ):
            resp = client.post(
                "/api/v1/admin/sso/okta/configure",
                json=payload,
                headers=admin_headers,
            )

        assert resp.status_code == 422
        assert "Okta domain not reachable" in resp.json()["detail"]

    def test_okta_configure_response_has_issuer_validated(self, client, admin_headers):
        """Successful Okta configuration returns issuer_validated=True."""
        payload = {
            "okta_domain": "mycompany.okta.com",
            "client_id": "okta-client-id",
            "client_secret": "okta-client-secret",
        }

        with (
            patch(
                "app.modules.admin.sso_oidc._validate_oidc_discovery",
                new_callable=AsyncMock,
                return_value=_GOOD_DISCOVERY_DOC,
            ),
            patch(
                "app.modules.admin.sso_oidc._encrypt_client_secret",
                return_value="local://b2t0YQ==",
            ),
            patch(
                "app.modules.admin.sso_oidc._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_oidc.management_api_request",
                new_callable=AsyncMock,
                return_value={"id": "con_OktaFull123"},
            ),
            patch(
                "app.modules.admin.sso_oidc._upsert_sso_provider_config_db",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                "/api/v1/admin/sso/okta/configure",
                json=payload,
                headers=admin_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["issuer_validated"] is True
        assert data["connection_id"] == "con_OktaFull123"


# ---------------------------------------------------------------------------
# Test 9: OIDC test endpoint returns correct URL
# ---------------------------------------------------------------------------


class TestOIDCTestEndpoint:
    """POST /admin/sso/oidc/test"""

    def test_oidc_test_returns_authorize_url(self, client, admin_headers):
        """
        When OIDC is configured, test endpoint returns a valid Auth0 authorize URL
        containing the connection_id, AUTH0_DOMAIN, and AUTH0_CLIENT_ID.
        """
        stored_config = {
            "provider_type": "oidc",
            "auth0_connection_id": "con_OIDCTestConn",
            "enabled": True,
        }

        with patch(
            "app.modules.admin.sso_oidc._get_sso_provider_config_db",
            new_callable=AsyncMock,
            return_value=stored_config,
        ):
            resp = client.post(
                "/api/v1/admin/sso/oidc/test",
                headers=admin_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "test_url" in data
        test_url = data["test_url"]
        assert "mingai-dev.jp.auth0.com" in test_url
        assert "con_OIDCTestConn" in test_url
        assert "test-client-id" in test_url
        assert "response_type=code" in test_url
        assert "openid" in test_url

    def test_oidc_test_returns_404_when_not_configured(self, client, admin_headers):
        """Test endpoint returns 404 when no OIDC connection is configured."""
        with patch(
            "app.modules.admin.sso_oidc._get_sso_provider_config_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                "/api/v1/admin/sso/oidc/test",
                headers=admin_headers,
            )

        assert resp.status_code == 404

    def test_oidc_test_requires_tenant_admin(self, client, viewer_headers):
        """Test endpoint returns 403 for viewer role."""
        resp = client.post(
            "/api/v1/admin/sso/oidc/test",
            headers=viewer_headers,
        )
        assert resp.status_code == 403
