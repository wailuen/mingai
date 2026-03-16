"""
mingai Backend API - FastAPI Application Entry Point

Port: 8022
Framework: FastAPI + Kailash SDK (DataFlow + Nexus + Kaizen)

All configuration from .env - never hardcode secrets or model names.
"""
import asyncio
import os
import traceback
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.health import build_health_response, build_ready_response
from app.core.logging import setup_logging
from app.core.middleware import setup_middleware
from app.core.tenant_middleware import TenantContextMiddleware
from app.modules.auth.jwt import generate_request_id

# Configure structured logging before anything else
setup_logging(json_output=os.environ.get("LOG_FORMAT", "json") == "json")

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# GAP-014: Request body size limit (10 MB)
# ---------------------------------------------------------------------------

_MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024  # 10 MB


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds the configured limit.

    This is a fail-safe guard. Actual file-size validation for document
    uploads also happens at the route layer, but this middleware stops
    oversized payloads before they are read into memory at all.
    """

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > _MAX_REQUEST_BODY_BYTES:
                    logger.warning(
                        "request_body_too_large",
                        content_length=content_length,
                        limit_bytes=_MAX_REQUEST_BODY_BYTES,
                        path=str(request.url.path),
                    )
                    return Response(
                        content="Request body too large",
                        status_code=413,
                        media_type="text/plain",
                    )
            except ValueError:
                # Malformed Content-Length — let downstream reject it naturally
                pass
        return await call_next(request)


# ---------------------------------------------------------------------------
# GAP-033: Graceful shutdown via lifespan context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup then graceful shutdown.

    Replaces deprecated @app.on_event("startup") / @app.on_event("shutdown").
    """
    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------
    logger.info("application_starting", version="1.0.0")

    # Dispose stale pool connections so all new connections belong to this
    # event loop. This is a no-op in production (pool is fresh) but prevents
    # asyncpg "another operation in progress" errors in tests where multiple
    # TestClient instances are created in different event loops.
    from app.core.session import engine as _engine

    await _engine.dispose()

    # Validate critical env vars are set
    required_vars = ["DATABASE_URL", "REDIS_URL", "JWT_SECRET_KEY", "FRONTEND_URL"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        logger.error(
            "missing_required_env_vars",
            missing=missing,
            hint="Check .env file and .env.example for required variables",
        )

    # AI-048: Start agent health monitor background job.
    # Recomputes trust scores for all published agents every hour.
    _health_monitor_task = None
    try:
        from app.core.session import async_session_factory
        from app.modules.har.health_monitor import AgentHealthMonitor

        monitor = AgentHealthMonitor(
            db_session_factory=async_session_factory, interval_seconds=3600
        )
        _health_monitor_task = asyncio.create_task(monitor.start())
        logger.info("agent_health_monitor_scheduled", interval_seconds=3600)
    except Exception as exc:
        logger.warning(
            "agent_health_monitor_startup_failed",
            error=str(exc),
        )

    # INFRA-026: Warm up glossary cache for all active tenants.
    # Lazy import to avoid import errors if Redis/DB not ready at module load.
    # Failure never blocks startup.
    try:
        from app.modules.glossary.warmup import warm_up_glossary_cache

        await warm_up_glossary_cache()
    except Exception as exc:
        logger.warning(
            "glossary_warmup_startup_failed",
            error=str(exc),
        )

    # CACHE-014: Start semantic cache cleanup background job (runs hourly).
    _semantic_cache_cleanup_task = None
    try:
        from app.core.cache.cleanup_job import run_semantic_cache_cleanup_loop

        _semantic_cache_cleanup_task = asyncio.create_task(
            run_semantic_cache_cleanup_loop()
        )
        logger.info("semantic_cache_cleanup_scheduled", interval_seconds=3600)
    except Exception as exc:
        logger.warning(
            "semantic_cache_cleanup_startup_failed",
            error=str(exc),
        )

    # CACHE-006: Start query embedding warming scheduler (fires daily at 03:00 UTC).
    _query_warming_task = None
    try:
        from app.modules.cache.query_warming import run_query_warming_scheduler

        _query_warming_task = asyncio.create_task(run_query_warming_scheduler())
        logger.info("query_warming_scheduler_started", schedule="daily at 03:00 UTC")
    except Exception as exc:
        logger.warning(
            "query_warming_scheduler_startup_failed",
            error=str(exc),
        )

    # PA-007: Start tenant health score batch job scheduler (fires daily at 02:00 UTC).
    _health_score_task = None
    try:
        from app.modules.platform.health_score_job import run_health_score_scheduler

        _health_score_task = asyncio.create_task(run_health_score_scheduler())
        logger.info("health_score_scheduler_started", schedule="daily at 02:00 UTC")
    except Exception as exc:
        logger.warning(
            "health_score_scheduler_startup_failed",
            error=str(exc),
        )

    # PA-012: Start token attribution / cost summary batch job (fires daily at 03:30 UTC).
    _cost_summary_task = None
    try:
        from app.modules.platform.cost_summary_job import start_cost_summary_scheduler

        _cost_summary_task = asyncio.create_task(start_cost_summary_scheduler())
        logger.info("cost_summary_scheduler_started", schedule="daily at 03:30 UTC")
    except Exception as exc:
        logger.warning(
            "cost_summary_scheduler_startup_failed",
            error=str(exc),
        )

    # PA-014: Start Azure Cost Management pull job (fires daily at 03:45 UTC).
    _azure_cost_task = None
    try:
        from app.modules.platform.azure_cost_job import start_azure_cost_scheduler

        _azure_cost_task = asyncio.create_task(start_azure_cost_scheduler())
        logger.info("azure_cost_scheduler_started", schedule="daily at 03:45 UTC")
    except Exception as exc:
        logger.warning(
            "azure_cost_scheduler_startup_failed",
            error=str(exc),
        )

    # PA-015: Start cost alert evaluation job (fires daily at 04:00 UTC).
    _cost_alert_task = None
    try:
        from app.modules.platform.cost_alert_job import start_cost_alert_scheduler

        _cost_alert_task = asyncio.create_task(start_cost_alert_scheduler())
        logger.info("cost_alert_scheduler_started", schedule="daily at 04:00 UTC")
    except Exception as exc:
        logger.warning(
            "cost_alert_scheduler_startup_failed",
            error=str(exc),
        )

    # TA-020: Seed agent templates into agent_templates table on startup.
    try:
        from app.core.seeds import seed_agent_templates

        await seed_agent_templates()
    except Exception as exc:
        logger.warning("agent_templates_seed_failed", error=str(exc))

    # TA-013: Start glossary miss signals batch job (fires daily at 04:30 UTC).
    _miss_signals_task = None
    try:
        from app.modules.glossary.miss_signals_job import run_miss_signals_scheduler

        _miss_signals_task = asyncio.create_task(run_miss_signals_scheduler())
        logger.info("miss_signals_scheduler_started", schedule="daily at 04:30 UTC")
    except Exception as exc:
        logger.warning(
            "miss_signals_scheduler_startup_failed",
            error=str(exc),
        )

    # TA-017: Start credential expiry monitoring job (fires daily at 05:00 UTC).
    _credential_expiry_task = None
    try:
        from app.modules.documents.credential_expiry_job import (
            run_credential_expiry_scheduler,
        )

        _credential_expiry_task = asyncio.create_task(run_credential_expiry_scheduler())
        logger.info(
            "credential_expiry_scheduler_started", schedule="daily at 05:00 UTC"
        )
    except Exception as exc:
        logger.warning(
            "credential_expiry_scheduler_startup_failed",
            error=str(exc),
        )

    logger.info("application_started")

    # ------------------------------------------------------------------
    # Hand control to the application
    # ------------------------------------------------------------------
    yield

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    logger.info("application_shutting_down")

    # Cancel background tasks
    if _health_monitor_task is not None and not _health_monitor_task.done():
        _health_monitor_task.cancel()
        try:
            await _health_monitor_task
        except asyncio.CancelledError:
            pass
        logger.info("agent_health_monitor_stopped")

    if (
        _semantic_cache_cleanup_task is not None
        and not _semantic_cache_cleanup_task.done()
    ):
        _semantic_cache_cleanup_task.cancel()
        try:
            await _semantic_cache_cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("semantic_cache_cleanup_stopped")

    if _query_warming_task is not None and not _query_warming_task.done():
        _query_warming_task.cancel()
        try:
            await _query_warming_task
        except asyncio.CancelledError:
            pass
        logger.info("query_warming_scheduler_stopped")

    if _health_score_task is not None and not _health_score_task.done():
        _health_score_task.cancel()
        try:
            await _health_score_task
        except asyncio.CancelledError:
            pass
        logger.info("health_score_scheduler_stopped")

    if _cost_summary_task is not None and not _cost_summary_task.done():
        _cost_summary_task.cancel()
        try:
            await _cost_summary_task
        except asyncio.CancelledError:
            pass
        logger.info("cost_summary_scheduler_stopped")

    if _azure_cost_task is not None and not _azure_cost_task.done():
        _azure_cost_task.cancel()
        try:
            await _azure_cost_task
        except asyncio.CancelledError:
            pass
        logger.info("azure_cost_scheduler_stopped")

    if _cost_alert_task is not None and not _cost_alert_task.done():
        _cost_alert_task.cancel()
        try:
            await _cost_alert_task
        except asyncio.CancelledError:
            pass
        logger.info("cost_alert_scheduler_stopped")

    if _miss_signals_task is not None and not _miss_signals_task.done():
        _miss_signals_task.cancel()
        try:
            await _miss_signals_task
        except asyncio.CancelledError:
            pass
        logger.info("miss_signals_scheduler_stopped")

    if _credential_expiry_task is not None and not _credential_expiry_task.done():
        _credential_expiry_task.cancel()
        try:
            await _credential_expiry_task
        except asyncio.CancelledError:
            pass
        logger.info("credential_expiry_scheduler_stopped")

    # Close Redis connections
    try:
        from app.core.redis_client import close_redis

        await close_redis()
        logger.info("redis_connections_closed")
    except Exception as exc:
        logger.warning("redis_close_failed", error=str(exc))

    # Close DB connection pool
    try:
        from app.core.session import engine as _engine

        await _engine.dispose()
        logger.info("db_connection_pool_disposed")
    except Exception as exc:
        logger.warning("db_pool_dispose_failed", error=str(exc))

    logger.info("graceful_shutdown_complete")


app = FastAPI(
    title="mingai API",
    description="Enterprise RAG Platform - Multi-Tenant Backend",
    version="1.0.0",
    docs_url="/api/docs" if os.environ.get("DEBUG", "").lower() == "true" else None,
    redoc_url=None,
    lifespan=lifespan,
)

# Setup middleware: CORS, security headers, request ID, rate limiting
setup_middleware(app)

# INFRA-048: Tenant context resolution — after CORS/security headers,
# before route handlers.  Populates request.state.tenant_id and
# request.state.scope from the JWT (or "default" in single-tenant mode).
app.add_middleware(TenantContextMiddleware)

# GAP-014: Request body size limit (must be added after setup_middleware so it
# wraps the full middleware stack — added last so it executes first in the chain)
app.add_middleware(RequestSizeLimitMiddleware)


# ---------------------------------------------------------------------------
# Error handlers (GAP-009 / API-122)
# ---------------------------------------------------------------------------

# HTTP status code → error code string mapping
_HTTP_ERROR_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


def _get_request_id(request: Request) -> str:
    """Read X-Request-ID from request header, or generate a fresh UUID."""
    return request.headers.get("X-Request-ID") or str(uuid.uuid4())


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Handler for HTTPException — returns consistent error envelope.

    Format: {"error": "code", "message": "...", "request_id": "uuid", "details": {}}
    """
    request_id = _get_request_id(request)
    status_code = exc.status_code
    error_code = _HTTP_ERROR_CODES.get(status_code, f"error_{status_code}")

    # detail may be a string or a dict from FastAPI; normalise to string for message
    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("message", str(detail))
    else:
        message = str(detail) if detail else exc.__class__.__name__

    # Include "detail" for backward compatibility with tests and existing clients
    # that read resp.json()["detail"]. New consumers should use "message".
    return JSONResponse(
        status_code=status_code,
        content={
            "error": error_code,
            "message": message,
            "detail": message,
            "request_id": request_id,
            "details": {},
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handler for Pydantic/FastAPI validation errors — returns field-level details.

    Format: {"error": "validation_error", "message": "...", "request_id": "uuid",
             "details": {"field_errors": [...]}}
    """
    request_id = _get_request_id(request)
    field_errors = [
        {
            "loc": list(err.get("loc", [])),
            "msg": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "Request validation failed",
            "request_id": request_id,
            "details": {"field_errors": field_errors},
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all handler for unexpected exceptions.

    Logs full traceback server-side; returns generic 500 with no internal details.
    Format: {"error": "internal_error", "message": "Internal server error",
             "request_id": "uuid", "details": {}}
    """
    request_id = _get_request_id(request)

    logger.error(
        "unhandled_exception",
        error=str(exc),
        error_type=type(exc).__name__,
        request_id=request_id,
        path=str(request.url.path),
        traceback=traceback.format_exc(),
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "Internal server error",
            "request_id": request_id,
            "details": {},
        },
    )


# Health check endpoint (INFRA-043) - no auth required
@app.get("/health", tags=["health"])
@app.get("/api/v1/health", tags=["health"])
async def health_check():
    """
    Platform health check.

    Returns component-level status for database, Redis, and search.
    Used by load balancers and monitoring systems.
    No authentication required.
    """
    db_ok = False
    redis_ok = False
    search_ok = True

    # Real database ping via SQLAlchemy async engine
    try:
        from sqlalchemy import text as sa_text

        from app.core.session import engine

        async with engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        db_ok = True
    except Exception as e:
        logger.warning("health_check_db_failed", error=str(e))

    # Real Redis ping
    try:
        from app.core.redis_client import get_redis

        redis = get_redis()
        await redis.ping()
        redis_ok = True
    except Exception as e:
        logger.warning("health_check_redis_failed", error=str(e))

    response = build_health_response(
        database_ok=db_ok,
        redis_ok=redis_ok,
        search_ok=search_ok,
    )

    status_code = 200 if response["status"] == "healthy" else 503
    return JSONResponse(content=response, status_code=status_code)


# Ready check endpoint (INFRA-055) - exposes circuit breaker state
@app.get("/ready", tags=["health"])
@app.get("/api/v1/ready", tags=["health"])
async def ready_check():
    """
    Readiness probe — includes circuit breaker state (INFRA-055).

    Returns component status plus any open LLM circuit breakers.
    A degraded status indicates the service can still accept traffic
    but some LLM slots may be temporarily unavailable.
    No authentication required.
    """
    db_ok = False
    redis_ok = False

    try:
        from sqlalchemy import text as sa_text

        from app.core.session import engine

        async with engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        db_ok = True
    except Exception as e:
        logger.warning("ready_check_db_failed", error=str(e))

    try:
        from app.core.redis_client import get_redis

        redis = get_redis()
        await redis.ping()
        redis_ok = True
    except Exception as e:
        logger.warning("ready_check_redis_failed", error=str(e))

    # Collect circuit breaker states — best-effort, never blocks readiness
    circuit_breakers: dict = {}
    try:
        if redis_ok:
            from app.core.circuit_breaker import get_circuit_breaker
            from app.core.redis_client import get_redis as _get_redis

            cb = get_circuit_breaker()
            r = _get_redis()
            # Scan for all CB keys: mingai:*:cb:*
            cb_keys = []
            async for key in r.scan_iter("mingai:*:cb:*"):
                cb_keys.append(key)
            for cb_key in cb_keys:
                # Parse tenant_id and slot from key pattern:
                # mingai:{tenant_id}:cb:{slot}
                parts = cb_key.split(":")
                if len(parts) >= 4:
                    tenant_id_part = parts[1]
                    slot_part = ":".join(parts[3:])
                    state = await cb.get_state(tenant_id_part, slot_part)
                    circuit_breakers[f"{tenant_id_part}:{slot_part}"] = state
    except Exception as e:
        logger.warning("ready_check_cb_scan_failed", error=str(e))

    response = build_ready_response(
        database_ok=db_ok,
        redis_ok=redis_ok,
        circuit_breakers=circuit_breakers,
    )

    status_code = 200 if response["status"] in ("ready", "degraded") else 503
    return JSONResponse(content=response, status_code=status_code)


# Include API router with all module endpoints
from app.api.router import router as api_router

app.include_router(api_router)
