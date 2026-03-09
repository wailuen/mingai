"""
Health check endpoint logic.

INFRA-043: Returns component-level health status.
INFRA-055: Exposes circuit breaker state per tenant+slot in /ready endpoint.
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


def build_ready_response(
    database_ok: bool,
    redis_ok: bool,
    circuit_breakers: dict | None = None,
) -> dict:
    """
    Build a /ready liveness response that includes circuit breaker state.

    Args:
        database_ok:       True if the database is reachable.
        redis_ok:          True if Redis is reachable.
        circuit_breakers:  Optional dict mapping "tenant_id:slot" → state string.
                           E.g. {"default:primary": "closed", "acme:primary": "open"}

    Status logic (same as health):
    - "ready":    database and Redis OK, no OPEN circuits
    - "degraded": Redis down or at least one circuit is OPEN
    - "not_ready": database down

    Returns dict suitable for JSON serialization.
    """
    cb_map = circuit_breakers or {}
    open_circuits = [k for k, v in cb_map.items() if v == "open"]

    if not database_ok:
        status = "not_ready"
    elif not redis_ok or open_circuits:
        status = "degraded"
    else:
        status = "ready"

    return {
        "status": status,
        "version": APP_VERSION,
        "database": "ok" if database_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "circuit_breakers": cb_map,
        "open_circuits": open_circuits,
    }
