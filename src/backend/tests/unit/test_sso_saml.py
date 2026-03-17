"""
Unit tests for SAML SSO wizard API (TA-001 verification).

Checks:
- SP metadata entityID format = https://{AUTH0_DOMAIN}/samlp/metadata/{connection_id}
- All 3 routes enforce require_tenant_admin
- configure and test routes exist under /admin/sso/saml/
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "c" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "bbbbcccc-dddd-eeee-ffff-000011112222"
TEST_ACTOR_ID = "saml-actor-001"


def _make_tenant_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": TEST_ACTOR_ID,
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": "admin@tenant.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_viewer_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "viewer-user-id",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["viewer"],
        "scope": "tenant",
        "plan": "professional",
        "email": "viewer@tenant.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


@pytest.fixture
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
        "AUTH0_DOMAIN": "dev-test.auth0.com",
        "AUTH0_CLIENT_ID": "test-client-id",
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
# TA-001: SP metadata entityID format
# ---------------------------------------------------------------------------


class TestSAMLSPMetadataEntityID:
    """TA-001: SP metadata entityID must be https://{AUTH0_DOMAIN}/samlp/metadata/{connection_id}"""

    def test_sp_metadata_entity_id_format(self, client, admin_headers, env_vars):
        """GET /admin/sso/saml/sp-metadata returns correct entityID format."""
        stored_config = {
            "provider_type": "saml",
            "auth0_connection_id": "con_SamlTest1234",
            "enabled": True,
        }
        with patch(
            "app.modules.admin.sso_saml._get_saml_config_db",
            new_callable=AsyncMock,
            return_value=stored_config,
        ):
            resp = client.get(
                "/api/v1/admin/sso/saml/sp-metadata", headers=admin_headers
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        xml_body = resp.text
        # TA-001: entityID must be https://{AUTH0_DOMAIN}/samlp/metadata/{connection_id}
        expected_entity_id = (
            'entityID="https://dev-test.auth0.com/samlp/metadata/con_SamlTest1234"'
        )
        assert expected_entity_id in xml_body, (
            f"Expected entityID pattern not found in SP metadata XML.\n"
            f"Expected: {expected_entity_id}\n"
            f"Got XML: {xml_body}"
        )

    def test_sp_metadata_not_hardcoded_api_domain(
        self, client, admin_headers, env_vars
    ):
        """SP metadata entityID must NOT be the old hardcoded 'https://api.mingai.app'."""
        stored_config = {
            "provider_type": "saml",
            "auth0_connection_id": "con_AnyConn9999",
            "enabled": True,
        }
        with patch(
            "app.modules.admin.sso_saml._get_saml_config_db",
            new_callable=AsyncMock,
            return_value=stored_config,
        ):
            resp = client.get(
                "/api/v1/admin/sso/saml/sp-metadata", headers=admin_headers
            )

        assert resp.status_code == 200
        xml_body = resp.text
        assert (
            "https://api.mingai.app" not in xml_body
        ), "SP metadata entityID must not be the hardcoded 'https://api.mingai.app'"

    def test_sp_metadata_acs_location_uses_auth0_domain(
        self, client, admin_headers, env_vars
    ):
        """ACS Location URL in SP metadata uses AUTH0_DOMAIN and connection_id."""
        stored_config = {
            "provider_type": "saml",
            "auth0_connection_id": "con_ACSTest5678",
            "enabled": True,
        }
        with patch(
            "app.modules.admin.sso_saml._get_saml_config_db",
            new_callable=AsyncMock,
            return_value=stored_config,
        ):
            resp = client.get(
                "/api/v1/admin/sso/saml/sp-metadata", headers=admin_headers
            )

        assert resp.status_code == 200
        xml_body = resp.text
        assert (
            "dev-test.auth0.com/login/callback?connection=con_ACSTest5678" in xml_body
        )


# ---------------------------------------------------------------------------
# TA-001: All 3 routes enforce require_tenant_admin
# ---------------------------------------------------------------------------


class TestSAMLRoutesRequireTenantAdmin:
    """TA-001: All 3 SAML wizard routes must require tenant_admin."""

    def test_configure_requires_tenant_admin_unauthorized(self, client):
        """POST /configure returns 401 without auth."""
        resp = client.post(
            "/api/v1/admin/sso/saml/configure",
            json={"metadata_xml": "<xml/>"},
        )
        assert resp.status_code == 401

    def test_configure_requires_tenant_admin_forbidden(self, client, viewer_headers):
        """POST /configure returns 403 for viewer."""
        resp = client.post(
            "/api/v1/admin/sso/saml/configure",
            json={"metadata_xml": "<xml/>"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_sp_metadata_requires_tenant_admin_unauthorized(self, client):
        """GET /sp-metadata returns 401 without auth."""
        resp = client.get("/api/v1/admin/sso/saml/sp-metadata")
        assert resp.status_code == 401

    def test_sp_metadata_requires_tenant_admin_forbidden(self, client, viewer_headers):
        """GET /sp-metadata returns 403 for viewer."""
        resp = client.get("/api/v1/admin/sso/saml/sp-metadata", headers=viewer_headers)
        assert resp.status_code == 403

    def test_test_route_requires_tenant_admin_unauthorized(self, client):
        """POST /test returns 401 without auth."""
        resp = client.post("/api/v1/admin/sso/saml/test")
        assert resp.status_code == 401

    def test_test_route_requires_tenant_admin_forbidden(self, client, viewer_headers):
        """POST /test returns 403 for viewer."""
        resp = client.post("/api/v1/admin/sso/saml/test", headers=viewer_headers)
        assert resp.status_code == 403
