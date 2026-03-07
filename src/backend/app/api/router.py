"""
API Router - aggregates all module routers.

All endpoints are under /api/v1/ prefix.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")

# Auth endpoints (API-001 to API-010)
from app.modules.auth.routes import router as auth_router

router.include_router(auth_router)

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

# Glossary endpoints (API-066 to API-075)
from app.modules.glossary.routes import router as glossary_router

router.include_router(glossary_router)

# Teams endpoints (API-051 to API-060)
from app.modules.teams.routes import router as teams_router

router.include_router(teams_router)

# Platform admin dashboard endpoint
from app.modules.platform.routes import router as platform_router

router.include_router(platform_router)

# Admin workspace settings endpoints (API-048/049)
from app.modules.admin.workspace import router as admin_workspace_router

router.include_router(admin_workspace_router)

# Admin analytics endpoints (FE-037 feedback monitoring)
from app.modules.admin.analytics import router as analytics_router

router.include_router(analytics_router)

# SharePoint document integration endpoints (API-050 to API-055)
from app.modules.documents.sharepoint import router as sharepoint_router

router.include_router(sharepoint_router)

# Notification SSE stream (API-012)
from app.modules.notifications.routes import router as notifications_router

router.include_router(notifications_router)

# Agent templates endpoints (API-110 to API-115)
from app.modules.agents.routes import router as agents_router

router.include_router(agents_router)

# Local dev: internal screenshot upload/serve endpoints (API-014 local mode)
# Always registered — HMAC token verification is the auth mechanism.
# Cloud deployments (aws/azure/gcp) never receive requests at these routes.
from app.core.local_storage_routes import router as local_storage_router

router.include_router(local_storage_router)
