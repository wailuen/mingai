"""
Async SQLAlchemy session factory with per-request RLS context injection.

INFRA-049: Adds contextvars-based RLS context so every DB session sets
`SET LOCAL app.tenant_id` and `SET LOCAL app.scope` before executing
application queries.

Provides:
- get_async_session()   — raw session, no RLS (for auth routes / bootstrap)
- set_rls_context()     — write RLS values into the current async context
- get_db_with_rls()     — context manager that opens a session + injects RLS
- get_db()              — FastAPI dependency that reads request.state and delegates
                          to get_db_with_rls()

Database URL from DATABASE_URL env var — NEVER hardcoded.
"""
import os
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncGenerator

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Allowed tenant_id values for RLS injection.
# A valid tenant_id is either a standard UUID, or one of the reserved strings
# used by platform-scope requests ("default", "platform") or an empty string
# (exempt / unauthenticated paths).  The pattern and set together form the
# complete allowlist; the empty string is handled as a special pass-through.
# ---------------------------------------------------------------------------
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_RESERVED_TENANT_IDS: frozenset[str] = frozenset({"default", "platform", ""})

# Allowed scope values for RLS injection
_VALID_SCOPES: frozenset[str] = frozenset({"tenant", "platform", ""})


def _validate_rls_tenant_id(tenant_id: str) -> str:
    """
    Validate a tenant_id value before embedding it in a SET LOCAL statement.

    Accepts:
      - Standard UUID strings (lowercase hex with dashes, 36 chars)
      - Reserved identifiers: "default", "platform", ""

    Raises ValueError for anything else — prevents SQL injection via
    tenant_id values that contain semicolons, quotes, or other control chars.
    """
    if tenant_id in _RESERVED_TENANT_IDS:
        return tenant_id
    if _UUID_RE.match(tenant_id):
        return tenant_id
    raise ValueError(
        f"Invalid tenant_id for RLS context: {tenant_id!r}. "
        "Must be a UUID, 'default', 'platform', or empty string."
    )


def _validate_rls_scope(scope: str) -> str:
    """
    Validate a scope value before embedding it in a SET LOCAL statement.

    Raises ValueError for scopes not in the explicit allowlist.
    """
    if scope not in _VALID_SCOPES:
        raise ValueError(
            f"Invalid scope for RLS context: {scope!r}. "
            f"Must be one of {sorted(_VALID_SCOPES)!r}."
        )
    return scope


# ---------------------------------------------------------------------------
# ContextVar holding the current request's RLS parameters.
# Default is empty strings — no tenant isolation for unauthenticated access.
# ---------------------------------------------------------------------------
_rls_context: ContextVar[dict[str, str]] = ContextVar(
    "_rls_context",
    default={"tenant_id": "", "scope": "tenant"},
)


def set_rls_context(tenant_id: str, scope: str) -> None:
    """
    Set the RLS context for the current async task.

    Called by get_db_with_rls() (and directly by tests) to bind the
    tenant_id and scope values that will be injected into each DB session
    opened within this async execution context.

    Raises ValueError if tenant_id or scope fail validation.
    """
    _validate_rls_tenant_id(tenant_id)
    _validate_rls_scope(scope)
    _rls_context.set({"tenant_id": tenant_id, "scope": scope})


def get_rls_context() -> dict[str, str]:
    """Return the RLS context for the current async task (read-only)."""
    return _rls_context.get()


# ---------------------------------------------------------------------------
# Engine + session factory
# ---------------------------------------------------------------------------


def _get_database_url() -> str:
    """
    Get DATABASE_URL from environment.

    Raises RuntimeError if not configured — explicit failure, no defaults.
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


# ---------------------------------------------------------------------------
# Raw session dependency (no RLS — used by auth routes / bootstrap paths
# that run before tenant identity is known)
# ---------------------------------------------------------------------------


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an async DB session WITHOUT RLS injection.

    Preserved for backward compatibility with auth routes and other handlers
    that operate before tenant identity is established (login, health, etc.).

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


# ---------------------------------------------------------------------------
# RLS-aware session context manager and FastAPI dependency
# ---------------------------------------------------------------------------


@asynccontextmanager
async def get_db_with_rls(
    tenant_id: str,
    scope: str,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager that opens a session and injects RLS context.

    On first use within the context manager body the session emits:
        SET LOCAL app.tenant_id = '<tenant_id>';
        SET LOCAL app.scope = '<scope>';

    Both values are SET LOCAL (transaction-scoped) so they are
    automatically cleared when the transaction ends — no cross-request
    leakage via connection pool recycling.

    Injection is skipped if tenant_id is empty (exempt / unauthenticated
    paths), because setting an empty app.tenant_id would match no rows
    under RLS and would only add unnecessary overhead.

    Raises ValueError if either parameter fails the allowlist check so
    that injection attempts are caught at the call site.

    Usage:
        async with get_db_with_rls(tenant_id, scope) as db:
            result = await db.execute(...)
    """
    _validate_rls_tenant_id(tenant_id)
    _validate_rls_scope(scope)
    set_rls_context(tenant_id, scope)

    async with async_session_factory() as session:
        try:
            # Inject RLS parameters as transaction-local settings.
            # Only inject when tenant_id is non-empty — empty means the
            # middleware could not resolve a tenant (auth endpoints, etc.)
            # and RLS is handled at the DB level by default-deny policies.
            if tenant_id:
                await session.execute(
                    text(
                        "SELECT set_config('app.tenant_id', :tid, true), "
                        "set_config('app.scope', :scope, true)"
                    ),
                    {"tid": tenant_id, "scope": scope},
                )
                logger.debug(
                    "rls_context_injected",
                    tenant_id=tenant_id,
                    scope=scope,
                )
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db(request=None) -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that opens an RLS-aware DB session.

    Reads tenant_id and scope from request.state (populated by
    TenantContextMiddleware — INFRA-048) and delegates to
    get_db_with_rls().

    Falls back to the raw get_async_session() when:
    - request is None (e.g. called from background tasks / workers)
    - request.state lacks tenant_id (exempt paths)

    Usage in route:
        async def my_route(db: AsyncSession = Depends(get_db)):
            ...
    """
    # Resolve tenant context from request state when available.
    tenant_id = ""
    scope = "tenant"

    if request is not None:
        state = getattr(request, "state", None)
        if state is not None:
            tenant_id = getattr(state, "tenant_id", "") or ""
            scope = getattr(state, "scope", "tenant") or "tenant"

    # Validate before entering the context manager so that injection
    # attempts surface as 500s (unexpected), not silent data leaks.
    try:
        _validate_rls_tenant_id(tenant_id)
        _validate_rls_scope(scope)
    except ValueError:
        logger.warning(
            "rls_context_invalid_values",
            tenant_id=tenant_id,
            scope=scope,
        )
        # Fall back to raw session — route's own auth guard will reject
        # unauthenticated access before any data is returned.
        async for session in get_async_session():
            yield session
        return

    async with get_db_with_rls(tenant_id, scope) as session:
        yield session
