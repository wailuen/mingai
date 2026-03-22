"""
Unit tests for TODO-15: TA Agent Deployment Wizard backend additions.

Coverage:
  - DeployFromLibraryRequest — new fields (allowed_roles, allowed_user_ids,
    kb_search_mode, rate_limit_per_minute)
  - credential_manager.store_credentials — vault path isolation
  - credential_manager.test_credentials — 15s timeout enforcement
  - credential_manager.get_credential — per-agent isolation
  - POST /admin/agents/test-credentials — endpoint shape

Tier 1: All dependencies mocked.  No database or Redis required.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# JWT helpers — mirror the pattern used in test_agent_deployment.py
# ---------------------------------------------------------------------------

TEST_JWT_SECRET = "d" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TEST_TEMPLATE_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

_MOD = "app.modules.agents.routes"


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


def _tenant_headers() -> dict:
    return {"Authorization": f"Bearer {_make_tenant_token()}"}


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


# ---------------------------------------------------------------------------
# 1. DeployFromLibraryRequest — schema validation of new fields
# ---------------------------------------------------------------------------


class TestDeployFromLibraryRequestSchema:
    """Validate new TODO-15 fields on the Pydantic model."""

    def _import(self):
        from app.modules.agents.routes import DeployFromLibraryRequest

        return DeployFromLibraryRequest

    def test_defaults(self):
        req = self._import()(template_id="t1", name="Bot")
        assert req.allowed_roles == []
        assert req.allowed_user_ids == []
        assert req.kb_search_mode == "parallel"
        assert req.rate_limit_per_minute is None

    def test_allowed_roles_accepted(self):
        req = self._import()(
            template_id="t1",
            name="Bot",
            allowed_roles=["admin", "user"],
        )
        assert req.allowed_roles == ["admin", "user"]

    def test_allowed_user_ids_accepted(self):
        req = self._import()(
            template_id="t1",
            name="Bot",
            allowed_user_ids=["uid-1", "uid-2"],
        )
        assert req.allowed_user_ids == ["uid-1", "uid-2"]

    def test_kb_search_mode_parallel(self):
        req = self._import()(template_id="t1", name="Bot", kb_search_mode="parallel")
        assert req.kb_search_mode == "parallel"

    def test_kb_search_mode_priority(self):
        req = self._import()(template_id="t1", name="Bot", kb_search_mode="priority")
        assert req.kb_search_mode == "priority"

    def test_kb_search_mode_invalid_rejected(self):
        with pytest.raises(ValidationError):
            self._import()(template_id="t1", name="Bot", kb_search_mode="invalid")

    def test_rate_limit_lower_bound(self):
        req = self._import()(template_id="t1", name="Bot", rate_limit_per_minute=1)
        assert req.rate_limit_per_minute == 1

    def test_rate_limit_upper_bound(self):
        req = self._import()(template_id="t1", name="Bot", rate_limit_per_minute=1000)
        assert req.rate_limit_per_minute == 1000

    def test_rate_limit_too_low_rejected(self):
        with pytest.raises(ValidationError):
            self._import()(template_id="t1", name="Bot", rate_limit_per_minute=0)

    def test_rate_limit_too_high_rejected(self):
        with pytest.raises(ValidationError):
            self._import()(template_id="t1", name="Bot", rate_limit_per_minute=1001)


# ---------------------------------------------------------------------------
# 2. store_credentials — vault path = {tenant_id}/agents/{agent_id}/{key}
# ---------------------------------------------------------------------------


class TestStoreCredentials:
    """Module-level store_credentials uses the correct vault path."""

    @pytest.mark.asyncio
    async def test_vault_path_pattern(self):
        """store_credentials must call vault_client.store_secret with path
        {tenant_id}/agents/{agent_id}/{key}."""
        from app.modules.agents.credential_manager import store_credentials

        mock_vault = MagicMock()
        schema = [{"key": "api_key", "required": True}]
        await store_credentials(
            tenant_id="t-111",
            agent_id="a-222",
            credentials={"api_key": "sk-secret"},
            schema=schema,
            vault_client=mock_vault,
        )
        mock_vault.store_secret.assert_called_once_with(
            "t-111/agents/a-222/api_key", "sk-secret"
        )

    @pytest.mark.asyncio
    async def test_unknown_keys_skipped(self):
        """Keys not in schema are skipped — never stored."""
        from app.modules.agents.credential_manager import store_credentials

        mock_vault = MagicMock()
        schema = [{"key": "api_key"}]
        await store_credentials(
            tenant_id="t-111",
            agent_id="a-222",
            credentials={"api_key": "sk-secret", "unknown_key": "bad"},
            schema=schema,
            vault_client=mock_vault,
        )
        # Only api_key stored; unknown_key never reaches vault
        assert mock_vault.store_secret.call_count == 1
        call_path = mock_vault.store_secret.call_args[0][0]
        assert "unknown_key" not in call_path

    @pytest.mark.asyncio
    async def test_two_agents_same_template_isolated(self):
        """Two deployments of the same template produce distinct vault paths."""
        from app.modules.agents.credential_manager import store_credentials

        mock_vault_a = MagicMock()
        mock_vault_b = MagicMock()
        schema = [{"key": "api_key"}]

        await store_credentials(
            tenant_id="tenant-1",
            agent_id="agent-AAA",
            credentials={"api_key": "value-a"},
            schema=schema,
            vault_client=mock_vault_a,
        )
        await store_credentials(
            tenant_id="tenant-1",
            agent_id="agent-BBB",
            credentials={"api_key": "value-b"},
            schema=schema,
            vault_client=mock_vault_b,
        )

        path_a = mock_vault_a.store_secret.call_args[0][0]
        path_b = mock_vault_b.store_secret.call_args[0][0]
        assert path_a != path_b
        assert "agent-AAA" in path_a
        assert "agent-BBB" in path_b

    @pytest.mark.asyncio
    async def test_path_not_tools_prefix(self):
        """Vault path must NOT use legacy 'tools/' prefix."""
        from app.modules.agents.credential_manager import store_credentials

        mock_vault = MagicMock()
        schema = [{"key": "api_key"}]
        await store_credentials(
            tenant_id="t-x",
            agent_id="a-y",
            credentials={"api_key": "secret"},
            schema=schema,
            vault_client=mock_vault,
        )
        path_used = mock_vault.store_secret.call_args[0][0]
        assert not path_used.startswith("tools/")
        assert path_used.startswith("t-x/agents/")

    @pytest.mark.asyncio
    async def test_empty_credentials_no_vault_calls(self):
        """Passing an empty credentials dict results in zero vault calls."""
        from app.modules.agents.credential_manager import store_credentials

        mock_vault = MagicMock()
        schema = [{"key": "api_key"}]
        await store_credentials(
            tenant_id="t",
            agent_id="a",
            credentials={},
            schema=schema,
            vault_client=mock_vault,
        )
        mock_vault.store_secret.assert_not_called()


# ---------------------------------------------------------------------------
# 3. test_credentials — 15s timeout enforcement
# ---------------------------------------------------------------------------


class TestTestCredentials:
    """test_credentials enforces 15s hard timeout."""

    @pytest.mark.asyncio
    async def test_returns_passed_true_on_success(self):
        from app.modules.agents.credential_manager import test_credentials

        result = await test_credentials(
            template_id="tmpl-1",
            credentials={"api_key": "sk-test"},
        )
        assert result.passed is True
        assert result.latency_ms is not None
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_timeout_returns_failed(self):
        """A timeout causes passed=False with a descriptive error."""
        from app.modules.agents.credential_manager import test_credentials

        # Patch asyncio.sleep to simulate a hang that exceeds timeout_seconds=0
        original_wait_for = asyncio.wait_for

        async def _always_timeout(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError()

        with patch("asyncio.wait_for", side_effect=_always_timeout):
            result = await test_credentials(
                template_id="tmpl-1",
                credentials={},
                timeout_seconds=0,
            )
        assert result.passed is False
        assert result.error_message is not None
        assert "timed out" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_latency_ms_populated_on_timeout(self):
        """latency_ms is set even on timeout."""
        from app.modules.agents.credential_manager import test_credentials

        async def _always_timeout(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError()

        with patch("asyncio.wait_for", side_effect=_always_timeout):
            result = await test_credentials(
                template_id="tmpl-1",
                credentials={},
                timeout_seconds=5,
            )
        # latency_ms is timeout_seconds * 1000 on TimeoutError
        assert result.latency_ms == 5000

    @pytest.mark.asyncio
    async def test_exception_returns_failed(self):
        """Unexpected exceptions produce passed=False with error_message."""
        from app.modules.agents.credential_manager import test_credentials

        async def _explode(coro, timeout):
            coro.close()
            raise RuntimeError("connection refused")

        with patch("asyncio.wait_for", side_effect=_explode):
            result = await test_credentials(
                template_id="tmpl-1",
                credentials={},
            )
        assert result.passed is False
        assert result.error_message == "connection refused"


# ---------------------------------------------------------------------------
# 4. get_credential — per-agent isolation
# ---------------------------------------------------------------------------


class TestGetCredential:
    """get_credential returns only the credential for the requested agent."""

    @pytest.mark.asyncio
    async def test_correct_vault_path_used(self):
        from app.modules.agents.credential_manager import get_credential

        mock_vault = MagicMock()
        mock_vault.get_secret.return_value = "sk-returned"

        result = await get_credential(
            tenant_id="ten-A",
            agent_id="ag-X",
            credential_key="api_key",
            vault_client=mock_vault,
        )
        assert result == "sk-returned"
        mock_vault.get_secret.assert_called_once_with("ten-A/agents/ag-X/api_key")

    @pytest.mark.asyncio
    async def test_agent_a_does_not_return_agent_b_creds(self):
        """Agent A's vault lookup must use agent A's path, not agent B's."""
        from app.modules.agents.credential_manager import get_credential

        calls = []

        def _mock_get_secret(path: str) -> str:
            calls.append(path)
            if "agent-A" in path:
                return "cred-for-A"
            raise KeyError(f"not found: {path}")

        mock_vault = MagicMock()
        mock_vault.get_secret.side_effect = _mock_get_secret

        result = await get_credential(
            tenant_id="tenant-1",
            agent_id="agent-A",
            credential_key="api_key",
            vault_client=mock_vault,
        )
        assert result == "cred-for-A"
        # Only one call made, and it used agent-A's path
        assert len(calls) == 1
        assert "agent-A" in calls[0]
        assert "agent-B" not in calls[0]

    @pytest.mark.asyncio
    async def test_vault_failure_returns_none(self):
        """Vault errors produce None, not an exception."""
        from app.modules.agents.credential_manager import get_credential

        mock_vault = MagicMock()
        mock_vault.get_secret.side_effect = RuntimeError("vault down")

        result = await get_credential(
            tenant_id="t",
            agent_id="a",
            credential_key="key",
            vault_client=mock_vault,
        )
        assert result is None


