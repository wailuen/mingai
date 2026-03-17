"""
API Router - aggregates all module routers.

All endpoints are under /api/v1/ prefix.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")

# Auth endpoints (API-001 to API-010) + admin session management (P3AUTH-011)
from app.modules.auth.routes import _admin_session_router as auth_admin_session_router
from app.modules.auth.routes import router as auth_router

router.include_router(auth_router)
router.include_router(auth_admin_session_router)  # POST /admin/users/{id}/force-logout

# Issue reports endpoints (API-013 to API-023) — must be before chat to avoid route collision
from app.modules.issues.routes import (
    admin_issues_router,
    platform_issues_router,
    router as issues_router,
    webhooks_router,
)

router.include_router(issues_router)
router.include_router(admin_issues_router)  # GET/PATCH /api/v1/admin/issues/...
router.include_router(platform_issues_router)  # GET/PATCH /api/v1/platform/issues/...
router.include_router(webhooks_router)  # POST /api/v1/webhooks/github

# Chat endpoints (API-007 to API-014)
from app.modules.chat.routes import router as chat_router

router.include_router(chat_router)

# Users endpoints (API-041 to API-050)
from app.modules.users.routes import router as users_router

router.include_router(users_router)

# Admin users endpoints (API-044 bulk invite)
from app.modules.users.routes import admin_users_router

router.include_router(admin_users_router)

# /me endpoints (API-104 GDPR data export)
from app.modules.users.routes import me_router

router.include_router(me_router)

# Memory endpoints (API-099 to API-105)
from app.modules.memory.routes import router as memory_router

router.include_router(memory_router)

# Platform admin endpoints (API-024 to API-034)
from app.modules.tenants.routes import router as tenants_router

router.include_router(tenants_router)

# Glossary endpoints (API-066 to API-075) and TA-013 admin miss-signals
from app.modules.glossary.routes import admin_router as glossary_admin_router
from app.modules.glossary.routes import router as glossary_router

router.include_router(glossary_router)
router.include_router(glossary_admin_router)  # GET /api/v1/admin/glossary/miss-signals

# Teams endpoints (API-051 to API-060)
from app.modules.teams.routes import router as teams_router

router.include_router(teams_router)

# Platform admin dashboard + agent templates + tool catalog (API-038 to API-042)
from app.modules.platform.routes import router as platform_router

router.include_router(platform_router)

# Platform cache analytics endpoints (API-106 to API-109)
from app.modules.platform.cache_analytics import router as cache_analytics_router

router.include_router(cache_analytics_router)

# Admin workspace settings endpoints (API-048/049)
from app.modules.admin.workspace import router as admin_workspace_router

router.include_router(admin_workspace_router)

# Admin semantic cache config endpoints (CACHE-013)
from app.modules.admin.cache_config import router as cache_config_router

router.include_router(cache_config_router)

# Admin per-index cache TTL configuration endpoints (CACHE-005)
from app.modules.admin.index_cache_config import router as index_cache_config_router

router.include_router(index_cache_config_router)

# Admin cache analytics endpoints (CACHE-016)
from app.modules.admin.cache_analytics_admin import (
    router as cache_analytics_admin_router,
)

router.include_router(cache_analytics_admin_router)

# Admin memory policy endpoints (API-076/077)
from app.modules.admin.memory_policy import router as memory_policy_router

router.include_router(memory_policy_router)

# Admin analytics endpoints (FE-037, API-074, API-075 feedback monitoring + engagement)
from app.modules.admin.analytics import router as analytics_router

router.include_router(analytics_router)

# Admin audit log endpoint (API-087)
from app.modules.admin.audit_log import router as audit_log_router

router.include_router(audit_log_router)

# SharePoint document integration endpoints (API-050 to API-056)
from app.modules.documents.sharepoint import (
    admin_sync_router,
    router as sharepoint_router,
)

router.include_router(sharepoint_router)
router.include_router(admin_sync_router)

# Google Drive document integration endpoints (TA-019) and sync worker (DEF-010)
from app.modules.documents.google_drive import router as google_drive_router
from app.modules.documents.google_drive.sync_worker import (
    router as google_drive_sync_router,
    webhook_router as google_drive_webhook_router,
)

router.include_router(google_drive_router)
router.include_router(google_drive_sync_router)
router.include_router(google_drive_webhook_router)

# Notification SSE stream + list/mark-read/preferences (API-012, API-117 to API-120)
from app.modules.notifications.routes import (
    me_notifications_router,
    router as notifications_router,
)

router.include_router(notifications_router)
router.include_router(me_notifications_router)

# Agent templates endpoints (API-110 to API-115)
from app.modules.agents.routes import router as agents_router

router.include_router(agents_router)

# Agent Studio admin endpoints (API-069 to API-073)
from app.modules.agents.routes import admin_router as agents_admin_router

router.include_router(agents_admin_router)

# HAR A2A transaction endpoints (AI-043 to AI-045)
from app.modules.har.routes import router as har_router

router.include_router(har_router)

# Public Agent Registry endpoints (API-089 to API-098)
from app.modules.registry.routes import router as registry_router

router.include_router(registry_router)

# KYB verification endpoints (HAR-012)
from app.modules.registry.kyb_routes import router as kyb_router

router.include_router(kyb_router)

# Platform LLM Library endpoints (P2LLM-005)
from app.modules.platform.llm_library.routes import router as llm_library_router

router.include_router(llm_library_router)

# Platform LLM Provider Credentials endpoints (PVDR-003)
from app.modules.platform.llm_providers.routes import router as llm_providers_router

router.include_router(llm_providers_router)

# Platform Cost Analytics endpoints (P2LLM-012)
from app.modules.platform.cost_analytics import router as cost_analytics_router

router.include_router(cost_analytics_router)

# Platform Cost Alert Thresholds endpoints (PA-015)
from app.modules.platform.cost_alerts import router as cost_alerts_router

router.include_router(cost_alerts_router)

# Admin LLM Config endpoints (P2LLM-006)
from app.modules.admin.llm_config import router as llm_config_router

router.include_router(llm_config_router)

# Admin BYOLLM endpoints (P2LLM-007)
from app.modules.admin.byollm import router as byollm_router

router.include_router(byollm_router)

# Admin KB access control endpoints (TA-007)
from app.modules.admin.kb_access_control import router as kb_access_control_router

router.include_router(kb_access_control_router)

# Admin onboarding wizard endpoints (TA-031)
from app.modules.admin.onboarding import router as onboarding_router

router.include_router(onboarding_router)

# Admin bulk user actions endpoints (TA-032)
from app.modules.admin.bulk_user_actions import router as bulk_user_actions_router

router.include_router(bulk_user_actions_router)

# Admin KB source management endpoints (TA-034)
from app.modules.admin.kb_sources import router as kb_sources_router

router.include_router(kb_sources_router)

# Admin Agent access control endpoints (TA-009)
from app.modules.admin.agent_access_control import router as agent_access_control_router

router.include_router(agent_access_control_router)

# Access request workflow endpoints (TA-010)
from app.modules.admin.access_requests import (
    admin_router as access_requests_admin_router,
    router as access_requests_router,
)

router.include_router(access_requests_router)
router.include_router(access_requests_admin_router)

# Notification preferences endpoints (DEF-003)
from app.modules.users.notification_preferences import (
    router as notification_prefs_router,
)

router.include_router(notification_prefs_router)

# Privacy settings endpoints (DEF-004)
from app.modules.users.privacy_settings import router as privacy_settings_router

router.include_router(privacy_settings_router)

# MCP servers admin endpoints (DEF-005)
from app.modules.admin.mcp_servers import router as mcp_servers_router

router.include_router(mcp_servers_router)

# SSO user import endpoints (TA-033)
from app.modules.admin.sso_import import router as sso_import_router

router.include_router(sso_import_router)

# SAML 2.0 SSO wizard endpoints (P3AUTH-004)
from app.modules.admin.sso_saml import router as sso_saml_router

router.include_router(sso_saml_router)

# OIDC/Google/Okta SSO wizard endpoints (P3AUTH-005/006/007)
from app.modules.admin.sso_oidc import router as sso_oidc_router

router.include_router(sso_oidc_router)

# Role delegation endpoints (TA-035)
from app.modules.admin.role_delegation import router as role_delegation_router

router.include_router(role_delegation_router)

# KB re-index estimate + reindex endpoints (TA-016)
from app.modules.documents.reindex import router as reindex_router

router.include_router(reindex_router)

# Local dev: internal screenshot upload/serve endpoints (API-014 local mode)
# Always registered — HMAC token verification is the auth mechanism.
# Cloud deployments (aws/azure/gcp) never receive requests at these routes.
from app.core.local_storage_routes import router as local_storage_router

router.include_router(local_storage_router)

# Document integrations list endpoint (FE-029 knowledge base page)
# Aggregates SharePoint and Google Drive connections for a tenant.
from fastapi import Depends
from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_integrations_router = APIRouter(prefix="/integrations", tags=["integrations"])


@_integrations_router.get("")
async def list_integrations(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """List document source integrations for the tenant (SharePoint + Google Drive)."""
    result = await session.execute(
        text(
            "SELECT id, provider, status, last_sync_at "
            "FROM integrations WHERE tenant_id = :tid ORDER BY created_at DESC"
        ),
        {"tid": current_user.tenant_id},
    )
    rows = result.fetchall()
    items = [
        {
            "id": str(r[0]),
            "type": r[1],  # "sharepoint" | "googledrive"
            "status": r[2],
            "last_sync": r[3].isoformat() if r[3] else None,
            "document_count": 0,
            "error_count": 0,
        }
        for r in rows
    ]
    return items


router.include_router(_integrations_router)
