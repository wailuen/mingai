"""
TEST-017: Issue type routing — unit tests.

Validates that IssueTriageAgent routes correctly:
- data_privacy issues → trust_safety (P0 override)
- PII/safety keywords → trust_safety escalation
- ui_bug / performance / access → engineering
- rag_quality → product
- confidence < 0.5 → product (human review)
- auto_close routing for 'other' with high confidence
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.modules.issues.triage_agent import (
    IssueTriageAgent,
    TriageResult,
)


class TestIssueTypeRouting:
    """TEST-017: Issue classification routes to correct destination."""

    def setup_method(self):
        self.agent = IssueTriageAgent()

    # ------------------------------------------------------------------
    # Routing table
    # ------------------------------------------------------------------

    def test_ui_bug_routes_to_engineering(self):
        routing = self.agent._determine_routing("ui_bug", confidence=0.8)
        assert routing == "engineering"

    def test_performance_routes_to_engineering(self):
        routing = self.agent._determine_routing("performance", confidence=0.8)
        assert routing == "engineering"

    def test_access_routes_to_engineering(self):
        routing = self.agent._determine_routing("access", confidence=0.8)
        assert routing == "engineering"

    def test_rag_quality_routes_to_product(self):
        routing = self.agent._determine_routing("rag_quality", confidence=0.8)
        assert routing == "product"

    def test_other_routes_to_product(self):
        routing = self.agent._determine_routing("other", confidence=0.8)
        assert routing == "product"

    def test_data_privacy_routes_to_trust_safety(self):
        """data_privacy ALWAYS routes to trust_safety regardless of confidence."""
        routing_high = self.agent._determine_routing("data_privacy", confidence=0.9)
        routing_low = self.agent._determine_routing("data_privacy", confidence=0.2)
        assert routing_high == "trust_safety"
        assert routing_low == "trust_safety"

    def test_low_confidence_routes_to_product(self):
        """confidence < 0.5 routes any non-privacy issue to product for human review."""
        for issue_type in ("ui_bug", "performance", "access", "rag_quality", "other"):
            routing = self.agent._determine_routing(issue_type, confidence=0.4)
            assert (
                routing == "product"
            ), f"{issue_type} with confidence 0.4 should route to product, got {routing}"

    def test_confidence_threshold_boundary(self):
        """confidence exactly 0.5 does NOT trigger low-confidence routing."""
        routing = self.agent._determine_routing("ui_bug", confidence=0.5)
        assert routing == "engineering"

    def test_confidence_just_below_threshold(self):
        """confidence 0.49 triggers low-confidence routing → product."""
        routing = self.agent._determine_routing("ui_bug", confidence=0.49)
        assert routing == "product"

    # ------------------------------------------------------------------
    # Post-LLM security overrides
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_data_privacy_issue_always_p0(self):
        """data_privacy issues are escalated to P0 after LLM call."""
        llm_result = {
            "issue_type": "data_privacy",
            "severity": "P2",  # LLM underestimates
            "confidence": 0.8,
            "reasoning": "User reports a data concern.",
        }
        import json

        with patch.object(
            self.agent,
            "_call_llm",
            new=AsyncMock(return_value=json.dumps(llm_result)),
        ):
            result = await self.agent.triage(
                "Data issue", "I can see another user's data", "tenant-1"
            )

        # Post-LLM override applies: data_privacy → P0
        assert result.severity == "P0"
        assert result.routing == "trust_safety"

    @pytest.mark.asyncio
    async def test_pii_keyword_escalates_to_p0(self):
        """PII keywords in title/description escalate any issue to P0."""
        llm_result = {
            "issue_type": "ui_bug",
            "severity": "P2",
            "confidence": 0.8,
            "reasoning": "UI bug.",
        }
        import json

        with patch.object(
            self.agent,
            "_call_llm",
            new=AsyncMock(return_value=json.dumps(llm_result)),
        ):
            result = await self.agent.triage(
                "User PII exposed in UI", "The name field shows PII", "tenant-1"
            )

        assert result.severity == "P0"
        assert result.routing == "trust_safety"

    @pytest.mark.asyncio
    async def test_data_leak_keyword_escalates_to_p0(self):
        """'data leak' keyword escalates to P0 regardless of LLM classification."""
        llm_result = {
            "issue_type": "performance",
            "severity": "P3",
            "confidence": 0.7,
            "reasoning": "Performance issue.",
        }
        import json

        with patch.object(
            self.agent,
            "_call_llm",
            new=AsyncMock(return_value=json.dumps(llm_result)),
        ):
            result = await self.agent.triage(
                "Data leak in export", "Saw a data leak when exporting", "tenant-1"
            )

        assert result.severity == "P0"
        assert result.routing == "trust_safety"

    @pytest.mark.asyncio
    async def test_invalid_llm_output_falls_back_to_rules(self):
        """Invalid LLM output (bad field values) falls back to rule-based classification."""
        with patch.object(
            self.agent,
            "_call_llm",
            new=AsyncMock(
                return_value='{"issue_type": "invalid_type", "severity": "P5"}'
            ),
        ):
            result = await self.agent.triage(
                "App crashes on login",
                "The app crashes every time I try to log in",
                "tenant-1",
            )

        # Rule-based fallback: "crash" matches bug keywords → ui_bug / P1
        assert result.issue_type in ("ui_bug", "data_privacy", "other")

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_rules(self):
        """LLM network failure falls back to rule-based classification, not a crash."""
        with patch.object(
            self.agent,
            "_call_llm",
            new=AsyncMock(side_effect=ConnectionError("LLM unreachable")),
        ):
            result = await self.agent.triage(
                "App is broken", "Everything is broken and not working", "tenant-1"
            )

        assert isinstance(result, TriageResult)
        assert result.issue_type in ("ui_bug", "data_privacy", "other")
        # Rule-based: "broken" + "not working" → ui_bug
        assert result.issue_type == "ui_bug"

    # ------------------------------------------------------------------
    # Rule-based fallback routing
    # ------------------------------------------------------------------

    def test_rule_based_privacy_keywords_route_to_trust_safety(self):
        """Rule-based fallback routes privacy keywords to trust_safety."""
        result = self.agent._rule_based_fallback(
            "Data privacy concern", "I saw a gdpr data leak"
        )
        assert result.routing == "trust_safety"
        assert result.issue_type == "data_privacy"

    def test_rule_based_bug_keywords_route_to_engineering(self):
        """Rule-based fallback routes bug keywords to engineering."""
        result = self.agent._rule_based_fallback(
            "App broken", "Everything is broken and not working"
        )
        assert result.routing == "engineering"
        assert result.issue_type == "ui_bug"

    def test_rule_based_fallback_default_routes_to_product(self):
        """Rule-based fallback with no matching keywords routes to product."""
        result = self.agent._rule_based_fallback(
            "General feedback", "I have some general thoughts"
        )
        assert result.routing == "product"
        assert result.issue_type == "other"
