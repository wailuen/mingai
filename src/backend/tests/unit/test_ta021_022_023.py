"""
Unit tests for TA-021, TA-022, TA-023 changes in app/modules/agents/routes.py.

TA-021: deploy_from_library produces status='active' and includes created_at.
TA-022: list_workspace_agents returns satisfaction_rate_7d / session_count_7d,
        status allowlist includes active/paused/archived, patch to paused/archived OK,
        end-user list includes 'active' agents.
TA-023: POST /admin/agents/{id}/test — schema, auth, 404, response shape, no DB writes.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.modules.agents.routes import (
    AgentTestRequest,
    DeployFromLibraryRequest,
    UpdateAgentStatusRequest,
    _VALID_AGENT_STATUSES,
    admin_router,
    deploy_from_library_db,
    get_agent_by_id_db,
    list_published_agents_db,
    list_workspace_agents_db,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_TENANT = "tenant-aaa-0000-0000-000000000001"
_FAKE_AGENT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
_FAKE_TEMPLATE_ID = "bbbbbbbb-0000-0000-0000-000000000002"
_FAKE_USER_ID = "cccccccc-0000-0000-0000-000000000003"


def _make_current_user(roles=None, scope="tenant"):
    user = MagicMock()
    user.tenant_id = _FAKE_TENANT
    user.id = _FAKE_USER_ID
    user.roles = roles or ["tenant_admin"]
    user.scope = scope
    user.plan = "enterprise"
    return user


def _async_mock_db():
    """Return a minimal AsyncSession mock."""
    db = AsyncMock()
    # execute returns an object whose .scalar() and .mappings().first() work
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# TA-021 Tests — deploy_from_library_db
# ---------------------------------------------------------------------------


class TestDeployFromLibrary:
    """TA-021: deploy_from_library_db produces status='active' and created_at."""

    @pytest.mark.asyncio
    async def test_deploy_returns_active_status(self):
        """Deployed agent must have status='active'."""
        db = _async_mock_db()

        # Simulate the INSERT execute call (no return value needed)
        # Then 2 commits (agent row + keypair)
        # Then SELECT created_at

        ts_row = MagicMock()
        ts_row.__getitem__ = (
            lambda self, key: "2026-01-01 00:00:00" if key == "created_at" else None
        )

        # Build sequential call results:
        # call 0: INSERT agent_cards
        # call 1: INSERT agent_access_control (ACL)
        # call 2: (keypair) UPDATE agent_cards
        # call 3: SELECT created_at
        insert_result = MagicMock()
        acl_result = MagicMock()
        update_result = MagicMock()

        ts_result = MagicMock()
        ts_result.mappings.return_value.first.return_value = ts_row

        db.execute = AsyncMock(side_effect=[insert_result, acl_result, update_result, ts_result])

        with patch(
            "app.modules.agents.routes.generate_agent_keypair",
            return_value=("pub_key", "enc_priv_key"),
        ):
            result = await deploy_from_library_db(
                tenant_id=_FAKE_TENANT,
                template_id=_FAKE_TEMPLATE_ID,
                template_version=1,
                template_name="Test Template",
                name="My Agent",
                system_prompt="You are a helpful assistant.",
                description="desc",
                category="HR",
                capabilities=[],
                created_by=_FAKE_USER_ID,
                db=db,
            )

        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_deploy_returns_created_at(self):
        """Deployed agent response must include created_at."""
        db = _async_mock_db()

        ts_row = MagicMock()
        ts_row.__getitem__ = (
            lambda self, key: "2026-03-01 10:00:00" if key == "created_at" else None
        )

        insert_result = MagicMock()
        acl_result = MagicMock()
        update_result = MagicMock()
        ts_result = MagicMock()
        ts_result.mappings.return_value.first.return_value = ts_row

        db.execute = AsyncMock(side_effect=[insert_result, acl_result, update_result, ts_result])

        with patch(
            "app.modules.agents.routes.generate_agent_keypair",
            return_value=("pub_key", "enc_priv_key"),
        ):
            result = await deploy_from_library_db(
                tenant_id=_FAKE_TENANT,
                template_id=_FAKE_TEMPLATE_ID,
                template_version=2,
                template_name="Template",
                name="Agent Name",
                system_prompt="System.",
                description="",
                category=None,
                capabilities=[],
                created_by=_FAKE_USER_ID,
                db=db,
            )

        assert "created_at" in result
        assert result["created_at"] == "2026-03-01 10:00:00"

    @pytest.mark.asyncio
    async def test_deploy_inserts_active_status_in_sql(self):
        """The SQL INSERT must use 'active' not 'published'."""
        db = _async_mock_db()

        captured_sql: list[str] = []

        async def capture_execute(sql_expr, params=None):
            sql_str = str(sql_expr)
            captured_sql.append(sql_str)
            result = MagicMock()
            result.mappings.return_value.first.return_value = None
            return result

        db.execute = capture_execute

        with patch(
            "app.modules.agents.routes.generate_agent_keypair",
            side_effect=Exception("skip keypair"),
        ):
            try:
                await deploy_from_library_db(
                    tenant_id=_FAKE_TENANT,
                    template_id=_FAKE_TEMPLATE_ID,
                    template_version=1,
                    template_name="T",
                    name="N",
                    system_prompt="S",
                    description="D",
                    category=None,
                    capabilities=[],
                    created_by=_FAKE_USER_ID,
                    db=db,
                )
            except Exception:
                pass

        # First SQL call is the INSERT
        insert_sql = captured_sql[0] if captured_sql else ""
        assert "'active'" in insert_sql, (
            "INSERT SQL must use 'active' status, got: " + insert_sql
        )
        assert "'published'" not in insert_sql

    @pytest.mark.asyncio
    async def test_requires_tenant_admin(self):
        """deploy_from_library endpoint requires require_tenant_admin dependency."""
        import inspect
        from app.modules.agents.routes import deploy_from_library
        from app.core.dependencies import require_tenant_admin

        sig = inspect.signature(deploy_from_library)
        found = False
        for param in sig.parameters.values():
            if (
                hasattr(param.default, "dependency")
                and param.default.dependency is require_tenant_admin
            ):
                found = True
                break
        assert found, "require_tenant_admin not found in deploy_from_library signature"

    @pytest.mark.asyncio
    async def test_missing_required_variable_returns_422(self):
        """Missing required variable in template raises 422."""
        db = _async_mock_db()

        # _get_agent_template_by_id returns a template with a required var
        fake_tmpl = {
            "id": _FAKE_TEMPLATE_ID,
            "name": "Template",
            "description": "",
            "category": "HR",
            "system_prompt": "Hello {{company_name}}",
            "variable_definitions": [{"name": "company_name", "required": True}],
            "guardrails": [],
            "version": 1,
        }

        body = DeployFromLibraryRequest(
            template_id=_FAKE_TEMPLATE_ID,
            name="Agent",
            variable_values={},  # missing company_name
        )

        current_user = _make_current_user()

        with (
            patch(
                "app.modules.agents.routes._get_agent_template_by_id",
                new=AsyncMock(return_value=fake_tmpl),
            ),
            patch(
                "app.modules.agents.routes._validate_kb_ids_for_tenant",
                new=AsyncMock(return_value=None),
            ),
        ):
            from app.modules.agents.routes import deploy_from_library

            with pytest.raises(HTTPException) as exc_info:
                await deploy_from_library(
                    body=body,
                    current_user=current_user,
                    session=db,
                )

        assert exc_info.value.status_code == 422
        assert "company_name" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_kb_ids_validated_for_tenant(self):
        """kb_ids not belonging to the tenant raise 403."""
        db = _async_mock_db()

        fake_tmpl = {
            "id": _FAKE_TEMPLATE_ID,
            "name": "Template",
            "description": "",
            "category": None,
            "system_prompt": "Hello",
            "variable_definitions": [],
            "guardrails": [],
            "version": 1,
        }

        body = DeployFromLibraryRequest(
            template_id=_FAKE_TEMPLATE_ID,
            name="Agent",
            kb_ids=["eeeeeeee-0000-0000-0000-000000000099"],
        )

        current_user = _make_current_user()

        async def _raise_403(kb_ids, tenant_id, db):
            raise HTTPException(
                status_code=403,
                detail="One or more kb_ids do not belong to this workspace.",
            )

        with (
            patch(
                "app.modules.agents.routes._get_agent_template_by_id",
                new=AsyncMock(return_value=fake_tmpl),
            ),
            patch(
                "app.modules.agents.routes._validate_kb_ids_for_tenant",
                new=_raise_403,
            ),
        ):
            from app.modules.agents.routes import deploy_from_library

            with pytest.raises(HTTPException) as exc_info:
                await deploy_from_library(
                    body=body,
                    current_user=current_user,
                    session=db,
                )

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# TA-022 Tests — list_workspace_agents_db metrics
# ---------------------------------------------------------------------------


class TestAdminAgentList:
    """TA-022: list_workspace_agents_db returns satisfaction_rate_7d and session_count_7d."""

    @pytest.mark.asyncio
    async def test_list_returns_satisfaction_rate_7d(self):
        """Response items must contain satisfaction_rate_7d key."""
        db = _async_mock_db()

        # Mock COUNT(*) for count_sql
        count_result = MagicMock()
        count_result.scalar.return_value = 1

        # Mock agent row
        agent_row = MagicMock()
        agent_row.__getitem__ = lambda self, key: {
            "id": _FAKE_AGENT_ID,
            "name": "My Agent",
            "description": "desc",
            "category": "HR",
            "source": "library",
            "status": "active",
            "version": 1,
            "template_id": _FAKE_TEMPLATE_ID,
            "template_name": "T",
            "created_at": "2026-01-01",
        }[key]
        rows_result = MagicMock()
        rows_result.mappings.return_value = [agent_row]

        # Batch satisfaction_rate_7d: 3 positive out of 4 total
        sr_batch_row = MagicMock()
        sr_batch_row.__getitem__ = lambda self, key: {
            "agent_id": _FAKE_AGENT_ID,
            "positive": 3,
            "total": 4,
        }[key]
        sr_batch_result = MagicMock()
        sr_batch_result.mappings.return_value = [sr_batch_row]

        # Batch session_count_7d
        sc_batch_row = MagicMock()
        sc_batch_row.__getitem__ = lambda self, key: {
            "agent_id": _FAKE_AGENT_ID,
            "session_count": 5,
        }[key]
        sc_batch_result = MagicMock()
        sc_batch_result.mappings.return_value = [sc_batch_row]

        db.execute = AsyncMock(
            side_effect=[count_result, rows_result, sr_batch_result, sc_batch_result]
        )

        result = await list_workspace_agents_db(
            tenant_id=_FAKE_TENANT,
            page=1,
            page_size=20,
            status_filter=None,
            db=db,
        )

        assert len(result["items"]) == 1
        item = result["items"][0]
        assert "satisfaction_rate_7d" in item
        assert "user_count" not in item

    @pytest.mark.asyncio
    async def test_list_returns_session_count_7d(self):
        """Response items must contain session_count_7d key."""
        db = _async_mock_db()

        count_result = MagicMock()
        count_result.scalar.return_value = 1

        agent_row = MagicMock()
        agent_row.__getitem__ = lambda self, key: {
            "id": _FAKE_AGENT_ID,
            "name": "Agent",
            "description": "",
            "category": None,
            "source": "custom",
            "status": "published",
            "version": 2,
            "template_id": None,
            "template_name": None,
            "created_at": "2026-02-01",
        }[key]
        rows_result = MagicMock()
        rows_result.mappings.return_value = [agent_row]

        # Batch sr: no ratings → empty result set
        sr_batch_result = MagicMock()
        sr_batch_result.mappings.return_value = []

        # Batch sc: 12 sessions
        sc_batch_row = MagicMock()
        sc_batch_row.__getitem__ = lambda self, key: {
            "agent_id": _FAKE_AGENT_ID,
            "session_count": 12,
        }[key]
        sc_batch_result = MagicMock()
        sc_batch_result.mappings.return_value = [sc_batch_row]

        db.execute = AsyncMock(
            side_effect=[count_result, rows_result, sr_batch_result, sc_batch_result]
        )

        result = await list_workspace_agents_db(
            tenant_id=_FAKE_TENANT,
            page=1,
            page_size=20,
            status_filter=None,
            db=db,
        )

        item = result["items"][0]
        assert "session_count_7d" in item
        assert item["session_count_7d"] == 12

    @pytest.mark.asyncio
    async def test_satisfaction_rate_7d_null_when_no_ratings(self):
        """satisfaction_rate_7d must be None when there are no ratings."""
        db = _async_mock_db()

        count_result = MagicMock()
        count_result.scalar.return_value = 1

        agent_row = MagicMock()
        agent_row.__getitem__ = lambda self, key: {
            "id": _FAKE_AGENT_ID,
            "name": "A",
            "description": "",
            "category": None,
            "source": "custom",
            "status": "active",
            "version": 1,
            "template_id": None,
            "template_name": None,
            "created_at": "2026-01-01",
        }[key]
        rows_result = MagicMock()
        rows_result.mappings.return_value = [agent_row]

        # Batch sr: no ratings → empty result set
        sr_batch_result = MagicMock()
        sr_batch_result.mappings.return_value = []

        # Batch sc: 0 sessions
        sc_batch_result = MagicMock()
        sc_batch_result.mappings.return_value = []

        db.execute = AsyncMock(
            side_effect=[count_result, rows_result, sr_batch_result, sc_batch_result]
        )

        result = await list_workspace_agents_db(
            tenant_id=_FAKE_TENANT,
            page=1,
            page_size=20,
            status_filter=None,
            db=db,
        )

        assert result["items"][0]["satisfaction_rate_7d"] is None

    def test_status_filter_active(self):
        """_VALID_AGENT_STATUSES must include 'active'."""
        assert "active" in _VALID_AGENT_STATUSES

    def test_status_filter_paused(self):
        """_VALID_AGENT_STATUSES must include 'paused'."""
        assert "paused" in _VALID_AGENT_STATUSES

    def test_status_filter_archived(self):
        """_VALID_AGENT_STATUSES must include 'archived'."""
        assert "archived" in _VALID_AGENT_STATUSES


class TestAgentStatusPatch:
    """TA-022: PATCH /admin/agents/{id}/status accepts active, paused, archived."""

    def test_patch_status_schema_paused(self):
        """UpdateAgentStatusRequest must accept 'paused'."""
        req = UpdateAgentStatusRequest(status="paused")
        assert req.status == "paused"

    def test_patch_status_schema_archived(self):
        """UpdateAgentStatusRequest must accept 'archived'."""
        req = UpdateAgentStatusRequest(status="archived")
        assert req.status == "archived"

    def test_patch_status_schema_active(self):
        """UpdateAgentStatusRequest must accept 'active'."""
        req = UpdateAgentStatusRequest(status="active")
        assert req.status == "active"

    def test_patch_status_schema_rejects_invalid(self):
        """UpdateAgentStatusRequest must reject unknown statuses."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            UpdateAgentStatusRequest(status="invalid_status")

    @pytest.mark.asyncio
    async def test_patch_status_to_paused_returns_200(self):
        """Patching to 'paused' must succeed (no system_prompt check)."""
        db = _async_mock_db()
        current_user = _make_current_user()

        existing_agent = {
            "id": _FAKE_AGENT_ID,
            "name": "Agent",
            "system_prompt": "You are helpful.",
            "status": "active",
            "version": 1,
            "description": None,
            "category": None,
            "avatar": None,
            "source": "library",
            "capabilities": [],
            "template_id": None,
            "template_version": None,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
        }

        with (
            patch(
                "app.modules.agents.routes.get_agent_by_id_db",
                new=AsyncMock(return_value=existing_agent),
            ),
            patch(
                "app.modules.agents.routes.update_agent_status_db",
                new=AsyncMock(return_value={"id": _FAKE_AGENT_ID, "status": "paused"}),
            ),
            patch(
                "app.modules.agents.routes.insert_audit_log",
                new=AsyncMock(return_value=None),
            ),
        ):
            from app.modules.agents.routes import (
                UpdateAgentStatusRequest,
                update_agent_status,
            )

            body = UpdateAgentStatusRequest(status="paused")
            result = await update_agent_status(
                agent_id=_FAKE_AGENT_ID,
                body=body,
                current_user=current_user,
                session=db,
            )

        assert result["status"] == "paused"

    @pytest.mark.asyncio
    async def test_patch_status_to_archived_returns_200(self):
        """Patching to 'archived' must succeed."""
        db = _async_mock_db()
        current_user = _make_current_user()

        existing_agent = {
            "id": _FAKE_AGENT_ID,
            "name": "Agent",
            "system_prompt": "",  # empty system_prompt should not block non-published
            "status": "paused",
            "version": 1,
            "description": None,
            "category": None,
            "avatar": None,
            "source": "library",
            "capabilities": [],
            "template_id": None,
            "template_version": None,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
        }

        with (
            patch(
                "app.modules.agents.routes.get_agent_by_id_db",
                new=AsyncMock(return_value=existing_agent),
            ),
            patch(
                "app.modules.agents.routes.update_agent_status_db",
                new=AsyncMock(
                    return_value={"id": _FAKE_AGENT_ID, "status": "archived"}
                ),
            ),
            patch(
                "app.modules.agents.routes.insert_audit_log",
                new=AsyncMock(return_value=None),
            ),
        ):
            from app.modules.agents.routes import (
                UpdateAgentStatusRequest,
                update_agent_status,
            )

            body = UpdateAgentStatusRequest(status="archived")
            result = await update_agent_status(
                agent_id=_FAKE_AGENT_ID,
                body=body,
                current_user=current_user,
                session=db,
            )

        assert result["status"] == "archived"


