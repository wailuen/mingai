"""
Platform admin bootstrap (INFRA-066).

Generates parameterized SQL to seed the initial tenant and platform admin user.
All credentials from environment variables - NEVER hardcoded.

Returns (sqlalchemy.text, params_dict) tuples for safe parameterized execution.
"""
import os
from typing import Any

import bcrypt
import structlog
from sqlalchemy import text

logger = structlog.get_logger()


def _hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Returns the hash as a UTF-8 string suitable for database storage.
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def generate_bootstrap_sql() -> list[tuple[Any, dict]]:
    """
    Generate parameterized SQL statements to bootstrap the platform.

    Creates:
    1. Default tenant from SEED_TENANT_NAME
    2. Platform admin user from PLATFORM_ADMIN_EMAIL/PASS

    Raises ValueError if any required environment variable is missing.

    Returns:
        List of (sqlalchemy.text, params_dict) tuples for safe parameterized
        execution via ``await session.execute(sql, params)``.
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

    slug = tenant_name.lower().replace(" ", "-").replace("_", "-")
    password_hash = _hash_password(admin_pass)
    email = admin_email.lower()

    statements: list[tuple[Any, dict]] = []

    # 1. Create the seed tenant (parameterized)
    statements.append(
        (
            text(
                "INSERT INTO tenants (name, slug, plan, status, primary_contact_email) "
                "VALUES (:name, :slug, :plan, :status, :email) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {
                "name": tenant_name,
                "slug": slug,
                "plan": "enterprise",
                "status": "active",
                "email": email,
            },
        )
    )

    # 2. Create the platform admin user (parameterized)
    statements.append(
        (
            text(
                "INSERT INTO users (tenant_id, email, name, password_hash, role, status) "
                "SELECT t.id, :email, :name, :password_hash, :role, :status "
                "FROM tenants t WHERE t.slug = :slug "
                "ON CONFLICT (tenant_id, email) DO NOTHING"
            ),
            {
                "email": email,
                "name": "Platform Admin",
                "password_hash": password_hash,
                "role": "platform_admin",
                "status": "active",
                "slug": slug,
            },
        )
    )

    logger.info(
        "bootstrap_sql_generated",
        tenant_name=tenant_name,
        admin_email=admin_email,
        statement_count=len(statements),
    )

    return statements
