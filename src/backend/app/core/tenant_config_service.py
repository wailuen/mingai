"""
TenantConfigService (P2LLM-008).

Three-tier config lookup for per-tenant settings:
    1. Redis cache:   mingai:{tenant_id}:config:{key}  (TTL 900s)
    2. PostgreSQL:    tenant_configs table, JSONB config_data column
    3. Env fallback:  os.environ.get(key.upper())

Write path:
    1. Write to tenant_configs JSONB
    2. DEL Redis cache key

This service is read-only for env fallback — env vars cannot be overwritten.
All Redis keys are raw strings (not through CacheService type system) to
allow the config key type to span all config sub-keys without registering
each as a VALID_CACHE_TYPES entry.
"""
import json
import os
from typing import Any

import structlog

logger = structlog.get_logger()

_CONFIG_TTL_SECONDS = 900  # 15 minutes


class TenantConfigService:
    """
    Three-tier config resolver for tenant-scoped settings.

    Usage::

        svc = TenantConfigService()
        value = await svc.get(tenant_id, "model_source")
        await svc.set(tenant_id, "model_source", "byollm")

    The Redis key format is:  mingai:{tenant_id}:config:{key}
    (The colon validation in build_redis_key forbids colons inside parts,
    so we use raw string construction here where key is guaranteed to be
    a simple word like 'llm_config', 'model_source', etc.)
    """

    @staticmethod
    def _redis_key(tenant_id: str, key: str) -> str:
        """
        Build the raw Redis key for a tenant config entry.

        Does NOT use build_redis_key() because that function forbids colons
        in any part, and we need to support arbitrary key names that may
        contain underscores but not colons.

        Format: mingai:{tenant_id}:config:{key}
        """
        if ":" in tenant_id:
            raise ValueError(f"tenant_id must not contain colons: {tenant_id!r}")
        if ":" in key:
            raise ValueError(f"config key must not contain colons: {key!r}")
        return f"mingai:{tenant_id}:config:{key}"

    async def get(self, tenant_id: str, key: str) -> Any:
        """
        Retrieve a config value using the three-tier lookup.

        Args:
            tenant_id: UUID string of the tenant.
            key:       Config key (e.g. 'model_source', 'llm_config').

        Returns:
            The config value, or None if not found in any tier.
        """
        # Tier 1: Redis cache
        try:
            from app.core.redis_client import get_redis

            redis = get_redis()
            redis_key = self._redis_key(tenant_id, key)
            raw = await redis.get(redis_key)
            if raw is not None:
                logger.debug("tenant_config_cache_hit", tenant_id=tenant_id, key=key)
                return json.loads(raw)
        except Exception as exc:
            logger.warning(
                "tenant_config_redis_get_failed",
                tenant_id=tenant_id,
                key=key,
                error=str(exc),
            )

        # Tier 2: PostgreSQL
        config_data = None
        try:
            from app.core.session import async_session_factory

            # Keep the DB session strictly for the SQL query — close it before
            # any Redis I/O so asyncpg's connection is returned to the pool
            # before any other async operations.
            async with async_session_factory() as session:
                from sqlalchemy import text

                result = await session.execute(
                    text(
                        "SELECT config_data FROM tenant_configs "
                        "WHERE tenant_id = :tid AND config_type = :key LIMIT 1"
                    ),
                    {"tid": tenant_id, "key": key},
                )
                row = result.fetchone()
                if row is not None:
                    raw_config = row[0]
                    config_data = (
                        json.loads(raw_config)
                        if isinstance(raw_config, str)
                        else raw_config
                    )
        except Exception as exc:
            logger.warning(
                "tenant_config_db_get_failed",
                tenant_id=tenant_id,
                key=key,
                error=str(exc),
            )

        if config_data is not None:
            # Populate Redis cache AFTER the DB session is fully closed
            try:
                from app.core.redis_client import get_redis

                redis = get_redis()
                redis_key = self._redis_key(tenant_id, key)
                await redis.setex(
                    redis_key,
                    _CONFIG_TTL_SECONDS,
                    json.dumps(config_data),
                )
            except Exception:
                pass  # Cache population is best-effort

            logger.debug("tenant_config_db_hit", tenant_id=tenant_id, key=key)
            return config_data

        # Tier 3: Environment variable fallback
        env_val = os.environ.get(key.upper())
        if env_val is not None:
            logger.debug("tenant_config_env_fallback", tenant_id=tenant_id, key=key)
            return env_val

        return None

    async def set(self, tenant_id: str, key: str, value: Any) -> None:
        """
        Write a config value to PostgreSQL and invalidate the Redis cache.

        Args:
            tenant_id: UUID string of the tenant.
            key:       Config key (stored as config_type in tenant_configs).
            value:     Config value (must be JSON-serializable).
        """
        import uuid as _uuid

        from sqlalchemy import text

        from app.core.session import async_session_factory

        serialized = json.dumps(value)

        async with async_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
                    "VALUES (:id, :tid, :key, CAST(:data AS jsonb)) "
                    "ON CONFLICT (tenant_id, config_type) DO UPDATE "
                    "SET config_data = CAST(:data AS jsonb)"
                ),
                {
                    "id": str(_uuid.uuid4()),
                    "tid": tenant_id,
                    "key": key,
                    "data": serialized,
                },
            )
            await session.commit()

        # Invalidate Redis cache
        try:
            from app.core.redis_client import get_redis

            redis = get_redis()
            redis_key = self._redis_key(tenant_id, key)
            await redis.delete(redis_key)
            logger.debug(
                "tenant_config_cache_invalidated", tenant_id=tenant_id, key=key
            )
        except Exception as exc:
            logger.warning(
                "tenant_config_cache_invalidate_failed",
                tenant_id=tenant_id,
                key=key,
                error=str(exc),
            )

        logger.info("tenant_config_set", tenant_id=tenant_id, key=key)
