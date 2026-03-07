"""
Alembic environment configuration.

Loads DATABASE_URL from environment (.env file) - never hardcoded.
Supports both online (connected) and offline (SQL generation) modes.
"""
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool, text

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env before reading DATABASE_URL
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Alembic Config object
config = context.config

# Set up loggers from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Get DATABASE_URL from environment - NEVER hardcode
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is required for migrations. "
        "Set it in .env or export it before running alembic."
    )

# Alembic needs synchronous URL (replace asyncpg with psycopg2 or psycopg)
sync_url = database_url.replace("+asyncpg", "+psycopg").replace(
    "postgresql://",
    "postgresql+psycopg://"
    if "+asyncpg" not in database_url and "postgresql://" in database_url
    else "postgresql://",
)
# Handle the simple case: postgresql+asyncpg -> postgresql+psycopg
if "+asyncpg" in database_url:
    sync_url = database_url.replace("+asyncpg", "+psycopg")

config.set_main_option("sqlalchemy.url", sync_url)

# No SQLAlchemy MetaData object since we use raw SQL migrations
target_metadata = None


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    Creates a connection and runs migrations against the live database.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
