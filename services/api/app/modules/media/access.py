"""Signed derivative URL issuance rules.

A previously issued URL may keep working until its short TTL expires — that is a
bounded revocation window, not a bug. This module decides whether to mint a
*new* URL. Raw uploads, invalid/rejected assets, deleted/revoked content, and
publicly expired vibes outside the creator retention window never get one.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.config import Settings
from app.db.models import LiveVibe, MediaAsset, OfficialVenuePost, Story
from app.modules.stories.lifecycle import is_official_post_public, is_publicly_viewable

#: Statuses that must never receive a new signed URL.
_BLOCKED_ASSET = frozenset(
    {
        "intent_pending",
        "uploaded",
        "validating",
        "processing",
        "moderation_pending",
        "upload_expired",
        "invalid",
        "processing_failed",
        "rejected",
        "manual_review",
        "deleted",
        "revoked",
    }
)
_BLOCKED_VIBE = frozenset(
    {"draft", "processing", "hidden", "removed", "rejected", "deleted", "revoked"}
)


def may_issue_signed_urls(
    asset: MediaAsset,
    vibe: LiveVibe | None,
    *,
    now: datetime,
    settings: Settings,
    creator_view: bool = False,
) -> bool:
    """Return True only when a client may receive fresh derivative URLs."""
    if asset.lifecycle_status != "ready":
        return False
    if asset.lifecycle_status in _BLOCKED_ASSET:
        return False
    if asset.moderation_status != "approved":
        return False
    if asset.deleted_at is not None:
        return False
    if vibe is None:
        return False
    if vibe.publication_status in _BLOCKED_VIBE:
        return False

    if vibe.publication_status == "published":
        if vibe.expires_at is None or vibe.expires_at <= now:
            # Treat a published row past expiry as expired for URL purposes.
            return (
                _creator_retention_allows(vibe, now=now, settings=settings)
                if creator_view
                else False
            )
        return True

    if vibe.publication_status == "expired":
        return creator_view and _creator_retention_allows(vibe, now=now, settings=settings)

    return False


def may_issue_content_signed_urls(
    asset: MediaAsset,
    *,
    story: Story | None,
    post: OfficialVenuePost | None,
    now: datetime,
    settings: Settings,
) -> bool:
    """Signed URLs for Story / official-post media (no LiveVibe required)."""
    _ = settings
    if asset.lifecycle_status != "ready":
        return False
    if asset.moderation_status != "approved":
        return False
    if asset.deleted_at is not None:
        return False
    if story is not None:
        return is_publicly_viewable(story, now=now)
    if post is not None:
        return is_official_post_public(post)
    return False


def _creator_retention_allows(vibe: LiveVibe, *, now: datetime, settings: Settings) -> bool:
    if vibe.expires_at is None:
        return False
    retention_end = vibe.expires_at + timedelta(days=settings.retention_processed_derivative_days)
    return now < retention_end
