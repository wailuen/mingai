"""
Async SQLAlchemy session factory.

Provides get_async_session() for dependency injection in FastAPI routes.
Database URL from DATABASE_URL env var - NEVER hardcoded.
"""
import os

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = structlog.get_logger()


def _get_database_url() -> str:
    """
    Get DATABASE_URL from environment.

    Raises RuntimeError if not configured -- explicit failure, no defaults.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Set it in .env (e.g., postgresql+asyncpg://user:pass@localhost:5432/mingai)"
        )
    return url


engine = create_async_engine(
    _get_database_url(),
    echo=os.environ.get("SQL_ECHO", "").lower() == "true",
    pool_size=5,
    max_overflow=10,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session():
    """
    FastAPI dependency that yields an async DB session.

    Usage in route:
        async def my_route(session: AsyncSession = Depends(get_async_session)):
            result = await session.execute(text("SELECT 1"))
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
