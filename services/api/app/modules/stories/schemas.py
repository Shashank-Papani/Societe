"""Stories and official venue post wire contracts. ``extra="forbid"`` everywhere."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.media.schemas import MediaType, MediaVariant, ReportReason
from app.modules.media.text import normalize_plain_text, normalize_tag

StoryAttributionMode = Literal["attributed", "anonymous"]
StoryReplyPolicy = Literal["disabled", "connections", "everyone"]
StoryPublicationStatus = Literal[
    "draft",
    "uploaded",
    "processing",
    "moderation_pending",
    "published",
    "expired",
    "hidden",
    "rejected",
    "failed",
    "deleted",
]
MediaLifecycleStatus = Literal[
    "intent_pending",
    "uploaded",
    "validating",
    "processing",
    "moderation_pending",
    "ready",
    "upload_expired",
    "invalid",
    "processing_failed",
    "rejected",
    "manual_review",
    "deleted",
    "revoked",
]
ModerationStatus = Literal["pending", "approved", "rejected", "manual_review", "quarantined"]
OfficialPostType = Literal[
    "announcement", "event", "dj", "special", "policy", "promotion", "general"
]
OfficialPostPublicationStatus = Literal[
    "draft",
    "processing",
    "moderation_pending",
    "published",
    "archived",
    "rejected",
    "failed",
    "deleted",
]
GroupType = Literal["venue", "user", "anon"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UploadInstruction(StrictModel):
    method: Literal["PUT"]
    url: str
    headers: dict[str, str]
    expires_at: datetime


class CreateUserStoryUploadRequest(StrictModel):
    venue_id: UUID
    device_id: UUID
    media_type: MediaType
    mime_type: str = Field(min_length=3, max_length=100)
    byte_size: int = Field(gt=0)
    caption: str | None = None
    vibe_tags: list[str] = Field(default_factory=list)
    attribution_mode: StoryAttributionMode
    reply_policy: StoryReplyPolicy = "disabled"
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("caption")
    @classmethod
    def strip_caption(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = normalize_plain_text(value)
        return cleaned or None

    @field_validator("vibe_tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for raw in value:
            tag = normalize_tag(raw)
            if tag and tag not in seen:
                seen.append(tag)
        return seen


class CreateOfficialStoryUploadRequest(StrictModel):
    media_type: MediaType
    mime_type: str = Field(min_length=3, max_length=100)
    byte_size: int = Field(gt=0)
    caption: str | None = None
    vibe_tags: list[str] = Field(default_factory=list)
    reply_policy: StoryReplyPolicy = "disabled"
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("caption")
    @classmethod
    def strip_caption(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = normalize_plain_text(value)
        return cleaned or None

    @field_validator("vibe_tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for raw in value:
            tag = normalize_tag(raw)
            if tag and tag not in seen:
                seen.append(tag)
        return seen


class CompleteStoryUploadRequest(StrictModel):
    device_id: UUID | None = None
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class StoryUploadResponse(StrictModel):
    story_id: UUID
    upload_id: UUID
    media_asset_id: UUID
    lifecycle_status: MediaLifecycleStatus
    publication_status: StoryPublicationStatus
    moderation_status: ModerationStatus
    attribution_mode: Literal["attributed", "anonymous", "official"]
    intent_expires_at: datetime
    max_byte_size: int
    upload: UploadInstruction | None = None
    variants: list[MediaVariant] = Field(default_factory=list)
    failure_reason: str | None = None
    expires_at: datetime | None = None
    published_at: datetime | None = None


class StoryAuthorProjection(StrictModel):
    id: UUID | None = None
    handle: str | None = None
    display_name: str | None = None


class VenueStoryProjection(StrictModel):
    id: UUID
    name: str
    slug: str | None = None


class StoryGroupSummary(StrictModel):
    group_key: str
    group_type: GroupType
    venue_id: UUID | None = None
    author: StoryAuthorProjection | None = None
    author_label: str
    venue: VenueStoryProjection | None = None
    is_official: bool = False
    is_mine: bool = False
    preview_variants: list[MediaVariant] = Field(default_factory=list)
    active_count: int
    unviewed_count: int
    latest_published_at: datetime
    earliest_expires_at: datetime


class StorySlide(StrictModel):
    story_id: UUID
    venue_id: UUID
    media_type: MediaType
    attribution_mode: Literal["attributed", "anonymous", "official"]
    author: StoryAuthorProjection | None = None
    author_label: str
    venue: VenueStoryProjection | None = None
    is_official: bool = False
    caption: str | None = None
    vibe_tags: list[str] = Field(default_factory=list)
    reply_policy: StoryReplyPolicy
    published_at: datetime
    expires_at: datetime
    viewed: bool = False
    is_mine: bool = False
    can_report: bool = False
    can_delete: bool = False
    variants: list[MediaVariant] = Field(default_factory=list)


class StoryGroupDetail(StrictModel):
    group_key: str
    group_type: GroupType
    venue_id: UUID | None = None
    author_label: str
    is_official: bool = False
    is_mine: bool = False
    slides: list[StorySlide]


class StoryGroupListResponse(StrictModel):
    items: list[StoryGroupSummary]


class RecordStoryViewResponse(StrictModel):
    story_id: UUID
    viewed: bool = True
    viewed_at: datetime


class CreateStoryReportRequest(StrictModel):
    reason: ReportReason
    description: str | None = None

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CreateStoryReportResponse(StrictModel):
    report_id: UUID
    story_id: UUID
    reason: ReportReason
    status: Literal["open", "reviewing", "resolved", "dismissed"]
    created_at: datetime


class DeleteStoryResponse(StrictModel):
    story_id: UUID
    publication_status: StoryPublicationStatus


class CreateOfficialPostRequest(StrictModel):
    post_type: OfficialPostType
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    call_to_action_type: str | None = Field(default=None, max_length=40)
    call_to_action_url: str | None = Field(default=None, max_length=2048)
    # Optional media intent — when present, post stays draft until moderation.
    media_type: MediaType | None = None
    mime_type: str | None = Field(default=None, min_length=3, max_length=100)
    byte_size: int | None = Field(default=None, gt=0)
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = normalize_plain_text(value)
        return cleaned or None

    @field_validator("body")
    @classmethod
    def strip_body(cls, value: str) -> str:
        cleaned = normalize_plain_text(value)
        if not cleaned:
            msg = "Body is required."
            raise ValueError(msg)
        return cleaned

    @model_validator(mode="after")
    def media_fields_together(self) -> CreateOfficialPostRequest:
        media_fields = (self.media_type, self.mime_type, self.byte_size)
        present = [f is not None for f in media_fields]
        if any(present) and not all(present):
            msg = "media_type, mime_type, and byte_size are all required when attaching media."
            raise ValueError(msg)
        return self


class OfficialPostUpload(StrictModel):
    upload_id: UUID
    media_asset_id: UUID
    intent_expires_at: datetime
    max_byte_size: int
    upload: UploadInstruction


class OfficialPostSummary(StrictModel):
    post_id: UUID
    venue_id: UUID
    post_type: OfficialPostType
    title: str | None = None
    body: str
    call_to_action_type: str | None = None
    call_to_action_url: str | None = None
    publication_status: OfficialPostPublicationStatus
    published_at: datetime | None = None
    # Public semantics: always official; label is the venue, never staff identity.
    is_official: bool = True
    author_label: str
    venue: VenueStoryProjection | None = None
    variants: list[MediaVariant] = Field(default_factory=list)


class OfficialPostDetail(OfficialPostSummary):
    created_at: datetime


class OfficialPostCreateResponse(StrictModel):
    post: OfficialPostDetail
    upload: OfficialPostUpload | None = None


class OfficialPostListResponse(StrictModel):
    items: list[OfficialPostSummary]
    next_cursor: str | None = None
