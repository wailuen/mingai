"""
OutputGuardrailChecker — runtime enforcement of agent guardrail configuration.

RULE A2A-01: Guardrail check (Stage 7b) MUST run AFTER the LLM completes and
BEFORE save_exchange(). No portion of a blocked response may be persisted to
conversation_messages or returned to the client.

RULE A2A-02: Guardrail configuration stored in agent_cards.capabilities is a
*declaration* only. Database storage != runtime enforcement. This module is the
enforcement point. Rules stored without this checker running are not enforced.
"""
import logging
import math
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canned responses
# ---------------------------------------------------------------------------

_CANNED_BLOCK_RESPONSE = (
    "I'm unable to provide that response due to content policy restrictions."
)
_CANNED_LOW_CONFIDENCE = (
    "I don't have enough information to answer that question reliably."
)
_TRUNCATION_SUFFIX = " [Response truncated by policy]"

# ---------------------------------------------------------------------------
# SSE event schema — used by orchestrator and frontend SSE parser
# ---------------------------------------------------------------------------

GUARDRAIL_TRIGGERED_EVENT = "guardrail_triggered"
GUARDRAIL_EVENT_DATA_SCHEMA = {
    "rule_id": "str — the rule that triggered",
    "action": "block|redact|flag",
    "user_message": "str — display to user",
    "agent_id": "str — the agent that triggered the rule",
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

_VALID_RULE_TYPES = frozenset(
    {"keyword_block", "max_length", "confidence_threshold", "citation_required", "semantic_check"}
)
_VALID_ON_VIOLATION = frozenset({"block", "redact", "warn"})


@dataclass
class FilterResult:
    passed: bool
    action: str  # "pass" | "block" | "redact" | "warn"
    rule_id: Optional[str] = None
    reason: Optional[str] = None
    filtered_text: Optional[str] = None
    violation_metadata: Optional[dict] = None


@dataclass
class GuardrailRule:
    rule_id: str
    rule_type: str  # "keyword_block" | "max_length" | "confidence_threshold" | "citation_required" | "semantic_check"
    patterns: List[str] = field(default_factory=list)
    on_violation: str = "block"  # "block" | "redact" | "warn"
    user_message: str = "This response was blocked by content policy."
    replacement: str = "[Content removed by policy]"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _has_active_guardrails(guardrails: dict) -> bool:
    """Return True only if there is at least one enforcement rule present.

    Criteria (any one being True is sufficient):
    - ``blocked_topics`` is a non-empty list
    - ``rules`` is a non-empty list
    - ``confidence_threshold`` is a float > 0
    - ``max_response_length`` is an int > 0
    """
    if not isinstance(guardrails, dict):
        return False

    blocked_topics = guardrails.get("blocked_topics")
    if isinstance(blocked_topics, list) and len(blocked_topics) > 0:
        return True

    rules = guardrails.get("rules")
    if isinstance(rules, list) and len(rules) > 0:
        return True

    confidence_threshold = guardrails.get("confidence_threshold")
    if isinstance(confidence_threshold, (int, float)) and math.isfinite(confidence_threshold) and confidence_threshold > 0:
        return True

    max_response_length = guardrails.get("max_response_length")
    if isinstance(max_response_length, int) and max_response_length > 0:
        return True

    return False


# ---------------------------------------------------------------------------
# Main checker
# ---------------------------------------------------------------------------


class OutputGuardrailChecker:
    """Runtime enforcement of agent guardrail configuration.

    RULE A2A-01: Guardrail check (Stage 7b) MUST run AFTER the LLM completes
    and BEFORE save_exchange(). No portion of a blocked response may be
    persisted to conversation_messages or returned to the client.

    RULE A2A-02: Guardrail configuration stored in agent_cards.capabilities is
    a *declaration* only. Database storage != runtime enforcement. This class
    is the enforcement point. Rules stored without this checker running are not
    enforced.
    """

    def __init__(
        self,
        agent_capabilities: dict,
        retrieval_confidence: float = 1.0,
    ) -> None:
        self._guardrails = agent_capabilities.get("guardrails", {})
        self._retrieval_confidence = retrieval_confidence
        self._rules = self._parse_rules()
        # TODO-SEMANTIC-CHECK: Bloomberg requirement — semantic similarity check
        # for "give investment advice" variants requires embedding-based matching.
        # Deferred to Phase C. Pattern: add rule_type="semantic_check" rule here,
        # call embedding API in check() for semantic_check rules only.

    # ------------------------------------------------------------------
    # Rule parsing
    # ------------------------------------------------------------------

    def _parse_rules(self) -> List[GuardrailRule]:
        """Parse rules from capabilities dict.

        Invalid rules (missing required fields, unrecognised types) are logged
        and skipped so that a single bad rule does not disable the entire
        guardrail set.
        """
        raw_rules = self._guardrails.get("rules", [])
        if not isinstance(raw_rules, list):
            logger.warning(
                "OutputGuardrailChecker: 'rules' key is not a list — skipping all rules"
            )
            return []

        parsed: List[GuardrailRule] = []
        for idx, raw in enumerate(raw_rules):
            if not isinstance(raw, dict):
                logger.warning(
                    "OutputGuardrailChecker: rule at index %d is not a dict — skipped",
                    idx,
                )
                continue

            rule_id = raw.get("rule_id")
            rule_type = raw.get("rule_type")

            if not rule_id or not isinstance(rule_id, str):
                logger.warning(
                    "OutputGuardrailChecker: rule at index %d has no valid rule_id — skipped",
                    idx,
                )
                continue

            if rule_type not in _VALID_RULE_TYPES:
                logger.warning(
                    "OutputGuardrailChecker: rule '%s' has unrecognised rule_type '%s' — skipped",
                    rule_id,
                    rule_type,
                )
                continue

            on_violation = raw.get("on_violation", "block")
            if on_violation not in _VALID_ON_VIOLATION:
                logger.warning(
                    "OutputGuardrailChecker: rule '%s' has invalid on_violation '%s' — defaulting to 'block'",
                    rule_id,
                    on_violation,
                )
                on_violation = "block"

            patterns = raw.get("patterns", [])
            if not isinstance(patterns, list):
                patterns = []

            parsed.append(
                GuardrailRule(
                    rule_id=rule_id,
                    rule_type=rule_type,
                    patterns=patterns,
                    on_violation=on_violation,
                    user_message=raw.get(
                        "user_message", "This response was blocked by content policy."
                    ),
                    replacement=raw.get("replacement", "[Content removed by policy]"),
                )
            )

        return parsed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check(self, response_text: str) -> FilterResult:
        """Run all guardrail checks against ``response_text``.

        Must be called with ``await``. Async from day one for forward
        compatibility with semantic_check rules that will call the embedding
        API.

        Fail-closed: any internal exception returns a block FilterResult with
        ``_CANNED_BLOCK_RESPONSE``. The unfiltered response is never returned
        on exception.

        Check order:
        1. confidence_threshold (if set and > 0)
        2. max_response_length (truncate at word boundary, action=redact)
        3. blocked_topics (exact phrase match, case-insensitive, action=block)
        4. keyword_block rules (regex pattern match)
        5. redact rules (replace matched text with rule.replacement)
        """
        try:
            return await self._check_internal(response_text)
        except Exception as exc:
            logger.error(
                "OutputGuardrailChecker.check() failed: %s",
                exc,
                exc_info=True,
            )
            return FilterResult(
                passed=False,
                action="block",
                rule_id="internal_error",
                reason=str(exc),
                filtered_text=_CANNED_BLOCK_RESPONSE,
                violation_metadata={"error": str(exc)},
            )

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    async def _check_internal(self, response_text: str) -> FilterResult:
        """Execute all checks in the defined order."""
        # 1. Confidence threshold
        threshold = self._guardrails.get("confidence_threshold", 0)
        retrieval_conf = self._retrieval_confidence
        if not isinstance(retrieval_conf, (int, float)) or not math.isfinite(retrieval_conf):
            retrieval_conf = 1.0  # treat invalid confidence as full confidence (fail-open)
        if isinstance(threshold, (int, float)) and math.isfinite(threshold) and threshold > 0:
            if retrieval_conf < threshold:
                return FilterResult(
                    passed=False,
                    action="block",
                    rule_id="confidence_threshold",
                    reason=(
                        f"Retrieval confidence {retrieval_conf:.3f} "
                        f"is below threshold {threshold:.3f}"
                    ),
                    filtered_text=_CANNED_LOW_CONFIDENCE,
                    violation_metadata={
                        "retrieval_confidence": retrieval_conf,
                        "threshold": threshold,
                    },
                )

        # 2. Max response length (truncate — response still delivered)
        max_len = self._guardrails.get("max_response_length", 0)
        if isinstance(max_len, int) and max_len > 0 and len(response_text) > max_len:
            truncated = response_text[:max_len].rsplit(" ", 1)[0] + _TRUNCATION_SUFFIX
            return FilterResult(
                passed=True,
                action="redact",
                rule_id="max_response_length",
                reason=f"Response length {len(response_text)} exceeds limit {max_len}",
                filtered_text=truncated,
                violation_metadata={
                    "original_length": len(response_text),
                    "max_length": max_len,
                },
            )

        # 3. Blocked topics (case-insensitive substring match)
        blocked_topics = self._guardrails.get("blocked_topics", [])
        if isinstance(blocked_topics, list):
            lower_response = response_text.lower()
            for topic in blocked_topics:
                if not isinstance(topic, str):
                    continue
                if topic.lower() in lower_response:
                    return FilterResult(
                        passed=False,
                        action="block",
                        rule_id="blocked_topics",
                        reason=f"Response contains blocked topic: '{topic}'",
                        filtered_text=_CANNED_BLOCK_RESPONSE,
                        violation_metadata={"blocked_topic": topic},
                    )

        # 4 & 5. Keyword_block and redact rules
        working_text = response_text
        warn_violations: List[dict] = []

        for rule in self._rules:
            if rule.rule_type != "keyword_block":
                # Other rule types (max_length, confidence_threshold, citation_required,
                # semantic_check) are handled elsewhere or deferred (semantic_check).
                continue

            for pattern in rule.patterns:
                try:
                    match = re.search(pattern, working_text, re.IGNORECASE)
                except re.error:
                    logger.warning(
                        "OutputGuardrailChecker: invalid regex pattern '%s' in rule '%s' — skipped",
                        pattern,
                        rule.rule_id,
                    )
                    continue

                if match is None:
                    continue

                if rule.on_violation == "block":
                    return FilterResult(
                        passed=False,
                        action="block",
                        rule_id=rule.rule_id,
                        reason=(
                            f"Response matched blocked pattern '{pattern}' "
                            f"in rule '{rule.rule_id}'"
                        ),
                        filtered_text=_CANNED_BLOCK_RESPONSE,
                        violation_metadata={
                            "pattern": pattern,
                            "matched_text": match.group(0),
                        },
                    )

                if rule.on_violation == "redact":
                    # Replace ALL occurrences (not just the first match)
                    try:
                        working_text = re.sub(
                            pattern,
                            rule.replacement,
                            working_text,
                            flags=re.IGNORECASE,
                        )
                    except re.error:
                        pass
                    # Continue processing remaining rules against the already-redacted text

                elif rule.on_violation == "warn":
                    warn_violations.append(
                        {
                            "rule_id": rule.rule_id,
                            "pattern": pattern,
                            "matched_text": match.group(0),
                        }
                    )

        # If any redactions happened, working_text differs from response_text
        if working_text != response_text:
            return FilterResult(
                passed=True,
                action="redact",
                rule_id=None,
                reason="One or more redact rules applied",
                filtered_text=working_text,
                violation_metadata=None,
            )

        if warn_violations:
            return FilterResult(
                passed=True,
                action="warn",
                rule_id=warn_violations[0]["rule_id"],
                reason="One or more warn rules triggered",
                filtered_text=working_text,
                violation_metadata={"violations": warn_violations},
            )

        return FilterResult(passed=True, action="pass", filtered_text=response_text)
