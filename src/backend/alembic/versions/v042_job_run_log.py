"""042 job_run_log — durable execution history for distributed scheduled jobs.

Records every scheduled job run: which pod acquired the lock, start/finish
times, final status (completed/failed/abandoned/skipped), and any error.

Used by:
  - Platform Admin > Scheduler History endpoint (SCHED-025)
  - Missed-job detection heartbeat (SCHED-024)
  - Startup cleanup of zombie 'running' rows (SCHED-005)

Columns:
  id                UUID PK
  job_name          VARCHAR(100) NOT NULL
  instance_id       VARCHAR(100)          — hostname of the pod
  tenant_id         UUID NULLABLE         — NULL for platform-scope jobs
  status            VARCHAR(20) NOT NULL  — running/completed/failed/abandoned/skipped
  started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
  completed_at      TIMESTAMPTZ           — NULL while running
  duration_ms       INTEGER
  records_processed INTEGER
  error_message     TEXT
  metadata          JSONB NOT NULL DEFAULT '{}'

Indexes:
  1. (job_name, started_at DESC)              — per-job history + missed-job check
  2. (tenant_id, started_at DESC) PARTIAL     — tenant admin history page
  3. (started_at DESC)                        — platform admin all-jobs view
  4. PARTIAL WHERE status = 'running'         — fast zombie row lookup at startup

No RLS policy — job_run_log is a platform-internal table with no tenant data.
No year-based partitioning — 90-day retention (SCHED-022) keeps the table
well under 5M rows at realistic tenant counts.

Revision ID: 042
Revises: 041
Create Date: 2026-03-20
"""
from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Main table
    op.execute(
        """
        CREATE TABLE job_run_log (
            id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            job_name          VARCHAR(100) NOT NULL,
            instance_id       VARCHAR(100),
            tenant_id         UUID         REFERENCES tenants(id) ON DELETE SET NULL,
            status            VARCHAR(20)  NOT NULL DEFAULT 'running'
                                           CHECK (status IN (
                                               'running','completed','failed',
                                               'abandoned','skipped'
                                           )),
            started_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            completed_at      TIMESTAMPTZ,
            duration_ms       INTEGER,
            records_processed INTEGER,
            error_message     TEXT,
            metadata          JSONB        NOT NULL DEFAULT '{}'
        )
        """
    )

    # Index 1: per-job history and missed-job check (M-01)
    op.execute(
        """
        CREATE INDEX idx_jrl_job_name_time
            ON job_run_log (job_name, started_at DESC)
        """
    )

    # Index 2: tenant admin history page — partial, only where tenant_id set
    op.execute(
        """
        CREATE INDEX idx_jrl_tenant_time
            ON job_run_log (tenant_id, started_at DESC)
            WHERE tenant_id IS NOT NULL
        """
    )

    # Index 3: platform admin all-jobs view
    op.execute(
        """
        CREATE INDEX idx_jrl_started_at
            ON job_run_log (started_at DESC)
        """
    )

    # Index 4: partial index for fast zombie row lookup at startup (SCHED-005)
    op.execute(
        """
        CREATE INDEX idx_jrl_running
            ON job_run_log (started_at)
            WHERE status = 'running'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_run_log")