# ---------------------------------------------------------------------------
# TA-023 Tests — POST /admin/agents/{id}/test
# ---------------------------------------------------------------------------


class TestAgentTestChat:
    """TA-023: Agent test harness endpoint."""

    def test_query_too_long_returns_422(self):
        """Query exceeding 2000 chars must fail Pydantic validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AgentTestRequest(query="x" * 2001)

    def test_query_empty_returns_422(self):
        """Empty query must fail Pydantic validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AgentTestRequest(query="")

    def test_query_max_length_accepted(self):
        """Query of exactly 2000 chars must be accepted."""
        req = AgentTestRequest(query="a" * 2000)
        assert len(req.query) == 2000

    @pytest.mark.asyncio
    async def test_agent_not_found_returns_404(self):
        """Returns 404 when agent doesn't exist for tenant."""
        db = _async_mock_db()
        current_user = _make_current_user()

        with patch(
            "app.modules.agents.routes.get_agent_by_id_db",
            new=AsyncMock(return_value=None),
        ):
            from app.modules.agents.routes import test_agent

            with pytest.raises(HTTPException) as exc_info:
                await test_agent(
                    agent_id=_FAKE_AGENT_ID,
                    body=AgentTestRequest(query="What is the policy?"),
                    current_user=current_user,
                    session=db,
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_requires_tenant_admin(self):
        """test_agent endpoint must have require_tenant_admin dependency."""
        import inspect
        from app.modules.agents.routes import test_agent
        from app.core.dependencies import require_tenant_admin

        sig = inspect.signature(test_agent)
        found = False
        for param in sig.parameters.values():
            if (
                hasattr(param.default, "dependency")
                and param.default.dependency is require_tenant_admin
            ):
                found = True
                break
        assert found, "require_tenant_admin not found in test_agent signature"

    @pytest.mark.asyncio
    async def test_returns_answer_and_metadata(self):
        """Returns correct response shape: answer, sources, confidence, tokens, latency."""
        import os

        db = _async_mock_db()
        current_user = _make_current_user()

        fake_agent = {
            "id": _FAKE_AGENT_ID,
            "name": "Test Agent",
            "system_prompt": "You are a helpful assistant.",
            "status": "active",
            "version": 1,
            "capabilities": [],
            "description": "",
            "category": "HR",
            "avatar": None,
            "source": "library",
            "template_id": None,
            "template_version": None,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
        }

        # Mock LLM response
        fake_usage = MagicMock()
        fake_usage.prompt_tokens = 15
        fake_usage.completion_tokens = 42

        fake_choice = MagicMock()
        fake_choice.message.content = "Here is the answer."

        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]
        fake_completion.usage = fake_usage

        fake_llm_client = MagicMock()
        fake_llm_client.chat.completions.create = AsyncMock(
            return_value=fake_completion
        )

        with (
            patch(
                "app.modules.agents.routes.get_agent_by_id_db",
                new=AsyncMock(return_value=fake_agent),
            ),
            patch.dict(
                os.environ, {"PRIMARY_MODEL": "gpt-5", "CLOUD_PROVIDER": "openai"}
            ),
            patch(
                "app.modules.agents.routes.EmbeddingService",
                side_effect=Exception("no embedding"),
                create=True,
            ),
            patch(
                "openai.AsyncOpenAI",
                return_value=fake_llm_client,
            ),
        ):
            from app.modules.agents.routes import test_agent

            result = await test_agent(
                agent_id=_FAKE_AGENT_ID,
                body=AgentTestRequest(query="What is the vacation policy?"),
                current_user=current_user,
                session=db,
            )

        assert "answer" in result
        assert "sources" in result
        assert "confidence" in result
        assert "tokens_in" in result
        assert "tokens_out" in result
        assert "latency_ms" in result
        assert isinstance(result["sources"], list)
        assert isinstance(result["latency_ms"], int)

    @pytest.mark.asyncio
    async def test_no_conversation_written_to_db(self):
        """test_agent must NOT call db.execute for conversation/message writes."""
        import os

        db = _async_mock_db()
        current_user = _make_current_user()

        fake_agent = {
            "id": _FAKE_AGENT_ID,
            "name": "A",
            "system_prompt": "System prompt.",
            "status": "active",
            "version": 1,
            "capabilities": [],
            "description": "",
            "category": None,
            "avatar": None,
            "source": "library",
            "template_id": None,
            "template_version": None,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
        }

        fake_usage = MagicMock()
        fake_usage.prompt_tokens = 10
        fake_usage.completion_tokens = 20

        fake_choice = MagicMock()
        fake_choice.message.content = "Answer."

        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]
        fake_completion.usage = fake_usage

        fake_llm_client = MagicMock()
        fake_llm_client.chat.completions.create = AsyncMock(
            return_value=fake_completion
        )

        with (
            patch(
                "app.modules.agents.routes.get_agent_by_id_db",
                new=AsyncMock(return_value=fake_agent),
            ),
            patch.dict(
                os.environ, {"PRIMARY_MODEL": "gpt-5", "CLOUD_PROVIDER": "openai"}
            ),
            patch(
                "app.modules.agents.routes.EmbeddingService",
                side_effect=Exception("no embedding"),
                create=True,
            ),
            patch(
                "openai.AsyncOpenAI",
                return_value=fake_llm_client,
            ),
        ):
            from app.modules.agents.routes import test_agent

            await test_agent(
                agent_id=_FAKE_AGENT_ID,
                body=AgentTestRequest(query="Test query"),
                current_user=current_user,
                session=db,
            )

        # db.execute and db.commit must NOT have been called (no DB writes)
        db.execute.assert_not_called()
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_returns_504(self):
        """LLM call exceeding 30s must raise 504."""
        import asyncio
        import os

        db = _async_mock_db()
        current_user = _make_current_user()

        fake_agent = {
            "id": _FAKE_AGENT_ID,
            "name": "A",
            "system_prompt": "S.",
            "status": "active",
            "version": 1,
            "capabilities": [],
            "description": "",
            "category": None,
            "avatar": None,
            "source": "library",
            "template_id": None,
            "template_version": None,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
        }

        async def _slow_create(**kwargs):
            raise asyncio.TimeoutError()

        fake_llm_client = MagicMock()
        fake_llm_client.chat.completions.create = _slow_create

        async def _fake_wait_for(coro, timeout):
            raise asyncio.TimeoutError()

        with (
            patch(
                "app.modules.agents.routes.get_agent_by_id_db",
                new=AsyncMock(return_value=fake_agent),
            ),
            patch.dict(
                os.environ, {"PRIMARY_MODEL": "gpt-5", "CLOUD_PROVIDER": "openai"}
            ),
            patch(
                "app.modules.agents.routes.EmbeddingService",
                side_effect=Exception("no embedding"),
                create=True,
            ),
            patch(
                "openai.AsyncOpenAI",
                return_value=fake_llm_client,
            ),
            patch("asyncio.wait_for", new=_fake_wait_for),
        ):
            from app.modules.agents.routes import test_agent

            with pytest.raises(HTTPException) as exc_info:
                await test_agent(
                    agent_id=_FAKE_AGENT_ID,
                    body=AgentTestRequest(query="Test"),
                    current_user=current_user,
                    session=db,
                )

        assert exc_info.value.status_code == 504


# ---------------------------------------------------------------------------
# TA-022: end-user list includes 'active' agents
# ---------------------------------------------------------------------------


class TestListPublishedAgents:
    """TA-021/022: list_published_agents_db includes active agents."""

    @pytest.mark.asyncio
    async def test_active_agents_included_in_end_user_list(self):
        """list_published_agents_db SQL must use IN ('published', 'active')."""
        db = _async_mock_db()

        captured_sql: list[str] = []

        async def capture_execute(sql_expr, params=None):
            captured_sql.append(str(sql_expr))
            result = MagicMock()
            result.scalar.return_value = 0
            result.fetchall.return_value = []
            return result

        db.execute = capture_execute

        await list_published_agents_db(
            tenant_id=_FAKE_TENANT,
            page=1,
            page_size=20,
            db=db,
        )

        all_sql = " ".join(captured_sql)
        assert "active" in all_sql, "SQL must include 'active' in status filter"
        assert (
            "published" in all_sql
        ), "SQL must still include 'published' in status filter"
