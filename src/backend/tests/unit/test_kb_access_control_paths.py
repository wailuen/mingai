"""
Unit tests for KB access control route paths (DEF-011).

Tests cover:
- GET /admin/knowledge-base/{id}/access-control is reachable
- PATCH /admin/knowledge-base/{id}/access-control is reachable
- GET /admin/knowledge-base/{id}/access (alias) is also reachable
- PATCH /admin/knowledge-base/{id}/access (alias) is also reachable
- 404 for non-existent KB index (foreign tenant scenario emulation)
- Invalid UUID returns 422
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(tenant_id="tenant-1"):
    from app.core.dependencies import CurrentUser

    return CurrentUser(
        id="admin-1",
        tenant_id=tenant_id,
        roles=["tenant_admin"],
        scope="tenant",
        plan="professional",
    )


def _mock_db(row=None):
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = row
    mock_result.scalar.return_value = 0
    db.execute.return_value = mock_result
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Route path tests (via route functions directly)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_access_control_returns_default_when_no_row():
    """GET /access-control returns workspace_wide default when KB is owned but no row."""
    from app.modules.admin.kb_access_control import get_kb_access

    kb_id = str(uuid.uuid4())
    db = _mock_db(row=None)
    user = _make_admin()

    # Ownership check must return truthy; second SELECT returns None (no row).
    call_count = [0]
    original_execute = db.execute

    async def _side_effect(sql, params=None):
        call_count[0] += 1
        result = MagicMock()
        sql_str = str(sql)
        if "UNION ALL" in sql_str.upper():
            result.fetchone.return_value = ("1",)
        else:
            result.fetchone.return_value = None
        return result

    db.execute = AsyncMock(side_effect=_side_effect)

    resp = await get_kb_access(index_id=kb_id, current_user=user, db=db)

    assert resp.visibility_mode == "workspace_wide"
    assert resp.index_id == kb_id
    assert resp.allowed_roles == []
    assert resp.allowed_user_ids == []


@pytest.mark.asyncio
async def test_get_access_control_returns_stored_row():
    """GET returns stored access control config."""
    from app.modules.admin.kb_access_control import get_kb_access

    kb_id = str(uuid.uuid4())
    user = _make_admin()
    db = _mock_db()

    async def _side_effect(sql, params=None):
        result = MagicMock()
        sql_str = str(sql)
        if "UNION ALL" in sql_str.upper():
            result.fetchone.return_value = ("1",)
        else:
            result.fetchone.return_value = ("role_restricted", ["admin"], [])
        return result

    db.execute = AsyncMock(side_effect=_side_effect)

    resp = await get_kb_access(index_id=kb_id, current_user=user, db=db)
    assert resp.visibility_mode == "role_restricted"
    assert resp.allowed_roles == ["admin"]


@pytest.mark.asyncio
async def test_get_access_control_foreign_tenant_returns_404():
    """GET for KB not owned by tenant returns 404."""
    from fastapi import HTTPException
    from app.modules.admin.kb_access_control import get_kb_access

    kb_id = str(uuid.uuid4())
    user = _make_admin()
    db = _mock_db(row=None)

    async def _side_effect(sql, params=None):
        result = MagicMock()
        result.fetchone.return_value = None
        return result

    db.execute = AsyncMock(side_effect=_side_effect)

    with pytest.raises(HTTPException) as exc_info:
        await get_kb_access(index_id=kb_id, current_user=user, db=db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_access_control_invalid_uuid_returns_422():
    """GET with invalid UUID returns 422."""
    from fastapi import HTTPException
    from app.modules.admin.kb_access_control import get_kb_access

    db = _mock_db()
    user = _make_admin()

    with pytest.raises(HTTPException) as exc_info:
        await get_kb_access(index_id="not-a-uuid", current_user=user, db=db)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_patch_access_control_upserts():
    """PATCH /access-control upserts and returns updated config."""
    from app.modules.admin.kb_access_control import (
        patch_kb_access,
        PatchKBAccessRequest,
    )

    kb_id = str(uuid.uuid4())
    user = _make_admin()
    db = _mock_db()

    async def _side_effect(sql, params=None):
        result = MagicMock()
        sql_str = str(sql)
        if "UNION ALL" in sql_str.upper():
            result.fetchone.return_value = ("1",)
        else:
            result.fetchone.return_value = None
            result.scalar.return_value = None
        return result

    db.execute = AsyncMock(side_effect=_side_effect)

    body = PatchKBAccessRequest(visibility_mode="workspace_wide")
    resp = await patch_kb_access(index_id=kb_id, body=body, current_user=user, db=db)
    assert resp.visibility_mode == "workspace_wide"
    assert resp.index_id == kb_id


@pytest.mark.asyncio
async def test_patch_access_control_invalid_uuid_returns_422():
    """PATCH with invalid UUID returns 422."""
    from fastapi import HTTPException
    from app.modules.admin.kb_access_control import (
        patch_kb_access,
        PatchKBAccessRequest,
    )

    db = _mock_db()
    user = _make_admin()

    body = PatchKBAccessRequest(visibility_mode="workspace_wide")
    with pytest.raises(HTTPException) as exc_info:
        await patch_kb_access(index_id="bad-id", body=body, current_user=user, db=db)
    assert exc_info.value.status_code == 422


def test_router_has_access_control_paths():
    """Router registers both /access-control and /access paths."""
    from app.modules.admin.kb_access_control import router

    routes = {r.path for r in router.routes}
    # Canonical paths with hyphen
    assert any(
        "access-control" in path for path in routes
    ), "Expected /access-control path in router"
    # Backward-compat alias without hyphen
    assert any(
        path.endswith("/access") for path in routes
    ), "Expected /access alias path in router"
