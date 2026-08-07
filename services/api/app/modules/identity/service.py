from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    AuthRefreshSession,
    ProfileMediaAsset,
    User,
    UserDevice,
    UserInterest,
    UserPolicyAcceptance,
    UserPrivacySettings,
)
from app.modules.identity.age import evaluate_age
from app.modules.identity.handles import normalize_handle, validate_handle
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.session_service import SessionService

INACTIVE_STATUSES = frozenset({"deletion_requested", "deleted", "suspended", "deactivated"})


def effective_privacy(privacy: UserPrivacySettings) -> dict[str, Any]:
    ghost = privacy.ghost_mode
    return {
        "ghost_mode": privacy.ghost_mode,
        "discoverable_in_venue": privacy.discoverable_in_venue,
        "allow_calling_cards": privacy.allow_calling_cards,
        "allow_messages_from_connections": privacy.allow_messages_from_connections,
        "show_social_links_after_accept": privacy.show_social_links_after_accept,
        "analytics_opt_out": privacy.analytics_opt_out,
        "notify_calling_cards": privacy.notify_calling_cards,
        "notify_messages": privacy.notify_messages,
        "effective": {
            "discoverable_in_venue": False if ghost else privacy.discoverable_in_venue,
            "allow_calling_cards": False if ghost else privacy.allow_calling_cards,
            "allow_messages_from_connections": (
                False if ghost else privacy.allow_messages_from_connections
            ),
            "ghost_mode_overrides": ghost,
        },
    }


