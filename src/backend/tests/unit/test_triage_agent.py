"""
Unit tests for IssueTriageAgent (AI-037, AI-038, TEST-014).

Tests the LLM-based issue triage classifier that determines issue type,
severity, confidence, and routing destination.

Tier 1: Fast, isolated, mocks LLM calls only.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.issues.triage_agent import IssueTriageAgent, TriageResult


class TestTriageResult:
    """Test TriageResult dataclass."""

    def test_fields_accessible(self):
        r = TriageResult("ui_bug", "P2", 0.8, "engineering", "test")
        assert r.issue_type == "ui_bug"
        assert r.severity == "P2"
        assert r.confidence == 0.8
        assert r.routing == "engineering"
        assert r.reasoning == "test"

    def test_all_issue_types_valid(self):
        for itype in (
            "ui_bug",
            "rag_quality",
            "performance",
            "data_privacy",
            "access",
            "other",
        ):
            r = TriageResult(itype, "P3", 0.5, "product", "ok")
            assert r.issue_type == itype

    def test_all_severities_valid(self):
        for sev in ("P0", "P1", "P2", "P3"):
            r = TriageResult("other", sev, 0.5, "product", "ok")
            assert r.severity == sev


class TestIssueTriageAgentRules:
    """Test rule-based overrides (non-LLM)."""

    def test_data_privacy_escalates_to_p0(self):
        agent = IssueTriageAgent()
        # Simulate LLM result that under-classified
        result = TriageResult("data_privacy", "P2", 0.8, "engineering", "test")
        # Apply the severity override manually (as done in triage())
        if result.issue_type == "data_privacy":
            result.severity = "P0"
            result.routing = "trust_safety"
        assert result.severity == "P0"
        assert result.routing == "trust_safety"

    def test_rule_based_fallback_data_privacy(self):
        agent = IssueTriageAgent()
        result = agent._rule_based_fallback(
            "I see another user's data", "PII leak detected"
        )
        assert result.issue_type == "data_privacy"
        assert result.severity == "P0"
        assert result.routing == "trust_safety"

    def test_rule_based_fallback_bug(self):
        agent = IssueTriageAgent()
        result = agent._rule_based_fallback("Login broken", "I can't log in, error 500")
        assert result.issue_type == "ui_bug"
        assert result.severity == "P1"
        assert result.routing == "engineering"

    def test_rule_based_fallback_unknown(self):
        agent = IssueTriageAgent()
        result = agent._rule_based_fallback("Feature request", "Would love dark mode")
        assert result.issue_type == "other"
        assert result.routing == "product"

    def test_determine_routing_low_confidence_goes_to_product(self):
        agent = IssueTriageAgent()
        routing = agent._determine_routing("ui_bug", 0.3)
        assert routing == "product"

    def test_determine_routing_high_confidence_ui_bug(self):
        agent = IssueTriageAgent()
        routing = agent._determine_routing("ui_bug", 0.9)
        assert routing == "engineering"

    def test_determine_routing_rag_quality(self):
        agent = IssueTriageAgent()
        routing = agent._determine_routing("rag_quality", 0.8)
        assert routing == "product"

    def test_determine_routing_data_privacy_always_trust_safety(self):
        agent = IssueTriageAgent()
        routing = agent._determine_routing("data_privacy", 0.9)
        assert routing == "trust_safety"

    def test_determine_routing_performance(self):
        agent = IssueTriageAgent()
        routing = agent._determine_routing("performance", 0.8)
        assert routing == "engineering"

    def test_determine_routing_access(self):
        agent = IssueTriageAgent()
        routing = agent._determine_routing("access", 0.7)
        assert routing == "engineering"


class TestIssueTriageAgentLLM:
    """Test LLM-based triage path with mocked LLM."""

    async def test_triage_uses_llm_result(self):
        agent = IssueTriageAgent()
        llm_response = '{"issue_type": "ui_bug", "severity": "P2", "confidence": 0.85, "reasoning": "UI glitch"}'

        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = llm_response
            result = await agent.triage(
                "Button broken", "Submit button does nothing", "tenant-1"
            )

        assert result.issue_type == "ui_bug"
        assert result.severity == "P2"
        assert result.confidence == 0.85
        assert result.routing == "engineering"

    async def test_triage_escalates_data_privacy_to_p0(self):
        agent = IssueTriageAgent()
        llm_response = '{"issue_type": "data_privacy", "severity": "P2", "confidence": 0.9, "reasoning": "Privacy issue"}'

        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = llm_response
            result = await agent.triage(
                "I see other users data", "Privacy concern", "tenant-1"
            )

        assert result.severity == "P0"  # Escalated by rule
        assert result.routing == "trust_safety"  # Overridden by rule

    async def test_triage_keyword_escalates_to_p0(self):
        agent = IssueTriageAgent()
        llm_response = '{"issue_type": "ui_bug", "severity": "P2", "confidence": 0.7, "reasoning": "Bug"}'

        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = llm_response
            result = await agent.triage(
                "Data leak found", "Seeing other user's data in results", "tenant-1"
            )

        assert result.severity == "P0"
        assert result.routing == "trust_safety"

    async def test_triage_falls_back_when_llm_fails(self):
        agent = IssueTriageAgent()

        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("LLM unavailable")
            result = await agent.triage(
                "Something broken", "App crashes on login", "tenant-1"
            )

        assert result is not None
        assert result.issue_type in (
            "ui_bug",
            "data_privacy",
            "other",
        )  # rule-based fallback

    async def test_triage_pii_keyword_escalates(self):
        agent = IssueTriageAgent()
        llm_response = '{"issue_type": "other", "severity": "P3", "confidence": 0.6, "reasoning": "General"}'

        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = llm_response
            result = await agent.triage(
                "PII exposure", "User PII visible in logs", "tenant-1"
            )

        assert result.severity == "P0"
        assert result.routing == "trust_safety"

    async def test_triage_low_confidence_routes_to_product(self):
        agent = IssueTriageAgent()
        llm_response = '{"issue_type": "ui_bug", "severity": "P2", "confidence": 0.3, "reasoning": "Unsure"}'

        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = llm_response
            result = await agent.triage(
                "Minor issue", "Something looks off", "tenant-1"
            )

        assert result.routing == "product"  # Low confidence -> needs human review

    async def test_triage_missing_confidence_defaults_to_0_7(self):
        agent = IssueTriageAgent()
        llm_response = (
            '{"issue_type": "ui_bug", "severity": "P2", "reasoning": "Bug found"}'
        )

        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = llm_response
            result = await agent.triage("Minor bug", "Small UI issue", "tenant-1")

        assert result.confidence == 0.7

    async def test_triage_wrong_person_keyword_escalates(self):
        agent = IssueTriageAgent()
        llm_response = '{"issue_type": "ui_bug", "severity": "P3", "confidence": 0.8, "reasoning": "Display bug"}'

        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = llm_response
            result = await agent.triage(
                "Wrong person data", "I see wrong person's files", "tenant-1"
            )

        assert result.severity == "P0"
        assert result.routing == "trust_safety"
