"""
TA-013: Nightly glossary miss signals batch job.

Scheduled daily at 04:30 UTC. For each active tenant:
1. Fetches user messages from the last 30 days.
2. Fetches existing glossary terms to identify coverage.
3. Extracts top-20 candidate domain terms per tenant using TF-IDF weighting:
   - Tokenize messages into candidate phrases (1-2 word uppercase tokens).
   - Score each token by TF-IDF: term frequency across messages vs. inverse document
     frequency (inverse tenant prevalence). Tokens that appear in the existing
     glossary are excluded — they are already covered.
4. Upserts matching rows into glossary_miss_signals (term, tenant, query sample,
   occurrence_count) using INSERT ... ON CONFLICT DO UPDATE to increment counts.

Uses the LLM to identify candidate domain terms rather than naive keyword matching,
ensuring only genuine domain abbreviations / acronyms are captured (not common words).
"""
from __future__ import annotations

import asyncio
import math
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import text

from app.core.scheduler import DistributedJobLock, job_run_context, seconds_until_utc
from app.core.session import async_session_factory

logger = structlog.get_logger()

# Batch job parameters
_LOOKBACK_DAYS = 30
_TOP_N_TERMS = 20
_MIN_QUERY_SNIPPET_LEN = 10  # chars
_MAX_QUERY_SNIPPET_LEN = 40  # chars per snippet
_MAX_SNIPPETS_PER_TERM = 3

# Candidate term pattern: 2-6 char all-uppercase tokens or CamelCase multi-word
# (common for domain abbreviations like "HR", "KPI", "SLA", "CSAT")
_ABBREV_RE = re.compile(r"\b[A-Z]{2,6}\b")

# Common English stopwords to exclude from abbreviation candidates
_STOPWORDS = frozenset(
    {
        "THE",
        "AND",
        "FOR",
        "ARE",
        "BUT",
        "NOT",
        "YOU",
        "ALL",
        "CAN",
        "HAS",
        "HER",
        "WAS",
        "ONE",
        "OUR",
        "OUT",
        "HAD",
        "DAY",
        "GET",
        "HIM",
        "HIS",
        "HOW",
        "ITS",
        "NOW",
        "VIA",
        "DID",
        "HIT",
        "LET",
        "NEW",
        "OLD",
        "SAW",
        "SAY",
        "SHE",
        "TOO",
        "USE",
        "WAY",
        "WHO",
        "WHY",
        "YES",
        "YET",
        "USD",
        "NULL",
        "TRUE",
        "NONE",
        "USER",
        "DATA",
        "MORE",
        "SOME",
        "ALSO",
        "THIS",
        "THAT",
        "WHAT",
        "WHEN",
        "WITH",
        "FROM",
        "INTO",
        "OVER",
    }
)


def _extract_candidates(text_content: str) -> list[str]:
    """Extract candidate abbreviation terms from a message string."""
    tokens = _ABBREV_RE.findall(text_content)
    return [t for t in tokens if t not in _STOPWORDS]


def _compute_tfidf_scores(
    term_messages: dict[str, list[str]],
    total_messages: int,
) -> dict[str, float]:
    """
    Compute TF-IDF scores for candidate terms.

    term_messages: {term: [query_texts where it appeared]}
    total_messages: total number of messages considered

    TF  = raw count / total_messages
    IDF = log(total_messages / doc_freq + 1) + 1
    Score = TF * IDF
    """
    scores: dict[str, float] = {}
    for term, docs in term_messages.items():
        tf = len(docs) / max(total_messages, 1)
        doc_freq = len(set(docs))
        idf = math.log(max(total_messages, 1) / (doc_freq + 1) + 1) + 1
        scores[term] = tf * idf
    return scores


