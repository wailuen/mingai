"""
TEST-INFRA-049: Database connection pool RLS context injection — unit tests.

Coverage target: 100% of session.py RLS logic (Tier 1 — fully mocked).

Tests:
- set_rls_context() correctly writes to the ContextVar
- get_rls_context() returns the value set by set_rls_context()
- RLS values are isolated per async task (contextvars semantics)
- get_db_with_rls() calls SET LOCAL with valid tenant_id / scope
- Injection attempts (semicolons, quotes, arbitrary strings) are rejected
- Reserved tenant IDs ("default", "platform", "") are accepted
- Invalid scope values are rejected
- Empty tenant_id skips RLS injection (exempt paths)
- get_db() reads request.state correctly and routes to get_db_with_rls()
- get_db() falls back gracefully when request is None
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# _validate_rls_tenant_id
# ---------------------------------------------------------------------------


class TestValidateRlsTenantId:
    """_validate_rls_tenant_id enforces the UUID / reserved-word allowlist."""

    def test_valid_uuid_accepted(self):
        from app.core.session import _validate_rls_tenant_id

        tid = _make_valid_uuid()
        assert _validate_rls_tenant_id(tid) == tid

    def test_empty_string_accepted(self):
        from app.core.session import _validate_rls_tenant_id

        assert _validate_rls_tenant_id("") == ""

    def test_reserved_default_accepted(self):
        from app.core.session import _validate_rls_tenant_id

        assert _validate_rls_tenant_id("default") == "default"

    def test_reserved_platform_accepted(self):
        from app.core.session import _validate_rls_tenant_id

        assert _validate_rls_tenant_id("platform") == "platform"

    def test_semicolon_injection_rejected(self):
        from app.core.session import _validate_rls_tenant_id

        with pytest.raises(ValueError, match="Invalid tenant_id"):
            _validate_rls_tenant_id("'; DROP TABLE users; --")

    def test_quote_injection_rejected(self):
        from app.core.session import _validate_rls_tenant_id

        with pytest.raises(ValueError, match="Invalid tenant_id"):
            _validate_rls_tenant_id("abc'xyz")

    def test_sql_or_clause_rejected(self):
        from app.core.session import _validate_rls_tenant_id

        with pytest.raises(ValueError, match="Invalid tenant_id"):
            _validate_rls_tenant_id("1 OR 1=1")

    def test_newline_injection_rejected(self):
        from app.core.session import _validate_rls_tenant_id

        with pytest.raises(ValueError, match="Invalid tenant_id"):
            _validate_rls_tenant_id("abc\nSET LOCAL role='pg_superuser'")

    def test_arbitrary_string_rejected(self):
        from app.core.session import _validate_rls_tenant_id

        with pytest.raises(ValueError, match="Invalid tenant_id"):
            _validate_rls_tenant_id("not-a-uuid-at-all")

    def test_uuid_with_uppercase_rejected(self):
        """UUIDs must be lowercase hex per the regex — uppercase is rejected."""
        from app.core.session import _validate_rls_tenant_id

        upper = _make_valid_uuid().upper()
        with pytest.raises(ValueError, match="Invalid tenant_id"):
            _validate_rls_tenant_id(upper)

    def test_path_traversal_rejected(self):
        from app.core.session import _validate_rls_tenant_id

        with pytest.raises(ValueError, match="Invalid tenant_id"):
            _validate_rls_tenant_id("../../etc/passwd")


# ---------------------------------------------------------------------------
# _validate_rls_scope
# ---------------------------------------------------------------------------


class TestValidateRlsScope:
    """_validate_rls_scope enforces the explicit scope allowlist."""

    def test_tenant_scope_accepted(self):
        from app.core.session import _validate_rls_scope

        assert _validate_rls_scope("tenant") == "tenant"

    def test_platform_scope_accepted(self):
        from app.core.session import _validate_rls_scope

        assert _validate_rls_scope("platform") == "platform"

    def test_empty_scope_accepted(self):
        from app.core.session import _validate_rls_scope

        assert _validate_rls_scope("") == ""

    def test_arbitrary_scope_rejected(self):
        from app.core.session import _validate_rls_scope

        with pytest.raises(ValueError, match="Invalid scope"):
            _validate_rls_scope("superuser")

    def test_injection_scope_rejected(self):
        from app.core.session import _validate_rls_scope

        with pytest.raises(ValueError, match="Invalid scope"):
            _validate_rls_scope("tenant'; DROP TABLE users; --")


# ---------------------------------------------------------------------------
# set_rls_context / get_rls_context
# ---------------------------------------------------------------------------


class TestSetRlsContext:
    """set_rls_context() / get_rls_context() ContextVar semantics."""

    def test_set_valid_uuid_tenant(self):
        from app.core.session import get_rls_context, set_rls_context

        tid = _make_valid_uuid()
        set_rls_context(tid, "tenant")
        ctx = get_rls_context()
        assert ctx["tenant_id"] == tid
        assert ctx["scope"] == "tenant"

    def test_set_platform_scope(self):
        from app.core.session import get_rls_context, set_rls_context

        set_rls_context("platform", "platform")
        ctx = get_rls_context()
        assert ctx["tenant_id"] == "platform"
        assert ctx["scope"] == "platform"

    def test_set_empty_string_for_exempt_path(self):
        from app.core.session import get_rls_context, set_rls_context

        set_rls_context("", "")
        ctx = get_rls_context()
        assert ctx["tenant_id"] == ""
        assert ctx["scope"] == ""

    def test_set_context_rejects_invalid_tenant_id(self):
        from app.core.session import set_rls_context

        with pytest.raises(ValueError, match="Invalid tenant_id"):
            set_rls_context("bad; value", "tenant")

    def test_set_context_rejects_invalid_scope(self):
        from app.core.session import set_rls_context

        with pytest.raises(ValueError, match="Invalid scope"):
            set_rls_context(_make_valid_uuid(), "root")

    def test_contextvars_isolated_between_tasks(self):
        """Two asyncio tasks must not share each other's RLS context."""
        from app.core.session import get_rls_context, set_rls_context

        tid_a = _make_valid_uuid()
        tid_b = _make_valid_uuid()

        results: dict[str, str] = {}

        async def task_a() -> None:
            set_rls_context(tid_a, "tenant")
            await asyncio.sleep(0)  # yield to task_b
            results["a"] = get_rls_context()["tenant_id"]

        async def task_b() -> None:
            set_rls_context(tid_b, "tenant")
            await asyncio.sleep(0)
            results["b"] = get_rls_context()["tenant_id"]

        async def run() -> None:
            await asyncio.gather(task_a(), task_b())

        asyncio.run(run())
        assert results["a"] == tid_a
        assert results["b"] == tid_b
        assert results["a"] != results["b"]


