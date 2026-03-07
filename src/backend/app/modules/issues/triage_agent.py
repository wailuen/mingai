"""
Issue Triage Agent (AI-037, AI-038).

Classifies incoming issue reports using LLM to determine:
- Issue type: ui_bug | rag_quality | performance | data_privacy | access | other
- Severity: P0 (critical) | P1 (high) | P2 (medium) | P3 (low)
- Confidence score: 0.0 - 1.0
- Routing: engineering | trust_safety | product | auto_close

Rules (non-LLM, applied after LLM output):
- P0 if keywords: "data leak", "wrong person", "other user's data", "PII"
- P0 if type == "data_privacy"
- P1 if keywords: "not working", "can't access", "broken", "error"
- confidence < 0.5 -> route to "product" (needs human review)
- type == "data_privacy" -> route to "trust_safety" regardless of confidence

The LLM call reads INTENT_MODEL / PRIMARY_MODEL and CLOUD_PROVIDER from env
(same pattern as ChatOrchestrationService).
"""

import json
import os
from dataclasses import dataclass
from typing import Literal

import structlog

logger = structlog.get_logger()

IssueType = Literal[
    "ui_bug", "rag_quality", "performance", "data_privacy", "access", "other"
]
Severity = Literal["P0", "P1", "P2", "P3"]
RoutingDest = Literal["engineering", "trust_safety", "product", "auto_close"]


@dataclass
class TriageResult:
    """Result of issue triage classification."""

    issue_type: IssueType
    severity: Severity
    confidence: float
    routing: RoutingDest
    reasoning: str


