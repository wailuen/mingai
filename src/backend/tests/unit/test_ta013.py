"""
Unit tests for TA-013: Admin glossary miss-signals endpoint.

  GET /admin/glossary/miss-signals

Returns top unresolved terms with query_count and example_queries (up to 3,
40 chars max each).

Tier 1: Fast, isolated.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "b" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = str(uuid.uuid4())

_ADMIN_MISS_SIGNALS_URL = "/api/v1/admin/glossary/miss-signals"


def _make_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "admin-user-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": "admin@test.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_viewer_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "viewer-user-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["viewer"],
        "scope": "tenant",
        "plan": "professional",
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


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_make_admin_token()}"}


def _viewer_headers() -> dict:
    return {"Authorization": f"Bearer {_make_viewer_token()}"}


def _make_db_rows(items: list[dict]):
    """Build mock DB result rows for the miss-signals query.

    Each row has: unresolved_term, query_count, example_queries
    """
    rows = []
    for item in items:
        row = MagicMock()
        row.get = lambda k, default=None, _d=item: _d.get(k, default)
        row.__getitem__ = lambda self, k, _d=item: _d[k]
        rows.append(row)
    return rows


def _patch_db_with_results(items: list[dict]):
    """Patch the DB session to return mock miss-signals aggregation rows."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()

    async def _execute(*args, **kwargs):
        mock_result = MagicMock()
        sql = str(args[0]) if args else ""
        if "glossary_miss_signals" in sql:
            # Build mapping rows
            rows = []
            for item in items:
                m = MagicMock()
                m.get = lambda k, default=None, _d=item: _d.get(k, default)
                m.__getitem__ = lambda self, k, _d=item: _d[k]
                rows.append(m)
            mock_result.mappings.return_value = rows
        else:
            mock_result.mappings.return_value = []
        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override

    class _Ctx:
        def __enter__(self):
            return mock_session

        def __exit__(self, *args):
            app.dependency_overrides.pop(get_async_session, None)

    return _Ctx()


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAdminMissSignalsAuth:
    def test_requires_auth(self, client):
        resp = client.get(_ADMIN_MISS_SIGNALS_URL)
        assert resp.status_code == 401

    def test_viewer_is_forbidden(self, client):
        resp = client.get(_ADMIN_MISS_SIGNALS_URL, headers=_viewer_headers())
        assert resp.status_code == 403

    def test_tenant_admin_is_allowed(self, client):
        with _patch_db_with_results([]):
            resp = client.get(_ADMIN_MISS_SIGNALS_URL, headers=_admin_headers())
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Response shape tests
# ---------------------------------------------------------------------------


class TestAdminMissSignalsResponseShape:
    def test_returns_items_and_total(self, client):
        items = [
            {
                "unresolved_term": "SLA",
                "query_count": 10,
                "example_queries": ["What is SLA?"],
            }
        ]
        with _patch_db_with_results(items):
            resp = client.get(_ADMIN_MISS_SIGNALS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 1

    def test_empty_result_returns_zero_items(self, client):
        with _patch_db_with_results([]):
            resp = client.get(_ADMIN_MISS_SIGNALS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_item_has_required_fields(self, client):
        items = [
            {
                "unresolved_term": "KPI",
                "query_count": 5,
                "example_queries": ["What is KPI?", "How do I check KPI"],
            }
        ]
        with _patch_db_with_results(items):
            resp = client.get(_ADMIN_MISS_SIGNALS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert "term" in item
        assert "query_count" in item
        assert "example_queries" in item

    def test_query_count_is_integer(self, client):
        items = [
            {
                "unresolved_term": "ROI",
                "query_count": 42,
                "example_queries": ["Show ROI metrics"],
            }
        ]
        with _patch_db_with_results(items):
            resp = client.get(_ADMIN_MISS_SIGNALS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert isinstance(item["query_count"], int)
        assert item["query_count"] == 42

    def test_example_queries_is_list(self, client):
        items = [
            {
                "unresolved_term": "CSAT",
                "query_count": 3,
                "example_queries": ["What is CSAT", "CSAT score today"],
            }
        ]
        with _patch_db_with_results(items):
            resp = client.get(_ADMIN_MISS_SIGNALS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert isinstance(item["example_queries"], list)


# ---------------------------------------------------------------------------
# DB helper unit tests (test get_admin_miss_signals_db directly)
# ---------------------------------------------------------------------------


class TestGetAdminMissSignalsDb:
    @pytest.mark.asyncio
    async def test_example_queries_truncated_to_40_chars(self):
        """Snippets longer than 40 chars are truncated."""
        from app.modules.glossary.routes import get_admin_miss_signals_db

        long_snippet = "A" * 60
        mock_row = MagicMock()
        mock_row.get = lambda k, default=None: {
            "example_queries": [long_snippet],
        }.get(k, default)
        mock_row.__getitem__ = lambda self, k: {
            "unresolved_term": "HR",
            "query_count": 1,
            "example_queries": [long_snippet],
        }[k]

        mock_result = MagicMock()
        mock_result.mappings.return_value = [mock_row]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        items = await get_admin_miss_signals_db("tenant-1", 50, mock_db)
        assert len(items) == 1
        for eq in items[0]["example_queries"]:
            assert len(eq) <= 40

    @pytest.mark.asyncio
    async def test_example_queries_capped_at_3(self):
        """At most 3 example queries are returned per term."""
        from app.modules.glossary.routes import get_admin_miss_signals_db

        many_snippets = [f"query snippet {i}" for i in range(10)]
        mock_row = MagicMock()
        mock_row.get = lambda k, default=None: {
            "example_queries": many_snippets,
        }.get(k, default)
        mock_row.__getitem__ = lambda self, k: {
            "unresolved_term": "CSAT",
            "query_count": 10,
            "example_queries": many_snippets,
        }[k]

        mock_result = MagicMock()
        mock_result.mappings.return_value = [mock_row]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        items = await get_admin_miss_signals_db("tenant-1", 50, mock_db)
        assert len(items) == 1
        assert len(items[0]["example_queries"]) <= 3

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_no_rows(self):
        from app.modules.glossary.routes import get_admin_miss_signals_db

        mock_result = MagicMock()
        mock_result.mappings.return_value = []

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        items = await get_admin_miss_signals_db("tenant-1", 50, mock_db)
        assert items == []
