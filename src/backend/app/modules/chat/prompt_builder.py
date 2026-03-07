"""
SystemPromptBuilder (AI-041) - 6-layer system prompt assembly.

Token budgets (canonical -- never deviate):
  Layer 0: Agent base (~100 tokens, fixed)
  Layer 1: Platform base (~100 tokens, fixed)
  Layer 2: Org Context (100 tokens)
  Layer 3: Profile Context (200 tokens)
  Layer 4a: Individual Working Memory (100 tokens)
  Layer 4b: Team Working Memory (150 tokens)
  Layer 5: RAG Domain Context (remaining budget)
  Layer 6: Glossary (0 tokens -- removed, pre-translated inline)
Total overhead (2-4b): 550 tokens
"""
import json

import structlog

logger = structlog.get_logger()


class SystemPromptBuilder:
    """
    Assembles the system prompt from 6 layers with strict token budgets.

    Layer 6 (glossary) is 0 tokens because glossary expansion happens
    inline during query pre-translation (GlossaryExpander), not in the
    system prompt.
    """

    LAYER_BUDGETS = {
        "org_context": 100,
        "profile": 200,
        "working_memory": 100,
        "team_memory": 150,
    }

    async def build(
        self,
        agent_id: str,
        tenant_id: str,
        org_context: dict | None,
        profile_context: dict | None,
        working_memory: dict | None,
        team_memory: dict | None,
        rag_context: list,
        query_budget: int = 2048,
        db_session=None,
    ) -> tuple[str, list[str]]:
        """
        Build the complete system prompt from all 6 layers.

        Args:
            agent_id: Agent card ID for Layer 0 prompt.
            tenant_id: Tenant ID for loading agent config.
            org_context: Layer 2 - org/department context.
            profile_context: Layer 3 - user profile attributes.
            working_memory: Layer 4a - individual working memory.
            team_memory: Layer 4b - team working memory.
            rag_context: Layer 5 - search results for RAG.
            query_budget: Total token budget for context (default 2048).

        Returns:
            Tuple of (system_prompt_string, list_of_active_layer_names).
        """
        layers = []
        layers_active = []
        overhead = 0

        # Layer 0: Agent base prompt (from agent_cards table)
        agent_prompt = await self._get_agent_prompt(agent_id, tenant_id, db_session)
        layers.append(agent_prompt)

        # Layer 1: Platform base (universal standards)
        layers.append(self._platform_base())

        # Layer 2: Org Context (100 tokens)
        if org_context:
            org_text = self._format_org_context(org_context)
            truncated = self._truncate_to_tokens(
                org_text, self.LAYER_BUDGETS["org_context"]
            )
            layers.append(truncated)
            overhead += self._count_tokens(truncated)
            layers_active.append("org_context")

        # Layer 3: Profile + memory notes (200 tokens)
        if profile_context:
            profile_text = self._format_profile_context(profile_context)
            truncated = self._truncate_to_tokens(
                profile_text, self.LAYER_BUDGETS["profile"]
            )
            layers.append(truncated)
            overhead += self._count_tokens(truncated)
            layers_active.append("profile")

        # Layer 4a: Individual Working Memory (100 tokens)
        if working_memory:
            wm_text = self._format_working_memory(working_memory)
            truncated = self._truncate_to_tokens(
                wm_text, self.LAYER_BUDGETS["working_memory"]
            )
            layers.append(truncated)
            overhead += self._count_tokens(truncated)
            layers_active.append("working_memory")

        # Layer 4b: Team Working Memory (150 tokens)
        if team_memory:
            tm_text = self._format_team_memory(team_memory)
            truncated = self._truncate_to_tokens(
                tm_text, self.LAYER_BUDGETS["team_memory"]
            )
            layers.append(truncated)
            overhead += self._count_tokens(truncated)
            layers_active.append("team_memory")

        # Layer 5: RAG Domain Context (remaining budget)
        rag_budget = query_budget - overhead
        if rag_context:
            rag_text = self._format_rag_context(rag_context, rag_budget)
            layers.append(rag_text)

        # Layer 6: Glossary -- REMOVED (pre-translated inline, 0 tokens)
        # Glossary expansion happens in GlossaryExpander before the LLM call.

        logger.info(
            "system_prompt_built",
            layers_active=layers_active,
            overhead_tokens=overhead,
            rag_budget=rag_budget,
            total_layers=len(layers),
        )

        return "\n\n---\n\n".join(filter(None, layers)), layers_active

    _DEFAULT_AGENT_PROMPT = (
        "You are an AI assistant configured for this workspace. "
        "Answer questions using the provided knowledge base context."
    )

    async def _get_agent_prompt(
        self, agent_id: str, tenant_id: str, db_session=None
    ) -> str:
        """
        Load agent's base system prompt from the agent_cards table.

        Queries agent_cards by agent_id and tenant_id. Returns the configured
        system_prompt if found and active. Falls back to the default platform
        prompt if the agent card is not found, the agent_id is not a valid UUID,
        or no DB session is available.
        """
        import uuid as _uuid

        from sqlalchemy import text

        if db_session is None:
            logger.debug(
                "agent_prompt_db_unavailable",
                agent_id=agent_id,
                reason="no db_session — using default platform prompt",
            )
            return self._DEFAULT_AGENT_PROMPT

        # Validate agent_id is a UUID before querying (agent_cards uses UUID PK)
        try:
            _uuid.UUID(agent_id)
        except (ValueError, AttributeError):
            logger.debug(
                "agent_prompt_id_not_uuid",
                agent_id=agent_id,
                reason="agent_id is not a UUID — using default platform prompt",
            )
            return self._DEFAULT_AGENT_PROMPT

        try:
            result = await db_session.execute(
                text(
                    "SELECT system_prompt FROM agent_cards "
                    "WHERE id = :agent_id AND tenant_id = :tenant_id "
                    "AND status = 'active' LIMIT 1"
                ),
                {"agent_id": agent_id, "tenant_id": tenant_id},
            )
            row = result.fetchone()
        except Exception as exc:
            logger.warning(
                "agent_prompt_db_lookup_failed",
                agent_id=agent_id,
                tenant_id=tenant_id,
                error=str(exc),
            )
            return self._DEFAULT_AGENT_PROMPT

        if row is None:
            logger.debug(
                "agent_prompt_not_found",
                agent_id=agent_id,
                tenant_id=tenant_id,
                reason="no active agent_card found — using default platform prompt",
            )
            return self._DEFAULT_AGENT_PROMPT

        logger.info(
            "agent_prompt_loaded",
            agent_id=agent_id,
            tenant_id=tenant_id,
            prompt_length=len(row[0]),
        )
        return row[0]

    def _platform_base(self) -> str:
        """Layer 1: Universal platform standards."""
        return (
            "You are an AI assistant for enterprise knowledge management. "
            "Base your answers on the provided context. "
            "If information is not in the context, say so clearly. "
            "Label confidence as 'retrieval confidence' -- this reflects "
            "source quality, not answer quality."
        )

    def _format_org_context(self, org_context: dict) -> str:
        """Format org context into a prompt section."""
        parts = ["[Organization Context]"]
        for key, value in org_context.items():
            parts.append(f"- {key}: {value}")
        return "\n".join(parts)

    def _format_profile_context(self, profile_context: dict) -> str:
        """Format user profile into a prompt section."""
        parts = ["[User Profile]"]
        for key, value in profile_context.items():
            if isinstance(value, list):
                parts.append(f"- {key}: {', '.join(str(v) for v in value)}")
            else:
                parts.append(f"- {key}: {value}")
        return "\n".join(parts)

    def _format_working_memory(self, working_memory: dict) -> str:
        """Format working memory into a prompt section."""
        parts = ["[Recent Context]"]
        if "topics" in working_memory:
            parts.append(f"Recent topics: {', '.join(working_memory['topics'])}")
        if "queries" in working_memory:
            parts.append("Recent queries:")
            for q in working_memory["queries"][:3]:
                parts.append(f"  - {q[:100]}")
        return "\n".join(parts)

    def _format_team_memory(self, team_memory: dict) -> str:
        """Format team working memory into a prompt section."""
        parts = ["[Team Context]"]
        if "recent_topics" in team_memory:
            parts.append(f"Team topics: {', '.join(team_memory['recent_topics'])}")
        return "\n".join(parts)

    def _format_rag_context(self, rag_context: list, budget: int) -> str:
        """Format search results into RAG context within budget."""
        if not rag_context:
            return ""

        parts = ["[Knowledge Base Context]"]
        remaining = budget

        for result in rag_context:
            if hasattr(result, "title"):
                entry = f"Source: {result.title}\n{result.content}"
            elif isinstance(result, dict):
                entry = (
                    f"Source: {result.get('title', 'Unknown')}\n"
                    f"{result.get('content', '')}"
                )
            else:
                entry = str(result)

            entry_tokens = self._count_tokens(entry)
            if entry_tokens > remaining:
                # Truncate last entry to fit
                truncated = self._truncate_to_tokens(entry, remaining)
                if truncated:
                    parts.append(truncated)
                break

            parts.append(entry)
            remaining -= entry_tokens

        return "\n\n".join(parts)

    @staticmethod
    def _count_tokens(text: str) -> int:
        """
        Estimate token count for text.

        Uses rough approximation: ~4 characters per token.
        In production, use tiktoken for exact counts.
        """
        if not text:
            return 0
        return len(text) // 4

    @staticmethod
    def _truncate_to_tokens(text: str, max_tokens: int) -> str:
        """
        Truncate text to fit within token budget.

        Uses rough approximation: ~4 characters per token.
        """
        if not text:
            return ""
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rsplit(" ", 1)[0] + "..."
