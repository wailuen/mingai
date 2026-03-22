"""
Integration test: BYOLLM cross-tenant isolation.

Verifies that tenant B cannot access tenant A's library entries or profiles:
  - 404 (not 403) when accessing another tenant's resource by ID
  - 422 when trying to assign a library entry owned by another tenant

404 not 403: revealing that a resource exists is itself an information leak.

Tier 2: No mocking — requires running PostgreSQL + Redis.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from jose import jwt
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
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def _run_sql(sql: str, params: Optional[dict] = None) -> None:
    url = _db_url()
    engine = create_async_engine(url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _create_tenant(tid: str) -> None:
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'enterprise', :email, 'active') "
        "ON CONFLICT (id) DO NOTHING",
        {
            "id": tid,
            "name": f"Isolation Tenant {tid[:8]}",
            "slug": f"iso-ent-{tid[:8]}",
            "email": f"iso-{tid[:8]}@test.example",
        },
    )


async def _delete_tenant(tid: str) -> None:
    # NULL out tenant's profile FK before deleting profiles
    await _run_sql("UPDATE tenants SET llm_profile_id = NULL WHERE id = :tid", {"tid": tid})
    # Delete child rows before tenant to avoid FK violations
    await _run_sql("DELETE FROM llm_profiles WHERE owner_tenant_id = :tid", {"tid": tid})
    await _run_sql(
        "DELETE FROM llm_library WHERE owner_tenant_id = :tid", {"tid": tid}
    )
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


async def _create_library_entry(tid: str) -> str:
    """Insert a library entry owned by tenant tid directly into DB. Returns entry id."""
    entry_id = str(uuid.uuid4())
    caps = json.dumps({"eligible_slots": ["chat", "intent"]})
    await _run_sql(
        "INSERT INTO llm_library "
        "(id, provider, model_name, display_name, plan_tier, endpoint_url, "
        "api_key_encrypted, api_key_last4, status, "
        "capabilities, is_byollm, owner_tenant_id, created_at, updated_at) "
        "VALUES "
        "(:id, 'openai_direct', 'gpt-4o', 'Test Model', 'professional', 'https://api.openai.com/v1', "
        "'enc_dummy', '4321', 'draft', "
        "CAST(:caps AS jsonb), true, :tid, NOW(), NOW())",
        {"id": entry_id, "caps": caps, "tid": tid},
    )
    return entry_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def two_enterprise_tenants():
    """Create tenant A and tenant B, return (tenant_a_id, tenant_b_id, entry_a_id)."""
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    asyncio.run(_create_tenant(tenant_a))
    asyncio.run(_create_tenant(tenant_b))
    entry_a = asyncio.run(_create_library_entry(tenant_a))
    yield tenant_a, tenant_b, entry_a
    asyncio.run(_delete_tenant(tenant_a))
    asyncio.run(_delete_tenant(tenant_b))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestByollmCrossTenantIsolation:
    """Tenant B cannot access or use tenant A's resources."""

    def test_tenant_b_cannot_read_tenant_a_library_entry(
        self, client, two_enterprise_tenants
    ):
        """GET /admin/byollm/library-entries/{id} returns 404 for cross-tenant access."""
        tenant_a, tenant_b, entry_a = two_enterprise_tenants
        headers_b = {
            "Authorization": f"Bearer {_make_enterprise_admin_token(tenant_b)}"
        }
        resp = client.get(
            f"/api/v1/admin/byollm/library-entries/{entry_a}", headers=headers_b
        )
        # Must be 404, not 403 — revealing existence is an information leak
        assert resp.status_code == 404, (
            f"Expected 404 for cross-tenant library entry read, got {resp.status_code}: {resp.text}"
        )

    def test_tenant_b_cannot_update_tenant_a_library_entry(
        self, client, two_enterprise_tenants
    ):
        """PATCH /admin/byollm/library-entries/{id} returns 404 for cross-tenant write."""
        tenant_a, tenant_b, entry_a = two_enterprise_tenants
        headers_b = {
            "Authorization": f"Bearer {_make_enterprise_admin_token(tenant_b)}"
        }
        resp = client.patch(
            f"/api/v1/admin/byollm/library-entries/{entry_a}",
            json={"display_name": "Hacked"},
            headers=headers_b,
        )
        assert resp.status_code == 404, (
            f"Expected 404 for cross-tenant library entry update, got {resp.status_code}: {resp.text}"
        )

    def test_tenant_b_library_list_does_not_include_tenant_a_entries(
        self, client, two_enterprise_tenants
    ):
        """GET /admin/byollm/library-entries returns only caller's entries."""
        tenant_a, tenant_b, entry_a = two_enterprise_tenants
        headers_b = {
            "Authorization": f"Bearer {_make_enterprise_admin_token(tenant_b)}"
        }
        resp = client.get("/api/v1/admin/byollm/library-entries", headers=headers_b)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        entries = resp.json()
        entry_ids = [e["id"] for e in entries]
        assert entry_a not in entry_ids, (
            "Tenant B's library list must not include tenant A's entry"
        )

    def test_tenant_b_cannot_assign_tenant_a_library_id_to_slot(
        self, client, two_enterprise_tenants
    ):
        """Assigning a cross-tenant library entry to a slot must return 404."""
        tenant_a, tenant_b, entry_a = two_enterprise_tenants
        headers_b = {
            "Authorization": f"Bearer {_make_enterprise_admin_token(tenant_b)}"
        }
        # First create a valid profile for tenant B
        profile_resp = client.post(
            "/api/v1/admin/byollm/profiles",
            json={"name": f"TenantB-{uuid.uuid4().hex[:6]}"},
            headers=headers_b,
        )
        assert profile_resp.status_code == 201, (
            f"Profile creation for tenant B failed: {profile_resp.status_code}: {profile_resp.text}"
        )
        profile_id = profile_resp.json()["id"]

        # Attempt to assign tenant A's library entry to a slot — must fail with 404
        assign_resp = client.patch(
            f"/api/v1/admin/byollm/profiles/{profile_id}/slots/chat",
            json={"library_id": entry_a},
            headers=headers_b,
        )
        assert assign_resp.status_code == 404, (
            f"Expected 404 for cross-tenant slot assignment, got {assign_resp.status_code}: {assign_resp.text}"
        )
