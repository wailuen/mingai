"""
Unit tests for INFRA-048 — Tenant Context Middleware.

Verifies:
- Exempt paths set tenant_id="" without JWT decoding
- Single-tenant mode (MULTI_TENANT_ENABLED=False) injects tenant_id="default"
- Multi-tenant mode extracts tenant_id from JWT
- Invalid / missing JWT in multi-tenant mode sets tenant_id=""
- scope claim is extracted alongside tenant_id
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestExemptPaths:
    """Exempt infrastructure paths bypass tenant resolution."""

    @pytest.mark.asyncio
    async def test_health_path_exempt(self):
        from app.core.tenant_middleware import TenantContextMiddleware

        request = MagicMock()
        request.url.path = "/health"
        request.state = MagicMock()

        call_next = AsyncMock(return_value=MagicMock())
        mw = TenantContextMiddleware(app=MagicMock())

        await mw.dispatch(request, call_next)

        assert request.state.tenant_id == ""
        assert request.state.scope == ""
        call_next.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_metrics_path_exempt(self):
        from app.core.tenant_middleware import TenantContextMiddleware

        request = MagicMock()
        request.url.path = "/metrics"
        request.state = MagicMock()

        call_next = AsyncMock(return_value=MagicMock())
        mw = TenantContextMiddleware(app=MagicMock())

        await mw.dispatch(request, call_next)

        assert request.state.tenant_id == ""

    @pytest.mark.asyncio
    async def test_openapi_json_path_exempt(self):
        from app.core.tenant_middleware import TenantContextMiddleware

        request = MagicMock()
        request.url.path = "/openapi.json"
        request.state = MagicMock()

        call_next = AsyncMock(return_value=MagicMock())
        mw = TenantContextMiddleware(app=MagicMock())

        await mw.dispatch(request, call_next)

        assert request.state.tenant_id == ""


class TestSingleTenantMode:
    """MULTI_TENANT_ENABLED=False injects fixed tenant_id='default'."""

    @pytest.mark.asyncio
    async def test_single_tenant_injects_default(self):
        from app.core.tenant_middleware import TenantContextMiddleware

        request = MagicMock()
        request.url.path = "/api/v1/chat"
        request.state = MagicMock()
        request.headers = {}

        call_next = AsyncMock(return_value=MagicMock())
        mw = TenantContextMiddleware(app=MagicMock())

        with patch.dict(os.environ, {"MULTI_TENANT_ENABLED": "false"}):
            await mw.dispatch(request, call_next)

        assert request.state.tenant_id == "default"
        assert request.state.scope == "tenant"

    @pytest.mark.asyncio
    async def test_single_tenant_no_jwt_required(self):
        """Single-tenant mode should not try to decode a JWT."""
        from app.core.tenant_middleware import TenantContextMiddleware

        request = MagicMock()
        request.url.path = "/api/v1/users"
        request.state = MagicMock()
        request.headers = {}  # No Authorization header

        call_next = AsyncMock(return_value=MagicMock())
        mw = TenantContextMiddleware(app=MagicMock())

        with patch.dict(os.environ, {"MULTI_TENANT_ENABLED": "false"}):
            with patch(
                "app.core.tenant_middleware._extract_claims_from_jwt"
            ) as mock_extract:
                await mw.dispatch(request, call_next)
                mock_extract.assert_not_called()


class TestMultiTenantMode:
    """MULTI_TENANT_ENABLED=True extracts tenant_id from JWT."""

    @pytest.mark.asyncio
    async def test_extracts_tenant_from_valid_jwt(self):
        from app.core.tenant_middleware import TenantContextMiddleware

        request = MagicMock()
        request.url.path = "/api/v1/chat"
        request.state = MagicMock()
        request.headers = {"Authorization": "Bearer valid.token.here"}

        call_next = AsyncMock(return_value=MagicMock())
        mw = TenantContextMiddleware(app=MagicMock())

        with patch.dict(os.environ, {"MULTI_TENANT_ENABLED": "true"}):
            with patch(
                "app.core.tenant_middleware._extract_claims_from_jwt",
                return_value=("tenant-abc", "tenant"),
            ):
                await mw.dispatch(request, call_next)

        assert request.state.tenant_id == "tenant-abc"
        assert request.state.scope == "tenant"

    @pytest.mark.asyncio
    async def test_no_jwt_sets_empty_tenant(self):
        """Missing or invalid JWT → tenant_id='' (route handles 401)."""
        from app.core.tenant_middleware import TenantContextMiddleware

        request = MagicMock()
        request.url.path = "/api/v1/chat"
        request.state = MagicMock()
        request.headers = {}

        call_next = AsyncMock(return_value=MagicMock())
        mw = TenantContextMiddleware(app=MagicMock())

        with patch.dict(os.environ, {"MULTI_TENANT_ENABLED": "true"}):
            with patch(
                "app.core.tenant_middleware._extract_claims_from_jwt",
                return_value=(None, None),
            ):
                await mw.dispatch(request, call_next)

        assert request.state.tenant_id == ""
        assert request.state.scope == ""

    @pytest.mark.asyncio
    async def test_platform_scope_extracted(self):
        """JWT with scope='platform' sets scope correctly."""
        from app.core.tenant_middleware import TenantContextMiddleware

        request = MagicMock()
        request.url.path = "/api/v1/platform/tenants"
        request.state = MagicMock()
        request.headers = {"Authorization": "Bearer platform.token"}

        call_next = AsyncMock(return_value=MagicMock())
        mw = TenantContextMiddleware(app=MagicMock())

        with patch.dict(os.environ, {"MULTI_TENANT_ENABLED": "true"}):
            with patch(
                "app.core.tenant_middleware._extract_claims_from_jwt",
                return_value=("platform", "platform"),
            ):
                await mw.dispatch(request, call_next)

        assert request.state.scope == "platform"


class TestIsMultiTenantEnabled:
    """_is_multi_tenant_enabled reads MULTI_TENANT_ENABLED env var."""

    def test_true_by_default(self):
        from app.core.tenant_middleware import _is_multi_tenant_enabled

        env = {k: v for k, v in os.environ.items() if k != "MULTI_TENANT_ENABLED"}
        with patch.dict(os.environ, env, clear=True):
            assert _is_multi_tenant_enabled() is True

    def test_false_when_set_to_false(self):
        from app.core.tenant_middleware import _is_multi_tenant_enabled

        with patch.dict(os.environ, {"MULTI_TENANT_ENABLED": "false"}):
            assert _is_multi_tenant_enabled() is False

    def test_false_when_set_to_zero(self):
        from app.core.tenant_middleware import _is_multi_tenant_enabled

        with patch.dict(os.environ, {"MULTI_TENANT_ENABLED": "0"}):
            assert _is_multi_tenant_enabled() is False

    def test_true_when_set_to_true(self):
        from app.core.tenant_middleware import _is_multi_tenant_enabled

        with patch.dict(os.environ, {"MULTI_TENANT_ENABLED": "true"}):
            assert _is_multi_tenant_enabled() is True


class TestExtractClaimsFromJWT:
    """_extract_claims_from_jwt decodes the token once and returns (tenant_id, scope)."""

    def test_returns_none_tuple_when_no_header(self):
        from app.core.tenant_middleware import _extract_claims_from_jwt

        assert _extract_claims_from_jwt("") == (None, None)

    def test_returns_none_tuple_when_no_bearer_prefix(self):
        from app.core.tenant_middleware import _extract_claims_from_jwt

        assert _extract_claims_from_jwt("Token abc123") == (None, None)

    def test_returns_none_tuple_when_jwt_secret_missing(self):
        from app.core.tenant_middleware import _extract_claims_from_jwt

        env = {k: v for k, v in os.environ.items() if k != "JWT_SECRET_KEY"}
        with patch.dict(os.environ, env, clear=True):
            result = _extract_claims_from_jwt("Bearer some.token.here")
            assert result == (None, None)

    def test_returns_none_tuple_on_invalid_token(self):
        """Malformed tokens must not raise — return (None, None) silently."""
        from app.core.tenant_middleware import _extract_claims_from_jwt

        with patch.dict(os.environ, {"JWT_SECRET_KEY": "a" * 32}):
            result = _extract_claims_from_jwt("Bearer not.a.real.jwt")
            assert result == (None, None)

    def test_returns_both_claims_from_valid_token(self):
        """Returns (tenant_id, scope) from a well-formed JWT in a single decode."""
        import time

        import jwt as pyjwt

        from app.core.tenant_middleware import _extract_claims_from_jwt

        secret = "s" * 32
        payload = {
            "sub": "user-123",
            "tenant_id": "tenant-xyz",
            "scope": "tenant",
            "roles": ["user"],
            "plan": "professional",
            "token_version": 2,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = pyjwt.encode(payload, secret, algorithm="HS256")

        with patch.dict(
            os.environ, {"JWT_SECRET_KEY": secret, "JWT_ALGORITHM": "HS256"}
        ):
            tenant_id, scope = _extract_claims_from_jwt(f"Bearer {token}")
            assert tenant_id == "tenant-xyz"
            assert scope == "tenant"
