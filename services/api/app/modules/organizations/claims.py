"""Venue ownership claim workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    Organization,
    OrganizationMember,
    OutboxEvent,
    User,
    Venue,
    VenueClaim,
    VenueOrganization,
)
from app.modules.identity.crypto_util import normalize_email
from app.modules.organizations.audit import (
    VENUE_CLAIM_APPROVED,
    VENUE_CLAIM_REJECTED,
    VENUE_CLAIM_SUBMITTED,
    VENUE_LINKED,
    append_audit_event,
)
from app.modules.organizations.authz import (
    ACTIVE_MEMBER,
    ACTIVE_VENUE_LINK,
    ROLE_MANAGER,
    ROLE_OWNER,
    OrganizationAuthorizer,
    assert_user_account_active,
)
from app.modules.organizations.names import normalize_organization_name
from app.modules.organizations.rates import OrganizationRateLimiter
from app.modules.organizations.schemas import (
    ClaimStatus,
    SubmitVenueClaimRequest,
    VenueClaimPublic,
)
from app.modules.organizations.service import require_venue_organizations_enabled


class ClaimService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis[str],
        settings: Settings,
    ) -> None:
        self._session = session
        self._settings = settings
        self._authz = OrganizationAuthorizer(session)
        self._rates = OrganizationRateLimiter(redis, settings)

    def _require_enabled(self) -> None:
        require_venue_organizations_enabled(self._settings)

    def _emit(
        self,
        *,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        occurred_at: datetime,
        payload: dict[str, object],
    ) -> None:
        self._session.add(
            OutboxEvent(
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
                available_at=occurred_at,
            )
        )

    def _public(self, claim: VenueClaim) -> dict[str, Any]:
        return VenueClaimPublic(
            id=claim.id,
            venue_id=claim.venue_id,
            status=cast(ClaimStatus, claim.status),
            organization_id=claim.claimant_organization_id,
            requested_organization_name=claim.requested_organization_name,
            created_at=claim.created_at,
            updated_at=claim.updated_at,
            reviewed_at=claim.reviewed_at,
            rejection_reason=claim.rejection_reason,
        ).model_dump(mode="json")

    async def submit_claim(
        self,
        user: User,
        venue_id: UUID,
        body: SubmitVenueClaimRequest,
        now: datetime,
    ) -> dict[str, Any]:
        self._require_enabled()
        assert_user_account_active(user)
        await self._rates.check_claim(user_id=user.id, now=now)

        venue = await self._session.get(Venue, venue_id)
        if venue is None or venue.status == "draft":
            raise AppError("VENUE_NOT_FOUND", "Venue not found.", status_code=404)

        existing_link = await self._session.execute(
            select(VenueOrganization)
            .where(
                VenueOrganization.venue_id == venue_id,
                VenueOrganization.status == ACTIVE_VENUE_LINK,
            )
            .limit(1)
        )
        if existing_link.scalar_one_or_none() is not None:
            raise AppError(
                "VENUE_ALREADY_CLAIMED",
                "This venue is already linked to an organization.",
                status_code=409,
            )

        if body.organization_id is None and not (body.requested_organization_name or "").strip():
            raise AppError(
                "CLAIM_ORGANIZATION_REQUIRED",
                "Provide an organization_id or requested_organization_name.",
                status_code=400,
            )

        claimant_organization_id: UUID | None = None
        requested_name: str | None = None
        if body.organization_id is not None:
            ctx = await self._authz.load_active_membership(
                user_id=user.id, organization_id=body.organization_id
            )
            if ctx.role not in {ROLE_OWNER, ROLE_MANAGER}:
                raise AppError(
                    "ORGANIZATION_FORBIDDEN",
                    "Only owners or managers can claim a venue for an organization.",
                    status_code=403,
                )
            claimant_organization_id = body.organization_id
        else:
            assert body.requested_organization_name is not None
            requested_name = body.requested_organization_name.strip()
            if len(normalize_organization_name(requested_name)) < 2:
                raise AppError(
                    "ORGANIZATION_NAME_INVALID",
                    "Organization name is too short.",
                    status_code=400,
                )

        business_email = normalize_email(body.business_email) if body.business_email else None

        claim = VenueClaim(
            venue_id=venue_id,
            claimant_user_id=user.id,
            claimant_organization_id=claimant_organization_id,
            requested_organization_name=requested_name,
            business_email=business_email,
            evidence_reference=body.evidence_reference,
            justification=body.justification,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(claim)
                await self._session.flush()
        except IntegrityError as exc:
            raise AppError(
                "CLAIM_ALREADY_PENDING",
                "You already have a pending claim for this venue.",
                status_code=409,
            ) from exc

        await append_audit_event(
            self._session,
            event_type=VENUE_CLAIM_SUBMITTED,
            actor_user_id=user.id,
            organization_id=claimant_organization_id,
            venue_id=venue_id,
            target_type="venue_claim",
            target_id=claim.id,
            metadata={
                "requested_organization_name": requested_name,
                "has_evidence": body.evidence_reference is not None,
            },
        )
        self._emit(
            aggregate_type="venue_claim",
            aggregate_id=claim.id,
            event_type="venue.claim.created",
            occurred_at=now,
            payload={
                "claim_id": str(claim.id),
                "venue_id": str(venue_id),
                "claimant_user_id": str(user.id),
                "organization_id": (
                    str(claimant_organization_id) if claimant_organization_id else None
                ),
            },
        )
        await self._session.commit()
        return self._public(claim)

    async def list_my_claims(self, user: User) -> list[dict[str, Any]]:
        self._require_enabled()
        assert_user_account_active(user)
        result = await self._session.execute(
            select(VenueClaim)
            .where(VenueClaim.claimant_user_id == user.id)
            .order_by(VenueClaim.created_at.desc())
        )
        return [self._public(claim) for claim in result.scalars().all()]

    async def cancel_claim(self, user: User, claim_id: UUID, now: datetime) -> dict[str, Any]:
        self._require_enabled()
        assert_user_account_active(user)
        result = await self._session.execute(
            select(VenueClaim).where(VenueClaim.id == claim_id).with_for_update().limit(1)
        )
        claim = result.scalar_one_or_none()
        if claim is None or claim.claimant_user_id != user.id:
            raise AppError("CLAIM_NOT_FOUND", "Venue claim was not found.", status_code=404)
        if claim.status not in {"pending", "under_review"}:
            raise AppError(
                "CLAIM_NOT_CANCELLABLE",
                "Only pending claims can be cancelled.",
                status_code=409,
            )
        claim.status = "cancelled"
        claim.updated_at = now
        await self._session.flush()
        await self._session.commit()
        return self._public(claim)

    async def approve_claim(
        self, admin_user: User, claim_id: UUID, now: datetime
    ) -> dict[str, Any]:
        self._require_enabled()
        assert_user_account_active(admin_user)

        result = await self._session.execute(
            select(VenueClaim).where(VenueClaim.id == claim_id).with_for_update().limit(1)
        )
        claim = result.scalar_one_or_none()
        if claim is None:
            raise AppError("CLAIM_NOT_FOUND", "Venue claim was not found.", status_code=404)

        # Idempotent double-approval: return current public view.
        if claim.status == "approved":
            return self._public(claim)

        if claim.status in {"rejected", "cancelled"}:
            raise AppError(
                "CLAIM_ALREADY_FINALIZED",
                "This claim has already been finalized.",
                status_code=409,
            )

        organization = await self._resolve_claim_organization(claim, now=now)

        link_result = await self._session.execute(
            select(VenueOrganization)
            .where(VenueOrganization.venue_id == claim.venue_id)
            .with_for_update()
        )
        links = list(link_result.scalars().all())
        active = next((row for row in links if row.status == ACTIVE_VENUE_LINK), None)
        if active is not None and active.organization_id != organization.id:
            raise AppError(
                "VENUE_ALREADY_CLAIMED",
                "This venue is already linked to another organization.",
                status_code=409,
            )
        if active is None:
            active = next(
                (
                    row
                    for row in links
                    if row.organization_id == organization.id and row.status == "unlinked"
                ),
                None,
            )
            if active is not None:
                active.status = ACTIVE_VENUE_LINK
                active.unlinked_at = None
                active.approved_claim_id = claim.id
                active.linked_at = now
            else:
                active = VenueOrganization(
                    venue_id=claim.venue_id,
                    organization_id=organization.id,
                    status=ACTIVE_VENUE_LINK,
                    approved_claim_id=claim.id,
                    linked_at=now,
                )
                self._session.add(active)
            await self._session.flush()

        await self._ensure_claimant_owner(
            organization_id=organization.id,
            user_id=claim.claimant_user_id,
            now=now,
        )

        claim.status = "approved"
        claim.claimant_organization_id = organization.id
        claim.reviewed_by_user_id = admin_user.id
        claim.reviewed_at = now
        claim.updated_at = now
        await self._session.flush()

        await append_audit_event(
            self._session,
            event_type=VENUE_CLAIM_APPROVED,
            actor_user_id=admin_user.id,
            organization_id=organization.id,
            venue_id=claim.venue_id,
            target_type="venue_claim",
            target_id=claim.id,
            metadata={"organization_id": str(organization.id)},
        )
        await append_audit_event(
            self._session,
            event_type=VENUE_LINKED,
            actor_user_id=admin_user.id,
            organization_id=organization.id,
            venue_id=claim.venue_id,
            target_type="venue_organization",
            target_id=active.id,
            metadata={"claim_id": str(claim.id)},
        )
        self._emit(
            aggregate_type="venue_claim",
            aggregate_id=claim.id,
            event_type="venue.claim.approved",
            occurred_at=now,
            payload={
                "claim_id": str(claim.id),
                "venue_id": str(claim.venue_id),
                "organization_id": str(organization.id),
                "claimant_user_id": str(claim.claimant_user_id),
            },
        )
        await self._session.commit()
        return self._public(claim)

    async def reject_claim(
        self,
        admin_user: User,
        claim_id: UUID,
        reason: str,
        now: datetime,
    ) -> dict[str, Any]:
        self._require_enabled()
        assert_user_account_active(admin_user)

        result = await self._session.execute(
            select(VenueClaim).where(VenueClaim.id == claim_id).with_for_update().limit(1)
        )
        claim = result.scalar_one_or_none()
        if claim is None:
            raise AppError("CLAIM_NOT_FOUND", "Venue claim was not found.", status_code=404)

        if claim.status in {"approved", "rejected"}:
            raise AppError(
                "CLAIM_ALREADY_FINALIZED",
                "This claim has already been finalized.",
                status_code=409,
            )
        if claim.status == "cancelled":
            raise AppError(
                "CLAIM_ALREADY_FINALIZED",
                "This claim has already been finalized.",
                status_code=409,
            )

        claim.status = "rejected"
        claim.rejection_reason = reason.strip()
        claim.reviewed_by_user_id = admin_user.id
        claim.reviewed_at = now
        claim.updated_at = now
        await self._session.flush()

        await append_audit_event(
            self._session,
            event_type=VENUE_CLAIM_REJECTED,
            actor_user_id=admin_user.id,
            organization_id=claim.claimant_organization_id,
            venue_id=claim.venue_id,
            target_type="venue_claim",
            target_id=claim.id,
            metadata={"reason_length": len(claim.rejection_reason)},
        )
        await self._session.commit()
        return self._public(claim)

    async def _resolve_claim_organization(
        self, claim: VenueClaim, *, now: datetime
    ) -> Organization:
        if claim.claimant_organization_id is not None:
            organization = await self._session.get(Organization, claim.claimant_organization_id)
            if organization is None or organization.deleted_at is not None:
                raise AppError(
                    "ORGANIZATION_NOT_FOUND",
                    "Claim organization was not found.",
                    status_code=404,
                )
            return organization

        name = (claim.requested_organization_name or "").strip()
        normalized = normalize_organization_name(name)
        if len(normalized) < 2:
            raise AppError(
                "ORGANIZATION_NAME_INVALID",
                "Claim is missing a valid organization name.",
                status_code=400,
            )

        existing = await self._session.execute(
            select(Organization)
            .where(
                Organization.normalized_name == normalized,
                Organization.deleted_at.is_(None),
                Organization.status != "deleted",
            )
            .with_for_update()
            .limit(1)
        )
        organization = existing.scalar_one_or_none()
        if organization is not None:
            return organization

        organization = Organization(
            name=name,
            normalized_name=normalized,
            status="active",
            created_by_user_id=claim.claimant_user_id,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(organization)
                await self._session.flush()
        except IntegrityError as exc:
            raise AppError(
                "ORGANIZATION_NAME_CONFLICT",
                "An organization with this name already exists.",
                status_code=409,
            ) from exc
        return organization

    async def _ensure_claimant_owner(
        self, *, organization_id: UUID, user_id: UUID, now: datetime
    ) -> None:
        result = await self._session.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
            .with_for_update()
            .order_by(OrganizationMember.created_at.desc())
            .limit(1)
        )
        membership = result.scalar_one_or_none()
        if membership is not None and membership.status == ACTIVE_MEMBER:
            if membership.role != ROLE_OWNER:
                membership.role = ROLE_OWNER
                membership.updated_at = now
                await self._session.flush()
            return
        if membership is not None and membership.status == "removed":
            membership.status = ACTIVE_MEMBER
            membership.role = ROLE_OWNER
            membership.removed_at = None
            membership.joined_at = now
            membership.updated_at = now
            await self._session.flush()
            return

        self._session.add(
            OrganizationMember(
                organization_id=organization_id,
                user_id=user_id,
                role=ROLE_OWNER,
                status=ACTIVE_MEMBER,
                joined_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await self._session.flush()
