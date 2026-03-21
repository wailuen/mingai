"""
ATA-025: Unit tests for _validate_and_store_credentials().

Tier 1: Fast, isolated. Uses AsyncMock for DB and mock vault clients.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, call
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Import the helper under test
# ---------------------------------------------------------------------------

from app.modules.agents.routes import _validate_and_store_credentials


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db() -> AsyncMock:
    """Return an AsyncMock that simulates a minimal AsyncSession."""
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


def _make_vault() -> MagicMock:
    """Return a MagicMock vault client with store_secret tracked."""
    vault = MagicMock()
    vault.store_secret = MagicMock(return_value="local://someref")
    return vault


_TENANT_ID = "aaaabbbb-cccc-dddd-eeee-000011112222"
_AGENT_ID = "11112222-3333-4444-5555-666677778888"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_mode_none_returns_none_no_vault():
    """auth_mode='none' → returns None; vault is never touched."""
    vault = _make_vault()
    db = _make_db()

    result = await _validate_and_store_credentials(
        tenant_id=_TENANT_ID,
        agent_id=_AGENT_ID,
        auth_mode="none",
        required_credentials=[],
        provided_credentials=None,
        vault_client=vault,
        db=db,
    )

    assert result is None
    vault.store_secret.assert_not_called()
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_auth_mode_empty_string_returns_none():
    """Empty auth_mode string is treated as 'none'."""
    vault = _make_vault()
    db = _make_db()

    result = await _validate_and_store_credentials(
        tenant_id=_TENANT_ID,
        agent_id=_AGENT_ID,
        auth_mode="",
        required_credentials=[],
        provided_credentials=None,
        vault_client=vault,
        db=db,
    )

    assert result is None
    vault.store_secret.assert_not_called()


@pytest.mark.asyncio
async def test_platform_credentials_raises_422():
    """auth_mode='platform_credentials' raises HTTPException 422 with 'not yet available'."""
    vault = _make_vault()
    db = _make_db()

    with pytest.raises(HTTPException) as exc_info:
        await _validate_and_store_credentials(
            tenant_id=_TENANT_ID,
            agent_id=_AGENT_ID,
            auth_mode="platform_credentials",
            required_credentials=[],
            provided_credentials=None,
            vault_client=vault,
            db=db,
        )

    assert exc_info.value.status_code == 422
    assert "not yet available" in exc_info.value.detail
    vault.store_secret.assert_not_called()


@pytest.mark.asyncio
async def test_tenant_credentials_missing_required_key_raises_422():
    """Missing required credential key raises 422 with sorted key names in detail."""
    vault = _make_vault()
    db = _make_db()

    required_credentials = [
        {"key": "api_key", "required": True},
        {"key": "secret_token", "required": True},
    ]

    with pytest.raises(HTTPException) as exc_info:
        await _validate_and_store_credentials(
            tenant_id=_TENANT_ID,
            agent_id=_AGENT_ID,
            auth_mode="tenant_credentials",
            required_credentials=required_credentials,
            provided_credentials={"api_key": "my-key"},  # missing secret_token
            vault_client=vault,
            db=db,
        )

    assert exc_info.value.status_code == 422
    assert "secret_token" in exc_info.value.detail
    # Keys must be sorted in the detail message
    detail = exc_info.value.detail
    assert "'secret_token'" in detail


@pytest.mark.asyncio
async def test_tenant_credentials_sorted_missing_keys():
    """Missing keys list in 422 detail is sorted alphabetically."""
    vault = _make_vault()
    db = _make_db()

    required_credentials = [
        {"key": "zebra_key", "required": True},
        {"key": "alpha_key", "required": True},
        {"key": "middle_key", "required": True},
    ]

    with pytest.raises(HTTPException) as exc_info:
        await _validate_and_store_credentials(
            tenant_id=_TENANT_ID,
            agent_id=_AGENT_ID,
            auth_mode="tenant_credentials",
            required_credentials=required_credentials,
            provided_credentials={},
            vault_client=vault,
            db=db,
        )

    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    # The missing list must be ['alpha_key', 'middle_key', 'zebra_key'] (sorted)
    assert detail.index("alpha_key") < detail.index("middle_key") < detail.index("zebra_key")


@pytest.mark.asyncio
async def test_tenant_credentials_all_provided_calls_vault_for_each_key():
    """With all required keys provided, vault.store_secret is called for each key."""
    vault = _make_vault()
    db = _make_db()

    required_credentials = [
        {"key": "api_key", "required": True},
        {"key": "region", "required": False},
    ]
    provided = {"api_key": "my-key", "region": "us-east-1"}

    result = await _validate_and_store_credentials(
        tenant_id=_TENANT_ID,
        agent_id=_AGENT_ID,
        auth_mode="tenant_credentials",
        required_credentials=required_credentials,
        provided_credentials=provided,
        vault_client=vault,
        db=db,
    )

    expected_prefix = f"{_TENANT_ID}/agents/{_AGENT_ID}"
    assert result == expected_prefix

    # vault.store_secret called once per provided key
    assert vault.store_secret.call_count == 2
    called_paths = {c.args[0] for c in vault.store_secret.call_args_list}
    assert f"{expected_prefix}/api_key" in called_paths
    assert f"{expected_prefix}/region" in called_paths

    # DB execute called to update credentials_vault_path
    db.execute.assert_called_once()
    call_args = db.execute.call_args
    # First arg is the SQL text object; check params contain the path and agent id
    params = call_args.args[1]
    assert params["path"] == expected_prefix
    assert params["id"] == _AGENT_ID
    assert params["tenant_id"] == _TENANT_ID


@pytest.mark.asyncio
async def test_no_required_credentials_empty_provided_succeeds():
    """Empty required_credentials list succeeds even with empty provided_credentials."""
    vault = _make_vault()
    db = _make_db()

    result = await _validate_and_store_credentials(
        tenant_id=_TENANT_ID,
        agent_id=_AGENT_ID,
        auth_mode="tenant_credentials",
        required_credentials=[],
        provided_credentials={},
        vault_client=vault,
        db=db,
    )

    # No keys to store — vault not called, but path is still returned
    vault.store_secret.assert_not_called()
    # DB execute still called (to set vault path)
    db.execute.assert_called_once()
    assert result == f"{_TENANT_ID}/agents/{_AGENT_ID}"


@pytest.mark.asyncio
async def test_vault_client_none_succeeds_gracefully():
    """vault_client=None succeeds without crash (graceful when vault not configured)."""
    db = _make_db()

    result = await _validate_and_store_credentials(
        tenant_id=_TENANT_ID,
        agent_id=_AGENT_ID,
        auth_mode="tenant_credentials",
        required_credentials=[{"key": "api_key", "required": True}],
        provided_credentials={"api_key": "my-key"},
        vault_client=None,
        db=db,
    )

    expected_prefix = f"{_TENANT_ID}/agents/{_AGENT_ID}"
    assert result == expected_prefix
    # DB execute still called to persist vault_path_prefix
    db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Credential key name validation — path traversal regression tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_traversal_key_raises_422():
    """
    Credential key name '../etc/passwd' must be rejected with 422.
    Regression: _validate_and_store_credentials blocks path traversal via
    _VALID_CRED_KEY_RE before vault path construction.
    """
    db = _make_db()
    vault = _make_vault()

    with pytest.raises(HTTPException) as exc_info:
        await _validate_and_store_credentials(
            tenant_id=_TENANT_ID,
            agent_id=_AGENT_ID,
            auth_mode="tenant_credentials",
            required_credentials=[{"key": "api_key", "required": True}],
            provided_credentials={
                "../etc/passwd": "malicious",
                "api_key": "valid",
            },
            vault_client=vault,
            db=db,
        )

    assert exc_info.value.status_code == 422
    assert "../etc/passwd" in exc_info.value.detail


@pytest.mark.asyncio
async def test_slash_in_key_raises_422():
    """Credential key with slash (path separator) raises 422."""
    db = _make_db()
    vault = _make_vault()

    with pytest.raises(HTTPException) as exc_info:
        await _validate_and_store_credentials(
            tenant_id=_TENANT_ID,
            agent_id=_AGENT_ID,
            auth_mode="tenant_credentials",
            required_credentials=[{"key": "api_key", "required": True}],
            provided_credentials={"api/key": "v"},
            vault_client=vault,
            db=db,
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_dot_in_key_raises_422():
    """Credential key with dot (e.g., 'api.key') raises 422."""
    db = _make_db()
    vault = _make_vault()

    with pytest.raises(HTTPException) as exc_info:
        await _validate_and_store_credentials(
            tenant_id=_TENANT_ID,
            agent_id=_AGENT_ID,
            auth_mode="tenant_credentials",
            required_credentials=[{"key": "api_key", "required": True}],
            provided_credentials={"api.key": "v"},
            vault_client=vault,
            db=db,
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_valid_key_names_pass_validation():
    """Valid key names (letters, digits, underscores) are accepted."""
    db = _make_db()
    vault = _make_vault()

    # Should NOT raise — these names are all valid
    await _validate_and_store_credentials(
        tenant_id=_TENANT_ID,
        agent_id=_AGENT_ID,
        auth_mode="tenant_credentials",
        required_credentials=[{"key": "api_key_1", "required": True}],
        provided_credentials={"api_key_1": "value", "_private": "x", "CamelCase": "y"},
        vault_client=vault,
        db=db,
    )

    vault.store_secret.assert_called()
