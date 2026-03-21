"""
Unit tests for ToolResolver (ATA-028) and SystemPromptBuilder.build_tool_context (ATA-030).

Tests:
  1. Empty tool_ids -> returns empty list immediately (no DB call)
  2. DB query failure -> returns empty list, does not raise
  3. resolve() calls DB with correct query structure
  4. Missing tool IDs -> logged with tool_resolution_missing
  5. build_tool_context() with tools -> correct text format
  6. build_tool_context() with empty list -> empty string

Tier 1: Fast, isolated, mocks all DB interaction.
"""
import logging
from unittest.mock import AsyncMock, MagicMock

import structlog

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(tool_id, name, source, endpoint, auth_type, status):
    """Create a mock row with named attribute access (like sqlalchemy Row)."""
    row = MagicMock()
    row.tool_id = tool_id
    row.name = name
    row.source = source
    row.endpoint = endpoint
    row.auth_type = auth_type
    row.status = status
    return row


def _make_db_session(rows=None, raise_on_execute=False):
    """Create a mock AsyncSession."""
    db = AsyncMock()
    if raise_on_execute:
        db.execute = AsyncMock(side_effect=Exception("DB connection lost"))
    else:
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows or []
        db.execute = AsyncMock(return_value=mock_result)
    return db


# ---------------------------------------------------------------------------
# ToolResolver tests
# ---------------------------------------------------------------------------


class TestToolResolverEmptyInput:
    @pytest.mark.asyncio
    async def test_empty_tool_ids_returns_empty_without_db_call(self):
        """Empty tool_ids list returns [] immediately — no DB query."""
        from app.modules.chat.tool_resolver import ToolResolver

        db = _make_db_session()
        resolver = ToolResolver(db=db, tenant_id="tenant-1")
        result = await resolver.resolve([])

        assert result == []
        db.execute.assert_not_called()


class TestToolResolverDbFailure:
    @pytest.mark.asyncio
    async def test_db_error_returns_empty_list(self):
        """DB query failure returns empty list — does not raise."""
        from app.modules.chat.tool_resolver import ToolResolver

        db = _make_db_session(raise_on_execute=True)
        resolver = ToolResolver(db=db, tenant_id="tenant-1")
        result = await resolver.resolve(["tool-uuid-1"])

        assert result == []

    @pytest.mark.asyncio
    async def test_db_error_is_logged(self):
        """DB failure is logged at ERROR level via structlog."""
        from app.modules.chat.tool_resolver import ToolResolver

        db = _make_db_session(raise_on_execute=True)
        resolver = ToolResolver(db=db, tenant_id="tenant-1")

        with structlog.testing.capture_logs() as cap_logs:
            await resolver.resolve(["tool-uuid-1"])

        assert any(
            log.get("event") == "tool_resolver_db_query_failed"
            for log in cap_logs
        )


class TestToolResolverQueryStructure:
    @pytest.mark.asyncio
    async def test_resolve_passes_tool_ids_and_tenant_id_to_db(self):
        """resolve() executes DB with tool_ids and tenant_id parameters."""
        from app.modules.chat.tool_resolver import ToolResolver

        rows = [
            _make_row("tool-1", "Jira", "tool_catalog", "https://jira/mcp", "api_key", "healthy")
        ]
        db = _make_db_session(rows=rows)
        resolver = ToolResolver(db=db, tenant_id="t-abc")
        result = await resolver.resolve(["tool-1"])

        db.execute.assert_called_once()
        call_kwargs = db.execute.call_args
        # Second positional arg is the params dict
        params = call_kwargs[0][1]
        assert params["tool_ids"] == ["tool-1"]
        assert params["tenant_id"] == "t-abc"

    @pytest.mark.asyncio
    async def test_resolve_returns_resolved_tool_objects(self):
        """resolve() maps DB rows to ResolvedTool dataclasses correctly."""
        from app.modules.chat.tool_resolver import ResolvedTool, ToolResolver

        rows = [
            _make_row("tc-1", "Confluence", "tool_catalog", "https://conf/mcp", "none", "healthy"),
            _make_row("mcp-2", "Slack", "mcp_server", "https://slack/ep", "oauth2", "active"),
        ]
        db = _make_db_session(rows=rows)
        resolver = ToolResolver(db=db, tenant_id="t-1")
        result = await resolver.resolve(["tc-1", "mcp-2"])

        assert len(result) == 2
        assert isinstance(result[0], ResolvedTool)
        assert result[0].tool_id == "tc-1"
        assert result[0].source == "tool_catalog"
        assert result[1].tool_id == "mcp-2"
        assert result[1].source == "mcp_server"
        assert result[1].auth_type == "oauth2"


