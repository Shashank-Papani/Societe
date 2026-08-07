"""HTTP schemas for notifications (extra=forbid)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.notifications.constants import NOTIFICATION_CATEGORIES


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotificationActorProjection(StrictModel):
    id: UUID | None = None
    handle: str | None = None
    display_name: str | None = None
    label: str


class NotificationItem(StrictModel):
    notification_id: UUID
    notification_type: str
    category: str
    title: str
    body: str
    deep_link: str | None = None
    occurrence_count: int
    priority: Literal["normal", "high"]
    read: bool
    actor: NotificationActorProjection | None = None
    venue_id: UUID | None = None
    conversation_id: UUID | None = None
    calling_card_id: UUID | None = None
    story_id: UUID | None = None
    organization_id: UUID | None = None
    venue_claim_id: UUID | None = None
    latest_event_at: datetime
    created_at: datetime


class NotificationListResponse(StrictModel):
    items: list[NotificationItem]
    next_cursor: str | None = None


class UnreadCountResponse(StrictModel):
    total: int
    by_category: dict[str, int]


class ReadNotificationResponse(StrictModel):
    notification_id: UUID
    read: bool = True
    read_at: datetime


class ReadAllNotificationsRequest(StrictModel):
    category: str | None = None


class ReadAllNotificationsResponse(StrictModel):
    changed_count: int


class DismissNotificationResponse(StrictModel):
    notification_id: UUID
    dismissed: bool = True
    dismissed_at: datetime


class PreferenceItem(StrictModel):
    category: str
    in_app_enabled: bool
    push_enabled: bool


class PreferenceListResponse(StrictModel):
    items: list[PreferenceItem]


class PreferencePatchItem(StrictModel):
    category: str
    in_app_enabled: bool | None = None
    push_enabled: bool | None = None


class PreferencePatchRequest(StrictModel):
    items: list[PreferencePatchItem] = Field(min_length=1)


class PushTokenRegisterRequest(StrictModel):
    provider: Literal["expo"]
    token: str = Field(min_length=8, max_length=4096)


class PushTokenRegisterResponse(StrictModel):
    registered: bool = True
    provider: Literal["expo"]
    device_id: UUID


class PushTokenDeleteResponse(StrictModel):
    disabled: bool = True
    device_id: UUID


class RealtimeTicketRequest(StrictModel):
    purpose: Literal["notifications", "calling_cards"]


class RealtimeTicketResponse(StrictModel):
    ticket: str
    expires_in_seconds: int
    purpose: Literal["notifications", "calling_cards"]
    websocket_path: str
    # Clients must open websocket_path (no query ticket/access_token), then send:
    # {"type": "authenticate", "ticket": "<one-time-ticket>"} as the first message.


class RealtimeAuthenticateMessage(StrictModel):
    """First client message on a ticket-authenticated WebSocket."""

    type: Literal["authenticate"]
    ticket: str = Field(min_length=16, max_length=512)


SUPPORTED_CATEGORIES = set(NOTIFICATION_CATEGORIES)
