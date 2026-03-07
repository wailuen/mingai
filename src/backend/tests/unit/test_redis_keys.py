"""
TEST-006: Cache key builder - unit tests

Validates that all Redis keys follow the namespace pattern:
    mingai:{tenant_id}:{key_type}:{...}

No user data may use tenant-unscoped Redis keys.
"""
import pytest


class TestRedisKeyBuilder:
    """TEST-006: Redis key namespace enforcement."""

    def test_basic_key_construction(self):
        """Basic key follows mingai:{tenant_id}:{key_type}:{parts} pattern."""
        from app.core.redis_client import build_redis_key

        key = build_redis_key("tenant-abc", "working_memory", "user-1", "agent-1")
        assert key == "mingai:tenant-abc:working_memory:user-1:agent-1"

    def test_key_starts_with_mingai_prefix(self):
        """All keys must start with 'mingai:' prefix."""
        from app.core.redis_client import build_redis_key

        key = build_redis_key("t1", "profile_learning", "profile", "u1")
        assert key.startswith("mingai:")

    def test_key_includes_tenant_id(self):
        """All keys must include tenant_id after 'mingai:' prefix."""
        from app.core.redis_client import build_redis_key

        key = build_redis_key("tenant-xyz", "org_context", "user-1")
        parts = key.split(":")
        assert parts[0] == "mingai"
        assert parts[1] == "tenant-xyz"

    def test_empty_tenant_id_raises_error(self):
        """Empty tenant_id must raise error (prevents unscoped keys)."""
        from app.core.redis_client import build_redis_key

        with pytest.raises(ValueError, match="tenant_id"):
            build_redis_key("", "working_memory", "user-1")

    def test_none_tenant_id_raises_error(self):
        """None tenant_id must raise error."""
        from app.core.redis_client import build_redis_key

        with pytest.raises(ValueError, match="tenant_id"):
            build_redis_key(None, "working_memory", "user-1")

    def test_empty_key_type_raises_error(self):
        """Empty key_type must raise error."""
        from app.core.redis_client import build_redis_key

        with pytest.raises(ValueError, match="key_type"):
            build_redis_key("tenant-1", "", "user-1")

    def test_working_memory_key_pattern(self):
        """Working memory key: mingai:{tenant_id}:working_memory:{user_id}:{agent_id}."""
        from app.core.redis_client import build_redis_key

        key = build_redis_key("t1", "working_memory", "u1", "a1")
        assert key == "mingai:t1:working_memory:u1:a1"

    def test_profile_learning_query_count_key(self):
        """Query count key: mingai:{tenant_id}:profile_learning:query_count:{user_id}."""
        from app.core.redis_client import build_redis_key

        key = build_redis_key("t1", "profile_learning", "query_count", "u1")
        assert key == "mingai:t1:profile_learning:query_count:u1"

    def test_embedding_cache_key(self):
        """Embedding cache key: mingai:{tenant_id}:embedding_cache:{hash}."""
        from app.core.redis_client import build_redis_key

        key = build_redis_key("t1", "embedding_cache", "abc123")
        assert key == "mingai:t1:embedding_cache:abc123"

    def test_glossary_terms_key(self):
        """Glossary terms key: mingai:{tenant_id}:glossary:terms."""
        from app.core.redis_client import build_redis_key

        key = build_redis_key("t1", "glossary", "terms")
        assert key == "mingai:t1:glossary:terms"

    def test_org_context_key(self):
        """Org context key: mingai:{tenant_id}:org_context:{user_id}."""
        from app.core.redis_client import build_redis_key

        key = build_redis_key("t1", "org_context", "u1")
        assert key == "mingai:t1:org_context:u1"

    def test_two_tenants_produce_different_keys(self):
        """Same key_type and parts produce different keys for different tenants."""
        from app.core.redis_client import build_redis_key

        key_a = build_redis_key("tenant-a", "working_memory", "user-1", "agent-1")
        key_b = build_redis_key("tenant-b", "working_memory", "user-1", "agent-1")
        assert key_a != key_b
        assert "tenant-a" in key_a
        assert "tenant-b" in key_b

    def test_colon_in_parts_raises_error(self):
        """Colons in suffix *parts must raise ValueError (namespace injection prevention)."""
        from app.core.redis_client import build_redis_key

        with pytest.raises(ValueError, match="colon"):
            build_redis_key("tenant-1", "working_memory", "user:injected", "agent-1")

    def test_colon_in_tenant_id_raises_error(self):
        """Colons in tenant_id must raise ValueError."""
        from app.core.redis_client import build_redis_key

        with pytest.raises(ValueError, match="invalid characters"):
            build_redis_key("tenant:evil", "working_memory", "user-1")

