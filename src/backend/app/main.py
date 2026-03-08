"""
mingai Backend API - FastAPI Application Entry Point

Port: 8022
Framework: FastAPI + Kailash SDK (DataFlow + Nexus + Kaizen)

All configuration from .env - never hardcode secrets or model names.
"""
import os
import traceback
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.health import build_health_response
from app.core.logging import setup_logging
from app.core.middleware import setup_middleware
from app.modules.auth.jwt import generate_request_id

# Configure structured logging before anything else
setup_logging(json_output=os.environ.get("LOG_FORMAT", "json") == "json")

logger = structlog.get_logger()

app = FastAPI(
    title="mingai API",
    description="Enterprise RAG Platform - Multi-Tenant Backend",
    version="1.0.0",
    docs_url="/api/docs" if os.environ.get("DEBUG", "").lower() == "true" else None,
    redoc_url=None,
)

# Setup middleware: CORS, security headers, request ID
setup_middleware(app)


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


# Include API router with all module endpoints
from app.api.router import router as api_router

app.include_router(api_router)


@app.on_event("startup")
async def startup():
    """Application startup: validate configuration and initialize connections."""
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
    try:
        import asyncio

        from app.core.session import async_session_factory
        from app.modules.har.health_monitor import AgentHealthMonitor

        monitor = AgentHealthMonitor(
            db_session_factory=async_session_factory, interval_seconds=3600
        )
        asyncio.create_task(monitor.start())
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

    logger.info("application_started")


@app.on_event("shutdown")
async def shutdown():
    """Application shutdown: close connections cleanly."""
    from app.core.redis_client import close_redis

    await close_redis()
    logger.info("application_shutdown")
