"""
JWT token validation for mingai platform.

Supports:
- JWT v2 (multi-tenant) with tenant_id, scope, roles, plan claims
- JWT v1 (legacy) dual-accept window with default values
- Auth0 JWKS validation (RS256, fetched from /.well-known/jwks.json)

All secrets from .env - NEVER hardcode signing keys.
"""
import os
import time
import uuid as uuid_module
from datetime import datetime, timezone

import structlog
from jose import JWTError, exceptions as jose_exceptions, jwt

logger = structlog.get_logger()


class JWTValidationError(Exception):
    """Raised when JWT validation fails with a specific reason."""

    def __init__(self, reason: str, status_code: int = 401):
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


VALID_SCOPES = {"tenant", "platform"}
MAX_CLOCK_SKEW_SECONDS = 60

# ---------------------------------------------------------------------------
# JWKS in-process cache
# ---------------------------------------------------------------------------
# Stores {"jwks": <jwks_dict>, "fetched_at": <unix_timestamp>}
# Module-level dict so it lives for the lifetime of the process.
_JWKS_CACHE: dict = {}
_JWKS_CACHE_TTL_SECONDS = 3600

# Custom Auth0 namespace for tenant claim
_AUTH0_TENANT_CLAIM = "https://mingai.app/tenant_id"


def _is_jwks_cache_valid() -> bool:
    """Return True if the cached JWKS is still within TTL."""
    if not _JWKS_CACHE:
        return False
    age = time.monotonic() - _JWKS_CACHE.get("fetched_at", 0)
    return age < _JWKS_CACHE_TTL_SECONDS


def _clear_jwks_cache() -> None:
    """Invalidate the JWKS cache (called on key-rotation detection)."""
    _JWKS_CACHE.clear()


async def _fetch_jwks(domain: str) -> dict:
    """
    Fetch the public JWKS from Auth0 and populate the in-process cache.

    Uses httpx async client. Raises JWTValidationError on HTTP failure.
    """
    import httpx

    url = f"https://{domain}/.well-known/jwks.json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            jwks = response.json()
    except httpx.HTTPStatusError as exc:
        raise JWTValidationError(
            f"Failed to fetch JWKS from Auth0 (HTTP {exc.response.status_code})"
        )
    except Exception as exc:
        raise JWTValidationError(f"Failed to fetch JWKS from Auth0: {exc}")

    _JWKS_CACHE["jwks"] = jwks
    _JWKS_CACHE["fetched_at"] = time.monotonic()
    logger.debug("jwks_cache_refreshed", domain=domain)
    return jwks


async def _get_jwks(domain: str) -> dict:
    """Return the JWKS dict, using cache if still valid."""
    if _is_jwks_cache_valid():
        return _JWKS_CACHE["jwks"]
    return await _fetch_jwks(domain)


def _extract_kid_from_token(token: str) -> str | None:
    """Extract the 'kid' header from an unverified JWT header."""
    try:
        header = jwt.get_unverified_header(token)
        return header.get("kid")
    except Exception:
        return None


def _is_auth0_token(token: str, auth0_domain: str) -> bool:
    """
    Heuristic: return True if the token header uses RS256 AND the unverified
    issuer claim matches the configured Auth0 domain.

    This lets us route tokens correctly without fetching JWKS first.
    """
    if not token:
        return False
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            return False
        # Check issuer in unverified claims
        unverified = jwt.get_unverified_claims(token)
        expected_issuer = f"https://{auth0_domain}/"
        return unverified.get("iss") == expected_issuer
    except Exception:
        return False


