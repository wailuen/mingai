"""
Middleware configuration for FastAPI application.

INFRA-051: CORS - allow_origins from FRONTEND_URL env var, NEVER wildcard.
INFRA-052: Security headers - X-Content-Type-Options, X-Frame-Options, HSTS, CSP.
"""
import os

import structlog

logger = structlog.get_logger()


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
    4. Tenant context resolution
    """
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi import Request
    from app.modules.auth.jwt import generate_request_id

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

    logger.info(
        "middleware_configured",
        cors_origins=cors_config["allow_origins"],
        security_headers=list(security_hdrs.keys()),
    )
