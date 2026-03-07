"""
INFRA-037: Glossary pretranslation rollout flag.

Reads per-tenant config from tenant_configs table (or Redis cache).
Default: False (legacy Layer 6 injection preserved).
Platform admin toggles via tenant_configs.glossary_pretranslation_enabled.
"""
import structlog
from sqlalchemy import text

logger = structlog.get_logger()

GLOSSARY_PRETRANSLATION_CONFIG_KEY = "glossary_pretranslation_enabled"


async def is_glossary_pretranslation_enabled(tenant_id: str, db) -> bool:
    """
    Check if glossary pretranslation is enabled for a tenant.

    Reads from tenant_configs table. Default is False if not configured.
    Changes take effect within 60 seconds via config cache TTL.

    Args:
        tenant_id: The tenant to check.
        db: Async database session.

    Returns:
        True if pretranslation (GlossaryExpander) is enabled, False for legacy Layer 6.
    """
    try:
        result = await db.execute(
            text(
                "SELECT config_value FROM tenant_configs "
                "WHERE tenant_id = :tenant_id AND config_key = :config_key"
            ),
            {"tenant_id": tenant_id, "config_key": GLOSSARY_PRETRANSLATION_CONFIG_KEY},
        )
        row = result.fetchone()
        if row is None:
            return False
        # config_value is stored as JSONB text, parse boolean
        value = row[0]
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
        return False  # Safe default: preserve legacy behavior


async def set_glossary_pretranslation_enabled(
    tenant_id: str, enabled: bool, db
) -> None:
    """
    Set the glossary pretranslation flag for a tenant.

    Upserts into tenant_configs. Changes take effect within 60 seconds.

    Args:
        tenant_id: The tenant to configure.
        enabled: True to enable pretranslation, False for legacy mode.
        db: Async database session.
    """
    await db.execute(
        text(
            "INSERT INTO tenant_configs (tenant_id, config_key, config_value) "
            "VALUES (:tenant_id, :config_key, :config_value) "
            "ON CONFLICT (tenant_id, config_key) "
            "DO UPDATE SET config_value = :config_value"
        ),
        {
            "tenant_id": tenant_id,
            "config_key": GLOSSARY_PRETRANSLATION_CONFIG_KEY,
            "config_value": enabled,
        },
    )
    await db.commit()
    logger.info(
        "glossary_pretranslation_flag_set",
        tenant_id=tenant_id,
        enabled=enabled,
    )
