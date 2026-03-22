"""v051 — Add 'bedrock' to llm_library provider CHECK constraint

Revision ID: 051
Revises: 050
Create Date: 2026-03-22

Bedrock reuses existing columns:
  - endpoint_url  → BEDROCK_BASE_URL (e.g. https://bedrock-runtime.ap-southeast-1.amazonaws.com)
  - api_key_encrypted  → AWS_BEARER_TOKEN_BEDROCK
  - model_name    → full ARN or short model ID
  - api_key_last4 → last 4 chars of bearer token

No new columns are required. The only schema change is expanding the
provider CHECK constraint from 3 values to 4.
"""
from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop existing provider check (IF EXISTS: idempotent across re-runs)
    op.execute(
        "ALTER TABLE llm_library "
        "DROP CONSTRAINT IF EXISTS llm_library_provider_check"
    )

    # Re-add with bedrock included as the fourth provider
    op.execute(
        "ALTER TABLE llm_library "
        "ADD CONSTRAINT llm_library_provider_check "
        "CHECK (provider IN ('azure_openai', 'openai_direct', 'anthropic', 'bedrock'))"
    )


def downgrade() -> None:
    # Remove all bedrock rows before restoring the three-value constraint
    op.execute("DELETE FROM llm_library WHERE provider = 'bedrock'")

    op.execute(
        "ALTER TABLE llm_library "
        "DROP CONSTRAINT IF EXISTS llm_library_provider_check"
    )

    op.execute(
        "ALTER TABLE llm_library "
        "ADD CONSTRAINT llm_library_provider_check "
        "CHECK (provider IN ('azure_openai', 'openai_direct', 'anthropic'))"
    )
