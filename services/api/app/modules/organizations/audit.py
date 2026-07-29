"""Append-only venue/organization audit events.

Never store invitation plaintext tokens or claim evidence blobs.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import VenueAuditEvent

# Stable event type constants.
ORGANIZATION_CREATED = "organization.created"
MEMBERSHIP_INVITED = "membership.invited"
MEMBERSHIP_ACCEPTED = "membership.accepted"
MEMBERSHIP_ROLE_CHANGED = "membership.role_changed"
MEMBERSHIP_REMOVED = "membership.removed"
VENUE_CLAIM_SUBMITTED = "venue.claim_submitted"
VENUE_CLAIM_APPROVED = "venue.claim_approved"
VENUE_CLAIM_REJECTED = "venue.claim_rejected"
VENUE_LINKED = "venue.linked"
VENUE_COVER_SELECTED = "venue.cover_selected"
VENUE_COVER_REMOVED = "venue.cover_removed"
OFFICIAL_STORY_CREATED = "official_story.created"
OFFICIAL_STORY_PUBLISHED = "official_story.published"
OFFICIAL_STORY_DELETED = "official_story.deleted"
OFFICIAL_POST_CREATED = "official_post.created"
OFFICIAL_POST_PUBLISHED = "official_post.published"
OFFICIAL_POST_ARCHIVED = "official_post.archived"
OFFICIAL_POST_DELETED = "official_post.deleted"

_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "token",
        "plaintext_token",
        "invitation_token",
        "evidence",
        "evidence_reference",
        "business_evidence",
        "object_key",
        "quarantine_object_key",
    }
)


def sanitize_audit_metadata(metadata: dict[str, Any] | None) -> dict[str, object]:
    if not metadata:
        return {}
    cleaned: dict[str, object] = {}
    for key, value in metadata.items():
        if key in _FORBIDDEN_METADATA_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            cleaned[key] = value
        elif isinstance(value, UUID):
            cleaned[key] = str(value)
        else:
            cleaned[key] = str(value)
    return cleaned


async def append_audit_event(
    session: AsyncSession,
    *,
    event_type: str,
    actor_user_id: UUID | None = None,
    organization_id: UUID | None = None,
    venue_id: UUID | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> VenueAuditEvent:
    event = VenueAuditEvent(
        organization_id=organization_id,
        venue_id=venue_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        metadata_json=sanitize_audit_metadata(metadata),
    )
    session.add(event)
    await session.flush()
    return event