# ---------------------------------------------------------------------------
# get_db_with_rls — mocked session, verifies SET LOCAL is called
# ---------------------------------------------------------------------------


class TestGetDbWithRls:
    """get_db_with_rls() injects SET LOCAL calls into the session."""

    @pytest.mark.asyncio
    async def test_injects_set_local_for_valid_tenant(self):
        """SET LOCAL is called with the validated tenant_id and scope."""
        from app.core.session import get_db_with_rls

        tid = _make_valid_uuid()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.session.async_session_factory", return_value=mock_cm):
            async with get_db_with_rls(tid, "tenant") as session:
                assert session is mock_session

        # Verify SET LOCAL was issued
        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        # The SQL text contains set_config calls
        sql_str = str(call_args[0][0])
        assert "set_config" in sql_str
        # The params dict carries tid and scope
        params = call_args[0][1]
        assert params["tid"] == tid
        assert params["scope"] == "tenant"

    @pytest.mark.asyncio
    async def test_skips_set_local_for_empty_tenant_id(self):
        """Empty tenant_id (exempt path) must NOT issue SET LOCAL."""
        from app.core.session import get_db_with_rls

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.session.async_session_factory", return_value=mock_cm):
            async with get_db_with_rls("", "") as session:
                assert session is mock_session

        # No execute call should have been made for the RLS SET
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_rollback_on_exception(self):
        """Session is rolled back when the body raises."""
        from app.core.session import get_db_with_rls

        tid = _make_valid_uuid()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.session.async_session_factory", return_value=mock_cm):
            with pytest.raises(RuntimeError):
                async with get_db_with_rls(tid, "tenant"):
                    raise RuntimeError("body error")

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_injection_attempt(self):
        """ValueError raised before any DB call for invalid tenant_id."""
        from app.core.session import get_db_with_rls

        with pytest.raises(ValueError, match="Invalid tenant_id"):
            async with get_db_with_rls("'; DROP TABLE users; --", "tenant"):
                pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_reserved_default_tenant_injects_rls(self):
        """'default' is a valid reserved tenant_id and triggers RLS injection."""
        from app.core.session import get_db_with_rls

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.session.async_session_factory", return_value=mock_cm):
            async with get_db_with_rls("default", "tenant") as session:
                assert session is mock_session

        # "default" is non-empty, so SET LOCAL must be issued
        mock_session.execute.assert_called_once()
        params = mock_session.execute.call_args[0][1]
        assert params["tid"] == "default"

    @pytest.mark.asyncio
    async def test_platform_scope_injects_rls(self):
        """Platform-scoped sessions inject RLS with scope='platform'."""
        from app.core.session import get_db_with_rls

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.session.async_session_factory", return_value=mock_cm):
            async with get_db_with_rls("platform", "platform") as session:
                assert session is mock_session

        params = mock_session.execute.call_args[0][1]
        assert params["scope"] == "platform"


