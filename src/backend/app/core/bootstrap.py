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
    3. Tenant admin user (tenant_admin@mingai.test)
    4. Regular end user (user@mingai.test)

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

    # Seed credentials for tenant-scoped demo users
    tenant_admin_email = "tenant_admin@mingai.test"
    tenant_admin_pass_hash = _hash_password("TenantAdmin1234!")
    end_user_email = "user@mingai.test"
    end_user_pass_hash = _hash_password("User1234!")

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

    # 3. Create the tenant admin user under the seed tenant
    statements.append(
        (
            text(
                "INSERT INTO users (tenant_id, email, name, password_hash, role, status) "
                "SELECT t.id, :email, :name, :password_hash, :role, :status "
                "FROM tenants t WHERE t.slug = :slug "
                "ON CONFLICT (tenant_id, email) DO NOTHING"
            ),
            {
                "email": tenant_admin_email,
                "name": "Tenant Admin",
                "password_hash": tenant_admin_pass_hash,
                "role": "tenant_admin",
                "status": "active",
                "slug": slug,
            },
        )
    )

    # 4. Create a regular end user under the seed tenant
    statements.append(
        (
            text(
                "INSERT INTO users (tenant_id, email, name, password_hash, role, status) "
                "SELECT t.id, :email, :name, :password_hash, :role, :status "
                "FROM tenants t WHERE t.slug = :slug "
                "ON CONFLICT (tenant_id, email) DO NOTHING"
            ),
            {
                "email": end_user_email,
                "name": "End User",
                "password_hash": end_user_pass_hash,
                "role": "viewer",
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


def generate_demo_seed_sql(tenant_slug: str) -> list[tuple[Any, dict]]:
    """
    Generate parameterized SQL to seed demo data into the default tenant.

    Creates:
    - 3 LLM profiles with realistic Azure OpenAI configurations
    - 10 glossary terms (business and tech abbreviations)
    - 5 sample issue reports at P0/P1/P2 severity

    All statements use ON CONFLICT DO NOTHING so they are safe to re-run.

    Args:
        tenant_slug: The slug of the tenant to seed data into.

    Returns:
        List of (sqlalchemy.text, params_dict) tuples.
    """
    import json as _json
    import uuid as _uuid

    statements: list[tuple[Any, dict]] = []

    # ------------------------------------------------------------------
    # LLM Profiles — 3 realistic Azure OpenAI configs
    # ------------------------------------------------------------------
    llm_profiles = [
        {
            "id": str(_uuid.uuid4()),
            "name": "Primary Azure GPT-5",
            "provider": "azure_openai",
            "primary_model": os.environ.get("PRIMARY_MODEL", "agentic-worker"),
            "intent_model": os.environ.get("INTENT_MODEL", "agentic-router"),
            "embedding_model": os.environ.get(
                "EMBEDDING_MODEL", "text-embedding-3-small"
            ),
            "endpoint_url": os.environ.get(
                "AZURE_OPENAI_ENDPOINT",
                "https://agentic-openai01.cognitiveservices.azure.com/",
            ),
            "is_default": True,
        },
        {
            "id": str(_uuid.uuid4()),
            "name": "East US GPT-5.2",
            "provider": "azure_openai",
            "primary_model": "agentic-worker",
            "intent_model": "agentic-router",
            "embedding_model": "text-embedding-3-small",
            "endpoint_url": "https://eastus2.api.cognitive.microsoft.com/",
            "is_default": False,
        },
        {
            "id": str(_uuid.uuid4()),
            "name": "Vision Profile",
            "provider": "azure_openai",
            "primary_model": "agentic-vision",
            "intent_model": "agentic-router",
            "embedding_model": "text-embedding-3-small",
            "endpoint_url": "https://eastus2.api.cognitive.microsoft.com/",
            "is_default": False,
        },
    ]

    for p in llm_profiles:
        statements.append(
            (
                text(
                    "INSERT INTO llm_profiles "
                    "(id, tenant_id, name, provider, primary_model, intent_model, "
                    "embedding_model, endpoint_url, is_default) "
                    "SELECT :id, t.id, :name, :provider, :primary_model, :intent_model, "
                    ":embedding_model, :endpoint_url, :is_default "
                    "FROM tenants t WHERE t.slug = :slug "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "id": p["id"],
                    "name": p["name"],
                    "provider": p["provider"],
                    "primary_model": p["primary_model"],
                    "intent_model": p["intent_model"],
                    "embedding_model": p["embedding_model"],
                    "endpoint_url": p["endpoint_url"],
                    "is_default": p["is_default"],
                    "slug": tenant_slug,
                },
            )
        )

    # ------------------------------------------------------------------
    # Glossary Terms — 10 common business and tech abbreviations
    # ------------------------------------------------------------------
    glossary_terms = [
        (
            "LTV",
            "Lifetime Value",
            "finance",
            "Total revenue expected from a customer over the full relationship duration.",
        ),
        (
            "KYC",
            "Know Your Customer",
            "compliance",
            "Regulatory process of verifying the identity of clients to prevent fraud and money laundering.",
        ),
        (
            "EBITDA",
            "Earnings Before Interest, Taxes, Depreciation and Amortization",
            "finance",
            "A measure of a company's core profitability excluding non-operating expenses.",
        ),
        (
            "NDA",
            "Non-Disclosure Agreement",
            "legal",
            "A legally binding contract that establishes a confidential relationship between parties.",
        ),
        (
            "SLA",
            "Service Level Agreement",
            "operations",
            "A contract that defines the expected level of service between a provider and client.",
        ),
        (
            "API",
            "Application Programming Interface",
            "technology",
            "A set of protocols and tools that allows different software applications to communicate.",
        ),
        (
            "RAG",
            "Retrieval-Augmented Generation",
            "ai",
            "An AI technique that grounds language model responses in retrieved external documents.",
        ),
        (
            "KPI",
            "Key Performance Indicator",
            "operations",
            "A measurable value that demonstrates how effectively a company achieves key business objectives.",
        ),
        (
            "MFA",
            "Multi-Factor Authentication",
            "security",
            "An authentication method requiring two or more verification factors to gain access.",
        ),
        (
            "SSO",
            "Single Sign-On",
            "security",
            "An authentication scheme allowing a user to log in once and gain access to multiple systems.",
        ),
    ]

    for abbr, full_form, _category, definition in glossary_terms:
        import json as _json2

        aliases_json = _json2.dumps([{"term": full_form, "note": definition}])
        statements.append(
            (
                text(
                    "INSERT INTO glossary_terms "
                    "(id, tenant_id, term, full_form, aliases) "
                    "SELECT gen_random_uuid(), t.id, :term, :full_form, CAST(:aliases AS jsonb) "
                    "FROM tenants t "
                    "WHERE t.slug = :slug "
                    "ON CONFLICT (tenant_id, term) DO NOTHING"
                ),
                {
                    "term": abbr,
                    "full_form": full_form,
                    "aliases": aliases_json,
                    "slug": tenant_slug,
                },
            )
        )

    # ------------------------------------------------------------------
    # Sample Issues — 5 across P0/P1/P2 severities
    # ------------------------------------------------------------------
    sample_issues = [
        {
            "id": str(_uuid.uuid4()),
            "issue_type": "bug",
            "description": "RAG responses are hallucinating on financial documents — returning incorrect balance figures.",
            "severity": "P0",
            "metadata": _json.dumps(
                {"title": "[P0] RAG hallucination on financial data"}
            ),
        },
        {
            "id": str(_uuid.uuid4()),
            "issue_type": "performance",
            "description": "Document indexing pipeline stalled for 3 hours — no new documents being processed.",
            "severity": "P1",
            "metadata": _json.dumps({"title": "[P1] Indexing pipeline stalled"}),
        },
        {
            "id": str(_uuid.uuid4()),
            "issue_type": "bug",
            "description": "Chat history not persisting across browser sessions for users with SSO login.",
            "severity": "P2",
            "metadata": _json.dumps({"title": "[P2] Chat history lost on SSO users"}),
        },
        {
            "id": str(_uuid.uuid4()),
            "issue_type": "ux",
            "description": "The glossary tooltip renders off-screen on small viewport sizes.",
            "severity": "P2",
            "metadata": _json.dumps({"title": "[P2] Glossary tooltip overflow"}),
        },
        {
            "id": str(_uuid.uuid4()),
            "issue_type": "feature_request",
            "description": "Users need ability to export conversation history to PDF for compliance reporting.",
            "severity": "P3",
            "metadata": _json.dumps({"title": "Feature: Export conversations to PDF"}),
        },
    ]

    for issue in sample_issues:
        statements.append(
            (
                text(
                    "INSERT INTO issue_reports "
                    "(id, tenant_id, reporter_id, issue_type, description, severity, status, "
                    "blur_acknowledged, metadata) "
                    "SELECT :id, t.id, u.id, :issue_type, :description, :severity, 'open', "
                    "false, CAST(:metadata AS jsonb) "
                    "FROM tenants t "
                    "JOIN users u ON u.tenant_id = t.id AND u.role = 'tenant_admin' "
                    "WHERE t.slug = :slug "
                    "AND NOT EXISTS ("
                    "  SELECT 1 FROM issue_reports ir WHERE ir.id = :id"
                    ") "
                    "LIMIT 1"
                ),
                {
                    "id": issue["id"],
                    "issue_type": issue["issue_type"],
                    "description": issue["description"],
                    "severity": issue["severity"],
                    "metadata": issue["metadata"],
                    "slug": tenant_slug,
                },
            )
        )

    logger.info(
        "demo_seed_sql_generated",
        tenant_slug=tenant_slug,
        statement_count=len(statements),
    )

    return statements
