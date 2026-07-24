from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserDevice, UserPrivacySettings


def generate_temporary_handle() -> str:
    """Random non-identifying handle. Not derived from email/phone/subject/device."""
    return f"guest_{secrets.token_hex(4)}"


class IdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_auth_subject(self, auth_subject: str) -> User | None:
        result = await self._session.execute(select(User).where(User.auth_subject == auth_subject))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create_user(self, *, auth_subject: str) -> User:
        last_error: Exception | None = None
        for _ in range(8):
            handle = generate_temporary_handle()
            try:
                async with self._session.begin_nested():
                    user = User(
                        auth_subject=auth_subject,
                        handle=handle,
                        display_name="New Guest",
                        account_status="active",
                    )
                    privacy = UserPrivacySettings(user=user)
                    self._session.add(user)
                    self._session.add(privacy)
                    await self._session.flush()
                    return user
            except IntegrityError as exc:
                last_error = exc
                continue
        raise RuntimeError(f"Unable to allocate unique handle: {last_error}")

    async def save(self) -> None:
        await self._session.commit()

    async def get_device_by_platform_installation(
        self, *, platform: str, installation_id: uuid.UUID
    ) -> UserDevice | None:
        result = await self._session.execute(
            select(UserDevice).where(
                UserDevice.platform == platform,
                UserDevice.installation_id == installation_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_device_for_user(
        self, *, user_id: uuid.UUID, device_id: uuid.UUID
    ) -> UserDevice | None:
        result = await self._session.execute(
            select(UserDevice).where(
                UserDevice.id == device_id,
                UserDevice.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def revoke_all_devices(self, user_id: uuid.UUID) -> None:
        now = datetime.now(UTC)
        result = await self._session.execute(
            select(UserDevice).where(
                UserDevice.user_id == user_id,
                UserDevice.revoked_at.is_(None),
            )
        )
        for device in result.scalars().all():
            device.revoked_at = now
