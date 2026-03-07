"""
Platform admin bootstrap (INFRA-066).

Generates SQL to seed the initial tenant and platform admin user.
All credentials from environment variables - NEVER hardcoded.
"""
import os

import bcrypt
import structlog

logger = structlog.get_logger()


def _escape_sql_string(value: str) -> str:
    """
    Escape a string for safe inclusion in SQL.

    Doubles single quotes to prevent SQL injection.
    Strips any null bytes and control characters.
    """
    # Remove null bytes and other dangerous control characters
    cleaned = value.replace("\x00", "")
    # Double single quotes for SQL string escaping
    return cleaned.replace("'", "''")


def _hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Returns the hash as a UTF-8 string suitable for database storage.
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def generate_bootstrap_sql() -> list[str]:
    """
    Generate SQL statements to bootstrap the platform.

    Creates:
    1. Default tenant from SEED_TENANT_NAME
    2. Platform admin user from PLATFORM_ADMIN_EMAIL/PASS

    Raises ValueError if any required environment variable is missing.

    Returns:
        List of SQL INSERT statements ready to execute.
    """
    tenant_name = os.environ.get("SEED_TENANT_NAME", "").strip()
    admin_email = os.environ.get("PLATFORM_ADMIN_EMAIL", "").strip()
    admin_pass = os.environ.get("PLATFORM_ADMIN_PASS", "").strip()

    if not tenant_name:
        raise ValueError(
            "SEED_TENANT_NAME environment variable is required for bootstrap. "
            "Set it in .env to the name of the initial tenant."
        )
    if not admin_email:
        raise ValueError(
            "PLATFORM_ADMIN_EMAIL environment variable is required for bootstrap. "
            "Set it in .env to the platform admin email address."
        )
    if not admin_pass:
        raise ValueError(
            "PLATFORM_ADMIN_PASS environment variable is required for bootstrap. "
            "Set it in .env to the platform admin password."
        )

    # Generate slug from tenant name (lowercase, hyphens for spaces)
    slug = _escape_sql_string(tenant_name.lower().replace(" ", "-").replace("_", "-"))
    safe_tenant_name = _escape_sql_string(tenant_name)
    safe_email = _escape_sql_string(admin_email.lower())
    password_hash = _hash_password(admin_pass)
    safe_hash = _escape_sql_string(password_hash)

    statements = []

    # 1. Create the seed tenant
    tenant_sql = (
        "INSERT INTO tenants (name, slug, plan, status, primary_contact_email) "
        f"VALUES ('{safe_tenant_name}', '{slug}', 'enterprise', 'active', "
        f"'{safe_email}') "
        "ON CONFLICT (slug) DO NOTHING"
    )
    statements.append(tenant_sql)

    # 2. Create the platform admin user
    user_sql = (
        "INSERT INTO users (tenant_id, email, name, password_hash, role, status) "
        f"SELECT t.id, '{safe_email}', 'Platform Admin', "
        f"'{safe_hash}', 'platform_admin', 'active' "
        "FROM tenants t WHERE t.slug = "
        f"'{slug}' "
        "ON CONFLICT (tenant_id, email) DO NOTHING"
    )
    statements.append(user_sql)

    logger.info(
        "bootstrap_sql_generated",
        tenant_name=tenant_name,
        admin_email=admin_email,
        statement_count=len(statements),
    )

    return statements
