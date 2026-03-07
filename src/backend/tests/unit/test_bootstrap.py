"""
Unit tests for platform admin bootstrap (INFRA-066).

Tests seed data generation and platform bootstrap SQL.
Tier 1: Fast, isolated, no database required.

generate_bootstrap_sql() returns list[tuple[text_obj, params_dict]].
Each tuple is (sqlalchemy.text, dict) for safe parameterized execution.
"""
import os
from unittest.mock import patch

import pytest


class TestBootstrapSQLGeneration:
    """INFRA-066: Platform admin bootstrap SQL tests."""

    def test_bootstrap_generates_tenant_insert(self):
        """Bootstrap generates parameterized SQL to insert the default tenant."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "acme-corp",
            "PLATFORM_ADMIN_EMAIL": "admin@acme.com",
            "PLATFORM_ADMIN_PASS": "secure-pass-123",
        }
        with patch.dict(os.environ, env):
            statements = generate_bootstrap_sql()

        # Should have at least: tenant insert, user insert
        assert len(statements) >= 2

        # First statement is a (text_obj, params_dict) tuple
        tenant_sql, tenant_params = statements[0]
        assert "INSERT INTO tenants" in str(tenant_sql)
        # Tenant name is in the params dict, not interpolated into the SQL
        assert tenant_params["name"] == "acme-corp"

    def test_bootstrap_generates_admin_user_insert(self):
        """Bootstrap generates parameterized SQL to insert the platform admin user."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "acme-corp",
            "PLATFORM_ADMIN_EMAIL": "admin@acme.com",
            "PLATFORM_ADMIN_PASS": "secure-pass-123",
        }
        with patch.dict(os.environ, env):
            statements = generate_bootstrap_sql()

        user_sql, user_params = statements[1]
        assert "INSERT INTO users" in str(user_sql)
        assert user_params["email"] == "admin@acme.com"
        assert user_params["role"] == "platform_admin"

    def test_bootstrap_never_includes_raw_password(self):
        """Password must be hashed - raw password never appears in SQL template or params."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "test-tenant",
            "PLATFORM_ADMIN_EMAIL": "admin@test.com",
            "PLATFORM_ADMIN_PASS": "my-secret-password-123",
        }
        with patch.dict(os.environ, env):
            statements = generate_bootstrap_sql()

        # Check neither the SQL templates nor param VALUES contain the raw password
        for sql_obj, params in statements:
            assert "my-secret-password-123" not in str(sql_obj)
            for v in params.values():
                assert "my-secret-password-123" not in str(v)

    def test_bootstrap_password_is_bcrypt_hashed(self):
        """Password in params should be a bcrypt hash, not plaintext."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "test-tenant",
            "PLATFORM_ADMIN_EMAIL": "admin@test.com",
            "PLATFORM_ADMIN_PASS": "test-password",
        }
        with patch.dict(os.environ, env):
            statements = generate_bootstrap_sql()

        _, user_params = statements[1]
        # bcrypt hashes start with $2b$ or $2a$
        assert user_params["password_hash"].startswith("$2b$") or user_params[
            "password_hash"
        ].startswith("$2a$")

    def test_bootstrap_raises_if_email_missing(self):
        """Bootstrap raises clear error if PLATFORM_ADMIN_EMAIL is not set."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "test",
            "PLATFORM_ADMIN_EMAIL": "",
            "PLATFORM_ADMIN_PASS": "password",
        }
        with patch.dict(os.environ, env):
            with pytest.raises(ValueError, match="PLATFORM_ADMIN_EMAIL"):
                generate_bootstrap_sql()

    def test_bootstrap_raises_if_password_missing(self):
        """Bootstrap raises clear error if PLATFORM_ADMIN_PASS is not set."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "test",
            "PLATFORM_ADMIN_EMAIL": "admin@test.com",
            "PLATFORM_ADMIN_PASS": "",
        }
        with patch.dict(os.environ, env):
            with pytest.raises(ValueError, match="PLATFORM_ADMIN_PASS"):
                generate_bootstrap_sql()

    def test_bootstrap_raises_if_tenant_name_missing(self):
        """Bootstrap raises clear error if SEED_TENANT_NAME is not set."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "",
            "PLATFORM_ADMIN_EMAIL": "admin@test.com",
            "PLATFORM_ADMIN_PASS": "password",
        }
        with patch.dict(os.environ, env):
            with pytest.raises(ValueError, match="SEED_TENANT_NAME"):
                generate_bootstrap_sql()

    def test_bootstrap_tenant_has_enterprise_plan(self):
        """Default tenant should have enterprise plan in params."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "acme",
            "PLATFORM_ADMIN_EMAIL": "admin@acme.com",
            "PLATFORM_ADMIN_PASS": "password-123",
        }
        with patch.dict(os.environ, env):
            statements = generate_bootstrap_sql()

        _, tenant_params = statements[0]
        assert tenant_params["plan"] == "enterprise"

    def test_bootstrap_tenant_has_active_status(self):
        """Default tenant should have active status in params."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "acme",
            "PLATFORM_ADMIN_EMAIL": "admin@acme.com",
            "PLATFORM_ADMIN_PASS": "password-123",
        }
        with patch.dict(os.environ, env):
            statements = generate_bootstrap_sql()

        _, tenant_params = statements[0]
        assert tenant_params["status"] == "active"

    def test_bootstrap_uses_parameterized_queries(self):
        """SQL templates use :param placeholders, not interpolated values — SQL injection proof."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "test'; DROP TABLE tenants;--",
            "PLATFORM_ADMIN_EMAIL": "admin@test.com",
            "PLATFORM_ADMIN_PASS": "password",
        }
        with patch.dict(os.environ, env):
            statements = generate_bootstrap_sql()

        tenant_sql, tenant_params = statements[0]
        # The SQL template must use :param placeholders, not the raw value
        sql_str = str(tenant_sql)
        assert ":name" in sql_str
        assert "DROP TABLE" not in sql_str
        # The injection attempt is safely stored in params (passed to DB driver, not parsed as SQL)
        assert tenant_params["name"] == "test'; DROP TABLE tenants;--"


