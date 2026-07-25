"""Refresh session rotation with concurrency-safe grace replay (ADR 0019)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.security import mint_access_token
from app.db.models import AuthRefreshSession, User, UserDevice
from app.modules.identity.crypto_util import generate_refresh_token, hash_secret

logger = get_logger(__name__)


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in_minutes: int
    session_id: uuid.UUID
    device_id: uuid.UUID


class SessionService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis[str],
        settings: Settings,
    ) -> None:
        self._session = session
        self._redis = redis
        self._settings = settings

    def _grace_key(self, old_hash: str) -> str:
        return f"auth:refresh_grace:{old_hash}"

    async def create_session(
        self,
        *,
        user: User,
        device: UserDevice,
        now: datetime | None = None,
    ) -> TokenPair:
        if device.user_id != user.id:
            raise AppError(
                "DEVICE_OWNERSHIP_VIOLATION",
                "Device does not belong to this account.",
                status_code=403,
            )
        if device.revoked_at is not None:
            raise AppError(
                "DEVICE_REVOKED",
                "This device has been revoked.",
                status_code=403,
            )
        now = now or datetime.now(UTC)
        refresh = generate_refresh_token()
        token_hash = hash_secret(refresh, self._settings)
        family_id = uuid.uuid4()
        row = AuthRefreshSession(
            user_id=user.id,
            device_id=device.id,
            family_id=family_id,
            token_hash=token_hash,
            expires_at=now + timedelta(days=self._settings.refresh_token_days),
            last_used_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        access = mint_access_token(
            subject=user.auth_subject,
            handle=user.handle,
            settings=self._settings,
            extra_claims={"sid": str(row.id), "did": str(device.id)},
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in_minutes=self._settings.jwt_access_token_minutes,
            session_id=row.id,
            device_id=device.id,
        )

    async def refresh(self, *, refresh_token: str, now: datetime | None = None) -> TokenPair:
        now = now or datetime.now(UTC)
        token_hash = hash_secret(refresh_token, self._settings)

        result = await self._session.execute(
            select(AuthRefreshSession)
            .where(
                or_(
                    AuthRefreshSession.token_hash == token_hash,
                    AuthRefreshSession.previous_token_hash == token_hash,
                )
            )
            .with_for_update()
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise AppError("UNAUTHORIZED", "Invalid or expired refresh token.", status_code=401)

        # Concurrent loser within grace: previous hash match.
        if row.previous_token_hash == token_hash and row.token_hash != token_hash:
            if row.revoked_at is not None:
                raise AppError("UNAUTHORIZED", "Invalid or expired refresh token.", status_code=401)
            if row.rotated_at is None:
                raise AppError("UNAUTHORIZED", "Invalid or expired refresh token.", status_code=401)
            age = (now - row.rotated_at).total_seconds()
            if age <= self._settings.refresh_rotation_grace_seconds:
                cached = await self._redis.get(self._grace_key(token_hash))
                if cached:
                    data = json.loads(cached)
                    return TokenPair(
                        access_token=data["access_token"],
                        refresh_token=data["refresh_token"],
                        expires_in_minutes=int(data["expires_in_minutes"]),
                        session_id=uuid.UUID(data["session_id"]),
                        device_id=uuid.UUID(data["device_id"]),
                    )
                # Grace window but cache miss: mint access against current session
                # without rotating again (refresh token already advanced).
                user = await self._session.get(User, row.user_id)
                if user is None:
                    raise AppError(
                        "UNAUTHORIZED", "Invalid or expired refresh token.", status_code=401
                    )
                access = mint_access_token(
                    subject=user.auth_subject,
                    handle=user.handle,
                    settings=self._settings,
                    extra_claims={"sid": str(row.id), "did": str(row.device_id)},
                )
                raise AppError(
                    "REFRESH_RETRY",
                    "Refresh is already in progress; retry with the newest refresh token.",
                    status_code=409,
                    details={"access_token": access},
                )
            # Outside grace → treat as theft / replay.
            await self._revoke_family(row.family_id, now=now, reason="refresh_reuse_outside_grace")
            await self._session.flush()
            logger.warning("refresh_family_revoked", reason="refresh_reuse_outside_grace")
            raise AppError("UNAUTHORIZED", "Invalid or expired refresh token.", status_code=401)

        if row.revoked_at is not None or row.expires_at <= now:
            raise AppError("UNAUTHORIZED", "Invalid or expired refresh token.", status_code=401)

        device = await self._session.get(UserDevice, row.device_id)
        user = await self._session.get(User, row.user_id)
        if user is None or device is None or device.user_id != user.id:
            raise AppError("UNAUTHORIZED", "Invalid or expired refresh token.", status_code=401)
        if device.revoked_at is not None:
            row.revoked_at = now
            row.revoke_reason = "device_revoked"
            await self._session.flush()
            raise AppError("UNAUTHORIZED", "Invalid or expired refresh token.", status_code=401)
        if user.account_status in {"deletion_requested", "deleted", "suspended"}:
            raise AppError("ACCOUNT_INACTIVE", "This account is not available.", status_code=403)

        old_hash = row.token_hash
        new_refresh = generate_refresh_token()
        new_hash = hash_secret(new_refresh, self._settings)
        row.previous_token_hash = old_hash
        row.token_hash = new_hash
        row.rotated_at = now
        row.last_used_at = now
        row.expires_at = now + timedelta(days=self._settings.refresh_token_days)
        await self._session.flush()

        access = mint_access_token(
            subject=user.auth_subject,
            handle=user.handle,
            settings=self._settings,
            extra_claims={"sid": str(row.id), "did": str(device.id)},
        )
        pair = TokenPair(
            access_token=access,
            refresh_token=new_refresh,
            expires_in_minutes=self._settings.jwt_access_token_minutes,
            session_id=row.id,
            device_id=device.id,
        )
        payload: dict[str, Any] = {
            "access_token": pair.access_token,
            "refresh_token": pair.refresh_token,
            "expires_in_minutes": pair.expires_in_minutes,
            "session_id": str(pair.session_id),
            "device_id": str(pair.device_id),
        }
        await self._redis.set(
            self._grace_key(old_hash),
            json.dumps(payload),
            ex=self._settings.refresh_rotation_grace_seconds,
        )
        return pair

    async def revoke_session(
        self,
        *,
        session_id: uuid.UUID | None = None,
        refresh_token: str | None = None,
        user_id: uuid.UUID | None = None,
        reason: str = "logout",
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        row: AuthRefreshSession | None = None
        if refresh_token is not None:
            token_hash = hash_secret(refresh_token, self._settings)
            result = await self._session.execute(
                select(AuthRefreshSession).where(AuthRefreshSession.token_hash == token_hash)
            )
            row = result.scalar_one_or_none()
        elif session_id is not None:
            row = await self._session.get(AuthRefreshSession, session_id)
        if row is None:
            return
        if user_id is not None and row.user_id != user_id:
            raise AppError("FORBIDDEN", "Cannot revoke another user's session.", status_code=403)
        if row.revoked_at is None:
            row.revoked_at = now
            row.revoke_reason = reason

    async def revoke_all_for_user(
        self,
        user_id: uuid.UUID,
        *,
        except_session_id: uuid.UUID | None = None,
        reason: str = "logout_all",
        now: datetime | None = None,
    ) -> int:
        now = now or datetime.now(UTC)
        stmt = (
            update(AuthRefreshSession)
            .where(
                AuthRefreshSession.user_id == user_id,
                AuthRefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoke_reason=reason)
        )
        if except_session_id is not None:
            stmt = stmt.where(AuthRefreshSession.id != except_session_id)
        result = await self._session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    async def revoke_device_sessions(
        self,
        *,
        user_id: uuid.UUID,
        device_id: uuid.UUID,
        reason: str = "device_revoked",
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        await self._session.execute(
            update(AuthRefreshSession)
            .where(
                AuthRefreshSession.user_id == user_id,
                AuthRefreshSession.device_id == device_id,
                AuthRefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoke_reason=reason)
        )

    async def _revoke_family(self, family_id: uuid.UUID, *, now: datetime, reason: str) -> None:
        await self._session.execute(
            update(AuthRefreshSession)
            .where(
                AuthRefreshSession.family_id == family_id,
                AuthRefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoke_reason=reason)
        )
