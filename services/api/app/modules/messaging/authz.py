"""Messaging authorization. REST is authoritative (ADR 0014 / 0015)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import ConnectionGrant, Conversation, User, UserBlock


def require_private_messaging_enabled(settings: Settings) -> None:
    if not settings.ff_private_messaging:
        raise AppError(
            "FEATURE_DISABLED",
            "Private messaging is not enabled.",
            status_code=404,
        )


def canonical_pair(a: UUID, b: UUID) -> tuple[UUID, UUID]:
    return (a, b) if a < b else (b, a)


class MessagingAuthorizer:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    def assert_active_account(self, user: User) -> None:
        if user.account_status != "active" or user.deleted_at is not None:
            raise AppError(
                "ACCOUNT_INACTIVE",
                "Account is not active.",
                status_code=403,
            )
        if user.onboarding_state == "age_ineligible":
            raise AppError(
                "AGE_INELIGIBLE",
                "This account does not meet the minimum age requirement.",
                status_code=403,
            )
        if user.onboarding_state != "completed":
            raise AppError(
                "ONBOARDING_INCOMPLETE",
                "Finish onboarding before messaging.",
                status_code=403,
            )

    async def is_blocked(self, a: UUID, b: UUID) -> bool:
        result = await self._session.execute(
            text("SELECT app.is_blocked(CAST(:a AS uuid), CAST(:b AS uuid))"),
            {"a": str(a), "b": str(b)},
        )
        return bool(result.scalar())

    async def load_active_grant_for_pair(self, low: UUID, high: UUID) -> ConnectionGrant | None:
        result = await self._session.execute(
            select(ConnectionGrant)
            .where(
                ConnectionGrant.user_a_id == low,
                ConnectionGrant.user_b_id == high,
                ConnectionGrant.revoked_at.is_(None),
            )
            .order_by(ConnectionGrant.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def load_active_grant_by_id(self, grant_id: UUID) -> ConnectionGrant | None:
        grant = await self._session.get(ConnectionGrant, grant_id)
        if grant is None or grant.revoked_at is not None:
            return None
        return grant

    async def assert_can_message_pair(
        self,
        *,
        actor: User,
        other_user_id: UUID,
        now: datetime,
    ) -> ConnectionGrant:
        del now  # Reserved for future time-based safety policies.
        self.assert_active_account(actor)
        if actor.id == other_user_id:
            raise AppError(
                "CONVERSATION_SELF",
                "You cannot message yourself.",
                status_code=400,
            )
        other = await self._session.get(User, other_user_id)
        if other is None or other.deleted_at is not None:
            raise AppError("USER_NOT_FOUND", "User not found.", status_code=404)
        if other.account_status != "active":
            raise AppError(
                "PEER_ACCOUNT_INACTIVE",
                "The other account is not available for messaging.",
                status_code=403,
            )
        if other.onboarding_state != "completed":
            raise AppError(
                "PEER_ONBOARDING_INCOMPLETE",
                "The other account is not available for messaging.",
                status_code=403,
            )
        if await self.is_blocked(actor.id, other_user_id):
            raise AppError(
                "MESSAGING_BLOCKED",
                "Messaging is not allowed while a block is in place.",
                status_code=403,
            )
        self._assert_messaging_privacy(actor)
        self._assert_messaging_privacy(other)
        low, high = canonical_pair(actor.id, other_user_id)
        grant = await self.load_active_grant_for_pair(low, high)
        if grant is None:
            raise AppError(
                "CONNECTION_REQUIRED",
                "An active connection is required to message.",
                status_code=403,
            )
        return grant

    @staticmethod
    def _assert_messaging_privacy(user: User) -> None:
        privacy = user.privacy
        if privacy is None:
            raise AppError(
                "MESSAGING_DISABLED",
                "Messaging preferences are missing.",
                status_code=403,
            )
        if privacy.ghost_mode or not privacy.allow_messages_from_connections:
            raise AppError(
                "MESSAGING_DISABLED",
                "Messaging is disabled by privacy settings.",
                status_code=403,
            )

    async def assert_member(self, conversation: Conversation, user_id: UUID) -> None:
        if user_id not in {conversation.user_low_id, conversation.user_high_id}:
            raise AppError(
                "CONVERSATION_NOT_FOUND",
                "Conversation not found.",
                status_code=404,
            )

    async def other_user_id(self, conversation: Conversation, user_id: UUID) -> UUID:
        await self.assert_member(conversation, user_id)
        if conversation.user_low_id == user_id:
            return conversation.user_high_id
        return conversation.user_low_id

    async def messaging_allowed(self, *, actor: User, other_user_id: UUID, now: datetime) -> bool:
        try:
            await self.assert_can_message_pair(actor=actor, other_user_id=other_user_id, now=now)
        except AppError:
            return False
        return True

    async def find_block_between(self, a: UUID, b: UUID) -> UserBlock | None:
        result = await self._session.execute(
            select(UserBlock).where(
                or_(
                    (UserBlock.blocker_user_id == a) & (UserBlock.blocked_user_id == b),
                    (UserBlock.blocker_user_id == b) & (UserBlock.blocked_user_id == a),
                )
            )
        )
        return result.scalar_one_or_none()
