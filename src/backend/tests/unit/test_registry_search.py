"""
HAR-003: Registry search filter unit tests.

Tests all search filter variants:
- industry = ANY(industries) array match
- transaction_type = ANY(transaction_types) array match
- language = ANY(languages) array match
- kyb_level: range semantics ('verified' returns 'verified' + 'enterprise')
- q: ILIKE on name + description
- limit (max 100) and offset with total_count in response
- Sort by created_at DESC (Phase 0)
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.registry.routes import (
    _KYB_RANGE,
    list_public_agents_db,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_with_count_and_rows(count=0, rows=None):
    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar.return_value = count
    rows_result = MagicMock()
    rows_result.mappings.return_value = rows or []
    db.execute = AsyncMock(side_effect=[count_result, rows_result])
    return db


async def _call_list(**kwargs):
    defaults = dict(
        query=None,
        industry=None,
        transaction_type=None,
        language=None,
        kyb_level=None,
        min_trust_score=None,
        limit=20,
        offset=0,
    )
    defaults.update(kwargs)
    db = _db_with_count_and_rows()
    defaults["db"] = db
    result = await list_public_agents_db(**defaults)
    return db, result


# ---------------------------------------------------------------------------
# industry filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_industry_filter_adds_any_clause():
    """industry filter uses :industry = ANY(industries)."""
    db, _ = await _call_list(industry="manufacturing")
    count_call = db.execute.call_args_list[0]
    sql = str(count_call[0][0])
    params = count_call[0][1]
    assert ":industry = ANY(industries)" in sql
    assert params["industry"] == "manufacturing"


@pytest.mark.asyncio
async def test_industry_filter_absent_when_none():
    """No industry clause in SQL when industry not provided."""
    db, _ = await _call_list(industry=None)
    count_call = db.execute.call_args_list[0]
    sql = str(count_call[0][0])
    assert "industry" not in sql


# ---------------------------------------------------------------------------
# transaction_type filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transaction_type_filter_adds_any_clause():
    """transaction_type filter uses :transaction_type = ANY(transaction_types)."""
    db, _ = await _call_list(transaction_type="RFQ")
    count_call = db.execute.call_args_list[0]
    sql = str(count_call[0][0])
    params = count_call[0][1]
    assert ":transaction_type = ANY(transaction_types)" in sql
    assert params["transaction_type"] == "RFQ"


@pytest.mark.asyncio
async def test_transaction_type_filter_absent_when_none():
    """No transaction_type clause when not provided."""
    db, _ = await _call_list(transaction_type=None)
    count_call = db.execute.call_args_list[0]
    sql = str(count_call[0][0])
    assert "transaction_type" not in sql


# ---------------------------------------------------------------------------
# language filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_language_filter_adds_any_clause():
    """language filter uses :language = ANY(languages)."""
    db, _ = await _call_list(language="zh")
    count_call = db.execute.call_args_list[0]
    sql = str(count_call[0][0])
    params = count_call[0][1]
    assert ":language = ANY(languages)" in sql
    assert params["language"] == "zh"


@pytest.mark.asyncio
async def test_language_filter_absent_when_none():
    """No language clause when not provided."""
    db, _ = await _call_list(language=None)
    count_call = db.execute.call_args_list[0]
    sql = str(count_call[0][0])
    assert "language" not in sql


# ---------------------------------------------------------------------------
# KYB level range filter (HAR-003 spec)
# ---------------------------------------------------------------------------


def test_kyb_range_verified_includes_enterprise():
    """'verified' kyb_level returns both 'verified' and 'enterprise'."""
    assert "verified" in _KYB_RANGE["verified"]
    assert "enterprise" in _KYB_RANGE["verified"]


def test_kyb_range_none_includes_all():
    """'none' kyb_level returns all levels."""
    assert set(_KYB_RANGE["none"]) == {"none", "basic", "verified", "enterprise"}


def test_kyb_range_basic_excludes_none():
    """'basic' kyb_level does not include 'none'."""
    assert "none" not in _KYB_RANGE["basic"]
    assert "basic" in _KYB_RANGE["basic"]
    assert "verified" in _KYB_RANGE["basic"]
    assert "enterprise" in _KYB_RANGE["basic"]


def test_kyb_range_enterprise_is_only_enterprise():
    """'enterprise' kyb_level returns only 'enterprise'."""
    assert _KYB_RANGE["enterprise"] == ["enterprise"]


@pytest.mark.asyncio
async def test_kyb_level_filter_adds_any_cast_clause():
    """kyb_level filter uses kyb_level = ANY(CAST(:kyb_levels AS text[]))."""
    db, _ = await _call_list(kyb_level="verified")
    count_call = db.execute.call_args_list[0]
    sql = str(count_call[0][0])
    params = count_call[0][1]
    assert "kyb_level = ANY(CAST(:kyb_levels AS text[]))" in sql
    assert "verified" in params["kyb_levels"]
    assert "enterprise" in params["kyb_levels"]


@pytest.mark.asyncio
async def test_kyb_level_filter_absent_when_none():
    """No kyb_level clause when not provided."""
    db, _ = await _call_list(kyb_level=None)
    count_call = db.execute.call_args_list[0]
    sql = str(count_call[0][0])
    assert "kyb_level" not in sql


# ---------------------------------------------------------------------------
# q / text search filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q_filter_ilike_on_name_and_description():
    """q filter adds ILIKE clause on name AND description."""
    db, _ = await _call_list(query="invoice")
    count_call = db.execute.call_args_list[0]
    sql = str(count_call[0][0])
    params = count_call[0][1]
    assert "name ILIKE :query" in sql
    assert "description ILIKE :query" in sql
    assert "%invoice%" in params["query"]


@pytest.mark.asyncio
async def test_q_filter_escapes_percent():
    """q filter escapes % before wrapping in LIKE pattern."""
    db, _ = await _call_list(query="100% fast")
    count_call = db.execute.call_args_list[0]
    params = count_call[0][1]
    assert "100\\%" in params["query"]


@pytest.mark.asyncio
async def test_q_filter_escapes_underscore():
    """q filter escapes _ before wrapping in LIKE pattern."""
    db, _ = await _call_list(query="agent_v2")
    count_call = db.execute.call_args_list[0]
    params = count_call[0][1]
    assert "agent\\_v2" in params["query"]


# ---------------------------------------------------------------------------
# limit / offset / total_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_limit_offset_passed_as_params():
    """limit and offset are passed directly as SQL params."""
    db, result = await _call_list(limit=50, offset=100)
    rows_call = db.execute.call_args_list[1]
    params = rows_call[0][1]
    assert params["limit"] == 50
    assert params["offset"] == 100


@pytest.mark.asyncio
async def test_total_count_in_response():
    """Response includes total count from COUNT(*) query."""
    db = _db_with_count_and_rows(count=42)
    result = await list_public_agents_db(
        query=None,
        industry=None,
        transaction_type=None,
        language=None,
        kyb_level=None,
        min_trust_score=None,
        limit=10,
        offset=0,
        db=db,
    )
    assert result["total"] == 42


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sort_by_created_at_desc():
    """Results are sorted by created_at DESC (Phase 0 requirement)."""
    db, _ = await _call_list()
    rows_call = db.execute.call_args_list[1]
    sql = str(rows_call[0][0])
    assert "created_at DESC" in sql
    # Should NOT sort by trust_score in Phase 0
    assert "trust_score" not in sql.split("ORDER BY")[1]
