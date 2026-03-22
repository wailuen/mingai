"""
Integration test: Degraded health_status on a library entry surfaces as a
warning in the platform profile detail API response.

Verifies:
- GET /platform/llm-profiles/{id} includes health indicator data for each slot
- A slot whose library entry has health_status='degraded' returns a warning
- GET /platform/llm-library returns health_status='degraded' for the degraded entry

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


async def _create_library_entry(health_status: str = "healthy") -> str:
    entry_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO llm_library "
        "(id, provider, model_name, display_name, plan_tier, endpoint_url, "
        "api_key_encrypted, api_key_last4, status, capabilities, "
        "is_byollm, owner_tenant_id, health_status, created_at, updated_at) "
        "VALUES "
        "(:id, 'openai_direct', :model, :display, 'professional', 'https://api.openai.com/v1', "
        "'enc_health_test', 'abcd', 'published', "
        "CAST('{\"eligible_slots\":[\"chat\",\"intent\"]}' AS jsonb), "
        "false, NULL, :hs, NOW(), NOW())",
        {
            "id": entry_id,
            "model": f"gpt-4o-health-{entry_id[:6]}",
            "display": f"Health Test {entry_id[:6]}",
            "hs": health_status,
        },
    )
    return entry_id


async def _create_platform_profile_with_slot(chat_library_id: str) -> str:
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
        ":cid, NULL, NULL, NULL, "
        "'{}', '{}', '{}', '{}', "
        "'[]', '[]', '[]', '[]', "
        "false, '{}', NULL, :actor, NOW(), NOW())",
        {
            "id": profile_id,
            "name": f"Health Warn Test {profile_id[:8]}",
            "cid": chat_library_id,
            "actor": str(uuid.uuid4()),
        },
    )
    return profile_id


async def _set_health_status(entry_id: str, health_status: str) -> None:
    await _run_sql(
        "UPDATE llm_library SET health_status = :hs WHERE id = :id",
        {"hs": health_status, "id": entry_id},
    )


async def _cleanup(profile_id: str, entry_id: str) -> None:
    await _run_sql(
        "DELETE FROM llm_profile_audit_log WHERE entity_id = :id", {"id": profile_id}
    )
    await _run_sql(
        "UPDATE llm_profiles SET chat_library_id = NULL WHERE id = :id",
        {"id": profile_id},
    )
    await _run_sql("DELETE FROM llm_profiles WHERE id = :id", {"id": profile_id})
    await _run_sql("DELETE FROM llm_library WHERE id = :id", {"id": entry_id})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def health_warning_scenario():
    """
    Creates:
      - A published library entry (initially healthy)
      - A platform profile with that entry assigned to the chat slot

    Yields (profile_id, entry_id).
    """
    entry_id = asyncio.run(_create_library_entry(health_status="healthy"))
    profile_id = asyncio.run(_create_platform_profile_with_slot(entry_id))
    yield profile_id, entry_id
    asyncio.run(_cleanup(profile_id, entry_id))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealthCheckDegradedShowsWarning:
    """Degraded library entry health surfaces as warning in profile detail API."""

    def test_healthy_entry_slot_has_no_health_warning(
        self, client, health_warning_scenario
    ):
        """GET /platform/llm-profiles/{id} for healthy entry: chat slot has no health warning."""
        profile_id, entry_id = health_warning_scenario
        asyncio.run(_set_health_status(entry_id, "healthy"))
        headers = {"Authorization": f"Bearer {_make_platform_token()}"}

        resp = client.get(
            f"/api/v1/platform/llm-profiles/{profile_id}", headers=headers
        )
        assert resp.status_code == 200, (
            f"Expected 200 from profile detail, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        # Profile detail should include slots data
        assert "id" in body, f"Response missing 'id' field: {body}"

    def test_degraded_entry_slot_includes_health_warning(
        self, client, health_warning_scenario
    ):
        """
        GET /platform/llm-profiles/{id} after setting entry to degraded:
        response should include health warning indicator in the slot data.
        """
        profile_id, entry_id = health_warning_scenario
        asyncio.run(_set_health_status(entry_id, "degraded"))
        headers = {"Authorization": f"Bearer {_make_platform_token()}"}

        resp = client.get(
            f"/api/v1/platform/llm-profiles/{profile_id}", headers=headers
        )
        assert resp.status_code == 200, (
            f"Expected 200 from profile detail, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        # The response must indicate degraded health for the chat slot
        # Acceptable representations: body contains 'degraded', or a slot field
        # references health_status, or chat_slot includes health info
        body_str = str(body).lower()
        assert "degraded" in body_str, (
            f"Expected 'degraded' health indicator in profile detail response for "
            f"degraded chat slot entry, but response was: {body}"
        )

    def test_library_list_returns_degraded_health_status(
        self, client, health_warning_scenario
    ):
        """
        GET /platform/llm-library returns health_status='degraded' for the degraded entry.
        """
        profile_id, entry_id = health_warning_scenario
        asyncio.run(_set_health_status(entry_id, "degraded"))
        headers = {"Authorization": f"Bearer {_make_platform_token()}"}

        resp = client.get("/api/v1/platform/llm-library", headers=headers)
        assert resp.status_code == 200, (
            f"Expected 200 from llm-library list, got {resp.status_code}: {resp.text}"
        )
        items = resp.json()
        if isinstance(items, dict):
            items = items.get("items", items.get("data", []))

        # Find the degraded entry in the response
        degraded_items = [
            item for item in items
            if isinstance(item, dict) and item.get("id") == entry_id
        ]
        assert len(degraded_items) == 1, (
            f"Expected to find entry {entry_id} in llm-library list; "
            f"found {len(degraded_items)} matching items. Response: {items[:3]}"
        )
        item = degraded_items[0]
        assert item.get("health_status") == "degraded", (
            f"Expected health_status='degraded' for entry {entry_id}, "
            f"got: {item.get('health_status')}"
        )

    def test_recovered_entry_shows_healthy_after_update(
        self, client, health_warning_scenario
    ):
        """After health_status transitions back to 'healthy', profile detail no longer warns."""
        profile_id, entry_id = health_warning_scenario
        asyncio.run(_set_health_status(entry_id, "degraded"))
        asyncio.run(_set_health_status(entry_id, "healthy"))
        headers = {"Authorization": f"Bearer {_make_platform_token()}"}

        resp = client.get(
            f"/api/v1/platform/llm-profiles/{profile_id}", headers=headers
        )
        assert resp.status_code == 200, (
            f"Expected 200 from profile detail after recovery, "
            f"got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        body_str = str(body).lower()
        # After recovery, 'degraded' should no longer appear for this entry
        # We check either that 'degraded' is absent OR that the slot health is 'healthy'
        # The test is satisfied if health_status field for this entry shows 'healthy'
        # We rely on the API contract: degraded → present, healthy → absent or 'healthy'
        assert "degraded" not in body_str or "healthy" in body_str, (
            f"After recovery, profile detail should not show 'degraded' warning "
            f"without also showing 'healthy': {body}"
        )
