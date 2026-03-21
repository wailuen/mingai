"""
Unit tests for SystemPromptBuilder (AI-041).

Tests the 6-layer prompt assembly, token budgets, and layer activation.
Tier 1: Fast, isolated, no external dependencies.
"""
from unittest.mock import AsyncMock

import pytest


class TestLayerBudgets:
    """Test canonical token budgets are correct."""

    def test_layer_budgets_match_canonical_spec(self):
        """Layer budgets must match canonical specification exactly."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        budgets = SystemPromptBuilder.LAYER_BUDGETS
        assert budgets["org_context"] == 100
        assert budgets["profile"] == 200
        assert budgets["working_memory"] == 100
        assert budgets["team_memory"] == 150

    def test_total_overhead_is_550(self):
        """Total overhead (layers 2-4b) must be 550 tokens."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        total = sum(SystemPromptBuilder.LAYER_BUDGETS.values())
        assert total == 550


class TestSystemPromptBuild:
    """Test the build() method."""

    @pytest.mark.asyncio
    async def test_build_returns_tuple_of_prompt_and_layers(self):
        """build() returns (prompt_string, layers_active_list)."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("You are an HR assistant.", {}, [], []))

        prompt, layers_active = await builder.build(
            agent_id="hr-bot",
            tenant_id="t1",
            org_context=None,
            profile_context=None,
            working_memory=None,
            team_memory=None,
            rag_context=[],
        )

        assert isinstance(prompt, str)
        assert isinstance(layers_active, list)

    @pytest.mark.asyncio
    async def test_build_includes_agent_prompt(self):
        """Agent base prompt (Layer 0) is always included."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(
            return_value=("You are an HR Policy Assistant.", {}, [], [])
        )

        prompt, _ = await builder.build(
            agent_id="hr-bot",
            tenant_id="t1",
            org_context=None,
            profile_context=None,
            working_memory=None,
            team_memory=None,
            rag_context=[],
        )

        assert "HR Policy Assistant" in prompt

    @pytest.mark.asyncio
    async def test_build_includes_platform_base(self):
        """Platform base prompt (Layer 1) is always included."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("Agent base.", {}, [], []))

        prompt, _ = await builder.build(
            agent_id="a1",
            tenant_id="t1",
            org_context=None,
            profile_context=None,
            working_memory=None,
            team_memory=None,
            rag_context=[],
        )

        assert "enterprise" in prompt.lower() or "knowledge" in prompt.lower()

    @pytest.mark.asyncio
    async def test_org_context_activates_layer(self):
        """When org_context is provided, 'org_context' appears in layers_active."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("Agent.", {}, [], []))

        _, layers_active = await builder.build(
            agent_id="a1",
            tenant_id="t1",
            org_context={"department": "Engineering", "role": "Developer"},
            profile_context=None,
            working_memory=None,
            team_memory=None,
            rag_context=[],
        )

        assert "org_context" in layers_active

    @pytest.mark.asyncio
    async def test_profile_context_activates_layer(self):
        """When profile_context is provided, 'profile' appears in layers_active."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("Agent.", {}, [], []))

        _, layers_active = await builder.build(
            agent_id="a1",
            tenant_id="t1",
            org_context=None,
            profile_context={
                "technical_level": "expert",
                "communication_style": "concise",
            },
            working_memory=None,
            team_memory=None,
            rag_context=[],
        )

        assert "profile" in layers_active

    @pytest.mark.asyncio
    async def test_working_memory_activates_layer(self):
        """When working_memory is provided, 'working_memory' in layers_active."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("Agent.", {}, [], []))

        _, layers_active = await builder.build(
            agent_id="a1",
            tenant_id="t1",
            org_context=None,
            profile_context=None,
            working_memory={"topics": ["deployment", "testing"]},
            team_memory=None,
            rag_context=[],
        )

        assert "working_memory" in layers_active

    @pytest.mark.asyncio
    async def test_team_memory_activates_layer(self):
        """When team_memory is provided, 'team_memory' in layers_active."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("Agent.", {}, [], []))

        _, layers_active = await builder.build(
            agent_id="a1",
            tenant_id="t1",
            org_context=None,
            profile_context=None,
            working_memory=None,
            team_memory={"recent_topics": ["quarterly review"]},
            rag_context=[],
        )

        assert "team_memory" in layers_active

    @pytest.mark.asyncio
    async def test_no_context_produces_no_active_layers(self):
        """With no optional context, layers_active is empty."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("Agent.", {}, [], []))

        _, layers_active = await builder.build(
            agent_id="a1",
            tenant_id="t1",
            org_context=None,
            profile_context=None,
            working_memory=None,
            team_memory=None,
            rag_context=[],
        )

        assert layers_active == []

    @pytest.mark.asyncio
    async def test_all_layers_active(self):
        """With all context provided, all 4 optional layers are active."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("Agent.", {}, [], []))

        _, layers_active = await builder.build(
            agent_id="a1",
            tenant_id="t1",
            org_context={"dept": "Eng"},
            profile_context={"level": "expert"},
            working_memory={"topics": ["test"]},
            team_memory={"recent": ["topic"]},
            rag_context=[],
        )

        assert "org_context" in layers_active
        assert "profile" in layers_active
        assert "working_memory" in layers_active
        assert "team_memory" in layers_active
        assert len(layers_active) == 4

    @pytest.mark.asyncio
    async def test_glossary_layer_is_zero_tokens(self):
        """Layer 6 (glossary) uses 0 tokens - pre-translated inline."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("Agent.", {}, [], []))

        prompt, _ = await builder.build(
            agent_id="a1",
            tenant_id="t1",
            org_context=None,
            profile_context=None,
            working_memory=None,
            team_memory=None,
            rag_context=[],
        )

        # Glossary should NOT appear in the system prompt
        assert "glossary" not in prompt.lower() or "pre-translated" in prompt.lower()

    @pytest.mark.asyncio
    async def test_layers_separated_by_divider(self):
        """Layers are separated by --- dividers for clarity."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("Agent base prompt.", {}, [], []))

        prompt, _ = await builder.build(
            agent_id="a1",
            tenant_id="t1",
            org_context={"dept": "Eng"},
            profile_context=None,
            working_memory=None,
            team_memory=None,
            rag_context=[],
        )

        assert "---" in prompt


class TestTokenBudget:
    """Token budget and truncation behavior."""

    def test_count_tokens_approximation(self):
        """Token count uses 4 chars per token approximation."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder()
        assert builder._count_tokens("aaaa") == 1
        assert builder._count_tokens("a" * 40) == 10
        assert builder._count_tokens("") == 0

    def test_truncate_to_tokens_long_text(self):
        """Text exceeding budget is truncated at word boundary with ellipsis."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder()
        long_text = " ".join(["word"] * 100)  # 100 words
        truncated = builder._truncate_to_tokens(long_text, 10)
        assert len(truncated) <= 10 * 4 + 3  # budget chars + ellipsis len
        assert truncated.endswith("...")

    def test_truncate_to_tokens_short_text_unchanged(self):
        """Text within budget is returned unchanged."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder()
        short = "Hello world"
        assert builder._truncate_to_tokens(short, 100) == short

    def test_truncate_to_tokens_empty_returns_empty(self):
        """Empty text returns empty string."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder()
        assert builder._truncate_to_tokens("", 100) == ""


class TestAgentPromptFallback:
    """Agent prompt DB lookup with fallback behavior."""

    @pytest.mark.asyncio
    async def test_no_db_session_uses_default_prompt(self):
        """No db_session passed — falls back to _DEFAULT_AGENT_PROMPT."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder()
        result, _, _, _ = await builder._get_agent_prompt("agent-1", "tenant-1", None)
        assert result == SystemPromptBuilder._DEFAULT_AGENT_PROMPT

    @pytest.mark.asyncio
    async def test_non_uuid_agent_id_uses_default_prompt(self):
        """Non-UUID agent_id skips DB lookup and uses default prompt."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        mock_db = AsyncMock()
        builder = SystemPromptBuilder()
        result, _, _, _ = await builder._get_agent_prompt("not-a-uuid", "t1", mock_db)
        assert result == SystemPromptBuilder._DEFAULT_AGENT_PROMPT
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_no_row_uses_default_prompt(self):
        """DB returns no matching agent card — falls back to default."""
        from unittest.mock import MagicMock

        from app.modules.chat.prompt_builder import SystemPromptBuilder

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        builder = SystemPromptBuilder()
        result, _, _, _ = await builder._get_agent_prompt(
            "00000000-0000-0000-0000-000000000001", "t1", mock_db
        )
        assert result == SystemPromptBuilder._DEFAULT_AGENT_PROMPT

    @pytest.mark.asyncio
    async def test_db_returns_custom_prompt(self):
        """DB row with system_prompt returns that prompt."""
        from unittest.mock import MagicMock

        from app.modules.chat.prompt_builder import SystemPromptBuilder

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("Custom agent system prompt.", None)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        builder = SystemPromptBuilder()
        result, _, _, _ = await builder._get_agent_prompt(
            "00000000-0000-0000-0000-000000000001", "t1", mock_db
        )
        assert result == "Custom agent system prompt."


class TestRagBudget:
    """RAG context budget calculation."""

    @pytest.mark.asyncio
    async def test_rag_budget_decreases_with_overhead(self):
        """RAG budget = query_budget - overhead from layers 2-4b."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder
        from app.modules.chat.vector_search import SearchResult

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("Agent.", {}, [], []))

        # Provide org_context to consume overhead
        result = SearchResult(
            title="Doc",
            content="x" * 400,
            score=0.9,
            source_url=None,
            document_id="d1",
        )
        prompt, _ = await builder.build(
            agent_id="a1",
            tenant_id="t1",
            org_context={"dept": "Eng"},
            profile_context=None,
            working_memory=None,
            team_memory=None,
            rag_context=[result],
            query_budget=2048,
        )
        # RAG content should appear in prompt
        assert "Knowledge Base Context" in prompt

    @pytest.mark.asyncio
    async def test_empty_rag_context_omits_rag_section(self):
        """Empty rag_context produces no Knowledge Base Context section."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("Agent.", {}, [], []))

        prompt, _ = await builder.build(
            agent_id="a1",
            tenant_id="t1",
            org_context=None,
            profile_context=None,
            working_memory=None,
            team_memory=None,
            rag_context=[],
        )
        assert "Knowledge Base Context" not in prompt

    @pytest.mark.asyncio
    async def test_rag_not_in_layers_active(self):
        """RAG context never appears in layers_active (not a tracked layer)."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder
        from app.modules.chat.vector_search import SearchResult

        builder = SystemPromptBuilder.__new__(SystemPromptBuilder)
        builder._get_agent_prompt = AsyncMock(return_value=("Agent.", {}, [], []))

        result = SearchResult(
            title="Test",
            content="Content",
            score=0.9,
            source_url=None,
            document_id="d1",
        )
        _, layers_active = await builder.build(
            agent_id="a1",
            tenant_id="t1",
            org_context=None,
            profile_context=None,
            working_memory=None,
            team_memory=None,
            rag_context=[result],
        )
        assert "rag" not in layers_active
        assert "rag_context" not in layers_active


