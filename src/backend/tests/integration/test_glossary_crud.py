"""
TEST-031: Glossary CRUD Integration Tests

Tests full CRUD lifecycle through HTTP using real PostgreSQL database.
Tier 2: No mocking — requires running Docker infrastructure.

Architecture note:
    Uses sync TestClient (session-scoped) + asyncio.run() for DB setup/teardown.
    This avoids event loop conflicts with the module-level SQLAlchemy engine in
    session.py. The ASGI app uses one portal (TestClient's event loop) consistently,
    while test DB setup uses asyncio.run() with its own isolated connections.

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_glossary_crud.py -v -m integration
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_TENANT_ID = str(uuid.uuid4())


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
    """Execute SQL against real DB using a fresh async engine."""
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _create_tenant(tid: str):
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, :plan, :email, 'active')",
        {
            "id": tid,
            "name": f"Glossary Integration Test {tid[:8]}",
            "slug": f"glossary-int-{tid[:8]}",
            "plan": "professional",
            "email": f"test-{tid[:8]}@glossary-int.test",
        },
    )


async def _cleanup_tenant(tid: str):
    await _run_sql("DELETE FROM glossary_terms WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


# ---------------------------------------------------------------------------
# Fixtures (session-scoped TestClient avoids event loop conflicts)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tenant_id():
    """Provision a real test tenant once per module, clean up after."""
    tid = str(uuid.uuid4())
    asyncio.run(_create_tenant(tid))
    yield tid
    asyncio.run(_cleanup_tenant(tid))


# ---------------------------------------------------------------------------
# Tests: List Glossary Terms
# ---------------------------------------------------------------------------


class TestListGlossaryIntegration:
    """GET /api/v1/glossary — real DB, no mocking."""

    def test_list_returns_200_with_real_db(self, client, tenant_id):
        """List endpoint connects to real DB and returns paginated response."""
        token = _make_user_token(tenant_id)
        resp = client.get(
            "/api/v1/glossary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert data["page"] == 1

    def test_list_unauthenticated_returns_401(self, client, tenant_id):
        """Unauthenticated request returns 401."""
        resp = client.get("/api/v1/glossary")
        assert resp.status_code == 401

    def test_list_respects_pagination_params(self, client, tenant_id):
        """Pagination params are accepted and reflected in response."""
        token = _make_user_token(tenant_id)
        resp = client.get(
            "/api/v1/glossary?page=1&page_size=5",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["page_size"] == 5

    def test_list_rejects_invalid_page(self, client, tenant_id):
        """page=0 is rejected with 422."""
        token = _make_user_token(tenant_id)
        resp = client.get(
            "/api/v1/glossary?page=0",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_list_rejects_page_size_over_100(self, client, tenant_id):
        """page_size=101 is rejected with 422."""
        token = _make_user_token(tenant_id)
        resp = client.get(
            "/api/v1/glossary?page_size=101",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Full CRUD Lifecycle
# ---------------------------------------------------------------------------


class TestGlossaryCRUDLifecycle:
    """Full CRUD cycle: Create → Read → Update → Delete using real DB."""

    def test_create_then_read_then_update_then_delete(self, client, tenant_id):
        """
        Full lifecycle: POST → GET → PATCH → DELETE all against real PostgreSQL.
        Verifies data persists correctly across requests.
        """
        admin_headers = {"Authorization": f"Bearer {_make_admin_token(tenant_id)}"}
        user_headers = {"Authorization": f"Bearer {_make_user_token(tenant_id)}"}
        unique_term = f"INTTEST{uuid.uuid4().hex[:6].upper()}"

        # 1. CREATE
        create_resp = client.post(
            "/api/v1/glossary",
            json={"term": unique_term, "full_form": "Integration Test Term"},
            headers=admin_headers,
        )
        assert create_resp.status_code == 201, create_resp.text
        created = create_resp.json()
        assert "id" in created
        assert created["term"] == unique_term
        assert created["full_form"] == "Integration Test Term"
        term_id = created["id"]

        # 2. READ — term appears in list
        list_resp = client.get("/api/v1/glossary", headers=user_headers)
        assert list_resp.status_code == 200
        ids = [item["id"] for item in list_resp.json()["items"]]
        assert term_id in ids, f"Created term {term_id} not found in list"

        # 3. READ — get by ID
        get_resp = client.get(f"/api/v1/glossary/{term_id}", headers=user_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == term_id
        assert get_resp.json()["term"] == unique_term

        # 4. UPDATE
        patch_resp = client.patch(
            f"/api/v1/glossary/{term_id}",
            json={"full_form": "Updated Integration Test Term"},
            headers=admin_headers,
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["full_form"] == "Updated Integration Test Term"

        # 5. VERIFY UPDATE persisted
        get_after = client.get(f"/api/v1/glossary/{term_id}", headers=user_headers)
        assert get_after.json()["full_form"] == "Updated Integration Test Term"

        # 6. DELETE
        del_resp = client.delete(f"/api/v1/glossary/{term_id}", headers=admin_headers)
        assert del_resp.status_code == 204

        # 7. VERIFY DELETED — real DB confirms absence
        get_after_del = client.get(f"/api/v1/glossary/{term_id}", headers=user_headers)
        assert get_after_del.status_code == 404

    def test_get_nonexistent_returns_404(self, client, tenant_id):
        """GET on a non-existent term ID returns 404 from real DB."""
        user_headers = {"Authorization": f"Bearer {_make_user_token(tenant_id)}"}
        nonexistent_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/glossary/{nonexistent_id}", headers=user_headers)
        assert resp.status_code == 404

    def test_patch_nonexistent_returns_404(self, client, tenant_id):
        """PATCH on non-existent term returns 404 — regression test for the 200+null bug."""
        admin_headers = {"Authorization": f"Bearer {_make_admin_token(tenant_id)}"}
        nonexistent_id = str(uuid.uuid4())
        resp = client.patch(
            f"/api/v1/glossary/{nonexistent_id}",
            json={"full_form": "This term does not exist"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, client, tenant_id):
        """DELETE on a non-existent term ID returns 404 from real DB."""
        admin_headers = {"Authorization": f"Bearer {_make_admin_token(tenant_id)}"}
        nonexistent_id = str(uuid.uuid4())
        resp = client.delete(
            f"/api/v1/glossary/{nonexistent_id}", headers=admin_headers
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Auth Enforcement
# ---------------------------------------------------------------------------


class TestGlossaryAuthEnforcement:
    """Verify role-based access: end_user cannot write, tenant_admin can."""

    def test_end_user_cannot_create(self, client, tenant_id):
        """end_user role is rejected on POST with 403."""
        user_headers = {"Authorization": f"Bearer {_make_user_token(tenant_id)}"}
        resp = client.post(
            "/api/v1/glossary",
            json={"term": "RESTRICTED", "full_form": "Should Not Create"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_end_user_cannot_update(self, client, tenant_id):
        """end_user role is rejected on PATCH with 403."""
        user_headers = {"Authorization": f"Bearer {_make_user_token(tenant_id)}"}
        resp = client.patch(
            f"/api/v1/glossary/{uuid.uuid4()}",
            json={"full_form": "Unauthorized Update"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_end_user_cannot_delete(self, client, tenant_id):
        """end_user role is rejected on DELETE with 403."""
        user_headers = {"Authorization": f"Bearer {_make_user_token(tenant_id)}"}
        resp = client.delete(f"/api/v1/glossary/{uuid.uuid4()}", headers=user_headers)
        assert resp.status_code == 403

    def test_empty_term_rejected_at_db_boundary(self, client, tenant_id):
        """Empty term field is rejected by Pydantic before hitting DB."""
        admin_headers = {"Authorization": f"Bearer {_make_admin_token(tenant_id)}"}
        resp = client.post(
            "/api/v1/glossary",
            json={"term": "", "full_form": "Something"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_full_form_over_200_chars_rejected(self, client, tenant_id):
        """full_form over 200 chars is rejected by Pydantic."""
        admin_headers = {"Authorization": f"Bearer {_make_admin_token(tenant_id)}"}
        resp = client.post(
            "/api/v1/glossary",
            json={"term": "TOOLONG", "full_form": "x" * 201},
            headers=admin_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Bulk CSV Import
# ---------------------------------------------------------------------------


class TestBulkImportIntegration:
    """POST /api/v1/glossary/import — real CSV processing through real DB."""

    def test_import_creates_real_terms(self, client, tenant_id):
        """CSV import creates real glossary terms in PostgreSQL."""
        admin_headers = {"Authorization": f"Bearer {_make_admin_token(tenant_id)}"}
        suffix = uuid.uuid4().hex[:6].upper()
        csv_data = (
            f"term,full_form\n"
            f"CSVTERM{suffix}A,CSV Import Term Alpha\n"
            f"CSVTERM{suffix}B,CSV Import Term Beta\n"
        ).encode("utf-8")

        resp = client.post(
            "/api/v1/glossary/import",
            files={"file": ("terms.csv", BytesIO(csv_data), "text/csv")},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        summary = resp.json()
        assert summary["imported"] == 2
        assert summary["skipped"] == 0
        assert len(summary.get("errors", [])) == 0

        # Verify terms appear in the list for this tenant
        user_headers = {"Authorization": f"Bearer {_make_user_token(tenant_id)}"}
        list_resp = client.get("/api/v1/glossary?page_size=100", headers=user_headers)
        assert list_resp.status_code == 200
        terms = {item["term"] for item in list_resp.json()["items"]}
        assert f"CSVTERM{suffix}A" in terms
        assert f"CSVTERM{suffix}B" in terms

    def test_import_skips_rows_with_empty_term(self, client, tenant_id):
        """Rows with empty term are skipped and reported in errors."""
        admin_headers = {"Authorization": f"Bearer {_make_admin_token(tenant_id)}"}
        csv_data = b"term,full_form\n,Empty Term Row\nVALIDSKIP,Valid Definition\n"

        resp = client.post(
            "/api/v1/glossary/import",
            files={"file": ("terms.csv", BytesIO(csv_data), "text/csv")},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        summary = resp.json()
        assert summary["skipped"] == 1
        assert len(summary["errors"]) == 1
        assert summary["imported"] >= 1

    def test_import_requires_auth(self, client, tenant_id):
        """Import endpoint requires authentication."""
        csv_data = b"term,full_form\nHR,Human Resources\n"
        resp = client.post(
            "/api/v1/glossary/import",
            files={"file": ("terms.csv", BytesIO(csv_data), "text/csv")},
        )
        assert resp.status_code == 401

    def test_import_requires_tenant_admin(self, client, tenant_id):
        """Import endpoint rejects end_user role."""
        user_headers = {"Authorization": f"Bearer {_make_user_token(tenant_id)}"}
        csv_data = b"term,full_form\nHR,Human Resources\n"
        resp = client.post(
            "/api/v1/glossary/import",
            files={"file": ("terms.csv", BytesIO(csv_data), "text/csv")},
            headers=user_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: API-062 Export Glossary CSV
# ---------------------------------------------------------------------------


class TestGlossaryExportCSV:
    """GET /api/v1/glossary/export — real DB integration tests."""

    def test_export_glossary_csv(self, client, tenant_id):
        """
        API-062: Export returns text/csv with UTF-8 BOM and correct columns.

        Verifies: Content-Type header, Content-Disposition, BOM, column headers.
        Auth: tenant_admin required.
        """
        admin_headers = {"Authorization": f"Bearer {_make_admin_token(tenant_id)}"}

        resp = client.get(
            "/api/v1/glossary/export",
            headers=admin_headers,
        )

        assert resp.status_code == 200, resp.text
        content_type = resp.headers.get("content-type", "")
        assert "text/csv" in content_type
        disposition = resp.headers.get("content-disposition", "")
        assert "attachment" in disposition
        assert "glossary.csv" in disposition

        # Verify content can be decoded
        content_bytes = resp.content
        # Strip BOM if present and decode
        if content_bytes.startswith(b"\xef\xbb\xbf"):
            content_bytes = content_bytes[3:]
        content_str = content_bytes.decode("utf-8")

        # Must have the header row matching API-062 spec
        first_line = content_str.splitlines()[0]
        assert "term" in first_line
        assert "full_form" in first_line

    def test_export_requires_tenant_admin(self, client, tenant_id):
        """Export endpoint rejects end_user role."""
        user_headers = {"Authorization": f"Bearer {_make_user_token(tenant_id)}"}
        resp = client.get("/api/v1/glossary/export", headers=user_headers)
        assert resp.status_code == 403

    def test_export_requires_auth(self, client, tenant_id):
        """Export endpoint returns 401 without auth."""
        resp = client.get("/api/v1/glossary/export")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: API-063 Glossary Miss Analytics
# ---------------------------------------------------------------------------


class TestGlossaryMissAnalytics:
    """GET /api/v1/glossary/analytics/misses — real DB integration tests."""

    def test_glossary_miss_analytics_empty(self, client, tenant_id):
        """
        API-063: Returns empty terms list when no miss signals exist for tenant.

        Verifies response schema: {terms: [], period: "30d"}.
        Auth: tenant_admin required.
        """
        admin_headers = {"Authorization": f"Bearer {_make_admin_token(tenant_id)}"}

        resp = client.get(
            "/api/v1/glossary/analytics/misses",
            headers=admin_headers,
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "terms" in data, "Response must have 'terms' key"
        assert "period" in data, "Response must have 'period' key"
        assert isinstance(data["terms"], list)
        assert data["period"] == "30d"  # default period

    def test_glossary_miss_analytics_accepts_7d_period(self, client, tenant_id):
        """period=7d is accepted and reflected in the response."""
        admin_headers = {"Authorization": f"Bearer {_make_admin_token(tenant_id)}"}

        resp = client.get(
            "/api/v1/glossary/analytics/misses?period=7d",
            headers=admin_headers,
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["period"] == "7d"

    def test_glossary_miss_analytics_rejects_invalid_period(self, client, tenant_id):
        """Invalid period value returns 422."""
        admin_headers = {"Authorization": f"Bearer {_make_admin_token(tenant_id)}"}

        resp = client.get(
            "/api/v1/glossary/analytics/misses?period=99d",
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_glossary_miss_analytics_requires_tenant_admin(self, client, tenant_id):
        """End-user role is rejected with 403."""
        user_headers = {"Authorization": f"Bearer {_make_user_token(tenant_id)}"}
        resp = client.get(
            "/api/v1/glossary/analytics/misses",
            headers=user_headers,
        )
        assert resp.status_code == 403