async def decode_jwt_token_auth0(token: str) -> dict:
    """
    Decode and validate an RS256 JWT token issued by Auth0.

    Flow:
    1. Peek at token header to find 'kid'.
    2. Fetch JWKS from https://{AUTH0_DOMAIN}/.well-known/jwks.json (cached 3600s).
    3. Find the matching public key by 'kid'.
    4. Validate signature, expiration, audience, and issuer via python-jose.
    5. On InvalidSignatureError: clear cache, re-fetch JWKS once, retry.

    Returns the decoded payload dict on success.
    Raises JWTValidationError on any failure.
    """
    if not token:
        raise JWTValidationError("Token is empty - provide a valid Bearer token")

    auth0_domain = os.environ.get("AUTH0_DOMAIN", "")
    auth0_audience = os.environ.get("AUTH0_AUDIENCE", "")

    if not auth0_domain:
        raise JWTValidationError(
            "AUTH0_DOMAIN not configured - cannot validate Auth0 token"
        )

    if not auth0_audience:
        raise JWTValidationError(
            "AUTH0_AUDIENCE not configured - cannot validate Auth0 token audience"
        )

    expected_issuer = f"https://{auth0_domain}/"

    async def _validate_with_jwks(jwks: dict) -> dict:
        """Attempt validation with the provided JWKS."""
        kid = _extract_kid_from_token(token)
        if not kid:
            raise JWTValidationError(
                "Auth0 token missing 'kid' header - cannot select signing key"
            )

        # Find the matching key
        keys = jwks.get("keys", [])
        matching_key = next((k for k in keys if k.get("kid") == kid), None)
        if matching_key is None:
            raise JWTValidationError(
                f"No matching JWKS key for kid='{kid}' - "
                "key may have been rotated, retrying"
            )

        try:
            payload = jwt.decode(
                token,
                matching_key,
                algorithms=["RS256"],
                audience=auth0_audience if auth0_audience else None,
                issuer=expected_issuer,
                options={"verify_exp": True},
            )
        except jose_exceptions.ExpiredSignatureError:
            raise JWTValidationError("Auth0 token has expired - request a new token")
        except jose_exceptions.JWTClaimsError as exc:
            raise JWTValidationError(f"Auth0 token claims validation failed: {exc}")
        except JWTError as exc:
            raise exc  # Re-raise so caller can catch for cache invalidation
        return payload

    # --- First attempt ---
    try:
        jwks = await _get_jwks(auth0_domain)
        payload = await _validate_with_jwks(jwks)
    except jose_exceptions.JWTError as exc:
        error_msg = str(exc).lower()
        if "signature" in error_msg or "key" in error_msg.lower():
            # Possible key rotation — clear cache and retry once
            logger.info(
                "jwks_cache_invalidated_on_signature_error",
                error=str(exc),
            )
            _clear_jwks_cache()
            try:
                fresh_jwks = await _fetch_jwks(auth0_domain)
                payload = await _validate_with_jwks(fresh_jwks)
            except JWTValidationError:
                raise
            except JWTError as retry_exc:
                raise JWTValidationError(
                    f"Auth0 token is invalid after JWKS refresh: {retry_exc}"
                )
        else:
            raise JWTValidationError(f"Auth0 token is invalid: {exc}")
    except JWTValidationError:
        raise

    # --- Normalise claims into the standard payload shape ---
    if "sub" not in payload or not payload["sub"]:
        raise JWTValidationError("Auth0 token missing required 'sub' claim")

    # tenant_id from custom claim, fall back to "default"
    tenant_id = (
        payload.get(_AUTH0_TENANT_CLAIM) or payload.get("tenant_id") or "default"
    )
    payload["tenant_id"] = tenant_id

    # scope: Auth0 scope claim is a space-separated string
    raw_scope = payload.get("scope", "")
    if "platform" in raw_scope.split():
        payload["scope"] = "platform"
    else:
        payload["scope"] = "tenant"

    if "roles" not in payload or not isinstance(payload.get("roles"), list):
        payload["roles"] = []

    if "plan" not in payload:
        payload["plan"] = "professional"

    return payload


# ---------------------------------------------------------------------------
# HS256 local JWT functions (unchanged from original)
# ---------------------------------------------------------------------------


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
