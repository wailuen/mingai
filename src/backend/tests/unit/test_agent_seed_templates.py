"""
Unit tests for TA-020: Seed agent templates.

Tests the seed_agent_templates() bootstrap function and the
_DB_SEED_TEMPLATES data structure.

Tier 1: Fast, isolated.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Seed template data structure tests
# ---------------------------------------------------------------------------


class TestSeedTemplateData:
    def setup_method(self):
        from app.core.seeds import _DB_SEED_TEMPLATES

        self._templates = _DB_SEED_TEMPLATES

    def test_has_four_templates(self):
        assert len(self._templates) == 4

    def test_all_have_required_fields(self):
        required_keys = {
            "name",
            "description",
            "category",
            "system_prompt",
            "variable_definitions",
            "guardrails",
            "confidence_threshold",
        }
        for tmpl in self._templates:
            missing = required_keys - tmpl.keys()
            assert not missing, f"Template '{tmpl.get('name')}' missing: {missing}"

    def test_confidence_threshold_is_0_80(self):
        for tmpl in self._templates:
            assert tmpl["confidence_threshold"] == 0.80, (
                f"Template '{tmpl['name']}' has wrong confidence_threshold: "
                f"{tmpl['confidence_threshold']}"
            )

    def test_all_have_at_least_one_variable(self):
        for tmpl in self._templates:
            assert (
                len(tmpl["variable_definitions"]) >= 1
            ), f"Template '{tmpl['name']}' has no variable_definitions"

    def test_variable_definitions_have_required_keys(self):
        var_required = {"name", "label", "type", "required", "description"}
        for tmpl in self._templates:
            for var in tmpl["variable_definitions"]:
                missing = var_required - var.keys()
                assert (
                    not missing
                ), f"Variable in '{tmpl['name']}' missing keys: {missing}"

    def test_guardrails_are_lists(self):
        for tmpl in self._templates:
            assert isinstance(
                tmpl["guardrails"], list
            ), f"Template '{tmpl['name']}' guardrails must be a list"

    def test_template_names_match_expected(self):
        names = {t["name"] for t in self._templates}
        assert "HR Policy Q&A" in names
        assert "IT Helpdesk" in names
        assert "Procurement Policy" in names
        assert "Employee Onboarding" in names

    def test_system_prompts_use_variable_placeholders(self):
        """Each template's system_prompt should reference at least one {{variable}}."""
        for tmpl in self._templates:
            assert (
                "{{" in tmpl["system_prompt"]
            ), f"Template '{tmpl['name']}' system_prompt has no {{{{variable}}}} placeholders"

    def test_no_duplicate_names(self):
        names = [t["name"] for t in self._templates]
        assert len(names) == len(set(names)), "Duplicate template names found"


# ---------------------------------------------------------------------------
# seed_agent_templates() function tests
# ---------------------------------------------------------------------------


class TestSeedAgentTemplates:
    def _build_mock_db(self, already_seeded: bool = False):
        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        async def _execute(*args, **kwargs):
            result = MagicMock()
            sql = str(args[0]) if args else ""
            if "FROM agent_templates" in sql and "SELECT" in sql.upper():
                if already_seeded:
                    result.fetchone.return_value = (1,)  # exists
                else:
                    result.fetchone.return_value = None  # not yet seeded
            else:
                result.rowcount = 1
                result.fetchone.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=_execute)
        return mock_db

    @pytest.mark.asyncio
    async def test_inserts_4_templates_when_empty(self):
        """When no seed templates exist, all 4 are inserted."""
        mock_db = self._build_mock_db(already_seeded=False)
        with patch(
            "app.core.session.async_session_factory",
            return_value=mock_db,
        ):
            from app.core.seeds import seed_agent_templates

            count = await seed_agent_templates()

        assert count == 4

    @pytest.mark.asyncio
    async def test_inserts_0_when_already_seeded(self):
        """When seed templates already exist, nothing is inserted."""
        mock_db = self._build_mock_db(already_seeded=True)
        with patch(
            "app.core.session.async_session_factory",
            return_value=mock_db,
        ):
            from app.core.seeds import seed_agent_templates

            count = await seed_agent_templates()

        assert count == 0

    @pytest.mark.asyncio
    async def test_commit_called_when_inserted(self):
        """db.commit() must be called when new templates are inserted."""
        mock_db = self._build_mock_db(already_seeded=False)
        with patch(
            "app.core.session.async_session_factory",
            return_value=mock_db,
        ):
            from app.core.seeds import seed_agent_templates

            await seed_agent_templates()

        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_commit_not_called_when_no_inserts(self):
        """db.commit() must NOT be called when nothing is inserted."""
        mock_db = self._build_mock_db(already_seeded=True)
        with patch(
            "app.core.session.async_session_factory",
            return_value=mock_db,
        ):
            from app.core.seeds import seed_agent_templates

            await seed_agent_templates()

        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_credentials_in_sql_params(self):
        """No private keys or secrets should appear in the SQL params."""
        mock_db = self._build_mock_db(already_seeded=False)
        with patch(
            "app.core.session.async_session_factory",
            return_value=mock_db,
        ):
            from app.core.seeds import seed_agent_templates

            await seed_agent_templates()

        for call in mock_db.execute.call_args_list:
            if call.args and len(call.args) > 1:
                params = call.args[1]
                for key, val in params.items():
                    assert "private_key" not in str(val).lower()
                    assert "secret" not in key.lower()
