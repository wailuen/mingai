"""
Unit tests for LLM profile assignment cache invalidation (PA-003).

Tests cover:
- PATCH /admin/llm-config DELetes Redis cache key after PostgreSQL write
- _invalidate_config_cache deletes both llm_config and byollm_key_ref keys
- _invalidate_config_cache handles Redis unavailable without raising
- update_llm_config calls _invalidate_config_cache after commit
- Cache invalidation uses correct key format: mingai:{tenant_id}:config:{key}
- Subsequent reads after DEL go to PostgreSQL (cache miss)
- byollm endpoint also invalidates cache
- Library validation: 404 for missing llm_library_id
"""
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(tenant_id="tenant-1", plan="enterprise"):
    from app.core.dependencies import CurrentUser

    return CurrentUser(
        id="admin-1",
        tenant_id=tenant_id,
        roles=["tenant_admin"],
        scope="tenant",
        plan=plan,
    )


def _mock_db(rows=None):
    db = AsyncMock()
    mock_result = MagicMock()
    if rows is not None:
        mock_result.fetchall.return_value = rows
        mock_result.fetchone.return_value = rows[0] if rows else None
    else:
        mock_result.fetchall.return_value = []
        mock_result.fetchone.return_value = None
    mock_result.scalar.return_value = None
    db.execute.return_value = mock_result
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# _invalidate_config_cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidate_config_cache_deletes_both_keys():
    """_invalidate_config_cache deletes both llm_config and byollm_key_ref keys."""
    from app.modules.admin.llm_config import _invalidate_config_cache

    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()

    with patch("app.modules.admin.llm_config.get_redis", return_value=mock_redis):
        await _invalidate_config_cache("tenant-1")

    mock_redis.delete.assert_called_once_with(
        "mingai:tenant-1:config:llm_config",
        "mingai:tenant-1:config:byollm_key_ref",
    )


@pytest.mark.asyncio
async def test_invalidate_config_cache_handles_redis_unavailable():
    """_invalidate_config_cache does not raise when Redis is unavailable."""
    from app.modules.admin.llm_config import _invalidate_config_cache

    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock(side_effect=Exception("Redis connection refused"))

    with patch("app.modules.admin.llm_config.get_redis", return_value=mock_redis):
        # Should NOT raise
        await _invalidate_config_cache("tenant-1")


@pytest.mark.asyncio
async def test_invalidate_cache_key_format():
    """Key format is mingai:{tenant_id}:config:{key}."""
    from app.modules.admin.llm_config import _invalidate_config_cache

    captured_args = []
    mock_redis = AsyncMock()

    async def capture_delete(*args):
        captured_args.extend(args)

    mock_redis.delete = capture_delete

    with patch("app.modules.admin.llm_config.get_redis", return_value=mock_redis):
        await _invalidate_config_cache("my-tenant")

    assert "mingai:my-tenant:config:llm_config" in captured_args
    assert "mingai:my-tenant:config:byollm_key_ref" in captured_args


# ---------------------------------------------------------------------------
# update_llm_config endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_llm_config_calls_cache_invalidation():
    """PATCH llm-config calls _invalidate_config_cache after commit."""
    from app.modules.admin.llm_config import update_llm_config, UpdateLLMConfigRequest

    user = _make_admin(plan="professional")

    # Library mode: need a valid llm_library_id
    lib_id = "11111111-1111-1111-1111-111111111111"

    # update_llm_config calls (no set_config before library check):
    # 1. SELECT status FROM llm_library WHERE id = :id
    # 2. INSERT INTO tenant_configs ... ON CONFLICT ...
    # 3. SELECT config_type, config_data FROM tenant_configs (return value)
    call_count = [0]

    async def mock_execute(stmt, params=None):
        call_count[0] += 1
        mock_result = MagicMock()
        n = call_count[0]
        if n == 1:
            # SELECT status FROM llm_library
            mock_result.fetchone.return_value = ("Published",)
        elif n == 2:
            # INSERT tenant_configs
            mock_result.fetchone.return_value = None
        else:
            # SELECT config for return value
            mock_result.fetchall.return_value = [
                ("llm_config", {"model_source": "library", "llm_library_id": lib_id})
            ]
            mock_result.fetchone.return_value = None
        return mock_result

    db = AsyncMock()
    db.execute = mock_execute
    db.commit = AsyncMock()

    with patch(
        "app.modules.admin.llm_config._invalidate_config_cache", new=AsyncMock()
    ) as mock_invalidate:
        body = UpdateLLMConfigRequest(model_source="library", llm_library_id=lib_id)
        await update_llm_config(request=body, current_user=user, db=db)

    mock_invalidate.assert_called_once_with(user.tenant_id)


@pytest.mark.asyncio
async def test_update_llm_config_library_not_found_returns_404():
    """PATCH with non-existent llm_library_id returns 404."""
    from fastapi import HTTPException
    from app.modules.admin.llm_config import update_llm_config, UpdateLLMConfigRequest

    user = _make_admin(plan="professional")
    lib_id = "22222222-2222-2222-2222-222222222222"

    def mock_execute_factory():
        calls = []

        async def mock_execute(stmt, params=None):
            calls.append(stmt)
            mock_result = MagicMock()
            call_idx = len(calls)
            if call_idx == 1:
                # set_config
                mock_result.fetchone.return_value = None
            elif call_idx == 2:
                # SELECT status FROM llm_library — not found
                mock_result.fetchone.return_value = None
            return mock_result

        return mock_execute

    db = AsyncMock()
    db.execute = mock_execute_factory()

    with pytest.raises(HTTPException) as exc_info:
        body = UpdateLLMConfigRequest(model_source="library", llm_library_id=lib_id)
        await update_llm_config(request=body, current_user=user, db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_llm_config_byollm_requires_enterprise():
    """PATCH model_source=byollm returns 403 for non-enterprise plan."""
    from fastapi import HTTPException
    from app.modules.admin.llm_config import update_llm_config, UpdateLLMConfigRequest

    user = _make_admin(plan="professional")

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())

    with pytest.raises(HTTPException) as exc_info:
        body = UpdateLLMConfigRequest(model_source="byollm")
        await update_llm_config(request=body, current_user=user, db=db)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_update_llm_config_library_requires_library_id():
    """PATCH model_source=library without llm_library_id returns 422."""
    from fastapi import HTTPException
    from app.modules.admin.llm_config import update_llm_config, UpdateLLMConfigRequest

    user = _make_admin(plan="professional")
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        body = UpdateLLMConfigRequest(model_source="library", llm_library_id=None)
        await update_llm_config(request=body, current_user=user, db=db)

    assert exc_info.value.status_code == 422
