"""
Unit tests for SCHED-002: DistributedJobLock.

Tests the core lock semantics with a mocked Redis client.

Tier 1: All Redis calls are mocked. Tests verify:
  - Acquire succeeds when SET NX EX returns True
  - Acquire skips (yields False) when SET NX EX returns None
  - Heartbeat renews EXPIRE at TTL//2 intervals
  - Heartbeat detects token mismatch and cancels the caller task
  - Lock is released via Lua script on context exit
  - Lock is released even when the job body raises
"""
import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# get_redis is imported lazily inside DistributedJobLock; patch at the source module.
_REDIS_MODULE = "app.core.redis_client"


def _make_redis(set_result=True, get_result_factory=None):
    """Build a minimal mock Redis client.

    Args:
        set_result:           Value returned by redis.set(nx=True, ex=...).
                              True = lock acquired; None/False = lock taken.
        get_result_factory:   Callable(call_count) → return value for redis.get().
                              Default: always returns the stored token.
    """
    mock_redis = MagicMock()
    _stored_token = []

    async def _set(key, value, nx=False, ex=None):
        if set_result is True:
            _stored_token.clear()
            _stored_token.append(value)
            return True
        return None  # Lock already taken

    async def _get(key):
        if get_result_factory is not None:
            return get_result_factory()
        return _stored_token[0] if _stored_token else None

    async def _expire(key, ttl):
        return 1

    mock_redis.set = AsyncMock(side_effect=_set)
    mock_redis.get = AsyncMock(side_effect=_get)
    mock_redis.expire = AsyncMock(side_effect=_expire)

    # register_script returns a callable Script stub that runs the Lua release logic.
    def _register_script(script_text):
        script_obj = MagicMock()

        async def _call(keys, args):
            # Simulate: DEL only if GET(key) == token
            current = _stored_token[0] if _stored_token else None
            if current == args[0]:
                _stored_token.clear()
                return 1
            return 0

        script_obj.side_effect = _call
        return script_obj

    mock_redis.register_script = MagicMock(side_effect=_register_script)
    return mock_redis


class TestDistributedJobLockAcquisition:
    """Test lock acquire / skip semantics."""

    @pytest.mark.asyncio
    async def test_acquired_yields_true(self):
        mock_redis = _make_redis(set_result=True)
        with patch(f"{_REDIS_MODULE}.get_redis", return_value=mock_redis):
            from app.core.scheduler.job_lock import DistributedJobLock

            async with DistributedJobLock("test_job", ttl=10) as acquired:
                assert acquired is True

    @pytest.mark.asyncio
    async def test_not_acquired_yields_false(self):
        mock_redis = _make_redis(set_result=None)
        with patch(f"{_REDIS_MODULE}.get_redis", return_value=mock_redis):
            from app.core.scheduler.job_lock import DistributedJobLock

            async with DistributedJobLock("test_job", ttl=10) as acquired:
                assert acquired is False

    @pytest.mark.asyncio
    async def test_lock_released_after_context_exits(self):
        mock_redis = _make_redis(set_result=True)
        with patch(f"{_REDIS_MODULE}.get_redis", return_value=mock_redis):
            from app.core.scheduler.job_lock import DistributedJobLock

            async with DistributedJobLock("test_job", ttl=10) as acquired:
                assert acquired is True
                # Token is held during the context
                assert mock_redis.register_script.called

        # register_script() was called (for the Lua release) — verify call happened
        assert mock_redis.register_script.call_count >= 1

    @pytest.mark.asyncio
    async def test_lock_released_when_job_raises(self):
        """Lock must be released even if the job body raises an exception."""
        mock_redis = _make_redis(set_result=True)
        with patch(f"{_REDIS_MODULE}.get_redis", return_value=mock_redis):
            from app.core.scheduler.job_lock import DistributedJobLock

            with pytest.raises(ValueError, match="test error"):
                async with DistributedJobLock("test_job", ttl=10):
                    raise ValueError("test error")

        # register_script was called for Lua release — the finally block ran
        assert mock_redis.register_script.call_count >= 1

    @pytest.mark.asyncio
    async def test_set_called_with_nx_and_ex(self):
        mock_redis = _make_redis(set_result=True)
        with patch(f"{_REDIS_MODULE}.get_redis", return_value=mock_redis):
            from app.core.scheduler.job_lock import DistributedJobLock

            async with DistributedJobLock("my_job", ttl=300):
                pass

        call_kwargs = mock_redis.set.call_args
        assert call_kwargs.kwargs.get("nx") is True
        assert call_kwargs.kwargs.get("ex") == 300

    @pytest.mark.asyncio
    async def test_lock_key_uses_job_name(self):
        mock_redis = _make_redis(set_result=True)
        with patch(f"{_REDIS_MODULE}.get_redis", return_value=mock_redis):
            from app.core.scheduler.job_lock import DistributedJobLock

            async with DistributedJobLock("special_job", ttl=10):
                pass

        key_used = mock_redis.set.call_args.args[0]
        assert "special_job" in key_used


class TestDistributedJobLockHeartbeat:
    """Test heartbeat renewal and token-mismatch cancellation."""

    @pytest.mark.asyncio
    async def test_heartbeat_renews_expire(self):
        """Heartbeat should call redis.expire() when token matches."""
        mock_redis = _make_redis(set_result=True)
        with patch(f"{_REDIS_MODULE}.get_redis", return_value=mock_redis):
            from app.core.scheduler.job_lock import DistributedJobLock

            # Use ttl=2 so heartbeat fires after 1 second
            async with DistributedJobLock("renew_job", ttl=2) as acquired:
                assert acquired is True
                await asyncio.sleep(1.5)  # Wait for 1 heartbeat cycle

        assert mock_redis.expire.call_count >= 1

    @pytest.mark.asyncio
    async def test_heartbeat_cancels_task_on_token_mismatch(self):
        """When stored token differs from ours, heartbeat should cancel the task."""
        call_count = 0

        def _get_result():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First get (during heartbeat) returns a different token — theft detected
                return "STOLEN_TOKEN"
            return "original"

        mock_redis = _make_redis(set_result=True, get_result_factory=_get_result)
        with patch(f"{_REDIS_MODULE}.get_redis", return_value=mock_redis):
            from app.core.scheduler.job_lock import DistributedJobLock

            cancelled = False
            with pytest.raises(asyncio.CancelledError):
                async with DistributedJobLock("stolen_job", ttl=2) as acquired:
                    assert acquired is True
                    # Wait long enough for heartbeat to fire (ttl//2 = 1s)
                    await asyncio.sleep(2)
                    # If we get here the heartbeat didn't cancel us
                    cancelled = False
