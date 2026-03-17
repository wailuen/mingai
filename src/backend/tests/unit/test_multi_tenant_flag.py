"""
Unit tests for MULTI_TENANT_ENABLED flag (DEF-009).

Tests cover:
- MULTI_TENANT_ENABLED=false forces tenant_id to "default" regardless of JWT
- MULTI_TENANT_ENABLED=true uses tenant_id from JWT
- _is_multi_tenant_enabled() returns True by default
- _is_multi_tenant_enabled() returns False for "false", "0", "no", "off"
- _is_multi_tenant_enabled() returns True for "true", "1", "yes"
- TenantContextMiddleware dispatch sets tenant_id="default" when flag=false
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _is_multi_tenant_enabled() unit tests
# ---------------------------------------------------------------------------


def test_is_multi_tenant_enabled_default():
    """Defaults to True when env var is not set."""
    from app.core.tenant_middleware import _is_multi_tenant_enabled

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MULTI_TENANT_ENABLED", None)
        result = _is_multi_tenant_enabled()
    assert result is True


@pytest.mark.parametrize("val", ["false", "False", "FALSE", "0", "no", "off"])
def test_is_multi_tenant_enabled_false_values(val):
    """Returns False for recognised falsy env var values."""
    from app.core.tenant_middleware import _is_multi_tenant_enabled

    with patch.dict(os.environ, {"MULTI_TENANT_ENABLED": val}):
        result = _is_multi_tenant_enabled()
    assert result is False


@pytest.mark.parametrize("val", ["true", "True", "TRUE", "1", "yes"])
def test_is_multi_tenant_enabled_true_values(val):
    """Returns True for truthy env var values."""
    from app.core.tenant_middleware import _is_multi_tenant_enabled

    with patch.dict(os.environ, {"MULTI_TENANT_ENABLED": val}):
        result = _is_multi_tenant_enabled()
    assert result is True


# ---------------------------------------------------------------------------
# TenantContextMiddleware dispatch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_single_tenant_overrides_to_default():
    """When flag=false, tenant_id is forced to 'default' regardless of JWT."""
    from app.core.tenant_middleware import TenantContextMiddleware

    mock_app = AsyncMock()
    middleware = TenantContextMiddleware(mock_app)

    mock_request = MagicMock()
    mock_request.url.path = "/api/v1/chat"
    mock_request.headers.get.return_value = "Bearer some.jwt.token"
    mock_request.state = MagicMock()

    mock_call_next = AsyncMock(return_value=MagicMock())

    with patch.dict(os.environ, {"MULTI_TENANT_ENABLED": "false"}):
        await middleware.dispatch(mock_request, mock_call_next)

    assert mock_request.state.tenant_id == "default"
    assert mock_request.state.scope == "tenant"


@pytest.mark.asyncio
async def test_middleware_multi_tenant_uses_jwt():
    """When flag=true, tenant_id is resolved from JWT Bearer token."""
    from app.core.tenant_middleware import TenantContextMiddleware

    mock_app = AsyncMock()
    middleware = TenantContextMiddleware(mock_app)

    mock_request = MagicMock()
    mock_request.url.path = "/api/v1/chat"
    mock_request.headers.get.return_value = "Bearer valid.jwt.token"
    mock_request.state = MagicMock()

    mock_call_next = AsyncMock(return_value=MagicMock())

    with patch.dict(os.environ, {"MULTI_TENANT_ENABLED": "true"}):
        with patch(
            "app.core.tenant_middleware._extract_claims_from_jwt",
            return_value=("tenant-from-jwt", "tenant"),
        ):
            await middleware.dispatch(mock_request, mock_call_next)

    assert mock_request.state.tenant_id == "tenant-from-jwt"
    assert mock_request.state.scope == "tenant"
