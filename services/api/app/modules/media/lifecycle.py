"""The only place media and Live Vibe statuses are written.

Routers and workers call these services. Nothing else assigns
``lifecycle_status`` or ``publication_status``, because "publish" spread across a
router, a worker, and a retry path is how unmoderated media becomes public: one
of those call sites eventually forgets a precondition.

Every transition is declared, so an illegal one is a 409 instead of a silent
overwrite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import LiveVibe, MediaAsset

MEDIA_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "intent_pending": frozenset({"uploaded", "upload_expired", "deleted"}),
    "uploaded": frozenset({"validating", "invalid", "processing_failed", "deleted", "revoked"}),
    "validating": frozenset(
        {
            "processing",
            "invalid",
            "rejected",
            "manual_review",
            "processing_failed",
            "deleted",
            "revoked",
        }
    ),
    "processing": frozenset(
        {"moderation_pending", "invalid", "processing_failed", "deleted", "revoked"}
    ),
    "moderation_pending": frozenset(
        {"ready", "rejected", "manual_review", "processing_failed", "deleted", "revoked"}
    ),
    "ready": frozenset({"rejected", "manual_review", "deleted", "revoked"}),
    "manual_review": frozenset({"ready", "rejected", "deleted", "revoked"}),
    # A retry re-runs validation from the quarantined original.
    "processing_failed": frozenset({"validating", "deleted", "revoked"}),
    "invalid": frozenset({"deleted"}),
    "rejected": frozenset({"deleted", "revoked"}),
    "upload_expired": frozenset({"deleted"}),
    "revoked": frozenset({"deleted"}),
    "deleted": frozenset(),
}

VIBE_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "draft": frozenset({"processing", "expired", "rejected", "deleted"}),
    "processing": frozenset({"published", "rejected", "hidden", "expired", "deleted", "revoked"}),
    "published": frozenset({"expired", "hidden", "removed", "rejected", "deleted", "revoked"}),
    "hidden": frozenset({"published", "removed", "rejected", "expired", "deleted", "revoked"}),
    "expired": frozenset({"removed", "deleted"}),
    "rejected": frozenset({"deleted"}),
    "removed": frozenset({"deleted"}),
    "revoked": frozenset({"deleted"}),
    "deleted": frozenset(),
}

#: Statuses that are safe to serve in the public venue feed.
PUBLIC_VIBE_STATUSES: Final[frozenset[str]] = frozenset({"published"})

#: Lifecycle statuses whose derivatives may be served.
SERVABLE_MEDIA_STATUSES: Final[frozenset[str]] = frozenset({"ready"})


class MediaStateError(AppError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__("MEDIA_STATE_INVALID", message, status_code=409, details=details or {})


def compute_vibe_expiry(
    published_at: datetime,
    venue_timezone: str,
    settings: Settings,
) -> datetime:
    """Public window: next local closing hour, capped by an absolute maximum.

    Computed at publication, never at intent creation: a clip that spends twenty
    minutes in moderation should still get its full window, and a clip published
    at 05:59 should still disappear at 06:00 local.
    """
    try:
        zone = ZoneInfo(venue_timezone)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(settings.default_purge_timezone)
    local = published_at.astimezone(zone)
    boundary = local.replace(
        hour=settings.vibe_expiry_local_hour, minute=0, second=0, microsecond=0
    )
    if local >= boundary:
        boundary = boundary + timedelta(days=1)
    cap = published_at + timedelta(hours=settings.vibe_absolute_max_lifetime_hours)
    return min(boundary.astimezone(UTC), cap)


class MediaLifecycleService:
    """Guarded transitions for ``app.media_assets``."""

    @staticmethod
    def _apply(asset: MediaAsset, target: str) -> None:
        allowed = MEDIA_TRANSITIONS.get(asset.lifecycle_status)
        if allowed is None:
            raise MediaStateError(
                f"Unknown media lifecycle status {asset.lifecycle_status!r}.",
                details={"media_asset_id": str(asset.id)},
            )
        if target == asset.lifecycle_status:
            return
        if target not in allowed:
            raise MediaStateError(
                f"Media cannot move from {asset.lifecycle_status!r} to {target!r}.",
                details={
                    "media_asset_id": str(asset.id),
                    "from": asset.lifecycle_status,
                    "to": target,
                },
            )
        asset.lifecycle_status = target

    @staticmethod
    def _merge_summary(asset: MediaAsset, extra: dict[str, Any]) -> None:
        # Reassign instead of mutating: SQLAlchemy does not track in-place JSONB
        # edits without a mutable type.
        summary = dict(asset.moderation_summary or {})
        summary.update(extra)
        asset.moderation_summary = summary

    def mark_uploaded(self, asset: MediaAsset, *, now: datetime) -> None:
        self._apply(asset, "uploaded")
        asset.uploaded_at = now
        asset.intent_consumed_at = now

    def mark_intent_expired(self, asset: MediaAsset, *, now: datetime) -> None:
        self._apply(asset, "upload_expired")
        self._merge_summary(asset, {"expired_at": now.isoformat()})

    def start_validation(self, asset: MediaAsset, *, now: datetime) -> None:
        self._apply(asset, "validating")
        self._merge_summary(asset, {"validation_started_at": now.isoformat()})

    def start_processing(self, asset: MediaAsset, *, now: datetime) -> None:
        self._apply(asset, "processing")
        self._merge_summary(asset, {"processing_started_at": now.isoformat()})

    def record_probe(
        self,
        asset: MediaAsset,
        *,
        detected_mime_type: str,
        byte_size: int,
        checksum_sha256: str,
        width: int | None = None,
        height: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        asset.detected_mime_type = detected_mime_type
        asset.byte_size = byte_size
        asset.checksum_sha256 = checksum_sha256
        asset.width = width
        asset.height = height
        asset.duration_ms = duration_ms

    def mark_invalid(self, asset: MediaAsset, *, now: datetime, reason: str) -> None:
        self._apply(asset, "invalid")
        self._merge_summary(asset, {"invalid_reason": reason, "invalid_at": now.isoformat()})

    def await_moderation(self, asset: MediaAsset, *, now: datetime) -> None:
        self._apply(asset, "moderation_pending")
        asset.processed_at = now

    def mark_ready(self, asset: MediaAsset, *, now: datetime, summary: dict[str, Any]) -> None:
        self._apply(asset, "ready")
        asset.moderation_status = "approved"
        self._merge_summary(asset, {**summary, "approved_at": now.isoformat()})

    def mark_rejected(self, asset: MediaAsset, *, now: datetime, summary: dict[str, Any]) -> None:
        self._apply(asset, "rejected")
        asset.moderation_status = "rejected"
        self._merge_summary(asset, {**summary, "rejected_at": now.isoformat()})

    def mark_manual_review(
        self, asset: MediaAsset, *, now: datetime, summary: dict[str, Any]
    ) -> None:
        self._apply(asset, "manual_review")
        asset.moderation_status = "manual_review"
        self._merge_summary(asset, {**summary, "manual_review_at": now.isoformat()})

    def mark_quarantined(
        self, asset: MediaAsset, *, now: datetime, summary: dict[str, Any]
    ) -> None:
        """Malware hit or a scanner we cannot trust. Never publishable."""
        self._apply(asset, "manual_review")
        asset.moderation_status = "quarantined"
        self._merge_summary(asset, {**summary, "quarantined_at": now.isoformat()})

    def mark_processing_failed(
        self, asset: MediaAsset, *, now: datetime, error_category: str
    ) -> None:
        self._apply(asset, "processing_failed")
        self._merge_summary(asset, {"error_category": error_category, "failed_at": now.isoformat()})

    def record_original_purged(self, asset: MediaAsset, *, now: datetime) -> None:
        """Note that the quarantined original is gone but derivatives may live on."""
        self._merge_summary(asset, {"original_purged_at": now.isoformat()})

    def mark_deleted(self, asset: MediaAsset, *, now: datetime, reason: str) -> None:
        self._apply(asset, "deleted")
        asset.deleted_at = now
        asset.deleted_reason = reason

    def mark_revoked(self, asset: MediaAsset, *, now: datetime, reason: str) -> None:
        self._apply(asset, "revoked")
        asset.deleted_reason = reason
        self._merge_summary(asset, {"revoked_at": now.isoformat()})


class VibeLifecycleService:
    """Guarded transitions for ``app.live_vibes``."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @staticmethod
    def _apply(vibe: LiveVibe, target: str) -> None:
        allowed = VIBE_TRANSITIONS.get(vibe.publication_status)
        if allowed is None:
            raise MediaStateError(
                f"Unknown vibe publication status {vibe.publication_status!r}.",
                details={"live_vibe_id": str(vibe.id)},
            )
        if target == vibe.publication_status:
            return
        if target not in allowed:
            raise MediaStateError(
                f"Live Vibe cannot move from {vibe.publication_status!r} to {target!r}.",
                details={
                    "live_vibe_id": str(vibe.id),
                    "from": vibe.publication_status,
                    "to": target,
                },
            )
        vibe.publication_status = target

    def start_processing(self, vibe: LiveVibe) -> None:
        self._apply(vibe, "processing")

    def publish(self, vibe: LiveVibe, *, now: datetime, venue_timezone: str) -> datetime:
        """Publish and stamp the expiry window. Returns ``expires_at``."""
        self._apply(vibe, "published")
        vibe.published_at = now
        vibe.hidden_at = None
        vibe.hidden_reason = None
        vibe.expires_at = compute_vibe_expiry(now, venue_timezone, self._settings)
        return vibe.expires_at

    def expire(self, vibe: LiveVibe, *, now: datetime) -> None:
        self._apply(vibe, "expired")
        if vibe.expires_at is None:
            vibe.expires_at = now

    def hide(self, vibe: LiveVibe, *, now: datetime, reason: str) -> None:
        self._apply(vibe, "hidden")
        vibe.hidden_at = now
        vibe.hidden_reason = reason

    def unhide(self, vibe: LiveVibe, *, now: datetime) -> None:
        self._apply(vibe, "published")
        vibe.hidden_at = None
        vibe.hidden_reason = None
        if vibe.published_at is None:
            vibe.published_at = now

    def reject(self, vibe: LiveVibe, *, now: datetime, reason: str) -> None:
        self._apply(vibe, "rejected")
        vibe.hidden_at = now
        vibe.hidden_reason = reason

    def remove(self, vibe: LiveVibe, *, now: datetime, reason: str) -> None:
        self._apply(vibe, "removed")
        vibe.hidden_at = now
        vibe.hidden_reason = reason

    def delete(self, vibe: LiveVibe, *, now: datetime, reason: str) -> None:
        self._apply(vibe, "deleted")
        vibe.hidden_at = now
        vibe.hidden_reason = reason

    def revoke(self, vibe: LiveVibe, *, now: datetime, reason: str) -> None:
        self._apply(vibe, "revoked")
        vibe.hidden_at = now
        vibe.hidden_reason = reason
