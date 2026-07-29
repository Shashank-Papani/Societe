"""Organization ownership wire contracts. ``extra="forbid"`` everywhere."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

OrgRole = Literal["owner", "manager", "content_editor", "analyst"]
OrgStatus = Literal["active", "suspended", "deleted"]
ClaimStatus = Literal["pending", "under_review", "approved", "rejected", "cancelled"]
InvitationStatus = Literal["pending", "accepted", "expired", "revoked"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateOrganizationRequest(StrictModel):
    name: str = Field(min_length=2, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            msg = "Organization name is too short."
            raise ValueError(msg)
        return cleaned


class OrganizationSummary(StrictModel):
    id: UUID
    name: str
    status: OrgStatus
    created_at: datetime


class MyOrganizationMembership(StrictModel):
    organization: OrganizationSummary
    role: OrgRole
    joined_at: datetime


class OrganizationDetail(StrictModel):
    id: UUID
    name: str
    status: OrgStatus
    role: OrgRole
    created_at: datetime
    updated_at: datetime


class OrganizationMemberSummary(StrictModel):
    user_id: UUID
    handle: str
    display_name: str
    role: OrgRole
    joined_at: datetime


class CreateInvitationRequest(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    role: OrgRole


class InvitationCreatedResponse(StrictModel):
    id: UUID
    organization_id: UUID
    email_normalized: str
    role: OrgRole
    status: InvitationStatus
    expires_at: datetime
    # Plaintext returned only at creation for local/test delivery.
    token: str


class InvitationPublicView(StrictModel):
    id: UUID
    organization_name: str
    role: OrgRole
    status: InvitationStatus
    expires_at: datetime
    email_normalized: str


class UpdateMemberRoleRequest(StrictModel):
    role: OrgRole


class SubmitVenueClaimRequest(StrictModel):
    organization_id: UUID | None = None
    requested_organization_name: str | None = Field(default=None, max_length=120)
    business_email: str | None = Field(default=None, max_length=320)
    evidence_reference: str | None = Field(default=None, max_length=500)
    justification: str | None = Field(default=None, max_length=2000)


class VenueClaimPublic(StrictModel):
    id: UUID
    venue_id: UUID
    status: ClaimStatus
    organization_id: UUID | None = None
    requested_organization_name: str | None = None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None


class RejectVenueClaimRequest(StrictModel):
    reason: str = Field(min_length=3, max_length=500)


class ManagedVenueProfileUpdate(StrictModel):
    description: str | None = Field(default=None, max_length=4000)
    music_tags: list[str] | None = None
    experience_tags: list[str] | None = None


class SetVenueCoverRequest(StrictModel):
    media_asset_id: UUID
