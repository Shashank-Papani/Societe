"""Calling Card and block wire contracts. ``extra="forbid"`` everywhere."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.social.message_validation import CUSTOM_MESSAGE_MAX

CallingCardStatus = Literal[
    "pending",
    "accepted",
    "declined",
    "expired",
    "cancelled",
    "blocked",
]

ResponseDecision = Literal["accept", "decline"]

ResponseAction = Literal["share_info", "make_move", "accept_only"]

ShareScope = Literal["instagram", "spotify", "phone", "snapchat", "display_name"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateCallingCardRequest(StrictModel):
    recipient_user_id: UUID
    reason_code: str | None = Field(default=None, max_length=64)
    # Legacy free-text field; preferred field is custom_message.
    reason_text: str | None = Field(default=None, max_length=280)
    custom_message: str | None = Field(default=None, max_length=CUSTOM_MESSAGE_MAX)

    @field_validator("reason_code")
    @classmethod
    def _normalize_reason_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        return cleaned or None


class RespondCallingCardRequest(StrictModel):
    decision: ResponseDecision
    action: ResponseAction | None = None
    share_scopes: list[ShareScope] = Field(default_factory=list)


class ShareCallingCardRequest(StrictModel):
    share_scopes: list[ShareScope] = Field(min_length=0, max_length=10)


class BlockUserRequest(StrictModel):
    reason_code: str | None = Field(default=None, max_length=64)


class CallingCardSummary(StrictModel):
    id: UUID
    status: CallingCardStatus
    venue_id: UUID
    sender_user_id: UUID
    recipient_user_id: UUID
    reason_code: str | None = None
    reason_text: str | None = None
    custom_message: str | None = None
    created_at: datetime
    expires_at: datetime
    responded_at: datetime | None = None
    response_action: ResponseAction | None = None
    # True when a non-revoked ConnectionGrant exists for this card.
    # Accepted cards can remain after block (grant revoked); messaging uses this flag.
    has_active_grant: bool = False


class CallingCardCreateResponse(StrictModel):
    id: UUID
    status: CallingCardStatus
    venue_id: UUID
    expires_at: datetime


class CallingCardListResponse(StrictModel):
    items: list[CallingCardSummary]


class CallingCardStatusResponse(StrictModel):
    id: UUID
    status: CallingCardStatus
    expires_at: datetime
    responded_at: datetime | None = None


class ConnectionGrantSummary(StrictModel):
    id: UUID
    calling_card_id: UUID
    scopes: list[str]
    # NULL = durable for messaging (ADR 0014).
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class CallingCardDetailResponse(StrictModel):
    card: CallingCardSummary
    grant: ConnectionGrantSummary | None = None


class RespondCallingCardResponse(StrictModel):
    card: CallingCardSummary
    grant: ConnectionGrantSummary | None = None


class DiscoverableUser(StrictModel):
    user_id: UUID
    handle: str
    display_name: str


class DiscoverableUsersResponse(StrictModel):
    venue_id: UUID
    items: list[DiscoverableUser]


class BlockResponse(StrictModel):
    blocker_user_id: UUID
    blocked_user_id: UUID
    created_at: datetime


class UnblockResponse(StrictModel):
    blocker_user_id: UUID
    blocked_user_id: UUID
    removed: bool


class BlockedUserItem(StrictModel):
    user_id: UUID
    handle: str
    display_name: str
    blocked_at: datetime
    profile_photo_url: str | None = None


class BlockedUsersResponse(StrictModel):
    blocked_users: list[BlockedUserItem]
