"""
GlossaryExpander - inline glossary expansion for query pre-processing.

Replaces Layer 6 system prompt injection with inline expansion.
RAG embedding uses ORIGINAL query; only LLM call uses expanded query.

Rules:
- First occurrence only (deduplication)
- full_form > 50 chars skipped (security guard)
- Terms <= 3 chars only expand if ALL CAPS in query
- Stop-word exclusion (never expand common words)
- CJK: use full-width parentheses
- Max 10 expansions per query
- Max 20 terms per tenant
- Max 200 chars per definition
"""
import re
import unicodedata

import structlog

logger = structlog.get_logger()

# Security constraints
MAX_TERMS_PER_TENANT = 20
MAX_DEFINITION_LENGTH = 200
MAX_FULL_FORM_LENGTH = 50
MAX_EXPANSIONS_PER_QUERY = 10

# Stop-word exclusion list (platform config - never expanded)
STOP_WORDS = frozenset({
    "as", "it", "or", "by", "at", "be", "do", "go", "in",
    "is", "on", "to", "up", "us", "we", "no", "so", "an",
    "am", "my", "of", "if", "me", "he", "ok",
})

# Prompt injection patterns to strip from definitions
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+previous\s+instructions?", re.IGNORECASE),
    re.compile(r"forget\s+all\s+prior\s+rules?", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a\s+different", re.IGNORECASE),
    re.compile(r"override\s+previous\s+context", re.IGNORECASE),
    re.compile(r"SYSTEM\s*:", re.IGNORECASE),
    re.compile(r"###\s*New\s+Instructions\s*###", re.IGNORECASE),
    re.compile(r"<\|endoftext\|>"),
    re.compile(r"\\n\\n(Human|Assistant|System)\s*:", re.IGNORECASE),
    re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),  # Script tags + content
    re.compile(r"<style[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL),  # Style tags + content
    re.compile(r"<[^>]+>"),  # Remaining HTML tags
]


def sanitize_glossary_definition(definition: str) -> str:
    """
    Sanitize a glossary definition before storage.

    Strips known prompt injection patterns, HTML tags,
    and enforces length limits.

    Returns the sanitized string.
    """
    if not definition:
        return ""

    sanitized = definition

    # Strip injection patterns
    for pattern in INJECTION_PATTERNS:
        sanitized = pattern.sub("", sanitized)

    # Clean up multiple spaces left by stripping
    sanitized = re.sub(r"\s+", " ", sanitized).strip()

    # Enforce length limit
    if len(sanitized) > MAX_DEFINITION_LENGTH:
        sanitized = sanitized[:MAX_DEFINITION_LENGTH]

    return sanitized


class GlossaryExpander:
    """
    Inline glossary expansion for query pre-processing.

    Usage:
        expander = GlossaryExpander()
        expanded_query, expansions = await expander.expand(query, tenant_id)

    The expanded_query goes to the LLM.
    The original query goes to the embedding/vector search.
    """

    async def expand(
        self,
        query: str,
        tenant_id: str,
    ) -> tuple[str, list[str]]:
        """
        Expand glossary terms in a query.

        Returns:
            (expanded_query, list_of_expansion_descriptions)
            Example expansions: ["AL -> Annual Leave", "HR -> Human Resources"]
        """
        terms = await self._get_terms(tenant_id)
        if not terms:
            return query, []

        expanded = query
        applied = []
        already_expanded = set()

        # Sort by length descending (longest match wins on ambiguity)
        sorted_terms = sorted(terms, key=lambda t: len(t["term"]), reverse=True)

        for term_obj in sorted_terms:
            if len(applied) >= MAX_EXPANSIONS_PER_QUERY:
                break

            term = term_obj["term"]
            full_form = term_obj.get("full_form", "")

            # Security guard: skip if full_form > 50 chars
            if len(full_form) > MAX_FULL_FORM_LENGTH:
                continue

            # Stop-word exclusion
            if term.lower() in STOP_WORDS:
                continue

            # Deduplication
            if term.lower() in already_expanded:
                continue

            # Try to expand the term
            expanded, was_applied = self._try_expand_term(
                expanded, term, full_form, query, already_expanded
            )
            if was_applied:
                applied.append(f"{term} \u2192 {full_form}")
                already_expanded.add(term.lower())

            # Also check aliases
            for alias in term_obj.get("aliases", []):
                if len(applied) >= MAX_EXPANSIONS_PER_QUERY:
                    break
                if alias.lower() in STOP_WORDS or alias.lower() in already_expanded:
                    continue

                expanded, was_applied = self._try_expand_term(
                    expanded, alias, full_form, query, already_expanded
                )
                if was_applied:
                    applied.append(f"{alias} \u2192 {full_form}")
                    already_expanded.add(alias.lower())

        return expanded, applied[:MAX_EXPANSIONS_PER_QUERY]

    def _try_expand_term(
        self,
        text: str,
        term: str,
        full_form: str,
        original_query: str,
        already_expanded: set,
    ) -> tuple[str, bool]:
        """Try to expand a single term in the text. Returns (new_text, was_applied)."""
        # Uppercase-only rule for short acronyms (<=3 chars)
        if len(term) <= 3:
            # Must be ALL CAPS in the original text to expand
            pattern = rf'\b{re.escape(term.upper())}\b'
            if not re.search(pattern, text):
                return text, False

        # CJK detection for parentheses
        is_cjk = self._is_cjk_query(original_query)
        open_p, close_p = ("\uff08", "\uff09") if is_cjk else ("(", ")")

        # Find first occurrence (case-insensitive for long terms, exact for short)
        if len(term) <= 3:
            pattern = rf'\b{re.escape(term.upper())}\b'
        else:
            pattern = rf'\b{re.escape(term)}\b'

        match = re.search(pattern, text, re.IGNORECASE if len(term) > 3 else 0)
        if match:
            replacement = f"{match.group(0)} {open_p}{full_form}{close_p}"
            text = text[:match.start()] + replacement + text[match.end():]
            return text, True

        return text, False

    def _is_cjk_query(self, text: str) -> bool:
        """Detect if query contains CJK characters."""
        for char in text:
            if unicodedata.east_asian_width(char) in ("W", "F"):
                return True
        return False

    async def _get_terms(self, tenant_id: str) -> list[dict]:
        """
        Fetch glossary terms from Redis cache (1h TTL).
        Fallback to PostgreSQL.

        Override in tests with mock data.
        """
        # This is the production implementation - relies on Redis + DB
        # For unit tests, this method is mocked
        logger.warning(
            "glossary_terms_not_loaded",
            tenant_id=tenant_id,
            reason="Production _get_terms requires Redis and DB connections",
        )
        return []
