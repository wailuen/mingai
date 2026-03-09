"""
Unit tests for INFRA-053 — Rate Limiting Middleware.

Verifies:
- Limiter constants are exported with correct tier values
- get_limiter() returns a Limiter instance (with Redis storage URI from env)
- setup_middleware wires the rate limit 429 exception handler
"""
import os
from unittest.mock import MagicMock, patch


class TestRateLimitConstants:
    """Tier constants must be stable — routes reference them."""

    def test_anonymous_limit(self):
        from app.core.middleware import RATE_LIMIT_ANONYMOUS

        assert RATE_LIMIT_ANONYMOUS == "60/minute"

    def test_auth_endpoint_limit(self):
        from app.core.middleware import RATE_LIMIT_AUTH_ENDPOINTS

        assert RATE_LIMIT_AUTH_ENDPOINTS == "10/minute"

    def test_authenticated_limit(self):
        from app.core.middleware import RATE_LIMIT_AUTHENTICATED

        assert RATE_LIMIT_AUTHENTICATED == "200/minute"


class TestBuildRateLimiter:
    """build_rate_limiter() constructs a slowapi Limiter backed by Redis."""

    def test_returns_limiter_instance(self):
        from slowapi import Limiter

        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}):
            from app.core.middleware import build_rate_limiter

            limiter = build_rate_limiter()
            assert isinstance(limiter, Limiter)

    def test_uses_redis_url_from_env(self):
        """build_rate_limiter reads REDIS_URL, not a hardcoded URL."""
        custom_url = "redis://custom-host:6380/1"
        with patch.dict(os.environ, {"REDIS_URL": custom_url}):
            from app.core.middleware import build_rate_limiter

            # Should not raise — just construct the limiter
            limiter = build_rate_limiter()
            assert limiter is not None

    def test_falls_back_to_localhost_when_redis_url_missing(self):
        """When REDIS_URL is absent, defaults to localhost (non-crashing)."""
        env = {k: v for k, v in os.environ.items() if k != "REDIS_URL"}
        with patch.dict(os.environ, env, clear=True):
            from app.core.middleware import build_rate_limiter

            limiter = build_rate_limiter()
            assert limiter is not None


class TestGetLimiter:
    """get_limiter() returns a singleton."""

    def test_get_limiter_returns_instance(self):
        from slowapi import Limiter

        import app.core.middleware as mw

        original = mw.limiter
        mw.limiter = None  # force rebuild
        try:
            with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}):
                result = mw.get_limiter()
                assert isinstance(result, Limiter)
        finally:
            mw.limiter = original

    def test_get_limiter_singleton(self):
        """Calling get_limiter() twice returns the same object."""
        import app.core.middleware as mw

        original = mw.limiter
        mw.limiter = None
        try:
            with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}):
                first = mw.get_limiter()
                second = mw.get_limiter()
                assert first is second
        finally:
            mw.limiter = original


class TestSetupMiddlewareRateLimiting:
    """setup_middleware wires slowapi's 429 handler onto the app."""

    def test_rate_limit_exception_handler_registered(self):
        """After setup_middleware, the app has a RateLimitExceeded handler."""
        from fastapi import FastAPI
        from slowapi.errors import RateLimitExceeded

        with patch.dict(
            os.environ,
            {
                "FRONTEND_URL": "http://localhost:3022",
                "REDIS_URL": "redis://localhost:6379/0",
            },
        ):
            from app.core.middleware import setup_middleware

            test_app = FastAPI()
            setup_middleware(test_app)

            assert RateLimitExceeded in test_app.exception_handlers

    def test_limiter_attached_to_app_state(self):
        """After setup_middleware, app.state.limiter is a Limiter instance."""
        from fastapi import FastAPI
        from slowapi import Limiter

        with patch.dict(
            os.environ,
            {
                "FRONTEND_URL": "http://localhost:3022",
                "REDIS_URL": "redis://localhost:6379/0",
            },
        ):
            from app.core.middleware import setup_middleware

            test_app = FastAPI()
            setup_middleware(test_app)

            assert hasattr(test_app.state, "limiter")
            assert isinstance(test_app.state.limiter, Limiter)
