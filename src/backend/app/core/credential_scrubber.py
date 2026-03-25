"""
CredentialScrubber — request-scoped credential value redaction.

Scrubs all resolved platform credential values from strings before they
leave the tool execution boundary (error messages, log entries, LLM context).

Security requirement C-01: Third-party APIs may echo credential values in
error responses (e.g., PitchBook: {"error": "Invalid API key: sk-live-abc"}).
The scrubber prevents these from propagating to logs, users, or LLM context.
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["CredentialScrubber"]


class CredentialScrubber:
    """Request-scoped credential value scrubber.

    Usage:
        resolved = await resolve_platform_credentials(template_id, keys)
        scrubber = CredentialScrubber(resolved)
        safe_error = scrubber.scrub(raw_error_from_tool)

    Args:
        resolved_credentials: Dict returned by resolve_platform_credentials().
                             Format: {key: {"value": str, "injection_config": dict}}
                             OR flat {key: str} for tenant credentials.
    """

    def __init__(self, resolved_credentials: dict) -> None:
        self._values: list[str] = []
        for v in resolved_credentials.values():
            if isinstance(v, dict):
                # Platform credential format: {"value": str, "injection_config": dict}
                raw = v.get("value", "")
            else:
                # Tenant credential format: str
                raw = v or ""
            if raw and len(raw) > 4:
                self._values.append(raw)

    def scrub(self, text: str) -> str:
        """Replace any credential value in text with [REDACTED].

        Args:
            text: Any string that may contain credential values.

        Returns:
            The input string with all credential values replaced by [REDACTED].
        """
        if not text or not self._values:
            return text
        for val in self._values:
            if val in text:
                text = text.replace(val, "[REDACTED]")
        return text

    def scrub_dict(self, data: dict) -> dict:
        """Recursively scrub all string values in a dict."""
        result = {}
        for k, v in data.items():
            if isinstance(v, str):
                result[k] = self.scrub(v)
            elif isinstance(v, dict):
                result[k] = self.scrub_dict(v)
            elif isinstance(v, list):
                result[k] = [self.scrub(i) if isinstance(i, str) else i for i in v]
            else:
                result[k] = v
        return result
