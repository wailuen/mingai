"""
Search result cache (CACHE-003).

Key schema:
    mingai:{tenant_id}:search:{index_id}:{emb_hash_prefix_16}:{params_hash_8}

- emb_hash_prefix_16: first 16 chars of SHA256 of float16 binary bytes
- params_hash_8:      first 8 chars of SHA256 of json.dumps(params, sort_keys=True)

Stored value (JSON):
    {"version": N, "results": [...]}

On lookup: compares stored["version"] with current get_index_version(tenant_id, index_id).
A version mismatch is treated as a cache miss — data is stale post-document-update.

TTL: 3600s default (configurable per index via TenantConfigService or platform
     cache-ttl override).

Key is built as a raw string (not via build_redis_key) because the schema has more
than the standard 3-part pattern — following the TenantConfigService precedent.
"""
import hashlib
import json
import struct
from typing import Any

import structlog

logger = structlog.get_logger()

# Default TTL for search result cache entries (seconds)
_DEFAULT_SEARCH_CACHE_TTL = 3600


class SearchCacheService:
    """
    Tenant-scoped search result cache backed by Redis.

    Cache invalidation is version-based: each document index has a monotonically
    increasing version counter in Redis. A stored result carries the version at
    which it was written; on lookup, if the current version differs, the entry
    is discarded even if the TTL has not expired.

    This ensures that after a document is added/updated/deleted, all search
    caches for that index are immediately invalidated without requiring an
    explicit DELETE scan.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(
        self,
        tenant_id: str,
        index_id: str,
        embedding: list[float],
        params: dict,
    ) -> list[dict] | None:
        """
        Retrieve cached search results.

        Args:
            tenant_id:  Tenant UUID string.
            index_id:   Index identifier (e.g. "{tenant_id}-{agent_id}").
            embedding:  Query embedding vector (float32 list).
            params:     Search parameters dict (top_k, filters, etc.).

        Returns:
            List of result dicts on cache hit, None on miss.
        """
        try:
            from app.core.redis_client import get_redis
            from app.core.cache_utils import get_index_version

            redis = get_redis()
            key = self._build_key(tenant_id, index_id, embedding, params)
            raw = await redis.get(key)
            if raw is None:
                return None

            stored = json.loads(raw)
            stored_version = stored.get("version", -1)

            # Version check — fetch current version outside the DB session
            current_version = await get_index_version(tenant_id, index_id)
            if stored_version != current_version:
                logger.debug(
                    "search_cache_version_mismatch",
                    tenant_id=tenant_id,
                    index_id=index_id,
                    stored_version=stored_version,
                    current_version=current_version,
                )
                return None

            logger.debug(
                "search_cache_hit",
                tenant_id=tenant_id,
                index_id=index_id,
                version=current_version,
            )
            return stored["results"]
        except Exception as exc:
            logger.warning(
                "search_cache_get_error",
                tenant_id=tenant_id,
                index_id=index_id,
                error=str(exc),
            )
            return None

    async def set(
        self,
        tenant_id: str,
        index_id: str,
        embedding: list[float],
        params: dict,
        results: list[dict],
        ttl: int | None = None,
    ) -> None:
        """
        Store search results in cache with current index version.

        CACHE-005: Before storing, reads the per-index TTL from TenantConfigService
        (key: f"index_cache_ttl.{index_id}"). If configured, the stored value
        overrides the caller-supplied ttl argument. Falls back to
        _DEFAULT_SEARCH_CACHE_TTL if neither is available.

        A TTL of 0 disables caching for this index — the entry is not written.

        Args:
            tenant_id:  Tenant UUID string.
            index_id:   Index identifier.
            embedding:  Query embedding vector.
            params:     Search parameters dict.
            results:    List of result dicts to cache.
            ttl:        TTL in seconds. Overridden by per-index config when present.
        """
        try:
            from app.core.redis_client import get_redis
            from app.core.cache_utils import get_index_version
            from app.core.tenant_config_service import TenantConfigService

            # CACHE-005: per-index TTL lookup
            # Only query TenantConfigService when index_id is safe (no colons)
            safe_index_id_for_config = index_id.replace(":", "_")
            config_key = f"index_cache_ttl.{safe_index_id_for_config}"
            try:
                svc = TenantConfigService()
                per_index_ttl = await svc.get(tenant_id, config_key)
            except Exception as _exc:
                logger.warning(
                    "search_cache_per_index_ttl_lookup_failed",
                    tenant_id=tenant_id,
                    index_id=index_id,
                    error=str(_exc),
                )
                per_index_ttl = None

            if per_index_ttl is not None:
                effective_ttl = max(int(per_index_ttl), 0)
            elif ttl is not None:
                effective_ttl = ttl
            else:
                effective_ttl = _DEFAULT_SEARCH_CACHE_TTL

            # TTL of 0 disables caching for this index
            if effective_ttl == 0:
                logger.debug(
                    "search_cache_set_skipped_ttl_zero",
                    tenant_id=tenant_id,
                    index_id=index_id,
                )
                return

            redis = get_redis()
            current_version = await get_index_version(tenant_id, index_id)
            payload = json.dumps({"version": current_version, "results": results})
            key = self._build_key(tenant_id, index_id, embedding, params)
            await redis.setex(key, effective_ttl, payload)
            logger.debug(
                "search_cache_set",
                tenant_id=tenant_id,
                index_id=index_id,
                version=current_version,
                result_count=len(results),
                ttl=effective_ttl,
            )
        except Exception as exc:
            logger.warning(
                "search_cache_set_error",
                tenant_id=tenant_id,
                index_id=index_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Key construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_key(
        tenant_id: str,
        index_id: str,
        embedding: list[float],
        params: dict,
    ) -> str:
        """
        Build the raw Redis key for a search result cache entry.

        Pattern: mingai:{tenant_id}:search:{index_id}:{emb_hash16}:{params_hash8}

        - emb_hash16: first 16 chars of SHA256 of float16-serialized embedding bytes
        - params_hash8: first 8 chars of SHA256 of json.dumps(params, sort_keys=True)

        Note: We build the key directly (not via build_redis_key) because the
        schema has more parts than the standard 3-segment pattern. The
        tenant_id is validated for colons to prevent namespace injection.
        """
        if ":" in tenant_id:
            raise ValueError(
                f"tenant_id must not contain colons for Redis key construction: {tenant_id!r}"
            )
        # Sanitize index_id — replace colons with underscores to avoid namespace break
        safe_index_id = index_id.replace(":", "_")

        # Hash the float16-serialized embedding for compactness
        n = len(embedding)
        emb_bytes = struct.pack(f"{n}e", *embedding)
        emb_hash = hashlib.sha256(emb_bytes).hexdigest()[:16]

        # Hash the search parameters
        params_str = json.dumps(params, sort_keys=True)
        params_hash = hashlib.sha256(params_str.encode("utf-8")).hexdigest()[:8]

        return f"mingai:{tenant_id}:search:{safe_index_id}:{emb_hash}:{params_hash}"
