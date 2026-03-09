"""
TEST-073: Alembic migration rollback tests.

Verifies every migration's downgrade() function executes cleanly.
Pattern: downgrade to before the migration, then upgrade again.

IMPORTANT: These tests use subprocess to run alembic CLI directly against
the test database, since Alembic's Python API requires a sync connection.
"""
import os
import subprocess
import sys
import psycopg2

# Backend root — where alembic.ini lives
BACKEND_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# Derive the alembic binary path from the active Python interpreter so the
# subprocess uses the same virtual-env / pyenv installation as pytest itself.
# e.g. /path/to/pyenv/versions/3.12.9/bin/python  ->  .../bin/alembic
_ALEMBIC_BIN = os.path.join(os.path.dirname(sys.executable), "alembic")


def _get_sync_db_url() -> str:
    """
    Return a psycopg2-compatible connection string from DATABASE_URL.

    DATABASE_URL may use +asyncpg driver; psycopg2 needs the plain
    postgresql:// scheme (or postgresql+psycopg2://).
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Export it or add it to .env before running integration tests."
        )
    # Strip any async driver suffix for psycopg2
    url = url.replace("+asyncpg", "").replace("+psycopg", "")
    # Normalise scheme
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    return url


def _alembic(cmd: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """
    Run an alembic CLI command in the backend root directory.

    Uses the alembic binary co-located with the active Python interpreter so
    the subprocess operates in the same virtual-env as pytest.

    Args:
        cmd: Space-separated alembic subcommand, e.g. "upgrade head".
        timeout: Seconds before the subprocess is killed.

    Returns:
        CompletedProcess — caller asserts returncode.
    """
    result = subprocess.run(
        [_ALEMBIC_BIN] + cmd.split(),
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def _query_one(sql: str, params: tuple = ()) -> object:
    """Execute a single-value query against the test DB and return the scalar."""
    url = _get_sync_db_url()
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def _table_exists(table_name: str) -> bool:
    count = _query_one(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table_name,),
    )
    return int(count) > 0


def _column_exists(table_name: str, column_name: str) -> bool:
    count = _query_one(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = 'public' "
        "  AND table_name = %s AND column_name = %s",
        (table_name, column_name),
    )
    return int(count) > 0


def _rls_enabled(table_name: str) -> bool:
    """Return True if row-level security is enabled on the table."""
    result = _query_one(
        "SELECT relrowsecurity FROM pg_class "
        "WHERE relname = %s AND relnamespace = 'public'::regnamespace",
        (table_name,),
    )
    return bool(result)


class TestMigrationRollback:
    """
    One test per migration (v001–v008).

    The class fixture brings the schema to `head` once before all tests,
    and restores it to `head` in teardown so each individual test always
    starts from a consistent state.

    Individual tests follow this pattern:
        1. Downgrade to the revision *before* the migration under test.
        2. Assert the schema change is absent.
        3. Upgrade back to the migration under test.
        4. Assert the schema change is present.
    """

    @classmethod
    def setup_class(cls):
        """Ensure the database is at head before any test runs."""
        result = _alembic("upgrade head")
        assert result.returncode == 0, (
            f"alembic upgrade head failed in setup_class:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    @classmethod
    def teardown_class(cls):
        """Restore the database to head after all tests finish."""
        _alembic("upgrade head")

    # ------------------------------------------------------------------
    # Full chain
    # ------------------------------------------------------------------

    def test_full_chain_upgrade_downgrade_upgrade(self):
        """Full chain: head -> base -> head completes without errors."""
        result_down = _alembic("downgrade base", timeout=180)
        assert result_down.returncode == 0, (
            f"alembic downgrade base failed:\n"
            f"stdout: {result_down.stdout}\nstderr: {result_down.stderr}"
        )

        # After downgrade to base no application tables should exist
        assert not _table_exists(
            "tenants"
        ), "tenants table still exists after downgrade to base"

        result_up = _alembic("upgrade head", timeout=180)
        assert result_up.returncode == 0, (
            f"alembic upgrade head failed after base downgrade:\n"
            f"stdout: {result_up.stdout}\nstderr: {result_up.stderr}"
        )

        # All baseline tables should be restored
        assert _table_exists(
            "tenants"
        ), "tenants table missing after re-upgrade to head"
        assert _table_exists("users"), "users table missing after re-upgrade to head"

    # ------------------------------------------------------------------
    # v008 — disputes table
    # ------------------------------------------------------------------

    def test_v008_disputes_table_rollback(self):
        """v008: disputes table created/dropped cleanly."""
        # Ensure we're at head first
        _alembic("upgrade head")
        assert _table_exists("disputes"), "disputes table should exist at head"

        # Downgrade to 007 — disputes should disappear
        result_down = _alembic("downgrade 007")
        assert result_down.returncode == 0, (
            f"alembic downgrade 007 failed:\n"
            f"stdout: {result_down.stdout}\nstderr: {result_down.stderr}"
        )
        assert not _table_exists(
            "disputes"
        ), "disputes table still exists after downgrade to 007"

        # Upgrade back to 008 — disputes should reappear
        result_up = _alembic("upgrade 008")
        assert result_up.returncode == 0, (
            f"alembic upgrade 008 failed:\n"
            f"stdout: {result_up.stdout}\nstderr: {result_up.stderr}"
        )
        assert _table_exists(
            "disputes"
        ), "disputes table missing after re-upgrade to 008"

    # ------------------------------------------------------------------
    # v007 — registry columns (is_public, a2a_endpoint, etc.)
    # ------------------------------------------------------------------

    def test_v007_registry_columns_rollback(self):
        """v007: registry columns added/removed cleanly from agent_cards."""
        _alembic("upgrade head")
        assert _column_exists(
            "agent_cards", "is_public"
        ), "is_public column should exist at head"

        result_down = _alembic("downgrade 006")
        assert result_down.returncode == 0, (
            f"alembic downgrade 006 failed:\n"
            f"stdout: {result_down.stdout}\nstderr: {result_down.stderr}"
        )
        assert not _column_exists(
            "agent_cards", "is_public"
        ), "is_public column still exists after downgrade to 006"
        assert not _column_exists(
            "agent_cards", "a2a_endpoint"
        ), "a2a_endpoint column still exists after downgrade to 006"

        result_up = _alembic("upgrade 007")
        assert result_up.returncode == 0, (
            f"alembic upgrade 007 failed:\n"
            f"stdout: {result_up.stdout}\nstderr: {result_up.stderr}"
        )
        assert _column_exists(
            "agent_cards", "is_public"
        ), "is_public column missing after re-upgrade to 007"
        assert _column_exists(
            "agent_cards", "a2a_endpoint"
        ), "a2a_endpoint column missing after re-upgrade to 007"

    # ------------------------------------------------------------------
    # v006 — notifications table
    # ------------------------------------------------------------------

    def test_v006_notifications_table_rollback(self):
        """v006: notifications table created/dropped cleanly."""
        _alembic("upgrade head")
        assert _table_exists(
            "notifications"
        ), "notifications table should exist at head"

        result_down = _alembic("downgrade 005")
        assert result_down.returncode == 0, (
            f"alembic downgrade 005 failed:\n"
            f"stdout: {result_down.stdout}\nstderr: {result_down.stderr}"
        )
        assert not _table_exists(
            "notifications"
        ), "notifications table still exists after downgrade to 005"

        result_up = _alembic("upgrade 006")
        assert result_up.returncode == 0, (
            f"alembic upgrade 006 failed:\n"
            f"stdout: {result_up.stdout}\nstderr: {result_up.stderr}"
        )
        assert _table_exists(
            "notifications"
        ), "notifications table missing after re-upgrade to 006"

    # ------------------------------------------------------------------
    # v005 — agent_cards studio columns
    # ------------------------------------------------------------------

    def test_v005_agent_cards_columns_rollback(self):
        """v005: agent_cards studio columns (category, source, avatar, template_id,
        template_version) added and removed cleanly."""
        _alembic("upgrade head")
        for col in ("category", "source", "avatar", "template_id", "template_version"):
            assert _column_exists(
                "agent_cards", col
            ), f"agent_cards.{col} should exist at head"

        result_down = _alembic("downgrade 004")
        assert result_down.returncode == 0, (
            f"alembic downgrade 004 failed:\n"
            f"stdout: {result_down.stdout}\nstderr: {result_down.stderr}"
        )
        for col in ("category", "source", "avatar", "template_id", "template_version"):
            assert not _column_exists(
                "agent_cards", col
            ), f"agent_cards.{col} still exists after downgrade to 004"

        result_up = _alembic("upgrade 005")
        assert result_up.returncode == 0, (
            f"alembic upgrade 005 failed:\n"
            f"stdout: {result_up.stdout}\nstderr: {result_up.stderr}"
        )
        for col in ("category", "source", "avatar", "template_id", "template_version"):
            assert _column_exists(
                "agent_cards", col
            ), f"agent_cards.{col} missing after re-upgrade to 005"

    # ------------------------------------------------------------------
    # v004 — llm_profiles.status column
    # ------------------------------------------------------------------

    def test_v004_llm_profile_status_rollback(self):
        """v004: llm_profiles.status column added/removed cleanly."""
        _alembic("upgrade head")
        assert _column_exists(
            "llm_profiles", "status"
        ), "llm_profiles.status should exist at head"

        result_down = _alembic("downgrade 003")
        assert result_down.returncode == 0, (
            f"alembic downgrade 003 failed:\n"
            f"stdout: {result_down.stdout}\nstderr: {result_down.stderr}"
        )
        assert not _column_exists(
            "llm_profiles", "status"
        ), "llm_profiles.status still exists after downgrade to 003"

        result_up = _alembic("upgrade 004")
        assert result_up.returncode == 0, (
            f"alembic upgrade 004 failed:\n"
            f"stdout: {result_up.stdout}\nstderr: {result_up.stderr}"
        )
        assert _column_exists(
            "llm_profiles", "status"
        ), "llm_profiles.status missing after re-upgrade to 004"

    # ------------------------------------------------------------------
    # v003 — HAR keypair columns + transaction tables
    # ------------------------------------------------------------------

    def test_v003_har_keypair_rollback(self):
        """v003: HAR keypair columns (public_key, private_key_enc, trust_score,
        kyb_level) and har_transactions / har_transaction_events tables
        added and removed cleanly."""
        _alembic("upgrade head")
        for col in ("public_key", "private_key_enc", "trust_score", "kyb_level"):
            assert _column_exists(
                "agent_cards", col
            ), f"agent_cards.{col} should exist at head"
        assert _table_exists(
            "har_transactions"
        ), "har_transactions should exist at head"
        assert _table_exists(
            "har_transaction_events"
        ), "har_transaction_events should exist at head"

        result_down = _alembic("downgrade 002")
        assert result_down.returncode == 0, (
            f"alembic downgrade 002 failed:\n"
            f"stdout: {result_down.stdout}\nstderr: {result_down.stderr}"
        )
        for col in ("public_key", "private_key_enc", "trust_score", "kyb_level"):
            assert not _column_exists(
                "agent_cards", col
            ), f"agent_cards.{col} still exists after downgrade to 002"
        assert not _table_exists(
            "har_transactions"
        ), "har_transactions still exists after downgrade to 002"
        assert not _table_exists(
            "har_transaction_events"
        ), "har_transaction_events still exists after downgrade to 002"

        result_up = _alembic("upgrade 003")
        assert result_up.returncode == 0, (
            f"alembic upgrade 003 failed:\n"
            f"stdout: {result_up.stdout}\nstderr: {result_up.stderr}"
        )
        for col in ("public_key", "private_key_enc", "trust_score", "kyb_level"):
            assert _column_exists(
                "agent_cards", col
            ), f"agent_cards.{col} missing after re-upgrade to 003"
        assert _table_exists(
            "har_transactions"
        ), "har_transactions missing after re-upgrade to 003"

    # ------------------------------------------------------------------
    # v002 — RLS policies
    # ------------------------------------------------------------------

    def test_v002_rls_policies_rollback(self):
        """v002: RLS policies applied/removed — verified on the tenants table."""
        _alembic("upgrade head")
        assert _rls_enabled("tenants"), "RLS should be enabled on tenants at head"

        result_down = _alembic("downgrade 001")
        assert result_down.returncode == 0, (
            f"alembic downgrade 001 failed:\n"
            f"stdout: {result_down.stdout}\nstderr: {result_down.stderr}"
        )
        assert not _rls_enabled(
            "tenants"
        ), "RLS still enabled on tenants after downgrade to 001"

        result_up = _alembic("upgrade 002")
        assert result_up.returncode == 0, (
            f"alembic upgrade 002 failed:\n"
            f"stdout: {result_up.stdout}\nstderr: {result_up.stderr}"
        )
        assert _rls_enabled(
            "tenants"
        ), "RLS not re-enabled on tenants after upgrade to 002"

    # ------------------------------------------------------------------
    # v001 — initial schema (22 tables)
    # ------------------------------------------------------------------

    def test_v001_initial_schema_rollback(self):
        """v001: All 22 initial tables created and dropped cleanly."""
        _alembic("upgrade head")

        # Spot-check a representative set of tables
        spot_check_tables = [
            "tenants",
            "users",
            "llm_profiles",
            "agent_cards",
            "issue_reports",
            "audit_log",
        ]
        for tbl in spot_check_tables:
            assert _table_exists(tbl), f"{tbl} should exist at head"

        result_down = _alembic("downgrade base")
        assert result_down.returncode == 0, (
            f"alembic downgrade base failed:\n"
            f"stdout: {result_down.stdout}\nstderr: {result_down.stderr}"
        )
        for tbl in spot_check_tables:
            assert not _table_exists(tbl), f"{tbl} still exists after downgrade to base"

        result_up = _alembic("upgrade 001")
        assert result_up.returncode == 0, (
            f"alembic upgrade 001 failed:\n"
            f"stdout: {result_up.stdout}\nstderr: {result_up.stderr}"
        )
        for tbl in spot_check_tables:
            assert _table_exists(tbl), f"{tbl} missing after re-upgrade to 001"
