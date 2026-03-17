"""
Unit tests for platform admin endpoints: impersonation, preferences, GDPR delete
(API-113, API-114, API-115, API-116).

Tests:
- test_impersonate_requires_platform_admin
- test_impersonate_requires_reason
- test_impersonate_generates_token_with_claims
- test_impersonate_unknown_tenant_404
- test_end_impersonation_without_impersonated_claim_400
- test_platform_preferences_requires_platform_admin
- test_platform_preferences_digest_time_validation
- test_gdpr_delete_requires_confirmed_true
- test_gdpr_delete_requires_deletion_reference

Tier 1: Fast, isolated, all external deps mocked.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_PLATFORM_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_TENANT_USER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _make_token(
    user_id: str = TEST_PLATFORM_USER_ID,
    tenant_id: str = "default",
    roles: list | None = None,
    scope: str = "platform",
    plan: str = "enterprise",
    extra_claims: dict | None = None,
) -> str:
    if roles is None:
        roles = ["platform_admin"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": plan,
        "email": "admin@platform.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "jti": str(uuid.uuid4()),
        "token_version": 2,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_tenant_token(
    impersonated_by: str = TEST_PLATFORM_USER_ID,
) -> str:
    """Create a token that looks like an impersonation token."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": impersonated_by,
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": "admin@platform.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "jti": str(uuid.uuid4()),
        "impersonated_by": impersonated_by,
        "impersonated_reason": "Testing impersonation flow",
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


@pytest.fixture
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture
def client(env_vars):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def platform_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


@pytest.fixture
def tenant_headers():
    return {
        "Authorization": f"Bearer {_make_token(scope='tenant', roles=['end_user'])}"
    }


# ---------------------------------------------------------------------------
# API-113: Impersonation
# ---------------------------------------------------------------------------


