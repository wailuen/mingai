"""
Unit tests for OutputGuardrailChecker (ATA-018).

Tier 1: Fast, isolated, no external dependencies.
Coverage:
  1.  _has_active_guardrails — all cases (empty, zero values, active values)
  2.  check() — confidence threshold blocks when below
  3.  check() — max_response_length truncates at word boundary
  4.  check() — blocked_topics blocks case-insensitive
  5.  check() — keyword_block rule blocks on pattern match
  6.  check() — redact rule replaces matched text
  7.  check() — warn rule passes but with action=warn
  8.  check() — no guardrails → pass
  9.  check() — internal exception → fail-closed block (not original text)
  10. _parse_rules() — invalid rule type logged and skipped
"""
import logging
import pytest

from app.modules.chat.guardrails import (
    OutputGuardrailChecker,
    _has_active_guardrails,
    _CANNED_BLOCK_RESPONSE,
    _CANNED_LOW_CONFIDENCE,
    _TRUNCATION_SUFFIX,
)

# ---------------------------------------------------------------------------
# 1. _has_active_guardrails
# ---------------------------------------------------------------------------


class TestHasActiveGuardrails:
    def test_empty_dict_returns_false(self):
        assert _has_active_guardrails({}) is False

    def test_none_returns_false(self):
        assert _has_active_guardrails(None) is False  # type: ignore[arg-type]

    def test_non_dict_returns_false(self):
        assert _has_active_guardrails("not a dict") is False  # type: ignore[arg-type]

    def test_max_response_length_zero_returns_false(self):
        assert _has_active_guardrails({"max_response_length": 0}) is False

    def test_max_response_length_negative_returns_false(self):
        assert _has_active_guardrails({"max_response_length": -1}) is False

    def test_blocked_topics_empty_list_returns_false(self):
        assert _has_active_guardrails({"blocked_topics": []}) is False

    def test_rules_empty_list_returns_false(self):
        assert _has_active_guardrails({"rules": []}) is False

    def test_confidence_threshold_zero_returns_false(self):
        assert _has_active_guardrails({"confidence_threshold": 0}) is False

    def test_confidence_threshold_zero_float_returns_false(self):
        assert _has_active_guardrails({"confidence_threshold": 0.0}) is False

    def test_blocked_topics_non_empty_returns_true(self):
        assert _has_active_guardrails({"blocked_topics": ["investment advice"]}) is True

    def test_max_response_length_positive_returns_true(self):
        assert _has_active_guardrails({"max_response_length": 500}) is True

    def test_confidence_threshold_positive_returns_true(self):
        assert _has_active_guardrails({"confidence_threshold": 0.9}) is True

    def test_rules_non_empty_returns_true(self):
        assert _has_active_guardrails({"rules": [{"rule_id": "r1"}]}) is True

    def test_multiple_inactive_keys_all_false_returns_false(self):
        assert _has_active_guardrails(
            {
                "blocked_topics": [],
                "rules": [],
                "confidence_threshold": 0,
                "max_response_length": 0,
            }
        ) is False

    def test_one_active_among_several_inactive_returns_true(self):
        assert _has_active_guardrails(
            {
                "blocked_topics": [],
                "rules": [],
                "confidence_threshold": 0,
                "max_response_length": 500,
            }
        ) is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _checker(guardrails: dict = None, retrieval_confidence: float = 1.0) -> OutputGuardrailChecker:
    caps = {"guardrails": guardrails or {}}
    return OutputGuardrailChecker(caps, retrieval_confidence=retrieval_confidence)


# ---------------------------------------------------------------------------
# 2. check() — confidence threshold
# ---------------------------------------------------------------------------


