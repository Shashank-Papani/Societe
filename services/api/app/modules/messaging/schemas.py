"""Messaging wire contracts. ``extra="forbid"`` everywhere."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateConversationRequest(StrictModel):
    other_user_id: UUID | None = None
    connection_grant_id: UUID | None = None

    @model_validator(mode="after")
    def require_one_identifier(self) -> CreateConversationRequest:
        if self.other_user_id is None and self.connection_grant_id is None:
            msg = "Provide other_user_id or connection_grant_id."
            raise ValueError(msg)
        if self.other_user_id is not None and self.connection_grant_id is not None:
            msg = "Provide only one of other_user_id or connection_grant_id."
            raise ValueError(msg)
        return self


class SendMessageRequest(StrictModel):
    body: str = Field(min_length=1, max_length=4000)
    client_message_id: str = Field(min_length=8, max_length=128)


class MarkReadRequest(StrictModel):
    last_read_message_id: UUID | None = None


class ParticipantSummary(StrictModel):
    user_id: UUID
    handle: str | None = None
    display_name: str | None = None


class MessageSummary(StrictModel):
    id: UUID
    conversation_id: UUID
    sender_user_id: UUID
    client_message_id: str
    body: str | None
    status: Literal["sent", "deleted"]
    created_at: datetime
    edited_at: datetime | None = None
    deleted_at: datetime | None = None


class ConversationSummary(StrictModel):
    id: UUID
    other_participant: ParticipantSummary
    last_message_preview: str | None = None
    last_message_at: datetime | None = None
    unread_count: int
    archived_at: datetime | None = None
    messaging_allowed: bool
    created_at: datetime
    updated_at: datetime


class ConversationDetail(StrictModel):
    id: UUID
    other_participant: ParticipantSummary
    originating_connection_grant_id: UUID
    unread_count: int
    archived_at: datetime | None = None
    messaging_allowed: bool
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None


class ConversationListResponse(StrictModel):
    items: list[ConversationSummary]
    next_cursor: str | None = None


class MessageListResponse(StrictModel):
    items: list[MessageSummary]
    next_cursor: str | None = None


class MarkReadResponse(StrictModel):
    conversation_id: UUID
    last_read_message_id: UUID | None
    last_read_at: datetime | None
    unread_count: int


class ArchiveResponse(StrictModel):
    conversation_id: UUID
    archived_at: datetime | None