def serialize_user(
    user: User,
    *,
    include_private: bool = True,
    interests: list[str] | None = None,
    profile_photo_url: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    privacy = user.privacy
    if privacy is None:
        raise AppError("PRIVACY_MISSING", "Privacy settings missing.", status_code=500)
    payload: dict[str, Any] = {
        "id": str(user.id),
        "handle": user.handle,
        "display_name": user.display_name,
        "bio": user.bio,
        "age_verified": user.age_verified,
        "age_band": user.age_band,
        "account_status": user.account_status,
        "onboarding_state": user.onboarding_state,
        "onboarding_completed": user.onboarding_state == "completed",
        "handle_locked": user.handle_locked_at is not None,
        "interests": interests or [],
        "profile_photo_url": profile_photo_url,
        "privacy": effective_privacy(privacy),
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }
    if include_private:
        payload["date_of_birth"] = (
            user.date_of_birth.isoformat() if user.date_of_birth is not None else None
        )
        if settings is not None:
            payload["required_policy_versions"] = {
                "terms_of_service": settings.tos_version,
                "privacy_policy": settings.privacy_policy_version,
            }
            payload["minimum_age_years"] = settings.minimum_age_years
    return payload


def serialize_device(device: UserDevice, *, current: bool = False) -> dict[str, Any]:
    return {
        "id": str(device.id),
        "platform": device.platform,
        "installation_id": str(device.installation_id),
        "app_version": device.app_version,
        "os_version": device.os_version,
        "attestation_status": device.attestation_status,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "created_at": device.created_at.isoformat(),
        "revoked": device.revoked_at is not None,
        "is_current": current,
    }


class IdentityService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._repo = IdentityRepository(session)
        self._session = session
        self._settings = settings

    async def resolve_or_provision(self, auth_subject: str) -> User:
        user = await self._repo.get_by_auth_subject(auth_subject)
        if user is None:
            user = await self._repo.create_user(auth_subject=auth_subject)
            await self._repo.save()
            user = await self._repo.get_by_auth_subject(auth_subject)
            assert user is not None
        return user

    async def ensure_dev_persona_ready(self, user: User, *, display_name: str | None) -> User:
        """Dev Alpha/Beta: onboarding-complete, age-eligible, social privacy on."""
        now = datetime.now(UTC)
        user.onboarding_state = "completed"
        user.onboarding_completed_at = user.onboarding_completed_at or now
        user.handle_locked_at = user.handle_locked_at or now
        user.age_verified = True
        if user.age_band is None:
            user.age_band = "25-29"
        if user.date_of_birth is None:
            user.date_of_birth = date(1995, 1, 15)
        if display_name is not None:
            user.display_name = display_name
        privacy = user.privacy
        if privacy is None:
            privacy = UserPrivacySettings(user_id=user.id)
            self._session.add(privacy)
            user.privacy = privacy
        privacy.discoverable_in_venue = True
        privacy.allow_calling_cards = True
        privacy.allow_messages_from_connections = True
        user.updated_at = now
        await self._repo.save()
        refreshed = await self._repo.get_by_id(user.id)
        assert refreshed is not None
        return refreshed

    def assert_active(self, user: User) -> None:
        if user.account_status in INACTIVE_STATUSES or user.deleted_at is not None:
            raise AppError(
                "ACCOUNT_INACTIVE",
                "This account is not available.",
                status_code=403,
            )

    async def interests_for(self, user_id: uuid.UUID) -> list[str]:
        result = await self._session.execute(
            select(UserInterest.tag)
            .where(UserInterest.user_id == user_id)
            .order_by(UserInterest.tag)
        )
        return list(result.scalars().all())

    async def update_profile(self, user: User, patch: dict[str, Any]) -> User:
        self.assert_active(user)
        # Phase 6: username locked after onboarding; never accept age_* from client.
        patch = {
            k: v for k, v in patch.items() if k not in {"age_verified", "age_band", "date_of_birth"}
        }
        if "handle" in patch and patch["handle"] is not None:
            if user.handle_locked_at is not None or user.onboarding_state == "completed":
                raise AppError(
                    "HANDLE_LOCKED",
                    "Username cannot be changed after onboarding.",
                    status_code=403,
                )
            user.handle = validate_handle(patch["handle"])
        if "display_name" in patch and patch["display_name"] is not None:
            user.display_name = patch["display_name"].strip()
            if not user.display_name:
                raise AppError("INVALID_DISPLAY_NAME", "Display name is required.", status_code=400)
        if "bio" in patch:
            user.bio = patch["bio"]
        if "interests" in patch and patch["interests"] is not None:
            await self._replace_interests(user.id, patch["interests"])
        user.updated_at = datetime.now(UTC)
        try:
            await self._repo.save()
        except IntegrityError as exc:
            await self._session.rollback()
            raise AppError(
                "HANDLE_TAKEN",
                "That handle is already taken.",
                status_code=409,
            ) from exc
        refreshed = await self._repo.get_by_id(user.id)
        assert refreshed is not None
        return refreshed

    async def _replace_interests(self, user_id: uuid.UUID, tags: list[str]) -> None:
        cleaned: list[str] = []
        for raw in tags[:20]:
            tag = normalize_handle(raw).replace("_", "")
            if 1 <= len(tag) <= 30 and tag.isalnum():
                cleaned.append(tag)
        existing = await self._session.execute(
            select(UserInterest).where(UserInterest.user_id == user_id)
        )
        for row in existing.scalars().all():
            await self._session.delete(row)
        for tag in sorted(set(cleaned)):
            self._session.add(UserInterest(user_id=user_id, tag=tag))

    async def update_privacy(self, user: User, patch: dict[str, Any]) -> User:
        self.assert_active(user)
        privacy = user.privacy
        if privacy is None:
            privacy = UserPrivacySettings(user_id=user.id)
            self._session.add(privacy)
            user.privacy = privacy
        for field in (
            "ghost_mode",
            "discoverable_in_venue",
            "allow_calling_cards",
            "allow_messages_from_connections",
            "show_social_links_after_accept",
            "analytics_opt_out",
            "notify_calling_cards",
            "notify_messages",
        ):
            if field in patch and patch[field] is not None:
                setattr(privacy, field, patch[field])
        privacy.updated_at = datetime.now(UTC)
        user.updated_at = datetime.now(UTC)
        await self._repo.save()
        refreshed = await self._repo.get_by_id(user.id)
        assert refreshed is not None
        return refreshed

    async def complete_onboarding_profile(
        self, user: User, *, handle: str, display_name: str
    ) -> User:
        self.assert_active(user)
        if user.onboarding_state not in {"authentication_verified", "profile_required"}:
            raise AppError(
                "ONBOARDING_STATE",
                "Profile step is not available in the current onboarding state.",
                status_code=409,
                details={"onboarding_state": user.onboarding_state},
            )
        user.handle = validate_handle(handle)
        user.display_name = display_name.strip()
        if not user.display_name or len(user.display_name) > 80:
            raise AppError("INVALID_DISPLAY_NAME", "Display name is invalid.", status_code=400)
        user.onboarding_state = "age_required"
        user.updated_at = datetime.now(UTC)
        try:
            await self._repo.save()
        except IntegrityError as exc:
            await self._session.rollback()
            raise AppError(
                "HANDLE_TAKEN", "That handle is already taken.", status_code=409
            ) from exc
        refreshed = await self._repo.get_by_id(user.id)
        assert refreshed is not None
        return refreshed

    async def complete_onboarding_age(self, user: User, *, date_of_birth: date) -> User:
        self.assert_active(user)
        if user.onboarding_state not in {"age_required", "age_ineligible"}:
            raise AppError(
                "ONBOARDING_STATE",
                "Age step is not available in the current onboarding state.",
                status_code=409,
                details={"onboarding_state": user.onboarding_state},
            )
        if self._settings is None:
            raise RuntimeError("Settings required for age evaluation")
        evaluation = evaluate_age(date_of_birth, minimum_age_years=self._settings.minimum_age_years)
        user.date_of_birth = date_of_birth
        if not evaluation.eligible:
            user.age_verified = False
            user.age_band = None
            user.onboarding_state = "age_ineligible"
        else:
            user.age_verified = True
            user.age_band = evaluation.age_band
            user.onboarding_state = "policy_acceptance_required"
        user.updated_at = datetime.now(UTC)
        await self._repo.save()
        refreshed = await self._repo.get_by_id(user.id)
        assert refreshed is not None
        return refreshed

    async def complete_onboarding_policies(
        self,
        user: User,
        *,
        tos_version: str,
        privacy_policy_version: str,
        ip_hash: str | None,
        user_agent_hash: str | None,
    ) -> User:
        self.assert_active(user)
        if user.onboarding_state != "policy_acceptance_required":
            raise AppError(
                "ONBOARDING_STATE",
                "Policy step is not available in the current onboarding state.",
                status_code=409,
                details={"onboarding_state": user.onboarding_state},
            )
        if self._settings is None:
            raise RuntimeError("Settings required for policy versions")
        if tos_version != self._settings.tos_version:
            raise AppError(
                "POLICY_VERSION_MISMATCH",
                "Terms of Service version is out of date.",
                status_code=400,
            )
        if privacy_policy_version != self._settings.privacy_policy_version:
            raise AppError(
                "POLICY_VERSION_MISMATCH",
                "Privacy Policy version is out of date.",
                status_code=400,
            )
        now = datetime.now(UTC)
        for policy_type, version in (
            ("terms_of_service", tos_version),
            ("privacy_policy", privacy_policy_version),
        ):
            existing = await self._session.execute(
                select(UserPolicyAcceptance).where(
                    UserPolicyAcceptance.user_id == user.id,
                    UserPolicyAcceptance.policy_type == policy_type,
                    UserPolicyAcceptance.policy_version == version,
                )
            )
            if existing.scalar_one_or_none() is None:
                self._session.add(
                    UserPolicyAcceptance(
                        user_id=user.id,
                        policy_type=policy_type,
                        policy_version=version,
                        accepted_at=now,
                        accepted_ip_hash=ip_hash,
                        accepted_user_agent_hash=user_agent_hash,
                    )
                )
        user.onboarding_state = "privacy_required"
        user.updated_at = now
        await self._repo.save()
        refreshed = await self._repo.get_by_id(user.id)
        assert refreshed is not None
        return refreshed

    async def complete_onboarding_privacy(self, user: User, patch: dict[str, Any]) -> User:
        self.assert_active(user)
        if user.onboarding_state != "privacy_required":
            raise AppError(
                "ONBOARDING_STATE",
                "Privacy step is not available in the current onboarding state.",
                status_code=409,
                details={"onboarding_state": user.onboarding_state},
            )
        required = (
            "discoverable_in_venue",
            "allow_calling_cards",
            "allow_messages_from_connections",
            "show_social_links_after_accept",
        )
        missing = [f for f in required if f not in patch or patch[f] is None]
        if missing:
            raise AppError(
                "PRIVACY_CHOICES_REQUIRED",
                "Explicit privacy choices are required to finish onboarding.",
                status_code=400,
                details={"missing": missing},
            )
        await self.update_privacy(user, patch)
        now = datetime.now(UTC)
        user = await self._repo.get_by_id(user.id)  # type: ignore[assignment]
        assert user is not None
        user.onboarding_state = "completed"
        user.onboarding_completed_at = now
        user.handle_locked_at = now
        user.updated_at = now
        await self._repo.save()
        refreshed = await self._repo.get_by_id(user.id)
        assert refreshed is not None
        return refreshed

    async def username_available(self, handle: str, *, excluding_user_id: uuid.UUID) -> bool:
        normalized = validate_handle(handle)
        result = await self._session.execute(
            select(User).where(User.deleted_at.is_(None)).where(User.handle.ilike(normalized))
        )
        other = result.scalar_one_or_none()
        return other is None or other.id == excluding_user_id

    async def register_device(
        self,
        user: User,
        *,
        platform: str,
        installation_id: uuid.UUID,
        app_version: str | None,
        os_version: str | None,
    ) -> UserDevice:
        self.assert_active(user)
        existing = await self._repo.get_device_by_platform_installation(
            platform=platform, installation_id=installation_id
        )
        now = datetime.now(UTC)
        if existing is not None:
            if existing.user_id != user.id and existing.revoked_at is None:
                other = await self._repo.get_by_id(existing.user_id)
                if other is not None and other.account_status == "active":
                    raise AppError(
                        "DEVICE_ALREADY_REGISTERED",
                        "This installation is registered to another account.",
                        status_code=409,
                    )
            if existing.user_id != user.id:
                raise AppError(
                    "DEVICE_ALREADY_REGISTERED",
                    "This installation is registered to another account.",
                    status_code=409,
                )
            existing.app_version = app_version
            existing.os_version = os_version
            existing.last_seen_at = now
            if existing.revoked_at is not None:
                existing.revoked_at = None
            await self._repo.save()
            return existing

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
        await self._repo.save()
        return device

    async def list_devices(self, user: User) -> list[UserDevice]:
        self.assert_active(user)
        result = await self._session.execute(
            select(UserDevice)
            .where(UserDevice.user_id == user.id)
            .order_by(UserDevice.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke_device(
        self,
        user: User,
        device_id: uuid.UUID,
        *,
        sessions: SessionService | None = None,
    ) -> None:
        self.assert_active(user)
        device = await self._repo.get_device_for_user(user_id=user.id, device_id=device_id)
        if device is None:
            raise AppError("DEVICE_NOT_FOUND", "Device not found.", status_code=404)
        if device.revoked_at is None:
            device.revoked_at = datetime.now(UTC)
            from app.modules.notifications.push import disable_device_push

            disable_device_push(device, now=datetime.now(UTC))
            if sessions is not None:
                await sessions.revoke_device_sessions(user_id=user.id, device_id=device_id)
            await self._repo.save()

    async def deactivate_account(self, user: User, *, sessions: SessionService) -> dict[str, str]:
        self.assert_active(user)
        now = datetime.now(UTC)
        user.account_status = "deactivated"
        user.deactivated_at = now
        user.updated_at = now
        await self._repo.revoke_all_devices(user.id)
        await sessions.revoke_all_for_user(user.id, reason="account_deactivated", now=now)
        await self._repo.save()
        return {"status": "deactivated"}

    async def reactivate_account(
        self,
        user: User,
        *,
        platform: str,
        installation_id: uuid.UUID,
        app_version: str | None,
        os_version: str | None,
        sessions: SessionService,
    ) -> tuple[User, Any]:
        if user.account_status in {"deletion_requested", "deleted"}:
            raise AppError(
                "ACCOUNT_INACTIVE",
                "This account cannot be reactivated.",
                status_code=403,
            )
        if user.account_status != "deactivated":
            raise AppError(
                "ACCOUNT_NOT_DEACTIVATED",
                "This account is not awaiting reactivation.",
                status_code=409,
            )
        now = datetime.now(UTC)
        user.account_status = "active"
        user.deactivated_at = None
        user.updated_at = now
        device = await self.register_device(
            user,
            platform=platform,
            installation_id=installation_id,
            app_version=app_version,
            os_version=os_version,
        )
        tokens = await sessions.create_session(user=user, device=device, now=now)
        await self._repo.save()
        refreshed = await self._repo.get_by_id(user.id)
        assert refreshed is not None
        return refreshed, tokens

    async def request_account_deletion(
        self, user: User, *, sessions: SessionService | None = None
    ) -> dict[str, str]:
        if user.account_status in {"deletion_requested", "deleted"}:
            return {"status": "already_requested"}
        user.account_status = "deletion_requested"
        user.deleted_at = datetime.now(UTC)
        user.updated_at = datetime.now(UTC)
        await self._repo.revoke_all_devices(user.id)
        if sessions is not None:
            await sessions.revoke_all_for_user(user.id, reason="account_deletion")
        await self._repo.save()
        return {"status": "scheduled"}

    async def approved_profile_photo_url(self, user: User) -> str | None:
        if user.profile_photo_media_id is None:
            return None
        asset = await self._session.get(ProfileMediaAsset, user.profile_photo_media_id)
        if asset is None or asset.deleted_at is not None:
            return None
        if asset.moderation_status != "approved" or not asset.processed_object_key:
            return None
        if self._settings is None:
            return f"profile-media:{asset.id}"
        from app.modules.media.storage import build_object_storage

        storage = build_object_storage(self._settings)
        return await storage.presign_get(
            bucket=self._settings.media_processed_bucket,
            key=asset.processed_object_key,
            expires_in=self._settings.media_signed_url_ttl_seconds,
        )

    async def list_sessions_for_devices(
        self, user_id: uuid.UUID
    ) -> dict[uuid.UUID, datetime | None]:
        result = await self._session.execute(
            select(AuthRefreshSession).where(
                AuthRefreshSession.user_id == user_id,
                AuthRefreshSession.revoked_at.is_(None),
            )
        )
        latest: dict[uuid.UUID, datetime | None] = {}
        for row in result.scalars().all():
            prev = latest.get(row.device_id)
            stamp = row.last_used_at or row.created_at
            if prev is None or (stamp and stamp > prev):
                latest[row.device_id] = stamp
        return latest
