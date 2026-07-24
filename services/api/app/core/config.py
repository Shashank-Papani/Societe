from __future__ import annotations

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

    cognito_region: str = "us-west-2"
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    cognito_accept_id_tokens: bool = False
    cognito_allowed_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])

    cursor_hmac_secret: SecretStr = Field(
        default=SecretStr("dev-only-cursor-hmac-change-me-0123456789abcdef")
    )
    cursor_ttl_seconds: int = 1800
    venue_static_cache_ttl_seconds: int = 600
    idempotency_ttl_seconds: int = 86_400

    # Presence — server clock is authoritative. observed_at only gates freshness.
    max_evidence_age_seconds: int = 15
    max_observed_future_skew_seconds: int = 5
    presence_candidate_radius_m: int = 150
    verified_lease_seconds: int = 120
    degraded_grace_seconds: int = 300
    evidence_idempotency_ttl_seconds: int = 900
    location_rate_limit_per_user_per_minute: int = 20
    location_rate_limit_per_device_per_minute: int = 20
    presence_sample_buffer_max: int = 12
    presence_sample_buffer_ttl_seconds: int = 120
    evidence_absolute_max_retention_hours: int = 36
    default_purge_timezone: str = "America/Los_Angeles"

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
    ff_location_simulator: bool = False

    @model_validator(mode="after")
    def reject_location_simulator_outside_development(self) -> Settings:
        if self.ff_location_simulator and self.app_env in {"staging", "production"}:
            msg = (
                "FF_LOCATION_SIMULATOR=true is forbidden when APP_ENV is "
                f"{self.app_env!r}. The simulator bypasses mock-location rejection."
            )
            raise ValueError(msg)
        if self.ff_location_simulator and self.app_env not in {"development", "test"}:
            msg = "FF_LOCATION_SIMULATOR=true requires APP_ENV development or test."
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_presence_settings(self) -> Settings:
        try:
            ZoneInfo(self.default_purge_timezone)
        except ZoneInfoNotFoundError as exc:
            msg = (
                f"DEFAULT_PURGE_TIMEZONE {self.default_purge_timezone!r} is not a valid IANA zone."
            )
            raise ValueError(msg) from exc
        if self.degraded_grace_seconds < self.verified_lease_seconds:
            msg = "DEGRADED_GRACE_SECONDS must be >= VERIFIED_LEASE_SECONDS."
            raise ValueError(msg)
        for name, value in (
            ("MAX_EVIDENCE_AGE_SECONDS", self.max_evidence_age_seconds),
            ("MAX_OBSERVED_FUTURE_SKEW_SECONDS", self.max_observed_future_skew_seconds),
            ("PRESENCE_CANDIDATE_RADIUS_M", self.presence_candidate_radius_m),
            ("VERIFIED_LEASE_SECONDS", self.verified_lease_seconds),
            ("PRESENCE_SAMPLE_BUFFER_MAX", self.presence_sample_buffer_max),
            ("PRESENCE_SAMPLE_BUFFER_TTL_SECONDS", self.presence_sample_buffer_ttl_seconds),
            ("EVIDENCE_ABSOLUTE_MAX_RETENTION_HOURS", self.evidence_absolute_max_retention_hours),
        ):
            if value <= 0:
                msg = f"{name} must be greater than zero."
                raise ValueError(msg)
        return self

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
        if self.cursor_hmac_secret.get_secret_value() in {
            "",
            "replace-me-cursor-hmac",
        }:
            msg = "CURSOR_HMAC_SECRET must be set."
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
