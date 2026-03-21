"""
ATA-031: Integration tests for ToolResolver and SystemPromptBuilder.build_tool_context.

Tests (real PostgreSQL — no mocking):
  1. Healthy tool in tool_catalog → resolved and returned (source='tool_catalog')
  2. Degraded tool in tool_catalog → returned with status='degraded'
  3. Unavailable (inactive) tool in tool_catalog → NOT returned
  4. mcp_server tool → resolved and returned (source='mcp_server')
  5. Unknown tool ID → warning logged, not in results, no exception raised
  6. build_tool_context produces correct format with "Available tools:" header

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_tool_resolver.py -v --timeout=60
"""
import asyncio
import logging
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Skip guards — fire when real infrastructure is absent
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict = None):
    """Execute SQL, commit, and return the result."""
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def _fetch_one(sql: str, params: dict = None):
    """Execute SQL and return first row as a mapping (or None)."""
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            row = result.mappings().first()
            return dict(row) if row is not None else None
    finally:
        await engine.dispose()


async def _create_test_tenant() -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"ToolResolver Test {tid[:8]}",
            "slug": f"tool-res-{tid[:8]}",
            "email": f"admin-{tid[:8]}@tool-res-int.test",
        },
    )
    return tid


async def _insert_tool_catalog_row(
    tool_id: str,
    name: str,
    health_status: str,
) -> None:
    """Insert a row directly into tool_catalog (platform-scoped table, no tenant_id)."""
    await _run_sql(
        """
        INSERT INTO tool_catalog
            (id, name, provider, mcp_endpoint, auth_type, capabilities,
             safety_classification, health_status)
        VALUES
            (:id, :name, :provider, :endpoint, 'api_key', '[]',
             'ReadOnly', :health_status)
        ON CONFLICT (id) DO UPDATE
            SET health_status = EXCLUDED.health_status
        """,
        {
            "id": tool_id,
            "name": name,
            "provider": f"test-provider-{tool_id[:8]}",
            "endpoint": f"https://mcp.example.com/{tool_id[:8]}",
            "health_status": health_status,
        },
    )


async def _insert_mcp_server_row(
    server_id: str,
    tenant_id: str,
    name: str,
    status: str = "active",
) -> None:
    """Insert a row into mcp_servers (tenant-scoped)."""
    await _run_sql(
        """
        INSERT INTO mcp_servers
            (id, tenant_id, name, endpoint, auth_type, status)
        VALUES
            (:id, :tenant_id, :name, :endpoint, 'api_key', :status)
        ON CONFLICT (tenant_id, name) DO UPDATE
            SET status = EXCLUDED.status
        """,
        {
            "id": server_id,
            "tenant_id": tenant_id,
            "name": name,
            "endpoint": f"https://mcp.example.com/server/{server_id[:8]}",
            "status": status,
        },
    )


async def _cleanup_tenant(tid: str) -> None:
    tables = ["mcp_servers", "users", "tenants"]
    for table in tables:
        col = "id" if table == "tenants" else "tenant_id"
        await _run_sql(f"DELETE FROM {table} WHERE {col} = :tid", {"tid": tid})


async def _cleanup_tool_catalog_row(tool_id: str) -> None:
    await _run_sql(
        "DELETE FROM tool_catalog WHERE id = :id", {"id": tool_id}
    )


# ---------------------------------------------------------------------------
# Module fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tenant_id():
    """Create a tenant once per module; clean up after all tests."""
    tid = asyncio.run(_create_test_tenant())
    yield tid
    asyncio.run(_cleanup_tenant(tid))


# ---------------------------------------------------------------------------
# Tests: ToolResolver.resolve()
# ---------------------------------------------------------------------------