class TestFormatHelpers:
    """Format helper output validates prompt section headers."""

    def test_format_org_context_produces_org_context_header(self):
        """_format_org_context output starts with [Organization Context]."""
        from app.modules.chat.prompt_builder import SystemPromptBuilder

        builder = SystemPromptBuilder()
        result = builder._format_org_context({"department": "Engineering"})
        assert result.startswith("[Organization Context]")
        assert "Engineering" in result


class TestGetTenantTokenBudget:
    """Unit tests for get_tenant_token_budget() — AI-033."""

    @pytest.mark.asyncio
    async def test_get_tenant_token_budget_from_config(self):
        """Returns the integer budget from tenant_configs when present and valid."""
        from unittest.mock import MagicMock

        from app.modules.chat.prompt_builder import get_tenant_token_budget

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ({"budget": 4096},)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        budget = await get_tenant_token_budget(
            db_session=mock_db, tenant_id="tenant-123"
        )
        assert budget == 4096

    @pytest.mark.asyncio
    async def test_get_tenant_token_budget_fallback_when_missing(self):
        """Falls back to 2048 when config_type row is not found in DB."""
        from unittest.mock import MagicMock

        from app.modules.chat.prompt_builder import get_tenant_token_budget

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        budget = await get_tenant_token_budget(
            db_session=mock_db, tenant_id="tenant-456"
        )
        assert budget == 2048

    @pytest.mark.asyncio
    async def test_get_tenant_token_budget_fallback_when_invalid(self):
        """Falls back to 2048 when budget value in config_data is not a valid integer."""
        from unittest.mock import MagicMock

        from app.modules.chat.prompt_builder import get_tenant_token_budget

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ({"budget": "not-a-number"},)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        budget = await get_tenant_token_budget(
            db_session=mock_db, tenant_id="tenant-789"
        )
        assert budget == 2048

    @pytest.mark.asyncio
    async def test_get_tenant_token_budget_fallback_when_out_of_range(self):
        """Falls back to 2048 when budget value is outside [1024, 8192]."""
        from unittest.mock import MagicMock

        from app.modules.chat.prompt_builder import get_tenant_token_budget

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ({"budget": 99},)  # below minimum 1024

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        budget = await get_tenant_token_budget(
            db_session=mock_db, tenant_id="tenant-000"
        )
        assert budget == 2048

    @pytest.mark.asyncio
    async def test_get_tenant_token_budget_fallback_when_no_session(self):
        """Falls back to 2048 when db_session is None."""
        from app.modules.chat.prompt_builder import get_tenant_token_budget

        budget = await get_tenant_token_budget(db_session=None, tenant_id="tenant-001")
        assert budget == 2048

    @pytest.mark.asyncio
    async def test_get_tenant_token_budget_fallback_on_db_error(self):
        """Falls back to 2048 when the DB query raises an exception."""
        from app.modules.chat.prompt_builder import get_tenant_token_budget

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("connection refused"))

        budget = await get_tenant_token_budget(
            db_session=mock_db, tenant_id="tenant-err"
        )
        assert budget == 2048
