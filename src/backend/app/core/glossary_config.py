"""
INFRA-037: Glossary pretranslation rollout flag.

Reads per-tenant config from tenant_configs table using config_type column.
The tenant_configs table schema: (tenant_id, config_type VARCHAR, config_data JSONB).
Default: False (inline expansion disabled unless explicitly enabled per tenant).
Platform admin toggles via tenant_configs row with config_type = 'glossary_pretranslation'.
"""
import structlog
from sqlalchemy import text

logger = structlog.get_logger()

GLOSSARY_PRETRANSLATION_CONFIG_TYPE = "glossary_pretranslation"


async def is_glossary_pretranslation_enabled(tenant_id: str, db) -> bool:
    """
    Check if glossary pretranslation is enabled for a tenant.

    Reads from tenant_configs table (config_type = 'glossary_pretranslation').
    The config_data JSONB field must contain {"enabled": true} to activate.
    Default is False if no row exists.

    Args:
        tenant_id: The tenant to check.
        db: Async database session.

    Returns:
        True if pretranslation (GlossaryExpander) is enabled, False otherwise.
    """
    try:
        result = await db.execute(
            text(
                "SELECT config_data FROM tenant_configs "
                "WHERE tenant_id = :tenant_id AND config_type = :config_type"
            ),
            {
                "tenant_id": tenant_id,
                "config_type": GLOSSARY_PRETRANSLATION_CONFIG_TYPE,
            },
        )
        row = result.fetchone()
        if row is None:
            return False
        # config_data is a JSONB dict with {"enabled": true/false}
        config_data = row[0]
        if isinstance(config_data, dict):
            value = config_data.get("enabled", False)
        elif isinstance(config_data, bool):
            value = config_data
        else:
            value = False
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)
    except Exception as exc:
        logger.warning(
            "glossary_flag_read_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )
        return False  # Safe default: disable expansion on error


async def set_glossary_pretranslation_enabled(
    tenant_id: str, enabled: bool, db
) -> None:
    """
    Set the glossary pretranslation flag for a tenant.

    Upserts a row into tenant_configs with config_type = 'glossary_pretranslation'
    and config_data = {"enabled": <bool>}. Changes take effect immediately.

    Args:
        tenant_id: The tenant to configure.
        enabled: True to enable pretranslation, False to disable.
        db: Async database session.
    """
    import json

    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (gen_random_uuid(), :tenant_id, :config_type, CAST(:config_data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) "
            "DO UPDATE SET config_data = CAST(:config_data AS jsonb)"
        ),
        {
            "tenant_id": tenant_id,
            "config_type": GLOSSARY_PRETRANSLATION_CONFIG_TYPE,
            "config_data": json.dumps({"enabled": enabled}),
        },
    )
    await db.commit()
    logger.info(
        "glossary_pretranslation_flag_set",
        tenant_id=tenant_id,
        enabled=enabled,
    )
