"""
ATA-013: Integration tests for agent deploy + access control.

Tests the deploy pipeline and access control enforcement:
  1. deploy_agent_template_db inserts agent_access_control row with correct visibility_mode
  2. _check_agent_access enforces workspace_wide / role_restricted / user_specific rules
  3. No-row fallback is fail-open (workspace_wide default)
  4. ON CONFLICT DO NOTHING on re-deploy

Architecture:
  - Real PostgreSQL (no mocking of DB)
  - deploy_agent_template_db called directly for access_control != "workspace"
    because the HTTP route has a Phase-A gate (ATA-003) that returns 422 for
    non-workspace access_control until ATA-057 removes it.
  - HTTP endpoint tested for the workspace case (access_control="workspace").
  - asyncio.run() for DB helpers to avoid event loop conflicts with session-scoped
    TestClient.

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_agent_deploy_access_control.py -v --timeout=60
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
    """Execute SQL, commit, and return the result (rows fetchable before dispose)."""
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
    """Execute SQL and return first row as a mapping (or None)."""
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
            "name": f"Deploy AC Test {tid[:8]}",
            "slug": f"deploy-ac-{tid[:8]}",
            "email": f"admin-{tid[:8]}@deploy-ac-int.test",
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
            "email": f"{role}-{uid[:8]}@deploy-ac-int.test",
            "name": f"Test {role.capitalize()} {uid[:8]}",
            "role": role,
        },
    )
    return uid


async def _cleanup_tenant(tid: str):
    tables = [
        "agent_access_control",
        "har_transactions",
        "agent_cards",
        "users",
        "tenants",
    ]
    for table in tables:
        col = "tenant_id" if table != "tenants" else "id"
        await _run_sql(f"DELETE FROM {table} WHERE {col} = :tid", {"tid": tid})


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _make_admin_token(tenant_id: str, user_id: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id or str(uuid.uuid4()),
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


# ---------------------------------------------------------------------------
# Tests: deploy_agent_template_db → agent_access_control rows
# ---------------------------------------------------------------------------


class TestDeployAccessControlRow:
    """
    Verify that deploy_agent_template_db inserts the correct agent_access_control
    row for each access_control API value.

    Calls the DB helper directly — bypassing the HTTP 422 gate — so all three
    access_control values can be tested without ATA-057 being active.
    """

    def test_deploy_workspace_inserts_workspace_wide_row(self, tenant_and_user):
        """
        access_control="workspace" → agent_access_control row with
        visibility_mode="workspace_wide", allowed_roles=[], allowed_user_ids=[].
        """
        from app.modules.agents.routes import deploy_agent_template_db

        tid, uid = tenant_and_user

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            agent_id = None
            try:
                async with factory() as db:
                    result = await deploy_agent_template_db(
                        tenant_id=tid,
                        name="Workspace Test Agent",
                        description="Integration test agent",
                        system_prompt="You are a test agent.",
                        capabilities=[],
                        access_control="workspace",
                        kb_ids=[],
                        created_by=uid,
                        db=db,
                        allowed_roles=[],
                        allowed_user_ids=[],
                    )
                    agent_id = result["id"]
            finally:
                await engine.dispose()

            assert agent_id is not None

            row = await _fetch_one(
                "SELECT visibility_mode, allowed_roles, allowed_user_ids "
                "FROM agent_access_control "
                "WHERE agent_id = :agent_id AND tenant_id = :tid",
                {"agent_id": agent_id, "tid": tid},
            )
            assert row is not None, "agent_access_control row must be inserted on deploy"
            assert row["visibility_mode"] == "workspace_wide"
            assert list(row["allowed_roles"] or []) == []
            assert list(row["allowed_user_ids"] or []) == []

        asyncio.run(_run())

    def test_deploy_role_inserts_role_restricted_row(self, tenant_and_user):
        """
        access_control="role" + allowed_roles=["analyst"] → visibility_mode="role_restricted",
        allowed_roles=["analyst"].
        """
        from app.modules.agents.routes import deploy_agent_template_db

        tid, uid = tenant_and_user

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            agent_id = None
            try:
                async with factory() as db:
                    result = await deploy_agent_template_db(
                        tenant_id=tid,
                        name="Role-Restricted Test Agent",
                        description="Integration test agent",
                        system_prompt="You are a test agent.",
                        capabilities=[],
                        access_control="role",
                        kb_ids=[],
                        created_by=uid,
                        db=db,
                        allowed_roles=["analyst"],
                        allowed_user_ids=[],
                    )
                    agent_id = result["id"]
            finally:
                await engine.dispose()

            assert agent_id is not None

            row = await _fetch_one(
                "SELECT visibility_mode, allowed_roles, allowed_user_ids "
                "FROM agent_access_control "
                "WHERE agent_id = :agent_id AND tenant_id = :tid",
                {"agent_id": agent_id, "tid": tid},
            )
            assert row is not None
            assert row["visibility_mode"] == "role_restricted"
            assert "analyst" in list(row["allowed_roles"] or [])
            assert list(row["allowed_user_ids"] or []) == []

        asyncio.run(_run())

    def test_deploy_user_inserts_user_specific_row(self, tenant_and_user):
        """
        access_control="user" + allowed_user_ids=[uid] → visibility_mode="user_specific",
        allowed_user_ids=[uid].
        """
        from app.modules.agents.routes import deploy_agent_template_db

        tid, uid = tenant_and_user

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            agent_id = None
            try:
                async with factory() as db:
                    result = await deploy_agent_template_db(
                        tenant_id=tid,
                        name="User-Specific Test Agent",
                        description="Integration test agent",
                        system_prompt="You are a test agent.",
                        capabilities=[],
                        access_control="user",
                        kb_ids=[],
                        created_by=uid,
                        db=db,
                        allowed_roles=[],
                        allowed_user_ids=[uid],
                    )
                    agent_id = result["id"]
            finally:
                await engine.dispose()

            assert agent_id is not None

            row = await _fetch_one(
                "SELECT visibility_mode, allowed_roles, allowed_user_ids "
                "FROM agent_access_control "
                "WHERE agent_id = :agent_id AND tenant_id = :tid",
                {"agent_id": agent_id, "tid": tid},
            )
            assert row is not None
            assert row["visibility_mode"] == "user_specific"
            assert uid in list(row["allowed_user_ids"] or [])
            assert list(row["allowed_roles"] or []) == []

        asyncio.run(_run())

    def test_redeploy_same_agent_no_conflict_error(self, tenant_and_user):
        """
        ON CONFLICT DO NOTHING: if agent_access_control row already exists for the
        same (agent_id, tenant_id), a second INSERT does not raise an error and
        the original row is preserved.
        """
        tid, uid = tenant_and_user
        agent_id = str(uuid.uuid4())

        async def _run():
            # Insert agent_cards row directly so we can test ACL conflict in isolation.
            await _run_sql(
                "INSERT INTO agent_cards "
                "(id, tenant_id, name, description, system_prompt, capabilities, status, version, created_by) "
                "VALUES (:id, :tid, :name, :desc, :prompt, '[]'::jsonb, 'published', 1, :uid)",
                {
                    "id": agent_id,
                    "tid": tid,
                    "name": "Conflict Test Agent",
                    "desc": "test",
                    "prompt": "test prompt",
                    "uid": uid,
                },
            )

            # First insert
            await _run_sql(
                """
                INSERT INTO agent_access_control
                    (agent_id, tenant_id, visibility_mode, allowed_roles, allowed_user_ids)
                VALUES
                    (:agent_id, :tid, 'workspace_wide', '{}', '{}')
                ON CONFLICT (tenant_id, agent_id) DO NOTHING
                """,
                {"agent_id": agent_id, "tid": tid},
            )

            # Second insert — must not raise
            await _run_sql(
                """
                INSERT INTO agent_access_control
                    (agent_id, tenant_id, visibility_mode, allowed_roles, allowed_user_ids)
                VALUES
                    (:agent_id, :tid, 'workspace_wide', '{}', '{}')
                ON CONFLICT (tenant_id, agent_id) DO NOTHING
                """,
                {"agent_id": agent_id, "tid": tid},
            )

            row = await _fetch_one(
                "SELECT COUNT(*) AS cnt FROM agent_access_control "
                "WHERE agent_id = :agent_id AND tenant_id = :tid",
                {"agent_id": agent_id, "tid": tid},
            )
            assert row["cnt"] == 1, "ON CONFLICT DO NOTHING must not insert a second row"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Tests: HTTP deploy endpoint (workspace path only — Phase-A gate allows it)
# ---------------------------------------------------------------------------


class TestDeployEndpointHTTP:
    """
    Verify the /agents/templates/{template_id}/deploy HTTP route for the
    workspace access_control path (the only path not gated by ATA-003).
    """

    def test_deploy_seed_template_workspace_returns_201(self, client, tenant_and_user):
        """
        POST /api/v1/agents/templates/seed-hr/deploy with access_control="workspace"
        returns 201 and the agent is persisted.
        """
        tid, uid = tenant_and_user
        token = _make_admin_token(tid, uid)
        resp = client.post(
            "/api/v1/agents/templates/seed-hr/deploy",
            json={"name": "HR Bot Integration Test", "access_control": "workspace"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "id" in data
        assert data["name"] == "HR Bot Integration Test"

        # Verify agent_access_control row was created
        row = asyncio.run(
            _fetch_one(
                "SELECT visibility_mode FROM agent_access_control "
                "WHERE agent_id = :agent_id AND tenant_id = :tid",
                {"agent_id": data["id"], "tid": tid},
            )
        )
        assert row is not None
        assert row["visibility_mode"] == "workspace_wide"

    def test_deploy_non_workspace_returns_422(self, client, tenant_and_user):
        """
        POST with access_control="role" returns 422 (Phase-A gate, ATA-003).
        """
        tid, uid = tenant_and_user
        token = _make_admin_token(tid, uid)
        resp = client.post(
            "/api/v1/agents/templates/seed-hr/deploy",
            json={
                "name": "Role Bot",
                "access_control": "role",
                "allowed_roles": ["analyst"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_deploy_unauthenticated_returns_401(self, client, tenant_and_user):
        """No auth token → 401."""
        resp = client.post(
            "/api/v1/agents/templates/seed-hr/deploy",
            json={"name": "No Auth Bot", "access_control": "workspace"},
        )
        assert resp.status_code == 401

    def test_deploy_unknown_template_returns_404(self, client, tenant_and_user):
        """Unknown template_id → 404."""
        tid, uid = tenant_and_user
        token = _make_admin_token(tid, uid)
        resp = client.post(
            "/api/v1/agents/templates/does-not-exist/deploy",
            json={"name": "Ghost Bot", "access_control": "workspace"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: _check_agent_access logic
# ---------------------------------------------------------------------------


class TestCheckAgentAccess:
    """
    Verify _check_agent_access returns True/False for each visibility_mode.
    Inserts rows directly; calls the method on a real DB session.
    """

    def _insert_acl_row(
        self,
        agent_id: str,
        tid: str,
        visibility_mode: str,
        allowed_roles: list,
        allowed_user_ids: list,
    ):
        """Insert an agent_access_control row for an agent that may not have an agent_cards row."""
        # agent_cards row is needed because of FK constraint on agent_access_control
        asyncio.run(
            _run_sql(
                "INSERT INTO agent_cards "
                "(id, tenant_id, name, description, system_prompt, capabilities, status, version, created_by) "
                "VALUES (:id, :tid, :name, 'test', 'test prompt', '[]'::jsonb, 'published', 1, :uid) "
                "ON CONFLICT (id) DO NOTHING",
                {
                    "id": agent_id,
                    "tid": tid,
                    "name": f"ACL Test Agent {agent_id[:8]}",
                    "uid": agent_id,  # reuse agent_id as placeholder — not a real user FK in this table
                },
            )
        )
        asyncio.run(
            _run_sql(
                """
                INSERT INTO agent_access_control
                    (agent_id, tenant_id, visibility_mode, allowed_roles, allowed_user_ids)
                VALUES
                    (:agent_id, :tid, :mode, :roles, :uids)
                ON CONFLICT (tenant_id, agent_id) DO UPDATE
                    SET visibility_mode = EXCLUDED.visibility_mode,
                        allowed_roles = EXCLUDED.allowed_roles,
                        allowed_user_ids = EXCLUDED.allowed_user_ids
                """,
                {
                    "agent_id": agent_id,
                    "tid": tid,
                    "mode": visibility_mode,
                    "roles": allowed_roles,
                    "uids": allowed_user_ids,
                },
            )
        )

    def test_workspace_wide_allows_any_user(self, tenant_and_user):
        """workspace_wide → any user_id / role combination is allowed."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        tid, uid = tenant_and_user
        agent_id = str(uuid.uuid4())
        self._insert_acl_row(agent_id, tid, "workspace_wide", [], [])

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as db:
                    svc = ChatOrchestrationService(
                        embedding_service=None,
                        vector_search_service=None,
                        profile_service=None,
                        working_memory_service=None,
                        org_context_service=None,
                        glossary_expander=None,
                        prompt_builder=None,
                        persistence_service=None,
                        confidence_calculator=None,
                        db_session=db,
                    )
                    result = await svc._check_agent_access(
                        agent_id=agent_id,
                        tenant_id=tid,
                        user_id=uid,
                        user_roles=["viewer"],
                    )
                    assert result is True, "workspace_wide must allow any user"
            finally:
                await engine.dispose()

        asyncio.run(_run())

    def test_role_restricted_denies_user_without_matching_role(self, tenant_and_user):
        """
        role_restricted with allowed_roles=["analyst"] denies a user whose
        roles=["viewer"] — no intersection.
        """
        from app.modules.chat.orchestrator import ChatOrchestrationService

        tid, uid = tenant_and_user
        agent_id = str(uuid.uuid4())
        self._insert_acl_row(agent_id, tid, "role_restricted", ["analyst"], [])

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as db:
                    svc = ChatOrchestrationService(
                        embedding_service=None,
                        vector_search_service=None,
                        profile_service=None,
                        working_memory_service=None,
                        org_context_service=None,
                        glossary_expander=None,
                        prompt_builder=None,
                        persistence_service=None,
                        confidence_calculator=None,
                        db_session=db,
                    )
                    result = await svc._check_agent_access(
                        agent_id=agent_id,
                        tenant_id=tid,
                        user_id=uid,
                        user_roles=["viewer"],
                    )
                    assert result is False, "role_restricted must deny user without matching role"
            finally:
                await engine.dispose()

        asyncio.run(_run())

    def test_role_restricted_allows_user_with_matching_role(self, tenant_and_user):
        """
        role_restricted with allowed_roles=["analyst"] allows a user whose
        roles=["analyst", "viewer"] — intersection exists.
        """
        from app.modules.chat.orchestrator import ChatOrchestrationService

        tid, uid = tenant_and_user
        agent_id = str(uuid.uuid4())
        self._insert_acl_row(agent_id, tid, "role_restricted", ["analyst"], [])

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as db:
                    svc = ChatOrchestrationService(
                        embedding_service=None,
                        vector_search_service=None,
                        profile_service=None,
                        working_memory_service=None,
                        org_context_service=None,
                        glossary_expander=None,
                        prompt_builder=None,
                        persistence_service=None,
                        confidence_calculator=None,
                        db_session=db,
                    )
                    result = await svc._check_agent_access(
                        agent_id=agent_id,
                        tenant_id=tid,
                        user_id=uid,
                        user_roles=["analyst", "viewer"],
                    )
                    assert result is True, "role_restricted must allow user with matching role"
            finally:
                await engine.dispose()

        asyncio.run(_run())

    def test_user_specific_allows_matching_user_id(self, tenant_and_user):
        """user_specific with allowed_user_ids=[uid] allows the exact user."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        tid, uid = tenant_and_user
        agent_id = str(uuid.uuid4())
        self._insert_acl_row(agent_id, tid, "user_specific", [], [uid])

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as db:
                    svc = ChatOrchestrationService(
                        embedding_service=None,
                        vector_search_service=None,
                        profile_service=None,
                        working_memory_service=None,
                        org_context_service=None,
                        glossary_expander=None,
                        prompt_builder=None,
                        persistence_service=None,
                        confidence_calculator=None,
                        db_session=db,
                    )
                    result = await svc._check_agent_access(
                        agent_id=agent_id,
                        tenant_id=tid,
                        user_id=uid,
                        user_roles=[],
                    )
                    assert result is True, "user_specific must allow matching user_id"
            finally:
                await engine.dispose()

        asyncio.run(_run())

    def test_user_specific_denies_non_matching_user_id(self, tenant_and_user):
        """user_specific with allowed_user_ids=[other_uid] denies a different user."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        tid, uid = tenant_and_user
        agent_id = str(uuid.uuid4())
        other_uid = str(uuid.uuid4())
        self._insert_acl_row(agent_id, tid, "user_specific", [], [other_uid])

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as db:
                    svc = ChatOrchestrationService(
                        embedding_service=None,
                        vector_search_service=None,
                        profile_service=None,
                        working_memory_service=None,
                        org_context_service=None,
                        glossary_expander=None,
                        prompt_builder=None,
                        persistence_service=None,
                        confidence_calculator=None,
                        db_session=db,
                    )
                    result = await svc._check_agent_access(
                        agent_id=agent_id,
                        tenant_id=tid,
                        user_id=uid,
                        user_roles=[],
                    )
                    assert result is False, "user_specific must deny non-matching user_id"
            finally:
                await engine.dispose()

        asyncio.run(_run())

    def test_no_acl_row_returns_true_fail_open(self, tenant_and_user):
        """
        No agent_access_control row for this agent → _check_agent_access returns True
        (workspace_wide fallback for pre-Phase-A agents).
        """
        from app.modules.chat.orchestrator import ChatOrchestrationService

        tid, uid = tenant_and_user
        # Use an agent_id that has no ACL row (no agent_cards row either)
        phantom_agent_id = str(uuid.uuid4())

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as db:
                    svc = ChatOrchestrationService(
                        embedding_service=None,
                        vector_search_service=None,
                        profile_service=None,
                        working_memory_service=None,
                        org_context_service=None,
                        glossary_expander=None,
                        prompt_builder=None,
                        persistence_service=None,
                        confidence_calculator=None,
                        db_session=db,
                    )
                    result = await svc._check_agent_access(
                        agent_id=phantom_agent_id,
                        tenant_id=tid,
                        user_id=uid,
                        user_roles=["viewer"],
                    )
                    assert result is True, "No ACL row must default to fail-open (True)"
            finally:
                await engine.dispose()

        asyncio.run(_run())