class TestConfidenceThreshold:
    @pytest.mark.asyncio
    async def test_blocks_when_below_threshold(self):
        checker = _checker({"confidence_threshold": 0.8}, retrieval_confidence=0.5)
        result = await checker.check("Here is my answer about investments.")
        assert result.passed is False
        assert result.action == "block"
        assert result.rule_id == "confidence_threshold"
        assert result.filtered_text == _CANNED_LOW_CONFIDENCE

    @pytest.mark.asyncio
    async def test_passes_when_at_threshold(self):
        checker = _checker({"confidence_threshold": 0.8}, retrieval_confidence=0.8)
        result = await checker.check("Here is my answer.")
        assert result.passed is True
        assert result.action == "pass"

    @pytest.mark.asyncio
    async def test_passes_when_above_threshold(self):
        checker = _checker({"confidence_threshold": 0.8}, retrieval_confidence=0.95)
        result = await checker.check("Here is my answer.")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_threshold_zero_never_blocks(self):
        checker = _checker({"confidence_threshold": 0}, retrieval_confidence=0.0)
        result = await checker.check("Any text.")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_violation_metadata_contains_scores(self):
        checker = _checker({"confidence_threshold": 0.9}, retrieval_confidence=0.3)
        result = await checker.check("Some response.")
        assert result.violation_metadata["retrieval_confidence"] == pytest.approx(0.3)
        assert result.violation_metadata["threshold"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# 3. check() — max_response_length
# ---------------------------------------------------------------------------


class TestMaxResponseLength:
    @pytest.mark.asyncio
    async def test_truncates_long_response(self):
        text = "one two three four five six seven eight nine ten"
        checker = _checker({"max_response_length": 20})
        result = await checker.check(text)
        assert result.action == "redact"
        assert result.passed is True  # truncation is not a block
        assert result.filtered_text.endswith(_TRUNCATION_SUFFIX)

    @pytest.mark.asyncio
    async def test_truncates_at_word_boundary(self):
        # "one two three" = 13 chars; limit 11 should not cut "three" mid-word
        text = "one two three four"
        checker = _checker({"max_response_length": 11})
        result = await checker.check(text)
        # Truncation point: text[:11] = "one two thr"; rsplit(' ', 1)[0] = "one two"
        assert "thr" not in result.filtered_text.replace(_TRUNCATION_SUFFIX, "")

    @pytest.mark.asyncio
    async def test_passes_when_under_limit(self):
        text = "short response"
        checker = _checker({"max_response_length": 500})
        result = await checker.check(text)
        assert result.passed is True
        assert result.action == "pass"

    @pytest.mark.asyncio
    async def test_zero_limit_does_not_truncate(self):
        text = "x" * 10_000
        checker = _checker({"max_response_length": 0})
        result = await checker.check(text)
        assert result.action == "pass"

    @pytest.mark.asyncio
    async def test_violation_metadata_contains_lengths(self):
        text = "hello world this is a long response"
        checker = _checker({"max_response_length": 10})
        result = await checker.check(text)
        assert result.violation_metadata["original_length"] == len(text)
        assert result.violation_metadata["max_length"] == 10


# ---------------------------------------------------------------------------
# 4. check() — blocked_topics
# ---------------------------------------------------------------------------


class TestBlockedTopics:
    @pytest.mark.asyncio
    async def test_blocks_matching_topic(self):
        checker = _checker({"blocked_topics": ["investment advice"]})
        result = await checker.check("I can give you some investment advice here.")
        assert result.passed is False
        assert result.action == "block"
        assert result.rule_id == "blocked_topics"
        assert result.filtered_text == _CANNED_BLOCK_RESPONSE

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self):
        checker = _checker({"blocked_topics": ["Investment Advice"]})
        result = await checker.check("Here is investment advice for you.")
        assert result.passed is False
        assert result.action == "block"

    @pytest.mark.asyncio
    async def test_uppercase_in_response_still_blocked(self):
        checker = _checker({"blocked_topics": ["investment advice"]})
        result = await checker.check("Here is INVESTMENT ADVICE for you.")
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_passes_when_no_match(self):
        checker = _checker({"blocked_topics": ["investment advice"]})
        result = await checker.check("The weather today is sunny.")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_first_matching_topic_triggers(self):
        checker = _checker({"blocked_topics": ["investment advice", "medical diagnosis"]})
        result = await checker.check("Here is medical diagnosis information.")
        assert result.passed is False
        assert result.violation_metadata["blocked_topic"] == "medical diagnosis"

    @pytest.mark.asyncio
    async def test_empty_blocked_topics_does_not_block(self):
        checker = _checker({"blocked_topics": []})
        result = await checker.check("Anything at all.")
        assert result.passed is True


# ---------------------------------------------------------------------------
# 5. check() — keyword_block rule blocks on pattern match
# ---------------------------------------------------------------------------


class TestKeywordBlockRule:
    @pytest.mark.asyncio
    async def test_blocks_on_pattern_match(self):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "no-ssn",
                        "rule_type": "keyword_block",
                        "patterns": [r"\d{3}-\d{2}-\d{4}"],
                        "on_violation": "block",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        result = await checker.check("Your SSN is 123-45-6789.")
        assert result.passed is False
        assert result.action == "block"
        assert result.rule_id == "no-ssn"

    @pytest.mark.asyncio
    async def test_passes_when_no_pattern_match(self):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "no-ssn",
                        "rule_type": "keyword_block",
                        "patterns": [r"\d{3}-\d{2}-\d{4}"],
                        "on_violation": "block",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        result = await checker.check("No sensitive data here.")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_case_insensitive_pattern(self):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "no-badword",
                        "rule_type": "keyword_block",
                        "patterns": ["badword"],
                        "on_violation": "block",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        result = await checker.check("This response contains BADWORD in it.")
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_violation_metadata_contains_matched_text(self):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "no-ssn",
                        "rule_type": "keyword_block",
                        "patterns": [r"\d{3}-\d{2}-\d{4}"],
                        "on_violation": "block",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        result = await checker.check("SSN: 123-45-6789 is present.")
        assert result.violation_metadata["matched_text"] == "123-45-6789"


