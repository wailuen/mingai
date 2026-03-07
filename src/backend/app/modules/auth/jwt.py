"""
JWT token validation for mingai platform.

Supports:
- JWT v2 (multi-tenant) with tenant_id, scope, roles, plan claims
- JWT v1 (legacy) dual-accept window with default values
- Auth0 JWKS validation (Phase 2)

All secrets from .env - NEVER hardcode signing keys.
"""
import uuid as uuid_module
from datetime import datetime, timezone

from jose import JWTError, jwt


class JWTValidationError(Exception):
    """Raised when JWT validation fails with a specific reason."""

    def __init__(self, reason: str, status_code: int = 401):
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


VALID_SCOPES = {"tenant", "platform"}
MAX_CLOCK_SKEW_SECONDS = 60


def decode_jwt_token(
    token: str,
    secret_key: str,
    algorithm: str,
) -> dict:
    """
    Decode and validate a JWT v2 token.

    Validates:
    - Token structure and signature
    - Expiration
    - Required claims: sub, tenant_id
    - Scope validity
    - Clock skew protection

    Raises JWTValidationError with descriptive message on any failure.
    Returns decoded payload dict on success.
    """
    if not token:
        raise JWTValidationError("Token is empty - provide a valid Bearer token")

    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[algorithm],
            options={
                "verify_exp": True,
                "verify_iat": False,  # We check clock skew manually
            },
        )
    except JWTError as e:
        error_msg = str(e).lower()
        if "expired" in error_msg or "exp" in error_msg:
            raise JWTValidationError(
                "Token has expired - request a new token via /auth/token/refresh"
            )
        raise JWTValidationError(
            f"Token is invalid - signature verification failed: {e}"
        )

    # Validate required claims
    if "sub" not in payload or not payload["sub"]:
        raise JWTValidationError(
            "Token missing required 'sub' claim - cannot identify user"
        )

    if "tenant_id" not in payload or not payload["tenant_id"]:
        raise JWTValidationError(
            "Token missing required 'tenant_id' claim - "
            "use v2 tokens or the v1 compatibility endpoint"
        )

    # Validate scope
    scope = payload.get("scope", "tenant")
    if scope not in VALID_SCOPES:
        raise JWTValidationError(
            f"Token has invalid scope '{scope}' - "
            f"must be one of: {', '.join(VALID_SCOPES)}"
        )
    payload["scope"] = scope

    # Ensure roles is a list
    if "roles" not in payload:
        payload["roles"] = []

    # Ensure plan has a value
    if "plan" not in payload:
        payload["plan"] = "professional"

    # Clock skew protection
    iat = payload.get("iat")
    if iat is not None:
        now_ts = datetime.now(timezone.utc).timestamp()
        if isinstance(iat, (int, float)):
            iat_ts = iat
        else:
            iat_ts = iat.timestamp() if hasattr(iat, "timestamp") else float(iat)

        if iat_ts > now_ts + MAX_CLOCK_SKEW_SECONDS:
            raise JWTValidationError(
                f"Token issued in the future (clock skew > {MAX_CLOCK_SKEW_SECONDS}s) "
                f"- check server clock synchronization"
            )

    return payload


def decode_jwt_token_v1_compat(
    token: str,
    secret_key: str,
    algorithm: str,
) -> dict:
    """
    Decode JWT with v1 backward compatibility.

    v1 tokens (without tenant_id) are accepted during the 30-day
    dual-accept window with these defaults:
    - tenant_id = "default"
    - scope = "tenant"
    - plan = "professional"

    After the dual-accept window closes, v1 tokens will be rejected
    by the standard decode_jwt_token function.
    """
    if not token:
        raise JWTValidationError("Token is empty - provide a valid Bearer token")

    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[algorithm],
            options={"verify_exp": True, "verify_iat": False},
        )
    except JWTError as e:
        error_msg = str(e).lower()
        if "expired" in error_msg or "exp" in error_msg:
            raise JWTValidationError(
                "Token has expired - request a new token via /auth/token/refresh"
            )
        raise JWTValidationError(f"Token is invalid: {e}")

    if "sub" not in payload or not payload["sub"]:
        raise JWTValidationError("Token missing required 'sub' claim")

    # Apply v1 defaults if tenant_id is missing
    if "tenant_id" not in payload or not payload["tenant_id"]:
        payload["tenant_id"] = "default"
        payload["scope"] = "tenant"
        payload["plan"] = "professional"
    else:
        # v2 token - validate scope
        scope = payload.get("scope", "tenant")
        if scope not in VALID_SCOPES:
            raise JWTValidationError(f"Invalid scope: {scope}")
        payload["scope"] = scope

    if "roles" not in payload:
        payload["roles"] = []
    if "plan" not in payload:
        payload["plan"] = "professional"

    return payload


def generate_request_id() -> str:
    """Generate a unique request ID for tracing."""
    return f"req_{uuid_module.uuid4().hex[:16]}"
