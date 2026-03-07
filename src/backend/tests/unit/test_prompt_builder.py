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
        builder._get_agent_prompt = AsyncMock(return_value="You are an HR assistant.")

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
            return_value="You are an HR Policy Assistant."
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
        builder._get_agent_prompt = AsyncMock(return_value="Agent base.")

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
        builder._get_agent_prompt = AsyncMock(return_value="Agent.")

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
        builder._get_agent_prompt = AsyncMock(return_value="Agent.")

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
        builder._get_agent_prompt = AsyncMock(return_value="Agent.")

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
        builder._get_agent_prompt = AsyncMock(return_value="Agent.")

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
        builder._get_agent_prompt = AsyncMock(return_value="Agent.")

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
        builder._get_agent_prompt = AsyncMock(return_value="Agent.")

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
        builder._get_agent_prompt = AsyncMock(return_value="Agent.")

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
        builder._get_agent_prompt = AsyncMock(return_value="Agent base prompt.")

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
