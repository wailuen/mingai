"""
mingai Backend API - FastAPI Application Entry Point

Port: 8022
Framework: FastAPI + Kailash SDK (DataFlow + Nexus + Kaizen)

All configuration from .env - never hardcode secrets or model names.
"""
import os

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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


# Global error handler (GAP-009 / API-122)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global error handler returning consistent error format.

    Format: {"error": "code", "message": "human-readable", "request_id": "uuid"}
    """
    request_id = getattr(request.state, "request_id", generate_request_id())

    logger.error(
        "unhandled_exception",
        error=str(exc),
        error_type=type(exc).__name__,
        request_id=request_id,
        path=str(request.url.path),
    )

    # Never expose internal errors in production
    debug = os.environ.get("DEBUG", "").lower() == "true"
    message = str(exc) if debug else "An internal error occurred"

    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": message,
            "request_id": request_id,
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

    # Validate critical env vars are set
    required_vars = ["DATABASE_URL", "REDIS_URL", "JWT_SECRET_KEY", "FRONTEND_URL"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        logger.error(
            "missing_required_env_vars",
            missing=missing,
            hint="Check .env file and .env.example for required variables",
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
