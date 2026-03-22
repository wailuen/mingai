"""
Regression tests for A2A proxy security fixes.

RED TEAM round 1 findings:
  CRITICAL-1: X-Tenant-Id header leaked internal tenant ID to external agents
  CRITICAL-2: _check_ssrf used blocking socket.getaddrinfo in async context
"""
import asyncio
import ipaddress
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.regression
def test_a2a_proxy_does_not_send_x_tenant_id_header():
    """CRITICAL-1: tenant_id MUST NOT be forwarded as X-Tenant-Id to external agents.

    Verifies the outbound headers dict does not contain X-Tenant-Id.
    If this fails, internal tenant IDs are leaked to third-party A2A agents.
    """
    import httpx

    captured_headers = {}

    async def _fake_post(url, *, json, headers, **kwargs):
        captured_headers.update(headers)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.content = b'{"result": "ok"}'
        mock_resp.json.return_value = {"result": "ok"}
        mock_resp.status_code = 200
        return mock_resp

    from app.modules.agents.a2a_proxy import invoke_a2a_agent

    async def run():
        with patch("app.core.security.ssrf.resolve_and_pin_url", new=AsyncMock(side_effect=lambda url, **kw: url)):
            with patch("app.modules.agents.a2a_proxy._check_rate_limit", new=AsyncMock()):
                with patch("httpx.AsyncClient") as mock_client_cls:
                    mock_client = AsyncMock()
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=False)
                    mock_resp = MagicMock()
                    mock_resp.raise_for_status = MagicMock()
                    mock_resp.content = b'{"result": "ok"}'
                    mock_resp.json.return_value = {"result": "ok"}
                    mock_client.post = AsyncMock(return_value=mock_resp)
                    mock_client_cls.return_value = mock_client

                    await invoke_a2a_agent(
                        tenant_id="tenant-secret-123",
                        calling_agent_id="agent-abc",
                        target_agent={
                            "id": "ext-agent-1",
                            "a2a_endpoint": "https://external.example.com/a2a",
                        },
                        request_body={"operation": "test", "input": {}},
                    )

                    # Extract headers from the post call
                    call_kwargs = mock_client.post.call_args
                    if call_kwargs:
                        sent_headers = call_kwargs.kwargs.get("headers", {}) or call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}
                        assert "X-Tenant-Id" not in sent_headers, (
                            "X-Tenant-Id header MUST NOT be sent to external A2A agents — "
                            "it leaks internal tenant identifiers"
                        )
                        assert "tenant-secret-123" not in str(sent_headers.values()), (
                            "Tenant ID value MUST NOT appear in any outbound header value"
                        )

    asyncio.run(run())


@pytest.mark.regression
def test_a2a_proxy_check_ssrf_is_async():
    """CRITICAL-2: resolve_and_pin_url MUST be an async function (not sync blocking).

    The shared SSRF module runs DNS resolution in an executor to avoid blocking
    the event loop under high concurrency.
    """
    import inspect
    from app.core.security.ssrf import resolve_and_pin_url

    assert inspect.iscoroutinefunction(resolve_and_pin_url), (
        "resolve_and_pin_url must be async to avoid blocking the event loop during DNS resolution"
    )


@pytest.mark.regression
def test_a2a_proxy_invoke_awaits_check_ssrf():
    """CRITICAL-2: invoke_a2a_agent must await resolve_and_pin_url (not call it synchronously)."""
    import inspect
    from app.modules.agents import a2a_proxy

    source = inspect.getsource(a2a_proxy.invoke_a2a_agent)
    # The source should contain 'await resolve_and_pin_url'
    assert "await resolve_and_pin_url" in source, (
        "invoke_a2a_agent must await resolve_and_pin_url to avoid blocking the event loop"
    )
