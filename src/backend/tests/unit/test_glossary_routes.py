"""
Unit tests for glossary routes (API-066 to API-075).

Tests glossary CRUD and bulk import endpoints.
Tier 1: Fast, isolated, uses mocking.
"""
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"


def _make_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "12345678-1234-5678-1234-567812345679",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": "admin@tenant.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_user_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "user-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["end_user"],
        "scope": "tenant",
        "plan": "professional",
        "email": "user@tenant.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


@pytest.fixture
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture
def client(env_vars):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {_make_admin_token()}"}


@pytest.fixture
def user_headers():
    return {"Authorization": f"Bearer {_make_user_token()}"}


class TestListGlossary:
    """GET /api/v1/glossary"""

    def test_list_glossary_requires_auth(self, client):
        resp = client.get("/api/v1/glossary")
        assert resp.status_code == 401

    def test_list_glossary_returns_paginated(self, client, user_headers):
        with patch(
            "app.modules.glossary.routes.list_glossary_db", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = {
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 20,
            }
            resp = client.get("/api/v1/glossary", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data

    def test_list_glossary_pagination_validation(self, client, user_headers):
        resp = client.get("/api/v1/glossary?page=0", headers=user_headers)
        assert resp.status_code == 422

    def test_list_glossary_page_size_max(self, client, user_headers):
        resp = client.get("/api/v1/glossary?page_size=101", headers=user_headers)
        assert resp.status_code == 422


class TestCreateGlossaryTerm:
    """POST /api/v1/glossary - tenant admin only."""

    def test_create_term_requires_auth(self, client):
        resp = client.post(
            "/api/v1/glossary", json={"term": "HR", "full_form": "Human Resources"}
        )
        assert resp.status_code == 401

    def test_create_term_requires_tenant_admin(self, client, user_headers):
        resp = client.post(
            "/api/v1/glossary",
            json={"term": "HR", "full_form": "Human Resources"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_create_term_returns_created(self, client, admin_headers):
        with patch(
            "app.modules.glossary.routes.create_glossary_term_db",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = {
                "id": "term-1",
                "term": "HR",
                "full_form": "Human Resources",
                "aliases": [],
            }
            resp = client.post(
                "/api/v1/glossary",
                json={"term": "HR", "full_form": "Human Resources"},
                headers=admin_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data

    def test_create_term_rejects_empty_term(self, client, admin_headers):
        resp = client.post(
            "/api/v1/glossary",
            json={"term": "", "full_form": "Some definition"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_create_term_rejects_full_form_over_200_chars(self, client, admin_headers):
        resp = client.post(
            "/api/v1/glossary",
            json={"term": "HR", "full_form": "x" * 201},
            headers=admin_headers,
        )
        assert resp.status_code == 422


class TestGetGlossaryTerm:
    """GET /api/v1/glossary/{id}"""

    def test_get_term_requires_auth(self, client):
        resp = client.get("/api/v1/glossary/term-1")
        assert resp.status_code == 401

    def test_get_term_returns_data(self, client, user_headers):
        import uuid as _uuid

        valid_id = str(_uuid.uuid4())
        with patch(
            "app.modules.glossary.routes.get_glossary_term_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "id": valid_id,
                "term": "HR",
                "definition": "Human Resources",
            }
            resp = client.get(f"/api/v1/glossary/{valid_id}", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == valid_id

    def test_get_term_returns_404(self, client, user_headers):
        with patch(
            "app.modules.glossary.routes.get_glossary_term_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None
            resp = client.get("/api/v1/glossary/nonexistent", headers=user_headers)
        assert resp.status_code == 404


class TestUpdateGlossaryTerm:
    """PATCH /api/v1/glossary/{id}"""

    def test_update_term_requires_tenant_admin(self, client, user_headers):
        resp = client.patch(
            "/api/v1/glossary/term-1",
            json={"full_form": "Updated definition"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_update_term_returns_updated(self, client, admin_headers):
        import uuid as _uuid
        from unittest.mock import MagicMock
        from app.core.session import get_async_session
        from app.main import app

        valid_id = str(_uuid.uuid4())
        before_state = {"id": valid_id, "full_form": "Human Resources"}
        updated_state = {"id": valid_id, "full_form": "Updated Human Resources"}

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        async def _override():
            yield mock_session

        app.dependency_overrides[get_async_session] = _override
        try:
            with patch(
                "app.modules.glossary.routes.get_glossary_term_db",
                new_callable=AsyncMock,
                return_value=before_state,
            ), patch(
                "app.modules.glossary.routes.update_glossary_term_db",
                new_callable=AsyncMock,
                return_value=updated_state,
            ), patch(
                "app.modules.glossary.routes._invalidate_glossary_cache",
                new_callable=AsyncMock,
            ):
                resp = client.patch(
                    f"/api/v1/glossary/{valid_id}",
                    json={"full_form": "Updated Human Resources"},
                    headers=admin_headers,
                )
        finally:
            app.dependency_overrides.pop(get_async_session, None)
        assert resp.status_code == 200


class TestDeleteGlossaryTerm:
    """DELETE /api/v1/glossary/{id}"""

    def test_delete_term_requires_tenant_admin(self, client, user_headers):
        resp = client.delete("/api/v1/glossary/term-1", headers=user_headers)
        assert resp.status_code == 403

    def test_delete_term_returns_204(self, client, admin_headers):
        # Must use a valid UUID — the route validates uuid.UUID(term_id) before any DB call
        valid_term_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with patch(
            "app.modules.glossary.routes.delete_glossary_term_db",
            new_callable=AsyncMock,
        ) as mock_del:
            mock_del.return_value = True
            resp = client.delete(
                f"/api/v1/glossary/{valid_term_id}", headers=admin_headers
            )
        assert resp.status_code == 204

    def test_delete_term_returns_404(self, client, admin_headers):
        with patch(
            "app.modules.glossary.routes.delete_glossary_term_db",
            new_callable=AsyncMock,
        ) as mock_del:
            mock_del.return_value = False
            resp = client.delete("/api/v1/glossary/nonexistent", headers=admin_headers)
        assert resp.status_code == 404


class TestBulkImportGlossary:
    """POST /api/v1/glossary/import - bulk CSV import."""

    def test_import_requires_auth(self, client):
        csv_data = b"term,definition\nHR,Human Resources"
        resp = client.post(
            "/api/v1/glossary/import",
            files={"file": ("terms.csv", BytesIO(csv_data), "text/csv")},
        )
        assert resp.status_code == 401

    def test_import_requires_tenant_admin(self, client, user_headers):
        csv_data = b"term,definition\nHR,Human Resources"
        resp = client.post(
            "/api/v1/glossary/import",
            files={"file": ("terms.csv", BytesIO(csv_data), "text/csv")},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_import_csv_returns_summary(self, client, admin_headers):
        with patch(
            "app.modules.glossary.routes.bulk_import_glossary", new_callable=AsyncMock
        ) as mock_import:
            mock_import.return_value = {
                "imported": 2,
                "skipped": 0,
                "errors": [],
            }
            csv_data = b"term,definition\nHR,Human Resources\nIT,Information Technology"
            resp = client.post(
                "/api/v1/glossary/import",
                files={"file": ("terms.csv", BytesIO(csv_data), "text/csv")},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "imported" in data
