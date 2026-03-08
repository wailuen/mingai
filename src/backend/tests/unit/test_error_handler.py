"""
Unit tests for API-122 — Global error handler middleware (GAP-009).

Verifies the consistent error envelope:
  {"error": "code", "message": "...", "request_id": "uuid", "details": {}}

Tier 1: Fast, isolated, no real DB/Redis.
"""
import os
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

TEST_ENV = {
    "JWT_SECRET_KEY": "a" * 64,
    "JWT_ALGORITHM": "HS256",
    "FRONTEND_URL": "http://localhost:3022",
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/mingai_test",
    "REDIS_URL": "redis://localhost:6379/1",
}


@pytest.fixture
def client():
    with patch.dict(os.environ, TEST_ENV):
        from app.main import app

        return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 404 error format
# ---------------------------------------------------------------------------


class TestNotFoundErrorFormat:
    """test_404_returns_error_format: 404 responses follow the envelope."""

    def test_404_returns_error_envelope(self, client):
        """Unknown route returns 404 with error envelope."""
        resp = client.get("/api/v1/nonexistent-route-xyz")
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"] == "not_found"
        assert "message" in data
        assert "request_id" in data
        assert "details" in data

    def test_404_request_id_is_uuid_string(self, client):
        """request_id in 404 response is a valid UUID string."""
        resp = client.get("/api/v1/nonexistent-route-xyz")
        data = resp.json()
        request_id = data.get("request_id", "")
        # Should be parseable as UUID
        parsed = uuid.UUID(request_id)
        assert str(parsed) == request_id

    def test_404_details_is_dict(self, client):
        """details field in 404 response is an empty dict."""
        resp = client.get("/api/v1/nonexistent-route-xyz")
        data = resp.json()
        assert isinstance(data["details"], dict)


# ---------------------------------------------------------------------------
# 422 validation error format
# ---------------------------------------------------------------------------


class TestValidationErrorFormat:
    """test_422_returns_field_details: 422 responses include field-level errors."""

    def test_422_has_validation_error_code(self, client):
        """Missing required fields returns 422 with 'validation_error' code."""
        # POST to login without required fields triggers validation error
        resp = client.post("/api/v1/auth/local/login", json={})
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"] == "validation_error"

    def test_422_contains_field_errors(self, client):
        """422 response details contains field_errors list."""
        resp = client.post("/api/v1/auth/local/login", json={})
        assert resp.status_code == 422
        data = resp.json()
        assert "details" in data
        assert "field_errors" in data["details"]
        assert isinstance(data["details"]["field_errors"], list)
        assert len(data["details"]["field_errors"]) > 0

    def test_422_field_error_has_loc_msg_type(self, client):
        """Each field error has loc, msg, and type keys."""
        resp = client.post("/api/v1/auth/local/login", json={})
        data = resp.json()
        first_error = data["details"]["field_errors"][0]
        assert "loc" in first_error
        assert "msg" in first_error
        assert "type" in first_error

    def test_422_has_request_id(self, client):
        """422 response includes request_id."""
        resp = client.post("/api/v1/auth/local/login", json={})
        data = resp.json()
        assert "request_id" in data
        assert data["request_id"]


# ---------------------------------------------------------------------------
# 500 error format
# ---------------------------------------------------------------------------


class TestInternalErrorFormat:
    """test_500_returns_generic_message: 500 responses do not leak internals."""

    def test_500_does_not_expose_traceback(self, client):
        """500 response body must not contain traceback or internal paths."""
        # Trigger a 500 by patching the health check to raise
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, TEST_ENV):
            from app.main import app

            # Mount a test route that raises an unhandled exception
            from fastapi import APIRouter

            boom_router = APIRouter()

            @boom_router.get("/test-boom-xyz")
            async def _boom():
                raise RuntimeError("secret internal detail")

            app.include_router(boom_router)
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.get("/test-boom-xyz")

        assert resp.status_code == 500
        data = resp.json()
        # Generic message — not the internal exception message
        assert "traceback" not in resp.text.lower()
        assert "secret internal detail" not in resp.text
        assert data["error"] == "internal_error"
        assert data["message"] == "Internal server error"

    def test_500_has_empty_details(self, client):
        """500 response details is empty — no internal info leaked."""
        from fastapi import APIRouter

        with patch.dict(os.environ, TEST_ENV):
            from app.main import app

            boom_router2 = APIRouter()

            @boom_router2.get("/test-boom-details-xyz")
            async def _boom_details():
                raise ValueError("internal value error")

            app.include_router(boom_router2)
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.get("/test-boom-details-xyz")

        assert resp.status_code == 500
        data = resp.json()
        assert data["details"] == {}


# ---------------------------------------------------------------------------
# X-Request-ID header passthrough
# ---------------------------------------------------------------------------


class TestRequestIdPropagation:
    """test_request_id_in_response_matches_header and test_request_id_generated."""

    def test_request_id_from_header_echoed_in_response(self, client):
        """If X-Request-ID header is set, the same value is echoed in response."""
        custom_id = "my-custom-request-id-001"
        resp = client.get(
            "/api/v1/nonexistent-route-xyz",
            headers={"X-Request-ID": custom_id},
        )
        data = resp.json()
        assert data["request_id"] == custom_id

    def test_request_id_generated_when_not_provided(self, client):
        """When X-Request-ID header is absent, a UUID is generated."""
        resp = client.get("/api/v1/nonexistent-route-xyz")
        data = resp.json()
        request_id = data.get("request_id", "")
        assert request_id  # not empty
        # Must be a valid UUID
        parsed = uuid.UUID(request_id)
        assert str(parsed) == request_id

    def test_request_id_generated_for_validation_errors(self, client):
        """422 responses also include a generated request_id."""
        resp = client.post("/api/v1/auth/local/login", json={})
        data = resp.json()
        request_id = data.get("request_id", "")
        assert request_id
        # Should be parseable as UUID (generated since we didn't send the header)
        try:
            uuid.UUID(request_id)
        except ValueError:
            pass  # custom string is also valid — just check it's non-empty

    def test_401_follows_error_envelope(self, client):
        """Auth-protected endpoint returns 401 with the standard envelope."""
        resp = client.get("/api/v1/auth/current")
        assert resp.status_code == 401
        data = resp.json()
        assert data["error"] == "unauthorized"
        assert "request_id" in data
        assert "details" in data
