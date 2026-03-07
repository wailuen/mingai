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
import json
import re
import unicodedata

import structlog
from sqlalchemy import text

from app.core.redis_client import get_redis

logger = structlog.get_logger()

# Redis cache TTL for glossary terms: 1 hour
GLOSSARY_CACHE_TTL_SECONDS = 3600

# Security constraints
MAX_TERMS_PER_TENANT = 20
MAX_DEFINITION_LENGTH = 200
MAX_FULL_FORM_LENGTH = 50
MAX_EXPANSIONS_PER_QUERY = 10

# Stop-word exclusion list (platform config - never expanded)
STOP_WORDS = frozenset(
    {
        "as",
        "it",
        "or",
        "by",
        "at",
        "be",
        "do",
        "go",
        "in",
        "is",
        "on",
        "to",
        "up",
        "us",
        "we",
        "no",
        "so",
        "an",
        "am",
        "my",
        "of",
        "if",
        "me",
        "he",
        "ok",
    }
)

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
    re.compile(
        r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL
    ),  # Script tags + content
    re.compile(
        r"<style[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL
    ),  # Style tags + content
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
        expander = GlossaryExpander(db=session)
        expanded_query, expansions = await expander.expand(query, tenant_id)

    The expanded_query goes to the LLM.
    The original query goes to the embedding/vector search.
    """

    def __init__(self, db=None):
        """
        Initialize with optional database session.

        Args:
            db: Async database session for PostgreSQL glossary queries.
                If None (e.g., unit tests), _get_terms returns [] with a
                debug log.
        """
        self._db = db

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
            pattern = rf"\b{re.escape(term.upper())}\b"
            if not re.search(pattern, text):
                return text, False

        # CJK detection for parentheses
        is_cjk = self._is_cjk_query(original_query)
        open_p, close_p = ("\uff08", "\uff09") if is_cjk else ("(", ")")

        # Find first occurrence (case-insensitive for long terms, exact for short)
        if len(term) <= 3:
            pattern = rf"\b{re.escape(term.upper())}\b"
        else:
            pattern = rf"\b{re.escape(term)}\b"

        match = re.search(pattern, text, re.IGNORECASE if len(term) > 3 else 0)
        if match:
            replacement = f"{match.group(0)} {open_p}{full_form}{close_p}"
            text = text[: match.start()] + replacement + text[match.end() :]
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
        Falls back to PostgreSQL on cache miss.

        If no database session is configured (e.g., unit tests),
        returns [] with a debug log.
        """
        if self._db is None:
            logger.debug(
                "glossary_terms_no_db",
                tenant_id=tenant_id,
                reason="No database session configured; returning empty terms",
            )
            return []

        cache_key = f"mingai:{tenant_id}:glossary_terms"

        # Check Redis cache first
        try:
            redis = get_redis()
            cached = await redis.get(cache_key)
            if cached:
                logger.debug(
                    "glossary_terms_cache_hit",
                    tenant_id=tenant_id,
                )
                return json.loads(cached)
        except Exception as exc:
            logger.error(
                "glossary_terms_redis_error",
                tenant_id=tenant_id,
                error=str(exc),
            )

        # Cache miss -- query PostgreSQL
        try:
            result = await self._db.execute(
                text(
                    "SELECT term, full_form, aliases "
                    "FROM glossary_terms "
                    "WHERE tenant_id = :tenant_id "
                    "ORDER BY term ASC"
                ),
                {"tenant_id": tenant_id},
            )
            rows = result.fetchall()

            terms = []
            for row in rows[:MAX_TERMS_PER_TENANT]:
                aliases_raw = row[2]
                if isinstance(aliases_raw, str):
                    aliases = json.loads(aliases_raw)
                elif isinstance(aliases_raw, list):
                    aliases = aliases_raw
                else:
                    aliases = []

                terms.append(
                    {
                        "term": row[0],
                        "full_form": row[1],
                        "aliases": aliases,
                    }
                )

            # Store in Redis cache
            try:
                await redis.setex(
                    cache_key,
                    GLOSSARY_CACHE_TTL_SECONDS,
                    json.dumps(terms),
                )
                logger.debug(
                    "glossary_terms_cached",
                    tenant_id=tenant_id,
                    term_count=len(terms),
                )
            except Exception as exc:
                logger.error(
                    "glossary_terms_cache_store_error",
                    tenant_id=tenant_id,
                    error=str(exc),
                )

            return terms

        except Exception as exc:
            logger.error(
                "glossary_terms_db_error",
                tenant_id=tenant_id,
                error=str(exc),
            )
            return []


class NoopGlossaryExpander:
    """
    No-op implementation of the glossary expander interface.

    Used when the glossary_pretranslation_enabled rollout flag is False for
    a tenant. Returns the original query unchanged with an empty expansions
    list, disabling inline glossary expansion without affecting other pipeline
    stages.
    """

    async def expand(
        self,
        query: str,
        tenant_id: str,
    ) -> tuple[str, list[str]]:
        """Return the original query unchanged with no expansions."""
        return query, []
