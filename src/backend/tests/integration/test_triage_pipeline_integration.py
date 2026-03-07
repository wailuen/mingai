"""
TEST-019: Full Triage Pipeline Integration Test

End-to-end pipeline test: issue submit → Redis Stream publish → worker process → DB update.

Uses real PostgreSQL and real Redis. Mocks only the LLM-backed IssueTriageAgent
(Tier 2: real infrastructure, external AI service mocked).

Test sequence:
1. Insert a test tenant + user + issue_report row in PostgreSQL.
2. Publish the report to the Redis Stream.
3. Call process_message() directly with the stream payload and a real DB session.
4. Assert that the issue_report status was updated correctly in PostgreSQL.
5. Cleanup all test data.

Tier 2: Real DB + Real Redis — no mocking of infrastructure.

Run:
    pytest tests/integration/test_triage_pipeline_integration.py -v -m integration
"""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Infrastructure helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping pipeline integration tests")
    return url


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        pytest.skip("REDIS_URL not configured — skipping pipeline integration tests")
    return url


@pytest_asyncio.fixture
async def db_session():
    """
    Per-test async DB session.

    Creates a fresh engine per test to avoid asyncpg's 'Future attached to a
    different loop' error that occurs when module-scoped engines are reused
    across pytest-asyncio's per-test event loops.
    """
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def redis_conn():
    """Real async Redis connection."""
    import redis.asyncio as aioredis

    r = aioredis.from_url(_redis_url(), decode_responses=True)
    yield r
    await r.aclose()


