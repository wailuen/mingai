"""
023 template_performance_daily + guardrail_events (PA-025).

Adds two tables:

1. guardrail_events — emitted by chat when a deployed agent's guardrail fires.
   Enables the guardrail_trigger_rate metric in template performance tracking.
   RLS notes:
     - Standard tenant-scoped policy (guardrail_events_tenant) for read/write
       by tenant sessions (app.tenant_id set).
     - Platform-scope bypass policy (guardrail_events_platform) for SELECT by
       the nightly performance batch job, which sets app.scope = 'platform' and
       must aggregate across ALL tenants without a single tenant_id filter.

2. template_performance_daily — daily aggregated stats per agent_template:
     satisfaction_rate, guardrail_trigger_rate, failure_count, session_count.
   Populated nightly by the batch job in app.modules.platform.performance.
   NO RLS: this table has no tenant_id (keyed on platform-global template_id).
   Access is controlled entirely at the API layer (require_platform_admin).

Revision ID: 023
Revises: 022
Create Date: 2026-03-16
"""
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # guardrail_events: one row per guardrail rule trigger during a conversation
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS guardrail_events (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            agent_id    UUID REFERENCES agent_cards(id) ON DELETE SET NULL,
            template_id UUID REFERENCES agent_templates(id) ON DELETE SET NULL,
            conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
            rule_pattern TEXT NOT NULL CHECK (char_length(rule_pattern) <= 2000),
            action      VARCHAR(20) NOT NULL CHECK (action IN ('block', 'warn')),
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_guardrail_events_template "
        "ON guardrail_events (template_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_guardrail_events_agent "
        "ON guardrail_events (agent_id, created_at DESC)"
    )
    op.execute("ALTER TABLE guardrail_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE guardrail_events FORCE ROW LEVEL SECURITY")
    # Tenant-scoped policy: tenant sessions read/write their own events
    op.execute(
        """
        CREATE POLICY guardrail_events_tenant ON guardrail_events
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )
    # Platform bypass: nightly batch job aggregates across all tenants.
    # Batch sessions set app.scope = 'platform'; this policy grants SELECT only.
    op.execute(
        """
        CREATE POLICY guardrail_events_platform ON guardrail_events
        FOR SELECT
        USING (current_setting('app.scope', true) = 'platform')
        """
    )

    # template_performance_daily: one row per (template_id, date), upserted nightly.
    # No RLS — no tenant_id column. This is a platform-global aggregated table.
    # Access enforced at API layer via require_platform_admin.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS template_performance_daily (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            template_id             UUID NOT NULL REFERENCES agent_templates(id) ON DELETE CASCADE,
            date                    DATE NOT NULL,
            satisfaction_rate        FLOAT,      -- positive / total feedback (NULL if no feedback)
            guardrail_trigger_rate   FLOAT,      -- guardrail triggers / sessions (NULL if no sessions)
            failure_count            INTEGER NOT NULL DEFAULT 0,  -- thumbs-down count
            session_count            INTEGER NOT NULL DEFAULT 0,  -- distinct conversation_ids
            computed_at              TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (template_id, date)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tpd_template_date "
        "ON template_performance_daily (template_id, date DESC)"
    )
    # No tenant_id column — enforce platform-scope access only via RLS.
    # Tenant sessions (app.tenant_id set) cannot read this table at all.
    # Platform batch/API sessions set app.scope = 'platform' to gain access.
    op.execute("ALTER TABLE template_performance_daily ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE template_performance_daily FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tpd_platform_only ON template_performance_daily
        USING (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tpd_platform_only ON template_performance_daily")
    op.execute("DROP TABLE IF EXISTS template_performance_daily")
    op.execute("DROP POLICY IF EXISTS guardrail_events_platform ON guardrail_events")
    op.execute("DROP POLICY IF EXISTS guardrail_events_tenant ON guardrail_events")
    op.execute("DROP TABLE IF EXISTS guardrail_events")
