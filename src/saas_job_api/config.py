"""Runtime configuration for the reference SaaS Job API."""

from __future__ import annotations

import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_DEFAULT_TOKENS = '{"dev-gateway-token": "gw_dev_local"}'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAAS_JOB_API_", extra="ignore")

    # JSON object string: {"<bearer-token>": "<gatewayId>"}
    gateway_tokens_json: str = _DEV_DEFAULT_TOKENS
    admin_token: str = "dev-admin-token"
    reservation_ttl_seconds: float = 60.0
    default_max_jobs: int = 20
    default_poll_after_ms: int = 2000
    seed_file: str | None = None
    
    # PostgreSQL connection URL (None = use in-memory store for dev)
    database_url: str | None = None

    # Logging level
    log_level: str = "INFO"

    # Phase 1.1: gateway registration (mTLS) + RBAC (JWT)
    enrollment_token_ttl_seconds: float = 86_400.0  # 24h
    gateway_certificate_validity_days: int = 30
    # PEM text. Both unset -> main.py generates an ephemeral CA at startup
    # with a warning (dev/test only: every restart then invalidates every
    # previously-issued gateway certificate). Production must configure both.
    ca_private_key_pem: str | None = None
    ca_certificate_pem: str | None = None
    jwt_secret: str = "dev-jwt-secret-change-in-production"
    jwt_ttl_seconds: float = 3_600.0  # 1h
    # If both are set and the username doesn't already exist, main.py seeds
    # one platform_admin principal at startup so there's a way to log in.
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None

    @property
    def gateway_tokens(self) -> dict[str, str]:
        return json.loads(self.gateway_tokens_json)

    @field_validator("gateway_tokens_json")
    @classmethod
    def _validate_json_object(cls, value: str) -> str:
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("SAAS_JOB_API_GATEWAY_TOKENS_JSON must be a JSON object")
        return value


settings = Settings()