class TestToolResolverIntegration:
    """
    Verify ToolResolver.resolve() against a real PostgreSQL database.

    All tool_catalog rows are uniquely named per test run to avoid collisions.
    """

    def _resolve(self, tenant_id: str, tool_ids: list[str]):
        """Run ToolResolver.resolve() synchronously via asyncio.run()."""

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as db:
                    # Set platform scope so RLS allows tool_catalog reads
                    await db.execute(
                        text("SET LOCAL app.current_scope = 'platform'")
                    )
                    await db.execute(
                        text("SET LOCAL app.user_role = 'platform_admin'")
                    )
                    from app.modules.chat.tool_resolver import ToolResolver

                    resolver = ToolResolver(db=db, tenant_id=tenant_id)
                    return await resolver.resolve(tool_ids)
            finally:
                await engine.dispose()

        return asyncio.run(_run())

    def test_healthy_tool_catalog_tool_is_resolved(self, tenant_id):
        """
        A tool_catalog row with health_status='healthy' must be returned
        with source='tool_catalog' and status='healthy'.
        """
        tool_id = str(uuid.uuid4())
        asyncio.run(
            _insert_tool_catalog_row(tool_id, f"HealthyTool-{tool_id[:8]}", "healthy")
        )
        try:
            results = self._resolve(tenant_id, [tool_id])
            assert len(results) == 1
            assert results[0].tool_id == tool_id
            assert results[0].source == "tool_catalog"
            assert results[0].status == "healthy"
        finally:
            asyncio.run(_cleanup_tool_catalog_row(tool_id))

    def test_degraded_tool_catalog_tool_is_returned(self, tenant_id):
        """
        A tool_catalog row with health_status='degraded' must be returned
        (degraded tools are visible per v048 RLS; NOT filtered out).
        """
        tool_id = str(uuid.uuid4())
        asyncio.run(
            _insert_tool_catalog_row(
                tool_id, f"DegradedTool-{tool_id[:8]}", "degraded"
            )
        )
        try:
            results = self._resolve(tenant_id, [tool_id])
            assert len(results) == 1
            assert results[0].status == "degraded"
            assert results[0].source == "tool_catalog"
        finally:
            asyncio.run(_cleanup_tool_catalog_row(tool_id))

    def test_unavailable_tool_catalog_tool_not_returned(self, tenant_id):
        """
        A tool_catalog row with health_status='unavailable' must NOT be
        returned — the UNION ALL query filters out unavailable tools.
        """
        tool_id = str(uuid.uuid4())
        asyncio.run(
            _insert_tool_catalog_row(
                tool_id, f"UnavailableTool-{tool_id[:8]}", "unavailable"
            )
        )
        try:
            results = self._resolve(tenant_id, [tool_id])
            assert results == [], (
                "Unavailable tools must be filtered out by the resolver query"
            )
        finally:
            asyncio.run(_cleanup_tool_catalog_row(tool_id))

    def test_mcp_server_active_tool_is_resolved(self, tenant_id):
        """
        An mcp_servers row with status='active' belonging to the caller's
        tenant must be returned with source='mcp_server'.
        """
        server_id = str(uuid.uuid4())
        asyncio.run(
            _insert_mcp_server_row(
                server_id,
                tenant_id,
                f"ActiveMcpServer-{server_id[:8]}",
                status="active",
            )
        )
        try:
            results = self._resolve(tenant_id, [server_id])
            assert len(results) == 1
            assert results[0].tool_id == server_id
            assert results[0].source == "mcp_server"
            assert results[0].status == "active"
        finally:
            asyncio.run(
                _run_sql(
                    "DELETE FROM mcp_servers WHERE id = :id", {"id": server_id}
                )
            )

    def test_unknown_tool_id_not_in_results_no_exception(self, tenant_id, caplog):
        """
        Calling resolve() with an unknown tool ID must return an empty list
        and log a warning — it must never raise.
        """
        unknown_id = str(uuid.uuid4())

        with caplog.at_level(logging.WARNING, logger="app.modules.chat.tool_resolver"):
            results = self._resolve(tenant_id, [unknown_id])

        assert results == [], "Unknown tool ID must not produce any resolved tool"
        warning_messages = [r.message for r in caplog.records]
        assert any(
            "tool_resolution_missing" in m or "not found" in m
            for m in warning_messages
        ), "Missing tool ID must trigger a warning log"

    def test_empty_tool_ids_returns_empty_list_immediately(self, tenant_id):
        """
        resolve([]) must return [] without touching the database.
        """
        results = self._resolve(tenant_id, [])
        assert results == []


# ---------------------------------------------------------------------------
# Tests: SystemPromptBuilder.build_tool_context
# ---------------------------------------------------------------------------


class TestBuildToolContextIntegration:
    """
    Verify SystemPromptBuilder.build_tool_context() produces the correct
    text format for a list of ResolvedTool objects.

    This tests the format contract — no DB required, but structured as
    integration test to confirm import paths are stable end-to-end.
    """

    def test_build_tool_context_correct_format(self):
        """
        build_tool_context produces 'Available tools:' header followed by
        one '- Name: source, status=...' line per tool.
        """
        from app.modules.chat.prompt_builder import SystemPromptBuilder
        from app.modules.chat.tool_resolver import ResolvedTool

        tools = [
            ResolvedTool(
                tool_id="t1",
                name="Jira",
                source="tool_catalog",
                endpoint="https://jira/mcp",
                auth_type="api_key",
                status="healthy",
            ),
            ResolvedTool(
                tool_id="t2",
                name="Slack MCP",
                source="mcp_server",
                endpoint="https://slack/mcp",
                auth_type="oauth2",
                status="active",
            ),
        ]

        result = SystemPromptBuilder.build_tool_context(tools)

        assert result.startswith("Available tools:")
        assert "- Jira: tool_catalog, status=healthy" in result
        assert "- Slack MCP: mcp_server, status=active" in result

    def test_build_tool_context_empty_returns_empty_string(self):
        """build_tool_context([]) returns empty string."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        assert SystemPromptBuilder.build_tool_context([]) == ""
