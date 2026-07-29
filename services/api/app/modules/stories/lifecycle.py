"""Guarded Story and OfficialVenuePost publication transitions.

Routers and the media pipeline call these helpers. Status fields are not
assigned ad hoc elsewhere — illegal transitions raise 409.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final

from app.core.errors import AppError
from app.db.models import OfficialVenuePost, Story

STORY_PUBLIC_WINDOW: Final[timedelta] = timedelta(hours=24)

STORY_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "draft": frozenset({"processing", "uploaded", "published", "rejected", "failed", "deleted"}),
    "uploaded": frozenset({"processing", "rejected", "failed", "deleted"}),
    "processing": frozenset(
        {"moderation_pending", "published", "rejected", "failed", "hidden", "deleted"}
    ),
    "moderation_pending": frozenset({"published", "rejected", "failed", "hidden", "deleted"}),
    "published": frozenset({"expired", "hidden", "rejected", "deleted"}),
    "hidden": frozenset({"published", "expired", "rejected", "deleted"}),
    "expired": frozenset({"deleted"}),
    "rejected": frozenset({"deleted"}),
    "failed": frozenset({"deleted"}),
    "deleted": frozenset(),
}

POST_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "draft": frozenset(
        {"processing", "moderation_pending", "published", "rejected", "failed", "deleted"}
    ),
    "processing": frozenset({"moderation_pending", "published", "rejected", "failed", "deleted"}),
    "moderation_pending": frozenset({"published", "rejected", "failed", "deleted"}),
    "published": frozenset({"archived", "rejected", "deleted"}),
    "archived": frozenset({"deleted"}),
    "rejected": frozenset({"deleted"}),
    "failed": frozenset({"deleted"}),
    "deleted": frozenset(),
}


class StoryStateError(AppError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__("STORY_STATE_INVALID", message, status_code=409, details=details or {})


class OfficialPostStateError(AppError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            "OFFICIAL_POST_STATE_INVALID", message, status_code=409, details=details or {}
        )


def _apply_story(story: Story, target: str) -> None:
    allowed = STORY_TRANSITIONS.get(story.publication_status)
    if allowed is None:
        raise StoryStateError(
            f"Unknown story publication status {story.publication_status!r}.",
            details={"story_id": str(story.id)},
        )
    if target == story.publication_status:
        return
    if target not in allowed:
        raise StoryStateError(
            f"Story cannot move from {story.publication_status!r} to {target!r}.",
            details={
                "story_id": str(story.id),
                "from": story.publication_status,
                "to": target,
            },
        )
    story.publication_status = target


def _apply_post(post: OfficialVenuePost, target: str) -> None:
    allowed = POST_TRANSITIONS.get(post.publication_status)
    if allowed is None:
        raise OfficialPostStateError(
            f"Unknown official post publication status {post.publication_status!r}.",
            details={"post_id": str(post.id)},
        )
    if target == post.publication_status:
        return
    if target not in allowed:
        raise OfficialPostStateError(
            f"Official post cannot move from {post.publication_status!r} to {target!r}.",
            details={
                "post_id": str(post.id),
                "from": post.publication_status,
                "to": target,
            },
        )
    post.publication_status = target


def publish_story(story: Story, *, now: datetime, ttl: timedelta = STORY_PUBLIC_WINDOW) -> datetime:
    """Publish and stamp the 24h public window. Returns ``expires_at``."""
    _apply_story(story, "published")
    story.published_at = now
    story.expires_at = now + ttl
    story.moderation_status = "approved"
    story.updated_at = now
    return story.expires_at


def start_processing(story: Story, *, now: datetime) -> None:
    _apply_story(story, "processing")
    story.updated_at = now


def expire_story(story: Story, *, now: datetime) -> None:
    _apply_story(story, "expired")
    if story.expires_at is None:
        story.expires_at = now
    story.updated_at = now


def mark_deleted(story: Story, *, now: datetime) -> None:
    _apply_story(story, "deleted")
    story.deleted_at = now
    story.updated_at = now


def mark_rejected(story: Story, *, now: datetime) -> None:
    _apply_story(story, "rejected")
    story.moderation_status = "rejected"
    story.updated_at = now


def is_publicly_viewable(story: Story, *, now: datetime) -> bool:
    return (
        story.publication_status == "published"
        and story.deleted_at is None
        and story.expires_at is not None
        and story.expires_at > now
    )


def publish_official_post(post: OfficialVenuePost, *, now: datetime) -> None:
    _apply_post(post, "published")
    post.published_at = now
    post.moderation_status = "approved"
    post.updated_at = now


def start_official_post_processing(post: OfficialVenuePost, *, now: datetime) -> None:
    _apply_post(post, "processing")
    post.updated_at = now


def archive_official_post(post: OfficialVenuePost, *, now: datetime) -> None:
    _apply_post(post, "archived")
    post.archived_at = now
    post.updated_at = now


def delete_official_post(post: OfficialVenuePost, *, now: datetime) -> None:
    _apply_post(post, "deleted")
    post.deleted_at = now
    post.updated_at = now


def reject_official_post(post: OfficialVenuePost, *, now: datetime) -> None:
    _apply_post(post, "rejected")
    post.moderation_status = "rejected"
    post.updated_at = now


def is_official_post_public(post: OfficialVenuePost) -> bool:
    return (
        post.publication_status == "published"
        and post.deleted_at is None
        and post.archived_at is None
    )
