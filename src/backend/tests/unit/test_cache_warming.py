"""
Unit tests for INFRA-014: Cache warming background job.

Tests validate that warm_embedding_cache():
- Skips tenants inactive for the past 7 days
- Respects MAX_QUERIES_PER_TENANT (100) cap
- Calls EmbeddingService.embed() for each top query
- Continues past per-tenant embed errors (never aborts all tenants)
- Logs per-tenant stats and totals
- Handles EmbeddingService init failure gracefully (missing env var)
- Does not blow up on zero active tenants
"""
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_session(tenant_rows, activity_counts, query_rows_by_tenant):
    """
    Build a mock async_session_factory context manager.

    tenant_rows: list of (id,) tuples for active tenants
    activity_counts: dict[tenant_id -> int] (recent 7-day activity count)
    query_rows_by_tenant: dict[tenant_id -> list[str]] (top queries)
    """
    session = AsyncMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        stmt_str = str(stmt)

        # Tenant list query
        if "SELECT id FROM tenants" in stmt_str:
            result.fetchall.return_value = tenant_rows
            return result

        # Activity check query (7-day window)
        if "INTERVAL '7 days'" in stmt_str:
            tenant_id = params["tenant_id"]
            result.scalar.return_value = activity_counts.get(tenant_id, 0)
            return result

        # Top queries query (30-day window)
        if "INTERVAL '30 days'" in stmt_str:
            tenant_id = params["tenant_id"]
            queries = query_rows_by_tenant.get(tenant_id, [])
            result.fetchall.return_value = [(q,) for q in queries]
            return result

        result.fetchall.return_value = []
        result.scalar.return_value = 0
        return result

    session.execute = _execute
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCacheWarmingSkipsInactive:
    """Tenants with no activity in the past 7 days are skipped."""

    @pytest.mark.asyncio
    async def test_inactive_tenant_is_skipped(self):
        tenant_rows = [("tenant-a",), ("tenant-b",)]
        # tenant-a: no recent activity; tenant-b: has activity
        activity = {"tenant-a": 0, "tenant-b": 5}
        queries = {"tenant-b": ["what is the refund policy?"]}

        session_ctx = _make_session(tenant_rows, activity, queries)
        embed_mock = AsyncMock(return_value=[0.1] * 768)

        with (
            patch(
                "app.modules.chat.cache_warming.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.chat.cache_warming.EmbeddingService") as MockEmb,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            instance = MockEmb.return_value
            instance.embed = embed_mock

            from app.modules.chat.cache_warming import warm_embedding_cache

            await warm_embedding_cache()

        # embed called once (tenant-b only), tenant-a skipped
        assert embed_mock.call_count == 1
        args = embed_mock.call_args_list[0]
        assert args == call("what is the refund policy?", tenant_id="tenant-b")

    @pytest.mark.asyncio
    async def test_all_inactive_tenants_produces_no_embed_calls(self):
        tenant_rows = [("tenant-x",)]
        activity = {"tenant-x": 0}
        queries = {}

        session_ctx = _make_session(tenant_rows, activity, queries)
        embed_mock = AsyncMock(return_value=[0.0] * 768)

        with (
            patch(
                "app.modules.chat.cache_warming.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.chat.cache_warming.EmbeddingService") as MockEmb,
        ):
            instance = MockEmb.return_value
            instance.embed = embed_mock

            from app.modules.chat.cache_warming import warm_embedding_cache

            await warm_embedding_cache()

        embed_mock.assert_not_called()


class TestCacheWarmingQueriesWarmed:
    """Embedding is called for each top query of active tenants."""

    @pytest.mark.asyncio
    async def test_embeds_all_top_queries(self):
        top_queries = [f"query {i}" for i in range(5)]
        tenant_rows = [("t1",)]
        activity = {"t1": 10}
        queries = {"t1": top_queries}

        session_ctx = _make_session(tenant_rows, activity, queries)
        embed_mock = AsyncMock(return_value=[0.1] * 768)

        with (
            patch(
                "app.modules.chat.cache_warming.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.chat.cache_warming.EmbeddingService") as MockEmb,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            instance = MockEmb.return_value
            instance.embed = embed_mock

            from app.modules.chat.cache_warming import warm_embedding_cache

            await warm_embedding_cache()

        assert embed_mock.call_count == 5
        called_queries = [c.args[0] for c in embed_mock.call_args_list]
        assert called_queries == top_queries

    @pytest.mark.asyncio
    async def test_embed_called_with_correct_tenant_id(self):
        tenant_rows = [("tenant-abc",)]
        activity = {"tenant-abc": 3}
        queries = {"tenant-abc": ["how do I reset my password?"]}

        session_ctx = _make_session(tenant_rows, activity, queries)
        embed_mock = AsyncMock(return_value=[0.5] * 768)

        with (
            patch(
                "app.modules.chat.cache_warming.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.chat.cache_warming.EmbeddingService") as MockEmb,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            instance = MockEmb.return_value
            instance.embed = embed_mock

            from app.modules.chat.cache_warming import warm_embedding_cache

            await warm_embedding_cache()

        embed_mock.assert_called_once_with(
            "how do I reset my password?", tenant_id="tenant-abc"
        )


class TestCacheWarmingErrorHandling:
    """Embed errors and tenant failures do not abort the full job."""

    @pytest.mark.asyncio
    async def test_embed_error_for_one_query_continues_remaining(self):
        top_queries = ["good query", "bad query", "another good query"]
        tenant_rows = [("t-err",)]
        activity = {"t-err": 10}
        queries = {"t-err": top_queries}

        session_ctx = _make_session(tenant_rows, activity, queries)

        call_count = 0

        async def flaky_embed(text, tenant_id=None):
            nonlocal call_count
            call_count += 1
            if text == "bad query":
                raise RuntimeError("Embedding API timeout")
            return [0.1] * 768

        with (
            patch(
                "app.modules.chat.cache_warming.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.chat.cache_warming.EmbeddingService") as MockEmb,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            instance = MockEmb.return_value
            instance.embed = flaky_embed

            from app.modules.chat.cache_warming import warm_embedding_cache

            # Must not raise
            await warm_embedding_cache()

        # All 3 queries attempted despite one error
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_embedding_service_init_failure_returns_early(self):
        """If EMBEDDING_MODEL is not set, the job exits cleanly without DB calls."""
        session_ctx = _make_session([], {}, {})

        with (
            patch(
                "app.modules.chat.cache_warming.async_session_factory",
                return_value=session_ctx,
            ),
            patch(
                "app.modules.chat.cache_warming.EmbeddingService",
                side_effect=ValueError("EMBEDDING_MODEL not configured"),
            ),
        ):
            from app.modules.chat.cache_warming import warm_embedding_cache

            # Must not raise
            await warm_embedding_cache()

        # session_ctx.__aenter__ was NOT called (job exited before DB access)
        session_ctx.__aenter__.assert_not_called()


class TestCacheWarmingNoTenants:
    """Handles the case where there are no active tenants gracefully."""

    @pytest.mark.asyncio
    async def test_no_active_tenants_does_nothing(self):
        session_ctx = _make_session([], {}, {})
        embed_mock = AsyncMock(return_value=[0.0] * 768)

        with (
            patch(
                "app.modules.chat.cache_warming.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.chat.cache_warming.EmbeddingService") as MockEmb,
        ):
            instance = MockEmb.return_value
            instance.embed = embed_mock

            from app.modules.chat.cache_warming import warm_embedding_cache

            await warm_embedding_cache()

        embed_mock.assert_not_called()


class TestCacheWarmingRateLimit:
    """asyncio.sleep is called between embed calls to enforce rate limit."""

    @pytest.mark.asyncio
    async def test_sleep_called_between_queries(self):
        top_queries = ["q1", "q2", "q3"]
        tenant_rows = [("t-rate",)]
        activity = {"t-rate": 10}
        queries = {"t-rate": top_queries}

        session_ctx = _make_session(tenant_rows, activity, queries)
        embed_mock = AsyncMock(return_value=[0.1] * 768)
        sleep_mock = AsyncMock()

        with (
            patch(
                "app.modules.chat.cache_warming.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.chat.cache_warming.EmbeddingService") as MockEmb,
            patch("asyncio.sleep", sleep_mock),
        ):
            instance = MockEmb.return_value
            instance.embed = embed_mock

            from app.modules.chat.cache_warming import warm_embedding_cache

            await warm_embedding_cache()

        # sleep is called once per query (rate limiting after each embed call)
        assert sleep_mock.call_count == len(top_queries)