class TestImpersonate:
    """POST /api/v1/platform/impersonate"""

    def test_impersonate_requires_platform_admin(self, client, tenant_headers):
        """Non-platform users get 403."""
        resp = client.post(
            "/api/v1/platform/impersonate",
            json={"tenant_id": TEST_TENANT_ID, "reason": "Testing access here"},
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_impersonate_requires_reason_min_length(self, client, platform_headers):
        """reason shorter than 10 chars returns 422."""
        resp = client.post(
            "/api/v1/platform/impersonate",
            json={"tenant_id": TEST_TENANT_ID, "reason": "short"},
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_impersonate_requires_reason_field(self, client, platform_headers):
        """Missing reason field returns 422."""
        resp = client.post(
            "/api/v1/platform/impersonate",
            json={"tenant_id": TEST_TENANT_ID},
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_impersonate_unknown_tenant_404(self, env_vars):
        """Unknown tenant_id returns 404."""
        from app.modules.platform import routes as plat_routes
        from fastapi import HTTPException
        import asyncio

        mock_session = AsyncMock()

        # Tenant not found
        tenant_result = MagicMock()
        tenant_result.fetchone.return_value = None

        mock_session.execute.side_effect = [tenant_result]

        async def _run():
            from app.core.dependencies import CurrentUser

            caller = CurrentUser(
                id=TEST_PLATFORM_USER_ID,
                tenant_id="default",
                roles=["platform_admin"],
                scope="platform",
                plan="enterprise",
            )
            req = plat_routes.ImpersonateRequest(
                tenant_id=TEST_TENANT_ID,
                reason="Investigating reported issue",
            )
            with pytest.raises(HTTPException) as exc_info:
                await plat_routes.impersonate_tenant(
                    body=req,
                    current_user=caller,
                    db=mock_session,
                )
            assert exc_info.value.status_code == 404

        asyncio.run(_run())

    def test_impersonate_generates_token_with_claims(self, env_vars):
        """
        Successful impersonation returns a JWT with expected claims:
        impersonated_by, tenant_id, roles=['tenant_admin'], scope='tenant'.
        """
        from app.modules.platform import routes as plat_routes
        from jose import jwt as jose_jwt
        import asyncio

        mock_session = AsyncMock()

        # Tenant found — tuple matches SELECT id, name, plan FROM tenants
        tenant_result = MagicMock()
        tenant_result.fetchone.return_value = (
            uuid.UUID(TEST_TENANT_ID),
            "Acme Corp",
            "professional",
        )
        mock_session.execute.side_effect = [
            tenant_result,
            AsyncMock(return_value=None)(),  # audit log INSERT
            AsyncMock(return_value=None)(),  # audit log commit
        ]
        mock_session.commit = AsyncMock()

        async def _run():
            from app.core.dependencies import CurrentUser

            caller = CurrentUser(
                id=TEST_PLATFORM_USER_ID,
                tenant_id="default",
                roles=["platform_admin"],
                scope="platform",
                plan="enterprise",
            )
            req = plat_routes.ImpersonateRequest(
                tenant_id=TEST_TENANT_ID,
                reason="Customer escalation investigation",
            )
            result = await plat_routes.impersonate_tenant(
                body=req,
                current_user=caller,
                db=mock_session,
            )

            assert "impersonation_token" in result
            assert result["expires_in"] == 3600
            assert result["tenant_id"] == TEST_TENANT_ID

            # Decode and verify claims
            token_payload = jose_jwt.decode(
                result["impersonation_token"],
                TEST_JWT_SECRET,
                algorithms=[TEST_JWT_ALGORITHM],
            )
            assert token_payload["impersonated_by"] == TEST_PLATFORM_USER_ID
            assert token_payload["tenant_id"] == TEST_TENANT_ID
            assert token_payload["roles"] == ["tenant_admin"]
            assert token_payload["scope"] == "tenant"
            assert token_payload["token_version"] == 2

        asyncio.run(_run())

    def test_impersonate_invalid_uuid_tenant_id(self, client, platform_headers):
        """Non-UUID tenant_id returns 422."""
        resp = client.post(
            "/api/v1/platform/impersonate",
            json={"tenant_id": "not-a-uuid", "reason": "Testing something here"},
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_impersonate_requires_auth(self, client):
        """No auth header returns 401."""
        resp = client.post(
            "/api/v1/platform/impersonate",
            json={"tenant_id": TEST_TENANT_ID, "reason": "Testing access"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# API-114: End impersonation
# ---------------------------------------------------------------------------


class TestEndImpersonation:
    """POST /api/v1/platform/impersonate/end"""

    def test_end_impersonation_requires_auth(self, client):
        """No auth returns 401."""
        resp = client.post("/api/v1/platform/impersonate/end")
        assert resp.status_code == 401

    def test_end_impersonation_without_impersonated_claim_400(self, env_vars):
        """
        Token without impersonated_by claim returns 400.
        Uses a regular end_user token (no impersonation claims).
        """
        from app.modules.platform import routes as plat_routes
        from fastapi import HTTPException
        import asyncio

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        # Regular end_user token (no impersonated_by claim)
        regular_token = _make_token(
            user_id=TEST_TENANT_USER_ID,
            tenant_id=TEST_TENANT_ID,
            scope="tenant",
            roles=["end_user"],
        )

        async def _run():
            from app.core.dependencies import CurrentUser

            caller = CurrentUser(
                id=TEST_TENANT_USER_ID,
                tenant_id=TEST_TENANT_ID,
                roles=["end_user"],
                scope="tenant",
                plan="professional",
            )
            with pytest.raises(HTTPException) as exc_info:
                await plat_routes.end_impersonation(
                    current_user=caller,
                    db=mock_session,
                    raw_authorization=f"Bearer {regular_token}",
                )
            assert exc_info.value.status_code == 400
            assert "impersonation" in exc_info.value.detail.lower()

        asyncio.run(_run())

    def test_end_impersonation_with_valid_impersonation_token(self, env_vars):
        """
        Token with impersonated_by claim returns {"status": "ended", "duration_seconds": int}.
        """
        from app.modules.platform import routes as plat_routes
        import asyncio

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock()

        impersonation_token = _make_tenant_token(impersonated_by=TEST_PLATFORM_USER_ID)

        async def _run():
            from app.core.dependencies import CurrentUser

            caller = CurrentUser(
                id=TEST_PLATFORM_USER_ID,
                tenant_id=TEST_TENANT_ID,
                roles=["tenant_admin"],
                scope="tenant",
                plan="professional",
            )
            with patch.object(plat_routes, "get_redis") as mock_get_redis:
                mock_redis = AsyncMock()
                mock_redis.set = AsyncMock()
                mock_get_redis.return_value = mock_redis

                result = await plat_routes.end_impersonation(
                    current_user=caller,
                    db=mock_session,
                    raw_authorization=f"Bearer {impersonation_token}",
                )
                assert result["status"] == "ended"
                assert isinstance(result["duration_seconds"], int)
                assert result["duration_seconds"] >= 0

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# API-115: Platform preferences
# ---------------------------------------------------------------------------


class TestPlatformPreferences:
    """GET + PATCH /api/v1/platform/preferences"""

    def test_platform_preferences_requires_platform_admin(self, client, tenant_headers):
        """Non-platform users get 403."""
        resp = client.get("/api/v1/platform/preferences", headers=tenant_headers)
        assert resp.status_code == 403

    def test_platform_preferences_patch_requires_platform_admin(
        self, client, tenant_headers
    ):
        resp = client.patch(
            "/api/v1/platform/preferences",
            json={"daily_digest_enabled": True},
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_platform_preferences_digest_time_validation(self, env_vars):
        """Invalid HH:MM format returns 422."""
        from app.modules.platform import routes as plat_routes
        from fastapi import HTTPException
        import asyncio

        async def _run():
            from app.core.dependencies import CurrentUser

            caller = CurrentUser(
                id=TEST_PLATFORM_USER_ID,
                tenant_id="default",
                roles=["platform_admin"],
                scope="platform",
                plan="enterprise",
            )
            with patch.object(plat_routes, "get_redis") as mock_get_redis:
                mock_redis = AsyncMock()
                mock_redis.get = AsyncMock(return_value=None)
                mock_get_redis.return_value = mock_redis

                req = plat_routes.PlatformPreferencesRequest(
                    daily_digest_time="25:99",  # invalid
                )
                with pytest.raises(HTTPException) as exc_info:
                    await plat_routes.update_platform_preferences(
                        body=req,
                        current_user=caller,
                    )
                assert exc_info.value.status_code == 422
                assert "HH:MM" in exc_info.value.detail

        asyncio.run(_run())

    def test_platform_preferences_valid_time_accepted(self, env_vars):
        """Valid HH:MM format is accepted and stored."""
        from app.modules.platform import routes as plat_routes
        import asyncio

        async def _run():
            from app.core.dependencies import CurrentUser

            caller = CurrentUser(
                id=TEST_PLATFORM_USER_ID,
                tenant_id="default",
                roles=["platform_admin"],
                scope="platform",
                plan="enterprise",
            )
            with patch.object(plat_routes, "get_redis") as mock_get_redis:
                mock_redis = AsyncMock()
                mock_redis.get = AsyncMock(return_value=None)
                mock_redis.set = AsyncMock()
                mock_get_redis.return_value = mock_redis

                req = plat_routes.PlatformPreferencesRequest(
                    daily_digest_time="14:30",
                )
                result = await plat_routes.update_platform_preferences(
                    body=req,
                    current_user=caller,
                )
                assert result["daily_digest_time"] == "14:30"

        asyncio.run(_run())

    def test_platform_preferences_get_returns_defaults(self, env_vars):
        """GET preferences returns default values when nothing is stored."""
        from app.modules.platform import routes as plat_routes
        import asyncio

        async def _run():
            from app.core.dependencies import CurrentUser

            caller = CurrentUser(
                id=TEST_PLATFORM_USER_ID,
                tenant_id="default",
                roles=["platform_admin"],
                scope="platform",
                plan="enterprise",
            )
            with patch.object(plat_routes, "get_redis") as mock_get_redis:
                mock_redis = AsyncMock()
                mock_redis.get = AsyncMock(return_value=None)
                mock_get_redis.return_value = mock_redis

                result = await plat_routes.get_platform_preferences(
                    current_user=caller,
                )
                assert result["daily_digest_enabled"] is True
                assert result["daily_digest_time"] == "08:00"
                assert result["alert_thresholds"]["cost_spike_pct"] == 20.0
                assert result["alert_thresholds"]["health_score_min"] == 60

        asyncio.run(_run())

    def test_platform_preferences_midnight_time_valid(self, env_vars):
        """00:00 is a valid digest time."""
        from app.modules.platform import routes as plat_routes
        import asyncio

        async def _run():
            from app.core.dependencies import CurrentUser

            caller = CurrentUser(
                id=TEST_PLATFORM_USER_ID,
                tenant_id="default",
                roles=["platform_admin"],
                scope="platform",
                plan="enterprise",
            )
            with patch.object(plat_routes, "get_redis") as mock_get_redis:
                mock_redis = AsyncMock()
                mock_redis.get = AsyncMock(return_value=None)
                mock_redis.set = AsyncMock()
                mock_get_redis.return_value = mock_redis

                req = plat_routes.PlatformPreferencesRequest(
                    daily_digest_time="00:00",
                )
                result = await plat_routes.update_platform_preferences(
                    body=req,
                    current_user=caller,
                )
                assert result["daily_digest_time"] == "00:00"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# API-116: GDPR delete
# ---------------------------------------------------------------------------


class TestGdprDelete:
    """POST /api/v1/platform/tenants/{tenant_id}/gdpr-delete"""

    def test_gdpr_delete_requires_platform_admin(self, client, tenant_headers):
        """Non-platform users get 403."""
        resp = client.post(
            f"/api/v1/platform/tenants/{TEST_TENANT_ID}/gdpr-delete",
            json={"confirmed": True, "deletion_reference": "GDPR-2026-001"},
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_gdpr_delete_requires_confirmed_true(self, env_vars):
        """confirmed=false raises 422."""
        from app.modules.platform import routes as plat_routes
        from fastapi import HTTPException
        import asyncio

        mock_session = AsyncMock()

        async def _run():
            from app.core.dependencies import CurrentUser

            caller = CurrentUser(
                id=TEST_PLATFORM_USER_ID,
                tenant_id="default",
                roles=["platform_admin"],
                scope="platform",
                plan="enterprise",
            )
            req = plat_routes.GdprDeleteRequest(
                confirmed=False,
                deletion_reference="GDPR-2026-001",
            )
            with pytest.raises(HTTPException) as exc_info:
                await plat_routes.gdpr_delete_tenant(
                    tenant_id=TEST_TENANT_ID,
                    body=req,
                    current_user=caller,
                    db=mock_session,
                )
            assert exc_info.value.status_code == 422
            assert "confirmed" in exc_info.value.detail.lower()

        asyncio.run(_run())

    def test_gdpr_delete_requires_deletion_reference(self, env_vars):
        """Empty deletion_reference raises 422 via Pydantic min_length."""
        from app.modules.platform import routes as plat_routes

        with pytest.raises(Exception):
            plat_routes.GdprDeleteRequest(
                confirmed=True,
                deletion_reference="",
            )

    def test_gdpr_delete_unknown_tenant_404(self, env_vars):
        """Unknown tenant_id returns 404."""
        from app.modules.platform import routes as plat_routes
        from fastapi import HTTPException
        import asyncio

        mock_session = AsyncMock()

        tenant_result = MagicMock()
        tenant_result.fetchone.return_value = None
        mock_session.execute = AsyncMock(return_value=tenant_result)

        async def _run():
            from app.core.dependencies import CurrentUser

            caller = CurrentUser(
                id=TEST_PLATFORM_USER_ID,
                tenant_id="default",
                roles=["platform_admin"],
                scope="platform",
                plan="enterprise",
            )
            req = plat_routes.GdprDeleteRequest(
                confirmed=True,
                deletion_reference="GDPR-2026-001",
            )
            with pytest.raises(HTTPException) as exc_info:
                await plat_routes.gdpr_delete_tenant(
                    tenant_id=TEST_TENANT_ID,
                    body=req,
                    current_user=caller,
                    db=mock_session,
                )
            assert exc_info.value.status_code == 404

        asyncio.run(_run())

    def test_gdpr_delete_completes_synchronously(self, env_vars):
        """
        Successful request executes pipeline synchronously and returns
        status=completed with a confirmation report.
        """
        from app.modules.platform import routes as plat_routes
        import asyncio

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.execute = AsyncMock()

        tenant_result = MagicMock()
        tenant_result.fetchone.return_value = (
            uuid.UUID(TEST_TENANT_ID),
            "Test Corp",
            "professional",
        )
        mock_session.execute.return_value = tenant_result

        fake_report = {
            "dry_run": False,
            "deleted_tables": ["tenants (soft-deleted)"],
            "retained_for_legal_hold": ["usage_events"],
            "counts": {"users_anonymized": 3},
            "completed_at": "2026-03-16T00:00:00+00:00",
        }

        async def _run():
            from app.core.dependencies import CurrentUser

            caller = CurrentUser(
                id=TEST_PLATFORM_USER_ID,
                tenant_id="default",
                roles=["platform_admin"],
                scope="platform",
                plan="enterprise",
            )
            req = plat_routes.GdprDeleteRequest(
                confirmed=True,
                deletion_reference="GDPR-2026-001",
            )
            with patch.object(
                plat_routes,
                "_execute_gdpr_pipeline",
                new=AsyncMock(return_value=fake_report),
            ):
                with patch.object(plat_routes, "_insert_platform_audit_log"):
                    with patch.object(plat_routes, "get_redis") as mock_get_redis:
                        mock_redis = AsyncMock()
                        mock_redis.scan = AsyncMock(return_value=(0, []))
                        mock_redis.delete = AsyncMock()
                        mock_get_redis.return_value = mock_redis

                        result = await plat_routes.gdpr_delete_tenant(
                            tenant_id=TEST_TENANT_ID,
                            body=req,
                            current_user=caller,
                            db=mock_session,
                        )

            assert result["status"] == "completed"
            assert "report" in result
            assert result["report"]["deleted_tables"] == ["tenants (soft-deleted)"]

        asyncio.run(_run())

    def test_gdpr_delete_invalid_tenant_uuid(self, env_vars):
        """Non-UUID tenant_id returns 422."""
        from app.modules.platform import routes as plat_routes
        from fastapi import HTTPException
        import asyncio

        mock_session = AsyncMock()

        async def _run():
            from app.core.dependencies import CurrentUser

            caller = CurrentUser(
                id=TEST_PLATFORM_USER_ID,
                tenant_id="default",
                roles=["platform_admin"],
                scope="platform",
                plan="enterprise",
            )
            req = plat_routes.GdprDeleteRequest(
                confirmed=True,
                deletion_reference="GDPR-2026-001",
            )
            with pytest.raises(HTTPException) as exc_info:
                await plat_routes.gdpr_delete_tenant(
                    tenant_id="not-a-uuid",
                    body=req,
                    current_user=caller,
                    db=mock_session,
                )
            assert exc_info.value.status_code == 422

        asyncio.run(_run())
