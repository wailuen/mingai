"""
Tests for CORS configuration (INFRA-051), security headers (INFRA-052),
and health check (INFRA-043).

CORS: allow_origins=[FRONTEND_URL], NEVER wildcard.
Security headers: X-Content-Type-Options, X-Frame-Options, HSTS, CSP.
Health check: GET /health returns component status.
"""
import os
import pytest
from unittest.mock import patch


class TestCORSConfiguration:
    """INFRA-051: CORS must restrict origins to FRONTEND_URL only."""

    def test_cors_uses_frontend_url_from_env(self):
        """CORS allowed origins must come from FRONTEND_URL env var."""
        from app.core.middleware import get_cors_config

        with patch.dict(os.environ, {"FRONTEND_URL": "http://localhost:3022"}):
            config = get_cors_config()
            assert config["allow_origins"] == ["http://localhost:3022"]

    def test_cors_never_wildcard(self):
        """CORS must NEVER use wildcard origin."""
        from app.core.middleware import get_cors_config

        with patch.dict(os.environ, {"FRONTEND_URL": "http://localhost:3022"}):
            config = get_cors_config()
            assert "*" not in config["allow_origins"]

    def test_cors_allows_credentials(self):
        """CORS must allow credentials for JWT auth."""
        from app.core.middleware import get_cors_config

        with patch.dict(os.environ, {"FRONTEND_URL": "http://localhost:3022"}):
            config = get_cors_config()
            assert config["allow_credentials"] is True

    def test_cors_allows_required_methods(self):
        """CORS must allow standard HTTP methods."""
        from app.core.middleware import get_cors_config

        with patch.dict(os.environ, {"FRONTEND_URL": "http://localhost:3022"}):
            config = get_cors_config()
            for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
                assert method in config["allow_methods"]

    def test_cors_allows_required_headers(self):
        """CORS must allow Authorization and Content-Type headers."""
        from app.core.middleware import get_cors_config

        with patch.dict(os.environ, {"FRONTEND_URL": "http://localhost:3022"}):
            config = get_cors_config()
            assert "Authorization" in config["allow_headers"]
            assert "Content-Type" in config["allow_headers"]

    def test_cors_raises_if_frontend_url_missing(self):
        """CORS must raise error if FRONTEND_URL not set."""
        from app.core.middleware import get_cors_config

        with patch.dict(os.environ, {}, clear=True):
            # Remove FRONTEND_URL entirely
            os.environ.pop("FRONTEND_URL", None)
            with pytest.raises(ValueError, match="FRONTEND_URL"):
                get_cors_config()

    def test_cors_raises_if_frontend_url_is_wildcard(self):
        """CORS must reject wildcard FRONTEND_URL."""
        from app.core.middleware import get_cors_config

        with patch.dict(os.environ, {"FRONTEND_URL": "*"}):
            with pytest.raises(ValueError, match="wildcard"):
                get_cors_config()


class TestSecurityHeaders:
    """INFRA-052: Security headers middleware."""

    def test_security_headers_complete(self):
        """All required security headers must be present."""
        from app.core.middleware import get_security_headers

        headers = get_security_headers()
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "max-age=" in headers["Strict-Transport-Security"]
        assert "includeSubDomains" in headers["Strict-Transport-Security"]
        assert "default-src" in headers["Content-Security-Policy"]
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert headers["X-XSS-Protection"] == "1; mode=block"

    def test_hsts_max_age_sufficient(self):
        """HSTS max-age must be at least 1 year (31536000 seconds)."""
        from app.core.middleware import get_security_headers

        headers = get_security_headers()
        hsts = headers["Strict-Transport-Security"]
        # Extract max-age value
        import re
        match = re.search(r"max-age=(\d+)", hsts)
        assert match is not None
        max_age = int(match.group(1))
        assert max_age >= 31536000


class TestHealthCheck:
    """INFRA-043: Health check endpoint."""

    def test_health_response_structure(self):
        """Health check returns expected structure."""
        from app.core.health import build_health_response

        response = build_health_response(
            database_ok=True,
            redis_ok=True,
            search_ok=True,
        )
        assert response["status"] == "healthy"
        assert response["database"] == "ok"
        assert response["redis"] == "ok"
        assert response["search"] == "ok"
        assert "version" in response

    def test_health_degraded_when_service_down(self):
        """Health check returns degraded status when a service is down."""
        from app.core.health import build_health_response

        response = build_health_response(
            database_ok=True,
            redis_ok=False,
            search_ok=True,
        )
        assert response["status"] == "degraded"
        assert response["redis"] == "error"
        assert response["database"] == "ok"

    def test_health_unhealthy_when_database_down(self):
        """Health check returns unhealthy when database is down."""
        from app.core.health import build_health_response

        response = build_health_response(
            database_ok=False,
            redis_ok=True,
            search_ok=True,
        )
        assert response["status"] == "unhealthy"
        assert response["database"] == "error"

    def test_health_includes_version(self):
        """Health check includes application version."""
        from app.core.health import build_health_response

        response = build_health_response(
            database_ok=True, redis_ok=True, search_ok=True
        )
        assert response["version"] is not None
        assert len(response["version"]) > 0
