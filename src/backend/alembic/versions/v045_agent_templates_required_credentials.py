"""Add required_credentials, auth_mode, plan_required to agent_templates.

ATA-001: Schema extension for credential and auth mode support.

Revision ID: 045
Revises: 044
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_templates",
        sa.Column(
            "required_credentials",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "agent_templates",
        sa.Column(
            "auth_mode",
            sa.String(32),
            nullable=False,
            server_default="'none'",
        ),
    )
    op.add_column(
        "agent_templates",
        sa.Column("plan_required", sa.String(32), nullable=True),
    )
    op.create_check_constraint(
        "ck_agent_templates_auth_mode",
        "agent_templates",
        "auth_mode IN ('none', 'tenant_credentials', 'platform_credentials')",
    )
    op.create_check_constraint(
        "ck_agent_templates_plan_required",
        "agent_templates",
        "plan_required IS NULL OR plan_required IN ('starter', 'professional', 'enterprise')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_templates_plan_required", "agent_templates")
    op.drop_constraint("ck_agent_templates_auth_mode", "agent_templates")
    op.drop_column("agent_templates", "plan_required")
    op.drop_column("agent_templates", "auth_mode")
    op.drop_column("agent_templates", "required_credentials")
