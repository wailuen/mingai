"""
CacheService (INFRA-011, INFRA-012, INFRA-013).

Redis-backed multi-tenant cache with:
- Tenant-scoped key isolation (mingai:{tenant_id}:{cache_type}:{key})
- JSON serialization with edge-case handling
- @cached decorator for async functions
- Pub/sub invalidation channel for cross-instance cache eviction
- Graceful degradation: CacheUnavailableError on Redis failure (caller decides to degrade)

Key namespace (aligns with CLAUDE.md Redis Key Namespace):
    mingai:{tenant_id}:{cache_type}:{key}

Valid cache types (allowlist — new types must be added here):
    embedding_cache, semantic_cache, glossary_terms, working_memory,
    team_memory, org_context, profile_learning, profile,
    intent_cache, query_cache

Invalidation channel: mingai:cache_invalidation
"""

import asyncio
import functools
import json
import time
from typing import Any, AsyncGenerator, Callable

import structlog

from app.core.redis_client import build_redis_key, get_redis

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INVALIDATION_CHANNEL = "mingai:cache_invalidation"

VALID_CACHE_TYPES = frozenset(
    {
        "embedding_cache",
        "semantic_cache",
        "glossary_terms",
        "working_memory",
        "team_memory",
        "org_context",
        "profile_learning",
        "profile",
        "intent_cache",
        "query_cache",
        "sse_buffer",
    }
)

# Default TTL per cache type (seconds)
DEFAULT_TTL: dict[str, int] = {
    "embedding_cache": 86_400,  # 24 h — stable, deterministic
    "semantic_cache": 3_600,  # 1 h — LLM responses can drift
    "glossary_terms": 3_600,  # 1 h — warm-up refreshes on change
    "working_memory": 86_400,  # 24 h — per-user context
    "team_memory": 86_400,  # 24 h — per-team context
    "org_context": 3_600,  # 1 h — org claims can change
    "profile_learning": 86_400,  # 24 h — profiles update infrequently
    "profile": 3_600,  # 1 h — L2 cache for profile reads
    "intent_cache": 900,  # 15 min — intent can change quickly
    "query_cache": 3_600,  # 1 h — short-lived query responses
    "sse_buffer": 300,  # 5 min — SSE Last-Event-ID replay buffer
}

# Max cached payload size (1 MB). Larger values are rejected.
MAX_PAYLOAD_BYTES = 1_048_576


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CacheUnavailableError(RuntimeError):
    """Raised when Redis is unreachable. Callers should degrade gracefully."""


class CacheTypeError(ValueError):
    """Raised when an invalid cache_type is supplied."""


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


class CacheSerializer:
    """
    JSON-based serializer for cache values.

    Supports:
    - str, int, float, bool, None, dict, list
    - datetime objects (ISO 8601 string representation)
    - Rejects payloads exceeding MAX_PAYLOAD_BYTES

    Float precision: float values are stored as-is in JSON (full precision).
    If float16 compression is needed, callers must compress before passing to set().
    """

    @staticmethod
    def serialize(value: Any) -> str:
        """
        Serialize value to JSON string.

        Raises:
            ValueError: If the serialized payload exceeds MAX_PAYLOAD_BYTES.
        """
        import datetime

        def default_encoder(obj: Any) -> Any:
            if isinstance(obj, datetime.datetime):
                return obj.isoformat()
            if isinstance(obj, datetime.date):
                return obj.isoformat()
            raise TypeError(
                f"Object of type {type(obj).__name__} is not JSON serializable"
            )

        raw = json.dumps(value, default=default_encoder, ensure_ascii=False)
        payload_bytes = raw.encode("utf-8")
        if len(payload_bytes) > MAX_PAYLOAD_BYTES:
            raise ValueError(
                f"Cache payload too large: {len(payload_bytes)} bytes "
                f"(max {MAX_PAYLOAD_BYTES} bytes). "
                "Compress the value before caching or reduce payload size."
            )
        return raw

    @staticmethod
    def deserialize(raw: str | bytes | None) -> Any:
        """
        Deserialize a JSON string from Redis back to a Python object.

        Returns None for cache-miss (None input).
        """
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)


# ---------------------------------------------------------------------------
# CacheService
# ---------------------------------------------------------------------------


