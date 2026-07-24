from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "societe-api"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_debug: bool = False
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    auth_provider: Literal["local", "cognito"] = "local"
    jwt_secret: SecretStr = Field(default=SecretStr("dev-only-insecure-secret-change-me"))
    jwt_algorithm: str = "HS256"
    jwt_access_token_minutes: int = 60
    local_dev_subject: str = "local-dev-user"
    local_dev_handle: str = "localdev"

    database_url: str = "postgresql+asyncpg://societe:societe@localhost:5432/societe"
    valkey_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "http://localhost:9000"
    minio_root_user: str = "societe"
    minio_root_password: SecretStr = Field(default=SecretStr("societe-minio-dev"))
    minio_bucket: str = "societe-local"

    otel_enabled: bool = False
    otel_service_name: str = "societe-api"
    otel_exporter_otlp_endpoint: str | None = None

    ff_live_crowd_counts: bool = False
    ff_calling_cards: bool = False
    ff_venue_people_discovery: bool = False
    ff_qr_verification: bool = False
    ff_ble_verification: bool = False
    ff_media_posting: bool = False
    ff_automated_moderation: bool = False
    ff_ghost_mode: bool = True

    @model_validator(mode="after")
    def reject_local_auth_outside_development(self) -> Settings:
        if self.auth_provider == "local" and self.app_env in {"staging", "production"}:
            msg = (
                "AUTH_PROVIDER=local is forbidden when APP_ENV is "
                f"{self.app_env!r}. Use a non-local auth provider."
            )
            raise ValueError(msg)
        if self.auth_provider == "local" and self.jwt_secret.get_secret_value() in {
            "",
            "replace-me-with-openssl-rand-hex-32",
        }:
            msg = "JWT_SECRET must be set to a strong value for local auth."
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
