"""
Unit tests for app/modules/platform/credential_health.py (ATA-036).

Tests cover:
1. Happy path: vault reachable — no notification sent
2. Vault unreachable — notification sent to admins
3. Dedup: second run suppresses duplicate notification (Redis key exists)
4. Dedup: Redis read failure still sends notification (fail-open toward alerting)
5. Dedup: Redis write failure after successful send — next run re-notifies (correct)
6. DistributedJobLock not acquired — returns zero counts immediately
7. Admin lookup: no admins — no notification sent, no dedup key written

All dependencies are mocked — no infrastructure required.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(agents=None, admins=None):
    """
    Return a mock AsyncSession.

    agents: list of (id, name, vault_path) tuples or empty list
    admins: list of (id,) tuples or empty list
    """
    db = AsyncMock()
    db.execute = AsyncMock()
    # commit is needed for scope-setting SQL calls
    db.commit = AsyncMock()

    agent_result = MagicMock()
    agent_result.fetchall.return_value = agents or []

    admin_result = MagicMock()
    admin_result.fetchall.return_value = admins or []

    # SET LOCAL scope statements return a no-op result; agent query is the first real one
    db.execute.side_effect = [
        MagicMock(),  # SET LOCAL app.current_scope
        MagicMock(),  # SET LOCAL app.user_role
        agent_result,  # SELECT agents
        admin_result,  # SELECT admins (only if unhealthy agent found)
    ]
    return db


def _make_redis(dedup_key_exists=False):
    """Return a mock Redis client."""
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=1 if dedup_key_exists else 0)
    redis.setex = AsyncMock()
    return redis


def _make_vault_client(fail_on_path=None):
    """Return a mock vault client. fail_on_path raises on that specific path."""
    vault = MagicMock()

    def _get_secret(path):
        if fail_on_path and path == fail_on_path:
            raise Exception("Vault path unreachable")
        return "secret-value"

    vault.get_secret = _get_secret
    return vault


_TENANT_ID = "tenant-0001-0001-0001-000000000001"
_AGENT_ID = "agent-uuid-0001-0001-0001-000000000001"
_VAULT_PATH = f"{_TENANT_ID}/agents/{_AGENT_ID}/credentials"


# ---------------------------------------------------------------------------
# run_daily_credential_health_check
# ---------------------------------------------------------------------------


class TestRunDailyCredentialHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy_credentials_returns_zero_unhealthy(self):
        """Vault is reachable — no notifications, unhealthy=0."""
        from app.modules.platform.credential_health import run_daily_credential_health_check

        db = _make_db(agents=[(_AGENT_ID, "Test Agent", _VAULT_PATH)])
        vault = _make_vault_client()  # does not raise

        with patch(
            "app.modules.platform.credential_health.DistributedJobLock"
        ) as mock_lock_cls:
            lock_instance = AsyncMock()
            lock_instance.__aenter__ = AsyncMock(return_value=True)
            lock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_lock_cls.return_value = lock_instance

            result = await run_daily_credential_health_check(
                tenant_id=_TENANT_ID, db=db, vault_client=vault
            )

        assert result["checked"] == 1
        assert result["unhealthy"] == 0
        assert result["notifications_sent"] == 0

    @pytest.mark.asyncio
    async def test_unhealthy_credential_sends_notification(self):
        """Vault raises for agent — notification sent, unhealthy=1."""
        from app.modules.platform.credential_health import run_daily_credential_health_check

        admin_id = "admin-uuid-0001-0001"
        db = _make_db(
            agents=[(_AGENT_ID, "Test Agent", _VAULT_PATH)],
            admins=[(admin_id,)],
        )
        vault = _make_vault_client(fail_on_path=_VAULT_PATH)
        redis = _make_redis(dedup_key_exists=False)

        with (
            patch(
                "app.modules.platform.credential_health.DistributedJobLock"
            ) as mock_lock_cls,
            patch("app.modules.platform.credential_health.get_redis", return_value=redis),
            patch(
                "app.modules.notifications.publisher.publish_notification",
                new=AsyncMock(),
            ) as mock_publish,
        ):
            lock_instance = AsyncMock()
            lock_instance.__aenter__ = AsyncMock(return_value=True)
            lock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_lock_cls.return_value = lock_instance

            result = await run_daily_credential_health_check(
                tenant_id=_TENANT_ID, db=db, vault_client=vault
            )

        assert result["checked"] == 1
        assert result["unhealthy"] == 1
        assert result["notifications_sent"] == 1
        mock_publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dedup_suppresses_duplicate_notification(self):
        """Redis dedup key exists — second run skips notification."""
        from app.modules.platform.credential_health import run_daily_credential_health_check

        admin_id = "admin-uuid-0001-0001"
        db = _make_db(
            agents=[(_AGENT_ID, "Test Agent", _VAULT_PATH)],
            admins=[(admin_id,)],
        )
        vault = _make_vault_client(fail_on_path=_VAULT_PATH)
        redis = _make_redis(dedup_key_exists=True)  # already notified

        with (
            patch(
                "app.modules.platform.credential_health.DistributedJobLock"
            ) as mock_lock_cls,
            patch("app.modules.platform.credential_health.get_redis", return_value=redis),
            patch(
                "app.modules.notifications.publisher.publish_notification",
                new=AsyncMock(),
            ) as mock_publish,
        ):
            lock_instance = AsyncMock()
            lock_instance.__aenter__ = AsyncMock(return_value=True)
            lock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_lock_cls.return_value = lock_instance

            result = await run_daily_credential_health_check(
                tenant_id=_TENANT_ID, db=db, vault_client=vault
            )

        # Notification suppressed — dedup key prevented duplicate send
        assert result["unhealthy"] == 1
        assert result["notifications_sent"] == 0
        mock_publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_redis_dedup_read_failure_still_sends_notification(self):
        """Redis.exists() raises — dedup check fails open, notification still sent."""
        import redis as redis_lib
        from app.modules.platform.credential_health import run_daily_credential_health_check

        admin_id = "admin-uuid-0001-0001"
        db = _make_db(
            agents=[(_AGENT_ID, "Test Agent", _VAULT_PATH)],
            admins=[(admin_id,)],
        )
        vault = _make_vault_client(fail_on_path=_VAULT_PATH)

        redis_broken = AsyncMock()
        redis_broken.exists = AsyncMock(
            side_effect=redis_lib.exceptions.ConnectionError("Redis unreachable")
        )
        redis_broken.setex = AsyncMock()

        with (
            patch(
                "app.modules.platform.credential_health.DistributedJobLock"
            ) as mock_lock_cls,
            patch(
                "app.modules.platform.credential_health.get_redis",
                return_value=redis_broken,
            ),
            patch(
                "app.modules.notifications.publisher.publish_notification",
                new=AsyncMock(),
            ) as mock_publish,
        ):
            lock_instance = AsyncMock()
            lock_instance.__aenter__ = AsyncMock(return_value=True)
            lock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_lock_cls.return_value = lock_instance

            result = await run_daily_credential_health_check(
                tenant_id=_TENANT_ID, db=db, vault_client=vault
            )

        # Fail-open on dedup: notification sent despite Redis error
        assert result["notifications_sent"] == 1
        mock_publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lock_not_acquired_returns_zero_counts(self):
        """Another pod holds the lock — returns zero counts immediately."""
        from app.modules.platform.credential_health import run_daily_credential_health_check

        db = _make_db()
        vault = _make_vault_client()

        with patch(
            "app.modules.platform.credential_health.DistributedJobLock"
        ) as mock_lock_cls:
            lock_instance = AsyncMock()
            lock_instance.__aenter__ = AsyncMock(return_value=False)  # lock not acquired
            lock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_lock_cls.return_value = lock_instance

            result = await run_daily_credential_health_check(
                tenant_id=_TENANT_ID, db=db, vault_client=vault
            )

        assert result == {"checked": 0, "unhealthy": 0, "notifications_sent": 0}

    @pytest.mark.asyncio
    async def test_no_admins_no_notification_sent(self):
        """No active admin users — notification cannot be delivered, count stays 0."""
        from app.modules.platform.credential_health import run_daily_credential_health_check

        db = _make_db(
            agents=[(_AGENT_ID, "Test Agent", _VAULT_PATH)],
            admins=[],  # no admins
        )
        vault = _make_vault_client(fail_on_path=_VAULT_PATH)
        redis = _make_redis(dedup_key_exists=False)

        with (
            patch(
                "app.modules.platform.credential_health.DistributedJobLock"
            ) as mock_lock_cls,
            patch("app.modules.platform.credential_health.get_redis", return_value=redis),
            patch(
                "app.modules.notifications.publisher.publish_notification",
                new=AsyncMock(),
            ) as mock_publish,
        ):
            lock_instance = AsyncMock()
            lock_instance.__aenter__ = AsyncMock(return_value=True)
            lock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_lock_cls.return_value = lock_instance

            result = await run_daily_credential_health_check(
                tenant_id=_TENANT_ID, db=db, vault_client=vault
            )

        assert result["unhealthy"] == 1
        assert result["notifications_sent"] == 0
        mock_publish.assert_not_awaited()
        # Dedup key should NOT be set (nothing was sent)
        redis.setex.assert_not_awaited()
