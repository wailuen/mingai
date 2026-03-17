"""
Unit tests for P3AUTH-003 SSO Connection Config API.

Endpoints under test:
- GET  /api/v1/admin/sso/config  — returns current config or null
- PATCH /api/v1/admin/sso/config — validates and stores config

Tier 1: fast, isolated, uses mocking for DB helpers.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, call, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "b" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb"
TEST_ACTOR_ID = "actor-user-id-001"


# ---------------------------------------------------------------------------
# JWT token factories
# ---------------------------------------------------------------------------


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
# GET /api/v1/admin/sso/config
# ---------------------------------------------------------------------------


class TestGetSSOConnectionConfig:
    """GET /api/v1/admin/sso/config"""

    def test_returns_null_when_not_configured(self, client, admin_headers):
        """Returns null (HTTP 200 with null body) when no SSO config is stored."""
        with patch(
            "app.modules.admin.workspace._get_sso_connection_config_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get("/api/v1/admin/sso/config", headers=admin_headers)

        assert resp.status_code == 200
        assert resp.json() is None

    def test_returns_stored_config(self, client, admin_headers):
        """Returns the stored SSO connection config when one exists."""
        stored = {
            "provider_type": "entra",
            "auth0_connection_id": "con_AbCdEfGhIjKl1234",
            "enabled": True,
        }
        with patch(
            "app.modules.admin.workspace._get_sso_connection_config_db",
            new_callable=AsyncMock,
            return_value=stored,
        ):
            resp = client.get("/api/v1/admin/sso/config", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_type"] == "entra"
        assert data["auth0_connection_id"] == "con_AbCdEfGhIjKl1234"
        assert data["enabled"] is True

    def test_returns_disabled_config(self, client, admin_headers):
        """Config with enabled=False is returned correctly."""
        stored = {
            "provider_type": "okta",
            "auth0_connection_id": "con_OktaTestConn",
            "enabled": False,
        }
        with patch(
            "app.modules.admin.workspace._get_sso_connection_config_db",
            new_callable=AsyncMock,
            return_value=stored,
        ):
            resp = client.get("/api/v1/admin/sso/config", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False

    def test_requires_auth(self, client):
        """GET returns 401 without Authorization header."""
        resp = client.get("/api/v1/admin/sso/config")
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client, viewer_headers):
        """GET returns 403 for viewer role."""
        resp = client.get("/api/v1/admin/sso/config", headers=viewer_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /api/v1/admin/sso/config
# ---------------------------------------------------------------------------


class TestPatchSSOConnectionConfig:
    """PATCH /api/v1/admin/sso/config"""

    def test_valid_config_stored_and_returned(self, client, admin_headers):
        """Valid PATCH stores config and returns updated response."""
        payload = {
            "provider_type": "entra",
            "auth0_connection_id": "con_AbCdEfGhIjKl1234",
            "enabled": True,
        }
        with (
            patch(
                "app.modules.admin.workspace._get_sso_connection_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.workspace._upsert_sso_connection_config_db",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.patch(
                "/api/v1/admin/sso/config", json=payload, headers=admin_headers
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_type"] == "entra"
        assert data["auth0_connection_id"] == "con_AbCdEfGhIjKl1234"
        assert data["enabled"] is True

    def test_all_valid_provider_types_accepted(self, client, admin_headers):
        """All five valid provider types are accepted without 422."""
        valid_providers = ["entra", "google", "okta", "saml", "oidc"]
        for provider in valid_providers:
            payload = {
                "provider_type": provider,
                "auth0_connection_id": "con_TestConn1234",
                "enabled": True,
            }
            with (
                patch(
                    "app.modules.admin.workspace._get_sso_connection_config_db",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "app.modules.admin.workspace._upsert_sso_connection_config_db",
                    new_callable=AsyncMock,
                ),
            ):
                resp = client.patch(
                    "/api/v1/admin/sso/config", json=payload, headers=admin_headers
                )
            assert (
                resp.status_code == 200
            ), f"Expected 200 for provider_type={provider!r}, got {resp.status_code}"

    def test_invalid_provider_type_returns_422(self, client, admin_headers):
        """Invalid provider_type not in allowed set returns 422."""
        payload = {
            "provider_type": "azure_ad",  # not in allowed set
            "auth0_connection_id": "con_TestConn1234",
            "enabled": True,
        }
        resp = client.patch(
            "/api/v1/admin/sso/config", json=payload, headers=admin_headers
        )
        assert resp.status_code == 422

    def test_invalid_connection_id_format_returns_422(self, client, admin_headers):
        """auth0_connection_id without con_ prefix returns 422."""
        payload = {
            "provider_type": "entra",
            "auth0_connection_id": "abc_NotAConnectionId",  # missing con_ prefix
            "enabled": True,
        }
        resp = client.patch(
            "/api/v1/admin/sso/config", json=payload, headers=admin_headers
        )
        assert resp.status_code == 422

    def test_connection_id_must_start_with_con_prefix(self, client, admin_headers):
        """Connection ID that is just 'con' without underscore returns 422."""
        payload = {
            "provider_type": "saml",
            "auth0_connection_id": "conAbc123",  # no underscore after 'con'
            "enabled": False,
        }
        resp = client.patch(
            "/api/v1/admin/sso/config", json=payload, headers=admin_headers
        )
        assert resp.status_code == 422

    def test_requires_auth(self, client):
        """PATCH returns 401 without Authorization header."""
        payload = {
            "provider_type": "entra",
            "auth0_connection_id": "con_TestConn",
            "enabled": True,
        }
        resp = client.patch("/api/v1/admin/sso/config", json=payload)
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client, viewer_headers):
        """PATCH returns 403 for viewer role."""
        payload = {
            "provider_type": "entra",
            "auth0_connection_id": "con_TestConn",
            "enabled": True,
        }
        resp = client.patch(
            "/api/v1/admin/sso/config", json=payload, headers=viewer_headers
        )
        assert resp.status_code == 403

    def test_audit_log_written_on_patch(self, client, admin_headers):
        """_upsert_sso_connection_config_db is called with before/after values."""
        old_config = {
            "provider_type": "google",
            "auth0_connection_id": "con_OldConn123",
            "enabled": False,
        }
        new_payload = {
            "provider_type": "entra",
            "auth0_connection_id": "con_NewConn456",
            "enabled": True,
        }
        with (
            patch(
                "app.modules.admin.workspace._get_sso_connection_config_db",
                new_callable=AsyncMock,
                return_value=old_config,
            ) as mock_get,
            patch(
                "app.modules.admin.workspace._upsert_sso_connection_config_db",
                new_callable=AsyncMock,
            ) as mock_upsert,
        ):
            resp = client.patch(
                "/api/v1/admin/sso/config", json=new_payload, headers=admin_headers
            )

        assert resp.status_code == 200

        # Verify _upsert was called with old_config as before-value
        upsert_call = mock_upsert.call_args
        assert upsert_call.kwargs["old_config"] == old_config
        assert upsert_call.kwargs["new_config"]["provider_type"] == "entra"
        assert (
            upsert_call.kwargs["new_config"]["auth0_connection_id"] == "con_NewConn456"
        )

    def test_patch_when_no_existing_config(self, client, admin_headers):
        """PATCH with no prior config passes None as old_config to upsert."""
        payload = {
            "provider_type": "oidc",
            "auth0_connection_id": "con_OidcConn789",
            "enabled": True,
        }
        with (
            patch(
                "app.modules.admin.workspace._get_sso_connection_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.workspace._upsert_sso_connection_config_db",
                new_callable=AsyncMock,
            ) as mock_upsert,
        ):
            resp = client.patch(
                "/api/v1/admin/sso/config", json=payload, headers=admin_headers
            )

        assert resp.status_code == 200
        upsert_call = mock_upsert.call_args
        assert upsert_call.kwargs["old_config"] is None


# ---------------------------------------------------------------------------
# TA-003: JIT config extension tests
# ---------------------------------------------------------------------------


class TestSSOConfigJITExtension:
    """TA-003: PATCH stores jit_default_role; GET returns jit_provisioning block."""

    def test_patch_with_jit_default_role_editor_stored(self, client, admin_headers):
        """PATCH with jit_default_role='editor' is accepted and stored in new_config."""
        payload = {
            "provider_type": "entra",
            "auth0_connection_id": "con_EntraConn001",
            "enabled": True,
            "jit_default_role": "editor",
        }
        with (
            patch(
                "app.modules.admin.workspace._get_sso_connection_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.workspace._upsert_sso_connection_config_db",
                new_callable=AsyncMock,
            ) as mock_upsert,
        ):
            resp = client.patch(
                "/api/v1/admin/sso/config", json=payload, headers=admin_headers
            )

        assert resp.status_code == 200
        data = resp.json()
        # Response includes jit_provisioning block
        assert data["jit_provisioning"] is not None
        assert data["jit_provisioning"]["enabled"] is True
        assert data["jit_provisioning"]["default_role"] == "editor"

        # Verify upsert received jit_default_role in new_config
        upsert_call = mock_upsert.call_args
        assert upsert_call.kwargs["new_config"].get("jit_default_role") == "editor"

    def test_patch_with_jit_default_role_admin_returns_422(self, client, admin_headers):
        """PATCH with jit_default_role='admin' must return 422 — admin not allowed via JIT."""
        payload = {
            "provider_type": "entra",
            "auth0_connection_id": "con_EntraConn002",
            "enabled": True,
            "jit_default_role": "admin",
        }
        resp = client.patch(
            "/api/v1/admin/sso/config", json=payload, headers=admin_headers
        )
        assert resp.status_code == 422

    def test_patch_with_jit_default_role_viewer_accepted(self, client, admin_headers):
        """PATCH with jit_default_role='viewer' is valid and returns jit_provisioning block."""
        payload = {
            "provider_type": "saml",
            "auth0_connection_id": "con_SamlConn003",
            "enabled": True,
            "jit_default_role": "viewer",
        }
        with (
            patch(
                "app.modules.admin.workspace._get_sso_connection_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.workspace._upsert_sso_connection_config_db",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.patch(
                "/api/v1/admin/sso/config", json=payload, headers=admin_headers
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["jit_provisioning"]["default_role"] == "viewer"

    def test_get_returns_jit_provisioning_block_when_sso_enabled(
        self, client, admin_headers
    ):
        """GET returns jit_provisioning block when SSO is configured and enabled."""
        stored = {
            "provider_type": "entra",
            "auth0_connection_id": "con_EntraConn001",
            "enabled": True,
            "jit_default_role": "editor",
        }
        with patch(
            "app.modules.admin.workspace._get_sso_connection_config_db",
            new_callable=AsyncMock,
            return_value=stored,
        ):
            resp = client.get("/api/v1/admin/sso/config", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["jit_provisioning"] is not None
        assert data["jit_provisioning"]["enabled"] is True
        assert data["jit_provisioning"]["default_role"] == "editor"

    def test_get_jit_provisioning_defaults_to_viewer_when_not_set(
        self, client, admin_headers
    ):
        """GET returns jit_provisioning.default_role='viewer' when jit_default_role not stored."""
        stored = {
            "provider_type": "saml",
            "auth0_connection_id": "con_SamlConn004",
            "enabled": True,
            # jit_default_role not set — should default to viewer
        }
        with patch(
            "app.modules.admin.workspace._get_sso_connection_config_db",
            new_callable=AsyncMock,
            return_value=stored,
        ):
            resp = client.get("/api/v1/admin/sso/config", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["jit_provisioning"]["default_role"] == "viewer"

    def test_get_no_jit_provisioning_block_when_sso_disabled(
        self, client, admin_headers
    ):
        """GET returns no jit_provisioning block when SSO is disabled (enabled=False)."""
        stored = {
            "provider_type": "entra",
            "auth0_connection_id": "con_EntraDisabled",
            "enabled": False,
        }
        with patch(
            "app.modules.admin.workspace._get_sso_connection_config_db",
            new_callable=AsyncMock,
            return_value=stored,
        ):
            resp = client.get("/api/v1/admin/sso/config", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["jit_provisioning"] is None