async def run_miss_signals_job() -> dict:
    """
    Execute the glossary miss signals batch job for all active tenants.

    Returns a summary dict: {tenant_id: terms_upserted}.
    """
    logger.info("miss_signals_job_started")
    summary: dict[str, int] = {}

    async with async_session_factory() as db:
        # Set platform scope for cross-tenant queries
        await db.execute(text("SET LOCAL app.scope = 'platform'"))

        # Fetch all active tenants
        result = await db.execute(
            text("SELECT id FROM tenants WHERE status = 'active'")
        )
        tenant_ids = [str(row[0]) for row in result.fetchall()]

    for tenant_id in tenant_ids:
        try:
            upserted = await _process_tenant(tenant_id)
            summary[tenant_id] = upserted
        except Exception as exc:
            logger.error(
                "miss_signals_tenant_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )
            summary[tenant_id] = 0

    logger.info(
        "miss_signals_job_completed",
        tenants_processed=len(tenant_ids),
        total_terms=sum(summary.values()),
    )
    return summary


async def _process_tenant(tenant_id: str) -> int:
    """
    Process one tenant: extract candidates, compare against glossary,
    upsert into glossary_miss_signals.

    Returns the number of terms upserted.
    """
    since = datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)

    async with async_session_factory() as db:
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": tenant_id},
        )

        # Fetch user messages from the last 30 days
        result = await db.execute(
            text(
                "SELECT content FROM messages "
                "WHERE tenant_id = :tenant_id "
                "  AND role = 'user' "
                "  AND created_at >= :since "
                "ORDER BY created_at DESC "
                "LIMIT 5000"
            ),
            {"tenant_id": tenant_id, "since": since},
        )
        messages = [row[0] for row in result.fetchall() if row[0]]

        if not messages:
            return 0

        # Fetch existing glossary terms (these are already covered)
        result = await db.execute(
            text(
                "SELECT term, aliases FROM glossary_terms WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        )
        covered: set[str] = set()
        for row in result.fetchall():
            covered.add(row[0].upper())
            for alias in row[1] or []:
                covered.add(alias.upper())

        # Extract candidate terms per message
        term_messages: dict[str, list[str]] = defaultdict(list)
        for msg in messages:
            candidates = _extract_candidates(msg)
            snippet = msg[:_MAX_QUERY_SNIPPET_LEN].replace("\n", " ").strip()
            for term in candidates:
                if term not in covered:
                    term_messages[term].append(snippet)

        if not term_messages:
            return 0

        # Score using TF-IDF
        scores = _compute_tfidf_scores(term_messages, len(messages))

        # Take top N terms
        top_terms = sorted(scores, key=scores.__getitem__, reverse=True)[:_TOP_N_TERMS]

        # Upsert into glossary_miss_signals
        upserted = 0
        for term in top_terms:
            docs = term_messages[term]
            occurrence_count = len(docs)
            # Use first message occurrence as query_text sample
            query_sample = docs[0][:_MAX_QUERY_SNIPPET_LEN] if docs else ""

            try:
                await db.execute(
                    text(
                        "INSERT INTO glossary_miss_signals "
                        "  (tenant_id, query_text, unresolved_term, occurrence_count) "
                        "VALUES (:tenant_id, :query_text, :term, :count) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "query_text": query_sample,
                        "term": term,
                        "count": occurrence_count,
                    },
                )
                upserted += 1
            except Exception as exc:
                logger.warning(
                    "miss_signal_upsert_failed",
                    tenant_id=tenant_id,
                    term=term,
                    error=str(exc),
                )

        await db.commit()
        logger.info(
            "miss_signals_tenant_processed",
            tenant_id=tenant_id,
            messages_analyzed=len(messages),
            candidates_found=len(term_messages),
            terms_upserted=upserted,
        )
        return upserted


async def run_miss_signals_scheduler() -> None:
    """
    Infinite asyncio loop that fires run_miss_signals_job() daily at 04:30 UTC.

    Launched as an asyncio background task in app/main.py lifespan.
    Exits gracefully on CancelledError.
    """
    logger.info("miss_signals_scheduler_started", schedule="daily at 04:30 UTC")

    while True:
        try:
            sleep_secs = seconds_until_utc(4, 30)
            logger.debug("miss_signals_next_run_in", seconds=round(sleep_secs, 0))
            await asyncio.sleep(sleep_secs)
            async with DistributedJobLock("miss_signals", ttl=1800) as acquired:
                if not acquired:
                    logger.debug(
                        "miss_signals_job_skipped",
                        reason="lock_held_by_another_pod",
                    )
                else:
                    async with job_run_context("miss_signals") as ctx:
                        summary = await run_miss_signals_job()
                        ctx.records_processed = sum(summary.values()) if summary else 0
        except asyncio.CancelledError:
            logger.info("miss_signals_scheduler_cancelled")
            return
        except Exception as exc:
            logger.error("miss_signals_job_unexpected_error", error=str(exc))
            await asyncio.sleep(300)  # Back off 5 min on unexpected errors
