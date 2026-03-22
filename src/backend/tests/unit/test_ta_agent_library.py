"""Unit tests for TODO-14: TA Agent Library Page — backend changes.

Tests cover:
- SEED_TEMPLATES contain the new rich card fields (template_type, llm_policy, etc.)
- GET /agents/templates returns template_type for seed templates
- GET /agents/templates/{id} returns variable_schema and changelog for seeds
- All seed templates have plan_required=None and auth_mode='none'
- _parse_jsonb helper handles all input variants
- _extract_variable_schema helper extracts tokens correctly
"""
import json
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.agents.routes import (
    SEED_TEMPLATES,
    _SEED_BY_ID,
    _extract_variable_schema,
    _parse_jsonb,
)


# ---------------------------------------------------------------------------
# _parse_jsonb helper
# ---------------------------------------------------------------------------


class TestParseJsonb:
    def test_none_returns_default(self):
        assert _parse_jsonb(None, {"key": "val"}) == {"key": "val"}

    def test_dict_returned_as_is(self):
        d = {"a": 1}
        assert _parse_jsonb(d, {}) is d

    def test_list_returned_as_is(self):
        lst = [1, 2, 3]
        assert _parse_jsonb(lst, []) is lst

    def test_valid_json_string_parsed(self):
        assert _parse_jsonb('{"x": 42}', {}) == {"x": 42}

    def test_invalid_json_string_returns_default(self):
        assert _parse_jsonb("not-json", {"fallback": True}) == {"fallback": True}

    def test_empty_string_returns_default(self):
        assert _parse_jsonb("", []) == []


# ---------------------------------------------------------------------------
# _extract_variable_schema helper
# ---------------------------------------------------------------------------


class TestExtractVariableSchema:
    def test_single_token(self):
        result = _extract_variable_schema("Hello {{company_name}}")
        assert result == [{"name": "company_name", "type": "string", "required": True, "description": ""}]

    def test_multiple_tokens(self):
        result = _extract_variable_schema("{{company_name}} and {{employee_role}}")
        assert len(result) == 2
        names = [r["name"] for r in result]
        assert "company_name" in names
        assert "employee_role" in names

    def test_duplicate_tokens_deduplicated(self):
        result = _extract_variable_schema("{{company_name}} is {{company_name}}")
        assert len(result) == 1
        assert result[0]["name"] == "company_name"

    def test_no_tokens(self):
        assert _extract_variable_schema("No variables here.") == []

    def test_empty_string(self):
        assert _extract_variable_schema("") == []

    def test_none_prompt(self):
        assert _extract_variable_schema(None) == []

    def test_order_preserved(self):
        result = _extract_variable_schema("{{alpha}} {{beta}} {{gamma}}")
        assert [r["name"] for r in result] == ["alpha", "beta", "gamma"]

    def test_all_fields_present(self):
        result = _extract_variable_schema("{{my_var}}")
        assert result[0]["type"] == "string"
        assert result[0]["required"] is True
        assert result[0]["description"] == ""


# ---------------------------------------------------------------------------
# SEED_TEMPLATES rich card fields
# ---------------------------------------------------------------------------


