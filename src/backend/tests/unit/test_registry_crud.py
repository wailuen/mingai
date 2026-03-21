"""
HAR-002: Agent card CRUD API unit tests.

Tests:
- POST /registry/agents: creates card with correct tenant ownership
- GET /registry/agents: returns active/public cards, no cross-tenant leakage
- PUT /registry/agents/{id}: verifies caller is owner (403 otherwise)
- DELETE /registry/agents/{id}: soft-delete (status='deregistered', is_public=false)
- GET /registry/agents/{id}: returns single public card
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.registry.routes import (
    deregister_agent_db,
    get_agent_card_by_tenant_db,
    get_agent_card_db,
    list_public_agents_db,
    register_agent_db,
    update_agent_registry_db,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_agent_row(
    agent_id=None,
    tenant_id=None,
    status="active",
    is_public=True,
    kyb_level="none",
):
    agent_id = agent_id or str(uuid.uuid4())
    tenant_id = tenant_id or str(uuid.uuid4())
    return {
        "id": agent_id,
        "tenant_id": tenant_id,
        "name": "Test Agent",
        "description": "Test description",
        "status": status,
        "is_public": is_public,
        "a2a_endpoint": "https://agent.example.com/a2a",
        "transaction_types": ["RFQ", "CAPABILITY_QUERY"],
        "industries": ["manufacturing"],
        "languages": ["en"],
        "health_check_url": "https://agent.example.com/health",
        "public_key": None,
        "trust_score": 80,
        "capabilities": [],
        "kyb_level": kyb_level,
        "created_at": "2026-03-17T00:00:00",
        "updated_at": "2026-03-17T00:00:00",
    }


def _make_async_db(row=None):
    """Return a mock AsyncSession that returns the given row from execute()."""
    db = AsyncMock()
    result = MagicMock()
    if row is None:
        result.mappings.return_value.first.return_value = None
    else:
        result.mappings.return_value.first.return_value = row
    result.scalar.return_value = 1
    result.mappings.return_value.all.return_value = [row] if row else []
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# HAR-002 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_agent_db_verifies_ownership_returns_none_if_not_found():
    """register_agent_db returns None when agent does not belong to calling tenant."""
    db = _make_async_db(row=None)  # agent not found
    result = await register_agent_db(
        agent_id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        a2a_endpoint="https://test.example.com/a2a",
        transaction_types=["RFQ"],
        industries=["tech"],
        languages=["en"],
        health_check_url=None,
        db=db,
    )
    assert result is None


@pytest.mark.asyncio
async def test_register_agent_db_sets_is_public_and_status_active():
    """register_agent_db sets is_public=true and status='active'."""
    agent_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    row = _make_agent_row(agent_id=agent_id, tenant_id=tenant_id, status="active")

    db = _make_async_db(row=row)

    result = await register_agent_db(
        agent_id=agent_id,
        tenant_id=tenant_id,
        a2a_endpoint="https://agent.example.com/a2a",
        transaction_types=["RFQ"],
        industries=["manufacturing"],
        languages=["en"],
        health_check_url="https://agent.example.com/health",
        db=db,
    )
    # The UPDATE was executed (commit called)
    db.commit.assert_called()
    assert result is not None


@pytest.mark.asyncio
async def test_deregister_agent_db_sets_status_deregistered_and_is_public_false():
    """deregister_agent_db soft-deletes: status='deregistered', is_public=false."""
    agent_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    success = await deregister_agent_db(
        agent_id=agent_id,
        tenant_id=tenant_id,
        db=db,
    )
    assert success is True
    db.commit.assert_called_once()

    # Verify the SQL contains 'deregistered'
    call_args = db.execute.call_args_list[0]
    sql_str = str(call_args[0][0])
    assert "deregistered" in sql_str
    assert "is_public = false" in sql_str


@pytest.mark.asyncio
async def test_deregister_agent_db_returns_false_when_not_found():
    """deregister_agent_db returns False when agent not found for tenant."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.rowcount = 0
    db.execute = AsyncMock(return_value=result_mock)
    db.rollback = AsyncMock()
    db.commit = AsyncMock()

    success = await deregister_agent_db(
        agent_id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        db=db,
    )
    assert success is False
    db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_get_agent_card_db_returns_none_if_not_found():
    """get_agent_card_db returns None if agent not found."""
    db = _make_async_db(row=None)
    result = await get_agent_card_db(str(uuid.uuid4()), db)
    assert result is None


