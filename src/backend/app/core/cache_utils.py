"""
Cache utility functions shared across caching modules.

Provides:
- normalize_query(query) — canonical form for cache key derivation
- increment_index_version(tenant_id, index_id) — INCR version counter
- get_index_version(tenant_id, index_id) — GET current version counter

Version keys are raw Redis strings bypassing build_redis_key (multi-part schema).
They use the pattern: mingai:{tenant_id}:version:{index_id}
"""
import re
import string

import structlog

logger = structlog.get_logger()

# Punctuation to strip during normalization (preserve apostrophes for
# contractions: "don't", "it's" etc.)
_PUNCT_TO_STRIP = re.compile(r"[^\w\s']", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_query(query: str) -> str:
    """
    Normalize a query string into a canonical form for cache key derivation.

    Steps:
    1. Lowercase
    2. Strip leading/trailing whitespace
    3. Remove punctuation except apostrophes
    4. Collapse internal whitespace runs to a single space

    Args:
        query: Raw user query string.

    Returns:
        Normalized string. Returns empty string for None or blank input.
    """
    if not query:
        return ""
    text = query.lower().strip()
    text = _PUNCT_TO_STRIP.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


async def increment_index_version(tenant_id: str, index_id: str) -> int:
    """
    INCR index version counter in Redis.

    Returns the new counter value after increment.
    The key has no TTL — it persists indefinitely (version counters must never
    expire silently or stale cache entries would pass the version check).

    Key pattern: mingai:{tenant_id}:version:{index_id}

    Args:
        tenant_id: Tenant UUID string. Must not contain colons.
        index_id:  Index identifier (e.g. integration_id or "global").
                   Must not contain colons.

    Returns:
        Integer — new counter value (1 on first call).

    Raises:
        ValueError: If tenant_id or index_id contain colons.
    """
    if ":" in tenant_id:
        raise ValueError(f"tenant_id must not contain colons: {tenant_id!r}")
    if ":" in index_id:
        raise ValueError(f"index_id must not contain colons: {index_id!r}")

    from app.core.redis_client import get_redis

    redis = get_redis()
    key = f"mingai:{tenant_id}:version:{index_id}"
    new_val = await redis.incr(key)
    logger.debug(
        "index_version_incremented",
        tenant_id=tenant_id,
        index_id=index_id,
        new_version=new_val,
    )
    return int(new_val)


async def get_index_version(tenant_id: str, index_id: str) -> int:
    """
    GET current index version counter value.

    Returns 0 if the key has never been set (no documents indexed yet,
    version check will treat as version 0).

    Key pattern: mingai:{tenant_id}:version:{index_id}

    Args:
        tenant_id: Tenant UUID string. Must not contain colons.
        index_id:  Index identifier. Must not contain colons.

    Returns:
        Integer version (0 if key absent).
    """
    if ":" in tenant_id:
        raise ValueError(f"tenant_id must not contain colons: {tenant_id!r}")
    if ":" in index_id:
        raise ValueError(f"index_id must not contain colons: {index_id!r}")

    from app.core.redis_client import get_redis

    redis = get_redis()
    key = f"mingai:{tenant_id}:version:{index_id}"
    val = await redis.get(key)
    return int(val) if val else 0
