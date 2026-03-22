"""
Regression tests for Agent security fixes — red team round 2.

CRITICAL-1 (C1): Legacy test_agent endpoint was missing audit log
CRITICAL-2 (C2): publish_custom_agent had no test-before-publish gate
HIGH-5    (H5):  update_provider_selection leaked 'platform' RLS scope on 404/422
"""
import inspect

import pytest


@pytest.mark.regression
def test_legacy_test_agent_writes_audit_log():
    """C1: The legacy test_agent handler MUST call insert_audit_log.

    Before this fix, a tenant admin could repeatedly test an agent with zero
    audit trail — no accountability for what queries were run against which agents.
    """
    from app.modules.agents import routes

    source = inspect.getsource(routes.test_agent)
    assert "insert_audit_log" in source, (
        "test_agent MUST call insert_audit_log to maintain audit trail "
        "for agent test invocations"
    )
    assert '"agent_test_run"' in source or "'agent_test_run'" in source, (
        "test_agent audit log action must be 'agent_test_run'"
    )
    assert '"mode": "test"' in source or "'mode': 'test'" in source, (
        "test_agent audit log must include mode='test'"
    )


@pytest.mark.regression
def test_legacy_test_agent_writes_last_tested_at():
    """C1/C2: test_agent must persist last_tested_at for the publish gate."""
    from app.modules.agents import routes

    source = inspect.getsource(routes.test_agent)
    assert "last_tested_at" in source, (
        "test_agent must UPDATE agent_cards.last_tested_at after a successful test"
    )


@pytest.mark.regression
def test_studio_test_agent_writes_last_tested_at():
    """C2: Studio test endpoint must also persist last_tested_at."""
    from app.modules.agents import routes

    source = inspect.getsource(routes.test_custom_agent_studio)
    assert "last_tested_at" in source, (
        "test_custom_agent_studio must UPDATE agent_cards.last_tested_at "
        "after a successful test"
    )


@pytest.mark.regression
def test_publish_gate_requires_last_tested_at():
    """C2: publish_custom_agent must gate on last_tested_at IS NOT NULL.

    Before this fix, a tenant admin could publish an agent that had never
    been tested — shipping untested prompts to end users.
    """
    from app.modules.agents import routes

    source = inspect.getsource(routes.publish_custom_agent)
    assert "last_tested_at" in source, (
        "publish_custom_agent must check last_tested_at before allowing publish"
    )
    assert "Cannot publish" in source and "test" in source.lower(), (
        "publish_custom_agent must return a descriptive 422 when agent is untested"
    )


@pytest.mark.regression
def test_provider_selection_rls_reset_in_finally():
    """H5: update_provider_selection must reset app.scope to 'tenant' in a finally block.

    Before this fix, a 404 or 422 raised during the platform-scope validation
    window would leave app.scope='platform' on the pooled connection, allowing
    the next request on that connection to read across all tenants.
    """
    from app.modules.admin import llm_config

    source = inspect.getsource(llm_config.update_provider_selection)

    # The 'platform' scope must be set
    assert "platform" in source, (
        "update_provider_selection must set app.scope='platform' for provider lookup"
    )

    # The reset must be in a finally block
    # Check that 'finally' appears after 'platform' in the source
    platform_idx = source.index("'platform'")
    assert "finally" in source[platform_idx:], (
        "The app.scope='tenant' reset MUST be in a finally block to guarantee "
        "it runs even when a 404 or 422 exception is raised"
    )


@pytest.mark.regression
def test_provider_selection_rls_scope_reset_not_only_on_success():
    """H5: The scope reset must not be contingent on the validation passing.

    Verify the reset is in 'finally', not just at the bottom of the success path.
    """
    from app.modules.admin import llm_config

    source = inspect.getsource(llm_config.update_provider_selection)

    lines = source.splitlines()
    finally_lines = [i for i, l in enumerate(lines) if "finally" in l]
    scope_reset_lines = [
        i for i, l in enumerate(lines)
        if "app.scope" in l and "tenant" in l
    ]

    assert finally_lines, "update_provider_selection must have a finally block"
    assert scope_reset_lines, (
        "update_provider_selection must reset app.scope to 'tenant'"
    )

    # At least one scope reset line must come AFTER a finally line
    finally_min = min(finally_lines)
    reset_after_finally = any(r > finally_min for r in scope_reset_lines)
    assert reset_after_finally, (
        "The app.scope='tenant' reset must appear inside the finally block"
    )
