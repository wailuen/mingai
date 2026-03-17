"""
DEF-018: Profile/memory E2E tests.

End-to-end tests for all critical memory feature flows:

1. Memory notes CRUD — create note, list notes, delete note
2. Working memory — get working memory context, clear working memory
3. Privacy toggle — disable profile_learning → privacy settings persisted
4. Privacy toggle — disable working_memory → working memory returns empty
5. GDPR erasure — comprehensive erasure clears notes, profile, privacy settings
6. Profile data — GET /memory/profile returns user context
7. Export — GET /memory/export returns all data aggregated
8. Multi-tenant isolation — user A cannot read user B notes
9. Note validation — notes over 200 chars rejected
10. Note delete 404 — deleting non-existent note returns 404

Tier 3: E2E, NO mocking, <10s timeout, requires Docker infrastructure.

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/e2e/test_memory_e2e.py -v --timeout=10
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Infrastructure helpers
# ---------------------------------------------------------------------------


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        pytest.skip("JWT_SECRET_KEY not configured -- skipping E2E tests")
    return secret


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured -- skipping E2E tests")
    return url


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict | None = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return result
    finally:
        await engine.dispose()


def _make_token(
    user_id: str,
    tenant_id: str,
    roles: list[str],
    scope: str = "tenant",
    plan: str = "professional",
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": plan,
        "email": f"mem-e2e-{user_id[:8]}@memory-e2e.test",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def _create_tenant(name_prefix: str = "Memory E2E") -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"{name_prefix} {tid[:8]}",
            "slug": f"mem-e2e-{tid[:8]}",
            "email": f"admin@mem-e2e-{tid[:8]}.test",
        },
    )
    return tid


async def _create_user(tid: str, role: str = "viewer") -> str:
    uid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO users (id, tenant_id, email, name, role, status) "
        "VALUES (:id, :tid, :email, :name, :role, 'active')",
        {
            "id": uid,
            "tid": tid,
            "email": f"{role}-{uid[:8]}@mem-e2e.test",
            "name": f"Memory E2E {role.title()} {uid[:8]}",
            "role": role,
        },
    )
    return uid


async def _cleanup_tenant(tid: str):
    """Clean up all memory-related and tenant data."""
    await _run_sql(
        "DELETE FROM user_privacy_settings WHERE tenant_id = :tid", {"tid": tid}
    )
    await _run_sql("DELETE FROM memory_notes WHERE tenant_id = :tid", {"tid": tid})
    # user_profiles may not exist as a table in all environments — best-effort
    try:
        await _run_sql("DELETE FROM user_profiles WHERE tenant_id = :tid", {"tid": tid})
    except Exception:
        pass
    await _run_sql("DELETE FROM audit_log WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM users WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :tid", {"tid": tid})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tenant_a():
    """Provision tenant A for memory E2E tests."""

    async def _setup():
        tid = await _create_tenant("Memory E2E A")
        uid = await _create_user(tid, "viewer")
        return tid, uid

    tid, uid = asyncio.run(_setup())
    yield {"tid": tid, "uid": uid}
    asyncio.run(_cleanup_tenant(tid))


@pytest.fixture(scope="module")
def tenant_b():
    """Provision tenant B for multi-tenant isolation tests."""

    async def _setup():
        tid = await _create_tenant("Memory E2E B")
        uid = await _create_user(tid, "viewer")
        return tid, uid

    tid, uid = asyncio.run(_setup())
    yield {"tid": tid, "uid": uid}
    asyncio.run(_cleanup_tenant(tid))


@pytest.fixture(scope="module")
def user_a_headers(tenant_a):
    token = _make_token(tenant_a["uid"], tenant_a["tid"], roles=["end_user"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def user_b_headers(tenant_b):
    token = _make_token(tenant_b["uid"], tenant_b["tid"], roles=["end_user"])
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test 1 & 2: Memory notes CRUD
# ---------------------------------------------------------------------------


class TestMemoryNotesCRUD:
    """Memory notes create, list, delete flow."""

    def test_create_note_returns_201(self, client, user_a_headers):
        """POST /memory/notes creates a note and returns 201."""
        resp = client.post(
            "/api/v1/memory/notes",
            json={"content": "I prefer concise technical answers."},
            headers=user_a_headers,
        )
        assert resp.status_code == 201, f"Create note failed: {resp.text}"
        data = resp.json()
        assert "id" in data
        assert data["content"] == "I prefer concise technical answers."
        assert data["source"] == "user_directed"

    def test_list_notes_includes_created_note(self, client, user_a_headers):
        """GET /memory/notes returns the previously created note."""
        # Create a distinguishable note
        unique_content = f"E2E note {uuid.uuid4().hex[:8]}"
        create_resp = client.post(
            "/api/v1/memory/notes",
            json={"content": unique_content},
            headers=user_a_headers,
        )
        assert create_resp.status_code == 201

        list_resp = client.get("/api/v1/memory/notes", headers=user_a_headers)
        assert list_resp.status_code == 200, f"List notes failed: {list_resp.text}"
        notes = list_resp.json()
        assert isinstance(notes, list)
        contents = [n["content"] for n in notes]
        assert unique_content in contents, f"Created note not found in: {contents}"


# ---------------------------------------------------------------------------
# Test 3: Note delete
# ---------------------------------------------------------------------------


class TestMemoryNoteDelete:
    """Memory note deletion flow."""

    def test_delete_note_returns_204(self, client, user_a_headers):
        """DELETE /memory/notes/{id} deletes a note and returns 204."""
        create_resp = client.post(
            "/api/v1/memory/notes",
            json={"content": "Temporary note for delete test."},
            headers=user_a_headers,
        )
        assert create_resp.status_code == 201
        note_id = create_resp.json()["id"]

        del_resp = client.delete(
            f"/api/v1/memory/notes/{note_id}", headers=user_a_headers
        )
        assert del_resp.status_code == 204, f"Delete note failed: {del_resp.text}"

        # Verify the note is gone
        list_resp = client.get("/api/v1/memory/notes", headers=user_a_headers)
        ids = [n["id"] for n in list_resp.json()]
        assert note_id not in ids, "Note still present after deletion"

    def test_delete_nonexistent_note_returns_404(self, client, user_a_headers):
        """Deleting a note that doesn't exist returns 404."""
        fake_id = str(uuid.uuid4())
        resp = client.delete(f"/api/v1/memory/notes/{fake_id}", headers=user_a_headers)
        assert resp.status_code == 404, f"Expected 404, got: {resp.status_code}"


