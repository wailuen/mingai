"""
ATA-023: Integration tests for guardrail enforcement.

Tests the OutputGuardrailChecker + _has_active_guardrails helper + orchestrator
audit write + persistence metadata storage.

Architecture:
  Tests 1-8 (pure logic) — no database required, no skip guard.
  Tests 9-10 (DB-dependent) — require DATABASE_URL; skipped if absent.

Run:
    pytest tests/integration/test_guardrail_enforcement.py -v --timeout=60

Pure-logic tests only (no DB):
    pytest tests/integration/test_guardrail_enforcement.py -k "not audit and not metadata" -v
"""
import asyncio
import json
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Skip guards (DB-dependent tests only)
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


# ---------------------------------------------------------------------------
# DB helpers (used by DB-dependent tests only)
# ---------------------------------------------------------------------------


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict = None):
    """Execute SQL, commit, and return the result."""
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def _fetch_one(sql: str, params: dict = None):
    """Execute SQL and return first row as a mapping (or None)."""
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            row = result.mappings().first()
            return dict(row) if row is not None else None
    finally:
        await engine.dispose()


async def _create_test_tenant() -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"Guardrail Test {tid[:8]}",
            "slug": f"guardrail-{tid[:8]}",
            "email": f"admin-{tid[:8]}@guardrail-int.test",
        },
    )
    return tid


async def _create_test_agent(tid: str, uid_placeholder: str) -> str:
    agent_id = str(uuid.uuid4())
    # created_by is nullable — use NULL to avoid FK violation against non-existent user
    await _run_sql(
        "INSERT INTO agent_cards "
        "(id, tenant_id, name, description, system_prompt, capabilities, status, version, created_by) "
        "VALUES (:id, :tid, :name, 'Integration test', 'You are a test.', "
        "'{}' ::jsonb, 'published', 1, NULL)",
        {
            "id": agent_id,
            "tid": tid,
            "name": f"Guardrail Agent {agent_id[:8]}",
        },
    )
    return agent_id


async def _create_test_conversation(tid: str, uid: str, agent_id: str) -> str:
    conv_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO conversations (id, tenant_id, user_id, agent_id, status) "
        "VALUES (:id, :tid, :uid, :agent_id, 'active')",
        {"id": conv_id, "tid": tid, "uid": uid, "agent_id": agent_id},
    )
    return conv_id


async def _cleanup_tenant(tid: str):
    tables = [
        "audit_log",
        "messages",
        "conversations",
        "agent_access_control",
        "agent_cards",
        "tenants",
    ]
    for table in tables:
        col = "tenant_id" if table != "tenants" else "id"
        # users may not exist — ignore missing rows
        await _run_sql(
            f"DELETE FROM {table} WHERE {col} = :tid", {"tid": tid}
        )


# ---------------------------------------------------------------------------
# Module fixture for DB-dependent tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_tenant():
    """Create a tenant + real user + agent once per module; clean up after all tests."""
    tid = asyncio.run(_create_test_tenant())
    uid = str(uuid.uuid4())
    # Insert a real user so FK constraints on conversations.user_id are satisfied
    asyncio.run(
        _run_sql(
            "INSERT INTO users (id, tenant_id, email, role, status) "
            "VALUES (:id, :tid, :email, 'tenant_admin', 'active')",
            {
                "id": uid,
                "tid": tid,
                "email": f"guardrail-user-{uid[:8]}@guardrail-int.test",
            },
        )
    )
    agent_id = asyncio.run(_create_test_agent(tid, uid))
    yield tid, uid, agent_id
    asyncio.run(_cleanup_tenant(tid))


# ---------------------------------------------------------------------------
# Pure-logic tests — no DB, no skip guard
# ---------------------------------------------------------------------------


