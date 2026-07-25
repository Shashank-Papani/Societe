"""Media and Live Vibe wire contracts.

``extra="forbid"`` everywhere. Phase 3 is single-PUT only, so a client that
starts sending ``parts`` or ``upload_id`` fails loudly instead of having its
multipart intent silently ignored while the response still looks successful.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.media.text import normalize_plain_text, normalize_tag

MediaType = Literal["image", "video"]

AttributionMode = Literal["attributed", "anonymous"]

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

VibePublicationStatus = Literal[
    "draft",
    "processing",
    "published",
    "expired",
    "hidden",
    "removed",
    "rejected",
    "deleted",
    "revoked",
]

ReportReason = Literal[
    "spam",
    "harassment",
    "sexual_content",
    "violence",
    "hate",
    "illegal",
    "other",
]

VARIANT_TYPES: tuple[str, ...] = (
    "image_1080",
    "image_720",
    "thumbnail",
    "video_720",
    "video_poster",
)


class CreateUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    venue_id: UUID
    device_id: UUID
    media_type: MediaType
    mime_type: str = Field(min_length=3, max_length=100)
    byte_size: int = Field(gt=0)
    original_filename: str | None = Field(default=None, max_length=255)
    caption: str | None = None
    vibe_tags: list[str] = Field(default_factory=list)
    # Client-declared and advisory only. The server recomputes SHA-256 from the
    # bytes it downloads; this value is compared, never trusted.
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


class UploadInstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["PUT"]
    url: str
    headers: dict[str, str]
    expires_at: datetime


class CreateUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: UUID
    live_vibe_id: UUID
    lifecycle_status: MediaLifecycleStatus
    attribution_mode: AttributionMode
    intent_expires_at: datetime
    max_byte_size: int
    upload: UploadInstruction


class CompleteUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: UUID
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class MediaVariant(BaseModel):
    """A signed, short-lived URL. Object keys never cross the boundary."""

    model_config = ConfigDict(extra="forbid")

    variant_type: str
    mime_type: str
    url: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    expires_at: datetime


class UploadStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: UUID
    media_type: MediaType
    lifecycle_status: MediaLifecycleStatus
    moderation_status: Literal["pending", "approved", "rejected", "manual_review", "quarantined"]
    attribution_mode: AttributionMode
    live_vibe_id: UUID | None = None
    publication_status: VibePublicationStatus | None = None
    published_at: datetime | None = None
    expires_at: datetime | None = None
    intent_expires_at: datetime | None = None
    variants: list[MediaVariant] = Field(default_factory=list)
    failure_reason: str | None = None


class VibeAuthor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    handle: str
    display_name: str


class VibeFeedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    venue_id: UUID
    media_type: MediaType
    attribution_mode: AttributionMode
    # Absent for anonymous posts. The client renders "Anonymous"; the server
    # never ships an id that could be joined back to a profile.
    author: VibeAuthor | None = None
    # Stable public label. Always "Anonymous" when attribution_mode is anonymous.
    author_label: str
    caption: str | None = None
    vibe_tags: list[str] = Field(default_factory=list)
    published_at: datetime
    expires_at: datetime
    variants: list[MediaVariant] = Field(default_factory=list)
    viewer_is_author: bool = False


class VibeFeedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[VibeFeedItem]
    next_cursor: str | None = None


class CreatorVibeItem(BaseModel):
    """Author-facing metadata. Media URLs only while retention still allows them."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    venue_id: UUID
    media_asset_id: UUID
    media_type: MediaType
    attribution_mode: AttributionMode
    publication_status: VibePublicationStatus
    lifecycle_status: MediaLifecycleStatus
    moderation_status: Literal["pending", "approved", "rejected", "manual_review", "quarantined"]
    caption: str | None = None
    vibe_tags: list[str] = Field(default_factory=list)
    created_at: datetime
    published_at: datetime | None = None
    expires_at: datetime | None = None
    variants: list[MediaVariant] = Field(default_factory=list)


class CreatorVibeListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CreatorVibeItem]
    next_cursor: str | None = None


class CreateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: ReportReason
    description: str | None = None

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CreateReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: UUID
    live_vibe_id: UUID
    reason: ReportReason
    status: Literal["open", "triaged", "resolved", "dismissed"]
    created_at: datetime
    content_hidden: bool = False


class DeleteVibeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    live_vibe_id: UUID
    publication_status: VibePublicationStatus
