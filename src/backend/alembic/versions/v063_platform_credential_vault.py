"""v063 — Platform Credential Vault

Revision ID: 063
Revises: 062
Create Date: 2026-03-24

Adds two tables required for the Platform Credential Vault feature:

  platform_credential_metadata
    Tracks which platform-level credential keys have been provisioned per
    template. Credential VALUES are NEVER stored here — only key names,
    metadata, and injection configuration. Values live in the vault backend
    (HashiCorp Vault KV v2 in prod, Fernet-encrypted JSON in dev).

  platform_credential_audit
    Append-only audit log of all credential operations (store, rotate,
    delete, resolve, blocked). Required for SOC 2 / ISO 27001.

Design decisions:
- PARTIAL unique index on (template_id, key) WHERE deleted_at IS NULL
  allows re-provisioning a key immediately after accidental soft-delete
  without waiting for hard-delete (30-day retention window).
- ON DELETE RESTRICT on the FK to agent_templates prevents orphaned
  credential metadata — admin must delete credentials before template.
- injection_config JSONB: stores how the credential is injected at runtime
  (bearer, custom header, query param, basic auth) so the orchestrator
  knows which HTTP header pattern to use per credential.
- allowed_domains JSONB: per-credential SSRF allowlist — orchestrator
  validates tool endpoint URL against this before injecting credential.
- version INTEGER: optimistic concurrency lock for rotate endpoint
  (If-Match header required, 409 on mismatch).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v063"
down_revision = "v062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # platform_credential_metadata
    # ------------------------------------------------------------------
    op.create_table(
        "platform_credential_metadata",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.VARCHAR(64), nullable=False),
        sa.Column(
            "allowed_domains",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("description", sa.VARCHAR(256), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "injection_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(
                "'{\"type\": \"header\", \"header_name\": \"Authorization\", \"header_format\": \"{value}\"}'::jsonb"
            ),
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("created_by", sa.VARCHAR(128), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_by", sa.VARCHAR(128), nullable=False),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.VARCHAR(128), nullable=True),
        sa.Column("retention_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["agent_templates.id"],
            name="fk_pcm_template",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # PARTIAL unique index — allows re-provisioning after soft-delete (M-01 fix)
    op.create_index(
        "uq_pcm_active",
        "platform_credential_metadata",
        ["template_id", "key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Fast lookup of active keys for a given template
    op.create_index(
        "idx_pcm_template",
        "platform_credential_metadata",
        ["template_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ------------------------------------------------------------------
    # platform_credential_audit
    # ------------------------------------------------------------------
    op.create_table(
        "platform_credential_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("actor_id", sa.VARCHAR(128), nullable=False),
        sa.Column("tenant_id", sa.VARCHAR(128), nullable=True),
        sa.Column("request_id", sa.VARCHAR(128), nullable=True),
        sa.Column("action", sa.VARCHAR(32), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.VARCHAR(64), nullable=False),
        sa.Column("source_ip", postgresql.INET(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Descending timestamp index for per-template audit trail queries
    op.create_index(
        "idx_pca_template",
        "platform_credential_audit",
        ["template_id", sa.text("timestamp DESC")],
    )


def downgrade() -> None:
    # Drop audit table first (no FK dependencies)
    op.drop_index("idx_pca_template", table_name="platform_credential_audit")
    op.drop_table("platform_credential_audit")

    # Drop metadata table — indexes must be dropped before table
    op.drop_index("idx_pcm_template", table_name="platform_credential_metadata")
    op.drop_index("uq_pcm_active", table_name="platform_credential_metadata")
    op.drop_table("platform_credential_metadata")
