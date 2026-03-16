"""
Integration test configuration.

The session-scoped `client` fixture is provided by tests/conftest.py (root level)
so that e2e, integration, and unit tests all share a single anyio event loop portal.
This prevents asyncpg "Future attached to a different loop" contamination between
test modules.
"""
