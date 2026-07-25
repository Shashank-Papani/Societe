"""Signed derivative URLs.

Object keys are internal. A client receives a short-lived signed URL and nothing
else: leaking a key would otherwise let anyone who learns the naming scheme probe
the processed bucket, and keys are guessable by design (they embed the asset id).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from app.core.config import Settings
from app.db.models import MediaDerivative
from app.modules.media.schemas import MediaVariant
from app.modules.media.storage import ObjectStorage


async def build_signed_variants(
    storage: ObjectStorage,
    settings: Settings,
    derivatives: Sequence[MediaDerivative],
    *,
    now: datetime,
) -> list[MediaVariant]:
    ttl = settings.media_signed_url_ttl_seconds
    expires_at = now + timedelta(seconds=ttl)
    variants: list[MediaVariant] = []
    for derivative in derivatives:
        if derivative.status != "ready":
            continue
        url = await storage.presign_get(
            bucket=settings.media_processed_bucket,
            key=derivative.object_key,
            expires_in=ttl,
        )
        variants.append(
            MediaVariant(
                variant_type=derivative.variant_type,
                mime_type=derivative.mime_type,
                url=url,
                width=derivative.width,
                height=derivative.height,
                duration_ms=derivative.duration_ms,
                expires_at=expires_at,
            )
        )
    return variants
