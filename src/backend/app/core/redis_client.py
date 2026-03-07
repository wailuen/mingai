"""
Redis connection management.

All Redis keys MUST use the namespace pattern:
    mingai:{tenant_id}:{key_type}:{...}

NEVER create tenant-unscoped Redis keys for user data.
"""
import os
import re
import urllib.parse
from typing import Optional

import structlog

logger = structlog.get_logger()

_redis_pool: Optional[object] = None

# Allowlist for structured key segments (tenant_id and key_type only).
# Key parts (suffix) allow colons so compound sub-keys still work, but
# tenant_id and key_type must never contain colons — that would break
# the namespace boundary and allow cross-tenant key collision.
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.@/-]+$")


def build_redis_key(tenant_id: str, key_type: str, *parts: str) -> str:
    """
    Build a tenant-scoped Redis key.

    Pattern: mingai:{tenant_id}:{key_type}:{...}

    Security rules:
    - tenant_id and key_type MUST NOT contain colons (namespace injection prevention).
    - tenant_id MUST be non-empty.
    - key_type MUST be non-empty.

    Raises ValueError if any constraint is violated.
    """
    if not tenant_id:
        raise ValueError(
            "tenant_id is required for Redis key construction. "
            "NEVER create tenant-unscoped Redis keys for user data."
        )
    if not key_type:
        raise ValueError("key_type is required for Redis key construction.")

    # Prevent colon injection in structural segments — a colon in tenant_id
    # or key_type would break the namespace boundary between tenants.
    if ":" in tenant_id:
        raise ValueError(
            f"tenant_id must not contain colons to prevent namespace injection: {tenant_id!r}"
        )
    if ":" in key_type:
        raise ValueError(
            f"key_type must not contain colons to prevent namespace injection: {key_type!r}"
        )

    key_parts = ["mingai", tenant_id, key_type] + list(parts)
    return ":".join(key_parts)


def get_redis():
    """
    Get Redis connection from pool (synchronous - returns pool object).

    The pool itself supports async operations (get, set, etc.).
    Connection URL from REDIS_URL env var - never hardcode.
    """
    global _redis_pool

    if _redis_pool is None:
        import redis.asyncio as aioredis

        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            raise ValueError(
                "REDIS_URL environment variable is not set. "
                "Set it in .env (e.g., redis://localhost:6379/0)"
            )

        _redis_pool = aioredis.from_url(
            redis_url,
            max_connections=50,
            socket_timeout=5,
            retry_on_timeout=True,
            decode_responses=True,
        )
        parsed = urllib.parse.urlparse(redis_url)
        logger.info(
            "redis_pool_created", host=parsed.hostname, port=parsed.port, db=parsed.path
        )

    return _redis_pool


async def close_redis():
    """Close Redis connection pool on shutdown."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None
        logger.info("redis_pool_closed")
