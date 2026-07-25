"""Optional profile photo upload (ADR 0023). Does not block onboarding."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import ProfileMediaAsset, User, UserDevice
from app.modules.media.processors import _strip_metadata
from app.modules.media.storage import build_object_storage


@dataclass(frozen=True)
class _ProcessedProfile:
    object_key: str
    mime_type: str
    byte_size: int
    width: int
    height: int
    checksum_sha256: str


class ProfileMediaService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._storage = build_object_storage(settings)

    async def create_upload(
        self,
        *,
        user: User,
        device_id: uuid.UUID,
        mime_type: str,
        byte_size: int,
    ) -> dict[str, Any]:
        if user.account_status != "active":
            raise AppError("ACCOUNT_INACTIVE", "This account is not available.", status_code=403)
        if mime_type not in self._settings.media_allowed_image_mime_types:
            raise AppError("MEDIA_TYPE_UNSUPPORTED", "Unsupported image type.", status_code=415)
        if byte_size > self._settings.profile_photo_max_bytes:
            raise AppError("MEDIA_TOO_LARGE", "Profile photo is too large.", status_code=413)

        device = await self._session.get(UserDevice, device_id)
        if device is None or device.user_id != user.id or device.revoked_at is not None:
            raise AppError("DEVICE_NOT_FOUND", "Device not found.", status_code=404)

        now = datetime.now(UTC)
        asset_id = uuid.uuid4()
        key = f"profile/{user.id}/{asset_id}/original"
        asset = ProfileMediaAsset(
            id=asset_id,
            owner_user_id=user.id,
            device_id=device.id,
            quarantine_object_key=key,
            declared_mime_type=mime_type,
            declared_byte_size=byte_size,
            intent_expires_at=now
            + timedelta(seconds=self._settings.media_upload_intent_ttl_seconds),
        )
        self._session.add(asset)
        await self._session.flush()
        signed = await self._storage.presign_put(
            bucket=self._settings.media_quarantine_bucket,
            key=key,
            content_type=mime_type,
            expires_in=self._settings.media_presigned_put_ttl_seconds,
        )
        return {
            "upload_id": str(asset.id),
            "upload_url": signed.url,
            "headers": signed.headers,
            "expires_at": asset.intent_expires_at.isoformat(),
            "moderation_status": asset.moderation_status,
        }

    async def complete_upload(self, *, user: User, upload_id: uuid.UUID) -> dict[str, Any]:
        asset = await self._session.get(ProfileMediaAsset, upload_id)
        if asset is None or asset.owner_user_id != user.id:
            raise AppError("UPLOAD_NOT_FOUND", "Upload not found.", status_code=404)
        if asset.intent_consumed_at is not None:
            return {
                "upload_id": str(asset.id),
                "moderation_status": asset.moderation_status,
                "lifecycle_status": asset.lifecycle_status,
                "published": user.profile_photo_media_id == asset.id,
            }
        now = datetime.now(UTC)
        if asset.intent_expires_at <= now:
            raise AppError("UPLOAD_EXPIRED", "Upload intent expired.", status_code=410)

        stat = await self._storage.stat_object(
            bucket=self._settings.media_quarantine_bucket,
            key=asset.quarantine_object_key,
        )
        if stat is None:
            raise AppError("UPLOAD_MISSING", "Upload object was not found.", status_code=400)

        try:
            processed = await self._process(asset)
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            asset.lifecycle_status = "rejected"
            asset.moderation_status = "rejected"
            asset.intent_consumed_at = now
            await self._session.flush()
            raise AppError(
                "MEDIA_REJECTED",
                "Profile photo could not be processed.",
                status_code=400,
            ) from exc

        asset.detected_mime_type = processed.mime_type
        asset.byte_size = processed.byte_size
        asset.width = processed.width
        asset.height = processed.height
        asset.checksum_sha256 = processed.checksum_sha256
        asset.processed_object_key = processed.object_key
        asset.lifecycle_status = "ready"
        asset.moderation_status = "approved"
        asset.uploaded_at = now
        asset.processed_at = now
        asset.intent_consumed_at = now
        user.profile_photo_media_id = asset.id
        user.updated_at = now
        await self._session.flush()
        return {
            "upload_id": str(asset.id),
            "moderation_status": asset.moderation_status,
            "lifecycle_status": asset.lifecycle_status,
            "published": True,
        }

    async def _process(self, asset: ProfileMediaAsset) -> _ProcessedProfile:
        with tempfile.TemporaryDirectory(prefix="societe-profile-") as tmp:
            work = Path(tmp)
            source = work / "original"
            await self._storage.download_to_path(
                bucket=self._settings.media_quarantine_bucket,
                key=asset.quarantine_object_key,
                destination=source,
            )
            if source.stat().st_size > self._settings.profile_photo_max_bytes:
                raise ValueError("too_large")
            with Image.open(source) as opened:
                opened.load()
                oriented = ImageOps.exif_transpose(opened) or opened
                sanitized = _strip_metadata(oriented)
                out = work / "profile.webp"
                sanitized.save(out, format="WEBP", quality=85, method=4)
                width, height = sanitized.size
                sanitized.close()
            digest = hashlib.sha256(out.read_bytes()).hexdigest()
            key = f"profile/{asset.owner_user_id}/{asset.id}/profile.webp"
            await self._storage.upload_path(
                bucket=self._settings.media_processed_bucket,
                key=key,
                source=out,
                content_type="image/webp",
            )
            return _ProcessedProfile(
                object_key=key,
                mime_type="image/webp",
                byte_size=out.stat().st_size,
                width=width,
                height=height,
                checksum_sha256=digest,
            )
