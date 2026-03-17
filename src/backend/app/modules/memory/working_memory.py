"""
WorkingMemoryService (AI-011 to AI-020).

Redis-backed working memory tracking recent topics and queries per user
per agent. Used for context continuity across conversations.

Redis key: mingai:{tenant_id}:working_memory:{user_id}:{agent_id}
TTL: 7 days
Max topics: 5
Max queries: 3 (100-char truncation)
Token budget: 100 tokens

DEF-004: Checks user_privacy_settings.working_memory_enabled before storing.
When disabled, update() returns early without writing to Redis.
"""
import json
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import get_redis

logger = structlog.get_logger()

# Constants
MAX_TOPICS = 5
MAX_QUERIES = 3
MAX_QUERY_LENGTH = 100
WORKING_MEMORY_TTL_SECONDS = 604800  # 7 days


def _build_key(tenant_id: str, user_id: str, agent_id: str) -> str:
    """Build working memory Redis key."""
    return f"mingai:{tenant_id}:working_memory:{user_id}:{agent_id}"


class WorkingMemoryService:
    """
    Manages per-user, per-agent working memory in Redis.

    Tracks recent topics (max 5) and recent queries (max 3, truncated
    to 100 chars) to provide context continuity.
    """

    async def update(
        self,
        user_id: str,
        tenant_id: str,
        agent_id: str,
        query: str,
        response: str,
        db: Optional[AsyncSession] = None,
    ) -> None:
        """
        Update working memory after a query-response exchange.

        Adds extracted topics and the query to the memory store.
        Prunes topics to MAX_TOPICS and queries to MAX_QUERIES.

        DEF-004: If db is provided, checks working_memory_enabled privacy
        setting before storing. Returns early if disabled.

        Args:
            user_id: User identifier.
            tenant_id: Tenant scope.
            agent_id: Agent that handled the query.
            query: The user's query text.
            response: The assistant's response text.
            db: Optional async session for privacy setting check.
        """
        if db is not None:
            from app.modules.users.privacy_settings import (
                _check_privacy_setting,
            )  # noqa: PLC0415

            enabled = await _check_privacy_setting(
                db, tenant_id, user_id, "working_memory_enabled"
            )
            if not enabled:
                logger.debug(
                    "working_memory_skipped_privacy",
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
                return

        key = _build_key(tenant_id, user_id, agent_id)
        redis = get_redis()

        # Load existing memory
        existing_raw = await redis.get(key)
        if existing_raw:
            memory = json.loads(existing_raw)
        else:
            memory = {"topics": [], "queries": []}

        # Extract topic from query (simple extraction)
        new_topic = self._extract_topic(query)
        if new_topic and new_topic not in memory["topics"]:
            memory["topics"].append(new_topic)

        # Prune topics to max 5 (keep newest)
        if len(memory["topics"]) > MAX_TOPICS:
            memory["topics"] = memory["topics"][-MAX_TOPICS:]

        # Add query (truncated to 100 chars)
        truncated_query = query[:MAX_QUERY_LENGTH]
        memory["queries"].append(truncated_query)

        # Prune queries to max 3 (keep newest)
        if len(memory["queries"]) > MAX_QUERIES:
            memory["queries"] = memory["queries"][-MAX_QUERIES:]

        # Store with TTL
        await redis.setex(
            key,
            WORKING_MEMORY_TTL_SECONDS,
            json.dumps(memory),
        )

        logger.debug(
            "working_memory_updated",
            user_id=user_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            topic_count=len(memory["topics"]),
            query_count=len(memory["queries"]),
        )

    async def get_for_prompt(
        self,
        user_id: str,
        tenant_id: str,
        agent_id: str,
    ) -> dict | None:
        """
        Get working memory for system prompt injection.

        Returns memory data dict or None if no memory exists.
        Budget: 100 tokens.

        Args:
            user_id: User identifier.
            tenant_id: Tenant scope.
            agent_id: Agent scope.

        Returns:
            Dict with 'topics' and 'queries' keys, or None.
        """
        key = _build_key(tenant_id, user_id, agent_id)
        redis = get_redis()

        raw = await redis.get(key)
        if not raw:
            return None

        return json.loads(raw)

    async def clear_memory(
        self,
        user_id: str,
        tenant_id: str,
        agent_id: str | None = None,
    ) -> None:
        """
        Clear working memory for a user.

        If agent_id is provided, clears only that agent's memory.
        If agent_id is None, scans and deletes ALL agent keys for
        this user (GDPR compliance -- aihub2 bug fix).

        Args:
            user_id: User whose memory to clear.
            tenant_id: Tenant scope.
            agent_id: Specific agent, or None for all.
        """
        redis = get_redis()

        if agent_id is not None:
            key = _build_key(tenant_id, user_id, agent_id)
            await redis.delete(key)
            logger.info(
                "working_memory_cleared",
                user_id=user_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
            )
        else:
            # GDPR: scan and delete ALL agent keys for this user
            pattern = f"mingai:{tenant_id}:working_memory:{user_id}:*"
            deleted_count = 0
            async for key in redis.scan_iter(pattern):
                await redis.delete(key)
                deleted_count += 1

            logger.info(
                "working_memory_gdpr_cleared",
                user_id=user_id,
                tenant_id=tenant_id,
                keys_deleted=deleted_count,
            )

    @staticmethod
    def _extract_topic(query: str) -> str | None:
        """
        Extract a topic from a query (simple keyword extraction).

        Phase 1: Simple extraction based on key phrases.
        Phase 2: Uses intent_model LLM for better extraction.
        """
        if not query or not query.strip():
            return None

        # Simple topic extraction: use first meaningful phrase
        query_clean = query.strip().lower()

        # Remove question words
        for prefix in [
            "how do i ",
            "how to ",
            "what is ",
            "what are ",
            "tell me about ",
            "explain ",
            "show me ",
            "can you ",
            "please ",
        ]:
            if query_clean.startswith(prefix):
                query_clean = query_clean[len(prefix) :]
                break

        # Take first 3-4 significant words as topic
        words = query_clean.split()[:4]
        if words:
            topic = " ".join(words).rstrip("?.,!")
            return topic if len(topic) > 2 else None

        return None
