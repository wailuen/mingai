"""
Integration tests for audit log endpoints (API-087).

Tests against real PostgreSQL — no mocking of DB layer.

Prerequisites:
    docker-compose up -d  # ensure PostgreSQL + Redis are running

Run:
    pytest tests/integration/test_audit_log_routes.py -v --timeout=30
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _create_test_tenant() -> str:
    tid = str(uuid.uuid4())
    slug = f"auditlog-test-{tid[:8]}"
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"AuditLog Test {tid[:8]}",
            "slug": slug,
            "email": f"admin-{tid[:8]}@auditlog-int.test",
        },
    )
    return tid


async def _create_test_user(tenant_id: str) -> str:
    uid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO users (id, tenant_id, email, name, role, status) "
        "VALUES (:id, :tenant_id, :email, :name, 'admin', 'active')",
        {
            "id": uid,
            "tenant_id": tenant_id,
            "email": f"user-{uid[:8]}@auditlog-int.test",
            "name": "AuditLog Test User",
        },
    )
    return uid


async def _create_audit_entry(
    tenant_id: str, user_id: str, action: str, resource_type: str
) -> str:
    eid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO audit_log (id, tenant_id, user_id, action, resource_type, details) "
        "VALUES (:id, :tenant_id, :user_id, :action, :resource_type, '{}'::jsonb)",
        {
            "id": eid,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type,
        },
    )
    return eid


async def _cleanup_tenant(tid: str):
    await _run_sql("DELETE FROM audit_log WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM users WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :tid", {"tid": tid})


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _make_tenant_admin_token(tenant_id: str) -> str:
    from datetime import timedelta

    from jose import jwt

    secret = os.environ.get("JWT_SECRET_KEY", "test-secret-" + "a" * 50)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": f"admin-{tenant_id[:8]}",
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": f"admin-{tenant_id[:8]}@test.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuditLogEmpty:
    """GET /admin/audit-log — empty state."""

    def test_audit_log_empty(self, client):
        """Returns empty items and total=0 for a fresh tenant."""
        tid = asyncio.run(_create_test_tenant())
        try:
            token = _make_tenant_admin_token(tid)
            headers = {"Authorization": f"Bearer {token}"}

            resp = client.get("/api/v1/admin/audit-log", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["items"] == []
            assert data["total"] == 0
            assert data["page"] == 1
            assert "page_size" in data
        finally:
            asyncio.run(_cleanup_tenant(tid))


class TestAuditLogWithEntries:
    """GET /admin/audit-log — with entries."""

    def test_audit_log_returns_entries(self, client):
        """Returns entries inserted for the tenant."""
        tid = asyncio.run(_create_test_tenant())
        uid = asyncio.run(_create_test_user(tid))
        try:
            asyncio.run(_create_audit_entry(tid, uid, "user.invite", "user"))
            asyncio.run(_create_audit_entry(tid, uid, "settings.update", "workspace"))

            token = _make_tenant_admin_token(tid)
            headers = {"Authorization": f"Bearer {token}"}

            resp = client.get("/api/v1/admin/audit-log", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 2
            assert len(data["items"]) == 2

            item = data["items"][0]
            assert "id" in item
            assert "actor_id" in item
            assert "actor_email" in item
            assert "action" in item
            assert "resource_type" in item
            assert "metadata" in item
            assert "created_at" in item
        finally:
            asyncio.run(_cleanup_tenant(tid))

    def test_audit_log_filter_by_action(self, client):
        """action filter returns only matching entries."""
        tid = asyncio.run(_create_test_tenant())
        uid = asyncio.run(_create_test_user(tid))
        try:
            asyncio.run(_create_audit_entry(tid, uid, "user.invite", "user"))
            asyncio.run(_create_audit_entry(tid, uid, "settings.update", "workspace"))

            token = _make_tenant_admin_token(tid)
            headers = {"Authorization": f"Bearer {token}"}

            resp = client.get(
                "/api/v1/admin/audit-log?action=user.invite", headers=headers
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1
            assert data["items"][0]["action"] == "user.invite"
        finally:
            asyncio.run(_cleanup_tenant(tid))

    def test_audit_log_tenant_isolation(self, client):
        """Entries from another tenant are not returned."""
        tid1 = asyncio.run(_create_test_tenant())
        tid2 = asyncio.run(_create_test_tenant())
        uid1 = asyncio.run(_create_test_user(tid1))
        uid2 = asyncio.run(_create_test_user(tid2))
        try:
            asyncio.run(_create_audit_entry(tid1, uid1, "action.tenant1", "resource"))
            asyncio.run(_create_audit_entry(tid2, uid2, "action.tenant2", "resource"))

            # Query as tenant1 admin — should only see tenant1 entries
            token = _make_tenant_admin_token(tid1)
            headers = {"Authorization": f"Bearer {token}"}

            resp = client.get("/api/v1/admin/audit-log", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            actions = [item["action"] for item in data["items"]]
            assert "action.tenant1" in actions
            assert "action.tenant2" not in actions
        finally:
            asyncio.run(_cleanup_tenant(tid1))
            asyncio.run(_cleanup_tenant(tid2))
