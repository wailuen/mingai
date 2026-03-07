"""
Integration test configuration.

Provides a single session-scoped TestClient shared across all integration tests.
This is critical: session.py creates a module-level async engine that binds to
the first event loop that uses it. If multiple TestClients are created (each with
their own portal/event loop), subsequent TestClients fail with asyncpg's
"Future attached to a different loop" error.

By sharing one TestClient for the entire test session, all HTTP calls go through
the same event loop portal, and the module-level engine is consistent.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    """
    Session-scoped TestClient for all integration tests.
    Uses a single event loop portal for the entire test session — prevents
    asyncpg 'Future attached to a different loop' errors with the module-level
    SQLAlchemy engine in app/core/session.py.
    """
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
