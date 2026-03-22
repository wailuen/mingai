"""
Integration test: BYOLLM profile activation requires required slots to be assigned and tested.

Verifies that activating a BYOLLM profile fails when:
- Required slots (chat, intent) are missing
- Slots are assigned but entries not yet tested (test_passed_at is NULL)

After testing the entries, activation succeeds.

Tier 2: No mocking — requires running PostgreSQL + Redis.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest
from jose import jwt as jose_jwt
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


def _make_enterprise_admin_token(tenant_id: str) -> str:
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
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


async def _fetch_one(sql: str, params: Optional[dict] = None):
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.fetchone()
    finally:
        await engine.dispose()


async def _create_tenant(plan: str = "enterprise") -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, :plan, :email, 'active') "
        "ON CONFLICT (id) DO NOTHING",
        {
            "id": tid,
            "name": f"BYOLLM Act {tid[:8]}",
            "slug": f"byact-{tid[:8]}",
            "plan": plan,
            "email": f"byact-{tid[:8]}@test.example",
        },
    )
    return tid


async def _create_byollm_library_entry(
    tenant_id: str,
    status: str = "published",
    test_passed_at=None,  # datetime or None
    eligible_slots: Optional[list] = None,
) -> str:
    entry_id = str(uuid.uuid4())
    caps = json.dumps({"eligible_slots": eligible_slots or ["chat", "intent"]})
    await _run_sql(
        "INSERT INTO llm_library "
        "(id, provider, model_name, display_name, plan_tier, endpoint_url, "
        "api_key_encrypted, api_key_last4, status, capabilities, "
        "is_byollm, owner_tenant_id, last_test_passed_at, created_at, updated_at) "
        "VALUES "
        "(:id, 'openai_direct', :model, :display, 'professional', 'https://api.openai.com/v1', "
        "'enc_byact_test', '1234', :status, "
        "CAST(:caps AS jsonb), true, :tid, :tpa, NOW(), NOW())",
        {
            "id": entry_id,
            "model": f"gpt-4o-byact-{entry_id[:6]}",
            "display": f"BYACT {entry_id[:6]}",
            "status": status,
            "caps": caps,
            "tid": tenant_id,
            "tpa": test_passed_at,
        },
    )
    return entry_id


async def _create_byollm_profile(tenant_id: str, name: str, status: str = "active") -> str:
    profile_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO llm_profiles "
        "(id, name, description, status, "
        "chat_library_id, intent_library_id, vision_library_id, agent_library_id, "
        "chat_params, intent_params, vision_params, agent_params, "
        "chat_traffic_split, intent_traffic_split, vision_traffic_split, agent_traffic_split, "
        "is_platform_default, plan_tiers, owner_tenant_id, created_by, created_at, updated_at) "
        "VALUES "
        "(:id, :name, NULL, :status, "
        "NULL, NULL, NULL, NULL, "
        "'{}', '{}', '{}', '{}', "
        "'[]', '[]', '[]', '[]', "
        "false, '{}', :tid, :actor, NOW(), NOW())",
        {
            "id": profile_id,
            "name": name,
            "status": status,
            "tid": tenant_id,
            "actor": str(uuid.uuid4()),
        },
    )
    return profile_id


async def _cleanup(tenant_id: str, profile_ids: list, lib_ids: list) -> None:
    # NULL out tenant's llm_profile_id FK to break circular dependency
    await _run_sql("UPDATE tenants SET llm_profile_id = NULL WHERE id = :id", {"id": tenant_id})
    # Delete child rows before tenant to avoid FK violations
    for pid in profile_ids:
        await _run_sql("DELETE FROM llm_profiles WHERE id = :id", {"id": pid})
    for lid in lib_ids:
        await _run_sql("DELETE FROM llm_library WHERE id = :id", {"id": lid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tenant_id})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def byollm_activation_scenario():
    """
    Creates an enterprise tenant, BYOLLM library entries, and profiles in various states.
    Yields (tenant_id, profile_id_chat_only, profile_id_untested, profile_id_ready).
    """
    tenant_id = asyncio.run(_create_tenant("enterprise"))

    # Profile 1: chat only, no intent assigned
    chat_lib_only = asyncio.run(
        _create_byollm_library_entry(tenant_id, status="published", test_passed_at=None)
    )
    profile_chat_only = asyncio.run(
        _create_byollm_profile(tenant_id, f"ChatOnly {uuid.uuid4().hex[:6]}", status="active")
    )
    asyncio.run(_run_sql(
        "UPDATE llm_profiles SET chat_library_id = :cid WHERE id = :pid",
        {"cid": chat_lib_only, "pid": profile_chat_only},
    ))

    # Profile 2: chat + intent assigned but not tested (test_passed_at=NULL)
    chat_lib_untested = asyncio.run(
        _create_byollm_library_entry(tenant_id, status="published", test_passed_at=None)
    )
    intent_lib_untested = asyncio.run(
        _create_byollm_library_entry(tenant_id, status="published", test_passed_at=None)
    )
    profile_untested = asyncio.run(
        _create_byollm_profile(tenant_id, f"Untested {uuid.uuid4().hex[:6]}", status="active")
    )
    asyncio.run(_run_sql(
        "UPDATE llm_profiles SET chat_library_id = :cid, intent_library_id = :iid WHERE id = :pid",
        {"cid": chat_lib_untested, "iid": intent_lib_untested, "pid": profile_untested},
    ))

    # Profile 3: chat + intent assigned AND tested
    now_dt = datetime.now(timezone.utc)
    chat_lib_tested = asyncio.run(
        _create_byollm_library_entry(tenant_id, status="published", test_passed_at=now_dt)
    )
    intent_lib_tested = asyncio.run(
        _create_byollm_library_entry(tenant_id, status="published", test_passed_at=now_dt)
    )
    profile_ready = asyncio.run(
        _create_byollm_profile(tenant_id, f"Ready {uuid.uuid4().hex[:6]}", status="active")
    )
    asyncio.run(_run_sql(
        "UPDATE llm_profiles SET chat_library_id = :cid, intent_library_id = :iid WHERE id = :pid",
        {"cid": chat_lib_tested, "iid": intent_lib_tested, "pid": profile_ready},
    ))

    yield (
        tenant_id,
        profile_chat_only,
        profile_untested,
        profile_ready,
    )
    asyncio.run(_cleanup(
        tenant_id,
        [profile_chat_only, profile_untested, profile_ready],
        [
            chat_lib_only,
            chat_lib_untested, intent_lib_untested,
            chat_lib_tested, intent_lib_tested,
        ],
    ))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestByollmActivationRequiresRequiredSlots:
    """Activation blocked when required slots missing or entries not tested."""

    def test_activate_with_chat_only_returns_error(
        self, client, byollm_activation_scenario
    ):
        """POST /admin/byollm/profiles/{id}/activate returns 422/409 when intent slot missing."""
        tenant_id, profile_chat_only, profile_untested, profile_ready = byollm_activation_scenario
        headers = {"Authorization": f"Bearer {_make_enterprise_admin_token(tenant_id)}"}

        resp = client.post(
            f"/api/v1/admin/byollm/profiles/{profile_chat_only}/activate",
            headers=headers,
        )
        assert resp.status_code in (400, 409, 422), (
            f"Expected error for chat-only profile activation, got {resp.status_code}: {resp.text}"
        )

    def test_activate_with_untested_entries_returns_error(
        self, client, byollm_activation_scenario
    ):
        """POST .../activate returns error when library entries are not tested."""
        tenant_id, profile_chat_only, profile_untested, profile_ready = byollm_activation_scenario
        headers = {"Authorization": f"Bearer {_make_enterprise_admin_token(tenant_id)}"}

        resp = client.post(
            f"/api/v1/admin/byollm/profiles/{profile_untested}/activate",
            headers=headers,
        )
        assert resp.status_code in (400, 409, 422), (
            f"Expected error for untested entries activation, got {resp.status_code}: {resp.text}"
        )

    def test_activate_with_all_ready_slots_succeeds(
        self, client, byollm_activation_scenario
    ):
        """POST .../activate returns 200 when chat+intent assigned and tested."""
        tenant_id, profile_chat_only, profile_untested, profile_ready = byollm_activation_scenario
        headers = {"Authorization": f"Bearer {_make_enterprise_admin_token(tenant_id)}"}

        resp = client.post(
            f"/api/v1/admin/byollm/profiles/{profile_ready}/activate",
            headers=headers,
        )
        assert resp.status_code == 200, (
            f"Expected 200 for ready profile activation, got {resp.status_code}: {resp.text}"
        )