class TestToolResolverMissingIds:
    @pytest.mark.asyncio
    async def test_missing_tool_ids_are_logged(self):
        """tool IDs not returned from DB are logged with tool_resolution_missing via structlog."""
        from app.modules.chat.tool_resolver import ToolResolver

        rows = [
            _make_row("known-1", "Tool A", "tool_catalog", None, "none", "healthy"),
        ]
        db = _make_db_session(rows=rows)
        resolver = ToolResolver(db=db, tenant_id="t-1")

        with structlog.testing.capture_logs() as cap_logs:
            await resolver.resolve(["known-1", "unknown-2", "unknown-3"])

        assert any(
            log.get("event") == "tool_resolution_missing"
            for log in cap_logs
        )

    @pytest.mark.asyncio
    async def test_all_tool_ids_found_no_warning(self, caplog):
        """No warning logged when all tool IDs are resolved."""
        from app.modules.chat.tool_resolver import ToolResolver

        rows = [
            _make_row("t-1", "Tool A", "tool_catalog", None, "none", "healthy"),
            _make_row("t-2", "Tool B", "mcp_server", "https://ep", "api_key", "active"),
        ]
        db = _make_db_session(rows=rows)
        resolver = ToolResolver(db=db, tenant_id="ten-1")

        with caplog.at_level(logging.WARNING, logger="app.modules.chat.tool_resolver"):
            result = await resolver.resolve(["t-1", "t-2"])

        assert len(result) == 2
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("tool_resolution_missing" in m for m in warning_messages)


# ---------------------------------------------------------------------------
# SystemPromptBuilder.build_tool_context tests
# ---------------------------------------------------------------------------


class TestBuildToolContext:
    def test_empty_list_returns_empty_string(self):
        """build_tool_context([]) returns empty string."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        result = SystemPromptBuilder.build_tool_context([])
        assert result == ""

    def test_single_tool_formats_correctly(self):
        """Single tool produces correct text block."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder
        from app.modules.chat.tool_resolver import ResolvedTool

        tool = ResolvedTool(
            tool_id="tc-1",
            name="Jira",
            source="tool_catalog",
            endpoint="https://jira/mcp",
            auth_type="api_key",
            status="healthy",
        )
        result = SystemPromptBuilder.build_tool_context([tool])
        assert result.startswith("Available tools:")
        assert "- Jira: tool_catalog, status=healthy" in result

    def test_multiple_tools_all_appear(self):
        """Multiple tools each appear as a line."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder
        from app.modules.chat.tool_resolver import ResolvedTool

        tools = [
            ResolvedTool("t1", "Jira", "tool_catalog", None, "api_key", "healthy"),
            ResolvedTool("t2", "Slack", "mcp_server", "https://slack/ep", "oauth2", "active"),
            ResolvedTool("t3", "Confluence", "tool_catalog", None, "none", "degraded"),
        ]
        result = SystemPromptBuilder.build_tool_context(tools)
        assert "- Jira: tool_catalog, status=healthy" in result
        assert "- Slack: mcp_server, status=active" in result
        assert "- Confluence: tool_catalog, status=degraded" in result

    def test_degraded_tool_status_shown(self):
        """Degraded tools show their status in the output."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder
        from app.modules.chat.tool_resolver import ResolvedTool

        tool = ResolvedTool(
            tool_id="tc-deg",
            name="SlowTool",
            source="tool_catalog",
            endpoint=None,
            auth_type="none",
            status="degraded",
        )
        result = SystemPromptBuilder.build_tool_context([tool])
        assert "status=degraded" in result
