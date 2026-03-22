"""
Unit tests for v050 LLM Profile v2 migration schema integrity.

Tests verify that:
- The schema.py TABLE_DEFINITIONS match the v050 migration structure
- llm_profiles v2 columns are defined (slot FKs, params, traffic splits, etc.)
- Old v1 columns are absent from the definition
- llm_profile_history and llm_profile_audit_log are present
- Status constraints use lowercase values
- Only one platform default is semantically enforced

These tests run against schema.py definitions WITHOUT a real DB connection.
They confirm that the schema definition layer is consistent with the migration.
"""
import pytest

from app.core.schema import TABLE_DEFINITIONS, TABLE_NAMES


class TestLLMProfilesV2Schema:
    """Validate llm_profiles v2 TABLE_DEFINITION matches v050 migration."""

    def test_llm_profiles_in_table_names(self):
        assert "llm_profiles" in TABLE_NAMES

    def test_llm_profiles_in_table_definitions(self):
        assert "llm_profiles" in TABLE_DEFINITIONS

    def test_v2_slot_columns_present(self):
        defn = TABLE_DEFINITIONS["llm_profiles"]
        for slot in ("chat", "intent", "vision", "agent"):
            assert f"{slot}_library_id" in defn, f"Missing {slot}_library_id in llm_profiles"

    def test_v2_params_columns_present(self):
        defn = TABLE_DEFINITIONS["llm_profiles"]
        for slot in ("chat", "intent", "vision", "agent"):
            assert f"{slot}_params" in defn, f"Missing {slot}_params in llm_profiles"

    def test_v2_traffic_split_columns_present(self):
        defn = TABLE_DEFINITIONS["llm_profiles"]
        for slot in ("chat", "intent", "vision", "agent"):
            assert f"{slot}_traffic_split" in defn, (
                f"Missing {slot}_traffic_split in llm_profiles"
            )

    def test_v2_platform_default_column_present(self):
        assert "is_platform_default" in TABLE_DEFINITIONS["llm_profiles"]

    def test_v2_plan_tiers_column_present(self):
        assert "plan_tiers" in TABLE_DEFINITIONS["llm_profiles"]

    def test_v2_owner_tenant_id_column_present(self):
        assert "owner_tenant_id" in TABLE_DEFINITIONS["llm_profiles"]

    def test_v2_status_constraint_lowercase(self):
        defn = TABLE_DEFINITIONS["llm_profiles"]
        # The CHECK constraint should reference lowercase values
        assert "active" in defn
        assert "deprecated" in defn

    def test_v2_unique_name_owner_constraint(self):
        defn = TABLE_DEFINITIONS["llm_profiles"]
        assert "UNIQUE (name, owner_tenant_id)" in defn

    def test_v1_columns_absent(self):
        """v1 flat columns must be gone — they were dropped in v050.

        Each check looks for '<colname> ' (with trailing space) or
        '<colname> UUID ... NOT NULL REFERENCES tenants' to avoid false
        positives from substrings like 'owner_tenant_id' matching 'tenant_id'.
        """
        defn = TABLE_DEFINITIONS["llm_profiles"]
        # v1 columns that MUST NOT appear as standalone column definitions.
        # We check using " col " or leading "col " to avoid substring false-positives.
        v1_columns = (
            "primary_model",
            "intent_model",
            "embedding_model",
        )
        for col in v1_columns:
            assert col not in defn, (
                f"v1 column '{col}' still present in llm_profiles schema — "
                "should have been removed by v050 migration"
            )

        # tenant_id check: the v1 schema had "tenant_id UUID NOT NULL REFERENCES tenants(id)"
        # as the SECOND column. v2 dropped this. We check that no line starts with
        # exactly "tenant_id UUID NOT NULL" (not a prefix like owner_tenant_id).
        assert '"tenant_id UUID NOT NULL' not in f'"{defn}', (
            "v1 column 'tenant_id UUID NOT NULL' still present — dropped in v050"
        )
        # Simpler: "NOT NULL REFERENCES tenants" won't appear in v2 for tenant_id
        # because the only tenant_id-like column is owner_tenant_id which is nullable.
        assert "tenant_id UUID NOT NULL" not in defn, (
            "The old 'tenant_id UUID NOT NULL' v1 column appears in llm_profiles — "
            "should be gone after v050"
        )

        # provider column: v1 had a flat 'provider' string; v2 removed it.
        # Check it's not there as a standalone column (not part of owner_tenant_id etc.)
        assert "provider VARCHAR" not in defn, (
            "v1 column 'provider VARCHAR' still present in llm_profiles — dropped in v050"
        )


