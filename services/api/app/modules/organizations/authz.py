"""Centralized organization and venue-management authorization.

Never trust client-supplied roles. Resolve active membership + organization
status + venue linkage from the database on every permission check.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import Organization, OrganizationMember, User, VenueOrganization

ROLE_OWNER = "owner"
ROLE_MANAGER = "manager"
ROLE_CONTENT_EDITOR = "content_editor"
ROLE_ANALYST = "analyst"

ACTIVE_MEMBER = "active"
ACTIVE_ORG = "active"
ACTIVE_VENUE_LINK = "active"

ORG_ROLES = frozenset({ROLE_OWNER, ROLE_MANAGER, ROLE_CONTENT_EDITOR, ROLE_ANALYST})
INVITABLE_BY_MANAGER = frozenset({ROLE_MANAGER, ROLE_CONTENT_EDITOR, ROLE_ANALYST})


class OrgPermission(StrEnum):
    ORGANIZATION_VIEW = "organization.view"
    ORGANIZATION_MEMBERS_INVITE = "organization.members.invite"
    ORGANIZATION_MEMBERS_MANAGE = "organization.members.manage"
    ORGANIZATION_DELETE = "organization.delete"
    VENUE_PROFILE_UPDATE = "venue.profile.update"
    VENUE_COVER_UPDATE = "venue.cover.update"
    VENUE_MEDIA_MANAGE = "venue.media.manage"
    VENUE_CONTENT_PUBLISH = "venue.content.publish"
    VENUE_ANALYTICS_VIEW = "venue.analytics.view"


ROLE_PERMISSIONS: dict[str, frozenset[OrgPermission]] = {
    ROLE_OWNER: frozenset(OrgPermission),
    ROLE_MANAGER: frozenset(
        {
            OrgPermission.ORGANIZATION_VIEW,
            OrgPermission.ORGANIZATION_MEMBERS_INVITE,
            OrgPermission.ORGANIZATION_MEMBERS_MANAGE,
            OrgPermission.VENUE_PROFILE_UPDATE,
            OrgPermission.VENUE_COVER_UPDATE,
            OrgPermission.VENUE_MEDIA_MANAGE,
            OrgPermission.VENUE_CONTENT_PUBLISH,
            OrgPermission.VENUE_ANALYTICS_VIEW,
        }
    ),
    ROLE_CONTENT_EDITOR: frozenset(
        {
            OrgPermission.ORGANIZATION_VIEW,
            OrgPermission.VENUE_COVER_UPDATE,
            OrgPermission.VENUE_MEDIA_MANAGE,
            OrgPermission.VENUE_CONTENT_PUBLISH,
        }
    ),
    ROLE_ANALYST: frozenset(
        {
            OrgPermission.ORGANIZATION_VIEW,
            OrgPermission.VENUE_ANALYTICS_VIEW,
        }
    ),
}


@dataclass(frozen=True)
class OrgMembershipContext:
    organization: Organization
    membership: OrganizationMember
    role: str


def role_has_permission(role: str, permission: OrgPermission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def assert_user_account_active(user: User) -> None:
    if user.account_status != "active" or user.deleted_at is not None:
        raise AppError(
            "ACCOUNT_INACTIVE",
            "This account cannot perform organization actions.",
            status_code=403,
        )


def assert_organization_active(organization: Organization) -> None:
    if organization.status != ACTIVE_ORG or organization.deleted_at is not None:
        raise AppError(
            "ORGANIZATION_INACTIVE",
            "This organization cannot perform management actions.",
            status_code=403,
        )


def can_invite_role(*, inviter_role: str, invitee_role: str) -> bool:
    if invitee_role not in ORG_ROLES:
        return False
    if inviter_role == ROLE_OWNER:
        return True
    if inviter_role == ROLE_MANAGER:
        return invitee_role in INVITABLE_BY_MANAGER
    return False


def can_manage_member(*, actor_role: str, target_role: str) -> bool:
    """Owners manage everyone; managers manage non-owners only."""
    if actor_role == ROLE_OWNER:
        return True
    if actor_role == ROLE_MANAGER:
        return target_role != ROLE_OWNER
    return False


class OrganizationAuthorizer:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_active_membership(
        self, *, user_id: UUID, organization_id: UUID
    ) -> OrgMembershipContext:
        organization = await self._session.get(Organization, organization_id)
        if organization is None or organization.deleted_at is not None:
            raise AppError(
                "ORGANIZATION_NOT_FOUND",
                "Organization was not found.",
                status_code=404,
            )
        assert_organization_active(organization)

        result = await self._session.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
                OrganizationMember.status == ACTIVE_MEMBER,
            )
            .limit(1)
        )
        membership = result.scalar_one_or_none()
        if membership is None:
            raise AppError(
                "ORGANIZATION_FORBIDDEN",
                "You do not have access to this organization.",
                status_code=403,
            )
        return OrgMembershipContext(
            organization=organization,
            membership=membership,
            role=membership.role,
        )

    async def require_organization_permission(
        self,
        user: User,
        organization_id: UUID,
        permission: OrgPermission,
    ) -> OrgMembershipContext:
        assert_user_account_active(user)
        ctx = await self.load_active_membership(user_id=user.id, organization_id=organization_id)
        if not role_has_permission(ctx.role, permission):
            raise AppError(
                "ORGANIZATION_FORBIDDEN",
                "You do not have permission for this action.",
                status_code=403,
                details={"permission": permission.value},
            )
        return ctx

    async def require_venue_permission(
        self,
        user: User,
        venue_id: UUID,
        permission: OrgPermission,
    ) -> OrgMembershipContext:
        assert_user_account_active(user)
        link = await self._session.execute(
            select(VenueOrganization)
            .where(
                VenueOrganization.venue_id == venue_id,
                VenueOrganization.status == ACTIVE_VENUE_LINK,
            )
            .limit(1)
        )
        venue_org = link.scalar_one_or_none()
        if venue_org is None:
            raise AppError(
                "VENUE_NOT_MANAGED",
                "This venue is not linked to a managing organization.",
                status_code=403,
            )
        return await self.require_organization_permission(
            user, venue_org.organization_id, permission
        )
