"""Validated internal deep-link helpers (no external URLs)."""

from __future__ import annotations

from uuid import UUID

from app.core.errors import AppError

ALLOWED_PREFIXES = (
    "societe://conversation/",
    "societe://calling-card/",
    "societe://story/",
    "societe://experience",
    "societe://venue-claim/",
    "societe://organization-invitation/",
)


def conversation_link(conversation_id: UUID) -> str:
    return f"societe://conversation/{conversation_id}"


def calling_card_link(calling_card_id: UUID) -> str:
    return f"societe://calling-card/{calling_card_id}"


def story_link(story_id: UUID) -> str:
    return f"societe://story/{story_id}"


def experience_link() -> str:
    return "societe://experience"


def venue_claim_link(claim_id: UUID) -> str:
    return f"societe://venue-claim/{claim_id}"


def organization_invitation_link(invitation_id: UUID) -> str:
    return f"societe://organization-invitation/{invitation_id}"


def assert_internal_deep_link(value: str | None) -> str | None:
    if value is None:
        return None
    if not any(value.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        raise AppError(
            "NOTIFICATION_FORBIDDEN",
            "Deep link must be an internal Société destination.",
            status_code=400,
        )
    if "://" in value[value.find("://") + 3 :] and not value.startswith("societe://"):
        raise AppError(
            "NOTIFICATION_FORBIDDEN",
            "External deep links are not allowed.",
            status_code=400,
        )
    return value
