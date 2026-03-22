"""
SkillExecutor — executes a tenant skill or platform skill in a bounded context.

Execution patterns:
  - 'tool_compose':   orchestrates a sequence of tool calls
  - 'prompt_chain':   LLM call with optional pipeline triggers (e.g. follow-up search)
  - 'data_transform': transforms structured data with optional tool calls
  - 'rag_augment':    adds domain context to a query before RAG retrieval

Token budget enforcement:
  - Fail-closed: if tokens_used >= token_budget BEFORE an LLM call, return SkillError
  - max_tool_calls_per_skill = 5 (hard cap; prevents runaway tool orchestration)
  - Plan-gate re-checked at execution time (tenant may have downgraded since adoption)

ExecutionContext is threadsafe for single-threaded async usage (one skill at a time per context).
"""
from __future__ import annotations

import os
import string
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

# Hard limits (non-configurable per tenant)
MAX_TOOL_CALLS_PER_SKILL = 5
DEFAULT_TOKEN_BUDGET = 2000
MAX_PROMPT_INTERPOLATION_CHARS = 8000  # Safety cap on interpolated prompt length


# ---------------------------------------------------------------------------
# ExecutionContext
# ---------------------------------------------------------------------------

@dataclass
class ExecutionContext:
    """
    Mutable execution state for a single skill invocation.

    Args:
        tenant_id: Calling tenant's UUID string.
        agent_id: Calling agent's UUID string.
        conversation_id: Active conversation UUID (for working memory lookup).
        token_budget: Maximum tokens allowed for all LLM calls in this skill.
        tokens_used: Accumulated token usage (updated after each LLM call).
        tool_calls_made: Number of tool calls dispatched in this invocation.
        llm_response: Concatenated LLM response text (populated during execution).
        confidence_score: Estimated confidence [0.0, 1.0] for pipeline triggers.
    """
    tenant_id: str
    agent_id: str
    conversation_id: Optional[str] = None
    token_budget: int = DEFAULT_TOKEN_BUDGET
    tokens_used: int = 0
    tool_calls_made: int = 0
    llm_response: str = ""
    confidence_score: float = 0.0
    _tool_results: list[dict] = field(default_factory=list)

    @property
    def tokens_remaining(self) -> int:
        return max(0, self.token_budget - self.tokens_used)

    @property
    def tool_calls_remaining(self) -> int:
        return max(0, MAX_TOOL_CALLS_PER_SKILL - self.tool_calls_made)

    def budget_exceeded(self) -> bool:
        return self.tokens_used >= self.token_budget

    def tool_limit_reached(self) -> bool:
        return self.tool_calls_made >= MAX_TOOL_CALLS_PER_SKILL


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SkillResult:
    success: bool
    output: dict
    tokens_used: int = 0
    tool_calls_made: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class SkillError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"[{code}] {detail}")


# ---------------------------------------------------------------------------
# Pipeline trigger evaluation
# ---------------------------------------------------------------------------

def _evaluate_pipeline_triggers(
    trigger_config: dict,
    context: ExecutionContext,
) -> bool:
    """
    Evaluate pipeline continuation triggers.

    Supported trigger types (OR logic — any match triggers continuation):
      - response_length: { min: int } — trigger if llm_response is shorter than min
      - confidence_score: { below: float } — trigger if score < threshold
      - contains_keyword: { keywords: [str] } — trigger if any keyword found in response
      - always: {} — always trigger (for chained pipelines)
      - never: {} — never trigger (effectively disables continuation)

    Returns True if continuation should be triggered.
    """
    if not trigger_config:
        return False

    trigger_type = trigger_config.get("type", "never")

    if trigger_type == "always":
        return True
    if trigger_type == "never":
        return False
    if trigger_type == "response_length":
        min_len = int(trigger_config.get("min", 100))
        return len(context.llm_response) < min_len
    if trigger_type == "confidence_score":
        threshold = float(trigger_config.get("below", 0.7))
        return context.confidence_score < threshold
    if trigger_type == "contains_keyword":
        keywords = trigger_config.get("keywords", [])
        response_lower = context.llm_response.lower()
        return any(kw.lower() in response_lower for kw in keywords)

    logger.warning("skill_unknown_pipeline_trigger", trigger_type=trigger_type)
    return False


# ---------------------------------------------------------------------------
# Prompt interpolation
# ---------------------------------------------------------------------------

