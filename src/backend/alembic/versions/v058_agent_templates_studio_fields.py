"""v058 — Agent Templates: Studio extended fields for TemplateStudioPanel (TODO-20)

Adds the 7-dimension configuration columns that the PA Template Studio (TODO-20) needs.
These fields match what the frontend TemplateStudioPanel sends and expects.

Revision ID: 058
Revises: 057
"""
from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_templates
            ADD COLUMN IF NOT EXISTS icon TEXT,
            ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS template_type VARCHAR(32) NOT NULL DEFAULT 'rag'
                CHECK (template_type IN ('rag', 'skill_augmented', 'tool_augmented', 'credentialed', 'registered_a2a')),
            ADD COLUMN IF NOT EXISTS llm_policy JSONB NOT NULL DEFAULT
                '{"tenant_can_override": true, "defaults": {"temperature": 0.3, "max_tokens": 2000}}',
            ADD COLUMN IF NOT EXISTS kb_policy JSONB NOT NULL DEFAULT
                '{"ownership": "tenant_managed", "recommended_categories": [], "required_kb_ids": []}',
            ADD COLUMN IF NOT EXISTS attached_skills JSONB NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS attached_tools JSONB NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS a2a_interface JSONB NOT NULL DEFAULT
                '{"a2a_enabled": false, "operations": [], "auth_required": false}',
            ADD COLUMN IF NOT EXISTS citation_mode VARCHAR(20)
                CHECK (citation_mode IS NULL OR citation_mode IN ('inline', 'footnote', 'none')),
            ADD COLUMN IF NOT EXISTS max_response_length INTEGER,
            ADD COLUMN IF NOT EXISTS pii_masking_enabled BOOLEAN NOT NULL DEFAULT false
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_templates_template_type "
        "ON agent_templates(template_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_templates_tags "
        "ON agent_templates USING GIN(tags)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agent_templates_tags")
    op.execute("DROP INDEX IF EXISTS idx_agent_templates_template_type")
    op.execute(
        """
        ALTER TABLE agent_templates
            DROP COLUMN IF EXISTS pii_masking_enabled,
            DROP COLUMN IF EXISTS max_response_length,
            DROP COLUMN IF EXISTS citation_mode,
            DROP COLUMN IF EXISTS a2a_interface,
            DROP COLUMN IF EXISTS attached_tools,
            DROP COLUMN IF EXISTS attached_skills,
            DROP COLUMN IF EXISTS kb_policy,
            DROP COLUMN IF EXISTS llm_policy,
            DROP COLUMN IF EXISTS template_type,
            DROP COLUMN IF EXISTS tags,
            DROP COLUMN IF EXISTS icon
        """
    )