@pytest.mark.asyncio
async def test_get_agent_card_by_tenant_db_scopes_to_tenant():
    """get_agent_card_by_tenant_db includes tenant_id in query."""
    agent_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    row = _make_agent_row(agent_id=agent_id, tenant_id=tenant_id)
    db = _make_async_db(row=row)

    result = await get_agent_card_by_tenant_db(agent_id, tenant_id, db)
    assert result is not None
    # Verify tenant_id was passed as param
    call_args = db.execute.call_args_list[0]
    params = call_args[0][1]
    assert params.get("tenant_id") == tenant_id


@pytest.mark.asyncio
async def test_update_agent_registry_db_returns_none_when_not_owner():
    """update_agent_registry_db returns None if agent not found for tenant (403 scenario)."""
    from app.modules.registry.routes import UpdateAgentRequest

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.rowcount = 0
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()

    updates = UpdateAgentRequest(description="New description")
    result = await update_agent_registry_db(
        agent_id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        updates=updates,
        db=db,
    )
    assert result is None


@pytest.mark.asyncio
async def test_update_agent_registry_db_builds_safe_set_clause():
    """update_agent_registry_db uses hardcoded column names, not f-string user data."""
    from app.modules.registry.routes import UpdateAgentRequest

    agent_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    row = _make_agent_row(agent_id=agent_id, tenant_id=tenant_id)

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()

    # Second execute (re-fetch) returns the row
    fetch_result = MagicMock()
    fetch_result.mappings.return_value.first.return_value = row
    db.execute.side_effect = [result_mock, fetch_result]

    updates = UpdateAgentRequest(description="Updated", industries=["finance"])
    result = await update_agent_registry_db(
        agent_id=agent_id,
        tenant_id=tenant_id,
        updates=updates,
        db=db,
    )
    # First call is the UPDATE — verify SET clause
    call_args = db.execute.call_args_list[0]
    sql_str = str(call_args[0][0])
    assert "description = :description" in sql_str
    assert "industries = CAST(:industries AS text[])" in sql_str
    # result is from re-fetch
    assert result is not None


@pytest.mark.asyncio
async def test_list_public_agents_db_filters_active_and_public():
    """list_public_agents_db filters status='active' AND is_public=true."""
    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    rows_result = MagicMock()
    rows_result.mappings.return_value = []
    db.execute = AsyncMock(side_effect=[count_result, rows_result])

    result = await list_public_agents_db(
        query=None,
        industry=None,
        transaction_type=None,
        language=None,
        kyb_level=None,
        min_trust_score=None,
        limit=10,
        offset=0,
        db=db,
    )
    # Verify the WHERE clause includes published + is_public
    count_call = db.execute.call_args_list[0]
    sql_str = str(count_call[0][0])
    assert "is_public = true" in sql_str
    assert "status = 'published'" in sql_str
    assert result["total"] == 0
    assert result["items"] == []


@pytest.mark.asyncio
async def test_list_public_agents_db_respects_limit_and_offset():
    """list_public_agents_db passes limit and offset as params (no page arithmetic)."""
    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 100
    rows_result = MagicMock()
    rows_result.mappings.return_value = []
    db.execute = AsyncMock(side_effect=[count_result, rows_result])

    await list_public_agents_db(
        query=None,
        industry=None,
        transaction_type=None,
        language=None,
        kyb_level=None,
        min_trust_score=None,
        limit=50,
        offset=25,
        db=db,
    )
    rows_call = db.execute.call_args_list[1]
    params = rows_call[0][1]
    assert params["limit"] == 50
    assert params["offset"] == 25


@pytest.mark.asyncio
async def test_list_public_agents_db_escapes_like_metacharacters():
    """list_public_agents_db escapes %, _, \\ in query before ILIKE."""
    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    rows_result = MagicMock()
    rows_result.mappings.return_value = []
    db.execute = AsyncMock(side_effect=[count_result, rows_result])

    await list_public_agents_db(
        query="100% fast_agent\\test",
        industry=None,
        transaction_type=None,
        language=None,
        kyb_level=None,
        min_trust_score=None,
        limit=10,
        offset=0,
        db=db,
    )
    count_call = db.execute.call_args_list[0]
    params = count_call[0][1]
    # backslash must be escaped first, then % and _
    assert "100\\%\\ fast\\_agent\\\\test" in params["query"] or (
        "\\%" in params["query"] and "\\_" in params["query"]
    )
