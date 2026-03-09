"""
Middleware configuration for FastAPI application.

INFRA-051: CORS - allow_origins from FRONTEND_URL env var, NEVER wildcard.
INFRA-052: Security headers - X-Content-Type-Options, X-Frame-Options, HSTS, CSP.
INFRA-053: Rate limiting - Redis-backed distributed rate limiter (slowapi).
"""
import os

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Rate limit tiers
# ---------------------------------------------------------------------------
# These are read by the limiter decorators applied on individual route handlers
# via `@limiter.limit(...)`.  The constants are importable so route modules
# can reference the canonical tier strings without re-typing them.
RATE_LIMIT_ANONYMOUS = "60/minute"
RATE_LIMIT_AUTH_ENDPOINTS = "10/minute"
RATE_LIMIT_AUTHENTICATED = "200/minute"


def _get_client_ip(request) -> str:
    """
    Extract the real client IP for rate-limit bucketing.

    Checks X-Forwarded-For first (reverse proxy / load balancer), then
    falls back to the direct connection's host.  We take only the first
    entry of X-Forwarded-For because that is the client address before the
    first trusted proxy appended its own IP.
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        # "client, proxy1, proxy2" — take leftmost
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def build_rate_limiter():
    """
    Build a slowapi Limiter backed by Redis.

    The Redis URL is read from REDIS_URL env var at call time so that the
    limiter is always configured against the right instance (unit tests can
    override REDIS_URL before importing this module).

    Returns a configured slowapi.Limiter instance.
    """
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    storage_uri = redis_url
    # slowapi uses limits library which expects redis:// URIs — compatible
    # with what we store in REDIS_URL.

    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[RATE_LIMIT_ANONYMOUS],
        storage_uri=storage_uri,
        headers_enabled=True,
        # limits library header names are already the standard ones:
        # X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset
    )
    return limiter


# Module-level singleton — built lazily in setup_middleware so env vars are
# available.  Exported so route decorators can import it.
limiter = None


def get_limiter():
    """Return the module-level limiter singleton, building it if needed."""
    global limiter
    if limiter is None:
        limiter = build_rate_limiter()
    return limiter


def get_cors_config() -> dict:
    """
    Build CORS configuration from environment.

    CORS allowed origins MUST come from FRONTEND_URL env var.
    NEVER use wildcard '*' - this would allow any website to make
    authenticated requests to our API.

    Raises ValueError if FRONTEND_URL is missing or wildcard.
    """
    frontend_url = os.environ.get("FRONTEND_URL", "")

    if not frontend_url:
        raise ValueError(
            "FRONTEND_URL environment variable is not set. "
            "CORS requires an explicit origin. Set FRONTEND_URL in .env "
            "to the frontend URL (e.g., http://localhost:3022)"
        )

    if frontend_url == "*":
        raise ValueError(
            "FRONTEND_URL must NOT be wildcard '*'. "
            "CORS requires an explicit origin for security. "
            "Set FRONTEND_URL to the actual frontend URL."
        )

    return {
        "allow_origins": [frontend_url],
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": [
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "X-Tenant-ID",
        ],
    }


def get_security_headers() -> dict:
    """
    Build security response headers.

    Applied to every HTTP response. Enterprise customers will flag
    missing security headers in their security assessments.
    """
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Content-Security-Policy": "default-src 'self'",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }


def setup_middleware(app):
    """
    Configure all middleware on the FastAPI application.

    Order matters:
    1. CORS (must be first for preflight requests)
    2. Security headers
    3. Request ID injection
    4. Rate limiting (SlowAPI exception handler + state attachment)
    5. Tenant context resolution (INFRA-048) — wired separately via
       TenantContextMiddleware added after this call in main.py
    """
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi import Request
    from app.modules.auth.jwt import generate_request_id
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    # 1. CORS middleware
    cors_config = get_cors_config()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_config["allow_origins"],
        allow_credentials=cors_config["allow_credentials"],
        allow_methods=cors_config["allow_methods"],
        allow_headers=cors_config["allow_headers"],
    )

    # 2. Security headers + Request ID
    security_hdrs = get_security_headers()

    @app.middleware("http")
    async def add_security_headers_and_request_id(request: Request, call_next):
        # Generate and attach request ID for tracing
        request_id = generate_request_id()
        request.state.request_id = request_id

        response = await call_next(request)

        # Apply security headers
        for header_name, header_value in security_hdrs.items():
            response.headers[header_name] = header_value

        # Include request ID in response for client-side correlation
        response.headers["X-Request-ID"] = request_id

        return response

    # 3. Rate limiting — attach limiter to app.state and register the
    #    429 exception handler that slowapi expects.
    _limiter = get_limiter()
    app.state.limiter = _limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    logger.info(
        "middleware_configured",
        cors_origins=cors_config["allow_origins"],
        security_headers=list(security_hdrs.keys()),
        rate_limit_default=RATE_LIMIT_ANONYMOUS,
        rate_limit_auth=RATE_LIMIT_AUTH_ENDPOINTS,
        rate_limit_authenticated=RATE_LIMIT_AUTHENTICATED,
    )
