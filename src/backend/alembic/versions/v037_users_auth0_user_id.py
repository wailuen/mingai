"""
037 Add auth0_user_id to users table (TA-033).

Adds auth0_user_id VARCHAR(255) NULL UNIQUE to users so that SSO-imported
users can be linked back to their Auth0 identity.

No new table is created in this migration — only an ALTER TABLE.  RLS is
already enabled on the users table (v002). No new RLS policy is needed.

Revision ID: 037
Revises: 036
Create Date: 2026-03-17
"""
from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS " "auth0_user_id VARCHAR(255) NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_auth0_user_id "
        "ON users (auth0_user_id) WHERE auth0_user_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_auth0_user_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS auth0_user_id")