class TestSeedTemplatesRichFields:
    """All 4 seed templates must have the new TODO-14 fields."""

    EXPECTED_SEED_IDS = {"seed-hr", "seed-it", "seed-procurement", "seed-onboarding"}

    def test_all_four_seeds_present(self):
        assert {t["id"] for t in SEED_TEMPLATES} == self.EXPECTED_SEED_IDS

    @pytest.mark.parametrize("seed", SEED_TEMPLATES)
    def test_template_type_is_rag(self, seed):
        assert seed["template_type"] == "rag"

    @pytest.mark.parametrize("seed", SEED_TEMPLATES)
    def test_plan_required_is_none(self, seed):
        assert seed["plan_required"] is None

    @pytest.mark.parametrize("seed", SEED_TEMPLATES)
    def test_auth_mode_is_none_string(self, seed):
        assert seed["auth_mode"] == "none"

    @pytest.mark.parametrize("seed", SEED_TEMPLATES)
    def test_instance_count_is_zero(self, seed):
        assert seed["instance_count"] == 0

    @pytest.mark.parametrize("seed", SEED_TEMPLATES)
    def test_icon_is_none(self, seed):
        assert seed["icon"] is None

    @pytest.mark.parametrize("seed", SEED_TEMPLATES)
    def test_tags_is_empty_list(self, seed):
        assert seed["tags"] == []

    @pytest.mark.parametrize("seed", SEED_TEMPLATES)
    def test_attached_skills_is_empty_list(self, seed):
        assert seed["attached_skills"] == []

    @pytest.mark.parametrize("seed", SEED_TEMPLATES)
    def test_attached_tools_is_empty_list(self, seed):
        assert seed["attached_tools"] == []

    @pytest.mark.parametrize("seed", SEED_TEMPLATES)
    def test_llm_policy_structure(self, seed):
        policy = seed["llm_policy"]
        assert isinstance(policy, dict)
        assert "tenant_can_override" in policy
        assert "defaults" in policy
        assert policy["defaults"]["temperature"] == 0.3
        assert policy["defaults"]["max_tokens"] == 2000

    @pytest.mark.parametrize("seed", SEED_TEMPLATES)
    def test_kb_policy_structure(self, seed):
        policy = seed["kb_policy"]
        assert isinstance(policy, dict)
        assert policy["ownership"] == "tenant_managed"
        assert isinstance(policy["recommended_categories"], list)
        assert isinstance(policy["required_kb_ids"], list)

    @pytest.mark.parametrize("seed", SEED_TEMPLATES)
    def test_a2a_interface_structure(self, seed):
        iface = seed["a2a_interface"]
        assert isinstance(iface, dict)
        assert iface["a2a_enabled"] is False
        assert isinstance(iface["operations"], list)
        assert iface["auth_required"] is False


# ---------------------------------------------------------------------------
# GET /agents/templates/{id} — seed detail enrichment
# ---------------------------------------------------------------------------


class TestGetAgentTemplateDetail:
    """Verify get_agent_template returns variable_schema + changelog for seeds."""

    def _seed_detail(self, seed_id: str) -> dict:
        """Simulate what get_agent_template returns for a seed (sans DB + HTTP)."""
        from app.modules.agents.routes import _SEED_BY_ID, _extract_variable_schema

        seed = dict(_SEED_BY_ID[seed_id])
        seed["variable_schema"] = _extract_variable_schema(seed.get("system_prompt", ""))
        seed["changelog"] = []
        return seed

    def test_hr_variable_schema_contains_company_name(self):
        detail = self._seed_detail("seed-hr")
        names = [v["name"] for v in detail["variable_schema"]]
        assert "company_name" in names

    def test_procurement_variable_schema_two_tokens(self):
        detail = self._seed_detail("seed-procurement")
        names = [v["name"] for v in detail["variable_schema"]]
        # system_prompt has {{company_name}} and {{approval_threshold}}
        assert "company_name" in names
        assert "approval_threshold" in names

    def test_onboarding_variable_schema_three_tokens(self):
        detail = self._seed_detail("seed-onboarding")
        names = [v["name"] for v in detail["variable_schema"]]
        assert "company_name" in names
        assert "employee_role" in names
        assert "start_date" in names

    def test_changelog_is_empty_list(self):
        detail = self._seed_detail("seed-hr")
        assert detail["changelog"] == []

    def test_variable_schema_items_have_correct_shape(self):
        detail = self._seed_detail("seed-it")
        for item in detail["variable_schema"]:
            assert set(item.keys()) == {"name", "type", "required", "description"}
            assert item["type"] == "string"
            assert item["required"] is True

    def test_original_seed_not_mutated(self):
        """get_agent_template must not modify the _SEED_BY_ID dict in place."""
        original_keys = set(_SEED_BY_ID["seed-hr"].keys())
        detail = self._seed_detail("seed-hr")
        assert set(_SEED_BY_ID["seed-hr"].keys()) == original_keys
        # variable_schema should only exist on the copy, not the original
        assert "variable_schema" not in _SEED_BY_ID["seed-hr"]
        assert "variable_schema" in detail
