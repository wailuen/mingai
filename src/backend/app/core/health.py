"""
Health check endpoint logic.

INFRA-043: Returns component-level health status.
Used by load balancers and monitoring systems.
"""

APP_VERSION = "1.0.0"


def build_health_response(
    database_ok: bool,
    redis_ok: bool,
    search_ok: bool,
) -> dict:
    """
    Build health check response with component-level status.

    Status logic:
    - "healthy": all components operational
    - "degraded": non-critical component down (redis, search)
    - "unhealthy": critical component down (database)

    Returns dict suitable for JSON serialization.
    """
    components = {
        "database": "ok" if database_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "search": "ok" if search_ok else "error",
    }

    # Database is critical - if it's down, we're unhealthy
    if not database_ok:
        status = "unhealthy"
    # Redis and search are important but not critical
    elif not redis_ok or not search_ok:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "version": APP_VERSION,
        **components,
    }