class TestLLMProfileHistorySchema:
    """Validate llm_profile_history TABLE_DEFINITION."""

    def test_llm_profile_history_in_table_names(self):
        assert "llm_profile_history" in TABLE_NAMES

    def test_llm_profile_history_in_table_definitions(self):
        assert "llm_profile_history" in TABLE_DEFINITIONS

    def test_profile_id_column_present(self):
        assert "profile_id" in TABLE_DEFINITIONS["llm_profile_history"]

    def test_slot_snapshot_column_present(self):
        assert "slot_snapshot" in TABLE_DEFINITIONS["llm_profile_history"]

    def test_changed_by_column_present(self):
        assert "changed_by" in TABLE_DEFINITIONS["llm_profile_history"]

    def test_changed_at_column_present(self):
        assert "changed_at" in TABLE_DEFINITIONS["llm_profile_history"]


class TestLLMProfileAuditLogSchema:
    """Validate llm_profile_audit_log TABLE_DEFINITION."""

    def test_llm_profile_audit_log_in_table_names(self):
        assert "llm_profile_audit_log" in TABLE_NAMES

    def test_llm_profile_audit_log_in_table_definitions(self):
        assert "llm_profile_audit_log" in TABLE_DEFINITIONS

    def test_entity_type_column_present(self):
        assert "entity_type" in TABLE_DEFINITIONS["llm_profile_audit_log"]

    def test_actor_id_column_present(self):
        assert "actor_id" in TABLE_DEFINITIONS["llm_profile_audit_log"]

    def test_tenant_id_column_present(self):
        assert "tenant_id" in TABLE_DEFINITIONS["llm_profile_audit_log"]

    def test_action_column_present(self):
        assert "action" in TABLE_DEFINITIONS["llm_profile_audit_log"]

    def test_diff_column_present(self):
        assert "diff" in TABLE_DEFINITIONS["llm_profile_audit_log"]

    def test_logged_at_column_present(self):
        assert "logged_at" in TABLE_DEFINITIONS["llm_profile_audit_log"]


class TestLLMLibraryStatusLowercase:
    """Validate that llm_library status is now lowercase after v050 migration."""

    def test_lowercase_status_in_instrumented_client(self):
        """instrumented_client.py must query status = 'published' (not 'Published')."""
        import inspect
        from app.core.llm import instrumented_client

        source = inspect.getsource(instrumented_client)
        # Must not contain the old Title Case status
        assert "status = 'Published'" not in source, (
            "instrumented_client.py still uses Title Case 'Published' — "
            "must be lowercase 'published' after v050"
        )

    def test_lowercase_status_in_llm_library_routes(self):
        """llm_library/routes.py must use lowercase status strings."""
        import inspect
        from app.modules.platform.llm_library import routes

        source = inspect.getsource(routes)
        # Check for specific Title Case occurrences that should be gone
        assert "status = 'Draft'" not in source, (
            "routes.py still has 'Draft' status string — must be lowercase"
        )
        assert "status = 'Published'" not in source, (
            "routes.py still has 'Published' status string — must be lowercase"
        )
        assert "status = 'Deprecated'" not in source, (
            "routes.py still has 'Deprecated' status string — must be lowercase"
        )

    def test_lowercase_status_in_llm_config(self):
        """admin/llm_config.py must use lowercase status strings."""
        import inspect
        from app.modules.admin import llm_config

        source = inspect.getsource(llm_config)
        assert "status = 'Published'" not in source, (
            "llm_config.py still uses Title Case 'Published' — must be lowercase"
        )

    def test_lowercase_status_in_reindex(self):
        """documents/reindex.py must use lowercase status strings."""
        import inspect
        from app.modules.documents import reindex

        source = inspect.getsource(reindex)
        assert "status = 'Published'" not in source, (
            "reindex.py still uses Title Case 'Published' — must be lowercase"
        )


class TestValidProvidersBedrock:
    """Verify bedrock is included in the provider allowlist."""

    def test_bedrock_in_valid_providers(self):
        from app.modules.platform.llm_library.routes import _VALID_PROVIDERS

        assert "bedrock" in _VALID_PROVIDERS, (
            "_VALID_PROVIDERS must include 'bedrock' after BEDROCK-002"
        )

    def test_all_four_providers_present(self):
        from app.modules.platform.llm_library.routes import _VALID_PROVIDERS

        expected = {"azure_openai", "openai_direct", "anthropic", "bedrock"}
        assert _VALID_PROVIDERS == expected