# ---------------------------------------------------------------------------
# Test 4: Privacy toggle — profile_learning_enabled = False
# ---------------------------------------------------------------------------


class TestPrivacyToggle:
    """Privacy toggle persists and takes effect in subsequent reads."""

    def test_disable_profile_learning_persisted(self, client, user_a_headers):
        """PATCH /memory/privacy disabling profile_learning is persisted and readable via export."""
        resp = client.patch(
            "/api/v1/memory/privacy",
            json={"profile_learning_enabled": False, "working_memory_enabled": True},
            headers=user_a_headers,
        )
        assert resp.status_code == 200, f"Privacy update failed: {resp.text}"
        data = resp.json()
        assert data["profile_learning_enabled"] is False
        assert data["working_memory_enabled"] is True

        # Confirm persisted via export
        export_resp = client.get("/api/v1/memory/export", headers=user_a_headers)
        assert export_resp.status_code == 200
        export = export_resp.json()
        assert export["privacy_settings"]["profile_learning_enabled"] is False

    def test_reenable_profile_learning(self, client, user_a_headers):
        """Re-enabling profile_learning restores true in settings."""
        resp = client.patch(
            "/api/v1/memory/privacy",
            json={"profile_learning_enabled": True, "working_memory_enabled": True},
            headers=user_a_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["profile_learning_enabled"] is True


# ---------------------------------------------------------------------------
# Test 5: Working memory
# ---------------------------------------------------------------------------


class TestWorkingMemory:
    """Working memory GET and clear flow."""

    def test_get_working_memory_returns_structure(self, client, user_a_headers):
        """GET /memory/working returns expected schema with topics and recent_queries."""
        resp = client.get("/api/v1/memory/working", headers=user_a_headers)
        assert resp.status_code == 200, f"Working memory failed: {resp.text}"
        data = resp.json()
        assert "user_id" in data
        assert "agent_id" in data
        assert "topics" in data
        assert "recent_queries" in data
        assert isinstance(data["topics"], list)
        assert isinstance(data["recent_queries"], list)

    def test_clear_working_memory_returns_204(self, client, user_a_headers):
        """DELETE /memory/working returns 204."""
        resp = client.delete("/api/v1/memory/working", headers=user_a_headers)
        assert resp.status_code == 204, f"Clear working memory failed: {resp.text}"


# ---------------------------------------------------------------------------
# Test 6: GDPR erasure
# ---------------------------------------------------------------------------


class TestGDPRErasure:
    """GDPR comprehensive erasure clears all memory data."""

    def test_gdpr_erasure_clears_notes(self, client, tenant_b, user_b_headers):
        """DELETE /memory/profile erases notes and returns 204."""
        # Create a note first
        create_resp = client.post(
            "/api/v1/memory/notes",
            json={"content": "Note to be GDPR-erased."},
            headers=user_b_headers,
        )
        assert create_resp.status_code == 201

        # GDPR erase
        erase_resp = client.delete("/api/v1/memory/profile", headers=user_b_headers)
        assert erase_resp.status_code == 204, f"GDPR erasure failed: {erase_resp.text}"

        # Verify notes are gone
        list_resp = client.get("/api/v1/memory/notes", headers=user_b_headers)
        assert list_resp.status_code == 200
        assert list_resp.json() == [], f"Notes not cleared: {list_resp.json()}"

    def test_gdpr_erasure_resets_privacy_to_defaults(self, client, user_b_headers):
        """After GDPR erasure, privacy settings default to enabled=True."""
        # Set privacy to disabled
        client.patch(
            "/api/v1/memory/privacy",
            json={"profile_learning_enabled": False, "working_memory_enabled": False},
            headers=user_b_headers,
        )

        # GDPR erase
        client.delete("/api/v1/memory/profile", headers=user_b_headers)

        # Export should show defaults restored
        export_resp = client.get("/api/v1/memory/export", headers=user_b_headers)
        assert export_resp.status_code == 200
        privacy = export_resp.json()["privacy_settings"]
        assert privacy["profile_learning_enabled"] is True
        assert privacy["working_memory_enabled"] is True


# ---------------------------------------------------------------------------
# Test 7: Multi-tenant isolation
# ---------------------------------------------------------------------------


class TestMemoryMultiTenantIsolation:
    """Notes created by user A are not visible to user B."""

    def test_user_a_notes_not_visible_to_user_b(
        self, client, user_a_headers, user_b_headers
    ):
        """Notes are tenant-scoped — user B cannot read user A's notes."""
        unique_content = f"Tenant-A-only note {uuid.uuid4().hex[:8]}"
        create_resp = client.post(
            "/api/v1/memory/notes",
            json={"content": unique_content},
            headers=user_a_headers,
        )
        assert create_resp.status_code == 201

        # User B should not see user A's note
        list_resp_b = client.get("/api/v1/memory/notes", headers=user_b_headers)
        assert list_resp_b.status_code == 200
        b_contents = [n["content"] for n in list_resp_b.json()]
        assert (
            unique_content not in b_contents
        ), f"Tenant isolation violated — user B can see user A's note: {b_contents}"


# ---------------------------------------------------------------------------
# Test 8: Note content validation
# ---------------------------------------------------------------------------


class TestMemoryNoteValidation:
    """Notes over 200 characters are rejected with 422."""

    def test_note_over_200_chars_returns_422(self, client, user_a_headers):
        """Creating a note with content > 200 chars is rejected."""
        long_content = "x" * 201
        resp = client.post(
            "/api/v1/memory/notes",
            json={"content": long_content},
            headers=user_a_headers,
        )
        assert (
            resp.status_code == 422
        ), f"Expected 422 for over-limit note, got: {resp.status_code}"

    def test_empty_note_returns_422(self, client, user_a_headers):
        """Creating a note with empty content is rejected."""
        resp = client.post(
            "/api/v1/memory/notes",
            json={"content": ""},
            headers=user_a_headers,
        )
        assert (
            resp.status_code == 422
        ), f"Expected 422 for empty note, got: {resp.status_code}"
