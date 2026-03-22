"""
Regression tests for Agent security fixes — red team round 3.

CRITICAL-1 (new): Studio test handler missing commit() → last_tested_at never persisted
HIGH-1    (new): list_available_providers leaked 'platform' RLS scope
HIGH-2    (new): verify_a2a_agent returned raw card_error to client
MEDIUM-1  (new): publish gate TOCTOU → replaced with atomic UPDATE + WHERE clause
"""
import inspect

import pytest


@pytest.mark.regression
def test_studio_test_handler_commits_last_tested_at():
    """C1: test_custom_agent_studio MUST call session.commit() after writing last_tested_at.

    Before this fix, the studio test endpoint wrote last_tested_at via execute() but
    never committed. The session would roll back on request completion, leaving
    last_tested_at = NULL and permanently blocking the publish gate for studio agents.
    """
    from app.modules.agents import routes

    source = inspect.getsource(routes.test_custom_agent_studio)
    # Both last_tested_at and a commit must appear after the LLM call section
    assert "last_tested_at" in source, "Studio test must write last_tested_at"
    # Find last_tested_at position then verify commit appears after it
    lt_pos = source.index("last_tested_at")
    remainder = source[lt_pos:]
    assert "await session.commit()" in remainder, (
        "test_custom_agent_studio MUST call await session.commit() "
        "after writing last_tested_at — without it the UPDATE is never persisted"
    )


@pytest.mark.regression
def test_list_available_providers_resets_rls_scope():
    """H1: list_available_providers must reset app.scope to 'tenant' after reading providers.

    Before this fix, the function elevated to platform scope to read llm_providers
    but never reset it, leaving the pooled connection in platform scope for the
    next request — enabling cross-tenant data access.
    """
    from app.modules.admin import llm_config

    source = inspect.getsource(llm_config.list_available_providers)
    assert "platform" in source, "Function must elevate to platform scope"
    # Verify the reset is in a finally block
    assert "finally" in source, (
        "list_available_providers must use try/finally to guarantee "
        "app.scope is reset to 'tenant' even if an exception occurs"
    )
    platform_idx = source.index("'platform'")
    assert "finally" in source[platform_idx:], (
        "The finally block must appear AFTER the platform scope elevation"
    )
    assert "'tenant'" in source[platform_idx:], (
        "The scope must be reset to 'tenant' inside the finally block"
    )


@pytest.mark.regression
def test_verify_a2a_agent_does_not_leak_card_error():
    """H2: verify_a2a_agent must not return raw exception details in card_error.

    Before this fix, card_error was set to str(exc) and returned verbatim to clients,
    potentially leaking internal hostnames, stack traces, or infrastructure details.
    """
    from app.modules.agents import routes

    source = inspect.getsource(routes.verify_a2a_agent)
    # card_error should be set to a generic string, not str(exc)
    assert "card_error = str(exc)" not in source, (
        "verify_a2a_agent must not assign card_error = str(exc) — "
        "this leaks raw exception details to clients"
    )
    # Generic messages should be used instead
    assert "A2A card validation failed" in source or "Could not fetch" in source, (
        "verify_a2a_agent must use generic error messages for card_error"
    )


@pytest.mark.regression
def test_publish_gate_is_atomic():
    """M1: publish_custom_agent must check last_tested_at atomically in the UPDATE.

    Before this fix, the gate read last_tested_at in one SELECT then updated status
    in a separate UPDATE — a TOCTOU race. The fix moves the gate check into the
    UPDATE WHERE clause: UPDATE ... WHERE last_tested_at IS NOT NULL.
    """
    from app.modules.agents import routes

    source = inspect.getsource(routes.publish_custom_agent)
    # The atomic pattern: UPDATE includes last_tested_at IS NOT NULL in WHERE
    assert "last_tested_at IS NOT NULL" in source, (
        "publish_custom_agent must gate the UPDATE on last_tested_at IS NOT NULL "
        "in the WHERE clause — this is the atomic pattern that eliminates TOCTOU"
    )


@pytest.mark.regression
def test_publish_gate_no_separate_select_for_gate():
    """M1 (complementary): publish gate should not use a separate SELECT for the gate check.

    The old pattern was: SELECT last_tested_at → check → UPDATE status.
    The new atomic pattern embeds the check in the UPDATE WHERE clause.
    A separate SELECT is only allowed for the fallback 404/422 disambiguation.
    """
    from app.modules.agents import routes

    source = inspect.getsource(routes.publish_custom_agent)
    # The primary gate check must be in the UPDATE, not a leading SELECT
    # Verify the UPDATE appears before the fallback SELECT
    update_idx = source.index("SET status = 'active'")
    assert "last_tested_at IS NOT NULL" in source[:update_idx + 200], (
        "The last_tested_at check must be inside the UPDATE WHERE clause, "
        "not in a leading SELECT"
    )
