"""ATA-009 unit tests: _check_agent_access in ChatOrchestrationService."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.chat.orchestrator import ChatOrchestrationService


def _make_service(db_result=None):
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = db_result
    mock_db.execute = AsyncMock(return_value=mock_result)

    svc = ChatOrchestrationService.__new__(ChatOrchestrationService)
    svc._db_session = mock_db
    return svc


@pytest.mark.asyncio
async def test_access_check_no_row_defaults_allow():
    """No agent_access_control row — allow by default (workspace_wide fallback)."""
    svc = _make_service(db_result=None)
    result = await svc._check_agent_access(
        agent_id="a1", tenant_id="t1", user_id="u1", user_roles=[]
    )
    assert result is True


@pytest.mark.asyncio
async def test_access_check_workspace_wide_allows_all():
    svc = _make_service(
        db_result={
            "visibility_mode": "workspace_wide",
            "allowed_roles": [],
            "allowed_user_ids": [],
        }
    )
    result = await svc._check_agent_access(
        agent_id="a1", tenant_id="t1", user_id="u1", user_roles=["viewer"]
    )
    assert result is True


@pytest.mark.asyncio
async def test_access_check_role_restricted_matching_role():
    svc = _make_service(
        db_result={
            "visibility_mode": "role_restricted",
            "allowed_roles": ["hr_manager"],
            "allowed_user_ids": [],
        }
    )
    result = await svc._check_agent_access(
        agent_id="a1",
        tenant_id="t1",
        user_id="u1",
        user_roles=["hr_manager", "viewer"],
    )
    assert result is True


@pytest.mark.asyncio
async def test_access_check_role_restricted_no_match():
    svc = _make_service(
        db_result={
            "visibility_mode": "role_restricted",
            "allowed_roles": ["hr_manager"],
            "allowed_user_ids": [],
        }
    )
    result = await svc._check_agent_access(
        agent_id="a1", tenant_id="t1", user_id="u1", user_roles=["viewer"]
    )
    assert result is False


@pytest.mark.asyncio
async def test_access_check_role_restricted_empty_allowed_roles():
    """role_restricted with no allowed_roles denies everyone."""
    svc = _make_service(
        db_result={
            "visibility_mode": "role_restricted",
            "allowed_roles": [],
            "allowed_user_ids": [],
        }
    )
    result = await svc._check_agent_access(
        agent_id="a1", tenant_id="t1", user_id="u1", user_roles=["admin"]
    )
    assert result is False


@pytest.mark.asyncio
async def test_access_check_user_specific_matching_user():
    svc = _make_service(
        db_result={
            "visibility_mode": "user_specific",
            "allowed_roles": [],
            "allowed_user_ids": ["u1"],
        }
    )
    result = await svc._check_agent_access(
        agent_id="a1", tenant_id="t1", user_id="u1", user_roles=[]
    )
    assert result is True


@pytest.mark.asyncio
async def test_access_check_user_specific_no_match():
    svc = _make_service(
        db_result={
            "visibility_mode": "user_specific",
            "allowed_roles": [],
            "allowed_user_ids": ["u2"],
        }
    )
    result = await svc._check_agent_access(
        agent_id="a1", tenant_id="t1", user_id="u1", user_roles=[]
    )
    assert result is False


@pytest.mark.asyncio
async def test_access_check_no_db_session_denies():
    """No DB session — fail closed. Production code always passes db; no-session is a bug."""
    svc = ChatOrchestrationService.__new__(ChatOrchestrationService)
    svc._db_session = None
    result = await svc._check_agent_access(
        agent_id="a1", tenant_id="t1", user_id="u1", user_roles=[]
    )
    assert result is False


@pytest.mark.asyncio
async def test_access_check_db_error_fails_closed():
    """DB exception on access check — fail closed (deny) to protect restricted agents."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=RuntimeError("connection lost"))
    svc = ChatOrchestrationService.__new__(ChatOrchestrationService)
    svc._db_session = mock_db
    result = await svc._check_agent_access(
        agent_id="a1", tenant_id="t1", user_id="u1", user_roles=[]
    )
    assert result is False


@pytest.mark.asyncio
async def test_access_check_unknown_visibility_mode_fails_closed():
    """Unknown visibility_mode — fail closed to prevent access via unrecognized modes."""
    svc = _make_service(
        db_result={
            "visibility_mode": "unknown_future_mode",
            "allowed_roles": [],
            "allowed_user_ids": [],
        }
    )
    result = await svc._check_agent_access(
        agent_id="a1", tenant_id="t1", user_id="u1", user_roles=[]
    )
    assert result is False
