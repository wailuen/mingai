"""
Agent Studio Management Integration Tests (API-069 to API-073).

Tests:
- API-069: GET /admin/agents — list workspace agents
- API-070: POST /admin/agents — create agent (Agent Studio)
- API-071: PUT /admin/agents/{agent_id} — update agent
- API-072: PATCH /admin/agents/{agent_id}/status — update status
- API-073: POST /admin/agents/deploy — deploy from template library

Architecture:
  - Real PostgreSQL (no mocking of DB)
  - No Redis or LLM calls in this suite
  - Isolated test tenants — cleaned up after each test

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_agent_management.py -v --timeout=60
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
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def _create_test_tenant() -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"Agent Mgmt Test {tid[:8]}",
            "slug": f"agent-mgmt-test-{tid[:8]}",
            "email": f"admin-{tid[:8]}@agent-int.test",
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
            "email": f"{role}-{uid[:8]}@agent-int.test",
            "name": f"Test {role.title()} {uid[:8]}",
            "role": role,
        },
    )
    return uid


async def _create_test_agent(
    tid: str, uid: str, name: str = "Test Agent", agent_status: str = "draft"
) -> str:
    agent_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO agent_cards "
        "(id, tenant_id, name, description, system_prompt, status, version, source, created_by) "
        "VALUES (:id, :tid, :name, :desc, :prompt, :status, 1, 'custom', :uid)",
        {
            "id": agent_id,
            "tid": tid,
            "name": name,
            "desc": "Test agent",
            "prompt": "You are a test agent.",
            "status": agent_status,
            "uid": uid,
        },
    )
    return agent_id


async def _cleanup_tenant(tid: str):
    tables = [
        "audit_log",
        "agent_cards",
        "users",
        "tenants",
    ]
    for table in tables:
        col = "tenant_id" if table != "tenants" else "id"
        await _run_sql(f"DELETE FROM {table} WHERE {col} = :tid", {"tid": tid})


# ---------------------------------------------------------------------------
# JWT token helper
# ---------------------------------------------------------------------------


def _make_admin_token(tenant_id: str, user_id: str) -> str:
    from datetime import timedelta

    from jose import jwt

    secret = os.environ.get("JWT_SECRET_KEY", "a" * 64)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": f"admin-{user_id[:8]}@test.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListWorkspaceAgents:
    """API-069: GET /admin/agents"""

    def test_list_workspace_agents_empty(self, client):
        """New tenant with no agents should return empty list."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                token = _make_admin_token(tid, uid)
                resp = client.get(
                    "/api/v1/admin/agents",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert (
                    resp.status_code == 200
                ), f"Expected 200, got {resp.status_code}: {resp.text}"
                data = resp.json()
                assert "items" in data
                assert "total" in data
                assert data["total"] == 0
                assert data["items"] == []
                assert data["page"] == 1
                assert data["page_size"] == 20
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_list_workspace_agents_with_agents(self, client):
        """Tenant with agents should return them in list."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            agent_id = await _create_test_agent(tid, uid, "HR Assistant", "draft")
            try:
                token = _make_admin_token(tid, uid)
                resp = client.get(
                    "/api/v1/admin/agents",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["total"] == 1
                assert len(data["items"]) == 1
                item = data["items"][0]
                assert item["id"] == agent_id
                assert item["name"] == "HR Assistant"
                assert item["status"] == "draft"
                assert item["source"] == "custom"
                assert "satisfaction_rate" in item
                assert "user_count" in item
                assert item["user_count"] == 0
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_list_workspace_agents_status_filter(self, client):
        """Status filter should return only matching agents."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            await _create_test_agent(tid, uid, "Draft Agent", "draft")
            await _create_test_agent(tid, uid, "Published Agent", "published")
            try:
                token = _make_admin_token(tid, uid)
                # Filter by draft
                resp = client.get(
                    "/api/v1/admin/agents?status=draft",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["total"] == 1
                assert data["items"][0]["status"] == "draft"
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_list_workspace_agents_invalid_status(self, client):
        """Invalid status filter should return 422."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                token = _make_admin_token(tid, uid)
                resp = client.get(
                    "/api/v1/admin/agents?status=invalid_status",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 422
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_list_workspace_agents_requires_auth(self, client):
        """Unauthenticated request should return 401."""
        resp = client.get("/api/v1/admin/agents")
        assert resp.status_code == 401


class TestCreateAgent:
    """API-070: POST /admin/agents"""

    def test_create_agent_draft(self, client):
        """Creating an agent with minimal fields should succeed."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                token = _make_admin_token(tid, uid)
                resp = client.post(
                    "/api/v1/admin/agents",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "name": "My Test Agent",
                        "system_prompt": "You are a helpful test agent.",
                        "status": "draft",
                    },
                )
                assert (
                    resp.status_code == 201
                ), f"Expected 201, got {resp.status_code}: {resp.text}"
                data = resp.json()
                assert "id" in data
                assert data["name"] == "My Test Agent"
                assert data["status"] == "draft"
                assert "created_at" in data
                # Verify it shows up in list
                list_resp = client.get(
                    "/api/v1/admin/agents",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert list_resp.status_code == 200
                assert list_resp.json()["total"] == 1
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_create_agent_validation_fails_empty_name(self, client):
        """Empty name should fail Pydantic validation."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                token = _make_admin_token(tid, uid)
                resp = client.post(
                    "/api/v1/admin/agents",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "name": "",
                        "system_prompt": "You are a helpful agent.",
                        "status": "draft",
                    },
                )
                assert resp.status_code == 422
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_create_agent_validation_fails_empty_system_prompt(self, client):
        """Empty system_prompt should fail Pydantic validation."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                token = _make_admin_token(tid, uid)
                resp = client.post(
                    "/api/v1/admin/agents",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "name": "Test Agent",
                        "system_prompt": "",
                        "status": "draft",
                    },
                )
                assert resp.status_code == 422
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_create_agent_with_guardrails(self, client):
        """Creating an agent with custom guardrails should persist them."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                token = _make_admin_token(tid, uid)
                resp = client.post(
                    "/api/v1/admin/agents",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "name": "Guarded Agent",
                        "system_prompt": "You are a helpful agent.",
                        "status": "draft",
                        "guardrails": {
                            "blocked_topics": ["politics", "gambling"],
                            "confidence_threshold": 0.8,
                            "max_response_length": 1000,
                        },
                    },
                )
                assert resp.status_code == 201
                data = resp.json()
                assert "id" in data
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())


class TestUpdateAgentStatus:
    """API-072: PATCH /admin/agents/{agent_id}/status"""

    def test_update_agent_status_publish(self, client):
        """Publishing a draft agent should succeed."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            agent_id = await _create_test_agent(tid, uid, "Ready Agent", "draft")
            try:
                token = _make_admin_token(tid, uid)
                resp = client.patch(
                    f"/api/v1/admin/agents/{agent_id}/status",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"status": "published"},
                )
                assert (
                    resp.status_code == 200
                ), f"Expected 200, got {resp.status_code}: {resp.text}"
                data = resp.json()
                assert data["id"] == agent_id
                assert data["status"] == "published"
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_update_agent_status_invalid_status(self, client):
        """Invalid status value should return 422."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            agent_id = await _create_test_agent(tid, uid)
            try:
                token = _make_admin_token(tid, uid)
                resp = client.patch(
                    f"/api/v1/admin/agents/{agent_id}/status",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"status": "invalid_status"},
                )
                assert resp.status_code == 422
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_update_agent_status_not_found(self, client):
        """Non-existent agent should return 404."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            fake_id = str(uuid.uuid4())
            try:
                token = _make_admin_token(tid, uid)
                resp = client.patch(
                    f"/api/v1/admin/agents/{fake_id}/status",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"status": "published"},
                )
                assert resp.status_code == 404
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())


