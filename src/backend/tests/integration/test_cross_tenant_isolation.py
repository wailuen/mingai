"""
TEST-003: Cross-Tenant Data Isolation Integration Tests

Tests that tenant A's data is not accessible to tenant B at the application
layer. Uses real PostgreSQL — no mocking.

Isolation model:
- Routes filter all queries by current_user.tenant_id from JWT
- Each query has WHERE tenant_id = :tenant_id; cross-tenant access returns 404
- DB-level RLS provides an additional enforcement layer in production (non-superuser)

Architecture note:
    Uses sync TestClient (session-scoped) + asyncio.run() for DB setup/teardown.
    This avoids event loop conflicts with the module-level SQLAlchemy engine.

Tier 2: No mocking — requires running Docker infrastructure.

Run:
    pytest tests/integration/test_cross_tenant_isolation.py -v -m integration
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
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


def _make_admin_token(tenant_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": f"admin@{tenant_id[:8]}.test",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _make_user_token(tenant_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "roles": ["end_user"],
        "scope": "tenant",
        "plan": "professional",
        "email": f"user@{tenant_id[:8]}.test",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def _run_sql(sql: str, params: dict = None):
    """Execute SQL using a fresh isolated async engine (own event loop)."""
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _create_tenant(tid: str, name_suffix: str):
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, :plan, :email, 'active')",
        {
            "id": tid,
            "name": f"Isolation Test {name_suffix} {tid[:8]}",
            "slug": f"iso-{name_suffix.lower()}-{tid[:8]}",
            "plan": "professional",
            "email": f"iso-{tid[:8]}@isolation.test",
        },
    )


async def _cleanup_tenant(tid: str):
    await _run_sql("DELETE FROM glossary_terms WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def two_tenants():
    """
    Provision two isolated test tenants. Yields (tenant_a, tenant_b).
    Cleans up after the module.
    """
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    asyncio.run(_create_tenant(tenant_a, "Alpha"))
    asyncio.run(_create_tenant(tenant_b, "Beta"))
    yield tenant_a, tenant_b
    asyncio.run(_cleanup_tenant(tenant_a))
    asyncio.run(_cleanup_tenant(tenant_b))


# ---------------------------------------------------------------------------
# Tests: Glossary Cross-Tenant Isolation
# ---------------------------------------------------------------------------


class TestGlossaryTenantIsolation:
    """
    Verify that tenant A's glossary terms are invisible to tenant B.
    Application routes filter by JWT's tenant_id — no cross-tenant leakage.
    """

    def test_tenant_a_terms_not_visible_to_tenant_b(self, client, two_tenants):
        """
        Tenant A creates a term → Tenant B cannot see it in their list.
        Routes pass current_user.tenant_id to all DB queries.
        """
        tenant_a, tenant_b = two_tenants
        admin_a = {"Authorization": f"Bearer {_make_admin_token(tenant_a)}"}
        user_b = {"Authorization": f"Bearer {_make_user_token(tenant_b)}"}

        unique_marker = uuid.uuid4().hex[:8].upper()
        create_resp = client.post(
            "/api/v1/glossary",
            json={
                "term": f"TENA{unique_marker}",
                "full_form": f"Tenant A Secret {unique_marker}",
            },
            headers=admin_a,
        )
        assert create_resp.status_code == 201, create_resp.text
        term_id = create_resp.json()["id"]

        # Tenant B lists glossary — must NOT see Tenant A's term
        list_b = client.get("/api/v1/glossary?page_size=100", headers=user_b)
        assert list_b.status_code == 200
        b_ids = {item["id"] for item in list_b.json()["items"]}
        assert (
            term_id not in b_ids
        ), f"Tenant B can see Tenant A's term {term_id} — CROSS-TENANT LEAK!"

    def test_tenant_b_cannot_get_tenant_a_term_by_id(self, client, two_tenants):
        """
        Tenant B's token cannot read Tenant A's term by ID.
        Routes add tenant_id to the WHERE clause → returns 404, not 200.
        """
        tenant_a, tenant_b = two_tenants
        admin_a = {"Authorization": f"Bearer {_make_admin_token(tenant_a)}"}
        user_b = {"Authorization": f"Bearer {_make_user_token(tenant_b)}"}

        unique_marker = uuid.uuid4().hex[:8].upper()
        create_resp = client.post(
            "/api/v1/glossary",
            json={"term": f"TENAGET{unique_marker}", "full_form": "Tenant A GET Test"},
            headers=admin_a,
        )
        assert create_resp.status_code == 201
        term_id = create_resp.json()["id"]

        get_resp = client.get(f"/api/v1/glossary/{term_id}", headers=user_b)
        assert get_resp.status_code == 404, (
            f"Tenant B got status {get_resp.status_code} on Tenant A's term "
            f"— expected 404. Response: {get_resp.text}"
        )

    def test_tenant_b_cannot_update_tenant_a_term(self, client, two_tenants):
        """
        Tenant B cannot PATCH Tenant A's term.
        WHERE clause includes tenant_id → no rows matched → 404, data unchanged.
        """
        tenant_a, tenant_b = two_tenants
        admin_a = {"Authorization": f"Bearer {_make_admin_token(tenant_a)}"}
        admin_b = {"Authorization": f"Bearer {_make_admin_token(tenant_b)}"}

        unique_marker = uuid.uuid4().hex[:8].upper()
        create_resp = client.post(
            "/api/v1/glossary",
            json={"term": f"TENAPATCH{unique_marker}", "full_form": "Original"},
            headers=admin_a,
        )
        assert create_resp.status_code == 201
        term_id = create_resp.json()["id"]

        # Tenant B tries PATCH
        patch_resp = client.patch(
            f"/api/v1/glossary/{term_id}",
            json={"full_form": "HIJACKED"},
            headers=admin_b,
        )
        assert patch_resp.status_code == 404, (
            f"Tenant B patched Tenant A's term — CROSS-TENANT WRITE! "
            f"Status: {patch_resp.status_code}, Body: {patch_resp.text}"
        )

        # Verify Tenant A's term is unchanged
        get_resp = client.get(f"/api/v1/glossary/{term_id}", headers=admin_a)
        assert get_resp.status_code == 200
        assert (
            get_resp.json()["full_form"] == "Original"
        ), "Tenant A's term was modified by Tenant B!"

    def test_tenant_b_cannot_delete_tenant_a_term(self, client, two_tenants):
        """
        Tenant B cannot DELETE Tenant A's term.
        WHERE clause filters by tenant_id → rowcount=0 → 404.
        Term must still be accessible by Tenant A after the attempt.
        """
        tenant_a, tenant_b = two_tenants
        admin_a = {"Authorization": f"Bearer {_make_admin_token(tenant_a)}"}
        admin_b = {"Authorization": f"Bearer {_make_admin_token(tenant_b)}"}

        unique_marker = uuid.uuid4().hex[:8].upper()
        create_resp = client.post(
            "/api/v1/glossary",
            json={"term": f"TENADEL{unique_marker}", "full_form": "Should Survive"},
            headers=admin_a,
        )
        assert create_resp.status_code == 201
        term_id = create_resp.json()["id"]

        del_resp = client.delete(f"/api/v1/glossary/{term_id}", headers=admin_b)
        assert del_resp.status_code == 404, (
            f"Tenant B deleted Tenant A's term — CROSS-TENANT DELETE! "
            f"Status: {del_resp.status_code}"
        )

        # Term must still exist for Tenant A
        get_resp = client.get(f"/api/v1/glossary/{term_id}", headers=admin_a)
        assert (
            get_resp.status_code == 200
        ), "Term was deleted by Tenant B — cross-tenant data destruction!"

    def test_each_tenant_sees_only_their_own_terms(self, client, two_tenants):
        """
        Tenant A and B both create terms. Each list returns only their own.
        Verifies complete isolation in paginated list responses.
        """
        tenant_a, tenant_b = two_tenants
        admin_a = {"Authorization": f"Bearer {_make_admin_token(tenant_a)}"}
        admin_b = {"Authorization": f"Bearer {_make_admin_token(tenant_b)}"}

        marker = uuid.uuid4().hex[:6].upper()
        term_a = f"ONLYA{marker}"
        term_b = f"ONLYB{marker}"

        resp_a = client.post(
            "/api/v1/glossary",
            json={"term": term_a, "full_form": "Only in Tenant A"},
            headers=admin_a,
        )
        assert resp_a.status_code == 201
        id_a = resp_a.json()["id"]

        resp_b = client.post(
            "/api/v1/glossary",
            json={"term": term_b, "full_form": "Only in Tenant B"},
            headers=admin_b,
        )
        assert resp_b.status_code == 201
        id_b = resp_b.json()["id"]

        # Tenant A's list
        list_a = client.get("/api/v1/glossary?page_size=100", headers=admin_a)
        ids_a = {item["id"] for item in list_a.json()["items"]}
        assert id_a in ids_a, "Tenant A cannot see their own term"
        assert id_b not in ids_a, "Tenant A sees Tenant B's term — ISOLATION FAILURE"

        # Tenant B's list
        list_b = client.get("/api/v1/glossary?page_size=100", headers=admin_b)
        ids_b = {item["id"] for item in list_b.json()["items"]}
        assert id_b in ids_b, "Tenant B cannot see their own term"
        assert id_a not in ids_b, "Tenant B sees Tenant A's term — ISOLATION FAILURE"


# ---------------------------------------------------------------------------
# Tests: Token Tampering
# ---------------------------------------------------------------------------


class TestTokenTampering:
    """
    Verify that invalid/tampered JWTs are rejected.
    """

    def test_expired_token_rejected(self, client):
        """Expired JWT returns 401."""
        secret = _jwt_secret()
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
            "roles": ["end_user"],
            "scope": "tenant",
            "plan": "professional",
            "email": "expired@test.com",
            "exp": now - timedelta(hours=1),
            "iat": now - timedelta(hours=2),
            "token_version": 2,
        }
        token = jwt.encode(payload, secret, algorithm="HS256")
        resp = client.get(
            "/api/v1/glossary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_wrong_signature_rejected(self, client):
        """JWT signed with wrong secret returns 401."""
        wrong_secret = "b" * 64
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
            "roles": ["end_user"],
            "scope": "tenant",
            "plan": "professional",
            "email": "tampered@test.com",
            "exp": now + timedelta(hours=1),
            "iat": now,
            "token_version": 2,
        }
        token = jwt.encode(payload, wrong_secret, algorithm="HS256")
        resp = client.get(
            "/api/v1/glossary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_malformed_token_rejected(self, client):
        """Garbage JWT string returns 401."""
        resp = client.get(
            "/api/v1/glossary",
            headers={"Authorization": "Bearer not.a.valid.jwt.at.all"},
        )
        assert resp.status_code == 401