def _interpolate_prompt(template: str, input_values: dict) -> str:
    """
    Safely interpolate {variable} placeholders in a prompt template.

    Uses string.Formatter to enumerate fields rather than .format(**input_values)
    to avoid attribute access attacks (e.g., {__class__.__mro__}).

    Only simple field names are allowed (no attribute access, no indexing).
    Unknown fields are left as-is (not raised as errors).
    """
    formatter = string.Formatter()
    result_parts: list[str] = []

    for literal, field_name, format_spec, conversion in formatter.parse(template):
        result_parts.append(literal)
        if field_name is None:
            continue
        # Guard: no attribute access or indexing
        if "." in field_name or "[" in field_name:
            # Leave the placeholder as-is
            result_parts.append("{" + field_name + "}")
            continue
        value = input_values.get(field_name)
        if value is None:
            # Leave placeholder unchanged
            result_parts.append("{" + field_name + "}")
        else:
            result_parts.append(str(value))

    interpolated = "".join(result_parts)
    # Safety cap
    if len(interpolated) > MAX_PROMPT_INTERPOLATION_CHARS:
        interpolated = interpolated[:MAX_PROMPT_INTERPOLATION_CHARS]
    return interpolated


# ---------------------------------------------------------------------------
# LLM call helper (thin wrapper — uses platform LLM client)
# ---------------------------------------------------------------------------