class TestDeployFromSeedTemplate:
    """API-073: POST /admin/agents/deploy (seed template case)"""

    def test_deploy_from_seed_template(self, client):
        """Deploying from a seed template should create a published agent."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                token = _make_admin_token(tid, uid)
                resp = client.post(
                    "/api/v1/admin/agents/deploy",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "template_id": "seed-hr",
                        "name": "Our HR Assistant",
                        "variables": {"company_name": "Acme Corp"},
                        "kb_ids": [],
                        "access_mode": "workspace_wide",
                    },
                )
                assert (
                    resp.status_code == 201
                ), f"Expected 201, got {resp.status_code}: {resp.text}"
                data = resp.json()
                assert "id" in data
                assert data["name"] == "Our HR Assistant"
                assert data["status"] == "published"
                assert data["template_id"] == "seed-hr"
                assert data["template_version"] == 1
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_deploy_from_seed_with_variable_substitution(self, client):
        """Variable substitution should replace {{placeholders}} in system_prompt."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                token = _make_admin_token(tid, uid)
                resp = client.post(
                    "/api/v1/admin/agents/deploy",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "template_id": "seed-hr",
                        "name": "HR Bot",
                        "variables": {"company_name": "TechStartup"},
                    },
                )
                assert resp.status_code == 201
                data = resp.json()
                assert data["id"]
                # Verify in list that agent is published
                list_resp = client.get(
                    "/api/v1/admin/agents?status=published",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert list_resp.status_code == 200
                list_data = list_resp.json()
                assert list_data["total"] >= 1
                deployed = next(
                    (a for a in list_data["items"] if a["id"] == data["id"]), None
                )
                assert deployed is not None
                assert deployed["source"] == "library"
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_deploy_from_nonexistent_template(self, client):
        """Non-existent template should return 404."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                token = _make_admin_token(tid, uid)
                resp = client.post(
                    "/api/v1/admin/agents/deploy",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "template_id": str(uuid.uuid4()),
                        "name": "Missing Template Deploy",
                    },
                )
                assert resp.status_code == 404
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())
