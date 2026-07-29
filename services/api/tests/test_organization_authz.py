"""Phase 7A organization authorization matrix (pure unit tests)."""

from __future__ import annotations

from app.modules.organizations.authz import (
    ROLE_ANALYST,
    ROLE_CONTENT_EDITOR,
    ROLE_MANAGER,
    ROLE_OWNER,
    OrgPermission,
    can_invite_role,
    can_manage_member,
    role_has_permission,
)


def test_owner_has_all_permissions() -> None:
    for permission in OrgPermission:
        assert role_has_permission(ROLE_OWNER, permission)


def test_manager_permission_matrix() -> None:
    assert role_has_permission(ROLE_MANAGER, OrgPermission.VENUE_COVER_UPDATE)
    assert role_has_permission(ROLE_MANAGER, OrgPermission.ORGANIZATION_MEMBERS_INVITE)
    assert role_has_permission(ROLE_MANAGER, OrgPermission.VENUE_ANALYTICS_VIEW)
    assert not role_has_permission(ROLE_MANAGER, OrgPermission.ORGANIZATION_DELETE)


def test_content_editor_permission_matrix() -> None:
    assert role_has_permission(ROLE_CONTENT_EDITOR, OrgPermission.VENUE_COVER_UPDATE)
    assert role_has_permission(ROLE_CONTENT_EDITOR, OrgPermission.VENUE_MEDIA_MANAGE)
    assert not role_has_permission(ROLE_CONTENT_EDITOR, OrgPermission.ORGANIZATION_MEMBERS_INVITE)
    assert not role_has_permission(ROLE_CONTENT_EDITOR, OrgPermission.ORGANIZATION_MEMBERS_MANAGE)
    assert not role_has_permission(ROLE_CONTENT_EDITOR, OrgPermission.VENUE_PROFILE_UPDATE)


def test_analyst_permission_matrix() -> None:
    assert role_has_permission(ROLE_ANALYST, OrgPermission.VENUE_ANALYTICS_VIEW)
    assert role_has_permission(ROLE_ANALYST, OrgPermission.ORGANIZATION_VIEW)
    assert not role_has_permission(ROLE_ANALYST, OrgPermission.VENUE_COVER_UPDATE)
    assert not role_has_permission(ROLE_ANALYST, OrgPermission.ORGANIZATION_MEMBERS_INVITE)
    assert not role_has_permission(ROLE_ANALYST, OrgPermission.VENUE_MEDIA_MANAGE)


def test_invite_hierarchy() -> None:
    assert can_invite_role(inviter_role=ROLE_OWNER, invitee_role=ROLE_OWNER)
    assert can_invite_role(inviter_role=ROLE_MANAGER, invitee_role=ROLE_ANALYST)
    assert not can_invite_role(inviter_role=ROLE_MANAGER, invitee_role=ROLE_OWNER)
    assert not can_invite_role(inviter_role=ROLE_CONTENT_EDITOR, invitee_role=ROLE_ANALYST)
    assert not can_invite_role(inviter_role=ROLE_ANALYST, invitee_role=ROLE_ANALYST)


def test_manage_member_hierarchy() -> None:
    assert can_manage_member(actor_role=ROLE_OWNER, target_role=ROLE_OWNER)
    assert can_manage_member(actor_role=ROLE_MANAGER, target_role=ROLE_ANALYST)
    assert not can_manage_member(actor_role=ROLE_MANAGER, target_role=ROLE_OWNER)
    assert not can_manage_member(actor_role=ROLE_CONTENT_EDITOR, target_role=ROLE_ANALYST)
