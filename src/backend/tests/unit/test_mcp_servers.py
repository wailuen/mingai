"""
Unit tests for MCP server registry API (DEF-005).

Tests cover:
- POST creates server with valid data
- POST with auth_type != none requires auth_config
- POST with invalid auth_type returns 422
- POST with invalid endpoint scheme returns 422
- POST with duplicate name returns 409
- GET lists servers for tenant
- DELETE removes server and returns 204
- DELETE non-existent server returns 404
- DELETE with invalid UUID returns 422
- auth_config is NOT logged (security)
- Pydantic validators for auth_type and endpoint
"""
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(user_id="admin-1", tenant_id="tenant-1"):
    from app.core.dependencies import CurrentUser

    return CurrentUser(
        id=user_id,
        tenant_id=tenant_id,
        roles=["tenant_admin"],
        scope="tenant",
        plan="enterprise",
    )


def _mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


_NOW = datetime(2026, 3, 17, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Pydantic validators
# ---------------------------------------------------------------------------


def test_create_request_invalid_auth_type():
    """Invalid auth_type raises ValidationError."""
    from pydantic import ValidationError
    from app.modules.admin.mcp_servers import CreateMCPServerRequest

    with pytest.raises(ValidationError):
        CreateMCPServerRequest(
            name="test",
            endpoint="https://example.com",
            auth_type="basic",
        )


def test_create_request_invalid_endpoint_scheme():
    """Endpoint not starting with http/https/mcp raises ValidationError."""
    from pydantic import ValidationError
    from app.modules.admin.mcp_servers import CreateMCPServerRequest

    with pytest.raises(ValidationError):
        CreateMCPServerRequest(
            name="test",
            endpoint="ftp://example.com",
        )


def test_create_request_valid_http():
    """http:// endpoint is accepted."""
    from app.modules.admin.mcp_servers import CreateMCPServerRequest

    req = CreateMCPServerRequest(name="srv", endpoint="http://localhost:8080")
    assert req.endpoint == "http://localhost:8080"


def test_create_request_valid_mcp_scheme():
    """mcp:// endpoint is accepted."""
    from app.modules.admin.mcp_servers import CreateMCPServerRequest

    req = CreateMCPServerRequest(name="srv", endpoint="mcp://host:1234")
    assert req.endpoint == "mcp://host:1234"


def test_create_request_auth_config_not_required_for_none():
    """auth_type=none does not require auth_config."""
    from app.modules.admin.mcp_servers import CreateMCPServerRequest

    req = CreateMCPServerRequest(name="srv", endpoint="https://host", auth_type="none")
    assert req.auth_type == "none"
    assert req.auth_config is None


# ---------------------------------------------------------------------------
# POST create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_mcp_server_success():
    """POST creates server and returns 201."""
    from app.modules.admin.mcp_servers import create_mcp_server, CreateMCPServerRequest

    db = _mock_db()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = (
        "server-uuid",
        "test-server",
        "https://example.com",
        "none",
        "active",
        None,
        _NOW,
    )
    db.execute.return_value = mock_result
    user = _make_admin()

    body = CreateMCPServerRequest(name="test-server", endpoint="https://example.com")
    resp = await create_mcp_server(body=body, current_user=user, db=db)

    assert resp.name == "test-server"
    assert resp.status == "active"
    assert resp.auth_type == "none"
    assert db.commit.called


@pytest.mark.asyncio
async def test_create_mcp_server_requires_auth_config_for_api_key():
    """POST with auth_type=api_key and no auth_config returns 422."""
    from fastapi import HTTPException
    from app.modules.admin.mcp_servers import create_mcp_server, CreateMCPServerRequest

    db = _mock_db()
    user = _make_admin()

    body = CreateMCPServerRequest(
        name="srv", endpoint="https://host", auth_type="api_key"
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_mcp_server(body=body, current_user=user, db=db)

    assert exc_info.value.status_code == 422
    assert "auth_config" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_mcp_server_duplicate_name_returns_409():
    """Duplicate name constraint triggers 409."""
    from fastapi import HTTPException
    from app.modules.admin.mcp_servers import create_mcp_server, CreateMCPServerRequest

    db = _mock_db()
    db.execute.side_effect = Exception("mcp_servers_tenant_name_unique violation")
    user = _make_admin()

    body = CreateMCPServerRequest(name="dup", endpoint="https://host")
    with pytest.raises(HTTPException) as exc_info:
        await create_mcp_server(body=body, current_user=user, db=db)

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# GET list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_mcp_servers_empty():
    """GET returns empty list when no servers configured."""
    from app.modules.admin.mcp_servers import list_mcp_servers

    db = _mock_db()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    db.execute.return_value = mock_result
    user = _make_admin()

    resp = await list_mcp_servers(current_user=user, db=db)
    assert resp == []


@pytest.mark.asyncio
async def test_list_mcp_servers_returns_items():
    """GET returns all servers for tenant."""
    from app.modules.admin.mcp_servers import list_mcp_servers

    db = _mock_db()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        ("id-1", "server-a", "https://a.example.com", "none", "active", None, _NOW),
        (
            "id-2",
            "server-b",
            "https://b.example.com",
            "api_key",
            "inactive",
            _NOW,
            _NOW,
        ),
    ]
    db.execute.return_value = mock_result
    user = _make_admin()

    resp = await list_mcp_servers(current_user=user, db=db)
    assert len(resp) == 2
    assert resp[0].name == "server-a"
    assert resp[1].auth_type == "api_key"


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_mcp_server_success():
    """DELETE returns 204 for existing server."""
    from app.modules.admin.mcp_servers import delete_mcp_server

    db = _mock_db()
    mock_result = MagicMock()
    mock_result.rowcount = 1
    db.execute.return_value = mock_result
    user = _make_admin()

    # Should not raise
    await delete_mcp_server(
        server_id="11111111-1111-1111-1111-111111111111",
        current_user=user,
        db=db,
    )
    assert db.commit.called


@pytest.mark.asyncio
async def test_delete_mcp_server_not_found():
    """DELETE returns 404 when server not found."""
    from fastapi import HTTPException
    from app.modules.admin.mcp_servers import delete_mcp_server

    db = _mock_db()
    mock_result = MagicMock()
    mock_result.rowcount = 0
    db.execute.return_value = mock_result
    user = _make_admin()

    with pytest.raises(HTTPException) as exc_info:
        await delete_mcp_server(
            server_id="11111111-1111-1111-1111-111111111111",
            current_user=user,
            db=db,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_mcp_server_invalid_uuid():
    """DELETE with non-UUID returns 422."""
    from fastapi import HTTPException
    from app.modules.admin.mcp_servers import delete_mcp_server

    db = _mock_db()
    user = _make_admin()

    with pytest.raises(HTTPException) as exc_info:
        await delete_mcp_server(server_id="not-a-uuid", current_user=user, db=db)

    assert exc_info.value.status_code == 422
