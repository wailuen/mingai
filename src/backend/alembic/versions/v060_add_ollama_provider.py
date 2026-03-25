"""v060 — Add 'ollama' to llm_library provider CHECK constraint

Revision ID: 060
Revises: 059
Create Date: 2026-03-23

Ollama reuses existing columns:
  - endpoint_url  → base URL of local Ollama instance (e.g. http://localhost:11434)
  - model_name    → Ollama model tag (e.g. qwen3.5:27b)
  - api_key_encrypted → not required (uses "ollama" placeholder)

No new columns are required. The only schema change is expanding the
provider CHECK constraint from 4 values to 5.
"""
from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop existing provider check (IF EXISTS: idempotent across re-runs)
    op.execute(
        "ALTER TABLE llm_library "
        "DROP CONSTRAINT IF EXISTS llm_library_provider_check"
    )

    # Re-add with ollama included as the fifth provider
    op.execute(
        "ALTER TABLE llm_library "
        "ADD CONSTRAINT llm_library_provider_check "
        "CHECK (provider IN ('azure_openai', 'openai_direct', 'anthropic', 'bedrock', 'ollama'))"
    )


def downgrade() -> None:
    # Remove all ollama rows before restoring the four-value constraint
    op.execute("DELETE FROM llm_library WHERE provider = 'ollama'")

    op.execute(
        "ALTER TABLE llm_library "
        "DROP CONSTRAINT IF EXISTS llm_library_provider_check"
    )

    op.execute(
        "ALTER TABLE llm_library "
        "ADD CONSTRAINT llm_library_provider_check "
        "CHECK (provider IN ('azure_openai', 'openai_direct', 'anthropic', 'bedrock'))"
    )