class TestSeedDataTemplates:
    """Seed data template validation."""

    def test_seed_templates_exist(self):
        """Verify seed data template module is importable."""
        from app.core.seeds import SEED_TEMPLATES

        assert isinstance(SEED_TEMPLATES, dict)
        assert len(SEED_TEMPLATES) > 0

    def test_seed_templates_have_required_fields(self):
        """Each seed template must have name, description, and agent_config."""
        from app.core.seeds import SEED_TEMPLATES

        for template_name, template in SEED_TEMPLATES.items():
            assert "name" in template, f"Template {template_name} missing 'name'"
            assert (
                "description" in template
            ), f"Template {template_name} missing 'description'"
            assert (
                "system_prompt" in template
            ), f"Template {template_name} missing 'system_prompt'"

    def test_seed_templates_include_hr_policy(self):
        """HR Policy agent template exists."""
        from app.core.seeds import SEED_TEMPLATES

        assert "hr_policy" in SEED_TEMPLATES

    def test_seed_templates_include_it_helpdesk(self):
        """IT Helpdesk agent template exists."""
        from app.core.seeds import SEED_TEMPLATES

        assert "it_helpdesk" in SEED_TEMPLATES

    def test_seed_templates_include_procurement(self):
        """Procurement agent template exists."""
        from app.core.seeds import SEED_TEMPLATES

        assert "procurement" in SEED_TEMPLATES

    def test_seed_templates_include_onboarding(self):
        """Onboarding agent template exists."""
        from app.core.seeds import SEED_TEMPLATES

        assert "onboarding" in SEED_TEMPLATES

    def test_seed_template_system_prompts_not_empty(self):
        """System prompts must not be empty."""
        from app.core.seeds import SEED_TEMPLATES

        for name, template in SEED_TEMPLATES.items():
            prompt = template["system_prompt"]
            assert (
                len(prompt.strip()) > 50
            ), f"Template {name} system_prompt too short ({len(prompt)} chars)"
