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
import os

import re

import structlog
from cachetools import LRUCache
from sqlalchemy import text

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

    async def get_profile_context(self, user_id: str, tenant_id: str) -> dict | None:
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

        On Redis cache miss (INCR returns 1), seeds counter from PostgreSQL
        checkpoint to recover position after Redis restart.

        On trigger (count % threshold == 0), checkpoints cumulative query
        count to PostgreSQL for durability.

        Args:
            user_id: User who queried.
            tenant_id: Tenant scope.
            agent_id: Agent that handled the query (Phase 1: not used in counter).
        """
        counter_key = f"mingai:{tenant_id}:profile_learning:query_count:{user_id}"
        redis = get_redis()

        count = await redis.incr(counter_key)
        await redis.expire(counter_key, COUNTER_TTL_SECONDS)

        # INFRA-032: Seed from PostgreSQL on Redis cache miss
        if count == 1:
            await self._seed_counter_from_db(user_id, tenant_id, redis, counter_key)
            # Re-read the counter after seeding (seed may have updated it)
            raw_count = await redis.get(counter_key)
            if raw_count is not None:
                count = int(raw_count)

        if count % LEARN_TRIGGER_THRESHOLD == 0:
            logger.info(
                "profile_learn_triggered",
                user_id=user_id,
                tenant_id=tenant_id,
                query_count=count,
            )
            await redis.set(counter_key, 0)
            # INFRA-032: Checkpoint cumulative count to PostgreSQL
            await self._checkpoint_counter_to_db(user_id, tenant_id)
            await self._run_profile_extraction(user_id, tenant_id, agent_id)

    async def clear_l1_cache(self, user_id: str) -> None:
        """
        GDPR: Clear all in-process L1 cache entries for a user.

        Removes entries across all tenants for this user.
        """
        keys_to_delete = [k for k in _profile_l1_cache if k.endswith(f":{user_id}")]
        for k in keys_to_delete:
            del _profile_l1_cache[k]

        logger.info(
            "profile_l1_cache_cleared",
            user_id=user_id,
            entries_removed=len(keys_to_delete),
        )

    async def _checkpoint_counter_to_db(self, user_id: str, tenant_id: str) -> None:
        """
        Checkpoint query count to PostgreSQL for Redis restart recovery.

        Uses upsert to increment user_profiles.query_count by LEARN_TRIGGER_THRESHOLD.
        Fire-and-forget: failures are logged and suppressed.
        """
        if self._db is None:
            return

        try:
            await self._db.execute(
                text(
                    "INSERT INTO user_profiles (user_id, tenant_id, query_count) "
                    "VALUES (:user_id, :tenant_id, :threshold) "
                    "ON CONFLICT (user_id, tenant_id) DO UPDATE "
                    "SET query_count = user_profiles.query_count + :threshold"
                ),
                {
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "threshold": LEARN_TRIGGER_THRESHOLD,
                },
            )
            await self._db.commit()
            logger.info(
                "counter_checkpoint_saved",
                user_id=user_id,
                tenant_id=tenant_id,
                increment=LEARN_TRIGGER_THRESHOLD,
            )
        except Exception as exc:
            logger.warning(
                "counter_checkpoint_failed",
                user_id=user_id,
                tenant_id=tenant_id,
                error=str(exc),
            )

    async def _seed_counter_from_db(
        self, user_id: str, tenant_id: str, redis, counter_key: str
    ) -> None:
        """
        Seed Redis counter from PostgreSQL checkpoint after cache miss.

        If PostgreSQL has a checkpoint, set Redis counter to (checkpoint % threshold)
        so the next trigger fires at the correct query count.
        """
        if self._db is None:
            return

        try:
            result = await self._db.execute(
                text(
                    "SELECT query_count FROM user_profiles "
                    "WHERE user_id = :user_id AND tenant_id = :tenant_id"
                ),
                {"user_id": user_id, "tenant_id": tenant_id},
            )
            row = result.fetchone()
            if row and row[0]:
                checkpoint = int(row[0])
                modular_position = checkpoint % LEARN_TRIGGER_THRESHOLD
                if modular_position > 0:
                    await redis.set(counter_key, modular_position)
                    logger.info(
                        "counter_seeded_from_db",
                        user_id=user_id,
                        tenant_id=tenant_id,
                        checkpoint=checkpoint,
                        modular_position=modular_position,
                    )
        except Exception as exc:
            logger.warning(
                "counter_seed_from_db_failed",
                user_id=user_id,
                tenant_id=tenant_id,
                error=str(exc),
            )

    async def _load_from_db(self, user_id: str, tenant_id: str) -> dict | None:
        """
        Load user profile from PostgreSQL (L3).

        Queries the user_profiles table with RLS tenant isolation.
        """
        if self._db is None:
            return None

        try:
            result = await self._db.execute(
                text(
                    "SELECT technical_level, communication_style, interests, "
                    "expertise_areas, common_tasks, profile_learning_enabled "
                    "FROM user_profiles "
                    "WHERE user_id = :user_id AND tenant_id = :tenant_id"
                ),
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

        if self._db is None:
            logger.warning(
                "profile_extraction_skipped",
                reason="No database session configured",
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return

        # Fetch last 10 conversations for this user (user queries only — data minimization)
        try:
            conv_result = await self._db.execute(
                text(
                    "SELECT id FROM conversations "
                    "WHERE user_id = :user_id AND tenant_id = :tenant_id "
                    "ORDER BY created_at DESC LIMIT 10"
                ),
                {"user_id": user_id, "tenant_id": tenant_id},
            )
            conversation_ids = [row[0] for row in conv_result.fetchall()]
        except Exception as exc:
            logger.warning(
                "profile_extraction_conv_fetch_failed",
                user_id=user_id,
                tenant_id=tenant_id,
                error=str(exc),
            )
            return

        if not conversation_ids:
            logger.info(
                "profile_extraction_no_conversations",
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return

        # Fetch user messages only (data minimization: never send AI responses to LLM)
        user_queries: list[str] = []
        for conv_id in conversation_ids:
            try:
                msg_result = await self._db.execute(
                    text(
                        "SELECT content FROM messages "
                        "WHERE conversation_id = :conv_id AND role = 'user' "
                        "ORDER BY created_at ASC"
                    ),
                    {"conv_id": conv_id},
                )
                for row in msg_result.fetchall():
                    if row[0]:
                        user_queries.append(row[0][:500])  # Truncate long messages
            except Exception as exc:
                logger.warning(
                    "profile_extraction_msg_fetch_failed",
                    conv_id=conv_id,
                    error=str(exc),
                )

        if not user_queries:
            return

        # Call intent model with EXTRACTION_PROMPT
        extracted = await self._call_intent_model(user_queries, tenant_id)
        if not extracted:
            return

        # Merge extracted attributes with existing profile
        await self._merge_and_persist_profile(user_id, tenant_id, extracted)

    async def _call_intent_model(
        self, user_queries: list[str], tenant_id: str
    ) -> dict | None:
        """
        Call the intent model to extract profile attributes from user queries.

        Model read from INTENT_MODEL env var (falls back to PRIMARY_MODEL).
        Returns parsed JSON dict or None if extraction fails.
        """
        cloud = os.environ.get("CLOUD_PROVIDER", "")
        model = os.environ.get("INTENT_MODEL") or os.environ.get("PRIMARY_MODEL")

        if not cloud or not model:
            logger.warning(
                "profile_extraction_llm_not_configured",
                tenant_id=tenant_id,
                cloud=cloud,
                model=model,
            )
            return None

        # C-1 fix: sanitize user queries before including in LLM prompt.
        # Strip known prompt injection patterns and limit per-query length.
        # This prevents malicious queries from hijacking the extraction LLM.
        _INJECTION_RE = re.compile(
            r"(ignore\s+(all\s+)?previous\s+instructions?|"
            r"forget\s+all\s+prior\s+rules?|"
            r"you\s+are\s+now|"
            r"override\s+previous\s+context|"
            r"SYSTEM\s*:|"
            r"###\s*New\s+Instructions|"
            r"<\|endoftext\|>|"
            r"<script[^>]*>|"
            r"</script>)",
            re.IGNORECASE,
        )

        def _sanitize_query(q: str) -> str:
            sanitized = _INJECTION_RE.sub("[REDACTED]", q)
            return sanitized[:300]  # Per-query character cap

        sanitized_queries = [_sanitize_query(q) for q in user_queries[:30]]
        # Additional token budget: cap total at 8000 chars
        total = 0
        capped_queries: list[str] = []
        for q in sanitized_queries:
            if total + len(q) > 8000:
                break
            capped_queries.append(q)
            total += len(q)

        queries_text = "\n".join(f"- {q}" for q in capped_queries)
        prompt = f"{EXTRACTION_PROMPT}\n\nUser queries:\n{queries_text}"

        try:
            if cloud == "azure":
                from openai import AsyncAzureOpenAI

                api_key = os.environ.get("AZURE_PLATFORM_OPENAI_API_KEY", "")
                endpoint = os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT", "")
                if not api_key or not endpoint:
                    logger.warning(
                        "profile_extraction_azure_not_configured",
                        tenant_id=tenant_id,
                    )
                    return None
                client = AsyncAzureOpenAI(
                    api_key=api_key,
                    azure_endpoint=endpoint,
                    api_version="2024-02-01",
                )
            else:
                from openai import AsyncOpenAI

                api_key = os.environ.get("OPENAI_API_KEY", "")
                if not api_key:
                    logger.warning(
                        "profile_extraction_openai_not_configured",
                        tenant_id=tenant_id,
                    )
                    return None
                client = AsyncOpenAI(api_key=api_key)

            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=512,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                return None

            raw_extracted = json.loads(content)

            # C-2 fix: strict schema validation — only whitelist known fields,
            # validate enum values, and cap string lengths in list items.
            _VALID_TECHNICAL_LEVELS = {"beginner", "intermediate", "expert"}
            _VALID_COMM_STYLES = {"concise", "detailed", "formal", "casual"}
            _ALLOWED_KEYS = {
                "technical_level",
                "communication_style",
                "interests",
                "expertise_areas",
                "common_tasks",
            }
            _MAX_ITEM_LEN = 100

            def _sanitize_str_list(raw: object) -> list[str]:
                if not isinstance(raw, list):
                    return []
                result = []
                for item in raw:
                    if isinstance(item, str) and item.strip():
                        result.append(item.strip()[:_MAX_ITEM_LEN])
                return result

            extracted: dict = {}
            technical_level = raw_extracted.get("technical_level")
            if (
                isinstance(technical_level, str)
                and technical_level in _VALID_TECHNICAL_LEVELS
            ):
                extracted["technical_level"] = technical_level

            comm_style = raw_extracted.get("communication_style")
            if isinstance(comm_style, str) and comm_style in _VALID_COMM_STYLES:
                extracted["communication_style"] = comm_style

            extracted["interests"] = _sanitize_str_list(raw_extracted.get("interests"))
            extracted["expertise_areas"] = _sanitize_str_list(
                raw_extracted.get("expertise_areas")
            )
            extracted["common_tasks"] = _sanitize_str_list(
                raw_extracted.get("common_tasks")
            )

            logger.info(
                "profile_extraction_success",
                tenant_id=tenant_id,
                fields_extracted=list(extracted.keys()),
            )
            return extracted

        except Exception as exc:
            logger.warning(
                "profile_extraction_llm_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )
            return None

    async def _merge_and_persist_profile(
        self, user_id: str, tenant_id: str, extracted: dict
    ) -> None:
        """
        Merge extracted profile attributes with the existing profile and persist to DB.

        Merge strategy:
        - interests: union-deduplicate, cap at 20
        - expertise_areas: union-deduplicate, cap at 10
        - common_tasks: union-deduplicate, cap at 15
        - technical_level: most-recent-wins
        - communication_style: most-recent-wins

        After update, invalidates L1 and L2 caches.
        """
        existing = await self._load_from_db(user_id, tenant_id)
        if existing is None:
            existing = {
                "technical_level": None,
                "communication_style": None,
                "interests": [],
                "expertise_areas": [],
                "common_tasks": [],
                "profile_learning_enabled": True,
            }

        # Merge list fields (union-deduplicate with caps)
        def _merge_list(old: list, new: list, cap: int) -> list:
            seen = set()
            merged = []
            for item in new + old:  # New items take priority (appear first)
                normalized = str(item).lower().strip()
                if normalized not in seen and normalized:
                    seen.add(normalized)
                    merged.append(item)
            return merged[:cap]

        merged_interests = _merge_list(
            existing.get("interests") or [],
            extracted.get("interests") or [],
            cap=20,
        )
        merged_expertise = _merge_list(
            existing.get("expertise_areas") or [],
            extracted.get("expertise_areas") or [],
            cap=10,
        )
        merged_tasks = _merge_list(
            existing.get("common_tasks") or [],
            extracted.get("common_tasks") or [],
            cap=15,
        )

        # Scalar fields: most-recent-wins (use extracted if present)
        new_technical_level = extracted.get("technical_level") or existing.get(
            "technical_level"
        )
        new_communication_style = extracted.get("communication_style") or existing.get(
            "communication_style"
        )

        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)

        try:
            await self._db.execute(
                text(
                    "INSERT INTO user_profiles "
                    "(user_id, tenant_id, technical_level, communication_style, "
                    "interests, expertise_areas, common_tasks, updated_at) "
                    "VALUES (:user_id, :tenant_id, :technical_level, :communication_style, "
                    "CAST(:interests AS jsonb), CAST(:expertise_areas AS jsonb), "
                    "CAST(:common_tasks AS jsonb), :updated_at) "
                    "ON CONFLICT (user_id, tenant_id) DO UPDATE SET "
                    "technical_level = EXCLUDED.technical_level, "
                    "communication_style = EXCLUDED.communication_style, "
                    "interests = EXCLUDED.interests, "
                    "expertise_areas = EXCLUDED.expertise_areas, "
                    "common_tasks = EXCLUDED.common_tasks, "
                    "updated_at = EXCLUDED.updated_at"
                ),
                {
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "technical_level": new_technical_level,
                    "communication_style": new_communication_style,
                    "interests": json.dumps(merged_interests),
                    "expertise_areas": json.dumps(merged_expertise),
                    "common_tasks": json.dumps(merged_tasks),
                    "updated_at": now,
                },
            )
            await self._db.commit()

            # Invalidate L1 and L2 caches so next read gets fresh data
            l1_key = f"{tenant_id}:{user_id}"
            if l1_key in _profile_l1_cache:
                del _profile_l1_cache[l1_key]

            l2_key = f"mingai:{tenant_id}:profile_learning:profile:{user_id}"
            redis = get_redis()
            await redis.delete(l2_key)

            logger.info(
                "profile_persisted",
                user_id=user_id,
                tenant_id=tenant_id,
                interests_count=len(merged_interests),
                expertise_count=len(merged_expertise),
                tasks_count=len(merged_tasks),
            )

        except Exception as exc:
            logger.error(
                "profile_persist_failed",
                user_id=user_id,
                tenant_id=tenant_id,
                error=str(exc),
            )
