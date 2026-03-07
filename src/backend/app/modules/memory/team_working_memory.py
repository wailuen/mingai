"""
TeamWorkingMemoryService (AI-013) -- shared team-level working memory.

Team members' queries contribute to a shared context pool.
Queries are anonymized to protect individual privacy.

Redis key: mingai:{tenant_id}:team_memory:{team_id}
TTL: 7 days
Schema:
  {
    "topics": ["string", ...],          # max 10, deduplicated
    "recent_queries": ["string", ...],  # max 5, anonymized
  }
"""
import json
from typing import Optional

import structlog

logger = structlog.get_logger()

TEAM_MEMORY_TTL = 604800  # 7 days
MAX_TOPICS = 10
MAX_QUERIES = 5
QUERY_TRUNCATION = 100


class TeamWorkingMemoryService:
    """
    Manages shared team-level working memory in Redis.

    Privacy: user_id is NEVER stored. Queries are anonymized
    before persistence. Topic extraction is keyword-based.
    """

    def __init__(self, redis=None):
        """
        Initialize with optional Redis client.

        Args:
            redis: Redis client (injected). If None, get_redis() is called lazily.
        """
        self._redis = redis

    def _redis_key(self, tenant_id: str, team_id: str) -> str:
        """Build Redis key for team memory."""
        return f"mingai:{tenant_id}:team_memory:{team_id}"

    async def _get_redis(self):
        """Get Redis client, lazily initializing if not injected."""
        if self._redis is not None:
            return self._redis
        from app.core.redis_client import get_redis

        return get_redis()

    async def update(
        self, team_id: str, tenant_id: str, query: str, response: str
    ) -> None:
        """
        Add query to team memory. Anonymizes, caps, deduplicates topics.

        Privacy guarantee: No user_id, display name, or personally identifiable
        information is stored. The query is anonymized before persistence.

        Args:
            team_id: Team identifier.
            tenant_id: Tenant scope.
            query: The user's query text (will be anonymized).
            response: The assistant's response text (used for context, not stored).
        """
        if not team_id:
            raise ValueError("team_id is required for team memory update.")
        if not tenant_id:
            raise ValueError("tenant_id is required for team memory update.")

        redis = await self._get_redis()
        key = self._redis_key(tenant_id, team_id)

        # Load existing memory
        existing_raw = await redis.get(key)
        if existing_raw:
            memory = json.loads(existing_raw)
        else:
            memory = {"topics": [], "recent_queries": []}

        # Extract topics from query, union-merge, deduplicate
        new_topics = self._extract_topics_from_query(query)
        existing_topics = memory.get("topics", [])
        merged_topics = list(existing_topics)
        for topic in new_topics:
            if topic not in merged_topics:
                merged_topics.append(topic)

        # Cap topics at MAX_TOPICS (keep newest)
        if len(merged_topics) > MAX_TOPICS:
            merged_topics = merged_topics[-MAX_TOPICS:]
        memory["topics"] = merged_topics

        # Anonymize and prepend query
        anonymized = self._anonymize_query(query)
        recent = memory.get("recent_queries", [])
        recent.append(anonymized)

        # Cap queries at MAX_QUERIES (keep newest)
        if len(recent) > MAX_QUERIES:
            recent = recent[-MAX_QUERIES:]
        memory["recent_queries"] = recent

        # Save with TTL
        await redis.setex(key, TEAM_MEMORY_TTL, json.dumps(memory))

        logger.debug(
            "team_memory_updated",
            team_id=team_id,
            tenant_id=tenant_id,
            topic_count=len(memory["topics"]),
            query_count=len(memory["recent_queries"]),
        )

    async def get(self, team_id: str, tenant_id: str) -> dict:
        """
        Return team memory dict.

        Returns:
            Dict with 'topics' and 'recent_queries_anonymous' keys.
            Empty lists if no data exists.
        """
        if not team_id:
            raise ValueError("team_id is required to get team memory.")
        if not tenant_id:
            raise ValueError("tenant_id is required to get team memory.")

        redis = await self._get_redis()
        key = self._redis_key(tenant_id, team_id)

        raw = await redis.get(key)
        if not raw:
            return {"topics": [], "recent_queries_anonymous": []}

        data = json.loads(raw)
        return {
            "topics": data.get("topics", []),
            "recent_queries_anonymous": data.get("recent_queries", []),
        }

    async def get_for_prompt(self, team_id: str, tenant_id: str) -> Optional[dict]:
        """
        Return memory dict for prompt injection, or None if empty/no data.

        Args:
            team_id: Team identifier.
            tenant_id: Tenant scope.

        Returns:
            Dict with 'topics' and 'recent_queries' keys, or None if empty.
        """
        if not team_id:
            raise ValueError("team_id is required for get_for_prompt.")
        if not tenant_id:
            raise ValueError("tenant_id is required for get_for_prompt.")

        redis = await self._get_redis()
        key = self._redis_key(tenant_id, team_id)

        raw = await redis.get(key)
        if not raw:
            return None

        data = json.loads(raw)

        # Return None if both lists are empty
        if not data.get("topics") and not data.get("recent_queries"):
            return None

        return data

    async def get_context(self, team_id: str, tenant_id: str) -> Optional[dict]:
        """
        Alias for get_for_prompt -- used by the orchestrator.

        The orchestrator calls team_memory.get_context(team_id=..., tenant_id=...).
        """
        return await self.get_for_prompt(team_id=team_id, tenant_id=tenant_id)

    async def clear(self, team_id: str, tenant_id: str) -> None:
        """
        Clear all team memory (team_admin or tenant_admin required -- caller enforces).

        Args:
            team_id: Team identifier.
            tenant_id: Tenant scope.
        """
        if not team_id:
            raise ValueError("team_id is required to clear team memory.")
        if not tenant_id:
            raise ValueError("tenant_id is required to clear team memory.")

        redis = await self._get_redis()
        key = self._redis_key(tenant_id, team_id)
        await redis.delete(key)

        logger.info(
            "team_memory_cleared",
            team_id=team_id,
            tenant_id=tenant_id,
        )

    def _extract_topics_from_query(self, query: str) -> list[str]:
        """
        Extract 1-3 key noun phrases from query as topic tags.

        Simple approach: lowercase words > 4 chars that are not stopwords.
        """
        stopwords = {
            "what",
            "when",
            "where",
            "which",
            "that",
            "this",
            "with",
            "from",
            "have",
            "does",
            "will",
            "should",
            "would",
            "could",
            "about",
            "into",
        }
        words = [
            w.strip("?.,!").lower() for w in query.split() if len(w.strip("?.,!")) > 4
        ]
        return [w for w in words if w not in stopwords][:3]

    def _anonymize_query(self, query: str) -> str:
        """Format query anonymously for team memory."""
        truncated = query[:QUERY_TRUNCATION]
        return f"a team member asked: {truncated}"