# ---------------------------------------------------------------------------
# 6. check() — redact rule replaces matched text
# ---------------------------------------------------------------------------


class TestRedactRule:
    @pytest.mark.asyncio
    async def test_redact_replaces_matched_text(self):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "redact-ssn",
                        "rule_type": "keyword_block",
                        "patterns": [r"\d{3}-\d{2}-\d{4}"],
                        "on_violation": "redact",
                        "replacement": "[SSN REDACTED]",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        result = await checker.check("SSN is 123-45-6789 for this person.")
        assert result.passed is True
        assert result.action == "redact"
        assert "[SSN REDACTED]" in result.filtered_text
        assert "123-45-6789" not in result.filtered_text

    @pytest.mark.asyncio
    async def test_redact_multiple_occurrences(self):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "redact-ssn",
                        "rule_type": "keyword_block",
                        "patterns": [r"\d{3}-\d{2}-\d{4}"],
                        "on_violation": "redact",
                        "replacement": "[REDACTED]",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        result = await checker.check("SSN1: 111-22-3333 and SSN2: 444-55-6666.")
        assert result.filtered_text.count("[REDACTED]") == 2
        assert "111-22-3333" not in result.filtered_text
        assert "444-55-6666" not in result.filtered_text

    @pytest.mark.asyncio
    async def test_redact_uses_default_replacement_when_not_specified(self):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "redact-phone",
                        "rule_type": "keyword_block",
                        "patterns": [r"\d{3}-\d{4}"],
                        "on_violation": "redact",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        result = await checker.check("Call 555-1234 for info.")
        assert result.passed is True
        assert "[Content removed by policy]" in result.filtered_text


# ---------------------------------------------------------------------------
# 7. check() — warn rule passes but with action=warn
# ---------------------------------------------------------------------------


class TestWarnRule:
    @pytest.mark.asyncio
    async def test_warn_passes_with_action_warn(self):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "warn-legal",
                        "rule_type": "keyword_block",
                        "patterns": ["legal advice"],
                        "on_violation": "warn",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        result = await checker.check("I can give you legal advice here.")
        assert result.passed is True
        assert result.action == "warn"
        assert result.rule_id == "warn-legal"

    @pytest.mark.asyncio
    async def test_warn_returns_original_text(self):
        original = "I can give you legal advice here."
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "warn-legal",
                        "rule_type": "keyword_block",
                        "patterns": ["legal advice"],
                        "on_violation": "warn",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        result = await checker.check(original)
        assert result.filtered_text == original

    @pytest.mark.asyncio
    async def test_warn_violation_metadata_contains_violations(self):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "warn-legal",
                        "rule_type": "keyword_block",
                        "patterns": ["legal advice"],
                        "on_violation": "warn",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        result = await checker.check("You need legal advice.")
        assert "violations" in result.violation_metadata
        assert len(result.violation_metadata["violations"]) > 0

    @pytest.mark.asyncio
    async def test_no_match_still_passes(self):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "warn-legal",
                        "rule_type": "keyword_block",
                        "patterns": ["legal advice"],
                        "on_violation": "warn",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        result = await checker.check("The weather is fine.")
        assert result.passed is True
        assert result.action == "pass"


# ---------------------------------------------------------------------------
# 8. check() — no guardrails → pass
# ---------------------------------------------------------------------------


class TestNoGuardrails:
    @pytest.mark.asyncio
    async def test_empty_capabilities_passes(self):
        checker = OutputGuardrailChecker({})
        result = await checker.check("Any response text at all.")
        assert result.passed is True
        assert result.action == "pass"

    @pytest.mark.asyncio
    async def test_empty_guardrails_dict_passes(self):
        checker = _checker({})
        result = await checker.check("Any response text at all.")
        assert result.passed is True
        assert result.action == "pass"

    @pytest.mark.asyncio
    async def test_filtered_text_equals_input_when_passing(self):
        text = "Clean response with no issues."
        checker = _checker({})
        result = await checker.check(text)
        assert result.filtered_text == text


# ---------------------------------------------------------------------------
# 9. check() — internal exception → fail-closed block
# ---------------------------------------------------------------------------


