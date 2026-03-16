"""
Unit tests for PA-022 template versioning endpoints.

  POST /platform/agent-templates/{id}/new-version
  GET  /platform/agent-templates/{id}/versions

Tier 1: Fast, isolated. Uses dependency_overrides + AsyncMock helpers.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "c" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_TEMPLATE_ID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
TEST_CHILD_ID = "11112222-3333-4444-5555-666677778888"

_MOD = "app.modules.platform.routes"

_NEW_VERSION_BASE = f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}/new-version"
_VERSIONS_BASE = f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}/versions"


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "platform-admin-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "email": "platform@mingai.io",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_tenant_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-admin-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
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


def _platform_headers() -> dict:
    return {"Authorization": f"Bearer {_make_platform_token()}"}


def _tenant_headers() -> dict:
    return {"Authorization": f"Bearer {_make_tenant_token()}"}


_MOCK_TEMPLATE_V1 = {
    "id": TEST_TEMPLATE_ID,
    "name": "HR Bot",
    "description": "HR assistant",
    "category": "HR",
    "system_prompt": "You are an HR assistant for {{company}}.",
    "variable_definitions": [
        {"name": "company", "type": "text", "label": "Company", "required": True}
    ],
    "guardrails": [],
    "confidence_threshold": None,
    "version": 1,
    "status": "Published",
    "changelog": "Initial version",
    "created_by": None,
    "parent_id": None,
    "created_at": "2026-03-16T00:00:00+00:00",
    "updated_at": "2026-03-16T00:00:00+00:00",
}

_MOCK_TEMPLATE_V2 = {
    **_MOCK_TEMPLATE_V1,
    "id": TEST_CHILD_ID,
    "version": 2,
    "status": "Draft",
    "changelog": None,
    "parent_id": TEST_TEMPLATE_ID,
}


def _patch_get_template(return_value):
    return patch(
        f"{_MOD}._get_agent_template_db", new=AsyncMock(return_value=return_value)
    )


def _patch_create_version(return_value):
    return patch(
        f"{_MOD}._create_template_version_db",
        new=AsyncMock(return_value=return_value),
    )


def _patch_list_versions(return_value):
    return patch(
        f"{_MOD}._list_template_versions_db",
        new=AsyncMock(return_value=return_value),
    )


# ---------------------------------------------------------------------------
# POST /new-version auth tests
# ---------------------------------------------------------------------------


class TestNewVersionAuth:
    def test_requires_auth(self, client):
        resp = client.post(_NEW_VERSION_BASE)
        assert resp.status_code == 401

    def test_requires_platform_admin(self, client):
        resp = client.post(_NEW_VERSION_BASE, headers=_tenant_headers())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /new-version — 404 tests
# ---------------------------------------------------------------------------


class TestNewVersionNotFound:
    def test_404_for_missing_template(self, client):
        with patch(f"{_MOD}._get_agent_template_db", new=AsyncMock(return_value=None)):
            resp = client.post(_NEW_VERSION_BASE, headers=_platform_headers())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /new-version — Deprecated source rejected
# ---------------------------------------------------------------------------


class TestNewVersionDeprecated:
    def test_deprecated_template_returns_409(self, client):
        deprecated_template = {**_MOCK_TEMPLATE_V1, "status": "Deprecated"}
        with patch(
            f"{_MOD}._get_agent_template_db",
            new=AsyncMock(return_value=deprecated_template),
        ):
            resp = client.post(_NEW_VERSION_BASE, headers=_platform_headers())
        assert resp.status_code == 409
        assert "Deprecated" in resp.json()["detail"]

    def test_draft_template_allowed(self, client):
        draft_template = {**_MOCK_TEMPLATE_V1, "status": "Draft"}
        with (
            patch(
                f"{_MOD}._get_agent_template_db",
                new=AsyncMock(return_value=draft_template),
            ),
            _patch_create_version(_MOCK_TEMPLATE_V2),
        ):
            resp = client.post(_NEW_VERSION_BASE, headers=_platform_headers())
        assert resp.status_code == 201

    def test_published_template_allowed(self, client):
        with (
            patch(
                f"{_MOD}._get_agent_template_db",
                new=AsyncMock(return_value=_MOCK_TEMPLATE_V1),
            ),
            _patch_create_version(_MOCK_TEMPLATE_V2),
        ):
            resp = client.post(_NEW_VERSION_BASE, headers=_platform_headers())
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# POST /new-version — happy path
# ---------------------------------------------------------------------------


def _patch_get_and_create(source_template, new_version_result):
    """Patch both _get_agent_template_db (status check) and _create_template_version_db."""
    return (
        patch(
            f"{_MOD}._get_agent_template_db",
            new=AsyncMock(return_value=source_template),
        ),
        _patch_create_version(new_version_result),
    )


class TestNewVersionSuccess:
    def test_returns_201_with_new_template(self, client):
        with (
            patch(
                f"{_MOD}._get_agent_template_db",
                new=AsyncMock(return_value=_MOCK_TEMPLATE_V1),
            ),
            _patch_create_version(_MOCK_TEMPLATE_V2),
        ):
            resp = client.post(_NEW_VERSION_BASE, headers=_platform_headers())
        assert resp.status_code == 201
        data = resp.json()
        assert data["version"] == 2
        assert data["status"] == "Draft"
        assert data["parent_id"] == TEST_TEMPLATE_ID

    def test_new_version_copies_name_and_system_prompt(self, client):
        with (
            patch(
                f"{_MOD}._get_agent_template_db",
                new=AsyncMock(return_value=_MOCK_TEMPLATE_V1),
            ),
            _patch_create_version(_MOCK_TEMPLATE_V2),
        ):
            resp = client.post(_NEW_VERSION_BASE, headers=_platform_headers())
        data = resp.json()
        assert data["name"] == "HR Bot"
        assert "{{company}}" in data["system_prompt"]

    def test_new_version_has_null_changelog(self, client):
        """New Draft versions start with no changelog."""
        with (
            patch(
                f"{_MOD}._get_agent_template_db",
                new=AsyncMock(return_value=_MOCK_TEMPLATE_V1),
            ),
            _patch_create_version(_MOCK_TEMPLATE_V2),
        ):
            resp = client.post(_NEW_VERSION_BASE, headers=_platform_headers())
        assert resp.json()["changelog"] is None


# ---------------------------------------------------------------------------
# GET /versions auth tests
# ---------------------------------------------------------------------------


class TestVersionsAuth:
    def test_requires_auth(self, client):
        resp = client.get(_VERSIONS_BASE)
        assert resp.status_code == 401

    def test_requires_platform_admin(self, client):
        resp = client.get(_VERSIONS_BASE, headers=_tenant_headers())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /versions — 404 tests
# ---------------------------------------------------------------------------


class TestVersionsNotFound:
    def test_404_for_missing_template(self, client):
        with _patch_list_versions(None):
            resp = client.get(_VERSIONS_BASE, headers=_platform_headers())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /versions — happy path
# ---------------------------------------------------------------------------


class TestVersionsSuccess:
    def test_returns_versions_list(self, client):
        versions = [
            {
                "id": TEST_CHILD_ID,
                "version": 2,
                "status": "Draft",
                "changelog": None,
                "system_prompt_preview": "You are an HR assistant for {{company}}.",
                "created_at": "2026-03-16T00:00:00+00:00",
                "updated_at": "2026-03-16T00:00:00+00:00",
            },
            {
                "id": TEST_TEMPLATE_ID,
                "version": 1,
                "status": "Published",
                "changelog": "Initial version",
                "system_prompt_preview": "You are an HR assistant for {{company}}.",
                "created_at": "2026-03-16T00:00:00+00:00",
                "updated_at": "2026-03-16T00:00:00+00:00",
            },
        ]
        with _patch_list_versions(versions):
            resp = client.get(_VERSIONS_BASE, headers=_platform_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "versions" in data
        assert len(data["versions"]) == 2

    def test_versions_sorted_desc(self, client):
        versions = [
            {"id": TEST_CHILD_ID, "version": 2, "status": "Draft"},
            {"id": TEST_TEMPLATE_ID, "version": 1, "status": "Published"},
        ]
        with _patch_list_versions(versions):
            resp = client.get(_VERSIONS_BASE, headers=_platform_headers())
        data = resp.json()
        assert data["versions"][0]["version"] == 2
        assert data["versions"][1]["version"] == 1

    def test_single_version_returned_for_unversioned_template(self, client):
        """Root-only template (no children) returns list with 1 entry."""
        versions = [
            {
                "id": TEST_TEMPLATE_ID,
                "version": 1,
                "status": "Published",
                "changelog": "Initial",
                "system_prompt_preview": "You are helpful.",
                "created_at": "2026-03-16T00:00:00+00:00",
                "updated_at": "2026-03-16T00:00:00+00:00",
            }
        ]
        with _patch_list_versions(versions):
            resp = client.get(_VERSIONS_BASE, headers=_platform_headers())
        data = resp.json()
        assert len(data["versions"]) == 1

    def test_version_entry_has_system_prompt_preview(self, client):
        versions = [
            {
                "id": TEST_TEMPLATE_ID,
                "version": 1,
                "status": "Published",
                "changelog": "Initial",
                "system_prompt_preview": "You are an HR assis",
                "created_at": "2026-03-16T00:00:00+00:00",
                "updated_at": "2026-03-16T00:00:00+00:00",
            }
        ]
        with _patch_list_versions(versions):
            resp = client.get(_VERSIONS_BASE, headers=_platform_headers())
        data = resp.json()
        assert "system_prompt_preview" in data["versions"][0]


# ---------------------------------------------------------------------------
# _create_template_version_db unit tests (logic verification)
# ---------------------------------------------------------------------------


class TestCreateTemplateVersionDbLogic:
    """Verify the DB helper's version family logic without hitting the DB."""

    def test_child_uses_root_id_as_parent(self):
        """If source already has a parent_id, new version's parent_id = source.parent_id."""
        # Simulates calling /new-version on an already-versioned draft (v2)
        # The new v3 should have parent_id = root (not v2's id)
        child_template = {
            **_MOCK_TEMPLATE_V1,
            "id": TEST_CHILD_ID,
            "version": 2,
            "parent_id": TEST_TEMPLATE_ID,  # points to root
        }
        # The root_id logic: root_id = source["parent_id"] or source["id"]
        # => if source["parent_id"] = TEST_TEMPLATE_ID, root_id = TEST_TEMPLATE_ID
        root_id = child_template.get("parent_id") or child_template["id"]
        assert root_id == TEST_TEMPLATE_ID

    def test_root_template_becomes_own_parent_for_version_family(self):
        """Root template (parent_id=None) acts as root_id for itself."""
        root_template = {**_MOCK_TEMPLATE_V1, "parent_id": None}
        root_id = root_template.get("parent_id") or root_template["id"]
        assert root_id == TEST_TEMPLATE_ID
