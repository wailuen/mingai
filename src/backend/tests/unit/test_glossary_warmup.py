"""
INFRA-026: Glossary cache warm-up on startup - unit tests

Coverage target: 100%
Target count: 6 tests

Validates warm_up_glossary_cache():
- Zero active tenants: no error, logs warmup_complete
- Cache already warm (Redis EXISTS=1): skipped=1, warmed=0
- Cache cold (Redis EXISTS=0): queries DB, caches in Redis, warmed=1
- DB failure on individual tenant: logs warning, continues gracefully
- Zero glossary terms for a tenant: caches empty list, warmed=1
- Aliases as JSON string: correctly parsed to list
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGlossaryCacheWarmup:
    """INFRA-026: Glossary cache warm-up on startup."""

    @pytest.mark.asyncio
    async def test_zero_active_tenants(self):
        """With no active tenants, warm-up completes without error and logs warmup_complete."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session_ctx)

        with patch(
            "app.modules.glossary.warmup.async_session_factory", mock_factory
        ), patch("app.modules.glossary.warmup.get_redis") as mock_get_redis, patch(
            "app.modules.glossary.warmup.logger"
        ) as mock_logger:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis

            from app.modules.glossary.warmup import warm_up_glossary_cache

            await warm_up_glossary_cache()

            # Should log warmup_complete with warmed=0, skipped=0
            mock_logger.info.assert_any_call(
                "glossary_warmup_complete",
                total_tenants=0,
                warmed=0,
                skipped=0,
                already_cached=0,
                elapsed_ms=pytest.approx(0, abs=5000),
            )

    @pytest.mark.asyncio
    async def test_cache_already_warm_skips(self):
        """When Redis cache key already exists, tenant is skipped (already_cached=1)."""
        mock_session = AsyncMock()

        # First query: get active tenants -> one tenant
        mock_tenants_result = MagicMock()
        mock_tenants_result.fetchall.return_value = [("tenant-abc",)]
        mock_session.execute.return_value = mock_tenants_result

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session_ctx)

        with patch(
            "app.modules.glossary.warmup.async_session_factory", mock_factory
        ), patch("app.modules.glossary.warmup.get_redis") as mock_get_redis, patch(
            "app.modules.glossary.warmup.logger"
        ) as mock_logger:
            mock_redis = AsyncMock()
            # Cache key exists
            mock_redis.exists.return_value = 1
            mock_get_redis.return_value = mock_redis

            from app.modules.glossary.warmup import warm_up_glossary_cache

            await warm_up_glossary_cache()

            # Should NOT have called setex (no caching needed)
            mock_redis.setex.assert_not_called()

            # Should log warmup_complete with already_cached=1
            mock_logger.info.assert_any_call(
                "glossary_warmup_complete",
                total_tenants=1,
                warmed=0,
                skipped=0,
                already_cached=1,
                elapsed_ms=pytest.approx(0, abs=5000),
            )

    @pytest.mark.asyncio
    async def test_cache_cold_queries_db_and_caches(self):
        """When Redis cache is cold, queries DB for terms and caches them."""
        mock_session = AsyncMock()

        # First call: get active tenants
        mock_tenants_result = MagicMock()
        mock_tenants_result.fetchall.return_value = [("tenant-xyz",)]

        # Second call: get glossary terms for tenant
        mock_terms_result = MagicMock()
        mock_terms_result.fetchall.return_value = [
            ("API", "Application Programming Interface", ["REST"]),
            ("SDK", "Software Development Kit", []),
        ]

        mock_session.execute.side_effect = [mock_tenants_result, mock_terms_result]

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session_ctx)

        with patch(
            "app.modules.glossary.warmup.async_session_factory", mock_factory
        ), patch("app.modules.glossary.warmup.get_redis") as mock_get_redis, patch(
            "app.modules.glossary.warmup.logger"
        ) as mock_logger:
            mock_redis = AsyncMock()
            mock_redis.exists.return_value = 0
            mock_get_redis.return_value = mock_redis

            from app.modules.glossary.warmup import warm_up_glossary_cache

            await warm_up_glossary_cache()

            # Should have called setex with the cached terms
            mock_redis.setex.assert_called_once()
            call_args = mock_redis.setex.call_args
            assert call_args[0][0] == "mingai:tenant-xyz:glossary_terms"
            assert call_args[0][1] == 3600

            cached_data = json.loads(call_args[0][2])
            assert len(cached_data) == 2
            assert cached_data[0]["term"] == "API"
            assert cached_data[0]["full_form"] == "Application Programming Interface"
            assert cached_data[0]["aliases"] == ["REST"]
            assert cached_data[1]["term"] == "SDK"

            # Should log warmup_complete with warmed=1
            mock_logger.info.assert_any_call(
                "glossary_warmup_complete",
                total_tenants=1,
                warmed=1,
                skipped=0,
                already_cached=0,
                elapsed_ms=pytest.approx(0, abs=5000),
            )

    @pytest.mark.asyncio
    async def test_db_failure_logs_warning_and_continues(self):
        """When DB fails for a tenant, logs warning and continues gracefully."""
        mock_session = AsyncMock()

        # First call: get active tenants
        mock_tenants_result = MagicMock()
        mock_tenants_result.fetchall.return_value = [("tenant-fail",)]

        # Second call: DB error on glossary query
        mock_session.execute.side_effect = [
            mock_tenants_result,
            Exception("connection refused"),
        ]

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session_ctx)

        with patch(
            "app.modules.glossary.warmup.async_session_factory", mock_factory
        ), patch("app.modules.glossary.warmup.get_redis") as mock_get_redis, patch(
            "app.modules.glossary.warmup.logger"
        ) as mock_logger:
            mock_redis = AsyncMock()
            mock_redis.exists.return_value = 0
            mock_get_redis.return_value = mock_redis

            from app.modules.glossary.warmup import warm_up_glossary_cache

            await warm_up_glossary_cache()

            # Should log warning for the failed tenant
            mock_logger.warning.assert_any_call(
                "glossary_warmup_tenant_failed",
                tenant_id="tenant-fail",
                error="connection refused",
            )

            # Should still complete (skipped=1)
            mock_logger.info.assert_any_call(
                "glossary_warmup_complete",
                total_tenants=1,
                warmed=0,
                skipped=1,
                already_cached=0,
                elapsed_ms=pytest.approx(0, abs=5000),
            )

    @pytest.mark.asyncio
    async def test_zero_glossary_terms_caches_empty_list(self):
        """Tenant with zero glossary terms still caches empty list (warmed=1)."""
        mock_session = AsyncMock()

        # First call: get active tenants
        mock_tenants_result = MagicMock()
        mock_tenants_result.fetchall.return_value = [("tenant-empty",)]

        # Second call: no glossary terms
        mock_terms_result = MagicMock()
        mock_terms_result.fetchall.return_value = []

        mock_session.execute.side_effect = [mock_tenants_result, mock_terms_result]

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session_ctx)

        with patch(
            "app.modules.glossary.warmup.async_session_factory", mock_factory
        ), patch("app.modules.glossary.warmup.get_redis") as mock_get_redis, patch(
            "app.modules.glossary.warmup.logger"
        ) as mock_logger:
            mock_redis = AsyncMock()
            mock_redis.exists.return_value = 0
            mock_get_redis.return_value = mock_redis

            from app.modules.glossary.warmup import warm_up_glossary_cache

            await warm_up_glossary_cache()

            # Should cache an empty list
            mock_redis.setex.assert_called_once()
            call_args = mock_redis.setex.call_args
            assert call_args[0][0] == "mingai:tenant-empty:glossary_terms"
            assert call_args[0][1] == 3600
            assert json.loads(call_args[0][2]) == []

            # Should log warmed=1 (empty list is still a valid cache entry)
            mock_logger.info.assert_any_call(
                "glossary_warmup_complete",
                total_tenants=1,
                warmed=1,
                skipped=0,
                already_cached=0,
                elapsed_ms=pytest.approx(0, abs=5000),
            )

    @pytest.mark.asyncio
    async def test_aliases_as_json_string_parsed_correctly(self):
        """Aliases stored as JSON string in DB are correctly parsed to list."""
        mock_session = AsyncMock()

        # First call: get active tenants
        mock_tenants_result = MagicMock()
        mock_tenants_result.fetchall.return_value = [("tenant-json",)]

        # Second call: aliases as JSON string (not list)
        mock_terms_result = MagicMock()
        mock_terms_result.fetchall.return_value = [
            ("HR", "Human Resources", '["People Ops", "Personnel"]'),
        ]

        mock_session.execute.side_effect = [mock_tenants_result, mock_terms_result]

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session_ctx)

        with patch(
            "app.modules.glossary.warmup.async_session_factory", mock_factory
        ), patch("app.modules.glossary.warmup.get_redis") as mock_get_redis, patch(
            "app.modules.glossary.warmup.logger"
        ) as mock_logger:
            mock_redis = AsyncMock()
            mock_redis.exists.return_value = 0
            mock_get_redis.return_value = mock_redis

            from app.modules.glossary.warmup import warm_up_glossary_cache

            await warm_up_glossary_cache()

            # Verify cached data has aliases parsed from JSON string
            mock_redis.setex.assert_called_once()
            call_args = mock_redis.setex.call_args
            cached_data = json.loads(call_args[0][2])
            assert len(cached_data) == 1
            assert cached_data[0]["aliases"] == ["People Ops", "Personnel"]