class CacheService:
    """
    Multi-tenant Redis cache with tenant-scoped key isolation.

    All operations require a valid `tenant_id`. Keys follow the pattern:
        mingai:{tenant_id}:{cache_type}:{key}

    Usage::

        cache = CacheService()
        await cache.set("tenant-1", "profile", "user-42", value={"name": "Alice"}, ttl=3600)
        profile = await cache.get("tenant-1", "profile", "user-42")

    Graceful degradation: callers should catch CacheUnavailableError and
    fall through to the source-of-truth.
    """

    def __init__(self) -> None:
        self._serializer = CacheSerializer()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_cache_type(cache_type: str) -> None:
        if cache_type not in VALID_CACHE_TYPES:
            raise CacheTypeError(
                f"Invalid cache_type {cache_type!r}. "
                f"Must be one of: {sorted(VALID_CACHE_TYPES)}"
            )

    def _make_key(self, tenant_id: str, cache_type: str, key: str) -> str:
        self._validate_cache_type(cache_type)
        return build_redis_key(tenant_id, cache_type, key)

    def _default_ttl(self, cache_type: str) -> int:
        return DEFAULT_TTL.get(cache_type, 3_600)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    async def get(self, tenant_id: str, cache_type: str, key: str) -> Any:
        """
        Retrieve a cached value.

        Returns None on cache miss. Raises CacheUnavailableError if Redis
        is unreachable.
        """
        redis_key = self._make_key(tenant_id, cache_type, key)
        try:
            redis = get_redis()
            raw = await redis.get(redis_key)
            value = self._serializer.deserialize(raw)
            if value is not None:
                logger.debug(
                    "cache_hit",
                    tenant_id=tenant_id,
                    cache_type=cache_type,
                    key=key,
                )
            return value
        except (CacheTypeError, ValueError):
            raise
        except Exception as exc:
            logger.warning(
                "cache_get_failed",
                tenant_id=tenant_id,
                cache_type=cache_type,
                key=key,
                error=str(exc),
            )
            raise CacheUnavailableError(
                "Cache service temporarily unavailable"
            ) from exc

    async def set(
        self,
        tenant_id: str,
        cache_type: str,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """
        Store a value in the cache with optional TTL.

        Uses the default TTL for the cache_type if ttl is not specified.
        Raises CacheUnavailableError if Redis is unreachable.
        """
        redis_key = self._make_key(tenant_id, cache_type, key)
        effective_ttl = ttl if ttl is not None else self._default_ttl(cache_type)
        raw = self._serializer.serialize(value)
        try:
            redis = get_redis()
            await redis.setex(redis_key, effective_ttl, raw)
            logger.debug(
                "cache_set",
                tenant_id=tenant_id,
                cache_type=cache_type,
                key=key,
                ttl=effective_ttl,
            )
        except (CacheTypeError, ValueError):
            raise
        except Exception as exc:
            logger.warning(
                "cache_set_failed",
                tenant_id=tenant_id,
                cache_type=cache_type,
                key=key,
                error=str(exc),
            )
            raise CacheUnavailableError(
                "Cache service temporarily unavailable"
            ) from exc

    async def delete(self, tenant_id: str, cache_type: str, key: str) -> None:
        """Delete a specific cache entry."""
        redis_key = self._make_key(tenant_id, cache_type, key)
        try:
            redis = get_redis()
            await redis.delete(redis_key)
            logger.debug(
                "cache_deleted",
                tenant_id=tenant_id,
                cache_type=cache_type,
                key=key,
            )
        except (CacheTypeError, ValueError):
            raise
        except Exception as exc:
            logger.warning(
                "cache_delete_failed",
                tenant_id=tenant_id,
                cache_type=cache_type,
                key=key,
                error=str(exc),
            )
            raise CacheUnavailableError(
                "Cache service temporarily unavailable"
            ) from exc

    async def get_many(
        self, tenant_id: str, cache_type: str, keys: list[str]
    ) -> dict[str, Any]:
        """
        Retrieve multiple cached values in one Redis MGET command.

        Returns a dict mapping key → value. Missing keys are omitted.
        """
        if not keys:
            return {}
        self._validate_cache_type(cache_type)
        redis_keys = [build_redis_key(tenant_id, cache_type, k) for k in keys]
        try:
            redis = get_redis()
            raw_values = await redis.mget(*redis_keys)
            result: dict[str, Any] = {}
            for k, raw in zip(keys, raw_values):
                value = self._serializer.deserialize(raw)
                if value is not None:
                    result[k] = value
            return result
        except (CacheTypeError, ValueError):
            raise
        except Exception as exc:
            logger.warning(
                "cache_get_many_failed",
                tenant_id=tenant_id,
                cache_type=cache_type,
                error=str(exc),
            )
            raise CacheUnavailableError(
                "Cache service temporarily unavailable"
            ) from exc

    async def set_many(
        self,
        tenant_id: str,
        cache_type: str,
        mapping: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """
        Store multiple values using a Redis pipeline for atomicity.
        """
        if not mapping:
            return
        self._validate_cache_type(cache_type)
        effective_ttl = ttl if ttl is not None else self._default_ttl(cache_type)
        try:
            redis = get_redis()
            async with redis.pipeline(transaction=False) as pipe:
                for key, value in mapping.items():
                    redis_key = build_redis_key(tenant_id, cache_type, key)
                    raw = self._serializer.serialize(value)
                    pipe.setex(redis_key, effective_ttl, raw)
                await pipe.execute()
            logger.debug(
                "cache_set_many",
                tenant_id=tenant_id,
                cache_type=cache_type,
                count=len(mapping),
                ttl=effective_ttl,
            )
        except (CacheTypeError, ValueError):
            raise
        except Exception as exc:
            logger.warning(
                "cache_set_many_failed",
                tenant_id=tenant_id,
                cache_type=cache_type,
                error=str(exc),
            )
            raise CacheUnavailableError(
                "Cache service temporarily unavailable"
            ) from exc

    async def invalidate_pattern(
        self, tenant_id: str, cache_type: str, pattern: str = "*"
    ) -> int:
        """
        Delete all keys matching the pattern under a given tenant + cache_type.

        Returns the number of keys deleted.

        The `pattern` is a Redis glob suffix applied WITHIN the tenant+cache_type
        namespace. It may contain `*` as a wildcard, but is sandwiched between
        the fixed prefix `mingai:{tenant_id}:{cache_type}:` so it cannot escape
        to other tenant namespaces.

        Warning: uses SCAN with batch size 100 to avoid blocking Redis.
        """
        self._validate_cache_type(cache_type)
        # Build the full scan pattern. The tenant+cache_type prefix is fixed;
        # only the suffix (caller-supplied) is variable. The prefix itself is
        # validated by build_redis_key (no colons in tenant_id or cache_type).
        prefix = build_redis_key(tenant_id, cache_type, "")
        scan_pattern = prefix + pattern
        try:
            redis = get_redis()
            deleted = 0
            async for redis_key in redis.scan_iter(match=scan_pattern, count=100):
                await redis.delete(redis_key)
                deleted += 1
            logger.info(
                "cache_invalidated",
                tenant_id=tenant_id,
                cache_type=cache_type,
                pattern=pattern,
                deleted=deleted,
            )
            return deleted
        except (CacheTypeError, ValueError):
            raise
        except Exception as exc:
            logger.warning(
                "cache_invalidate_failed",
                tenant_id=tenant_id,
                cache_type=cache_type,
                pattern=pattern,
                error=str(exc),
            )
            raise CacheUnavailableError(
                "Cache service temporarily unavailable"
            ) from exc


# ---------------------------------------------------------------------------
# @cached decorator (INFRA-012)
# ---------------------------------------------------------------------------


def cached(
    cache_type: str,
    ttl: int | None = None,
    key_fn: Callable[..., str] | None = None,
) -> Callable:
    """
    Decorator for async functions that caches results in Redis.

    The decorated function MUST accept `tenant_id` as a keyword argument
    (or as the first positional argument after `self` for methods).

    Args:
        cache_type: One of VALID_CACHE_TYPES.
        ttl: Override TTL in seconds. Uses DEFAULT_TTL if omitted.
        key_fn: Optional callable that accepts the same args as the decorated
                function and returns a string cache key. Defaults to joining
                all positional args (excluding tenant_id) with ":".

    Behaviour on Redis failure:
        Logs a warning and calls through to the original function (degrades
        gracefully — never raises CacheUnavailableError to the caller).

    Example::

        @cached(cache_type="profile", ttl=3600)
        async def get_user_profile(user_id: str, tenant_id: str) -> dict:
            ...
    """
    _validate_at_decoration_time(cache_type)
    _cache_svc = CacheService()

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract tenant_id from kwargs or first positional arg
            tenant_id: str | None = kwargs.get("tenant_id")
            if tenant_id is None and args:
                # Try first positional arg (for module-level functions)
                # For class methods, args[0] is self — skip
                candidate = args[0]
                if isinstance(candidate, str):
                    tenant_id = candidate

            if not tenant_id:
                # Cannot cache without tenant_id — call through
                logger.debug(
                    "cached_no_tenant_id",
                    func=func.__qualname__,
                )
                return await func(*args, **kwargs)

            # Build cache key
            if key_fn is not None:
                cache_key = key_fn(*args, **kwargs)
            else:
                # Default: join non-tenant_id string args
                parts: list[str] = []
                for arg in args:
                    if isinstance(arg, str) and arg != tenant_id:
                        parts.append(arg)
                for k, v in kwargs.items():
                    if k != "tenant_id" and isinstance(v, str):
                        parts.append(v)
                cache_key = ":".join(parts) if parts else "default"

            # Cache lookup
            try:
                cached_value = await _cache_svc.get(tenant_id, cache_type, cache_key)
                if cached_value is not None:
                    return cached_value
            except CacheUnavailableError:
                logger.warning(
                    "cached_decorator_get_miss",
                    func=func.__qualname__,
                    cache_type=cache_type,
                )
                return await func(*args, **kwargs)

            # Call through and store result
            result = await func(*args, **kwargs)
            if result is not None:
                try:
                    await _cache_svc.set(
                        tenant_id, cache_type, cache_key, result, ttl=ttl
                    )
                except (CacheUnavailableError, ValueError):
                    # Serialization failure or Redis down — still return result
                    logger.warning(
                        "cached_decorator_set_failed",
                        func=func.__qualname__,
                        cache_type=cache_type,
                    )
            return result

        return wrapper

    return decorator


def _validate_at_decoration_time(cache_type: str) -> None:
    """Fail fast at import time if an invalid cache_type is used."""
    if cache_type not in VALID_CACHE_TYPES:
        raise CacheTypeError(
            f"@cached: invalid cache_type {cache_type!r}. "
            f"Must be one of: {sorted(VALID_CACHE_TYPES)}"
        )


# ---------------------------------------------------------------------------
# Pub/Sub invalidation (INFRA-013)
# ---------------------------------------------------------------------------


async def publish_invalidation(
    tenant_id: str,
    cache_type: str,
    pattern: str = "*",
) -> None:
    """
    Publish a cache invalidation event to all CacheService instances.

    Message format (JSON):
        {"tenant_id": "...", "cache_type": "...", "pattern": "...", "ts": 1234567890.0}

    The pattern follows Redis glob syntax applied to the key suffix after
    `mingai:{tenant_id}:{cache_type}:`.

    All subscribers will call invalidate_pattern() for the matching keys.
    """
    if cache_type not in VALID_CACHE_TYPES:
        raise CacheTypeError(f"publish_invalidation: invalid cache_type {cache_type!r}")
    message = json.dumps(
        {
            "tenant_id": tenant_id,
            "cache_type": cache_type,
            "pattern": pattern,
            "ts": time.time(),
        }
    )
    try:
        redis = get_redis()
        await redis.publish(INVALIDATION_CHANNEL, message)
        logger.debug(
            "cache_invalidation_published",
            tenant_id=tenant_id,
            cache_type=cache_type,
            pattern=pattern,
        )
    except Exception as exc:
        logger.warning(
            "cache_invalidation_publish_failed",
            tenant_id=tenant_id,
            cache_type=cache_type,
            error=str(exc),
        )
        raise CacheUnavailableError("Cache service temporarily unavailable") from exc


async def subscribe_invalidation() -> AsyncGenerator[dict, None]:
    """
    Subscribe to cache invalidation events.

    Yields parsed invalidation message dicts. The consumer is responsible
    for calling CacheService.invalidate_pattern() for the specified keys.

    Usage (in a background task)::

        async for event in subscribe_invalidation():
            cache = CacheService()
            await cache.invalidate_pattern(
                event["tenant_id"], event["cache_type"], event["pattern"]
            )
    """
    import redis.asyncio as aioredis

    redis_url = __import__("os").environ.get("REDIS_URL")
    if not redis_url:
        raise ValueError("REDIS_URL environment variable is not set.")

    # Create a dedicated connection for pub/sub (cannot share pool connection)
    pubsub_redis = aioredis.from_url(redis_url, decode_responses=True)
    pubsub = pubsub_redis.pubsub()
    try:
        await pubsub.subscribe(INVALIDATION_CHANNEL)
        logger.info("cache_invalidation_subscribed", channel=INVALIDATION_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    event = json.loads(message["data"])
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "cache_invalidation_bad_message",
                        error=str(exc),
                        data_length=len(str(message.get("data", ""))),
                    )
                    continue

                # Validate required fields and cache_type allowlist before yielding
                required = ("tenant_id", "cache_type", "pattern")
                if not all(k in event for k in required):
                    logger.warning(
                        "cache_invalidation_missing_fields",
                        missing=[k for k in required if k not in event],
                    )
                    continue
                if event["cache_type"] not in VALID_CACHE_TYPES:
                    logger.warning(
                        "cache_invalidation_invalid_type",
                        cache_type=event["cache_type"],
                    )
                    continue

                yield event
    finally:
        await pubsub.unsubscribe(INVALIDATION_CHANNEL)
        await pubsub_redis.close()
        logger.info("cache_invalidation_unsubscribed")
