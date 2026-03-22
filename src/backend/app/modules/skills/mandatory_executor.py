"""
MandatorySkillExecutor — post-processing layer for mandatory skills (TODO-25, Gap 9).

Mandatory skills are configured per-agent and run after every response.
They must never block the user response — failures are captured and reported
but the original response is always returned.

Stage 8.5: Mandatory skills receive the guardrail-cleared response (not raw LLM output).
Timeout: configurable, defaults to 500ms. Timeouts are captured as failures.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from app.modules.skills.executor import SkillExecutor, SkillResult, ExecutionContext

logger = structlog.get_logger()

# Default timeout for mandatory skill execution: 500ms
_DEFAULT_TIMEOUT_MS = 500


@dataclass
class MandatorySkillResult:
    """Result of running all mandatory skills after a response."""

    response: str
    skill_results: list[dict[str, Any]] = field(default_factory=list)
    skill_failures: list[dict[str, Any]] = field(default_factory=list)


class MandatorySkillExecutor:
    """
    Runs mandatory skills in post-processing.

    Mandatory skills are fire-and-soft-fail:
    - Run concurrently after the main response is generated.
    - Each skill has a bounded timeout (default 500ms).
    - Skill failures are logged and captured but never block the response.
    - The guardrail-cleared agent response is passed to mandatory skills as input.

    Usage:
        executor = MandatorySkillExecutor()
        result = await executor.execute(
            agent_response="...",
            mandatory_skills=[...],
            conversation_context={},
            tenant_id="...",
            agent_id="...",
        )
    """

    def __init__(self, timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> None:
        self._timeout_ms = timeout_ms

    async def execute(
        self,
        agent_response: str,
        mandatory_skills: list[dict[str, Any]],
        conversation_context: dict[str, Any],
        tenant_id: str,
        agent_id: str,
    ) -> MandatorySkillResult:
        """
        Execute all mandatory skills against the guardrail-cleared agent response.

        Args:
            agent_response: The guardrail-cleared response text to process.
            mandatory_skills: List of skill records to execute.
            conversation_context: Ambient conversation context.
            tenant_id: The calling tenant's ID.
            agent_id: The calling agent's ID.

        Returns:
            MandatorySkillResult with the original response preserved and skill
            execution outcomes recorded (never raises on skill failure).
        """
        if not mandatory_skills:
            return MandatorySkillResult(response=agent_response)

        skill_results: list[dict[str, Any]] = []
        skill_failures: list[dict[str, Any]] = []

        skill_executor = SkillExecutor()
        timeout_seconds = self._timeout_ms / 1000.0

        async def _run_skill(skill: dict[str, Any]) -> None:
            skill_id = skill.get("id", "unknown")
            skill_name = skill.get("name", "unknown")
            context = ExecutionContext(
                tenant_id=tenant_id,
                agent_id=agent_id,
            )
            input_data = {
                "response_text": agent_response,
                "conversation_context": conversation_context,
            }
            try:
                result: SkillResult = await asyncio.wait_for(
                    skill_executor.execute(skill, input_data, context),
                    timeout=timeout_seconds,
                )
                skill_results.append({
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                    "success": result.success,
                    "tokens_used": result.tokens_used,
                })
            except asyncio.TimeoutError:
                logger.warning(
                    "mandatory_skill_timeout",
                    skill_id=skill_id,
                    skill_name=skill_name,
                    timeout_ms=self._timeout_ms,
                    tenant_id=tenant_id,
                )
                skill_failures.append({
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                    "error": "timeout",
                    "detail": f"Skill exceeded {self._timeout_ms}ms timeout",
                })
            except Exception as exc:
                logger.warning(
                    "mandatory_skill_error",
                    skill_id=skill_id,
                    skill_name=skill_name,
                    error=str(exc),
                    tenant_id=tenant_id,
                )
                skill_failures.append({
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                    "error": "exception",
                    "detail": str(exc),
                })

        # Run all mandatory skills concurrently — failures are soft
        await asyncio.gather(*[_run_skill(s) for s in mandatory_skills])

        return MandatorySkillResult(
            response=agent_response,  # Always preserve the original response
            skill_results=skill_results,
            skill_failures=skill_failures if skill_failures else [],
        )
