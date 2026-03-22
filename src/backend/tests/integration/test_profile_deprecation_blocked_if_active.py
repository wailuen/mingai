"""
Integration test: Platform profile deprecation is blocked when tenants are using it.

Verifies:
- Deprecating a profile with assigned tenants returns 409 with tenant_count
- After removing tenants from the profile, deprecation succeeds

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


async def _create_platform_profile(name: str) -> str:
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
        "false, '{}', NULL, :actor, NOW(), NOW())",
        {"id": profile_id, "name": name, "actor": str(uuid.uuid4())},
    )
    return profile_id


async def _create_tenant_with_profile(profile_id: str) -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status, llm_profile_id) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active', :pid) "
        "ON CONFLICT (id) DO NOTHING",
        {
            "id": tid,
            "name": f"DeprBlocked Tenant {tid[:8]}",
            "slug": f"db-{tid[:8]}",
            "email": f"db-{tid[:8]}@test.example",
            "pid": profile_id,
        },
    )
    return tid


async def _unassign_tenant(tid: str) -> None:
    await _run_sql(
        "UPDATE tenants SET llm_profile_id = NULL WHERE id = :id", {"id": tid}
    )


async def _cleanup(tenant_ids: list, profile_id: str) -> None:
    for tid in tenant_ids:
        await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})
    await _run_sql(
        "DELETE FROM llm_profile_audit_log WHERE entity_id = :id", {"id": profile_id}
    )
    await _run_sql("DELETE FROM llm_profiles WHERE id = :id", {"id": profile_id})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def deprecation_blocked_scenario():
    """
    Creates:
      - A platform profile
      - Three tenants assigned to it
    Yields (profile_id, [tenant_id_1, tenant_id_2, tenant_id_3]).
    """
    profile_id = asyncio.run(
        _create_platform_profile(f"DeprBlocked {uuid.uuid4().hex[:6]}")
    )
    tenant_ids = [
        asyncio.run(_create_tenant_with_profile(profile_id)) for _ in range(3)
    ]
    yield profile_id, tenant_ids
    asyncio.run(_cleanup(tenant_ids, profile_id))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProfileDeprecationBlockedIfActive:
    """Deprecation blocked when tenants are using the profile."""

    def test_delete_endpoint_returns_409_when_tenants_assigned(
        self, client, deprecation_blocked_scenario
    ):
        """DELETE /platform/llm-profiles/{id} returns 409 while tenants use it."""
        profile_id, tenant_ids = deprecation_blocked_scenario
        headers = {"Authorization": f"Bearer {_make_platform_token()}"}

        resp = client.delete(
            f"/api/v1/platform/llm-profiles/{profile_id}", headers=headers
        )
        assert resp.status_code == 409, (
            f"Expected 409 when profile has assigned tenants, got {resp.status_code}: {resp.text}"
        )

    def test_409_response_includes_tenant_count(
        self, client, deprecation_blocked_scenario
    ):
        """409 response includes tenant_count >= 3."""
        profile_id, tenant_ids = deprecation_blocked_scenario
        headers = {"Authorization": f"Bearer {_make_platform_token()}"}

        resp = client.delete(
            f"/api/v1/platform/llm-profiles/{profile_id}", headers=headers
        )
        assert resp.status_code == 409
        body = resp.json()
        assert "tenant_count" in body, (
            f"409 response should include tenant_count, got: {body}"
        )
        assert body["tenant_count"] >= 3, (
            f"tenant_count should be >= 3, got {body['tenant_count']}"
        )

    def test_delete_succeeds_after_tenants_unassigned(
        self, client, deprecation_blocked_scenario
    ):
        """DELETE succeeds (200/204) after all tenants are unassigned from the profile."""
        profile_id, tenant_ids = deprecation_blocked_scenario

        # Unassign all tenants
        for tid in tenant_ids:
            asyncio.run(_unassign_tenant(tid))

        headers = {"Authorization": f"Bearer {_make_platform_token()}"}
        resp = client.delete(
            f"/api/v1/platform/llm-profiles/{profile_id}", headers=headers
        )
        assert resp.status_code in (200, 204), (
            f"Expected 200/204 after all tenants unassigned, got {resp.status_code}: {resp.text}"
        )

    def test_profile_status_is_deprecated_after_delete(
        self, client, deprecation_blocked_scenario
    ):
        """After successful deprecation, profile status is 'deprecated' in DB."""
        profile_id, tenant_ids = deprecation_blocked_scenario

        async def _check_status() -> str:
            engine = create_async_engine(_db_url(), echo=False)
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                async with factory() as db:
                    result = await db.execute(
                        text("SELECT status FROM llm_profiles WHERE id = :id"),
                        {"id": profile_id},
                    )
                    row = result.fetchone()
                    return row[0] if row else "not_found"
            finally:
                await engine.dispose()

        # The delete test above ran deprecation — verify status
        status = asyncio.run(_check_status())
        assert status == "deprecated", (
            f"Expected status='deprecated' after deprecation, got '{status}'"
        )