class TestHasActiveGuardrails:
    """_has_active_guardrails() — pure dict predicate, no I/O."""

    def test_empty_dict_returns_false(self):
        from app.modules.chat.guardrails import _has_active_guardrails

        assert _has_active_guardrails({}) is False

    def test_zero_values_return_false(self):
        from app.modules.chat.guardrails import _has_active_guardrails

        assert (
            _has_active_guardrails(
                {"max_response_length": 0, "confidence_threshold": 0.0}
            )
            is False
        )

    def test_non_dict_returns_false(self):
        from app.modules.chat.guardrails import _has_active_guardrails

        assert _has_active_guardrails(None) is False  # type: ignore[arg-type]
        assert _has_active_guardrails("string") is False  # type: ignore[arg-type]
        assert _has_active_guardrails([]) is False  # type: ignore[arg-type]

    def test_empty_blocked_topics_list_returns_false(self):
        from app.modules.chat.guardrails import _has_active_guardrails

        assert _has_active_guardrails({"blocked_topics": []}) is False

    def test_active_blocked_topics_returns_true(self):
        from app.modules.chat.guardrails import _has_active_guardrails

        assert (
            _has_active_guardrails({"blocked_topics": ["investment advice"]}) is True
        )

    def test_active_rules_list_returns_true(self):
        from app.modules.chat.guardrails import _has_active_guardrails

        assert (
            _has_active_guardrails(
                {
                    "rules": [
                        {
                            "rule_id": "r1",
                            "rule_type": "keyword_block",
                            "patterns": ["foo"],
                        }
                    ]
                }
            )
            is True
        )

    def test_positive_confidence_threshold_returns_true(self):
        from app.modules.chat.guardrails import _has_active_guardrails

        assert _has_active_guardrails({"confidence_threshold": 0.7}) is True

    def test_positive_max_response_length_returns_true(self):
        from app.modules.chat.guardrails import _has_active_guardrails

        assert _has_active_guardrails({"max_response_length": 500}) is True


class TestOutputGuardrailChecker:
    """OutputGuardrailChecker.check() — async, pure logic, no DB."""

    def test_no_guardrails_passes(self):
        """Empty capabilities dict → every response passes."""
        from app.modules.chat.guardrails import OutputGuardrailChecker

        async def _run():
            checker = OutputGuardrailChecker({})
            result = await checker.check("This is a perfectly normal response.")
            assert result.passed is True
            assert result.action == "pass"
            assert result.filtered_text == "This is a perfectly normal response."

        asyncio.run(_run())

    def test_blocked_topic_blocks_response(self):
        """blocked_topics match → action='block', filtered_text is canned response."""
        from app.modules.chat.guardrails import OutputGuardrailChecker, _CANNED_BLOCK_RESPONSE

        async def _run():
            checker = OutputGuardrailChecker(
                {"guardrails": {"blocked_topics": ["investment advice"]}}
            )
            result = await checker.check(
                "Here is my investment advice: buy these stocks for guaranteed returns."
            )
            assert result.passed is False
            assert result.action == "block"
            assert result.filtered_text == _CANNED_BLOCK_RESPONSE
            # The original response must NOT appear in filtered_text
            assert "buy these stocks" not in (result.filtered_text or "")

        asyncio.run(_run())

    def test_blocked_topic_case_insensitive(self):
        """blocked_topics match is case-insensitive."""
        from app.modules.chat.guardrails import OutputGuardrailChecker

        async def _run():
            checker = OutputGuardrailChecker(
                {"guardrails": {"blocked_topics": ["Investment Advice"]}}
            )
            result = await checker.check(
                "This is Investment Advice you should follow."
            )
            assert result.passed is False
            assert result.action == "block"

        asyncio.run(_run())

    def test_max_length_truncates_response(self):
        """max_response_length exceeded → action='redact', truncated text returned."""
        from app.modules.chat.guardrails import OutputGuardrailChecker, _TRUNCATION_SUFFIX

        async def _run():
            long_response = "A" * 30 + " " + "B" * 30 + " " + "C" * 30
            checker = OutputGuardrailChecker(
                {"guardrails": {"max_response_length": 50}}
            )
            result = await checker.check(long_response)
            assert result.action == "redact"
            assert result.passed is True
            assert result.filtered_text is not None
            # Must end with truncation suffix
            assert result.filtered_text.endswith(_TRUNCATION_SUFFIX)
            # Must be shorter than original (50 chars + suffix length)
            assert len(result.filtered_text) <= 50 + len(_TRUNCATION_SUFFIX)

        asyncio.run(_run())

    def test_max_length_not_exceeded_passes(self):
        """Response shorter than max_response_length passes without truncation."""
        from app.modules.chat.guardrails import OutputGuardrailChecker

        async def _run():
            short_response = "Short response."
            checker = OutputGuardrailChecker(
                {"guardrails": {"max_response_length": 500}}
            )
            result = await checker.check(short_response)
            assert result.action == "pass"
            assert result.filtered_text == short_response

        asyncio.run(_run())

    def test_confidence_threshold_blocks_low_confidence(self):
        """retrieval_confidence < threshold → action='block', canned low-confidence response."""
        from app.modules.chat.guardrails import OutputGuardrailChecker, _CANNED_LOW_CONFIDENCE

        async def _run():
            checker = OutputGuardrailChecker(
                {"guardrails": {"confidence_threshold": 0.9}},
                retrieval_confidence=0.5,
            )
            result = await checker.check("This is a response to something.")
            assert result.passed is False
            assert result.action == "block"
            assert result.filtered_text == _CANNED_LOW_CONFIDENCE
            assert result.rule_id == "confidence_threshold"

        asyncio.run(_run())

    def test_confidence_threshold_allows_above_threshold(self):
        """retrieval_confidence >= threshold → response passes the confidence gate."""
        from app.modules.chat.guardrails import OutputGuardrailChecker

        async def _run():
            checker = OutputGuardrailChecker(
                {"guardrails": {"confidence_threshold": 0.6}},
                retrieval_confidence=0.85,
            )
            result = await checker.check("High confidence answer here.")
            # Should pass or at minimum not be blocked by confidence gate
            assert result.rule_id != "confidence_threshold"

        asyncio.run(_run())

    def test_keyword_block_rule_blocks_matching_response(self):
        """keyword_block rule with matching pattern → action='block'."""
        from app.modules.chat.guardrails import OutputGuardrailChecker

        async def _run():
            capabilities = {
                "guardrails": {
                    "rules": [
                        {
                            "rule_id": "no_passwords",
                            "rule_type": "keyword_block",
                            "patterns": [r"password\s*is\s*\w+"],
                            "on_violation": "block",
                        }
                    ]
                }
            }
            checker = OutputGuardrailChecker(capabilities)
            result = await checker.check(
                "Your password is Admin1234 — please change it soon."
            )
            assert result.passed is False
            assert result.action == "block"
            assert result.rule_id == "no_passwords"

        asyncio.run(_run())

    def test_fail_closed_on_internal_exception(self):
        """_check_internal raising → check() returns block result (fail-closed, no propagation)."""
        from app.modules.chat.guardrails import OutputGuardrailChecker, _CANNED_BLOCK_RESPONSE

        class _ExplodingChecker(OutputGuardrailChecker):
            async def _check_internal(self, response_text: str):
                raise RuntimeError("Simulated internal failure")

        async def _run():
            checker = _ExplodingChecker({})
            result = await checker.check("Any response text.")
            assert result.passed is False
            assert result.action == "block"
            assert result.filtered_text == _CANNED_BLOCK_RESPONSE
            assert result.rule_id == "internal_error"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# DB-dependent tests — require DATABASE_URL
