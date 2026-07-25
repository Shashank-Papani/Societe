"""Passwordless email OTP with atomic verify (ADR 0018)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import AuthIdentity, OtpChallenge, User, UserDevice, UserPrivacySettings
from app.modules.identity.crypto_util import (
    generate_otp_code,
    hash_optional,
    hash_secret,
    normalize_email,
)
from app.modules.identity.email import EmailMessage, build_email_sender
from app.modules.identity.repository import IdentityRepository, generate_temporary_handle
from app.modules.identity.session_service import SessionService, TokenPair

logger = get_logger(__name__)

GENERIC_OTP_MESSAGE = "If that email can receive codes, one has been sent."


@dataclass(frozen=True)
class OtpVerifyResult:
    tokens: TokenPair | None
    user: User | None
    auth_status: Literal[
        "authenticated",
        "reactivation_required",
        "onboarding_required",
        "age_ineligible",
    ]
    is_new_user: bool


class OtpService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis[str],
        settings: Settings,
    ) -> None:
        self._session = session
        self._redis = redis
        self._settings = settings
        self._repo = IdentityRepository(session)
        self._sessions = SessionService(session, redis, settings)

    async def request_otp(
        self,
        *,
        email: str,
        client_ip: str | None,
    ) -> dict[str, str | int]:
        normalized = normalize_email(email)
        if "@" not in normalized or "." not in normalized.split("@")[-1]:
            # Still generic — do not reveal validation specifics that aid enumeration
            # beyond basic format for UX.
            raise AppError("INVALID_EMAIL", "Enter a valid email address.", status_code=400)

        await self._enforce_rate_limits(normalized_email=normalized, client_ip=client_ip)

        # Resend cooldown against latest active challenge.
        latest = await self._latest_active_challenge(normalized)
        now = datetime.now(UTC)
        if latest is not None:
            elapsed = (now - latest.created_at).total_seconds()
            if elapsed < self._settings.otp_resend_cooldown_seconds:
                retry = int(self._settings.otp_resend_cooldown_seconds - elapsed) + 1
                raise AppError(
                    "OTP_RESEND_COOLDOWN",
                    "Please wait before requesting another code.",
                    status_code=429,
                    details={"retry_after_seconds": retry},
                )
            latest.consumed_at = now

        code = generate_otp_code()
        challenge = OtpChallenge(
            normalized_email=normalized,
            code_hash=hash_secret(code, self._settings),
            purpose="login",
            expires_at=now + timedelta(seconds=self._settings.otp_ttl_seconds),
            max_attempts=self._settings.otp_max_attempts,
            created_ip_hash=hash_optional(client_ip, self._settings),
        )
        self._session.add(challenge)
        await self._session.flush()

        sender = build_email_sender(self._settings)
        await sender.send(
            EmailMessage(
                to_address=normalized,
                subject="Your Société sign-in code",
                text_body=(
                    f"Your Société verification code is {code}.\n\n"
                    f"It expires in {self._settings.otp_ttl_seconds // 60} minutes.\n"
                    "If you did not request this, you can ignore this email.\n"
                ),
            )
        )
        logger.info("otp_requested", email_domain=normalized.split("@")[-1])
        return {
            "message": GENERIC_OTP_MESSAGE,
            "expires_in_seconds": self._settings.otp_ttl_seconds,
            "resend_after_seconds": self._settings.otp_resend_cooldown_seconds,
        }

    async def verify_otp(
        self,
        *,
        email: str,
        code: str,
        platform: Literal["ios", "android"],
        installation_id: uuid.UUID,
        app_version: str | None,
        os_version: str | None,
        client_ip: str | None,
    ) -> OtpVerifyResult:
        normalized = normalize_email(email)
        now = datetime.now(UTC)

        # Lock the newest unconsumed challenge for this email.
        result = await self._session.execute(
            select(OtpChallenge)
            .where(
                OtpChallenge.normalized_email == normalized,
                OtpChallenge.consumed_at.is_(None),
            )
            .order_by(OtpChallenge.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        challenge = result.scalar_one_or_none()
        if challenge is None or challenge.expires_at <= now:
            logger.info("otp_verify_failed", reason="missing_or_expired")
            raise AppError("OTP_INVALID", "Invalid or expired code.", status_code=401)
        if challenge.attempt_count >= challenge.max_attempts:
            logger.info("otp_verify_failed", reason="locked")
            raise AppError("OTP_LOCKED", "Too many attempts. Request a new code.", status_code=429)

        if not hmac_compare(challenge.code_hash, hash_secret(code.strip(), self._settings)):
            challenge.attempt_count += 1
            await self._session.flush()
            logger.info("otp_verify_failed", reason="mismatch")
            raise AppError("OTP_INVALID", "Invalid or expired code.", status_code=401)

        # Consume atomically before provisioning (prevents concurrent double-consume).
        consume = await self._session.execute(
            update(OtpChallenge)
            .where(
                OtpChallenge.id == challenge.id,
                OtpChallenge.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        if int(getattr(consume, "rowcount", 0) or 0) != 1:
            raise AppError("OTP_INVALID", "Invalid or expired code.", status_code=401)

        identity, user, is_new = await self._resolve_identity_and_user(normalized, now=now)

        if user.account_status in {"deletion_requested", "deleted"}:
            raise AppError(
                "ACCOUNT_INACTIVE",
                "This account is not available.",
                status_code=403,
            )

        if user.account_status == "deactivated":
            # Restricted reactivation token: short-lived access only, no refresh.
            from app.core.security import mint_access_token

            access = mint_access_token(
                subject=user.auth_subject,
                handle=user.handle,
                settings=self._settings,
                extra_claims={"reactivation": True},
            )
            logger.info("otp_verified", outcome="reactivation_required")
            return OtpVerifyResult(
                tokens=TokenPair(
                    access_token=access,
                    refresh_token="",
                    expires_in_minutes=self._settings.jwt_access_token_minutes,
                    session_id=uuid.UUID(int=0),
                    device_id=uuid.UUID(int=0),
                ),
                user=user,
                auth_status="reactivation_required",
                is_new_user=False,
            )

        device = await self._register_or_validate_device(
            user=user,
            platform=platform,
            installation_id=installation_id,
            app_version=app_version,
            os_version=os_version,
            now=now,
        )
        tokens = await self._sessions.create_session(user=user, device=device, now=now)
        identity.verified_at = identity.verified_at or now
        identity.updated_at = now
        await self._session.flush()

        if user.onboarding_state == "age_ineligible":
            status: Literal[
                "authenticated", "reactivation_required", "onboarding_required", "age_ineligible"
            ] = "age_ineligible"
        elif user.onboarding_state != "completed":
            status = "onboarding_required"
        else:
            status = "authenticated"

        logger.info("otp_verified", outcome=status, is_new_user=is_new)
        return OtpVerifyResult(tokens=tokens, user=user, auth_status=status, is_new_user=is_new)

    async def _resolve_identity_and_user(
        self, normalized_email: str, *, now: datetime
    ) -> tuple[AuthIdentity, User, bool]:
        result = await self._session.execute(
            select(AuthIdentity)
            .where(
                AuthIdentity.provider == "email",
                AuthIdentity.normalized_email == normalized_email,
            )
            .with_for_update()
        )
        identity = result.scalar_one_or_none()
        if identity is not None:
            user = await self._repo.get_by_id(identity.user_id)
            if user is None:
                raise AppError(
                    "ACCOUNT_INACTIVE", "This account is not available.", status_code=403
                )
            return identity, user, False

        auth_subject = f"email:{normalized_email}"
        existing = await self._repo.get_by_auth_subject(auth_subject)
        if existing is not None:
            try:
                async with self._session.begin_nested():
                    identity = AuthIdentity(
                        user_id=existing.id,
                        provider="email",
                        normalized_email=normalized_email,
                        verified_at=now,
                    )
                    self._session.add(identity)
                    await self._session.flush()
            except IntegrityError:
                identity = await self._load_identity(normalized_email)
                return identity, existing, False
            return identity, existing, False

        user = await self._create_otp_user(auth_subject=auth_subject)
        try:
            async with self._session.begin_nested():
                identity = AuthIdentity(
                    user_id=user.id,
                    provider="email",
                    normalized_email=normalized_email,
                    verified_at=now,
                )
                self._session.add(identity)
                await self._session.flush()
        except IntegrityError:
            identity = await self._load_identity(normalized_email)
            reloaded = await self._repo.get_by_id(identity.user_id)
            assert reloaded is not None
            return identity, reloaded, False
        return identity, user, True

    async def _load_identity(self, normalized_email: str) -> AuthIdentity:
        result = await self._session.execute(
            select(AuthIdentity).where(
                AuthIdentity.provider == "email",
                AuthIdentity.normalized_email == normalized_email,
            )
        )
        identity = result.scalar_one_or_none()
        if identity is None:
            raise AppError("OTP_INVALID", "Invalid or expired code.", status_code=401)
        return identity

    async def _create_otp_user(self, *, auth_subject: str) -> User:
        """New OTP users: incomplete onboarding + conservative privacy defaults."""
        for _ in range(8):
            handle = generate_temporary_handle()
            try:
                async with self._session.begin_nested():
                    user = User(
                        auth_subject=auth_subject,
                        handle=handle,
                        display_name="New Guest",
                        account_status="active",
                        onboarding_state="profile_required",
                        age_verified=False,
                    )
                    privacy = UserPrivacySettings(
                        user=user,
                        ghost_mode=False,
                        discoverable_in_venue=False,
                        allow_calling_cards=False,
                        allow_messages_from_connections=False,
                        show_social_links_after_accept=False,
                        analytics_opt_out=False,
                    )
                    self._session.add(user)
                    self._session.add(privacy)
                    await self._session.flush()
                    return user
            except IntegrityError:
                continue
        raise RuntimeError("Unable to allocate unique handle for OTP user")

    async def _register_or_validate_device(
        self,
        *,
        user: User,
        platform: str,
        installation_id: uuid.UUID,
        app_version: str | None,
        os_version: str | None,
        now: datetime,
    ) -> UserDevice:
        """Device rules during OTP verify:

        - No prior row → create for this user.
        - Same user (active or revoked) → refresh metadata; clear revoke.
        - Other active user → DEVICE_ALREADY_REGISTERED (ownership protection).
        - Other inactive/deleted user → still refuse silent transfer.
        """
        existing = await self._repo.get_device_by_platform_installation(
            platform=platform, installation_id=installation_id
        )
        if existing is None:
            device = UserDevice(
                user_id=user.id,
                platform=platform,
                installation_id=installation_id,
                app_version=app_version,
                os_version=os_version,
                attestation_status="unknown",
                last_seen_at=now,
            )
            self._session.add(device)
            await self._session.flush()
            return device

        if existing.user_id != user.id:
            raise AppError(
                "DEVICE_ALREADY_REGISTERED",
                "This installation is registered to another account.",
                status_code=409,
            )
        existing.app_version = app_version
        existing.os_version = os_version
        existing.last_seen_at = now
        existing.revoked_at = None
        await self._session.flush()
        return existing

    async def _latest_active_challenge(self, normalized_email: str) -> OtpChallenge | None:
        result = await self._session.execute(
            select(OtpChallenge)
            .where(
                OtpChallenge.normalized_email == normalized_email,
                OtpChallenge.consumed_at.is_(None),
            )
            .order_by(OtpChallenge.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _enforce_rate_limits(self, *, normalized_email: str, client_ip: str | None) -> None:
        try:
            email_key = f"auth:otp:email:{hash_secret(normalized_email, self._settings)}"
            email_count = await self._redis.incr(email_key)
            if email_count == 1:
                await self._redis.expire(email_key, 3600)
            if email_count > self._settings.otp_rate_limit_per_email_per_hour:
                raise AppError(
                    "OTP_RATE_LIMITED",
                    "Too many requests. Try again later.",
                    status_code=429,
                )
            if client_ip:
                ip_key = f"auth:otp:ip:{hash_secret(client_ip, self._settings)}"
                ip_count = await self._redis.incr(ip_key)
                if ip_count == 1:
                    await self._redis.expire(ip_key, 3600)
                if ip_count > self._settings.otp_rate_limit_per_ip_per_hour:
                    raise AppError(
                        "OTP_RATE_LIMITED",
                        "Too many requests. Try again later.",
                        status_code=429,
                    )
        except RedisError:
            logger.error("otp_rate_limit_unavailable")
            raise AppError(
                "SERVICE_UNAVAILABLE",
                "Authentication is temporarily unavailable.",
                status_code=503,
            ) from None


def hmac_compare(a: str, b: str) -> bool:
    import hmac as hmac_mod

    return hmac_mod.compare_digest(a, b)
