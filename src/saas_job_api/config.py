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
