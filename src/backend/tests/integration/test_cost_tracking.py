"""
P2LLM-018: Cost Tracking Accuracy Integration Tests.

Uses real PostgreSQL — no mocking.

Tests:
- Token count in usage_events matches actual response values
- Cost calculation within 1% of expected formula

Tier 2: Requires running PostgreSQL + JWT_SECRET_KEY configured.

Run:
    pytest tests/integration/test_cost_tracking.py -v
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _setup_tenant(tenant_id: str, plan: str = "enterprise") -> None:
    """Create test tenant row synchronously."""
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
                    "VALUES (:id, :name, :slug, :plan, :email, 'active') "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": tenant_id,
                    "name": f"Cost Test {tenant_id[:8]}",
                    "slug": f"cost-{tenant_id[:8]}",
                    "plan": plan,
                    "email": f"admin-{tenant_id[:8]}@test.example",
                },
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


def _cleanup(tenant_id: str) -> None:
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text("DELETE FROM usage_events WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await session.execute(
                text(
                    "DELETE FROM llm_library WHERE model_name LIKE 'test-cost-model-%'"
                )
            )
            await session.execute(
                text("DELETE FROM tenants WHERE id = :id"), {"id": tenant_id}
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


def _write_usage_event_direct(
    tenant_id: str,
    tokens_in: int,
    tokens_out: int,
    model: str,
    provider: str,
    model_source: str,
    cost_usd: float | None,
    latency_ms: int = 100,
) -> str:
    """Write a usage_event row directly to DB and return the row ID."""
    db_url = _db_url()
    event_id = str(uuid.uuid4())

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text(
                    "INSERT INTO usage_events ("
                    "  id, tenant_id, provider, model, tokens_in, tokens_out, "
                    "  model_source, cost_usd, latency_ms"
                    ") VALUES ("
                    "  :id, :tid, :provider, :model, :ti, :to_, "
                    "  :ms, :cost, :latency"
                    ")"
                ),
                {
                    "id": event_id,
                    "tid": tenant_id,
                    "provider": provider,
                    "model": model,
                    "ti": tokens_in,
                    "to_": tokens_out,
                    "ms": model_source,
                    "cost": str(cost_usd) if cost_usd is not None else None,
                    "latency": latency_ms,
                },
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())
    return event_id


def _read_usage_event(event_id: str) -> dict | None:
    """Read a usage_event row from DB synchronously."""
    db_url = _db_url()
    result = {}

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            r = await session.execute(
                text(
                    "SELECT id, tenant_id, provider, model, tokens_in, tokens_out, "
                    "model_source, cost_usd, latency_ms "
                    "FROM usage_events WHERE id = :id"
                ),
                {"id": event_id},
            )
            row = r.fetchone()
            if row:
                result["row"] = {
                    "id": str(row[0]),
                    "tenant_id": str(row[1]),
                    "provider": row[2],
                    "model": row[3],
                    "tokens_in": row[4],
                    "tokens_out": row[5],
                    "model_source": row[6],
                    "cost_usd": float(row[7]) if row[7] is not None else None,
                    "latency_ms": row[8],
                }
        await engine.dispose()

    asyncio.run(_do())
    return result.get("row")


async def _async_create_llm_library_entry(
    model_name: str, price_in: float, price_out: float
) -> str:
    """Insert a Published llm_library entry with known pricing (async)."""
    from app.core.session import async_session_factory

    entry_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO llm_library ("
                "  id, provider, model_name, display_name, plan_tier, "
                "  is_recommended, status, "
                "  pricing_per_1k_tokens_in, pricing_per_1k_tokens_out"
                ") VALUES ("
                "  :id, 'azure_openai', :model_name, :model_name, 'professional', "
                "  false, 'published', :price_in, :price_out"
                ")"
            ),
            {
                "id": entry_id,
                "model_name": model_name,
                "price_in": str(price_in),
                "price_out": str(price_out),
            },
        )
        await session.commit()
    return entry_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUsageEventStorage:
    """Verify usage_events table correctly stores token counts and cost."""

    @pytest.fixture(scope="class")
    def tenant_id(self):
        tid = str(uuid.uuid4())
        _setup_tenant(tid)
        yield tid
        _cleanup(tid)

    def test_usage_event_tokens_match_written_values(self, tenant_id):
        """Token counts read back from DB match what was written."""
        tokens_in = 423
        tokens_out = 187
        model = f"test-cost-model-{uuid.uuid4().hex[:8]}"

        event_id = _write_usage_event_direct(
            tenant_id=tenant_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
            provider="azure_openai",
            model_source="library",
            cost_usd=None,
        )

        row = _read_usage_event(event_id)
        assert row is not None, "Usage event not found in DB"
        assert (
            row["tokens_in"] == tokens_in
        ), f"tokens_in mismatch: expected {tokens_in}, got {row['tokens_in']}"
        assert (
            row["tokens_out"] == tokens_out
        ), f"tokens_out mismatch: expected {tokens_out}, got {row['tokens_out']}"
        assert row["tenant_id"] == tenant_id
        assert row["model"] == model

    def test_usage_event_cost_stored_correctly(self, tenant_id):
        """cost_usd is stored and retrieved accurately."""
        price_in = 0.002
        price_out = 0.004
        tokens_in = 1000
        tokens_out = 500
        expected_cost = (tokens_in / 1000 * price_in) + (tokens_out / 1000 * price_out)

        event_id = _write_usage_event_direct(
            tenant_id=tenant_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model="test-cost-calc",
            provider="azure_openai",
            model_source="library",
            cost_usd=expected_cost,
        )

        row = _read_usage_event(event_id)
        assert row is not None
        assert row["cost_usd"] is not None
        # Within 1% of expected
        assert (
            abs(row["cost_usd"] - expected_cost) / expected_cost < 0.01
        ), f"Stored cost {row['cost_usd']:.8f} differs from expected {expected_cost:.8f}"

    def test_usage_event_cost_can_be_null(self, tenant_id):
        """cost_usd=null is allowed when pricing is unavailable."""
        event_id = _write_usage_event_direct(
            tenant_id=tenant_id,
            tokens_in=100,
            tokens_out=50,
            model="unknown-model",
            provider="openai_direct",
            model_source="byollm",
            cost_usd=None,
        )

        row = _read_usage_event(event_id)
        assert row is not None
        assert row["cost_usd"] is None

    def test_usage_event_model_source_check_constraint(self, tenant_id):
        """model_source must be one of 'library' or 'byollm'."""
        db_url = _db_url()
        bad_id = str(uuid.uuid4())

        async def _try_bad_insert():
            engine = create_async_engine(db_url, echo=False)
            async_session = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with async_session() as session:
                    await session.execute(
                        text(
                            "INSERT INTO usage_events ("
                            "  id, tenant_id, provider, model, tokens_in, tokens_out, "
                            "  model_source"
                            ") VALUES ("
                            "  :id, :tid, 'azure_openai', 'gpt-4o', 10, 5, 'invalid_source'"
                            ")"
                        ),
                        {"id": bad_id, "tid": tenant_id},
                    )
                    await session.commit()
                    return False  # Should have raised
            except Exception:
                return True  # Expected constraint violation
            finally:
                await engine.dispose()

        constraint_raised = asyncio.run(_try_bad_insert())
        assert constraint_raised, "DB did not enforce model_source check constraint"


class TestCostCalculationAccuracy:
    """Verify cost formula accuracy end-to-end."""

    @pytest.fixture(scope="class")
    def tenant_id(self):
        tid = str(uuid.uuid4())
        _setup_tenant(tid)
        yield tid
        _cleanup(tid)

    @pytest.mark.asyncio
    async def test_instrumented_client_cost_within_1pct(self, tenant_id):
        """InstrumentedLLMClient._calculate_cost produces cost within 1% of formula.

        Uses real DB lookup via _get_library_pricing — no mocking.
        """
        from app.core.llm.instrumented_client import InstrumentedLLMClient

        # Create library entry with known pricing (async — already in async context)
        # Status is 'Published' so _get_library_pricing will find it via real DB query
        model_name = f"test-cost-model-{uuid.uuid4().hex[:8]}"
        price_in = 0.003
        price_out = 0.006
        await _async_create_llm_library_entry(model_name, price_in, price_out)

        client = InstrumentedLLMClient()

        tokens_in = 750
        tokens_out = 300
        expected_cost = (tokens_in / 1000 * price_in) + (tokens_out / 1000 * price_out)

        # _get_library_pricing does a real DB lookup — no mock needed
        cost = await client._calculate_cost(
            model_source="library",
            model=model_name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

        assert cost is not None, "Cost should not be None with known pricing"
        pct_diff = abs(cost - expected_cost) / expected_cost
        assert (
            pct_diff < 0.01
        ), f"Cost {cost:.8f} differs from expected {expected_cost:.8f} by {pct_diff:.2%}"
