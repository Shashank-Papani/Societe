"""Organization membership and invitation service.

Transactions: flush intermediate rows, single commit at the end of each
mutating method. Never put invitation plaintext tokens in audit metadata,
outbox payloads, or logs.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import (
    AuthIdentity,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    OutboxEvent,
    User,
)
from app.modules.identity.crypto_util import hash_secret, normalize_email
from app.modules.identity.email import EmailMessage, build_email_sender
from app.modules.organizations.audit import (
    MEMBERSHIP_ACCEPTED,
    MEMBERSHIP_INVITED,
    MEMBERSHIP_REMOVED,
    MEMBERSHIP_ROLE_CHANGED,
    ORGANIZATION_CREATED,
    append_audit_event,
)
from app.modules.organizations.authz import (
    ACTIVE_MEMBER,
    ROLE_OWNER,
    OrganizationAuthorizer,
    OrgPermission,
    assert_user_account_active,
    can_invite_role,
    can_manage_member,
)
from app.modules.organizations.names import normalize_organization_name
from app.modules.organizations.rates import OrganizationRateLimiter
from app.modules.organizations.schemas import (
    InvitationCreatedResponse,
    InvitationPublicView,
    InvitationStatus,
    MyOrganizationMembership,
    OrganizationDetail,
    OrganizationMemberSummary,
    OrganizationSummary,
    OrgRole,
    OrgStatus,
)

logger = get_logger(__name__)


def require_venue_organizations_enabled(settings: Settings) -> None:
    if not settings.ff_venue_organizations:
        raise AppError(
            "FEATURE_DISABLED",
            "Venue organizations are not enabled.",
            status_code=404,
        )


class OrganizationService:
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

    async def create_organization(self, user: User, name: str, now: datetime) -> dict[str, Any]:
        self._require_enabled()
        assert_user_account_active(user)
        cleaned = name.strip()
        normalized = normalize_organization_name(cleaned)
        if len(normalized) < 2:
            raise AppError(
                "ORGANIZATION_NAME_INVALID",
                "Organization name is too short.",
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
        if existing.scalar_one_or_none() is not None:
            raise AppError(
                "ORGANIZATION_NAME_CONFLICT",
                "An organization with this name already exists.",
                status_code=409,
            )

        org = Organization(
            name=cleaned,
            normalized_name=normalized,
            status="active",
            created_by_user_id=user.id,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(org)
                await self._session.flush()
        except IntegrityError as exc:
            raise AppError(
                "ORGANIZATION_NAME_CONFLICT",
                "An organization with this name already exists.",
                status_code=409,
            ) from exc

        membership = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=ROLE_OWNER,
            status=ACTIVE_MEMBER,
            invited_by_user_id=None,
            joined_at=now,
            created_at=now,
            updated_at=now,
        )
        self._session.add(membership)
        await self._session.flush()

        await append_audit_event(
            self._session,
            event_type=ORGANIZATION_CREATED,
            actor_user_id=user.id,
            organization_id=org.id,
            target_type="organization",
            target_id=org.id,
            metadata={"name": org.name},
        )
        self._emit(
            aggregate_type="organization",
            aggregate_id=org.id,
            event_type="organization.created",
            occurred_at=now,
            payload={
                "organization_id": str(org.id),
                "name": org.name,
                "created_by_user_id": str(user.id),
            },
        )
        await self._session.commit()
        return OrganizationDetail(
            id=org.id,
            name=org.name,
            status=cast(OrgStatus, org.status),
            role=cast(OrgRole, ROLE_OWNER),
            created_at=org.created_at,
            updated_at=org.updated_at,
        ).model_dump(mode="json")

    async def list_my_organizations(self, user: User) -> list[dict[str, Any]]:
        self._require_enabled()
        assert_user_account_active(user)
        result = await self._session.execute(
            select(OrganizationMember, Organization)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.status == ACTIVE_MEMBER,
                Organization.deleted_at.is_(None),
                Organization.status == "active",
            )
            .order_by(OrganizationMember.joined_at.desc())
        )
        items: list[dict[str, Any]] = []
        for membership, org in result.all():
            items.append(
                MyOrganizationMembership(
                    organization=OrganizationSummary(
                        id=org.id,
                        name=org.name,
                        status=cast(OrgStatus, org.status),
                        created_at=org.created_at,
                    ),
                    role=cast(OrgRole, membership.role),
                    joined_at=membership.joined_at,
                ).model_dump(mode="json")
            )
        return items

    async def get_organization(self, user: User, organization_id: UUID) -> dict[str, Any]:
        self._require_enabled()
        ctx = await self._authz.require_organization_permission(
            user, organization_id, OrgPermission.ORGANIZATION_VIEW
        )
        org = ctx.organization
        return OrganizationDetail(
            id=org.id,
            name=org.name,
            status=cast(OrgStatus, org.status),
            role=cast(OrgRole, ctx.role),
            created_at=org.created_at,
            updated_at=org.updated_at,
        ).model_dump(mode="json")

    async def list_members(self, user: User, organization_id: UUID) -> list[dict[str, Any]]:
        self._require_enabled()
        await self._authz.require_organization_permission(
            user, organization_id, OrgPermission.ORGANIZATION_VIEW
        )
        result = await self._session.execute(
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.status == ACTIVE_MEMBER,
                User.deleted_at.is_(None),
            )
            .order_by(OrganizationMember.joined_at.asc())
        )
        return [
            OrganizationMemberSummary(
                user_id=member.user_id,
                handle=member_user.handle,
                display_name=member_user.display_name,
                role=cast(OrgRole, member.role),
                joined_at=member.joined_at,
            ).model_dump(mode="json")
            for member, member_user in result.all()
        ]

    async def invite_member(
        self,
        user: User,
        organization_id: UUID,
        email: str,
        role: str,
        now: datetime,
    ) -> InvitationCreatedResponse:
        self._require_enabled()
        ctx = await self._authz.require_organization_permission(
            user, organization_id, OrgPermission.ORGANIZATION_MEMBERS_INVITE
        )
        if not can_invite_role(inviter_role=ctx.role, invitee_role=role):
            raise AppError(
                "ORGANIZATION_FORBIDDEN",
                "You cannot invite a member with that role.",
                status_code=403,
            )

        await self._rates.check_invitation(organization_id=organization_id, now=now)

        email_normalized = normalize_email(email)
        if "@" not in email_normalized or "." not in email_normalized.split("@")[-1]:
            raise AppError("INVALID_EMAIL", "Enter a valid email address.", status_code=400)

        pending = await self._session.execute(
            select(OrganizationInvitation)
            .where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.email_normalized == email_normalized,
                OrganizationInvitation.status == "pending",
            )
            .with_for_update()
            .limit(1)
        )
        if pending.scalar_one_or_none() is not None:
            raise AppError(
                "INVITATION_ALREADY_PENDING",
                "A pending invitation already exists for this email.",
                status_code=409,
            )

        token = secrets.token_urlsafe(32)
        token_hash = hash_secret(token, self._settings)
        expires_at = now + timedelta(seconds=self._settings.organization_invitation_ttl_seconds)
        invitation = OrganizationInvitation(
            organization_id=organization_id,
            email_normalized=email_normalized,
            role=role,
            token_hash=token_hash,
            invited_by_user_id=user.id,
            status="pending",
            expires_at=expires_at,
            created_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(invitation)
                await self._session.flush()
        except IntegrityError as exc:
            raise AppError(
                "INVITATION_ALREADY_PENDING",
                "A pending invitation already exists for this email.",
                status_code=409,
            ) from exc

        await append_audit_event(
            self._session,
            event_type=MEMBERSHIP_INVITED,
            actor_user_id=user.id,
            organization_id=organization_id,
            target_type="organization_invitation",
            target_id=invitation.id,
            metadata={
                "email_normalized": email_normalized,
                "role": role,
                "invitation_id": str(invitation.id),
            },
        )
        self._emit(
            aggregate_type="organization_invitation",
            aggregate_id=invitation.id,
            event_type="organization.invitation.created",
            occurred_at=now,
            payload={
                "invitation_id": str(invitation.id),
                "organization_id": str(organization_id),
                "email_normalized": email_normalized,
                "role": role,
                "expires_at": expires_at.isoformat(),
            },
        )

        sender = build_email_sender(self._settings)
        await sender.send(
            EmailMessage(
                to_address=email_normalized,
                subject=f"You're invited to join {ctx.organization.name} on Société",
                text_body=(
                    f"You have been invited to join {ctx.organization.name} "
                    f"as {role.replace('_', ' ')}.\n\n"
                    f"Invitation token: {token}\n\n"
                    "If you did not expect this invitation, you can ignore this email.\n"
                ),
            )
        )
        logger.info(
            "organization_invitation_sent",
            organization_id=str(organization_id),
            invitation_id=str(invitation.id),
            email_domain=email_normalized.split("@")[-1],
        )

        await self._session.commit()
        return InvitationCreatedResponse(
            id=invitation.id,
            organization_id=organization_id,
            email_normalized=email_normalized,
            role=cast(OrgRole, role),
            status="pending",
            expires_at=expires_at,
            token=token,
        )

    async def _lock_active_owners(self, organization_id: UUID) -> list[OrganizationMember]:
        result = await self._session.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.role == ROLE_OWNER,
                OrganizationMember.status == ACTIVE_MEMBER,
            )
            .with_for_update()
        )
        return list(result.scalars().all())

    async def update_member_role(
        self,
        user: User,
        organization_id: UUID,
        target_user_id: UUID,
        role: str,
        now: datetime,
    ) -> dict[str, Any]:
        self._require_enabled()
        ctx = await self._authz.require_organization_permission(
            user, organization_id, OrgPermission.ORGANIZATION_MEMBERS_MANAGE
        )

        result = await self._session.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == target_user_id,
                OrganizationMember.status == ACTIVE_MEMBER,
            )
            .with_for_update()
            .limit(1)
        )
        target = result.scalar_one_or_none()
        if target is None:
            raise AppError(
                "MEMBERSHIP_NOT_FOUND",
                "Organization member was not found.",
                status_code=404,
            )
        if not can_manage_member(actor_role=ctx.role, target_role=target.role):
            raise AppError(
                "ORGANIZATION_FORBIDDEN",
                "You cannot manage this member.",
                status_code=403,
            )
        if role == ROLE_OWNER and ctx.role != ROLE_OWNER:
            raise AppError(
                "ORGANIZATION_FORBIDDEN",
                "Only an owner can grant the owner role.",
                status_code=403,
            )

        previous_role = target.role
        if previous_role == ROLE_OWNER and role != ROLE_OWNER:
            owners = await self._lock_active_owners(organization_id)
            if len(owners) <= 1:
                raise AppError(
                    "LAST_OWNER_PROTECTED",
                    "Cannot demote the last organization owner.",
                    status_code=409,
                )

        target.role = role
        target.updated_at = now
        await self._session.flush()

        await append_audit_event(
            self._session,
            event_type=MEMBERSHIP_ROLE_CHANGED,
            actor_user_id=user.id,
            organization_id=organization_id,
            target_type="organization_member",
            target_id=target.id,
            metadata={
                "target_user_id": str(target_user_id),
                "previous_role": previous_role,
                "role": role,
            },
        )
        await self._session.commit()

        member_user = await self._session.get(User, target_user_id)
        assert member_user is not None
        return OrganizationMemberSummary(
            user_id=target.user_id,
            handle=member_user.handle,
            display_name=member_user.display_name,
            role=cast(OrgRole, target.role),
            joined_at=target.joined_at,
        ).model_dump(mode="json")

    async def remove_member(
        self,
        user: User,
        organization_id: UUID,
        target_user_id: UUID,
        now: datetime,
    ) -> dict[str, str]:
        self._require_enabled()
        ctx = await self._authz.require_organization_permission(
            user, organization_id, OrgPermission.ORGANIZATION_MEMBERS_MANAGE
        )

        result = await self._session.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == target_user_id,
                OrganizationMember.status == ACTIVE_MEMBER,
            )
            .with_for_update()
            .limit(1)
        )
        target = result.scalar_one_or_none()
        if target is None:
            raise AppError(
                "MEMBERSHIP_NOT_FOUND",
                "Organization member was not found.",
                status_code=404,
            )
        if not can_manage_member(actor_role=ctx.role, target_role=target.role):
            raise AppError(
                "ORGANIZATION_FORBIDDEN",
                "You cannot manage this member.",
                status_code=403,
            )

        if target.role == ROLE_OWNER:
            owners = await self._lock_active_owners(organization_id)
            if len(owners) <= 1:
                raise AppError(
                    "LAST_OWNER_PROTECTED",
                    "Cannot remove the last organization owner.",
                    status_code=409,
                )

        target.status = "removed"
        target.removed_at = now
        target.updated_at = now
        await self._session.flush()

        await append_audit_event(
            self._session,
            event_type=MEMBERSHIP_REMOVED,
            actor_user_id=user.id,
            organization_id=organization_id,
            target_type="organization_member",
            target_id=target.id,
            metadata={
                "target_user_id": str(target_user_id),
                "role": target.role,
            },
        )
        await self._session.commit()
        return {"status": "removed"}

    async def get_invitation_by_token(self, token: str) -> InvitationPublicView:
        self._require_enabled()
        token_hash = hash_secret(token, self._settings)
        result = await self._session.execute(
            select(OrganizationInvitation, Organization)
            .join(Organization, Organization.id == OrganizationInvitation.organization_id)
            .where(OrganizationInvitation.token_hash == token_hash)
            .limit(1)
        )
        row = result.one_or_none()
        if row is None:
            raise AppError(
                "INVITATION_NOT_FOUND",
                "Invitation was not found.",
                status_code=404,
            )
        invitation, organization = row
        now = datetime.now(UTC)
        if invitation.status == "pending" and invitation.expires_at <= now:
            invitation.status = "expired"
            await self._session.commit()

        return InvitationPublicView(
            id=invitation.id,
            organization_name=organization.name,
            role=cast(OrgRole, invitation.role),
            status=cast(InvitationStatus, invitation.status),
            expires_at=invitation.expires_at,
            email_normalized=invitation.email_normalized,
        )

    async def accept_invitation(self, user: User, token: str, now: datetime) -> dict[str, Any]:
        self._require_enabled()
        assert_user_account_active(user)
        token_hash = hash_secret(token, self._settings)

        result = await self._session.execute(
            select(OrganizationInvitation)
            .where(OrganizationInvitation.token_hash == token_hash)
            .with_for_update()
            .limit(1)
        )
        invitation = result.scalar_one_or_none()
        if invitation is None:
            raise AppError(
                "INVITATION_NOT_FOUND",
                "Invitation was not found.",
                status_code=404,
            )

        if invitation.status == "accepted" and invitation.accepted_by_user_id == user.id:
            membership = await self._load_active_membership(
                organization_id=invitation.organization_id, user_id=user.id
            )
            if membership is not None:
                return self._membership_summary(membership)

        if invitation.status == "pending" and invitation.expires_at <= now:
            invitation.status = "expired"
            await self._session.commit()
            raise AppError(
                "INVITATION_NOT_FOUND",
                "Invitation was not found.",
                status_code=404,
            )

        if invitation.status != "pending":
            raise AppError(
                "INVITATION_NOT_FOUND",
                "Invitation was not found.",
                status_code=404,
            )

        identities = await self._session.execute(
            select(AuthIdentity).where(AuthIdentity.user_id == user.id)
        )
        emails = {row.normalized_email for row in identities.scalars().all()}
        if invitation.email_normalized not in emails:
            raise AppError(
                "INVITATION_EMAIL_MISMATCH",
                "This invitation was sent to a different email address.",
                status_code=403,
            )

        membership = await self._ensure_membership(
            organization_id=invitation.organization_id,
            user_id=user.id,
            role=invitation.role,
            invited_by_user_id=invitation.invited_by_user_id,
            now=now,
        )

        invitation.status = "accepted"
        invitation.accepted_by_user_id = user.id
        invitation.accepted_at = now
        await self._session.flush()

        await append_audit_event(
            self._session,
            event_type=MEMBERSHIP_ACCEPTED,
            actor_user_id=user.id,
            organization_id=invitation.organization_id,
            target_type="organization_invitation",
            target_id=invitation.id,
            metadata={
                "role": invitation.role,
                "membership_id": str(membership.id),
            },
        )
        self._emit(
            aggregate_type="organization_invitation",
            aggregate_id=invitation.id,
            event_type="organization.invitation.accepted",
            occurred_at=now,
            payload={
                "invitation_id": str(invitation.id),
                "organization_id": str(invitation.organization_id),
                "user_id": str(user.id),
                "role": invitation.role,
            },
        )
        await self._session.commit()
        return self._membership_summary(membership)

    async def revoke_invitation(
        self, user: User, invitation_id: UUID, now: datetime
    ) -> dict[str, str]:
        self._require_enabled()
        result = await self._session.execute(
            select(OrganizationInvitation)
            .where(OrganizationInvitation.id == invitation_id)
            .with_for_update()
            .limit(1)
        )
        invitation = result.scalar_one_or_none()
        if invitation is None:
            raise AppError(
                "INVITATION_NOT_FOUND",
                "Invitation was not found.",
                status_code=404,
            )

        await self._authz.require_organization_permission(
            user,
            invitation.organization_id,
            OrgPermission.ORGANIZATION_MEMBERS_MANAGE,
        )

        if invitation.status != "pending":
            raise AppError(
                "INVITATION_NOT_PENDING",
                "Only pending invitations can be revoked.",
                status_code=409,
            )

        invitation.status = "revoked"
        invitation.revoked_at = now
        await self._session.flush()
        await self._session.commit()
        return {"status": "revoked"}

    async def _load_active_membership(
        self, *, organization_id: UUID, user_id: UUID
    ) -> OrganizationMember | None:
        result = await self._session.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
                OrganizationMember.status == ACTIVE_MEMBER,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _ensure_membership(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        role: str,
        invited_by_user_id: UUID | None,
        now: datetime,
    ) -> OrganizationMember:
        existing = await self._session.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
            .with_for_update()
            .order_by(OrganizationMember.created_at.desc())
            .limit(1)
        )
        membership = existing.scalar_one_or_none()
        if membership is not None and membership.status == ACTIVE_MEMBER:
            return membership
        if membership is not None and membership.status == "removed":
            membership.status = ACTIVE_MEMBER
            membership.role = role
            membership.removed_at = None
            membership.invited_by_user_id = invited_by_user_id
            membership.joined_at = now
            membership.updated_at = now
            await self._session.flush()
            return membership

        membership = OrganizationMember(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
            status=ACTIVE_MEMBER,
            invited_by_user_id=invited_by_user_id,
            joined_at=now,
            created_at=now,
            updated_at=now,
        )
        self._session.add(membership)
        await self._session.flush()
        return membership

    def _membership_summary(self, membership: OrganizationMember) -> dict[str, Any]:
        return {
            "organization_id": str(membership.organization_id),
            "user_id": str(membership.user_id),
            "role": membership.role,
            "status": membership.status,
            "joined_at": membership.joined_at.isoformat(),
        }