# ---------------------------------------------------------------------------
# 5. POST /admin/agents/test-credentials — endpoint shape
# ---------------------------------------------------------------------------


class TestTestCredentialsEndpoint:
    """The /admin/agents/test-credentials endpoint returns the expected shape."""

    _URL = "/api/v1/admin/agents/test-credentials"

    def test_requires_auth(self, client):
        resp = client.post(
            self._URL,
            json={"template_id": "t-1", "credentials": {"api_key": "sk"}},
        )
        assert resp.status_code == 401

    def test_returns_expected_shape(self, client):
        """Endpoint returns passed, error_message, latency_ms."""
        mock_result = MagicMock()
        mock_result.passed = True
        mock_result.error_message = None
        mock_result.latency_ms = 101

        with patch(
            "app.modules.agents.credential_manager.test_credentials",
            new=AsyncMock(return_value=mock_result),
        ):
            resp = client.post(
                self._URL,
                json={"template_id": "t-1", "credentials": {"api_key": "sk"}},
                headers=_tenant_headers(),
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "passed" in body
        assert "error_message" in body
        assert "latency_ms" in body

    def test_passed_true_on_success(self, client):
        mock_result = MagicMock()
        mock_result.passed = True
        mock_result.error_message = None
        mock_result.latency_ms = 50

        with patch(
            "app.modules.agents.credential_manager.test_credentials",
            new=AsyncMock(return_value=mock_result),
        ):
            resp = client.post(
                self._URL,
                json={"template_id": "t-1", "credentials": {}},
                headers=_tenant_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["passed"] is True

    def test_passed_false_on_failure(self, client):
        mock_result = MagicMock()
        mock_result.passed = False
        mock_result.error_message = "Credential test timed out after 15 seconds"
        mock_result.latency_ms = 15000

        with patch(
            "app.modules.agents.credential_manager.test_credentials",
            new=AsyncMock(return_value=mock_result),
        ):
            resp = client.post(
                self._URL,
                json={"template_id": "t-1", "credentials": {"api_key": "bad"}},
                headers=_tenant_headers(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["passed"] is False
        assert body["error_message"] is not None
        assert body["latency_ms"] == 15000
