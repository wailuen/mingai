"""
Application configuration loaded from environment variables.

All API keys, model names, and sensitive config MUST come from .env.
Never hardcode model names or secrets.
"""
import os
from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    """Settings loaded from .env file. All fields are required unless defaulted."""

    # Database
    database_url: str
    redis_url: str

    # Cloud provider: aws | azure | gcp | local
    cloud_provider: str

    # AI Models - from .env, NEVER hardcode
    primary_model: str
    intent_model: str
    embedding_model: str

    # Auth - JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # Auth0 (Phase 2)
    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_management_client_id: str = ""
    auth0_management_client_secret: str = ""

    # Platform
    frontend_url: str
    multi_tenant_enabled: bool = True
    debug: bool = False

    # Platform admin bootstrap
    platform_admin_email: str = ""
    platform_admin_pass: str = ""
    seed_tenant_name: str = ""

    @field_validator("cloud_provider")
    @classmethod
    def validate_cloud_provider(cls, v: str) -> str:
        allowed = {"aws", "azure", "gcp", "local"}
        if v not in allowed:
            raise ValueError(
                f"CLOUD_PROVIDER must be one of {allowed}, got '{v}'"
            )
        return v

    @field_validator("primary_model", "intent_model", "embedding_model")
    @classmethod
    def validate_model_names_not_hardcoded(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "Model name must not be empty. Set PRIMARY_MODEL, INTENT_MODEL, "
                "and EMBEDDING_MODEL in .env"
            )
        return v

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "JWT_SECRET_KEY must not be empty. Generate with: "
                "python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if len(v) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters for security"
            )
        return v

    @field_validator("frontend_url")
    @classmethod
    def validate_frontend_url(cls, v: str) -> str:
        if not v:
            raise ValueError("FRONTEND_URL must be set for CORS configuration")
        if v == "*":
            raise ValueError(
                "FRONTEND_URL must NOT be '*'. Set it to the actual frontend URL."
            )
        return v

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


def get_settings() -> Settings:
    """
    Get application settings. Raises clear errors if required env vars are missing.
    NEVER returns default/fallback values for security-critical settings.
    """
    return Settings()
