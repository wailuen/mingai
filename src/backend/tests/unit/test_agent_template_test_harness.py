"""
Unit tests for PA-021 POST /platform/agent-templates/{id}/test endpoint.

Tests: auth, prompt validation, variable substitution, missing required variable,
guardrail evaluation, timeout handling, partial results.

Tier 1: Fast, isolated. Uses dependency_overrides + AsyncMock helpers.
"""
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "b" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_TEMPLATE_ID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"

_MOD = "app.modules.platform.routes"

_BASE = f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}/test"

_MOCK_TEMPLATE = {
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
    "status": "Draft",
    "changelog": None,
    "created_by": None,
    "created_at": "2026-03-16T00:00:00+00:00",
    "updated_at": "2026-03-16T00:00:00+00:00",
}


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


def _patch_get_template(return_value):
    return patch(
        f"{_MOD}._get_agent_template_db", new=AsyncMock(return_value=return_value)
    )


def _patch_run_prompt(return_value):
    return patch(
        f"{_MOD}._run_template_prompt", new=AsyncMock(return_value=return_value)
    )


def _make_test_result(prompt="Hello?", response="Hi!", guardrail_triggered=False):
    from app.modules.platform.routes import TemplateTestResult

    return TemplateTestResult(
        prompt=prompt,
        response=response,
        tokens_in=10,
        tokens_out=5,
        latency_ms=200,
        guardrail_triggered=guardrail_triggered,
        guardrail_reason="" if not guardrail_triggered else "matched rule",
        timed_out=False,
    )


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestTestHarnessAuth:
    def test_requires_auth(self, client):
        resp = client.post(
            _BASE,
            json={"test_prompts": ["Hello?"], "variable_values": {"company": "Acme"}},
        )
        assert resp.status_code == 401

    def test_requires_platform_admin(self, client):
        resp = client.post(
            _BASE,
            json={"test_prompts": ["Hello?"], "variable_values": {"company": "Acme"}},
            headers=_tenant_headers(),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------


class TestTestHarnessValidation:
    def test_rejects_empty_prompts(self, client):
        resp = client.post(
            _BASE,
            json={"test_prompts": [], "variable_values": {}},
            headers=_platform_headers(),
        )
        assert resp.status_code == 422

    def test_rejects_over_5_prompts(self, client):
        resp = client.post(
            _BASE,
            json={
                "test_prompts": ["p1", "p2", "p3", "p4", "p5", "p6"],
                "variable_values": {},
            },
            headers=_platform_headers(),
        )
        assert resp.status_code == 422

    def test_accepts_exactly_5_prompts(self, client):
        template_no_vars = {
            **_MOCK_TEMPLATE,
            "variable_definitions": [],
            "system_prompt": "You are helpful.",
        }
        result = _make_test_result()
        with (
            _patch_get_template(template_no_vars),
            _patch_run_prompt(result),
        ):
            resp = client.post(
                _BASE,
                json={
                    "test_prompts": ["p1", "p2", "p3", "p4", "p5"],
                    "variable_values": {},
                },
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        assert len(resp.json()["tests"]) == 5


# ---------------------------------------------------------------------------
# Template lookup tests
# ---------------------------------------------------------------------------


class TestTestHarnessTemplateLookup:
    def test_404_for_missing_template(self, client):
        with _patch_get_template(None):
            resp = client.post(
                _BASE,
                json={"test_prompts": ["Hello?"], "variable_values": {}},
                headers=_platform_headers(),
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Variable substitution tests
# ---------------------------------------------------------------------------


class TestVariableSubstitution:
    def test_missing_required_variable_returns_422(self, client):
        """Required variable not in variable_values → 422 with field name."""
        with _patch_get_template(_MOCK_TEMPLATE):
            resp = client.post(
                _BASE,
                json={
                    "test_prompts": ["What is our leave policy?"],
                    "variable_values": {},
                },
                headers=_platform_headers(),
            )
        assert resp.status_code == 422
        assert "company" in resp.json()["detail"]

    def test_optional_variable_can_be_omitted(self, client):
        template_opt = {
            **_MOCK_TEMPLATE,
            "system_prompt": "You are helpful for {{department}}.",
            "variable_definitions": [
                {
                    "name": "department",
                    "type": "text",
                    "label": "Department",
                    "required": False,
                }
            ],
        }
        result = _make_test_result()
        with (
            _patch_get_template(template_opt),
            _patch_run_prompt(result),
        ):
            resp = client.post(
                _BASE,
                json={"test_prompts": ["Hello?"], "variable_values": {}},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200

    def test_variable_substitution_applied(self):
        """Unit test the substitution function directly."""
        from app.modules.platform.routes import _substitute_variables

        prompt = "You are an assistant for {{company}} in {{country}}."
        result = _substitute_variables(prompt, {"company": "Acme", "country": "SG"})
        assert result == "You are an assistant for Acme in SG."

    def test_missing_variable_kept_as_placeholder(self):
        """Variables not in variable_values are left as-is (no KeyError)."""
        from app.modules.platform.routes import _substitute_variables

        prompt = "You work for {{company}}."
        result = _substitute_variables(prompt, {})
        assert result == "You work for {{company}}."


# ---------------------------------------------------------------------------
# Guardrail evaluation tests
# ---------------------------------------------------------------------------


class TestGuardrailEvaluation:
    def test_no_guardrails_returns_not_triggered(self):
        from app.modules.platform.routes import _evaluate_guardrails

        triggered, reason = _evaluate_guardrails("Normal response.", [])
        assert triggered is False
        assert reason == ""

    def test_guardrail_pattern_match(self):
        from app.modules.platform.routes import _evaluate_guardrails

        guardrails = [
            {"pattern": r"password", "action": "block", "reason": "PII leakage"}
        ]
        triggered, reason = _evaluate_guardrails("Your password is 1234.", guardrails)
        assert triggered is True
        assert "PII" in reason

    def test_guardrail_no_match(self):
        from app.modules.platform.routes import _evaluate_guardrails

        guardrails = [
            {"pattern": r"password", "action": "block", "reason": "PII leakage"}
        ]
        triggered, reason = _evaluate_guardrails("Everything looks good.", guardrails)
        assert triggered is False

    def test_guardrail_case_insensitive(self):
        from app.modules.platform.routes import _evaluate_guardrails

        guardrails = [{"pattern": r"PASSWORD", "action": "block", "reason": "PII"}]
        triggered, _ = _evaluate_guardrails("your password is here.", guardrails)
        assert triggered is True

    def test_guardrail_invalid_regex_falls_back_to_substring(self):
        from app.modules.platform.routes import _evaluate_guardrails

        guardrails = [
            {"pattern": "[invalid(regex", "action": "block", "reason": "test"}
        ]
        # Invalid regex — should fall back to substring matching
        triggered, _ = _evaluate_guardrails("[invalid(regex in text", guardrails)
        assert triggered is True

    def test_guardrail_triggered_in_response(self, client):
        """End-to-end: guardrail triggered → guardrail_triggered=True in result."""
        template_with_guard = {
            **_MOCK_TEMPLATE,
            "variable_definitions": [],
            "system_prompt": "You are helpful.",
            "guardrails": [
                {"pattern": "confidential", "action": "block", "reason": "data leak"}
            ],
        }
        triggered_result = _make_test_result(
            response="This is confidential info.", guardrail_triggered=True
        )
        with (
            _patch_get_template(template_with_guard),
            _patch_run_prompt(triggered_result),
        ):
            resp = client.post(
                _BASE,
                json={"test_prompts": ["Tell me a secret."], "variable_values": {}},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tests"][0]["guardrail_triggered"] is True


# ---------------------------------------------------------------------------
# Timeout and partial results tests
# ---------------------------------------------------------------------------


class TestTimeoutHandling:
    def test_timed_out_entry_has_flag(self):
        from app.modules.platform.routes import TemplateTestResult

        timed_out_result = TemplateTestResult(
            prompt="slow?",
            response="",
            tokens_in=0,
            tokens_out=0,
            latency_ms=30000,
            guardrail_triggered=False,
            guardrail_reason="",
            timed_out=True,
        )
        assert timed_out_result.timed_out is True

    def test_partial_results_when_some_timeout(self, client):
        """One prompt succeeds, one times out — both returned in tests[]."""
        template_no_vars = {
            **_MOCK_TEMPLATE,
            "variable_definitions": [],
            "system_prompt": "You are helpful.",
        }
        fast_result = _make_test_result(prompt="Fast?", response="Here!")
        from app.modules.platform.routes import TemplateTestResult

        slow_result = TemplateTestResult(
            prompt="Slow?",
            response="",
            tokens_in=0,
            tokens_out=0,
            latency_ms=30000,
            guardrail_triggered=False,
            guardrail_reason="",
            timed_out=True,
        )

        call_count = [0]

        async def _varying_prompt(prompt, resolved_prompt, guardrails, adapter=None):
            call_count[0] += 1
            return fast_result if call_count[0] == 1 else slow_result

        with (
            _patch_get_template(template_no_vars),
            patch(f"{_MOD}._run_template_prompt", new=_varying_prompt),
        ):
            resp = client.post(
                _BASE,
                json={"test_prompts": ["Fast?", "Slow?"], "variable_values": {}},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tests"]) == 2
        assert data["tests"][0]["timed_out"] is False
        assert data["tests"][1]["timed_out"] is True


# ---------------------------------------------------------------------------
# _run_template_prompt unit tests (mocks the provider, not the whole function)
# ---------------------------------------------------------------------------


class TestRunTemplatePrompt:
    """Direct unit tests for _run_template_prompt — exercises the real code path."""

    @pytest.mark.asyncio
    async def test_passes_model_kwarg_from_env(self, env_vars):
        """_run_template_prompt must pass model= to adapter.complete()."""
        import asyncio

        from app.modules.platform.routes import _run_template_prompt

        mock_adapter = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Sounds good."
        mock_response.tokens_in = 5
        mock_response.tokens_out = 3
        mock_response.latency_ms = 100
        mock_adapter.complete = AsyncMock(return_value=mock_response)

        with patch.dict(os.environ, {"PRIMARY_MODEL": "agentic-worker"}):
            result = await _run_template_prompt(
                prompt="Hello?",
                resolved_system_prompt="You are helpful.",
                guardrails=[],
                adapter=mock_adapter,
            )

        mock_adapter.complete.assert_awaited_once()
        call_kwargs = mock_adapter.complete.call_args
        assert call_kwargs.kwargs.get("model") == "agentic-worker"
        assert result.response == "Sounds good."
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_timeout_returns_sentinel_result(self, env_vars):
        """asyncio.TimeoutError is converted to timed_out=True result."""
        import asyncio

        from app.modules.platform.routes import _run_template_prompt

        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(side_effect=asyncio.TimeoutError)

        result = await _run_template_prompt(
            prompt="slow?",
            resolved_system_prompt="You are helpful.",
            guardrails=[],
            adapter=mock_adapter,
        )

        assert result.timed_out is True
        assert result.response == ""
        assert result.tokens_in == 0

    @pytest.mark.asyncio
    async def test_guardrail_applied_to_response(self, env_vars):
        """Guardrail matching is applied after response is received."""
        from app.modules.platform.routes import _run_template_prompt

        mock_adapter = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Your password is 1234."
        mock_response.tokens_in = 8
        mock_response.tokens_out = 5
        mock_response.latency_ms = 150
        mock_adapter.complete = AsyncMock(return_value=mock_response)

        guardrails = [{"pattern": "password", "action": "block", "reason": "PII leak"}]
        result = await _run_template_prompt(
            prompt="what is my password?",
            resolved_system_prompt="You are helpful.",
            guardrails=guardrails,
            adapter=mock_adapter,
        )

        assert result.guardrail_triggered is True
        assert "PII" in result.guardrail_reason


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestTestHarnessSuccess:
    def test_success_returns_tests_list(self, client):
        template_no_vars = {
            **_MOCK_TEMPLATE,
            "variable_definitions": [],
            "system_prompt": "You are helpful.",
        }
        result = _make_test_result(
            prompt="What can you do?", response="I can help with HR queries."
        )
        with (
            _patch_get_template(template_no_vars),
            _patch_run_prompt(result),
        ):
            resp = client.post(
                _BASE,
                json={"test_prompts": ["What can you do?"], "variable_values": {}},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "tests" in data
        assert len(data["tests"]) == 1
        assert data["tests"][0]["prompt"] == "What can you do?"
        assert data["tests"][0]["response"] == "I can help with HR queries."
        assert "tokens_in" in data["tests"][0]
        assert "tokens_out" in data["tests"][0]
        assert "guardrail_triggered" in data["tests"][0]

    def test_with_variable_substitution_success(self, client):
        result = _make_test_result(
            prompt="What is the leave policy?",
            response="You have 21 days annual leave.",
        )
        with (
            _patch_get_template(_MOCK_TEMPLATE),
            _patch_run_prompt(result),
        ):
            resp = client.post(
                _BASE,
                json={
                    "test_prompts": ["What is the leave policy?"],
                    "variable_values": {"company": "Acme Corp"},
                },
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