class TestFailClosed:
    @pytest.mark.asyncio
    async def test_exception_returns_block_not_original_text(self):
        """Simulate an internal error by making _check_internal raise."""
        checker = _checker({"confidence_threshold": 0.5}, retrieval_confidence=0.8)

        original_check = checker._check_internal

        async def _raise(*args, **kwargs):
            raise RuntimeError("Simulated internal failure")

        checker._check_internal = _raise

        result = await checker.check("Some response text.")
        assert result.passed is False
        assert result.action == "block"
        assert result.rule_id == "internal_error"
        # Critical: the ORIGINAL text must NOT appear in filtered_text
        assert "Some response text." not in (result.filtered_text or "")
        assert result.filtered_text == _CANNED_BLOCK_RESPONSE

    @pytest.mark.asyncio
    async def test_exception_violation_metadata_contains_error(self):
        checker = _checker({})

        async def _raise(*args, **kwargs):
            raise ValueError("Deliberate test error")

        checker._check_internal = _raise

        result = await checker.check("Text.")
        assert "error" in result.violation_metadata
        assert "Deliberate test error" in result.violation_metadata["error"]


# ---------------------------------------------------------------------------
# 10. _parse_rules() — invalid rule type logged and skipped
# ---------------------------------------------------------------------------


class TestParseRules:
    def test_invalid_rule_type_skipped(self, caplog):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "bad-rule",
                        "rule_type": "nonexistent_type",
                        "patterns": ["anything"],
                    }
                ]
            }
        }
        with caplog.at_level(logging.WARNING):
            checker = OutputGuardrailChecker(capabilities)
        assert len(checker._rules) == 0
        assert "nonexistent_type" in caplog.text

    def test_missing_rule_id_skipped(self, caplog):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_type": "keyword_block",
                        "patterns": ["anything"],
                    }
                ]
            }
        }
        with caplog.at_level(logging.WARNING):
            checker = OutputGuardrailChecker(capabilities)
        assert len(checker._rules) == 0

    def test_non_dict_rule_skipped(self, caplog):
        capabilities = {
            "guardrails": {
                "rules": ["not a dict"]
            }
        }
        with caplog.at_level(logging.WARNING):
            checker = OutputGuardrailChecker(capabilities)
        assert len(checker._rules) == 0

    def test_valid_rule_parsed(self):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "r1",
                        "rule_type": "keyword_block",
                        "patterns": ["badword"],
                        "on_violation": "block",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        assert len(checker._rules) == 1
        assert checker._rules[0].rule_id == "r1"
        assert checker._rules[0].rule_type == "keyword_block"

    def test_invalid_on_violation_defaults_to_block(self, caplog):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "r2",
                        "rule_type": "keyword_block",
                        "patterns": ["test"],
                        "on_violation": "explode",
                    }
                ]
            }
        }
        with caplog.at_level(logging.WARNING):
            checker = OutputGuardrailChecker(capabilities)
        assert len(checker._rules) == 1
        assert checker._rules[0].on_violation == "block"
        assert "explode" in caplog.text

    def test_valid_and_invalid_rules_mixed(self):
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "valid-rule",
                        "rule_type": "keyword_block",
                        "patterns": ["badword"],
                    },
                    {
                        "rule_id": "invalid-rule",
                        "rule_type": "unknown_type",
                        "patterns": ["anything"],
                    },
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        assert len(checker._rules) == 1
        assert checker._rules[0].rule_id == "valid-rule"

    def test_rules_not_a_list_returns_empty(self, caplog):
        capabilities = {
            "guardrails": {
                "rules": "not a list"
            }
        }
        with caplog.at_level(logging.WARNING):
            checker = OutputGuardrailChecker(capabilities)
        assert checker._rules == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_check_order_confidence_before_blocked_topics(self):
        """confidence_threshold (step 1) fires before blocked_topics (step 3)."""
        checker = _checker(
            {
                "confidence_threshold": 0.9,
                "blocked_topics": ["investment advice"],
            },
            retrieval_confidence=0.5,
        )
        result = await checker.check("Here is investment advice.")
        assert result.rule_id == "confidence_threshold"

    @pytest.mark.asyncio
    async def test_check_order_max_length_before_blocked_topics(self):
        """max_response_length (step 2) fires before blocked_topics (step 3)."""
        long_clean_text = "hello " * 200  # well under any blocked topic
        checker = _checker(
            {
                "max_response_length": 10,
                "blocked_topics": ["never appears"],
            }
        )
        result = await checker.check(long_clean_text)
        assert result.rule_id == "max_response_length"
        assert result.action == "redact"

    @pytest.mark.asyncio
    async def test_empty_response_text_passes_clean(self):
        checker = _checker({})
        result = await checker.check("")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_invalid_regex_in_rule_skipped_gracefully(self):
        """A malformed regex should not crash check(); that rule is skipped."""
        capabilities = {
            "guardrails": {
                "rules": [
                    {
                        "rule_id": "bad-regex",
                        "rule_type": "keyword_block",
                        "patterns": [r"[invalid("],
                        "on_violation": "block",
                    }
                ]
            }
        }
        checker = OutputGuardrailChecker(capabilities)
        result = await checker.check("Some text that could trigger a bad rule.")
        # Bad regex is skipped; should not raise and should pass cleanly
        assert result.passed is True