async def _call_llm(prompt: str, context: ExecutionContext) -> tuple[str, int]:
    """
    Call the platform LLM with budget enforcement.

    Returns (response_text, tokens_consumed).
    Raises SkillError on budget exceeded or LLM failure.
    """
    if context.budget_exceeded():
        raise SkillError(
            "token_budget_exceeded",
            f"Token budget of {context.token_budget} already exhausted before LLM call",
        )

    try:
        from app.modules.chat.embedding import _get_llm_client  # type: ignore[import]

        llm_client = _get_llm_client()
        response = await llm_client.complete(prompt)
        # Estimate tokens: ~4 chars/token heuristic when exact count unavailable
        tokens_consumed = getattr(llm_client, "last_tokens_used", None)
        if tokens_consumed is None:
            tokens_consumed = max(1, (len(prompt) + len(response)) // 4)
        return response.strip(), int(tokens_consumed)
    except SkillError:
        raise
    except Exception as exc:
        raise SkillError("llm_call_failed", f"LLM call failed: {str(exc)[:200]}") from exc


# ---------------------------------------------------------------------------
# SkillExecutor
# ---------------------------------------------------------------------------

class SkillExecutor:
    """
    Executes a skill record against an ExecutionContext.

    Skills are tenant-authored or platform-published. Each has:
      - execution_pattern: 'tool_compose' | 'prompt_chain' | 'data_transform' | 'rag_augment'
      - prompt_template: Optional Jinja-style {variable} prompt
      - tool_dependencies: list of tool_catalog UUIDs (resolved at execution time)
      - pipeline_config: Optional dict with trigger config for continuation
      - guardrails: Optional list of {'type': 'regex'/'length', ...} configs

    Usage:
        executor = SkillExecutor(tool_executor=ToolExecutor(...))
        result = await executor.execute(skill_record, input_data, context)
    """

    def __init__(
        self,
        tool_executor: Any = None,
    ) -> None:
        self._tool_executor = tool_executor

    async def execute(
        self,
        skill: dict,
        input_data: dict,
        context: ExecutionContext,
    ) -> SkillResult:
        """
        Execute a skill.

        Args:
            skill: Skill record dict (from tenant_skills or platform skills).
            input_data: User-supplied input values for this invocation.
            context: Mutable execution context (token budget, counters, etc.).

        Returns:
            SkillResult with success/failure info.
        """
        import time

        skill_id = str(skill.get("id", ""))
        skill_name = skill.get("name", "unknown")
        execution_pattern = skill.get("execution_pattern", "prompt_chain")

        start_ms = int(time.time() * 1000)

        try:
            # Plan-gate re-check at execution time
            skill_plan = skill.get("plan_required", "starter")
            from app.modules.agents.skills_routes import PLAN_ORDER
            tenant_plan = input_data.get("__tenant_plan__", "starter")
            t_rank = PLAN_ORDER.get(tenant_plan, 0)
            s_rank = PLAN_ORDER.get(skill_plan, 0)
            if t_rank < s_rank:
                raise SkillError(
                    "plan_downgraded",
                    f"Skill requires '{skill_plan}' plan; tenant is on '{tenant_plan}'",
                )

            if execution_pattern == "tool_compose":
                output = await self._execute_tool_compose(skill, input_data, context)
            elif execution_pattern == "prompt_chain":
                output = await self._execute_prompt_chain(skill, input_data, context)
            elif execution_pattern == "data_transform":
                output = await self._execute_data_transform(skill, input_data, context)
            elif execution_pattern == "rag_augment":
                output = await self._execute_rag_augment(skill, input_data, context)
            else:
                raise SkillError(
                    "unknown_execution_pattern",
                    f"Unsupported execution_pattern: {execution_pattern}",
                )

            latency_ms = int(time.time() * 1000) - start_ms
            logger.info(
                "skill_execution_success",
                skill_id=skill_id,
                skill_name=skill_name,
                execution_pattern=execution_pattern,
                tenant_id=context.tenant_id,
                tokens_used=context.tokens_used,
                tool_calls_made=context.tool_calls_made,
                latency_ms=latency_ms,
            )
            return SkillResult(
                success=True,
                output=output,
                tokens_used=context.tokens_used,
                tool_calls_made=context.tool_calls_made,
            )

        except SkillError as exc:
            latency_ms = int(time.time() * 1000) - start_ms
            logger.warning(
                "skill_execution_error",
                skill_id=skill_id,
                skill_name=skill_name,
                error_code=exc.code,
                error_detail=exc.detail,
                tenant_id=context.tenant_id,
                latency_ms=latency_ms,
            )
            return SkillResult(
                success=False,
                output={},
                tokens_used=context.tokens_used,
                tool_calls_made=context.tool_calls_made,
                error_code=exc.code,
                error_message=exc.detail,
            )
        except Exception as exc:
            latency_ms = int(time.time() * 1000) - start_ms
            logger.error(
                "skill_execution_unexpected_error",
                skill_id=skill_id,
                skill_name=skill_name,
                error=str(exc),
                tenant_id=context.tenant_id,
                latency_ms=latency_ms,
            )
            return SkillResult(
                success=False,
                output={},
                tokens_used=context.tokens_used,
                tool_calls_made=context.tool_calls_made,
                error_code="internal_error",
                error_message=str(exc)[:200],
            )

    # ---------------------------------------------------------------------------
    # Execution pattern implementations
    # ---------------------------------------------------------------------------

    async def _execute_tool_compose(
        self,
        skill: dict,
        input_data: dict,
        context: ExecutionContext,
    ) -> dict:
        """
        Tool-compose pattern: call one or more tools in sequence, accumulate results.

        tool_dependencies is a list of tool_catalog records resolved before calling.
        Each tool is called with the original input_data; results are accumulated.
        """
        if self._tool_executor is None:
            raise SkillError("tool_executor_unavailable", "No ToolExecutor configured for this SkillExecutor")

        tool_records: list[dict] = skill.get("_resolved_tools", [])
        if not tool_records:
            raise SkillError("no_tools_configured", "tool_compose skill has no resolved tool records")

        accumulated: dict = {}
        for tool_record in tool_records:
            if context.tool_limit_reached():
                raise SkillError(
                    "tool_call_limit_reached",
                    f"Maximum {MAX_TOOL_CALLS_PER_SKILL} tool calls per skill exceeded",
                )

            tool_result = await self._tool_executor.execute(
                tool=tool_record,
                arguments=input_data,
                tenant_id=context.tenant_id,
                agent_id=context.agent_id,
            )
            context.tool_calls_made += 1
            context._tool_results.append({
                "tool_id": str(tool_record.get("id", "")),
                "success": tool_result.success,
                "output": tool_result.output,
            })
            if not tool_result.success:
                logger.warning(
                    "skill_tool_compose_tool_failed",
                    tool_id=str(tool_record.get("id", "")),
                    error_code=tool_result.error_code,
                    tenant_id=context.tenant_id,
                )
                continue
            accumulated.update(tool_result.output)

        return {"tool_results": context._tool_results, "accumulated": accumulated}

    async def _execute_prompt_chain(
        self,
        skill: dict,
        input_data: dict,
        context: ExecutionContext,
    ) -> dict:
        """
        Prompt-chain pattern:
          1. Interpolate prompt_template with input_data
          2. (Optional) pre-call tool for context enrichment
          3. LLM call with budget enforcement
          4. Evaluate pipeline_config triggers for optional continuation
        """
        prompt_template: str = skill.get("prompt_template") or ""
        if not prompt_template:
            raise SkillError("no_prompt_template", "prompt_chain skill requires a prompt_template")

        # Optional pre-tool call (first tool dependency as context enricher)
        tool_context_output: dict = {}
        tool_records: list[dict] = skill.get("_resolved_tools", [])
        if tool_records and self._tool_executor is not None:
            if not context.tool_limit_reached():
                pre_tool = tool_records[0]
                pre_result = await self._tool_executor.execute(
                    tool=pre_tool,
                    arguments=input_data,
                    tenant_id=context.tenant_id,
                    agent_id=context.agent_id,
                )
                context.tool_calls_made += 1
                if pre_result.success:
                    tool_context_output = pre_result.output

        # Merge tool context into interpolation values
        interpolation_values = {**input_data, **tool_context_output}
        prompt = _interpolate_prompt(prompt_template, interpolation_values)

        # Primary LLM call (fail-closed on budget exceeded)
        # Pre-check budget here so that callers who mock _call_llm still see
        # the fail-closed behaviour (token_budget_exceeded).
        if context.budget_exceeded():
            raise SkillError(
                "token_budget_exceeded",
                f"Token budget of {context.token_budget} already exhausted before LLM call",
            )
        response_text, tokens_consumed = await _call_llm(prompt, context)
        context.tokens_used += tokens_consumed
        context.llm_response = response_text

        # Estimate confidence: use response length as a simple proxy
        # (Real implementations should extract from LLM logprobs or a classifier)
        context.confidence_score = min(1.0, len(response_text) / 800.0)

        output: dict = {
            "response": response_text,
            "tokens_used": context.tokens_used,
        }

        # Pipeline trigger evaluation for continuation
        pipeline_config: dict = skill.get("pipeline_config") or {}
        if pipeline_config:
            trigger_config = pipeline_config.get("trigger", {})
            if _evaluate_pipeline_triggers(trigger_config, context):
                continuation_prompt = pipeline_config.get("continuation_prompt", "")
                if continuation_prompt and not context.budget_exceeded():
                    cont_prompt = _interpolate_prompt(continuation_prompt, {
                        "initial_response": response_text,
                        **input_data,
                    })
                    cont_response, cont_tokens = await _call_llm(cont_prompt, context)
                    context.tokens_used += cont_tokens
                    context.llm_response = cont_response
                    output["continuation_response"] = cont_response
                    output["tokens_used"] = context.tokens_used

        return output

    async def _execute_data_transform(
        self,
        skill: dict,
        input_data: dict,
        context: ExecutionContext,
    ) -> dict:
        """
        Data-transform pattern: apply tool-based transformation to structured data.

        Uses the data_formatter built-in tool to convert between formats,
        or delegates to the first configured tool dependency.
        """
        tool_records: list[dict] = skill.get("_resolved_tools", [])

        if not tool_records or self._tool_executor is None:
            # No tool configured — apply direct format inference
            data = input_data.get("data") or input_data
            return {"transformed": data, "format": "passthrough"}

        if context.tool_limit_reached():
            raise SkillError(
                "tool_call_limit_reached",
                f"Maximum {MAX_TOOL_CALLS_PER_SKILL} tool calls per skill exceeded",
            )

        transform_tool = tool_records[0]
        tool_result = await self._tool_executor.execute(
            tool=transform_tool,
            arguments=input_data,
            tenant_id=context.tenant_id,
            agent_id=context.agent_id,
        )
        context.tool_calls_made += 1

        if not tool_result.success:
            raise SkillError(
                "data_transform_tool_failed",
                f"Transform tool failed: {tool_result.error_code}",
            )

        return tool_result.output

    async def _execute_rag_augment(
        self,
        skill: dict,
        input_data: dict,
        context: ExecutionContext,
    ) -> dict:
        """
        RAG-augment pattern: enrich the query with domain context before retrieval.

        Uses the prompt_template to wrap the user query with domain instructions.
        Returns the augmented query text (not the final RAG response — that is
        handled by the chat orchestration layer).
        """
        prompt_template: str = skill.get("prompt_template") or ""
        query: str = input_data.get("query", "")

        if not query:
            raise SkillError("rag_augment_no_query", "rag_augment requires 'query' in input_data")

        if not prompt_template:
            # No augmentation configured — return query unchanged
            return {"augmented_query": query, "augmented": False}

        augmented = _interpolate_prompt(prompt_template, {"query": query, **input_data})
        return {"augmented_query": augmented, "augmented": True}
