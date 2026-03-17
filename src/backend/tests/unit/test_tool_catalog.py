"""
Unit tests for PA-031: Tool catalog API.

  GET  /platform/tools
  POST /platform/tools
  GET  /platform/tools/{id}
  DELETE /platform/tools/{id}

Tier 1: Fast, isolated. Uses dependency_overrides + AsyncMock.
"""
import contextlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_TOOL_ID = str(uuid.uuid4())

_TOOLS_URL = "/api/v1/platform/tools"


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "platform-admin-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "email": "platform@mingai.io",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_tenant_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-user-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
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
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture
def client(env_vars):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def _platform_headers() -> dict:
    return {"Authorization": f"Bearer {_make_platform_token()}"}


def _tenant_headers() -> dict:
    return {"Authorization": f"Bearer {_make_tenant_token()}"}


def _make_tool_row(
    tool_id: str = TEST_TOOL_ID,
    name: str = "my-tool",
    safety: str = "ReadOnly",
    health: str = "healthy",
):
    """Return a mock tool_catalog row tuple."""
    import json as _json

    return (
        uuid.UUID(tool_id),  # 0: id
        name,  # 1: name
        "acme-corp",  # 2: provider
        "https://tools.acme.io/mcp",  # 3: mcp_endpoint
        "api_key",  # 4: auth_type
        _json.dumps(["search", "read"]),  # 5: capabilities (jsonb as str)
        safety,  # 6: safety_classification
        health,  # 7: health_status
        "1.2.3",  # 8: version
        None,  # 9: last_health_check
        "https://tools.acme.io/health",  # 10: health_check_url
        datetime(2026, 3, 16, 0, 0, 0, tzinfo=timezone.utc),  # 11: created_at
    )


def _patch_db_list(total: int, tool_rows: list):
    """Patch get_async_session for list tools.

    Call order:
      1. set_config scope
      2. set_config tenant_id
      3. COUNT(*) → scalar → total
      4. SELECT tools → fetchall → tool_rows
    """
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()
    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count <= 2:
            mock_result.scalar.return_value = None
            mock_result.fetchall.return_value = []
        elif call_count == 3:
            mock_result.scalar.return_value = total
            mock_result.fetchall.return_value = []
        else:
            mock_result.fetchall.return_value = tool_rows
        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override

    @contextlib.contextmanager
    def _ctx():
        try:
            yield
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    return _ctx()


