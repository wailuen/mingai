"""
INFRA-037: Glossary pretranslation rollout flag - unit tests.

Validates per-tenant glossary pretranslation config read/write:
- Default False when no config row exists
- Boolean parsing from string and native bool
- Safe default on DB errors
- Upsert behavior for set operation
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    db = AsyncMock()
    return db


class TestIsGlossaryPretranslationEnabled:
    """Tests for is_glossary_pretranslation_enabled()."""

    @pytest.mark.asyncio
    async def test_flag_disabled_when_no_config_row(self, mock_db):
        """When DB returns no row, returns False (legacy behavior preserved)."""
        from app.core.glossary_config import is_glossary_pretranslation_enabled

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result

        result = await is_glossary_pretranslation_enabled("tenant-abc", mock_db)

        assert result is False
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_flag_enabled_when_config_is_true_string(self, mock_db):
        """config_value = 'true' (string) returns True."""
        from app.core.glossary_config import is_glossary_pretranslation_enabled

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("true",)
        mock_db.execute.return_value = mock_result

        result = await is_glossary_pretranslation_enabled("tenant-abc", mock_db)

        assert result is True

    @pytest.mark.asyncio
    async def test_flag_disabled_when_config_is_false_string(self, mock_db):
        """config_value = 'false' (string) returns False."""
        from app.core.glossary_config import is_glossary_pretranslation_enabled

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("false",)
        mock_db.execute.return_value = mock_result

        result = await is_glossary_pretranslation_enabled("tenant-abc", mock_db)

        assert result is False

    @pytest.mark.asyncio
    async def test_flag_enabled_when_config_is_bool_true(self, mock_db):
        """config_value = True (native bool) returns True."""
        from app.core.glossary_config import is_glossary_pretranslation_enabled

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (True,)
        mock_db.execute.return_value = mock_result

        result = await is_glossary_pretranslation_enabled("tenant-abc", mock_db)

        assert result is True

    @pytest.mark.asyncio
    async def test_flag_disabled_on_db_error(self, mock_db):
        """DB exception returns False (safe default) and logs warning."""
        from app.core.glossary_config import is_glossary_pretranslation_enabled

        mock_db.execute.side_effect = RuntimeError("connection refused")

        result = await is_glossary_pretranslation_enabled("tenant-abc", mock_db)

        assert result is False

    @pytest.mark.asyncio
    async def test_set_flag_upserts_to_db(self, mock_db):
        """set_glossary_pretranslation_enabled() calls DB execute with upsert SQL."""
        from app.core.glossary_config import set_glossary_pretranslation_enabled

        await set_glossary_pretranslation_enabled("tenant-xyz", True, mock_db)

        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        # Verify the SQL contains ON CONFLICT upsert pattern
        sql_text = str(call_args[0][0])
        assert "INSERT INTO tenant_configs" in sql_text
        assert "ON CONFLICT" in sql_text
        # Verify parameters include correct tenant_id and value
        params = call_args[0][1]
        assert params["tenant_id"] == "tenant-xyz"
        assert params["config_value"] is True
        # Verify commit was called
        mock_db.commit.assert_called_once()
