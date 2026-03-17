"""
Integration tests for cache analytics endpoints (API-106 to API-109).

Tier 2: Real Redis, real PostgreSQL. Docker must be running.

Tests:
- test_cache_analytics_returns_structure (zero-data graceful degradation)
- test_cache_ttl_update (Redis round-trip via API-109)

Event loop pattern: module-scoped TestClient, per-test redis pool reset.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from jose import jwt

import app.core.redis_client as redis_client_module

TEST_JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "a" * 64)
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "platform-admin-integration",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "email": "platform@mingai.io",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


@pytest.fixture(autouse=True)
def _reset_redis_pool():
    """
    Reset global Redis pool before each test (sync, no async teardown needed
    because each TestClient call creates a new event loop context).
    """
    redis_client_module._redis_pool = None
    yield
    redis_client_module._redis_pool = None


@pytest.fixture
def platform_headers():
    return {"Authorization": f"Bearer {_make_platform_token()}"}


# ---------------------------------------------------------------------------
# test_cache_analytics_returns_structure
# ---------------------------------------------------------------------------


def test_cache_analytics_returns_structure(client, platform_headers):
    """
    GET /platform/analytics/cache should return the expected shape even when
    cache_analytics_events table does not exist or has no data (graceful degradation).
    """
    resp = client.get(
        "/api/v1/platform/analytics/cache?period=30d",
        headers=platform_headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    # Verify top-level structure
    assert "period" in data
    assert data["period"] == "30d"
    assert "overall" in data
    assert "by_type" in data
    assert "generated_at" in data

    # Verify overall sub-structure
    overall = data["overall"]
    assert "hit_rate" in overall
    assert "hits" in overall
    assert "misses" in overall
    assert "estimated_cost_saved_usd" in overall

    # In zero-data case all numeric fields must be >= 0
    assert overall["hits"] >= 0
    assert overall["misses"] >= 0
    assert overall["hit_rate"] >= 0.0
    assert overall["estimated_cost_saved_usd"] >= 0.0

    # by_type must be a list
    assert isinstance(data["by_type"], list)


def test_cache_analytics_invalid_period(client, platform_headers):
    """Invalid period parameter should return 422."""
    resp = client.get(
        "/api/v1/platform/analytics/cache?period=365d",
        headers=platform_headers,
    )
    assert resp.status_code == 422


def test_cache_analytics_requires_platform_admin(client):
    """Non-platform token should receive 401/403."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-user",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    token = jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)
    resp = client.get(
        "/api/v1/platform/analytics/cache",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (401, 403)


def test_cache_analytics_by_index_returns_structure(client, platform_headers):
    """GET /platform/analytics/cache/by-index should return an 'indexes' list."""
    resp = client.get(
        "/api/v1/platform/analytics/cache/by-index",
        headers=platform_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "indexes" in data
    assert isinstance(data["indexes"], list)


def test_cache_savings_returns_structure(client, platform_headers):
    """GET /platform/analytics/cache/savings should return cost/latency fields."""
    resp = client.get(
        "/api/v1/platform/analytics/cache/savings?period=7d",
        headers=platform_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == "7d"
    assert "estimated_cost_saved_usd" in data
    assert "tokens_served_from_cache" in data
    assert "avg_latency_reduction_ms" in data
    assert data["estimated_cost_saved_usd"] >= 0.0
    assert data["tokens_served_from_cache"] >= 0
    assert data["avg_latency_reduction_ms"] >= 0.0


# ---------------------------------------------------------------------------
# test_cache_ttl_update
# ---------------------------------------------------------------------------


def test_cache_ttl_update(client, platform_headers):
    """
    PATCH /platform/cache-ttl/{index_name} should store ttl_hours in Redis
    and return the stored value.

    Verification reads directly from Redis using a synchronous helper.
    """
    index_name = "integ-test-index"
    resp = client.patch(
        f"/api/v1/platform/cache-ttl/{index_name}",
        json={"ttl_hours": 48},
        headers=platform_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["index_name"] == index_name
    assert data["ttl_hours"] == 48
    assert "updated_at" in data

    # Verify stored in Redis synchronously (no asyncio.run needed)
    from app.core.redis_client import build_redis_key, get_redis
    import redis as sync_redis_lib

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    r = sync_redis_lib.from_url(redis_url, decode_responses=True)
    ttl_key = build_redis_key("platform", "cache_ttl", index_name)
    value = r.get(ttl_key)
    assert value == "48"
    # Clean up
    r.delete(ttl_key)
    r.close()


def test_cache_ttl_update_out_of_range(client, platform_headers):
    """ttl_hours outside 1–168 must be rejected with 422."""
    resp = client.patch(
        "/api/v1/platform/cache-ttl/some-index",
        json={"ttl_hours": 0},
        headers=platform_headers,
    )
    assert resp.status_code == 422

    resp2 = client.patch(
        "/api/v1/platform/cache-ttl/some-index",
        json={"ttl_hours": 200},
        headers=platform_headers,
    )
    assert resp2.status_code == 422


def test_cache_ttl_update_invalid_index_name(client, platform_headers):
    """index_name with special characters (e.g. colons) should be rejected."""
    resp = client.patch(
        "/api/v1/platform/cache-ttl/bad:index:name",
        json={"ttl_hours": 24},
        headers=platform_headers,
    )
    # The colon is part of the URL path which FastAPI will handle — the validator
    # inside the handler checks for safe characters. Either 404 (path not matched)
    # or 422 (validation error) is acceptable rejection.
    assert resp.status_code in (404, 422)
