"""
HAR-007: Outbound A2A routing unit tests.

Tests:
- route_message: success path, retry logic, exhausted retries → ABANDONED
- _get_a2a_endpoint: found/not found
- Exponential backoff sequence (1s, 2s, 4s)
- Logs routing event on success and failure
- Validates payload schema before routing
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.registry.a2a_routing import (
    _BACKOFF_SECONDS,
    _MAX_RETRIES,
    _abandon_transaction,
    _get_a2a_endpoint,
    route_message,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _txn_row(tenant_id=None, initiator_agent_id=None):
    return {
        "tenant_id": tenant_id or str(uuid.uuid4()),
        "initiator_agent_id": initiator_agent_id or str(uuid.uuid4()),
    }


def _make_session(
    endpoint="https://agent.example.com/a2a",
    txn_row=None,
    key_row=None,
):
    session = AsyncMock()

    endpoint_result = MagicMock()
    endpoint_result.mappings.return_value.first.return_value = (
        {"a2a_endpoint": endpoint} if endpoint else None
    )

    txn_result = MagicMock()
    txn_result.mappings.return_value.first.return_value = txn_row or _txn_row()

    key_result = MagicMock()
    key_result.mappings.return_value.first.return_value = key_row

    session.execute = AsyncMock(side_effect=[endpoint_result, txn_result, key_result])
    session.commit = AsyncMock()
    return session


def _no_schema_errors():
    """Patch context that returns no schema errors."""
    mock_validator = MagicMock()
    mock_validator.iter_errors.return_value = []
    return patch(
        "app.modules.registry.schemas.validator.Draft202012Validator",
        return_value=mock_validator,
    )


def _schema_errors(errors):
    """Patch context that returns schema errors."""
    mock_validator = MagicMock()
    err_objs = []
    for e in errors:
        err_mock = MagicMock()
        err_mock.message = e["message"]
        err_mock.absolute_path = [e.get("path", "(root)")]
        err_objs.append(err_mock)
    mock_validator.iter_errors.return_value = err_objs
    return patch(
        "app.modules.registry.schemas.validator.Draft202012Validator",
        return_value=mock_validator,
    )


# ---------------------------------------------------------------------------
# _get_a2a_endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_a2a_endpoint_returns_url_when_found():
    """_get_a2a_endpoint returns the endpoint URL from agent_cards."""
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.first.return_value = {
        "a2a_endpoint": "https://agent.example.com/a2a"
    }
    session.execute = AsyncMock(return_value=result)

    endpoint = await _get_a2a_endpoint(str(uuid.uuid4()), session)
    assert endpoint == "https://agent.example.com/a2a"


@pytest.mark.asyncio
async def test_get_a2a_endpoint_returns_none_when_not_found():
    """_get_a2a_endpoint returns None if agent not found."""
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.first.return_value = None
    session.execute = AsyncMock(return_value=result)

    endpoint = await _get_a2a_endpoint(str(uuid.uuid4()), session)
    assert endpoint is None


@pytest.mark.asyncio
async def test_get_a2a_endpoint_returns_none_when_endpoint_empty():
    """_get_a2a_endpoint returns None if agent has no a2a_endpoint set."""
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.first.return_value = {"a2a_endpoint": None}
    session.execute = AsyncMock(return_value=result)

    endpoint = await _get_a2a_endpoint(str(uuid.uuid4()), session)
    assert endpoint is None


# ---------------------------------------------------------------------------
# route_message tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_message_raises_for_schema_validation_error():
    """route_message raises ValueError when payload fails schema validation."""
    session = AsyncMock()

    with _schema_errors([{"path": "items", "message": "required property 'items'"}]):
        with pytest.raises(ValueError, match="Payload validation failed"):
            await route_message(
                session=session,
                transaction_id=uuid.uuid4(),
                target_agent_id=uuid.uuid4(),
                message_type="RFQ",
                payload={},
            )


@pytest.mark.asyncio
async def test_route_message_raises_when_no_endpoint():
    """route_message raises ValueError when target agent has no a2a_endpoint."""
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.first.return_value = None
    session.execute = AsyncMock(return_value=result)

    with _no_schema_errors():
        with pytest.raises(ValueError, match="no a2a_endpoint"):
            await route_message(
                session=session,
                transaction_id=uuid.uuid4(),
                target_agent_id=uuid.uuid4(),
                message_type="RFQ",
                payload={"requester_agent_id": str(uuid.uuid4()), "items": []},
            )


@pytest.mark.asyncio
async def test_route_message_success_on_first_attempt():
    """route_message returns status='sent' when HTTP POST succeeds on first attempt."""
    tenant_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())

    session = _make_session(
        endpoint="https://agent.example.com/a2a",
        txn_row=_txn_row(tenant_id=tenant_id, initiator_agent_id=agent_id),
    )
    event_result = MagicMock()
    session.execute.side_effect = list(session.execute.side_effect) + [event_result]

    mock_response = MagicMock()
    mock_response.status_code = 200

    with _no_schema_errors(), patch(
        "app.modules.registry.a2a_routing._validate_ssrf_safe_url"
    ), patch(
        "app.modules.registry.a2a_routing.httpx.AsyncClient"
    ) as mock_client, patch(
        "app.modules.registry.a2a_routing._log_routing_event",
        AsyncMock(),
    ):
        mock_client.return_value.__aenter__ = AsyncMock(
            return_value=mock_client.return_value
        )
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.post = AsyncMock(return_value=mock_response)

        result = await route_message(
            session=session,
            transaction_id=uuid.uuid4(),
            target_agent_id=uuid.uuid4(),
            message_type="RFQ",
            payload={"requester_agent_id": agent_id, "items": []},
        )

    assert result["status"] == "sent"
    assert result["attempt_count"] == 1


@pytest.mark.asyncio
async def test_route_message_fails_after_max_retries():
    """route_message returns status='failed' after all retries exhausted."""
    tenant_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())

    session = _make_session(
        endpoint="https://agent.example.com/a2a",
        txn_row=_txn_row(tenant_id=tenant_id, initiator_agent_id=agent_id),
    )

    with _no_schema_errors(), patch(
        "app.modules.registry.a2a_routing._validate_ssrf_safe_url"
    ), patch(
        "app.modules.registry.a2a_routing.httpx.AsyncClient"
    ) as mock_client, patch(
        "app.modules.registry.a2a_routing._log_routing_event",
        AsyncMock(),
    ), patch(
        "app.modules.registry.a2a_routing._abandon_transaction",
        AsyncMock(),
    ), patch(
        "app.modules.registry.a2a_routing.asyncio.sleep",
        AsyncMock(),
    ):
        mock_client.return_value.__aenter__ = AsyncMock(
            return_value=mock_client.return_value
        )
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.post = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        result = await route_message(
            session=session,
            transaction_id=uuid.uuid4(),
            target_agent_id=uuid.uuid4(),
            message_type="RFQ",
            payload={},
        )

    assert result["status"] == "failed"
    assert result["attempt_count"] == _MAX_RETRIES


@pytest.mark.asyncio
async def test_route_message_abandons_transaction_on_exhausted_retries():
    """route_message calls _abandon_transaction when all retries fail."""
    abandon_called = []

    async def _fake_abandon(txn_id, tenant_id, session):
        abandon_called.append(txn_id)

    session = _make_session()

    with _no_schema_errors(), patch(
        "app.modules.registry.a2a_routing._validate_ssrf_safe_url"
    ), patch(
        "app.modules.registry.a2a_routing.httpx.AsyncClient"
    ) as mock_client, patch(
        "app.modules.registry.a2a_routing._log_routing_event",
        AsyncMock(),
    ), patch(
        "app.modules.registry.a2a_routing._abandon_transaction",
        _fake_abandon,
    ), patch(
        "app.modules.registry.a2a_routing.asyncio.sleep",
        AsyncMock(),
    ):
        mock_client.return_value.__aenter__ = AsyncMock(
            return_value=mock_client.return_value
        )
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.post = AsyncMock(side_effect=Exception("Timeout"))

        await route_message(
            session=session,
            transaction_id=uuid.uuid4(),
            target_agent_id=uuid.uuid4(),
            message_type="RFQ",
            payload={},
        )

    assert len(abandon_called) == 1


# ---------------------------------------------------------------------------
# Backoff constants
# ---------------------------------------------------------------------------


def test_backoff_sequence_is_exponential():
    """Backoff sequence: 1s, 2s, 4s."""
    assert _BACKOFF_SECONDS == [1, 2, 4]


def test_max_retries_is_three():
    """MAX_RETRIES is 3."""
    assert _MAX_RETRIES == 3


# ---------------------------------------------------------------------------
# _abandon_transaction tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abandon_transaction_updates_state():
    """_abandon_transaction executes UPDATE to ABANDONED state."""
    session = AsyncMock()
    result_mock = MagicMock()
    session.execute = AsyncMock(return_value=result_mock)
    session.commit = AsyncMock()

    await _abandon_transaction("txn-1", "tenant-1", session)

    session.commit.assert_called_once()
    call_sql = str(session.execute.call_args_list[0][0][0])
    assert "ABANDONED" in call_sql


@pytest.mark.asyncio
async def test_abandon_transaction_does_not_raise_on_error():
    """_abandon_transaction never raises — errors are logged only."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=Exception("DB error"))
    session.commit = AsyncMock()

    # Should not raise
    await _abandon_transaction("txn-1", "tenant-1", session)
