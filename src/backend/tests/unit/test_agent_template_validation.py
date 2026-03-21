"""
ATA-022 unit tests: GuardrailsSchema validation.

Tests the structured guardrail configuration schema directly at the Pydantic layer.
No HTTP calls — Tier 1 unit tests.
"""
import pytest
from pydantic import ValidationError

from app.modules.platform.routes import (
    GuardrailsSchema,
    _VALID_GUARDRAIL_ACTIONS,
    _VALID_GUARDRAIL_RULE_TYPES,
)


# ---------------------------------------------------------------------------
# Rule type validation
# ---------------------------------------------------------------------------


def test_guardrail_validation_invalid_rule_type_raises():
    """Invalid rule type must be rejected with ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        GuardrailsSchema(
            rules=[{"type": "not_a_real_type", "action": "block"}]
        )
    assert "Invalid rule type" in str(exc_info.value)


def test_guardrail_validation_valid_keyword_block_rule():
    """keyword_block rule with valid action passes validation."""
    schema = GuardrailsSchema(
        rules=[{"type": "keyword_block", "action": "block", "patterns": ["spam"]}]
    )
    assert schema.rules[0]["type"] == "keyword_block"


def test_guardrail_validation_all_valid_rule_types():
    """All valid rule types are accepted."""
    for rule_type in _VALID_GUARDRAIL_RULE_TYPES:
        schema = GuardrailsSchema(rules=[{"type": rule_type}])
        assert schema.rules[0]["type"] == rule_type


# ---------------------------------------------------------------------------
# Action validation
# ---------------------------------------------------------------------------


def test_guardrail_validation_invalid_action_raises():
    """Invalid action value must be rejected with ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        GuardrailsSchema(
            rules=[{"type": "keyword_block", "action": "explode"}]
        )
    assert "Invalid action" in str(exc_info.value)


def test_guardrail_validation_all_valid_actions():
    """All valid action values are accepted."""
    for action in _VALID_GUARDRAIL_ACTIONS:
        schema = GuardrailsSchema(
            rules=[{"type": "keyword_block", "action": action}]
        )
        assert schema.rules[0]["action"] == action


def test_guardrail_validation_missing_action_allowed():
    """Action is optional — a rule without action field is accepted."""
    schema = GuardrailsSchema(rules=[{"type": "citation_required"}])
    assert schema.rules[0].get("action") is None


# ---------------------------------------------------------------------------
# Regex pattern validation
# ---------------------------------------------------------------------------


def test_guardrail_validation_invalid_regex_raises():
    """Invalid regex pattern '[unclosed' must be rejected with ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        GuardrailsSchema(
            rules=[{"type": "keyword_block", "patterns": ["[unclosed"]}]
        )
    assert "Invalid regex pattern" in str(exc_info.value)


def test_guardrail_validation_valid_regex_passes():
    """Valid regex pattern is accepted."""
    schema = GuardrailsSchema(
        rules=[{"type": "keyword_block", "patterns": [r"\bspam\b", r"(foo|bar)"]}]
    )
    assert len(schema.rules[0]["patterns"]) == 2


def test_guardrail_validation_empty_patterns_list_passes():
    """Empty patterns list is valid."""
    schema = GuardrailsSchema(
        rules=[{"type": "keyword_block", "patterns": []}]
    )
    assert schema.rules[0]["patterns"] == []


# ---------------------------------------------------------------------------
# confidence_threshold range
# ---------------------------------------------------------------------------


def test_guardrail_validation_confidence_threshold_above_one_raises():
    """confidence_threshold > 1.0 must be rejected."""
    with pytest.raises(ValidationError):
        GuardrailsSchema(confidence_threshold=1.5)


def test_guardrail_validation_confidence_threshold_negative_raises():
    """confidence_threshold < 0.0 must be rejected."""
    with pytest.raises(ValidationError):
        GuardrailsSchema(confidence_threshold=-0.1)


def test_guardrail_validation_confidence_threshold_boundary_values():
    """Boundary values 0.0 and 1.0 are valid."""
    assert GuardrailsSchema(confidence_threshold=0.0).confidence_threshold == 0.0
    assert GuardrailsSchema(confidence_threshold=1.0).confidence_threshold == 1.0


# ---------------------------------------------------------------------------
# blocked_topics length limit
# ---------------------------------------------------------------------------


def test_guardrail_validation_blocked_topics_over_limit_raises():
    """blocked_topics list of 51 items must be rejected (max 50)."""
    with pytest.raises(ValidationError):
        GuardrailsSchema(blocked_topics=["topic"] * 51)


def test_guardrail_validation_blocked_topics_at_limit_passes():
    """blocked_topics list of exactly 50 items is valid."""
    schema = GuardrailsSchema(blocked_topics=["topic"] * 50)
    assert len(schema.blocked_topics) == 50


def test_guardrail_validation_blocked_topics_none_passes():
    """None blocked_topics is valid (optional field)."""
    schema = GuardrailsSchema(blocked_topics=None)
    assert schema.blocked_topics is None


# ---------------------------------------------------------------------------
# max_response_length range
# ---------------------------------------------------------------------------


def test_guardrail_validation_max_response_length_negative_raises():
    """Negative max_response_length must be rejected."""
    with pytest.raises(ValidationError):
        GuardrailsSchema(max_response_length=-1)


def test_guardrail_validation_max_response_length_exceeds_max_raises():
    """max_response_length above 10000 must be rejected."""
    with pytest.raises(ValidationError):
        GuardrailsSchema(max_response_length=10001)


def test_guardrail_validation_max_response_length_boundary_values():
    """Boundary values 0 and 10000 are valid."""
    assert GuardrailsSchema(max_response_length=0).max_response_length == 0
    assert GuardrailsSchema(max_response_length=10000).max_response_length == 10000


def test_guardrail_validation_max_response_length_none_passes():
    """None max_response_length is valid (optional field)."""
    schema = GuardrailsSchema(max_response_length=None)
    assert schema.max_response_length is None


# ---------------------------------------------------------------------------
# Empty / null rules
# ---------------------------------------------------------------------------


def test_guardrail_validation_no_rules_passes():
    """GuardrailsSchema with no rules is valid."""
    schema = GuardrailsSchema()
    assert schema.rules is None
    assert schema.blocked_topics is None
    assert schema.confidence_threshold is None
    assert schema.max_response_length is None


def test_guardrail_validation_empty_rules_list_passes():
    """Empty rules list is valid."""
    schema = GuardrailsSchema(rules=[])
    assert schema.rules == []
