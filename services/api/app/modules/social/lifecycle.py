"""The only place Calling Card statuses are written.

Routers and workers call through SocialService; status mutations go through
``CallingCardLifecycleService`` so an illegal transition is a 409 instead of a
silent overwrite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import CallingCard

CALLING_CARD_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "pending": frozenset({"accepted", "declined", "expired", "cancelled", "blocked"}),
    "accepted": frozenset({"blocked"}),
    "declined": frozenset(),
    "expired": frozenset(),
    "cancelled": frozenset(),
    "blocked": frozenset(),
}


class CallingCardStateError(AppError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            "CALLING_CARD_STATE_INVALID",
            message,
            status_code=409,
            details=details or {},
        )


def compute_calling_card_expiry(
    created_at: datetime,
    venue_timezone: str,
    settings: Settings,
) -> datetime:
    """TTL capped by the next venue-local 06:00 boundary."""
    try:
        zone = ZoneInfo(venue_timezone)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(settings.default_purge_timezone)
    local = created_at.astimezone(zone)
    boundary = local.replace(
        hour=settings.vibe_expiry_local_hour, minute=0, second=0, microsecond=0
    )
    if local >= boundary:
        boundary = boundary + timedelta(days=1)
    ttl_cap = created_at + timedelta(seconds=settings.calling_card_ttl_seconds)
    return min(boundary.astimezone(UTC), ttl_cap)


def next_venue_night_end(moment: datetime, venue_timezone: str, settings: Settings) -> datetime:
    """Next local 06:00 boundary for the venue, in UTC."""
    try:
        zone = ZoneInfo(venue_timezone)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(settings.default_purge_timezone)
    local = moment.astimezone(zone)
    boundary = local.replace(
        hour=settings.vibe_expiry_local_hour, minute=0, second=0, microsecond=0
    )
    if local >= boundary:
        boundary = boundary + timedelta(days=1)
    return boundary.astimezone(UTC)


def venue_night_id(moment: datetime, venue_timezone: str, settings: Settings) -> str:
    """Stable id for the venue-night ending at the next local 06:00."""
    return next_venue_night_end(moment, venue_timezone, settings).date().isoformat()


class CallingCardLifecycleService:
    @staticmethod
    def transition(
        card: CallingCard,
        target: str,
        *,
        now: datetime,
        response_action: str | None = None,
        cancelled_reason: str | None = None,
    ) -> None:
        allowed = CALLING_CARD_TRANSITIONS.get(card.status)
        if allowed is None:
            raise CallingCardStateError(
                f"Unknown calling card status {card.status!r}.",
                details={"calling_card_id": str(card.id)},
            )
        if target == card.status:
            return
        if target not in allowed:
            raise CallingCardStateError(
                f"Calling card cannot move from {card.status!r} to {target!r}.",
                details={
                    "calling_card_id": str(card.id),
                    "from": card.status,
                    "to": target,
                },
            )
        card.status = target
        if target in {"accepted", "declined"}:
            card.responded_at = now
            if response_action is not None:
                card.response_action = response_action
        if target in {"cancelled", "blocked", "expired"} and cancelled_reason is not None:
            card.cancelled_reason = cancelled_reason
        if target == "expired" and card.responded_at is None:
            card.responded_at = now
