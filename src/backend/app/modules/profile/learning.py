"""
ProfileLearningService (AI-001 to AI-010).

3-tier cache architecture:
  L1: In-process LRU cache (1000 entries, instant)
  L2: Redis (TTL 1 hour, shared across processes)
  L3: PostgreSQL (persistent, source of truth)

Profile extraction triggered every 10 queries via Redis counter.
Model read from INTENT_MODEL env var - NEVER hardcoded.
"""
import json

import structlog
from cachetools import LRUCache

from app.core.redis_client import get_redis

logger = structlog.get_logger()

# L1: In-process LRU cache (shared across requests in same process)
_profile_l1_cache: LRUCache = LRUCache(maxsize=1000)

# Profile extraction trigger threshold (every N queries)
LEARN_TRIGGER_THRESHOLD = 10

# Redis TTLs
PROFILE_L2_TTL_SECONDS = 3600  # 1 hour
COUNTER_TTL_SECONDS = 2592000  # 30 days

# Profile extraction prompt sent to intent model
EXTRACTION_PROMPT = (
    "Analyze the following user queries and extract profile attributes. "
    "Return JSON with these fields (only include fields you can confidently infer):\n"
    "- technical_level: beginner | intermediate | expert\n"
    "- communication_style: concise | detailed | formal | casual\n"
    "- interests: list of topic strings\n"
    "- expertise_areas: list of domain strings\n"
    "- common_tasks: list of task description strings\n"
    "- memory_notes: list of notable preferences or facts\n\n"
    "Return {} if nothing can be confidently extracted. "
    "Only include fields with high confidence. "
    "Return valid JSON only, no explanation."
)


class ProfileLearningService:
    """
    Manages user profile learning with 3-tier caching.

    Triggers profile extraction every LEARN_TRIGGER_THRESHOLD queries.
    Uses L1 (in-process) -> L2 (Redis) -> L3 (PostgreSQL) cache hierarchy.
    """

    def __init__(self, db_session=None):
        """
        Initialize with optional database session.

        Args:
            db_session: Async database session for L3 queries.
        """
        self._db = db_session

    async def get_profile_context(
        self, user_id: str, tenant_id: str
    ) -> dict | None:
        """
        Get user profile context for system prompt injection.

        Checks L1 (in-process) -> L2 (Redis) -> L3 (PostgreSQL).
        Budget: 200 tokens.

        Args:
            user_id: The user to get profile for.
            tenant_id: Tenant scope for isolation.

        Returns:
            Profile dict or None if no profile exists.
        """
        l1_key = f"{tenant_id}:{user_id}"

        # L1: In-process LRU cache (fastest)
        if l1_key in _profile_l1_cache:
            logger.debug(
                "profile_l1_hit",
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return _profile_l1_cache[l1_key]

        # L2: Redis
        l2_key = f"mingai:{tenant_id}:profile_learning:profile:{user_id}"
        redis = get_redis()
        cached = await redis.get(l2_key)
        if cached:
            profile = json.loads(cached)
            _profile_l1_cache[l1_key] = profile
            logger.debug(
                "profile_l2_hit",
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return profile

        # L3: PostgreSQL
        profile = await self._load_from_db(user_id, tenant_id)
        if profile:
            # Populate L2 and L1 caches
            await redis.setex(l2_key, PROFILE_L2_TTL_SECONDS, json.dumps(profile))
            _profile_l1_cache[l1_key] = profile
            logger.debug(
                "profile_l3_hit",
                user_id=user_id,
                tenant_id=tenant_id,
            )

        return profile

    async def on_query_completed(
        self,
        user_id: str,
        tenant_id: str,
        agent_id: str,
    ) -> None:
        """
        Called after every chat query. Increments counter, triggers
        profile extraction at every LEARN_TRIGGER_THRESHOLD queries.

        Args:
            user_id: User who queried.
            tenant_id: Tenant scope.
            agent_id: Agent that handled the query (Phase 1: not used in counter).
        """
        counter_key = (
            f"mingai:{tenant_id}:profile_learning:query_count:{user_id}"
        )
        redis = get_redis()

        count = await redis.incr(counter_key)
        await redis.expire(counter_key, COUNTER_TTL_SECONDS)

        if count % LEARN_TRIGGER_THRESHOLD == 0:
            logger.info(
                "profile_learn_triggered",
                user_id=user_id,
                tenant_id=tenant_id,
                query_count=count,
            )
            await redis.set(counter_key, 0)
            await self._run_profile_extraction(user_id, tenant_id, agent_id)

    async def clear_l1_cache(self, user_id: str) -> None:
        """
        GDPR: Clear all in-process L1 cache entries for a user.

        Removes entries across all tenants for this user.
        """
        keys_to_delete = [
            k for k in _profile_l1_cache if k.endswith(f":{user_id}")
        ]
        for k in keys_to_delete:
            del _profile_l1_cache[k]

        logger.info(
            "profile_l1_cache_cleared",
            user_id=user_id,
            entries_removed=len(keys_to_delete),
        )

    async def _load_from_db(
        self, user_id: str, tenant_id: str
    ) -> dict | None:
        """
        Load user profile from PostgreSQL (L3).

        Queries the user_profiles table with RLS tenant isolation.
        """
        if self._db is None:
            return None

        try:
            result = await self._db.execute(
                "SELECT technical_level, communication_style, interests, "
                "expertise_areas, common_tasks, profile_learning_enabled "
                "FROM user_profiles "
                "WHERE user_id = :user_id AND tenant_id = :tenant_id",
                {"user_id": user_id, "tenant_id": tenant_id},
            )
            row = result.fetchone()
            if row is None:
                return None

            return {
                "technical_level": row[0],
                "communication_style": row[1],
                "interests": row[2] or [],
                "expertise_areas": row[3] or [],
                "common_tasks": row[4] or [],
                "profile_learning_enabled": row[5],
            }
        except Exception as e:
            logger.error(
                "profile_db_load_error",
                user_id=user_id,
                tenant_id=tenant_id,
                error=str(e),
            )
            return None

    async def _run_profile_extraction(
        self, user_id: str, tenant_id: str, agent_id: str
    ) -> None:
        """
        Run profile extraction using the intent model.

        Fetches last 10 conversations, sends user queries to
        the intent model with EXTRACTION_PROMPT, and stores results.
        """
        logger.info(
            "profile_extraction_started",
            user_id=user_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
        # Phase 1: extraction logic will connect to real LLM
        # and persist extracted attributes to user_profiles table.
        # The counter reset and trigger mechanism are fully implemented.