# ---------------------------------------------------------------------------


class TestGuardrailAuditWrite:
    """_write_guardrail_violation_audit() writes to audit_log (requires real DB)."""

    def test_audit_inserts_row_without_original_text(self, db_tenant):
        """
        _write_guardrail_violation_audit() writes one audit_log row with
        action='guardrail_violation'. RULE A2A-01: 'original_text' key must
        NOT appear in the stored metadata.
        """
        _db_url()  # triggers skip if DATABASE_URL absent
        from app.modules.chat.orchestrator import ChatOrchestrationService

        tid, uid, agent_id = db_tenant

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as db:
                    # Set RLS context so INSERT is allowed
                    await db.execute(
                        text(
                            "SELECT set_config('app.current_tenant_id', :tid, true)"
                        ),
                        {"tid": tid},
                    )

                    svc = ChatOrchestrationService(
                        embedding_service=None,
                        vector_search_service=None,
                        profile_service=None,
                        working_memory_service=None,
                        org_context_service=None,
                        glossary_expander=None,
                        prompt_builder=None,
                        persistence_service=None,
                        confidence_calculator=None,
                        db_session=db,
                    )
                    await svc._write_guardrail_violation_audit(
                        agent_id=agent_id,
                        tenant_id=tid,
                        violation_metadata={
                            "blocked_topic": "investment advice",
                            # original_text MUST NOT be stored (RULE A2A-01) —
                            # include it here to verify the method strips it
                            "original_text": "Super secret LLM response text",
                        },
                        rule_id="blocked_topics",
                        action="block",
                    )
            finally:
                await engine.dispose()

        asyncio.run(_run())

        # Verify the row was inserted
        row = asyncio.run(
            _fetch_one(
                "SELECT action, details "
                "FROM audit_log "
                "WHERE tenant_id = :tid AND resource_type = 'agent' AND resource_id = :agent_id "
                "ORDER BY created_at DESC LIMIT 1",
                {"tid": tid, "agent_id": agent_id},
            )
        )
        assert row is not None, "audit_log row must be inserted by _write_guardrail_violation_audit"
        assert row["action"] == "guardrail_violation"

        # Deserialise details — may be a string or already a dict depending on driver
        metadata = row["details"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        assert isinstance(metadata, dict), "metadata must be a JSON object"

        # RULE A2A-01: original_text must never appear in the stored metadata
        assert "original_text" not in metadata, (
            "RULE A2A-01 violated: original_text must not be stored in audit_log metadata"
        )
        assert metadata.get("rule_id") == "blocked_topics"
        assert metadata.get("action") == "block"
        assert metadata.get("blocked_topic") == "investment advice"


class TestGuardrailViolationsInMessageMetadata:
    """save_exchange() stores guardrail_violations in message metadata (requires real DB)."""

    def test_guardrail_violations_persisted_in_message_metadata(self, db_tenant):
        """
        save_exchange() called with guardrail_violations=[...] stores that list
        in messages.metadata->>'guardrail_violations'.
        RULE A2A-01: Original blocked text is never stored.
        """
        _db_url()  # triggers skip if DATABASE_URL absent
        from app.modules.chat.persistence import ConversationPersistenceService

        tid, uid, agent_id = db_tenant

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as db:
                    # Set RLS context
                    await db.execute(
                        text(
                            "SELECT set_config('app.current_tenant_id', :tid, true)"
                        ),
                        {"tid": tid},
                    )

                    svc = ConversationPersistenceService(db_session=db)
                    msg_id, conv_id = await svc.save_exchange(
                        user_id=uid,
                        tenant_id=tid,
                        conversation_id=None,  # create new
                        query="What is the capital of France?",
                        response="The capital of France is Paris.",
                        sources=[],
                        guardrail_violations=[
                            {"rule_id": "test_rule", "action": "redact"}
                        ],
                    )
                    return msg_id, conv_id
            finally:
                await engine.dispose()

        msg_id, conv_id = asyncio.run(_run())
        assert msg_id is not None
        assert conv_id is not None

        # Verify the message metadata contains guardrail_violations
        row = asyncio.run(
            _fetch_one(
                "SELECT metadata FROM messages "
                "WHERE id = :msg_id AND tenant_id = :tid",
                {"msg_id": msg_id, "tid": tid},
            )
        )
        assert row is not None, "messages row must exist after save_exchange"
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        assert isinstance(metadata, dict)
        assert "guardrail_violations" in metadata, (
            "metadata must contain guardrail_violations key"
        )
        violations = metadata["guardrail_violations"]
        assert isinstance(violations, list)
        assert len(violations) == 1
        assert violations[0]["rule_id"] == "test_rule"
        assert violations[0]["action"] == "redact"

    def test_no_guardrail_violations_metadata_omitted(self, db_tenant):
        """
        save_exchange() called without guardrail_violations does NOT add the
        guardrail_violations key to the assistant message metadata.
        """
        _db_url()  # triggers skip if DATABASE_URL absent
        from app.modules.chat.persistence import ConversationPersistenceService

        tid, uid, agent_id = db_tenant

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as db:
                    await db.execute(
                        text(
                            "SELECT set_config('app.current_tenant_id', :tid, true)"
                        ),
                        {"tid": tid},
                    )
                    svc = ConversationPersistenceService(db_session=db)
                    msg_id, conv_id = await svc.save_exchange(
                        user_id=uid,
                        tenant_id=tid,
                        conversation_id=None,
                        query="Tell me about Paris.",
                        response="Paris is the capital of France.",
                        sources=[],
                        guardrail_violations=None,
                    )
                    return msg_id, conv_id
            finally:
                await engine.dispose()

        msg_id, _ = asyncio.run(_run())
        row = asyncio.run(
            _fetch_one(
                "SELECT metadata FROM messages "
                "WHERE id = :msg_id AND tenant_id = :tid",
                {"msg_id": msg_id, "tid": tid},
            )
        )
        assert row is not None
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        assert isinstance(metadata, dict)
        # When no violations, the key should be absent
        assert "guardrail_violations" not in metadata, (
            "guardrail_violations key must be absent when no violations occurred"
        )
