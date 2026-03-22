"""
Agent orchestrator routing utilities (TODO-25).

Provides LLM response parsing for multi-agent routing decisions.
The orchestrator uses an LLM to select which agent to route a query to,
then caches the routing decision to avoid redundant LLM calls.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import structlog

logger = structlog.get_logger()

# Routing decision cache TTL: 5 minutes
_ROUTING_CACHE_TTL_SECONDS = 300


@dataclass
class RoutingDecision:
    """Result of an LLM routing decision."""

    agent_id: Optional[str]
    confidence: float
    reasoning: str
    fallback: bool


def _routing_decision_from_llm_response(
    llm_output: str,
    confidence_threshold: float = 0.7,
) -> RoutingDecision:
    """
    Parse an LLM routing response and apply the confidence threshold.

    The LLM is expected to return JSON with:
        {"agent_id": "<id>|null", "confidence": 0.0-1.0, "reasoning": "<text>"}

    If the response cannot be parsed, or confidence < threshold, or agent_id is null,
    the decision falls back to general RAG (agent_id=None, fallback=True).

    Args:
        llm_output: Raw string output from the routing LLM.
        confidence_threshold: Minimum confidence required to use a routed agent.
                              Queries below this threshold fall back to general RAG.

    Returns:
        RoutingDecision with agent_id=None and fallback=True on fallback paths.
    """
    try:
        data = json.loads(llm_output)
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "orchestrator_routing_invalid_json",
            llm_output_preview=llm_output[:100],
        )
        return RoutingDecision(
            agent_id=None,
            confidence=0.0,
            reasoning="Could not parse LLM routing response",
            fallback=True,
        )

    agent_id: Optional[str] = data.get("agent_id") or None
    confidence: float = float(data.get("confidence", 0.0))
    reasoning: str = data.get("reasoning", "")

    # Fall back if agent_id is absent or confidence is below threshold
    if agent_id is None or confidence < confidence_threshold:
        logger.info(
            "orchestrator_routing_fallback",
            agent_id=agent_id,
            confidence=confidence,
            threshold=confidence_threshold,
        )
        return RoutingDecision(
            agent_id=None,
            confidence=confidence,
            reasoning=reasoning,
            fallback=True,
        )

    return RoutingDecision(
        agent_id=agent_id,
        confidence=confidence,
        reasoning=reasoning,
        fallback=False,
    )
