from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import User, UserDevice, UserPrivacySettings
from app.modules.identity.repository import IdentityRepository

INACTIVE_STATUSES = frozenset({"deletion_requested", "deleted", "suspended"})


def effective_privacy(privacy: UserPrivacySettings) -> dict[str, Any]:
    ghost = privacy.ghost_mode
    return {
        "ghost_mode": privacy.ghost_mode,
        "discoverable_in_venue": privacy.discoverable_in_venue,
        "allow_calling_cards": privacy.allow_calling_cards,
        "show_social_links_after_accept": privacy.show_social_links_after_accept,
        "analytics_opt_out": privacy.analytics_opt_out,
        "effective": {
            "discoverable_in_venue": False if ghost else privacy.discoverable_in_venue,
            "allow_calling_cards": False if ghost else privacy.allow_calling_cards,
            "ghost_mode_overrides": ghost,
        },
    }


def serialize_user(user: User) -> dict[str, Any]:
    privacy = user.privacy
    if privacy is None:
        raise AppError("PRIVACY_MISSING", "Privacy settings missing.", status_code=500)
    return {
        "id": str(user.id),
        "handle": user.handle,
        "display_name": user.display_name,
        "bio": user.bio,
        "age_verified": user.age_verified,
        "age_band": user.age_band,
        "account_status": user.account_status,
        "privacy": effective_privacy(privacy),
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }


def serialize_device(device: UserDevice) -> dict[str, Any]:
    return {
        "id": str(device.id),
        "platform": device.platform,
        "installation_id": str(device.installation_id),
        "app_version": device.app_version,
        "os_version": device.os_version,
        "attestation_status": device.attestation_status,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "created_at": device.created_at.isoformat(),
    }


class IdentityService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = IdentityRepository(session)
        self._session = session

    async def resolve_or_provision(self, auth_subject: str) -> User:
        user = await self._repo.get_by_auth_subject(auth_subject)
        if user is None:
            user = await self._repo.create_user(auth_subject=auth_subject)
            await self._repo.save()
            user = await self._repo.get_by_auth_subject(auth_subject)
            assert user is not None
        return user

    def assert_active(self, user: User) -> None:
        if user.account_status in INACTIVE_STATUSES or user.deleted_at is not None:
            raise AppError(
                "ACCOUNT_INACTIVE",
                "This account is not available.",
                status_code=403,
            )

    async def update_profile(self, user: User, patch: dict[str, Any]) -> User:
        self.assert_active(user)
        if "handle" in patch and patch["handle"] is not None:
            user.handle = patch["handle"]
        if "display_name" in patch and patch["display_name"] is not None:
            user.display_name = patch["display_name"]
        if "bio" in patch:
            user.bio = patch["bio"]
        if "age_band" in patch:
            user.age_band = patch["age_band"]
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
            "show_social_links_after_accept",
            "analytics_opt_out",
        ):
            if field in patch and patch[field] is not None:
                setattr(privacy, field, patch[field])
        privacy.updated_at = datetime.now(UTC)
        user.updated_at = datetime.now(UTC)
        await self._repo.save()
        refreshed = await self._repo.get_by_id(user.id)
        assert refreshed is not None
        return refreshed

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

    async def revoke_device(self, user: User, device_id: uuid.UUID) -> None:
        self.assert_active(user)
        device = await self._repo.get_device_for_user(user_id=user.id, device_id=device_id)
        if device is None:
            raise AppError("DEVICE_NOT_FOUND", "Device not found.", status_code=404)
        if device.revoked_at is None:
            device.revoked_at = datetime.now(UTC)
            await self._repo.save()

    async def request_account_deletion(self, user: User) -> dict[str, str]:
        if user.account_status in {"deletion_requested", "deleted"}:
            return {"status": "already_requested"}
        user.account_status = "deletion_requested"
        user.deleted_at = datetime.now(UTC)
        user.updated_at = datetime.now(UTC)
        await self._repo.revoke_all_devices(user.id)
        await self._repo.save()
        return {"status": "scheduled"}