class IssueTriageAgent:
    """
    LLM-based issue triage classifier.

    Uses the same env-var pattern as ChatOrchestrationService:
    - CLOUD_PROVIDER: "azure" | "openai" | "local"
    - INTENT_MODEL: model to use for intent/classification (lighter than PRIMARY_MODEL)
    - PRIMARY_MODEL: fallback model if INTENT_MODEL not set
    """

    TRIAGE_PROMPT = """You are an issue triage system for an enterprise AI platform.
Classify this issue report into JSON format.

Issue title: {title}
Issue description: {description}

Return ONLY valid JSON with exactly these fields:
{{
  "issue_type": "ui_bug" | "rag_quality" | "performance" | "data_privacy" | "access" | "other",
  "severity": "P0" | "P1" | "P2" | "P3",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}}

Severity guide:
- P0: data privacy breach, wrong user's data shown, critical security issue
- P1: core feature broken, users cannot complete their work
- P2: degraded experience, workaround exists
- P3: minor UI issue, enhancement request
"""

    _P0_KEYWORDS = (
        "data leak",
        "wrong person",
        "other user",
        "other user's data",
        "pii",
    )
    _P1_KEYWORDS = ("not working", "can't access", "broken", "error")
    _PRIVACY_KEYWORDS = ("data", "privacy", "leak", "pii", "gdpr")
    _BUG_KEYWORDS = ("broken", "not working", "error", "crash", "can't")

    async def triage(
        self, title: str, description: str, tenant_id: str
    ) -> TriageResult:
        """
        Classify issue and return TriageResult.

        Falls back to rule-based classification if LLM call fails.
        """
        _VALID_TYPES = {
            "ui_bug",
            "rag_quality",
            "performance",
            "data_privacy",
            "access",
            "other",
        }
        _VALID_SEVERITIES = {"P0", "P1", "P2", "P3"}

        try:
            raw = await self._call_llm(title, description, tenant_id)
            parsed = json.loads(raw)
            issue_type = parsed.get("issue_type", "")
            severity = parsed.get("severity", "")
            if issue_type not in _VALID_TYPES or severity not in _VALID_SEVERITIES:
                raise ValueError(
                    f"LLM returned invalid fields: issue_type={issue_type!r}, severity={severity!r}"
                )
            confidence = float(parsed.get("confidence", 0.7))
            result = TriageResult(
                issue_type=issue_type,
                severity=severity,
                confidence=confidence,
                routing=self._determine_routing(issue_type, confidence),
                reasoning=parsed.get("reasoning", ""),
            )
        except Exception as exc:
            logger.warning("triage_llm_failed", error=str(exc), title=title[:50])
            result = self._rule_based_fallback(title, description)

        # Override severity for data privacy (CRITICAL security rule - R01)
        if result.issue_type == "data_privacy":
            result.severity = "P0"
            result.routing = "trust_safety"

        # Rule-based P0 escalation for safety-critical keywords
        combined = (title + " " + description).lower()
        if any(kw in combined for kw in self._P0_KEYWORDS):
            result.severity = "P0"
            result.routing = "trust_safety"

        logger.info(
            "issue_triaged",
            issue_type=result.issue_type,
            severity=result.severity,
            confidence=result.confidence,
            routing=result.routing,
            tenant_id=tenant_id,
        )
        return result

    async def _call_llm(self, title: str, description: str, tenant_id: str) -> str:
        """Call LLM for classification. Returns raw JSON string."""
        cloud = os.environ.get("CLOUD_PROVIDER")
        if not cloud:
            raise ValueError(
                "CLOUD_PROVIDER environment variable is not set. "
                "Expected one of: azure, openai, local"
            )

        model = os.environ.get("INTENT_MODEL") or os.environ.get("PRIMARY_MODEL")
        if not model:
            raise ValueError(
                "Neither INTENT_MODEL nor PRIMARY_MODEL environment variable is set. "
                "At least one must be configured for LLM-based triage."
            )

        prompt = self.TRIAGE_PROMPT.format(
            title=title[:200], description=description[:1000]
        )

        if cloud == "azure":
            from openai import AsyncAzureOpenAI

            api_key = os.environ.get("AZURE_PLATFORM_OPENAI_API_KEY")
            endpoint = os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT")
            if not api_key:
                raise ValueError(
                    "AZURE_PLATFORM_OPENAI_API_KEY environment variable is not set. "
                    "Required for Azure cloud provider."
                )
            if not endpoint:
                raise ValueError(
                    "AZURE_PLATFORM_OPENAI_ENDPOINT environment variable is not set. "
                    "Required for Azure cloud provider."
                )
            client = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=endpoint,
                api_version="2024-02-01",
            )
        elif cloud in ("openai", "local"):
            from openai import AsyncOpenAI

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError(
                    "OPENAI_API_KEY environment variable is not set. "
                    "Required for openai/local cloud provider."
                )
            client = AsyncOpenAI(api_key=api_key)
        else:
            raise ValueError(
                f"Unsupported CLOUD_PROVIDER: {cloud!r}. "
                "Expected one of: azure, openai, local"
            )

        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=256,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError(
                "LLM returned empty content. Model may have refused or hit a filter."
            )
        return content

    def _determine_routing(
        self, issue_type: IssueType, confidence: float
    ) -> RoutingDest:
        """Determine routing destination based on issue type and confidence."""
        if issue_type == "data_privacy":
            return "trust_safety"
        if confidence < 0.5:
            return "product"
        if issue_type in ("ui_bug", "performance", "access"):
            return "engineering"
        if issue_type == "rag_quality":
            return "product"
        return "product"

    def _rule_based_fallback(self, title: str, description: str) -> TriageResult:
        """Fallback classification when LLM is unavailable."""
        combined = (title + " " + description).lower()
        if any(kw in combined for kw in self._PRIVACY_KEYWORDS):
            return TriageResult(
                "data_privacy",
                "P0",
                0.6,
                "trust_safety",
                "Rule-based: privacy keywords",
            )
        if any(kw in combined for kw in self._BUG_KEYWORDS):
            return TriageResult(
                "ui_bug", "P1", 0.5, "engineering", "Rule-based: error keywords"
            )
        return TriageResult("other", "P3", 0.3, "product", "Rule-based: fallback")