# ---------------------------------------------------------------------------
# Test data factory
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pipeline_test_data(db_session):
    """
    Insert a minimal tenant + user + issue_report for pipeline testing.
    Returns a dict of IDs. Cleans up after each test.
    """
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())

    # Insert tenant
    await db_session.execute(
        text(
            "INSERT INTO tenants (id, name, slug, plan, status, primary_contact_email) "
            "VALUES (:id, :name, :slug, 'professional', 'active', :email)"
        ),
        {
            "id": tenant_id,
            "name": f"Pipeline Test Tenant {tenant_id[:8]}",
            "slug": f"pipeline-test-{tenant_id[:8]}",
            "email": f"admin@pipeline-{tenant_id[:8]}.test",
        },
    )

    # Insert user
    await db_session.execute(
        text(
            "INSERT INTO users (id, tenant_id, email, name, role, status) "
            "VALUES (:id, :tenant_id, :email, 'Test User', 'user', 'active')"
        ),
        {
            "id": user_id,
            "tenant_id": tenant_id,
            "email": f"user@pipeline-{tenant_id[:8]}.test",
        },
    )

    # Insert issue report (status starts as 'open')
    await db_session.execute(
        text(
            "INSERT INTO issue_reports "
            "(id, tenant_id, reporter_id, issue_type, description, severity, status, blur_acknowledged) "
            "VALUES (:id, :tenant_id, :reporter_id, :issue_type, :description, 'medium', 'open', false)"
        ),
        {
            "id": report_id,
            "tenant_id": tenant_id,
            "reporter_id": user_id,
            "issue_type": "bug",
            "description": "Login button crashes the app on Safari when using dark mode.",
        },
    )
    await db_session.commit()

    yield {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "report_id": report_id,
    }

    # Cleanup — delete in FK-safe order
    await db_session.execute(
        text("DELETE FROM issue_reports WHERE id = :id"), {"id": report_id}
    )
    await db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    await db_session.execute(
        text("DELETE FROM tenants WHERE id = :id"), {"id": tenant_id}
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestTriagePipelineFeatureRoute:
    """Feature requests route to product_backlog without invoking triage agent."""

    async def test_feature_issue_routed_to_product_backlog(
        self, pipeline_test_data, db_session, redis_conn
    ):
        """
        Feature-type messages must set status='product_backlog' and NOT call
        IssueTriageAgent — verified by asserting the mock was never invoked.
        """
        from app.modules.issues.worker import process_message

        report_id = pipeline_test_data["report_id"]
        tenant_id = pipeline_test_data["tenant_id"]

        # Override the issue_type to 'feature' for this test
        await db_session.execute(
            text(
                "UPDATE issue_reports SET issue_type = 'feature' "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"id": report_id, "tenant_id": tenant_id},
        )
        await db_session.commit()

        fields = {
            "report_id": report_id,
            "tenant_id": tenant_id,
            "issue_type": "feature",
            "severity_hint": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with patch("app.modules.issues.worker.IssueTriageAgent") as MockAgent:
            await process_message(
                msg_id="1678900000000-0",
                fields=fields,
                db_session=db_session,
                redis=redis_conn,
            )
            # Triage agent must NOT be invoked for feature requests
            MockAgent.return_value.triage.assert_not_called()

        # Verify status updated in real DB
        result = await db_session.execute(
            text(
                "SELECT status FROM issue_reports WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"id": report_id, "tenant_id": tenant_id},
        )
        row = result.fetchone()
        assert row is not None, "Issue report must still exist after processing"
        assert (
            row[0] == "product_backlog"
        ), f"Expected status='product_backlog' but got '{row[0]}'"


@pytest.mark.integration
@pytest.mark.asyncio
class TestTriagePipelineBugRoute:
    """Bug-type issues invoke triage agent and persist the result."""

    async def test_bug_issue_triaged_and_status_updated_in_db(
        self, pipeline_test_data, db_session, redis_conn
    ):
        """
        Bug-type messages must:
        1. Set status='triaging' before agent call.
        2. Invoke IssueTriageAgent.triage() with correct arguments.
        3. Set status='triaged' in real PostgreSQL after successful triage.
        """
        from app.modules.issues.triage_agent import TriageResult
        from app.modules.issues.worker import process_message

        report_id = pipeline_test_data["report_id"]
        tenant_id = pipeline_test_data["tenant_id"]

        mock_triage_result = TriageResult(
            issue_type="ui_bug",
            severity="P2",
            confidence=0.91,
            routing="engineering",
            reasoning="Dark mode rendering issue on Safari — CSS variable not applied.",
        )

        fields = {
            "report_id": report_id,
            "tenant_id": tenant_id,
            "issue_type": "bug",
            "severity_hint": "P2",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with patch("app.modules.issues.worker.IssueTriageAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.triage.return_value = mock_triage_result
            MockAgent.return_value = mock_instance

            await process_message(
                msg_id="1678900000001-0",
                fields=fields,
                db_session=db_session,
                redis=redis_conn,
            )

            # Triage MUST be called
            mock_instance.triage.assert_called_once()

            # Called with the correct tenant_id
            call_kwargs = mock_instance.triage.call_args[1]
            assert call_kwargs.get("tenant_id") == tenant_id

        # Verify final status in real DB
        result = await db_session.execute(
            text(
                "SELECT status FROM issue_reports WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"id": report_id, "tenant_id": tenant_id},
        )
        row = result.fetchone()
        assert row is not None
        assert (
            row[0] == "triaged"
        ), f"Expected status='triaged' after successful triage but got '{row[0]}'"


@pytest.mark.integration
@pytest.mark.asyncio
class TestTriagePipelineStreamPublishAndConsume:
    """Full publish → process cycle using real Redis stream."""

    async def test_publish_then_process_message_end_to_end(
        self, pipeline_test_data, db_session, redis_conn
    ):
        """
        Complete pipeline: publish_issue_to_stream → message appears in stream →
        process_message with real DB session updates issue status.
        """
        from app.modules.issues.stream import (
            STREAM_KEY,
            ensure_stream_group,
            publish_issue_to_stream,
        )
        from app.modules.issues.triage_agent import TriageResult
        from app.modules.issues.worker import process_message

        report_id = pipeline_test_data["report_id"]
        tenant_id = pipeline_test_data["tenant_id"]

        # Step 1: Ensure the consumer group exists in real Redis
        await ensure_stream_group(redis_conn)

        # Step 2: Publish the issue to real Redis Stream
        entry_id = await publish_issue_to_stream(
            report_id=report_id,
            tenant_id=tenant_id,
            issue_type="bug",
            severity_hint="P2",
            redis=redis_conn,
        )
        assert isinstance(entry_id, str)
        assert "-" in entry_id, "entry_id must be a valid Redis stream ID"

        # Step 3: Verify the message was written to the stream
        messages = await redis_conn.xrange(STREAM_KEY, min=entry_id, max=entry_id)
        assert len(messages) == 1, "Message must appear in stream"
        msg_id, fields = messages[0]
        assert fields["report_id"] == report_id
        assert fields["tenant_id"] == tenant_id

        # Step 4: Process the message with real DB session (mock LLM only)
        mock_result = TriageResult(
            issue_type="ui_bug",
            severity="P2",
            confidence=0.88,
            routing="engineering",
            reasoning="Reproduces on Safari with dark mode OS setting.",
        )

        with patch("app.modules.issues.worker.IssueTriageAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.triage.return_value = mock_result
            MockAgent.return_value = mock_instance

            await process_message(
                msg_id=msg_id,
                fields=fields,
                db_session=db_session,
                redis=redis_conn,
            )

        # Step 5: Verify issue status is 'triaged' in real PostgreSQL
        result = await db_session.execute(
            text(
                "SELECT status FROM issue_reports "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"id": report_id, "tenant_id": tenant_id},
        )
        row = result.fetchone()
        assert row is not None
        assert (
            row[0] == "triaged"
        ), f"Full pipeline must update status to 'triaged' in DB but got '{row[0]}'"

    async def test_missing_report_id_in_stream_message_is_handled_gracefully(
        self, db_session, redis_conn
    ):
        """
        process_message with an empty report_id logs an error and returns without
        crashing — stream consumer must not be blocked by malformed messages.
        """
        from app.modules.issues.worker import process_message

        # Malformed message: report_id missing
        fields = {
            "report_id": "",
            "tenant_id": str(uuid.uuid4()),
            "issue_type": "bug",
            "severity_hint": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Must not raise — worker loop must continue after bad messages
        await process_message(
            msg_id="0-0",
            fields=fields,
            db_session=db_session,
            redis=redis_conn,
        )

    async def test_nonexistent_report_id_is_handled_gracefully(
        self, db_session, redis_conn
    ):
        """
        process_message for a report_id that doesn't exist in DB logs a warning
        and returns without error — prevents phantom stream messages from crashing worker.
        """
        from app.modules.issues.worker import process_message

        fields = {
            "report_id": str(uuid.uuid4()),  # Random UUID, not in DB
            "tenant_id": str(uuid.uuid4()),
            "issue_type": "bug",
            "severity_hint": "P1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Must not raise
        await process_message(
            msg_id="0-1",
            fields=fields,
            db_session=db_session,
            redis=redis_conn,
        )
