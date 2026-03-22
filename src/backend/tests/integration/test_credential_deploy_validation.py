"""
ATA-026: Integration tests for credential deploy validation.

Tests the full credential validation pipeline against a real PostgreSQL database:
  1. Deploy with auth_mode='tenant_credentials' missing required key → 422
  2. Deploy with all required credentials → 201; credentials_vault_path non-null
  3. GET /admin/agents/{id} returns has_credentials=true, vault path NOT in response
  4. Deploy with auth_mode='platform_credentials' → 422

Architecture:
  - Real PostgreSQL (no mocking of DB)
  - agent_templates row created directly in DB with auth_mode/required_credentials
  - HTTP endpoint tested via TestClient (session-scoped, shared with other tests)
  - asyncio.run() for DB setup to avoid event loop conflicts with session-scoped
    TestClient.

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_credential_deploy_validation.py -v --timeout=60
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Skip guards — these fire if real infrastructure is absent
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        pytest.skip("JWT_SECRET_KEY not configured — skipping integration tests")
    return secret


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict = None):
    """Execute SQL, commit, and return the result."""
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def _fetch_one(sql: str, params: dict = None):
    """Execute SQL and return first row as a mapping dict (or None)."""
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            row = result.mappings().first()
            return dict(row) if row is not None else None
    finally:
        await engine.dispose()


async def _create_test_tenant() -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"Cred Deploy Test {tid[:8]}",
            "slug": f"cred-deploy-{tid[:8]}",
            "email": f"admin-{tid[:8]}@cred-deploy-int.test",
        },
    )
    return tid


async def _create_test_user(tid: str, role: str = "admin") -> str:
    uid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO users (id, tenant_id, email, name, role, status) "
        "VALUES (:id, :tid, :email, :name, :role, 'active')",
        {
            "id": uid,
            "tid": tid,
            "email": f"{role}-{uid[:8]}@cred-deploy-int.test",
            "name": f"Test {role.capitalize()} {uid[:8]}",
            "role": role,
        },
    )
    return uid


async def _create_agent_template(
    auth_mode: str, required_credentials: list
) -> str:
    """Insert an agent_templates row with the given auth_mode and required_credentials."""
    tmpl_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO agent_templates "
        "(id, name, description, category, system_prompt, status, version, "
        "auth_mode, required_credentials) "
        "VALUES (:id, :name, :desc, :cat, :prompt, 'Published', 1, "
        ":auth_mode, CAST(:required_credentials AS jsonb))",
        {
            "id": tmpl_id,
            "name": f"Cred Test Template {tmpl_id[:8]}",
            "desc": "Integration test template for credential validation",
            "cat": "Test",
            "prompt": "You are a test agent.",
            "auth_mode": auth_mode,
            "required_credentials": json.dumps(required_credentials),
        },
    )
    return tmpl_id


async def _cleanup_tenant(tid: str):
    tables = [
        "agent_access_control",
        "har_transactions",
        "agent_cards",
        "audit_log",
        "users",
        "tenants",
    ]
    for table in tables:
        col = "tenant_id" if table != "tenants" else "id"
        await _run_sql(f"DELETE FROM {table} WHERE {col} = :tid", {"tid": tid})


async def _cleanup_templates(tmpl_ids: list):
    for tmpl_id in tmpl_ids:
        await _run_sql(
            "DELETE FROM agent_templates WHERE id = :id", {"id": tmpl_id}
        )


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _make_admin_token(tenant_id: str, user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
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


# ---------------------------------------------------------------------------
# Module fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tenant_and_user():
    """Create a tenant + admin user once per module; clean up after all tests."""
    tid = asyncio.run(_create_test_tenant())
    uid = asyncio.run(_create_test_user(tid, role="admin"))
    yield tid, uid
    asyncio.run(_cleanup_tenant(tid))


@pytest.fixture(scope="module")
def test_client():
    """Session-scoped TestClient for the FastAPI app."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

    env_patch = {
        "JWT_SECRET_KEY": _jwt_secret(),
        "JWT_ALGORITHM": "HS256",
        "DATABASE_URL": _db_url(),
        "REDIS_URL": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "FRONTEND_URL": "http://localhost:3022",
    }
    import unittest.mock as _mock
    with _mock.patch.dict(os.environ, env_patch):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


# ---------------------------------------------------------------------------
# ATA-026 tests
# ---------------------------------------------------------------------------


