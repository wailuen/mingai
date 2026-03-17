"""
Unit tests for ENTRA-001/002/004/003 — Azure Entra ID SSO wizard.

Tests:
  1.  configure_entra_happy_path
  2.  configure_entra_org_enable_called_when_org_id_present
  3.  configure_entra_org_enable_skipped_when_org_id_absent
  4.  configure_entra_org_enable_failure_does_not_fail_request
  5.  configure_entra_duplicate_returns_409
  6.  configure_entra_invalid_domain_returns_400
  7.  configure_entra_invalid_client_id_returns_400
  8.  configure_entra_empty_secret_returns_400
  9.  configure_entra_management_api_failure_returns_502
  10. configure_entra_secret_not_in_db_args
  11. configure_entra_secret_not_in_response
  12. update_entra_happy_path_secret_rotation
  13. update_entra_happy_path_domain_update
  14. update_entra_not_configured_returns_404
  15. update_entra_empty_body_returns_400
  16. update_entra_management_api_failure_returns_502
  17. update_entra_secret_not_in_response
  18. test_entra_returns_test_url
  19. test_entra_not_configured_returns_404
  20. test_entra_disabled_returns_404
  21. disable_entra_calls_org_remove
  22. reenable_entra_calls_org_add

All DB and HTTP calls are mocked (Tier 1 unit tests).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt

_TENANT_ID = "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"
_ACTOR_ID = "cccccccc-4444-5555-6666-dddddddddddd"
_ORG_ID = "org_testorg123"
_CONN_ID = "con_testconn456"

TEST_JWT_SECRET = "e" * 64
TEST_JWT_ALGORITHM = "HS256"

_VALID_CLIENT_ID = "12345678-abcd-ef01-2345-6789abcdef01"
_VALID_DOMAIN = "contoso.com"
_VALID_SECRET = "my-azure-client-secret"


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _make_tenant_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": _ACTOR_ID,
        "tenant_id": _TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "enterprise",
        "email": "admin@contoso.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_viewer_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "viewer-entra-test",
        "tenant_id": _TENANT_ID,
        "roles": ["viewer"],
        "scope": "tenant",
        "plan": "professional",
        "email": "viewer@contoso.com",
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
# Convenience: plain function/db mocks for direct handler tests
# ---------------------------------------------------------------------------


def _make_user(role: str = "tenant_admin") -> MagicMock:
    user = MagicMock()
    user.tenant_id = _TENANT_ID
    user.id = _ACTOR_ID
    user.roles = [role]
    return user


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Tests 1-11: configure_entra_sso (direct handler)
# ---------------------------------------------------------------------------


class TestConfigureEntra:
    """POST /admin/sso/entra/configure"""

    @pytest.mark.asyncio
    async def test_configure_entra_happy_path(self):
        """Valid inputs → management_api_request called with waad strategy → db.execute called."""
        from app.modules.admin.sso_entra import (
            configure_entra_sso,
            EntraConfigureRequest,
        )

        db = _make_db()
        user = _make_user()

        request = EntraConfigureRequest(
            client_id=_VALID_CLIENT_ID,
            client_secret=_VALID_SECRET,
            domain=_VALID_DOMAIN,
        )

        with (
            patch(
                "app.modules.admin.sso_entra._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_entra.management_api_request",
                new_callable=AsyncMock,
                return_value={"id": _CONN_ID},
            ) as mock_mgmt,
            patch(
                "app.modules.admin.sso_entra.get_tenant_auth0_org_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            response = await configure_entra_sso(request, user, db)

        assert response.connection_id == _CONN_ID
        assert response.domain == _VALID_DOMAIN
        assert "authorize" in response.test_url
        # management_api_request was called with waad strategy
        first_call = mock_mgmt.call_args_list[0]
        body = (
            first_call[0][2]
            if len(first_call[0]) >= 3
            else first_call[1].get("body") or first_call[0][2]
        )
        assert body["strategy"] == "waad"
        # db.execute was called (for upsert + audit log)
        assert db.execute.call_count >= 2
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_configure_entra_org_enable_called_when_org_id_present(self):
        """When org_id is found, POST organizations/{org_id}/enabled_connections is called."""
        from app.modules.admin.sso_entra import (
            configure_entra_sso,
            EntraConfigureRequest,
        )

        db = _make_db()
        user = _make_user()

        request = EntraConfigureRequest(
            client_id=_VALID_CLIENT_ID,
            client_secret=_VALID_SECRET,
            domain=_VALID_DOMAIN,
        )

        mgmt_calls: list = []

        async def _capture_mgmt(method, path, body=None):
            mgmt_calls.append((method, path, body))
            return {"id": _CONN_ID}

        with (
            patch(
                "app.modules.admin.sso_entra._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_entra.management_api_request",
                side_effect=_capture_mgmt,
            ),
            patch(
                "app.modules.admin.sso_entra.get_tenant_auth0_org_id",
                new_callable=AsyncMock,
                return_value=_ORG_ID,
            ),
        ):
            await configure_entra_sso(request, user, db)

        # First call creates the connection; second enables it in the org
        org_calls = [
            c
            for c in mgmt_calls
            if f"organizations/{_ORG_ID}/enabled_connections" in c[1]
        ]
        assert len(org_calls) == 1
        assert org_calls[0][0] == "POST"
        assert org_calls[0][2]["connection_id"] == _CONN_ID

    @pytest.mark.asyncio
    async def test_configure_entra_org_enable_skipped_when_org_id_absent(self):
        """When org_id is None, no org API call is made and connection is still created."""
        from app.modules.admin.sso_entra import (
            configure_entra_sso,
            EntraConfigureRequest,
        )

        db = _make_db()
        user = _make_user()

        request = EntraConfigureRequest(
            client_id=_VALID_CLIENT_ID,
            client_secret=_VALID_SECRET,
            domain=_VALID_DOMAIN,
        )

        mgmt_calls: list = []

        async def _capture_mgmt(method, path, body=None):
            mgmt_calls.append((method, path))
            return {"id": _CONN_ID}

        with (
            patch(
                "app.modules.admin.sso_entra._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_entra.management_api_request",
                side_effect=_capture_mgmt,
            ),
            patch(
                "app.modules.admin.sso_entra.get_tenant_auth0_org_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            response = await configure_entra_sso(request, user, db)

        # Only the connection creation call — no org call
        org_calls = [c for c in mgmt_calls if "organizations" in c[1]]
        assert len(org_calls) == 0
        assert response.connection_id == _CONN_ID

    @pytest.mark.asyncio
    async def test_configure_entra_org_enable_failure_does_not_fail_request(self):
        """If org enable raises RuntimeError, warning is logged but connection is still returned."""
        from app.modules.admin.sso_entra import (
            configure_entra_sso,
            EntraConfigureRequest,
        )

        db = _make_db()
        user = _make_user()

        request = EntraConfigureRequest(
            client_id=_VALID_CLIENT_ID,
            client_secret=_VALID_SECRET,
            domain=_VALID_DOMAIN,
        )

        call_count = {"n": 0}

        async def _mgmt_with_org_failure(method, path, body=None):
            call_count["n"] += 1
            if "organizations" in path:
                raise RuntimeError("Auth0 org API error")
            return {"id": _CONN_ID}

        with (
            patch(
                "app.modules.admin.sso_entra._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_entra.management_api_request",
                side_effect=_mgmt_with_org_failure,
            ),
            patch(
                "app.modules.admin.sso_entra.get_tenant_auth0_org_id",
                new_callable=AsyncMock,
                return_value=_ORG_ID,
            ),
        ):
            # Should NOT raise — org failure is non-fatal
            response = await configure_entra_sso(request, user, db)

        assert response.connection_id == _CONN_ID

    @pytest.mark.asyncio
    async def test_configure_entra_duplicate_returns_409(self):
        """If any SSO config already exists, returns 409 Conflict."""
        from app.modules.admin.sso_entra import (
            configure_entra_sso,
            EntraConfigureRequest,
        )

        db = _make_db()
        user = _make_user()

        request = EntraConfigureRequest(
            client_id=_VALID_CLIENT_ID,
            client_secret=_VALID_SECRET,
            domain=_VALID_DOMAIN,
        )

        existing = {
            "provider_type": "entra",
            "auth0_connection_id": "con_old",
            "enabled": True,
        }

        with (
            patch(
                "app.modules.admin.sso_entra._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=existing,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await configure_entra_sso(request, user, db)

        assert exc_info.value.status_code == 409
        assert "already configured" in exc_info.value.detail.lower()

    def test_configure_entra_invalid_domain_returns_400(self, client, admin_headers):
        """Invalid domain format → 422 Unprocessable Entity."""
        payload = {
            "client_id": _VALID_CLIENT_ID,
            "client_secret": _VALID_SECRET,
            "domain": "notadomain",
        }
        resp = client.post(
            "/api/v1/admin/sso/entra/configure", json=payload, headers=admin_headers
        )
        assert resp.status_code == 422

    def test_configure_entra_invalid_client_id_returns_400(self, client, admin_headers):
        """Non-UUID client_id → 422 Unprocessable Entity."""
        payload = {
            "client_id": "not-a-uuid",
            "client_secret": _VALID_SECRET,
            "domain": _VALID_DOMAIN,
        }
        resp = client.post(
            "/api/v1/admin/sso/entra/configure", json=payload, headers=admin_headers
        )
        assert resp.status_code == 422

    def test_configure_entra_empty_secret_returns_400(self, client, admin_headers):
        """Empty client_secret → 422 Unprocessable Entity."""
        payload = {
            "client_id": _VALID_CLIENT_ID,
            "client_secret": "",
            "domain": _VALID_DOMAIN,
        }
        resp = client.post(
            "/api/v1/admin/sso/entra/configure", json=payload, headers=admin_headers
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_configure_entra_management_api_failure_returns_502(self):
        """management_api_request raising RuntimeError → HTTPException 502."""
        from app.modules.admin.sso_entra import (
            configure_entra_sso,
            EntraConfigureRequest,
        )

        db = _make_db()
        user = _make_user()

        request = EntraConfigureRequest(
            client_id=_VALID_CLIENT_ID,
            client_secret=_VALID_SECRET,
            domain=_VALID_DOMAIN,
        )

        with (
            patch(
                "app.modules.admin.sso_entra._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_entra.management_api_request",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Auth0 connection failed"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await configure_entra_sso(request, user, db)

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_configure_entra_secret_not_in_db_args(self):
        """client_secret MUST NOT appear in any db.execute call args."""
        from app.modules.admin.sso_entra import (
            configure_entra_sso,
            EntraConfigureRequest,
        )

        db = _make_db()
        user = _make_user()
        secret = "super-secret-azure-value-xyz"

        request = EntraConfigureRequest(
            client_id=_VALID_CLIENT_ID,
            client_secret=secret,
            domain=_VALID_DOMAIN,
        )

        with (
            patch(
                "app.modules.admin.sso_entra._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_entra.management_api_request",
                new_callable=AsyncMock,
                return_value={"id": _CONN_ID},
            ),
            patch(
                "app.modules.admin.sso_entra.get_tenant_auth0_org_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            await configure_entra_sso(request, user, db)

        # Inspect every db.execute call — secret must not appear in any parameter dict
        for c in db.execute.call_args_list:
            args, kwargs = c
            # The params dict is the second positional argument
            if len(args) >= 2:
                params_str = str(args[1])
                assert (
                    secret not in params_str
                ), f"client_secret found in db.execute params: {params_str}"

    @pytest.mark.asyncio
    async def test_configure_entra_secret_not_in_response(self):
        """Response model must not contain a client_secret field."""
        from app.modules.admin.sso_entra import (
            configure_entra_sso,
            EntraConfigureRequest,
        )

        db = _make_db()
        user = _make_user()

        request = EntraConfigureRequest(
            client_id=_VALID_CLIENT_ID,
            client_secret="another-secret-value",
            domain=_VALID_DOMAIN,
        )

        with (
            patch(
                "app.modules.admin.sso_entra._get_any_sso_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_entra.management_api_request",
                new_callable=AsyncMock,
                return_value={"id": _CONN_ID},
            ),
            patch(
                "app.modules.admin.sso_entra.get_tenant_auth0_org_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            response = await configure_entra_sso(request, user, db)

        response_dict = response.model_dump()
        assert "client_secret" not in response_dict


# ---------------------------------------------------------------------------
# Tests 12-17: update_entra_sso (direct handler)
# ---------------------------------------------------------------------------


class TestUpdateEntra:
    """PATCH /admin/sso/entra/configure"""

    @pytest.mark.asyncio
    async def test_update_entra_happy_path_secret_rotation(self):
        """Existing config + new secret → PATCH connections called; audit log written."""
        from app.modules.admin.sso_entra import update_entra_sso, EntraUpdateRequest

        db = _make_db()
        user = _make_user()
        existing = {
            "provider_type": "entra",
            "auth0_connection_id": _CONN_ID,
            "enabled": True,
            "domain": _VALID_DOMAIN,
            "client_id": _VALID_CLIENT_ID,
        }

        request = EntraUpdateRequest(client_secret="new-rotated-secret")

        with (
            patch(
                "app.modules.admin.sso_entra._get_sso_provider_config_db",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "app.modules.admin.sso_entra.management_api_request",
                new_callable=AsyncMock,
                return_value={},
            ) as mock_mgmt,
        ):
            response = await update_entra_sso(request, user, db)

        # Auth0 PATCH was called
        mock_mgmt.assert_called_once()
        call_args = mock_mgmt.call_args
        assert call_args[0][0] == "PATCH"
        assert _CONN_ID in call_args[0][1]
        # Audit log write + db.commit
        assert db.execute.call_count >= 1
        db.commit.assert_called_once()
        assert response.connection_id == _CONN_ID

    @pytest.mark.asyncio
    async def test_update_entra_happy_path_domain_update(self):
        """Domain change → tenant_configs updated with new domain."""
        from app.modules.admin.sso_entra import update_entra_sso, EntraUpdateRequest

        db = _make_db()
        user = _make_user()
        existing = {
            "provider_type": "entra",
            "auth0_connection_id": _CONN_ID,
            "enabled": True,
            "domain": "old.contoso.com",
            "client_id": _VALID_CLIENT_ID,
        }

        request = EntraUpdateRequest(domain="new.contoso.com")

        with (
            patch(
                "app.modules.admin.sso_entra._get_sso_provider_config_db",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "app.modules.admin.sso_entra.management_api_request",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            response = await update_entra_sso(request, user, db)

        assert response.domain == "new.contoso.com"
        # tenant_configs INSERT + audit_log INSERT
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_update_entra_not_configured_returns_404(self):
        """No existing config → HTTPException 404."""
        from app.modules.admin.sso_entra import update_entra_sso, EntraUpdateRequest

        db = _make_db()
        user = _make_user()
        request = EntraUpdateRequest(client_secret="new-secret")

        with (
            patch(
                "app.modules.admin.sso_entra._get_sso_provider_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_entra_sso(request, user, db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_entra_empty_body_returns_400(self):
        """Neither client_secret nor domain provided → HTTPException 400."""
        from app.modules.admin.sso_entra import update_entra_sso, EntraUpdateRequest

        db = _make_db()
        user = _make_user()
        request = EntraUpdateRequest()  # both fields None

        with pytest.raises(HTTPException) as exc_info:
            await update_entra_sso(request, user, db)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_update_entra_management_api_failure_returns_502(self):
        """management_api_request PATCH raises RuntimeError → 502."""
        from app.modules.admin.sso_entra import update_entra_sso, EntraUpdateRequest

        db = _make_db()
        user = _make_user()
        existing = {
            "provider_type": "entra",
            "auth0_connection_id": _CONN_ID,
            "enabled": True,
            "domain": _VALID_DOMAIN,
            "client_id": _VALID_CLIENT_ID,
        }
        request = EntraUpdateRequest(client_secret="new-secret")

        with (
            patch(
                "app.modules.admin.sso_entra._get_sso_provider_config_db",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "app.modules.admin.sso_entra.management_api_request",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Auth0 PATCH failed"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_entra_sso(request, user, db)

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_update_entra_secret_not_in_response(self):
        """Response from update must not contain client_secret field."""
        from app.modules.admin.sso_entra import update_entra_sso, EntraUpdateRequest

        db = _make_db()
        user = _make_user()
        existing = {
            "provider_type": "entra",
            "auth0_connection_id": _CONN_ID,
            "enabled": True,
            "domain": _VALID_DOMAIN,
            "client_id": _VALID_CLIENT_ID,
        }
        request = EntraUpdateRequest(client_secret="rotated-secret-value")

        with (
            patch(
                "app.modules.admin.sso_entra._get_sso_provider_config_db",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "app.modules.admin.sso_entra.management_api_request",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            response = await update_entra_sso(request, user, db)

        response_dict = response.model_dump()
        assert "client_secret" not in response_dict


# ---------------------------------------------------------------------------
# Tests 18-20: test_entra_sso (direct handler)
# ---------------------------------------------------------------------------


class TestTestEntra:
    """POST /admin/sso/entra/test"""

    @pytest.mark.asyncio
    async def test_test_entra_returns_test_url(self):
        """Happy path → test_url contains connection param."""
        from app.modules.admin.sso_entra import test_entra_sso

        db = _make_db()
        user = _make_user()
        config = {
            "provider_type": "entra",
            "auth0_connection_id": _CONN_ID,
            "enabled": True,
            "domain": _VALID_DOMAIN,
        }

        with (
            patch(
                "app.modules.admin.sso_entra._get_sso_provider_config_db",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patch.dict(os.environ, {"AUTH0_DOMAIN": "mingai-dev.jp.auth0.com"}),
        ):
            response = await test_entra_sso(user, db)

        assert _CONN_ID in response.test_url
        assert "authorize" in response.test_url
        assert "response_type=code" in response.test_url

    @pytest.mark.asyncio
    async def test_test_entra_not_configured_returns_404(self):
        """No config stored → HTTPException 404."""
        from app.modules.admin.sso_entra import test_entra_sso

        db = _make_db()
        user = _make_user()

        with (
            patch(
                "app.modules.admin.sso_entra._get_sso_provider_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await test_entra_sso(user, db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_test_entra_disabled_returns_404(self):
        """Config with enabled=False → HTTPException 404."""
        from app.modules.admin.sso_entra import test_entra_sso

        db = _make_db()
        user = _make_user()
        config = {
            "provider_type": "entra",
            "auth0_connection_id": _CONN_ID,
            "enabled": False,
            "domain": _VALID_DOMAIN,
        }

        with (
            patch(
                "app.modules.admin.sso_entra._get_sso_provider_config_db",
                new_callable=AsyncMock,
                return_value=config,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await test_entra_sso(user, db)

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Tests 21-22: update_sso_connection_config Entra org lifecycle (ENTRA-003)
# ---------------------------------------------------------------------------


class TestEntraOrgLifecycle:
    """
    Tests 21-22 exercise the Entra org lifecycle inside update_sso_connection_config
    from workspace.py (ENTRA-003).
    """

    @pytest.mark.asyncio
    async def test_disable_entra_calls_org_remove(self):
        """
        PATCH /admin/sso/config with enabled=False on an Entra config →
        management_api DELETE organizations/{org_id}/enabled_connections/{connection_id} called.
        """
        from app.modules.admin.workspace import update_sso_connection_config
        from app.modules.admin.workspace import SSOConnectionConfigRequest

        db = _make_db()
        user = _make_user()

        old_config = {
            "provider_type": "entra",
            "auth0_connection_id": _CONN_ID,
            "enabled": True,
        }

        request = SSOConnectionConfigRequest(
            provider_type="entra",
            auth0_connection_id=_CONN_ID,
            enabled=False,
        )

        mgmt_calls: list = []

        async def _capture_mgmt(method, path, body=None):
            mgmt_calls.append((method, path))
            return {}

        with (
            patch(
                "app.modules.admin.workspace._get_sso_connection_config_db",
                new_callable=AsyncMock,
                return_value=old_config,
            ),
            patch(
                "app.modules.admin.workspace._upsert_sso_connection_config_db",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.admin.workspace.get_tenant_auth0_org_id",
                new_callable=AsyncMock,
                return_value=_ORG_ID,
            ),
            patch(
                "app.modules.admin.workspace.management_api_request",
                side_effect=_capture_mgmt,
            ),
        ):
            await update_sso_connection_config(request, user, db)

        delete_calls = [
            c
            for c in mgmt_calls
            if c[0] == "DELETE"
            and f"organizations/{_ORG_ID}/enabled_connections/{_CONN_ID}" in c[1]
        ]
        assert len(delete_calls) == 1, f"Expected 1 DELETE org call, got: {mgmt_calls}"

    @pytest.mark.asyncio
    async def test_reenable_entra_calls_org_add(self):
        """
        PATCH /admin/sso/config with enabled=True on a previously disabled Entra config →
        management_api POST organizations/{org_id}/enabled_connections called.
        """
        from app.modules.admin.workspace import update_sso_connection_config
        from app.modules.admin.workspace import SSOConnectionConfigRequest

        db = _make_db()
        user = _make_user()

        old_config = {
            "provider_type": "entra",
            "auth0_connection_id": _CONN_ID,
            "enabled": False,
        }

        request = SSOConnectionConfigRequest(
            provider_type="entra",
            auth0_connection_id=_CONN_ID,
            enabled=True,
        )

        mgmt_calls: list = []

        async def _capture_mgmt(method, path, body=None):
            mgmt_calls.append((method, path, body))
            return {}

        with (
            patch(
                "app.modules.admin.workspace._get_sso_connection_config_db",
                new_callable=AsyncMock,
                return_value=old_config,
            ),
            patch(
                "app.modules.admin.workspace._upsert_sso_connection_config_db",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.admin.workspace.get_tenant_auth0_org_id",
                new_callable=AsyncMock,
                return_value=_ORG_ID,
            ),
            patch(
                "app.modules.admin.workspace.management_api_request",
                side_effect=_capture_mgmt,
            ),
        ):
            await update_sso_connection_config(request, user, db)

        post_calls = [
            c
            for c in mgmt_calls
            if c[0] == "POST" and f"organizations/{_ORG_ID}/enabled_connections" in c[1]
        ]
        assert len(post_calls) == 1, f"Expected 1 POST org call, got: {mgmt_calls}"
        assert post_calls[0][2]["connection_id"] == _CONN_ID
