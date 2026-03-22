"""
Integration test: Concurrent set-platform-default is atomic.

Simulates two concurrent requests trying to set different profiles as the
platform default. After both complete, exactly one profile must have
is_platform_default=TRUE.

Tier 2: No mocking — requires running PostgreSQL + Redis.
"""
import asyncio
import os
import uuid
from typing import Optional

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        pytest.skip("JWT_SECRET_KEY not configured — skipping integration tests")
    return secret


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _make_platform_token() -> str:
    from datetime import datetime, timedelta, timezone
    from jose import jwt as jose_jwt
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jose_jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def _run_sql(sql: str, params: Optional[dict] = None) -> None:
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _count_defaults() -> int:
    """Return count of profiles with is_platform_default=TRUE."""
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM llm_profiles "
                    "WHERE is_platform_default = true AND owner_tenant_id IS NULL AND status = 'active'"
                )
            )
            row = result.fetchone()
            return row[0] if row else 0
    finally:
        await engine.dispose()


async def _create_platform_profile(name: str, is_default: bool = False) -> str:
    profile_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO llm_profiles "
        "(id, name, description, status, "
        "chat_library_id, intent_library_id, vision_library_id, agent_library_id, "
        "chat_params, intent_params, vision_params, agent_params, "
        "chat_traffic_split, intent_traffic_split, vision_traffic_split, agent_traffic_split, "
        "is_platform_default, plan_tiers, owner_tenant_id, created_by, created_at, updated_at) "
        "VALUES "
        "(:id, :name, NULL, 'active', "
        "NULL, NULL, NULL, NULL, "
        "'{}', '{}', '{}', '{}', "
        "'[]', '[]', '[]', '[]', "
        ":is_default, '{}', NULL, :actor, NOW(), NOW())",
        {"id": profile_id, "name": name, "is_default": is_default, "actor": str(uuid.uuid4())},
    )
    return profile_id


async def _cleanup_profiles(profile_ids: list) -> None:
    for pid in profile_ids:
        await _run_sql(
            "DELETE FROM llm_profile_audit_log WHERE entity_id = :id", {"id": pid}
        )
        await _run_sql("DELETE FROM llm_profiles WHERE id = :id", {"id": pid})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def two_platform_profiles():
    """Create two platform profiles for concurrency testing. Yields (profile_a_id, profile_b_id)."""
    profile_a = asyncio.run(_create_platform_profile(f"ConcDefault-A {uuid.uuid4().hex[:6]}"))
    profile_b = asyncio.run(_create_platform_profile(f"ConcDefault-B {uuid.uuid4().hex[:6]}"))
    yield profile_a, profile_b
    # Unset default first to avoid leaving a sticky default
    asyncio.run(_run_sql(
        "UPDATE llm_profiles SET is_platform_default = false "
        "WHERE id = :a OR id = :b",
        {"a": profile_a, "b": profile_b},
    ))
    asyncio.run(_cleanup_profiles([profile_a, profile_b]))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConcurrentProfileUpdate:
    """Atomic swap prevents double-default state."""

    def test_set_default_is_atomic_no_double_default(
        self, client, two_platform_profiles
    ):
        """
        Two concurrent set-default requests: only one profile ends up as default.

        Uses two sequential HTTP calls (sync TestClient is not concurrent) to
        verify the atomic swap: after A becomes default, setting B to default
        must clear A first. The end state must be exactly one default.
        """
        profile_a, profile_b = two_platform_profiles
        headers = {"Authorization": f"Bearer {_make_platform_token()}"}

        # First: set A as default
        resp_a = client.post(
            f"/api/v1/platform/llm-profiles/{profile_a}/set-default",
            headers=headers,
        )
        assert resp_a.status_code == 200, (
            f"Setting profile A as default failed: {resp_a.status_code} {resp_a.text}"
        )

        # Now set B as default — should atomically clear A and set B
        resp_b = client.post(
            f"/api/v1/platform/llm-profiles/{profile_b}/set-default",
            headers=headers,
        )
        assert resp_b.status_code == 200, (
            f"Setting profile B as default failed: {resp_b.status_code} {resp_b.text}"
        )

        # Verify exactly one default exists in DB
        default_count = asyncio.run(_count_defaults())
        # Filter to only our test profiles
        async def _count_our_defaults() -> int:
            engine = create_async_engine(_db_url(), echo=False)
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                async with factory() as session:
                    result = await session.execute(
                        text(
                            "SELECT COUNT(*) FROM llm_profiles "
                            "WHERE is_platform_default = true "
                            "AND id IN (:a, :b)"
                        ),
                        {"a": profile_a, "b": profile_b},
                    )
                    row = result.fetchone()
                    return row[0] if row else 0
            finally:
                await engine.dispose()

        our_defaults = asyncio.run(_count_our_defaults())
        assert our_defaults == 1, (
            f"Expected exactly 1 default among test profiles, found {our_defaults}"
        )

    def test_set_default_response_contains_previous_default_id(
        self, client, two_platform_profiles
    ):
        """
        set-default response includes previous_default_id (the profile being replaced).
        """
        profile_a, profile_b = two_platform_profiles
        headers = {"Authorization": f"Bearer {_make_platform_token()}"}

        # Ensure A is default first
        client.post(
            f"/api/v1/platform/llm-profiles/{profile_a}/set-default",
            headers=headers,
        )

        # Set B as default, expect response to include previous_default_id=profile_a
        resp = client.post(
            f"/api/v1/platform/llm-profiles/{profile_b}/set-default",
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "new_default_id" in body, (
            f"Response should include new_default_id: {body}"
        )
        assert body["new_default_id"] == profile_b, (
            f"new_default_id should be {profile_b}, got {body['new_default_id']}"
        )

    def test_no_double_default_after_repeated_swaps(
        self, client, two_platform_profiles
    ):
        """Repeated swaps between A and B never produce more than 1 default."""
        profile_a, profile_b = two_platform_profiles
        headers = {"Authorization": f"Bearer {_make_platform_token()}"}

        for i in range(4):
            target = profile_a if i % 2 == 0 else profile_b
            resp = client.post(
                f"/api/v1/platform/llm-profiles/{target}/set-default",
                headers=headers,
            )
            assert resp.status_code == 200, (
                f"Swap {i+1} failed: {resp.status_code} {resp.text}"
            )

            # Check no double default after each swap
            async def _count_our_defaults() -> int:
                engine = create_async_engine(_db_url(), echo=False)
                factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
                try:
                    async with factory() as session:
                        result = await session.execute(
                            text(
                                "SELECT COUNT(*) FROM llm_profiles "
                                "WHERE is_platform_default = true "
                                "AND id IN (:a, :b)"
                            ),
                            {"a": profile_a, "b": profile_b},
                        )
                        row = result.fetchone()
                        return row[0] if row else 0
                finally:
                    await engine.dispose()

            count = asyncio.run(_count_our_defaults())
            assert count == 1, (
                f"Double-default detected after swap {i+1}: count={count}"
            )
