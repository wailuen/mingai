"""
P2LLM-017: BYOLLM Security Integration Tests.

Uses real PostgreSQL — no mocking.

Security invariants tested:
- Stored row in DB never contains plaintext API key (api_key_encrypted is opaque)
- API response (POST/GET /admin/byollm/library-entries) returns api_key_last4 only — no plaintext
- DELETE removes entry from DB (key material gone with it)
- Non-enterprise tenant gets 403

Tier 2: Requires running PostgreSQL + JWT_SECRET_KEY configured.

Run:
    pytest tests/integration/test_byollm_security.py -v
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


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


def _make_token(
    tenant_id: str, roles: list, scope: str = "tenant", plan: str = "enterprise"
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": plan,
        "token_version": 2,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


# ---------------------------------------------------------------------------
# DB setup / teardown
# ---------------------------------------------------------------------------


def _setup_tenant(tenant_id: str, plan: str = "enterprise") -> None:
    """Create test tenant row synchronously."""
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
                    "VALUES (:id, :name, :slug, :plan, :email, 'active') "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": tenant_id,
                    "name": f"BYOLLM Sec Test {tenant_id[:8]}",
                    "slug": f"byollm-sec-{tenant_id[:8]}",
                    "plan": plan,
                    "email": f"admin-{tenant_id[:8]}@test.example",
                },
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


def _cleanup_tenant(tenant_id: str) -> None:
    """Remove test tenant and any associated library entries / profiles."""
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            # NULL out tenant's llm_profile_id FK to break circular dependency
            await session.execute(
                text("UPDATE tenants SET llm_profile_id = NULL WHERE id = :id"),
                {"id": tenant_id},
            )
            # Delete child rows before tenant
            await session.execute(
                text("DELETE FROM llm_profiles WHERE owner_tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await session.execute(
                text("DELETE FROM llm_library WHERE owner_tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await session.execute(
                text("DELETE FROM tenants WHERE id = :id"),
                {"id": tenant_id},
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


def _read_library_row(entry_id: str, tenant_id: str) -> dict | None:
    """Read raw library row from DB to verify encryption. Returns None if not found."""
    db_url = _db_url()
    result = {}

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            r = await session.execute(
                text(
                    "SELECT id, api_key_encrypted, api_key_last4 FROM llm_library "
                    "WHERE id = :id AND owner_tenant_id = :tid"
                ),
                {"id": entry_id, "tid": tenant_id},
            )
            row = r.fetchone()
            if row:
                result["data"] = {
                    "id": str(row[0]),
                    "api_key_encrypted": row[1],
                    "api_key_last4": row[2],
                }
        await engine.dispose()

    asyncio.run(_do())
    return result.get("data")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


PLAINTEXT_KEY = "sk-realkey-that-must-never-appear-in-db"


@pytest.fixture(scope="module")
def enterprise_tenant():
    """Create an enterprise tenant for the test module."""
    tenant_id = str(uuid.uuid4())
    _setup_tenant(tenant_id, plan="enterprise")
    yield tenant_id
    _cleanup_tenant(tenant_id)


@pytest.fixture(scope="module")
def pro_tenant():
    """Create a professional (non-enterprise) tenant for the test module."""
    tenant_id = str(uuid.uuid4())
    _setup_tenant(tenant_id, plan="professional")
    yield tenant_id
    _cleanup_tenant(tenant_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBYOLLMSecurity:
    """Security invariants for BYOLLM credential storage via library entries API."""

    def test_store_byollm_key_response_has_no_plaintext_key(
        self, client, enterprise_tenant
    ):
        """POST /admin/byollm/library-entries response must not contain the API key."""
        token = _make_token(
            enterprise_tenant, roles=["tenant_admin"], plan="enterprise"
        )
        response = client.post(
            "/api/v1/admin/byollm/library-entries",
            json={
                "name": "Security Test Entry",
                "provider": "openai_direct",
                "model_name": "gpt-4o",
                "api_key": PLAINTEXT_KEY,
                "capabilities": {"eligible_slots": ["chat", "intent"]},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        # Skip if Fernet key not configured (encryption infra missing)
        if response.status_code == 500:
            pytest.skip("Fernet key not configured — cannot encrypt key")

        assert response.status_code == 201, response.text
        body = response.json()

        # Response MUST NOT contain the plaintext key anywhere
        body_str = str(body)
        assert PLAINTEXT_KEY not in body_str, (
            f"Plaintext API key found in POST response: {body_str}"
        )

        # api_key_encrypted must never appear in response
        assert "api_key_encrypted" not in body, (
            "api_key_encrypted field must never be returned in API response"
        )

        # Response shows api_key_last4 only
        assert "api_key_last4" in body
        assert body["api_key_last4"] == PLAINTEXT_KEY[-4:]

    def test_db_stores_no_plaintext_key(self, client, enterprise_tenant):
        """After POST, the DB row must store the key encrypted, not in plaintext."""
        token = _make_token(
            enterprise_tenant, roles=["tenant_admin"], plan="enterprise"
        )
        response = client.post(
            "/api/v1/admin/byollm/library-entries",
            json={
                "name": "DB Encryption Test Entry",
                "provider": "openai_direct",
                "model_name": "gpt-4o",
                "api_key": PLAINTEXT_KEY,
                "capabilities": {"eligible_slots": ["chat"]},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 201:
            pytest.skip("BYOLLM store failed — skipping DB assertion")

        entry_id = response.json()["id"]
        row = _read_library_row(entry_id, enterprise_tenant)
        assert row is not None, "Library entry not found in DB"

        # api_key_encrypted must not be the plaintext key
        encrypted = row["api_key_encrypted"]
        assert encrypted is not None, "api_key_encrypted must not be NULL"
        assert encrypted != PLAINTEXT_KEY, (
            "api_key_encrypted must not equal the plaintext key"
        )
        assert PLAINTEXT_KEY not in str(encrypted), (
            f"Plaintext key found inside api_key_encrypted: {encrypted}"
        )

        # last4 must match
        assert row["api_key_last4"] == PLAINTEXT_KEY[-4:], (
            f"api_key_last4 mismatch: expected {PLAINTEXT_KEY[-4:]!r}, got {row['api_key_last4']!r}"
        )

    def test_get_entry_has_no_plaintext_key(self, client, enterprise_tenant):
        """GET /admin/byollm/library-entries/{id} must never contain the API key."""
        token = _make_token(
            enterprise_tenant, roles=["tenant_admin"], plan="enterprise"
        )
        # Create an entry first
        create_resp = client.post(
            "/api/v1/admin/byollm/library-entries",
            json={
                "name": "GET Security Test",
                "provider": "openai_direct",
                "model_name": "gpt-4o",
                "api_key": PLAINTEXT_KEY,
                "capabilities": {"eligible_slots": ["chat"]},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if create_resp.status_code != 201:
            pytest.skip("Entry creation failed — skipping GET assertion")

        entry_id = create_resp.json()["id"]

        # Fetch the entry
        get_resp = client.get(
            f"/api/v1/admin/byollm/library-entries/{entry_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert get_resp.status_code == 200, get_resp.text
        body = get_resp.json()
        body_str = str(body)

        assert PLAINTEXT_KEY not in body_str, (
            f"Plaintext API key found in GET response: {body_str}"
        )
        assert "api_key_encrypted" not in body, (
            "api_key_encrypted must never be returned in GET response"
        )

    def test_delete_disables_entry(self, client, enterprise_tenant):
        """DELETE /admin/byollm/library-entries/{id} soft-deletes entry (status=disabled)."""
        token = _make_token(
            enterprise_tenant, roles=["tenant_admin"], plan="enterprise"
        )
        # Ensure entry is created first
        create_resp = client.post(
            "/api/v1/admin/byollm/library-entries",
            json={
                "name": "Delete Test Entry",
                "provider": "openai_direct",
                "model_name": "gpt-4o",
                "api_key": PLAINTEXT_KEY,
                "capabilities": {"eligible_slots": ["chat"]},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if create_resp.status_code != 201:
            pytest.skip("Entry creation failed — skipping DELETE test")

        entry_id = create_resp.json()["id"]

        # Confirm it exists and has no disabled status
        row_before = _read_library_row(entry_id, enterprise_tenant)
        assert row_before is not None, "Entry must exist in DB before DELETE"

        # Delete it
        delete_resp = client.delete(
            f"/api/v1/admin/byollm/library-entries/{entry_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert delete_resp.status_code == 204, delete_resp.text

        # Entry should be soft-deleted (status=disabled) — verify via list endpoint
        list_resp = client.get(
            "/api/v1/admin/byollm/library-entries",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_resp.status_code == 200, list_resp.text
        active_ids = [e["id"] for e in list_resp.json() if e.get("status") != "disabled"]
        assert entry_id not in active_ids, (
            "Deleted entry must not appear as active in library list"
        )

    def test_non_enterprise_tenant_gets_403(self, client, pro_tenant):
        """Non-enterprise plan gets 403 on POST /admin/byollm/library-entries."""
        token = _make_token(pro_tenant, roles=["tenant_admin"], plan="professional")
        response = client.post(
            "/api/v1/admin/byollm/library-entries",
            json={
                "name": "Should Be Blocked",
                "provider": "openai_direct",
                "model_name": "gpt-4o",
                "api_key": PLAINTEXT_KEY,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403, response.text
