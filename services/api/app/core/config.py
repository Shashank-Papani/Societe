from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit
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
    # Keep 60 until mobile refresh + single-retry-on-401 are shipped and tested;
    # 15 minutes is the approved post-refresh default (ADR / Phase 6 plan).
    jwt_access_token_minutes: int = 60
    local_dev_subject: str = "local-dev-user"
    local_dev_handle: str = "localdev"

    cognito_region: str = "us-west-2"
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    cognito_accept_id_tokens: bool = False
    cognito_allowed_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])

    # Phase 6 email OTP (ADR 0018). Mailpit is development/test only.
    email_provider: Literal["mailpit", "ses", "memory"] = "mailpit"
    mailpit_smtp_host: str = "localhost"
    mailpit_smtp_port: int = 1025
    mailpit_ui_url: str = "http://localhost:8025"
    ses_region: str = "us-west-2"
    ses_from_email: str = ""
    otp_ttl_seconds: int = 600
    otp_resend_cooldown_seconds: int = 60
    otp_max_attempts: int = 5
    otp_rate_limit_per_email_per_hour: int = 10
    otp_rate_limit_per_ip_per_hour: int = 30
    refresh_token_days: int = 30
    refresh_rotation_grace_seconds: int = 30
    minimum_age_years: int = 18
    tos_version: str = "2026-07-01"
    privacy_policy_version: str = "2026-07-01"
    profile_photo_max_bytes: int = 5_000_000

    cursor_hmac_secret: SecretStr = Field(
        default=SecretStr("dev-only-cursor-hmac-change-me-0123456789abcdef")
    )
    cursor_ttl_seconds: int = 1800
    venue_static_cache_ttl_seconds: int = 600
    idempotency_ttl_seconds: int = 86_400

    # Presence — server clock is authoritative. observed_at only gates freshness.
    max_evidence_age_seconds: int = 15
    max_observed_future_skew_seconds: int = 5
    # Candidate search must cover retention + outside confirmation distances.
    presence_candidate_radius_m: int = 400
    # Entry / retention hysteresis (meters). Exact product defaults.
    presence_entry_radius_meters: float = 160.9344
    presence_retention_radius_meters: float = 241.4016
    presence_default_max_accuracy_meters: float = 50.0
    # Lease + additive grace (not total wall-clock). Max without evidence = lease + grace.
    verified_lease_seconds: int = 1800
    degraded_grace_seconds: int = 900
    presence_outside_confirmations_required: int = 2
    presence_outside_confirmation_delay_seconds: int = 90
    evidence_idempotency_ttl_seconds: int = 900
    location_rate_limit_per_user_per_minute: int = 20
    location_rate_limit_per_device_per_minute: int = 20
    presence_sample_buffer_max: int = 12
    presence_sample_buffer_ttl_seconds: int = 120
    evidence_absolute_max_retention_hours: int = 36
    default_purge_timezone: str = "America/Los_Angeles"

    database_url: str = "postgresql+asyncpg://societe:societe@localhost:5432/societe"
    valkey_url: str = "redis://localhost:6379/0"

    # Internal endpoint the API and workers dial (http://minio:9000 under Compose).
    minio_endpoint: str = "http://localhost:9000"
    # Client-reachable endpoint used for every presigned URL handed to a device.
    # Never the internal Compose hostname: a phone cannot resolve `minio`.
    minio_public_endpoint: str = "http://localhost:9000"
    minio_region: str = "us-east-1"
    minio_root_user: str = "societe"
    minio_root_password: SecretStr = Field(default=SecretStr("societe-minio-dev"))
    minio_bucket: str = "societe-local"
    media_quarantine_bucket: str = "societe-quarantine"
    media_processed_bucket: str = "societe-processed"

    # Media ingestion (Phase 3). Sizes are bytes.
    media_upload_intent_ttl_seconds: int = 900
    media_presigned_put_ttl_seconds: int = 900
    media_signed_url_ttl_seconds: int = 300
    media_max_image_bytes: int = 12_000_000
    media_max_video_bytes: int = 40_000_000
    media_max_video_duration_ms: int = 15_000
    media_max_image_dimension: int = 8192
    media_max_image_pixels: int = 40_000_000
    media_allowed_image_mime_types: list[str] = Field(
        default_factory=lambda: ["image/jpeg", "image/png", "image/webp"]
    )
    media_allowed_video_mime_types: list[str] = Field(
        default_factory=lambda: ["video/mp4", "video/quicktime"]
    )
    media_caption_max_length: int = 300
    media_max_vibe_tags: int = 10
    media_vibe_tag_max_length: int = 30
    media_upload_rate_limit_per_user_per_hour: int = 20
    media_upload_rate_limit_per_user_per_venue_per_hour: int = 10
    media_pending_intent_limit_per_user: int = 3

    # Processing. ffmpeg/ffprobe are system binaries; arguments are fixed in code.
    ffmpeg_binary_path: str = "ffmpeg"
    ffprobe_binary_path: str = "ffprobe"
    media_ffmpeg_timeout_seconds: int = 90
    media_processing_max_attempts: int = 5
    media_processing_retry_backoff_seconds: int = 30
    media_worker_poll_interval_seconds: int = 5
    media_worker_batch_size: int = 5
    media_worker_heartbeat_path: str = "/tmp/societe-media-processor.heartbeat"
    media_worker_heartbeat_max_age_seconds: int = 120

    media_malware_scanner: Literal["noop", "clamav"] = "noop"
    media_moderation_provider: Literal["fake", "rekognition"] = "fake"
    media_moderation_policy_version: str = "phase3-v1"

    # Publication window and retention.
    vibe_expiry_local_hour: int = 6
    vibe_absolute_max_lifetime_hours: int = 12
    vibe_report_auto_hide_threshold: int = 0
    vibe_report_description_max_length: int = 500
    vibe_report_rate_limit_per_user_per_hour: int = 20
    vibe_feed_page_max: int = 30
    retention_incomplete_upload_hours: int = 24
    retention_processed_original_hours: int = 24
    retention_rejected_original_days: int = 3
    retention_processed_derivative_days: int = 7

    # Calling Cards (Phase 4). Venue is always taken from the caller's lease.
    calling_card_ttl_seconds: int = 1800
    decline_cooldown_seconds: int = 7200
    calling_card_rate_limit_per_user_per_10_minutes: int = 3
    calling_card_rate_limit_per_user_per_venue_night: int = 10
    sensitive_action_lease_min_remaining_seconds: int = 30
    discoverable_list_limit: int = 50

    # Private messaging (Phase 5). Accepted grants are durable (ADR 0014).
    message_body_max_length: int = 2000
    message_rate_limit_per_user_per_minute: int = 30
    conversation_list_page_max: int = 50
    message_list_page_max: int = 50
    realtime_provider: Literal["local", "appsync"] = "local"
    push_provider: Literal["local", "noop"] = "local"
    # After realtime publish, wait for POST /v1/events/{id}/ack before push fallback.
    realtime_ack_wait_seconds: float = 2.0
    realtime_ack_ttl_seconds: int = 300
    event_dispatcher_poll_interval_seconds: int = 2
    event_dispatcher_batch_size: int = 20
    event_dispatcher_max_attempts: int = 12
    event_dispatcher_retry_backoff_seconds: int = 5
    event_dispatcher_heartbeat_path: str = "/tmp/societe-event-dispatcher.heartbeat"
    event_dispatcher_heartbeat_max_age_seconds: int = 120

    otel_enabled: bool = False
    otel_service_name: str = "societe-api"
    otel_exporter_otlp_endpoint: str | None = None

    organization_invitation_ttl_seconds: int = 7 * 86400
    venue_claim_rate_limit_per_user_per_hour: int = 10
    organization_invitation_rate_limit_per_org_per_hour: int = 50

    ff_live_crowd_counts: bool = False
    ff_calling_cards: bool = False
    ff_venue_people_discovery: bool = False
    ff_private_messaging: bool = False
    ff_qr_verification: bool = False
    ff_ble_verification: bool = False
    ff_media_posting: bool = False
    ff_automated_moderation: bool = False
    ff_ghost_mode: bool = True
    ff_location_simulator: bool = False
    ff_venue_organizations: bool = True
    ff_venue_claim_admin: bool = False

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
    def reject_venue_claim_admin_outside_development(self) -> Settings:
        if self.ff_venue_claim_admin and self.app_env in {"staging", "production"}:
            msg = (
                "FF_VENUE_CLAIM_ADMIN=true is forbidden when APP_ENV is "
                f"{self.app_env!r}. Claim admin is a development/test fixture only."
            )
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
        # Grace is additive after lease expiry (lease + grace = max without evidence).
        if self.degraded_grace_seconds <= 0:
            msg = "DEGRADED_GRACE_SECONDS must be greater than zero."
            raise ValueError(msg)
        if self.presence_entry_radius_meters <= 0:
            msg = "PRESENCE_ENTRY_RADIUS_METERS must be greater than zero."
            raise ValueError(msg)
        if self.presence_retention_radius_meters < self.presence_entry_radius_meters:
            msg = (
                "PRESENCE_RETENTION_RADIUS_METERS must be >= PRESENCE_ENTRY_RADIUS_METERS "
                "(hysteresis)."
            )
            raise ValueError(msg)
        if self.presence_outside_confirmations_required < 2:
            msg = "PRESENCE_OUTSIDE_CONFIRMATIONS_REQUIRED must be >= 2."
            raise ValueError(msg)
        if not (60 <= self.presence_outside_confirmation_delay_seconds <= 120):
            msg = "PRESENCE_OUTSIDE_CONFIRMATION_DELAY_SECONDS must be between 60 and 120."
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
    def reject_placeholder_malware_scanner_outside_development(self) -> Settings:
        """A no-op scanner outside dev/test would publish unscanned bytes."""
        if self.media_malware_scanner == "noop" and self.app_env not in {"development", "test"}:
            msg = (
                "MEDIA_MALWARE_SCANNER=noop is forbidden when APP_ENV is "
                f"{self.app_env!r}. Configure a real scanner before enabling uploads."
            )
            raise ValueError(msg)
        if self.media_moderation_provider == "fake" and self.app_env not in {
            "development",
            "test",
        }:
            msg = (
                "MEDIA_MODERATION_PROVIDER=fake is forbidden when APP_ENV is "
                f"{self.app_env!r}. Media must not be published on a stub decision."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_media_settings(self) -> Settings:
        host = urlsplit(self.minio_public_endpoint).hostname
        if host in {"minio", "societe-minio"}:
            msg = (
                "MINIO_PUBLIC_ENDPOINT must be reachable from a device "
                f"(got {self.minio_public_endpoint!r}). Compose-internal hostnames "
                "are not routable from an emulator or a phone."
            )
            raise ValueError(msg)
        if not self.minio_public_endpoint.startswith(("http://", "https://")):
            msg = "MINIO_PUBLIC_ENDPOINT must include an http:// or https:// scheme."
            raise ValueError(msg)
        if self.media_quarantine_bucket == self.media_processed_bucket:
            msg = "MEDIA_QUARANTINE_BUCKET and MEDIA_PROCESSED_BUCKET must differ."
            raise ValueError(msg)
        if not 0 <= self.vibe_expiry_local_hour <= 23:
            msg = "VIBE_EXPIRY_LOCAL_HOUR must be between 0 and 23."
            raise ValueError(msg)
        if self.vibe_report_auto_hide_threshold < 0:
            msg = "VIBE_REPORT_AUTO_HIDE_THRESHOLD must be >= 0 (0 disables auto-hide)."
            raise ValueError(msg)
        for name, value in (
            ("MEDIA_UPLOAD_INTENT_TTL_SECONDS", self.media_upload_intent_ttl_seconds),
            ("MEDIA_PRESIGNED_PUT_TTL_SECONDS", self.media_presigned_put_ttl_seconds),
            ("MEDIA_SIGNED_URL_TTL_SECONDS", self.media_signed_url_ttl_seconds),
            ("MEDIA_MAX_IMAGE_BYTES", self.media_max_image_bytes),
            ("MEDIA_MAX_VIDEO_BYTES", self.media_max_video_bytes),
            ("MEDIA_MAX_VIDEO_DURATION_MS", self.media_max_video_duration_ms),
            ("MEDIA_MAX_IMAGE_DIMENSION", self.media_max_image_dimension),
            ("MEDIA_MAX_IMAGE_PIXELS", self.media_max_image_pixels),
            ("MEDIA_FFMPEG_TIMEOUT_SECONDS", self.media_ffmpeg_timeout_seconds),
            ("MEDIA_PROCESSING_MAX_ATTEMPTS", self.media_processing_max_attempts),
            ("VIBE_ABSOLUTE_MAX_LIFETIME_HOURS", self.vibe_absolute_max_lifetime_hours),
            ("RETENTION_INCOMPLETE_UPLOAD_HOURS", self.retention_incomplete_upload_hours),
            ("RETENTION_PROCESSED_ORIGINAL_HOURS", self.retention_processed_original_hours),
            ("RETENTION_REJECTED_ORIGINAL_DAYS", self.retention_rejected_original_days),
            ("RETENTION_PROCESSED_DERIVATIVE_DAYS", self.retention_processed_derivative_days),
        ):
            if value <= 0:
                msg = f"{name} must be greater than zero."
                raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_calling_card_settings(self) -> Settings:
        for name, value in (
            ("CALLING_CARD_TTL_SECONDS", self.calling_card_ttl_seconds),
            ("DECLINE_COOLDOWN_SECONDS", self.decline_cooldown_seconds),
            (
                "CALLING_CARD_RATE_LIMIT_PER_USER_PER_10_MINUTES",
                self.calling_card_rate_limit_per_user_per_10_minutes,
            ),
            (
                "CALLING_CARD_RATE_LIMIT_PER_USER_PER_VENUE_NIGHT",
                self.calling_card_rate_limit_per_user_per_venue_night,
            ),
            (
                "SENSITIVE_ACTION_LEASE_MIN_REMAINING_SECONDS",
                self.sensitive_action_lease_min_remaining_seconds,
            ),
            ("DISCOVERABLE_LIST_LIMIT", self.discoverable_list_limit),
            ("REALTIME_ACK_TTL_SECONDS", self.realtime_ack_ttl_seconds),
            ("EVENT_DISPATCHER_POLL_INTERVAL_SECONDS", self.event_dispatcher_poll_interval_seconds),
            ("EVENT_DISPATCHER_BATCH_SIZE", self.event_dispatcher_batch_size),
            ("EVENT_DISPATCHER_MAX_ATTEMPTS", self.event_dispatcher_max_attempts),
            ("EVENT_DISPATCHER_RETRY_BACKOFF_SECONDS", self.event_dispatcher_retry_backoff_seconds),
            (
                "EVENT_DISPATCHER_HEARTBEAT_MAX_AGE_SECONDS",
                self.event_dispatcher_heartbeat_max_age_seconds,
            ),
            ("MESSAGE_BODY_MAX_LENGTH", self.message_body_max_length),
            (
                "MESSAGE_RATE_LIMIT_PER_USER_PER_MINUTE",
                self.message_rate_limit_per_user_per_minute,
            ),
            ("CONVERSATION_LIST_PAGE_MAX", self.conversation_list_page_max),
            ("MESSAGE_LIST_PAGE_MAX", self.message_list_page_max),
        ):
            if value <= 0:
                msg = f"{name} must be greater than zero."
                raise ValueError(msg)
        if self.realtime_ack_wait_seconds < 0:
            msg = "REALTIME_ACK_WAIT_SECONDS must be greater than or equal to zero."
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_auth_and_email_settings(self) -> Settings:
        """Societe-minted JWTs (AUTH_PROVIDER=local) power OTP in all envs.

        Dev persona minting remains separately gated to development/test.
        Email provider fails closed outside development/test (ADR 0018).
        """
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
        if self.app_env in {"staging", "production"}:
            if self.email_provider in {"mailpit", "memory"}:
                msg = (
                    f"EMAIL_PROVIDER={self.email_provider!r} is forbidden when "
                    f"APP_ENV is {self.app_env!r}. Configure EMAIL_PROVIDER=ses."
                )
                raise ValueError(msg)
            if self.email_provider == "ses" and not self.ses_from_email:
                msg = "SES_FROM_EMAIL is required when EMAIL_PROVIDER=ses."
                raise ValueError(msg)
        if self.email_provider == "mailpit" and self.app_env not in {"development", "test"}:
            msg = "EMAIL_PROVIDER=mailpit is only allowed in development/test."
            raise ValueError(msg)
        if self.email_provider == "memory" and self.app_env not in {"development", "test"}:
            msg = "EMAIL_PROVIDER=memory is only allowed in development/test."
            raise ValueError(msg)
        if self.minimum_age_years < 13 or self.minimum_age_years > 25:
            msg = "MINIMUM_AGE_YEARS must be between 13 and 25."
            raise ValueError(msg)
        for name, value in (
            ("OTP_TTL_SECONDS", self.otp_ttl_seconds),
            ("OTP_RESEND_COOLDOWN_SECONDS", self.otp_resend_cooldown_seconds),
            ("OTP_MAX_ATTEMPTS", self.otp_max_attempts),
            ("REFRESH_TOKEN_DAYS", self.refresh_token_days),
            ("REFRESH_ROTATION_GRACE_SECONDS", self.refresh_rotation_grace_seconds),
            ("PROFILE_PHOTO_MAX_BYTES", self.profile_photo_max_bytes),
        ):
            if value <= 0:
                msg = f"{name} must be greater than zero."
                raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
