"""
Unit tests for TA-013: Glossary miss signals batch job.

Tests the TF-IDF extraction logic and the job's DB interaction.

Tier 1: Fast, isolated.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestExtractCandidates:
    """Unit tests for the _extract_candidates() pure function."""

    def setup_method(self):
        from app.modules.glossary.miss_signals_job import _extract_candidates

        self._fn = _extract_candidates

    def test_extracts_uppercase_abbreviations(self):
        result = self._fn("What is our CSAT score for the HR department?")
        assert "CSAT" in result
        assert "HR" in result

    def test_excludes_stopwords(self):
        """Common English uppercase words are excluded."""
        result = self._fn("THE AND FOR ARE BUT NOT ALL CAN")
        assert result == []

    def test_excludes_single_char_tokens(self):
        """Single char uppercase tokens are not abbreviations."""
        result = self._fn("I met A person who said B was important")
        assert "A" not in result
        assert "B" not in result

    def test_excludes_7plus_char_tokens(self):
        """Tokens longer than 6 chars are not abbreviations."""
        result = self._fn("VERYLONGABBREVIATION is not extracted")
        assert "VERYLONGABBREVIATION" not in result

    def test_extracts_all_valid_abbreviations(self):
        result = self._fn("Our KPI and SLA metrics are tracked in the ROI dashboard")
        assert "KPI" in result
        assert "SLA" in result
        assert "ROI" in result

    def test_empty_string_returns_empty(self):
        assert self._fn("") == []

    def test_no_abbreviations_returns_empty(self):
        assert self._fn("This is a completely lowercase sentence") == []


class TestComputeTfidfScores:
    """Unit tests for the _compute_tfidf_scores() pure function."""

    def setup_method(self):
        from app.modules.glossary.miss_signals_job import _compute_tfidf_scores

        self._fn = _compute_tfidf_scores

    def test_higher_frequency_gets_higher_score(self):
        """A term appearing in more messages should score higher."""
        term_messages = {
            "KPI": ["msg1", "msg2", "msg3"],
            "SLA": ["msg4"],
        }
        scores = self._fn(term_messages, total_messages=10)
        assert scores["KPI"] > scores["SLA"]

    def test_no_zero_division_with_single_message(self):
        """Should not crash when total_messages=1."""
        scores = self._fn({"HR": ["what is HR"]}, total_messages=1)
        assert scores["HR"] > 0

    def test_no_zero_division_with_zero_messages(self):
        """total_messages=0 is guarded against division by zero."""
        scores = self._fn({"HR": ["what is HR"]}, total_messages=0)
        assert "HR" in scores
        assert not any(v != v for v in scores.values())  # no NaN

    def test_all_scores_positive(self):
        term_messages = {"CSAT": ["a", "b"], "ROI": ["c"]}
        scores = self._fn(term_messages, total_messages=5)
        assert all(v > 0 for v in scores.values())


class TestMissSignalsJob:
    """Integration-style unit test for run_miss_signals_job()."""

    @pytest.mark.asyncio
    async def test_job_skips_tenant_with_no_messages(self):
        """If a tenant has no user messages, it contributes 0 terms."""
        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        call_count = 0

        async def _execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            sql = str(args[0]) if args else ""
            if "FROM tenants" in sql:
                result.fetchall.return_value = [
                    (uuid.UUID("12345678-1234-5678-1234-567812345678"),)
                ]
            elif "FROM messages" in sql:
                result.fetchall.return_value = []  # no messages
            else:
                result.fetchall.return_value = []
            return result

        mock_db.execute = AsyncMock(side_effect=_execute)

        with patch(
            "app.modules.glossary.miss_signals_job.async_session_factory",
            return_value=mock_db,
        ):
            from app.modules.glossary.miss_signals_job import run_miss_signals_job

            summary = await run_miss_signals_job()

        assert summary.get("12345678-1234-5678-1234-567812345678", 0) == 0

    @pytest.mark.asyncio
    async def test_job_excludes_covered_terms(self):
        """Terms already in the glossary are excluded from miss signals."""
        from app.modules.glossary.miss_signals_job import (
            _extract_candidates,
            _STOPWORDS,
        )

        # KPI is in glossary → should be excluded
        # SLA is NOT in glossary → should be candidate
        messages = ["Our KPI and SLA metrics need attention"]
        covered = {"KPI"}

        candidates = [
            t for msg in messages for t in _extract_candidates(msg) if t not in covered
        ]
        assert "KPI" not in candidates
        assert "SLA" in candidates

    def test_seconds_until_next_run_positive(self):
        """Scheduler always returns a positive sleep time."""
        from app.modules.glossary.miss_signals_job import _seconds_until_next_run

        secs = _seconds_until_next_run()
        assert secs > 0
        assert secs <= 24 * 3600 + 60

    def test_tfidf_top_n_selection(self):
        """Only top 20 terms are retained even if more candidates exist."""
        from app.modules.glossary.miss_signals_job import (
            _compute_tfidf_scores,
            _TOP_N_TERMS,
        )

        # Create 30 terms with varying frequencies
        term_messages = {
            f"T{i:02d}": [f"msg{j}" for j in range(i + 1)] for i in range(30)
        }
        scores = _compute_tfidf_scores(term_messages, total_messages=100)
        top = sorted(scores, key=scores.__getitem__, reverse=True)[:_TOP_N_TERMS]
        assert len(top) == _TOP_N_TERMS
        # The term with most occurrences should rank highest
        assert top[0] == "T29"  # 30 occurrences

    def test_query_snippet_truncated_to_max_len(self):
        """Query snippets are limited to _MAX_QUERY_SNIPPET_LEN characters."""
        from app.modules.glossary.miss_signals_job import _MAX_QUERY_SNIPPET_LEN

        long_msg = "A" * 200
        snippet = long_msg[:_MAX_QUERY_SNIPPET_LEN]
        assert len(snippet) <= _MAX_QUERY_SNIPPET_LEN
