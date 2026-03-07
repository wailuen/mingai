"""
API Router - aggregates all module routers.

All endpoints are under /api/v1/ prefix.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")

# Auth endpoints (API-001 to API-010)
from app.modules.auth.routes import router as auth_router

router.include_router(auth_router)

# Issue reports endpoints (API-013) — must be before chat to avoid route collision
# Chat module has legacy /issues endpoint; this module provides the full CRUD
from app.modules.issues.routes import router as issues_router

router.include_router(issues_router)

# Chat endpoints (API-007 to API-014)
from app.modules.chat.routes import router as chat_router

router.include_router(chat_router)

# Users endpoints (API-041 to API-050)
from app.modules.users.routes import router as users_router

router.include_router(users_router)

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