# ---------------------------------------------------------------------------
# get_db() FastAPI dependency
# ---------------------------------------------------------------------------


class TestGetDbDependency:
    """get_db() reads request.state and delegates to get_db_with_rls()."""

    @pytest.mark.asyncio
    async def test_reads_tenant_from_request_state(self):
        """get_db() extracts tenant_id/scope from request.state."""
        from app.core.session import get_db

        tid = _make_valid_uuid()
        request = MagicMock()
        request.state.tenant_id = tid
        request.state.scope = "tenant"

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.session.async_session_factory", return_value=mock_cm):
            gen = get_db(request=request)
            session = await gen.__anext__()
            assert session is mock_session

    @pytest.mark.asyncio
    async def test_falls_back_when_request_is_none(self):
        """get_db(None) falls back to raw get_async_session()."""
        from app.core.session import get_db

        mock_session = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.session.async_session_factory", return_value=mock_cm):
            gen = get_db(request=None)
            session = await gen.__anext__()
            # Should still yield a session (raw, no RLS SET)
            assert session is mock_session

    @pytest.mark.asyncio
    async def test_falls_back_on_invalid_tenant_in_state(self):
        """get_db() falls back gracefully if state has an invalid tenant_id."""
        from app.core.session import get_db

        request = MagicMock()
        request.state.tenant_id = "'; DROP TABLE users; --"
        request.state.scope = "tenant"

        mock_session = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.session.async_session_factory", return_value=mock_cm):
            gen = get_db(request=request)
            # Falls back to raw session — does not raise
            session = await gen.__anext__()
            assert session is mock_session

    @pytest.mark.asyncio
    async def test_empty_tenant_in_state_skips_rls(self):
        """get_db() with empty tenant_id (exempt path) does not issue SET LOCAL."""
        from app.core.session import get_db

        request = MagicMock()
        request.state.tenant_id = ""
        request.state.scope = ""

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.session.async_session_factory", return_value=mock_cm):
            gen = get_db(request=request)
            session = await gen.__anext__()
            assert session is mock_session

        # No SET LOCAL should be issued for empty tenant_id
        mock_session.execute.assert_not_called()
