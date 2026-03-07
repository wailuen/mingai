"""
Root conftest.py - loads .env for all tests.

Kailash SDK convention: root conftest auto-loads .env.
"""
import os
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


@pytest.fixture
def anyio_backend():
    return "asyncio"