class TestCredentialDeployValidation:
    """
    Integration tests for ATA-025 credential validation in the deploy pipeline.
    """

    def test_missing_required_credential_returns_422(
        self, tenant_and_user, test_client
    ):
        """
        Deploy with auth_mode='tenant_credentials' and a required key not provided
        returns 422 with the missing key name in the detail.
        """
        tid, uid = tenant_and_user
        token = _make_admin_token(tid, uid)

        tmpl_id = asyncio.run(
            _create_agent_template(
                auth_mode="tenant_credentials",
                required_credentials=[{"key": "api_key", "required": True}],
            )
        )
        try:
            response = test_client.post(
                "/api/v1/admin/agents/deploy",
                json={
                    "template_id": tmpl_id,
                    "name": "Missing Cred Agent",
                    # No credentials field — api_key required but absent
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 422, response.text
            detail = response.json().get("detail", "")
            assert "Missing required credentials" in detail
            assert "api_key" in detail
        finally:
            asyncio.run(_cleanup_templates([tmpl_id]))

    def test_deploy_with_all_credentials_returns_201_and_sets_vault_path(
        self, tenant_and_user, test_client
    ):
        """
        Deploy with all required credentials provided returns 201 and
        agent_cards.credentials_vault_path is non-null in the database.
        """
        tid, uid = tenant_and_user
        token = _make_admin_token(tid, uid)

        tmpl_id = asyncio.run(
            _create_agent_template(
                auth_mode="tenant_credentials",
                required_credentials=[{"key": "api_key", "required": True}],
            )
        )
        agent_id = None
        try:
            response = test_client.post(
                "/api/v1/admin/agents/deploy",
                json={
                    "template_id": tmpl_id,
                    "name": "Cred Agent With Key",
                    "credentials": {"api_key": "my-secret-api-key"},
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 201, response.text
            data = response.json()
            agent_id = data.get("id")
            assert agent_id is not None

            # Verify credentials_vault_path is non-null in DB
            row = asyncio.run(
                _fetch_one(
                    "SELECT credentials_vault_path FROM agent_cards WHERE id = :id",
                    {"id": agent_id},
                )
            )
            assert row is not None, "Agent not found in DB"
            assert row["credentials_vault_path"] is not None, (
                "credentials_vault_path should be non-null after credential deploy"
            )
        finally:
            asyncio.run(_cleanup_templates([tmpl_id]))

    def test_get_agent_detail_returns_has_credentials_true_no_vault_path(
        self, tenant_and_user, test_client
    ):
        """
        GET /admin/agents/{id} returns has_credentials=true when credentials
        are stored, and does NOT expose the vault path in the response body.
        """
        tid, uid = tenant_and_user
        token = _make_admin_token(tid, uid)

        tmpl_id = asyncio.run(
            _create_agent_template(
                auth_mode="tenant_credentials",
                required_credentials=[{"key": "api_key", "required": True}],
            )
        )
        agent_id = None
        try:
            # Deploy with credentials
            deploy_resp = test_client.post(
                "/api/v1/admin/agents/deploy",
                json={
                    "template_id": tmpl_id,
                    "name": "Agent For Detail Check",
                    "credentials": {"api_key": "test-secret"},
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert deploy_resp.status_code == 201, deploy_resp.text
            agent_id = deploy_resp.json().get("id")

            # GET agent detail
            detail_resp = test_client.get(
                f"/api/v1/admin/agents/{agent_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert detail_resp.status_code == 200, detail_resp.text
            detail_data = detail_resp.json()

            # has_credentials must be True
            assert detail_data.get("has_credentials") is True, (
                f"Expected has_credentials=True, got: {detail_data.get('has_credentials')}"
            )
            # Vault path must NOT be in the response
            assert "credentials_vault_path" not in detail_data, (
                "Vault path must not be exposed in the API response"
            )
        finally:
            asyncio.run(_cleanup_templates([tmpl_id]))

    def test_platform_credentials_auth_mode_returns_422(
        self, tenant_and_user, test_client
    ):
        """
        Deploy with auth_mode='platform_credentials' returns 422 with
        "not yet available" in the detail message.
        """
        tid, uid = tenant_and_user
        token = _make_admin_token(tid, uid)

        tmpl_id = asyncio.run(
            _create_agent_template(
                auth_mode="platform_credentials",
                required_credentials=[],
            )
        )
        try:
            response = test_client.post(
                "/api/v1/admin/agents/deploy",
                json={
                    "template_id": tmpl_id,
                    "name": "Platform Cred Agent",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 422, response.text
            detail = response.json().get("detail", "")
            assert "not yet available" in detail
        finally:
            asyncio.run(_cleanup_templates([tmpl_id]))
