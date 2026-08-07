"""Notification types, categories, and mapping helpers."""

from __future__ import annotations

from typing import Final

NOTIFICATION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "calling_card.received",
        "calling_card.accepted",
        "message.received",
        "story.published",
        "story.rejected",
        "story.failed",
        "venue_claim.approved",
        "venue_claim.rejected",
        "organization.invitation.received",
        "system.account_notice",
    }
)

NOTIFICATION_CATEGORIES: Final[tuple[str, ...]] = (
    "messages",
    "calling_cards",
    "stories",
    "venue_management",
    "account",
)

CATEGORY_DEFAULTS: Final[dict[str, dict[str, bool]]] = {
    "messages": {"in_app_enabled": True, "push_enabled": True},
    "calling_cards": {"in_app_enabled": True, "push_enabled": True},
    "stories": {"in_app_enabled": True, "push_enabled": True},
    "venue_management": {"in_app_enabled": True, "push_enabled": True},
    "account": {"in_app_enabled": True, "push_enabled": True},
}

# Account in-app cannot be disabled.
MANDATORY_IN_APP_CATEGORIES: Final[frozenset[str]] = frozenset({"account"})

TYPE_TO_CATEGORY: Final[dict[str, str]] = {
    "calling_card.received": "calling_cards",
    "calling_card.accepted": "calling_cards",
    "message.received": "messages",
    "story.published": "stories",
    "story.rejected": "stories",
    "story.failed": "stories",
    "venue_claim.approved": "venue_management",
    "venue_claim.rejected": "venue_management",
    "organization.invitation.received": "venue_management",
    "system.account_notice": "account",
}

SOURCE_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "calling_card.created",
        "calling_card.accepted",
        "message.created",
        "story.published",
        "story.rejected",
        "story.failed",
        "venue.claim.approved",
        "venue.claim.rejected",
        "organization.invitation.created",
    }
)


def category_for_type(notification_type: str) -> str:
    return TYPE_TO_CATEGORY[notification_type]