def _patch_db_get(tool_row):
    """Patch for GET /platform/tools/{id} — 3 calls: 2 set_config + SELECT."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()
    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count <= 2:
            mock_result.fetchone.return_value = None
        else:
            mock_result.fetchone.return_value = tool_row
        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override

    @contextlib.contextmanager
    def _ctx():
        try:
            yield
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    return _ctx()


def _patch_db_delete(deleted_row, assignments=None):
    """Patch for DELETE /platform/tools/{id}.

    Call order:
      1. set_config scope
      2. set_config tenant_id
      3. SELECT tenant assignments (may raise if table missing → treated as [])
      4. DELETE → fetchone → deleted_row
    """
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()
    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count <= 2:
            mock_result.fetchone.return_value = None
            mock_result.fetchall.return_value = []
        elif call_count == 3:
            # tenant assignments query
            mock_result.fetchall.return_value = assignments or []
        else:
            mock_result.fetchone.return_value = deleted_row
        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override

    @contextlib.contextmanager
    def _ctx():
        try:
            yield
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    return _ctx()


_VALID_PAYLOAD = {
    "name": "my-tool",
    "provider": "acme-corp",
    "mcp_endpoint": "https://tools.acme.io/mcp",
    "auth_type": "api_key",
    "capabilities": ["search", "read"],
    "safety_classification": "ReadOnly",
    "version": "1.2.3",
    "health_check_url": "https://tools.acme.io/health",
}


class TestToolCatalogAuth:
    def test_list_requires_auth(self, client):
        resp = client.get(_TOOLS_URL)
        assert resp.status_code == 401

    def test_list_requires_platform_admin(self, client):
        resp = client.get(_TOOLS_URL, headers=_tenant_headers())
        assert resp.status_code == 403

    def test_post_requires_auth(self, client):
        resp = client.post(_TOOLS_URL, json=_VALID_PAYLOAD)
        assert resp.status_code == 401

    def test_delete_requires_platform_admin(self, client):
        resp = client.delete(f"{_TOOLS_URL}/{TEST_TOOL_ID}", headers=_tenant_headers())
        assert resp.status_code == 403


class TestListTools:
    def test_returns_tools_and_total(self, client):
        rows = [_make_tool_row()]
        with _patch_db_list(1, rows):
            resp = client.get(_TOOLS_URL, headers=_platform_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        assert "total" in data
        assert data["total"] == 1
        assert len(data["tools"]) == 1

    def test_tool_structure(self, client):
        rows = [_make_tool_row()]
        with _patch_db_list(1, rows):
            resp = client.get(_TOOLS_URL, headers=_platform_headers())
        tool = resp.json()["tools"][0]
        assert tool["id"] == TEST_TOOL_ID
        assert tool["name"] == "my-tool"
        assert tool["safety_classification"] == "ReadOnly"
        assert tool["health_status"] == "healthy"
        assert isinstance(tool["capabilities"], list)

    def test_empty_catalog(self, client):
        with _patch_db_list(0, []):
            resp = client.get(_TOOLS_URL, headers=_platform_headers())
        assert resp.status_code == 200
        assert resp.json()["tools"] == []
        assert resp.json()["total"] == 0


class TestGetTool:
    def test_get_existing_tool(self, client):
        row = _make_tool_row()
        with _patch_db_get(row):
            resp = client.get(
                f"{_TOOLS_URL}/{TEST_TOOL_ID}", headers=_platform_headers()
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == TEST_TOOL_ID

    def test_get_missing_tool_returns_404(self, client):
        with _patch_db_get(None):
            resp = client.get(
                f"{_TOOLS_URL}/{TEST_TOOL_ID}", headers=_platform_headers()
            )
        assert resp.status_code == 404


class TestRegisterTool:
    def test_health_check_failure_returns_422(self, client):
        """When health check fails, registration returns 422 with step+detail."""
        with patch(
            "app.modules.platform.routes._run_tool_health_checks",
            new=AsyncMock(
                return_value=(False, "endpoint_reachability", "Connection refused")
            ),
        ):
            resp = client.post(
                _TOOLS_URL, json=_VALID_PAYLOAD, headers=_platform_headers()
            )
        assert resp.status_code == 422
        # The app's error middleware serializes HTTPException detail as a string.
        detail_str = str(resp.json().get("detail", ""))
        assert "endpoint_reachability" in detail_str
        assert "Connection refused" in detail_str

    def test_successful_registration_returns_201(self, client):
        """When health checks pass, tool is inserted and 201 returned."""
        inserted_row = _make_tool_row()
        from app.core.session import get_async_session
        from app.main import app

        mock_session = MagicMock()
        call_count = 0

        async def _execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count <= 2:
                mock_result.fetchone.return_value = None
            else:
                mock_result.fetchone.return_value = inserted_row
            return mock_result

        mock_session.execute = AsyncMock(side_effect=_execute)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()

        async def _override():
            yield mock_session

        app.dependency_overrides[get_async_session] = _override

        try:
            with patch(
                "app.modules.platform.routes._run_tool_health_checks",
                new=AsyncMock(return_value=(True, "", "")),
            ):
                resp = client.post(
                    _TOOLS_URL, json=_VALID_PAYLOAD, headers=_platform_headers()
                )
        finally:
            app.dependency_overrides.pop(get_async_session, None)

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "my-tool"
        assert data["safety_classification"] == "ReadOnly"

    def test_invalid_auth_type_returns_422(self, client):
        bad_payload = {**_VALID_PAYLOAD, "auth_type": "basic"}
        resp = client.post(_TOOLS_URL, json=bad_payload, headers=_platform_headers())
        assert resp.status_code == 422

    def test_invalid_safety_classification_returns_422(self, client):
        bad_payload = {**_VALID_PAYLOAD, "safety_classification": "Unknown"}
        resp = client.post(_TOOLS_URL, json=bad_payload, headers=_platform_headers())
        assert resp.status_code == 422


class TestDeleteTool:
    def test_delete_existing_tool(self, client):
        deleted_row = (uuid.UUID(TEST_TOOL_ID), "my-tool")
        with _patch_db_delete(deleted_row):
            resp = client.delete(
                f"{_TOOLS_URL}/{TEST_TOOL_ID}", headers=_platform_headers()
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True
        assert data["tool_id"] == TEST_TOOL_ID
        assert data["tool_name"] == "my-tool"

    def test_delete_missing_tool_returns_404(self, client):
        with _patch_db_delete(None):
            resp = client.delete(
                f"{_TOOLS_URL}/{TEST_TOOL_ID}", headers=_platform_headers()
            )
        assert resp.status_code == 404

    def test_delete_reports_affected_tenant_count(self, client):
        deleted_row = (uuid.UUID(TEST_TOOL_ID), "my-tool")
        assignments = [
            (uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), "Tenant A"),
            (uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"), "Tenant B"),
        ]
        with _patch_db_delete(deleted_row, assignments):
            resp = client.delete(
                f"{_TOOLS_URL}/{TEST_TOOL_ID}", headers=_platform_headers()
            )
        assert resp.status_code == 200
        assert resp.json()["affected_tenant_count"] == 2
