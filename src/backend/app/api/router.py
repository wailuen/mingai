"""
API Router - aggregates all module routers.

All endpoints are under /api/v1/ prefix.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")

# Auth endpoints (API-001 to API-010)
from app.modules.auth.routes import router as auth_router

router.include_router(auth_router)

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
