"""
021 Agent Template Versioning (PA-022).

Adds `parent_id` column to `agent_templates` so that new-version drafts can
reference their root template.  This supports the two-endpoint versioning API:

  POST /platform/agent-templates/{id}/new-version
  GET  /platform/agent-templates/{id}/versions

Schema change:
  agent_templates.parent_id  UUID REFERENCES agent_templates(id) ON DELETE SET NULL

Design:
  - Root template (first version): parent_id = NULL
  - Each subsequent draft created via /new-version: parent_id = root_id
    (always points to the original root, never to an intermediate version)
  - Version family query: WHERE id = :root_id OR parent_id = :root_id

RLS is inherited from the existing policies created in v020 — no policy
changes required because the new column is not security-relevant.

Revision ID: 021
Revises: 020
Create Date: 2026-03-16
"""
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_templates
            ADD COLUMN IF NOT EXISTS parent_id UUID
                REFERENCES agent_templates(id) ON DELETE SET NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_templates_parent_id "
        "ON agent_templates (parent_id)"
    )
    # Unique constraint prevents duplicate version numbers within a template
    # family. COALESCE(parent_id, id) resolves both root templates (parent_id
    # IS NULL → family key = own id) and versioned children (parent_id = root).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_templates_family_version "
        "ON agent_templates (COALESCE(parent_id, id), version)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agent_templates_family_version")
    op.execute("DROP INDEX IF EXISTS idx_agent_templates_parent_id")
    op.execute("ALTER TABLE agent_templates DROP COLUMN IF EXISTS parent_id")
