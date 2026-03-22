"""
SystemPromptValidator — prompt injection and ReDoS detection.

Used on all save paths for agent templates, tenant skills, and custom agents.
Implements OWASP LLM Top 10 prompt injection detection patterns.

Usage:
    result = validate_prompt(prompt_text)
    if not result.valid:
        raise HTTPException(422, detail=result.reason)

PA override: if override_validation=True is passed with a non-empty reason,
the save is allowed but an audit log entry is written.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Character limits
# ---------------------------------------------------------------------------
SKILL_PROMPT_MAX_CHARS = 3000   # tenant skill prompts (less exposed)
TEMPLATE_PROMPT_MAX_CHARS = 2000  # PA agent template system prompts

# ReDoS detection timeout (ms)
_REDOS_TIMEOUT_MS = 50

# ---------------------------------------------------------------------------
# Injection detection patterns (OWASP LLM Top 10 corpus)
# ---------------------------------------------------------------------------
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    # Jailbreak classics
    (r"ignore\s+(all\s+|previous\s+|your\s+)?(instructions?|directives?|system|prompt)", "jailbreak_ignore_instructions"),
    (r"disregard\s+(your|the)\s+system", "jailbreak_disregard_system"),
    (r"act\s+as\s+(DAN|DAN-|jailbroken|an?\s+(unfiltered|unrestricted|uncensored))", "jailbreak_act_as_dan"),
    (r"you\s+are\s+now\s+(a|an|DAN)\b", "jailbreak_you_are_now"),
    (r"respond\s+to\s+(me\s+|the\s+user\s+)?as\s+if", "jailbreak_respond_as_if"),
    (r"pretend\s+(that\s+|you\s+are\s+)", "jailbreak_pretend"),
    # Role-play escalation
    (r"(you\s+are\s+)?(a\s+)?helpful\s+(and\s+)?honest.*no\s+restrictions?", "jailbreak_no_restrictions"),
    (r"without\s+(any|ethical)\s+(restrictions?|constraints?|limitations?)", "jailbreak_bypass_restrictions"),
    # Prompt leakage attempts
    (r"(repeat|print|reveal|output|display)\s+(your|the|this)\s+(system\s+)?prompt", "prompt_leakage_attempt"),
    (r"what\s+(are|is)\s+your\s+(exact\s+)?(instructions?|prompt|system\s+message)", "prompt_leakage_attempt"),
    # Common Unicode homoglyph bypass patterns
    # Cyrillic characters that look like Latin (а=\u0430, е=\u0435, о=\u043e, etc.)
    # Detect suspicious non-ASCII in keyword positions
    (r"[\u0430\u0435\u043e\u0440\u0441\u0445\u0441\u0440\u0443\u0438]{3,}", "unicode_homoglyph_suspicious"),
    # Developer mode tricks
    (r"\[developer\s+mode\s+(on|enabled)\]", "jailbreak_developer_mode"),
    (r"(enable|activate)\s+(god|developer|admin|root)\s+mode", "jailbreak_mode_switch"),
    # Instruction injection via delimiters
    (r"---\s*end\s+of\s+(system\s+)?instructions?", "delimiter_injection"),
    (r"\[SYSTEM\]\s", "system_tag_injection"),
    (r"<\|im_start\|>", "im_start_injection"),
]

_COMPILED_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(pattern, re.IGNORECASE), label)
    for pattern, label in _INJECTION_PATTERNS
]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    valid: bool
    reason: Optional[str] = None
    blocked_patterns: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_prompt(
    prompt: str,
    max_chars: int = SKILL_PROMPT_MAX_CHARS,
) -> ValidationResult:
    """
    Validate a prompt template for injection patterns and length.

    Args:
        prompt: The prompt string to validate.
        max_chars: Maximum allowed character count.

    Returns:
        ValidationResult with valid=True if safe, else False with details.
    """
    if not isinstance(prompt, str):
        return ValidationResult(valid=False, reason="Prompt must be a string")

    if len(prompt) > max_chars:
        return ValidationResult(
            valid=False,
            reason=f"Prompt exceeds maximum length of {max_chars} characters ({len(prompt)} given)",
        )

    blocked: list[str] = []
    for pattern, label in _COMPILED_PATTERNS:
        if pattern.search(prompt):
            blocked.append(label)

    if blocked:
        return ValidationResult(
            valid=False,
            reason=f"Prompt contains blocked injection patterns: {', '.join(sorted(set(blocked)))}",
            blocked_patterns=list(sorted(set(blocked))),
        )

    return ValidationResult(valid=True)


async def validate_guardrail_regex(pattern: str) -> ValidationResult:
    """
    Validate a regex pattern from a guardrail rule.

    Tests for ReDoS vulnerability by running a match attempt against
    a known catastrophic input within a tight timeout.

    Args:
        pattern: Regex string to validate.

    Returns:
        ValidationResult with valid=True if the pattern is safe.
    """
    if not isinstance(pattern, str):
        return ValidationResult(valid=False, reason="Pattern must be a string")

    # Compile first to catch syntax errors
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return ValidationResult(valid=False, reason=f"Invalid regex: {exc}")

    # ReDoS detection: try matching against a pathological input string
    # Known catastrophic patterns like (a+)+ fail here within the timeout
    redos_test_input = "a" * 50 + "!"

    try:
        async def _test_match() -> None:
            compiled.search(redos_test_input)

        await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, compiled.search, redos_test_input),
            timeout=_REDOS_TIMEOUT_MS / 1000,
        )
    except asyncio.TimeoutError:
        return ValidationResult(
            valid=False,
            reason=(
                "Regex pattern may be vulnerable to ReDoS (catastrophic backtracking). "
                "Simplify the pattern."
            ),
        )
    except Exception as exc:
        return ValidationResult(
            valid=False,
            reason=f"Regex validation error: {str(exc)[:200]}",
        )

    return ValidationResult(valid=True)
