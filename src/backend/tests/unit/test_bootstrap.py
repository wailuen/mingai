"""
Unit tests for platform admin bootstrap (INFRA-066).

Tests seed data generation and platform bootstrap SQL.
Tier 1: Fast, isolated, no database required.
"""
import os
from unittest.mock import patch

import pytest


class TestBootstrapSQLGeneration:
    """INFRA-066: Platform admin bootstrap SQL tests."""

    def test_bootstrap_generates_tenant_insert(self):
        """Bootstrap generates SQL to insert the default tenant."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "acme-corp",
            "PLATFORM_ADMIN_EMAIL": "admin@acme.com",
            "PLATFORM_ADMIN_PASS": "secure-pass-123",
        }
        with patch.dict(os.environ, env):
            sql_statements = generate_bootstrap_sql()

        # Should have at least: tenant insert, user insert
        assert len(sql_statements) >= 2

        # First statement should be tenant creation
        tenant_sql = sql_statements[0]
        assert "INSERT INTO tenants" in tenant_sql
        assert "acme-corp" in tenant_sql

    def test_bootstrap_generates_admin_user_insert(self):
        """Bootstrap generates SQL to insert the platform admin user."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "acme-corp",
            "PLATFORM_ADMIN_EMAIL": "admin@acme.com",
            "PLATFORM_ADMIN_PASS": "secure-pass-123",
        }
        with patch.dict(os.environ, env):
            sql_statements = generate_bootstrap_sql()

        user_sql = sql_statements[1]
        assert "INSERT INTO users" in user_sql
        assert "admin@acme.com" in user_sql
        assert "platform_admin" in user_sql

    def test_bootstrap_never_includes_raw_password(self):
        """Password must be hashed - raw password never appears in SQL."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "test-tenant",
            "PLATFORM_ADMIN_EMAIL": "admin@test.com",
            "PLATFORM_ADMIN_PASS": "my-secret-password-123",
        }
        with patch.dict(os.environ, env):
            sql_statements = generate_bootstrap_sql()

        all_sql = " ".join(sql_statements)
        assert "my-secret-password-123" not in all_sql

    def test_bootstrap_password_is_bcrypt_hashed(self):
        """Password in SQL should be a bcrypt hash."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "test-tenant",
            "PLATFORM_ADMIN_EMAIL": "admin@test.com",
            "PLATFORM_ADMIN_PASS": "test-password",
        }
        with patch.dict(os.environ, env):
            sql_statements = generate_bootstrap_sql()

        user_sql = sql_statements[1]
        # bcrypt hashes start with $2b$ or $2a$
        assert "$2b$" in user_sql or "$2a$" in user_sql

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
        """Default tenant should have enterprise plan."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "acme",
            "PLATFORM_ADMIN_EMAIL": "admin@acme.com",
            "PLATFORM_ADMIN_PASS": "password-123",
        }
        with patch.dict(os.environ, env):
            sql_statements = generate_bootstrap_sql()

        tenant_sql = sql_statements[0]
        assert "enterprise" in tenant_sql

    def test_bootstrap_tenant_has_active_status(self):
        """Default tenant should have active status."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "acme",
            "PLATFORM_ADMIN_EMAIL": "admin@acme.com",
            "PLATFORM_ADMIN_PASS": "password-123",
        }
        with patch.dict(os.environ, env):
            sql_statements = generate_bootstrap_sql()

        tenant_sql = sql_statements[0]
        assert "active" in tenant_sql

    def test_bootstrap_uses_parameterized_values(self):
        """SQL must use safe string escaping, not f-string interpolation."""
        from app.core.bootstrap import generate_bootstrap_sql

        env = {
            "SEED_TENANT_NAME": "test'; DROP TABLE tenants;--",
            "PLATFORM_ADMIN_EMAIL": "admin@test.com",
            "PLATFORM_ADMIN_PASS": "password",
        }
        with patch.dict(os.environ, env):
            sql_statements = generate_bootstrap_sql()

        # The tenant name should be safely escaped
        tenant_sql = sql_statements[0]
        # Single quotes in the name should be doubled (SQL escaping)
        assert "DROP TABLE" not in tenant_sql or "''" in tenant_sql


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
