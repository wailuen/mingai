"""
Root conftest.py — loads .env and provides the session-scoped TestClient.

Kailash SDK convention: root conftest auto-loads .env.

The session-scoped `client` fixture lives here (not in tests/integration/conftest.py
or tests/e2e/) so that ALL test directories (e2e, integration, unit) share a single
anyio event loop portal. This prevents asyncpg event loop contamination:
session.py creates a module-level async engine that binds to the first event loop
that uses it; multiple TestClients each create their own portals, causing
"Future attached to a different loop" or "another operation is in progress" errors.
"""
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Ensure the backend app package is importable
backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

# Load .env before any import that reads env vars
env_path = backend_root / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # For tests, provide minimal test defaults
    env_path_example = backend_root / ".env.example"
    if env_path_example.exists():
        load_dotenv(env_path_example)

# Signal to the app that we are running in test mode — disables background
# scheduler tasks (like credential_health) that iterate over all tenants and
# cause TestClient teardown timeouts when the test DB has accumulated many rows.
import os as _os
_os.environ.setdefault("TESTING", "1")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def client():
    """
    Session-scoped TestClient shared across ALL tests (e2e, integration, unit).

    A single anyio event loop portal is created for the entire pytest session.
    The module-level SQLAlchemy async engine (app/core/session.py) binds to
    this loop on first use and remains consistent for all subsequent requests —
    preventing asyncpg "Future attached to a different loop" errors.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    except RuntimeError as exc:
        # Suppress "Event loop is closed" during TestClient teardown — known
        # starlette/asyncio race on session-scoped fixtures.
        if "event loop is closed" not in str(exc).lower():
            raise
