"""Private messaging service.

REST is authoritative. Outbox rows never carry message bodies (ADR privacy).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import DateTime, and_, func, literal, or_, select, tuple_
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import (
    ConnectionGrant,
    Conversation,
    ConversationMember,
    Message,
    OutboxEvent,
    User,
)
from app.modules.messaging.authz import (
    MessagingAuthorizer,
    canonical_pair,
    require_private_messaging_enabled,
)
from app.modules.messaging.rates import MessageRateLimiter
from app.modules.messaging.schemas import (
    ArchiveResponse,
    ConversationDetail,
    ConversationListResponse,
    ConversationSummary,
    CreateConversationRequest,
    MarkReadRequest,
    MarkReadResponse,
    MessageListResponse,
    MessageSummary,
    ParticipantSummary,
    SendMessageRequest,
)
from app.shared.cursors import keyset_fingerprint, sign_keyset_cursor, verify_keyset_cursor

logger = get_logger(__name__)

LIST_NAME = "conversations"
MESSAGES_NAME = "messages"


class MessagingService:
    def __init__(self, session: AsyncSession, redis: Redis[str], settings: Settings) -> None:
        self._session = session
        self._redis = redis
        self._settings = settings
        self._authz = MessagingAuthorizer(session, settings)
        self._rates = MessageRateLimiter(redis, settings)

    async def create_conversation(
        self,
        *,
        user: User,
        request: CreateConversationRequest,
        now: datetime,
    ) -> ConversationDetail:
        require_private_messaging_enabled(self._settings)
        self._authz.assert_active_account(user)

        if request.connection_grant_id is not None:
            grant = await self._authz.load_active_grant_by_id(request.connection_grant_id)
            if grant is None:
                raise AppError(
                    "CONNECTION_REQUIRED",
                    "An active connection is required to message.",
                    status_code=403,
                )
            if user.id not in {grant.user_a_id, grant.user_b_id}:
                raise AppError(
                    "CONNECTION_REQUIRED",
                    "An active connection is required to message.",
                    status_code=403,
                )
            other_id = grant.user_b_id if grant.user_a_id == user.id else grant.user_a_id
            grant = await self._authz.assert_can_message_pair(
                actor=user, other_user_id=other_id, now=now
            )
        else:
            assert request.other_user_id is not None
            grant = await self._authz.assert_can_message_pair(
                actor=user, other_user_id=request.other_user_id, now=now
            )

        low, high = canonical_pair(grant.user_a_id, grant.user_b_id)
        existing = await self._load_conversation_for_pair(low, high)
        if existing is not None:
            if existing.revoked_at is not None:
                existing.revoked_at = None
                existing.revoked_reason = None
                existing.updated_at = now
                await self._session.commit()
            return await self._detail(existing, viewer=user, now=now)

        conversation = Conversation(
            user_low_id=low,
            user_high_id=high,
            originating_connection_grant_id=grant.id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(conversation)
        await self._session.flush()

        member_a = ConversationMember(
            conversation_id=conversation.id,
            user_id=low,
            created_at=now,
            updated_at=now,
        )
        member_b = ConversationMember(
            conversation_id=conversation.id,
            user_id=high,
            created_at=now,
            updated_at=now,
        )
        self._session.add(member_a)
        self._session.add(member_b)
        await self._session.flush()

        member_count = await self._session.scalar(
            select(func.count())
            .select_from(ConversationMember)
            .where(ConversationMember.conversation_id == conversation.id)
        )
        if int(member_count or 0) != 2:
            raise AppError(
                "CONVERSATION_MEMBERSHIP_INVALID",
                "Conversation must have exactly two members.",
                status_code=500,
            )

        self._emit(
            aggregate_type="conversation",
            aggregate_id=conversation.id,
            event_type="conversation.created",
            occurred_at=now,
            recipient_user_ids=[low, high],
            payload={
                "conversation_id": str(conversation.id),
                "user_low_id": str(low),
                "user_high_id": str(high),
            },
        )
        await self._session.commit()
        return await self._detail(conversation, viewer=user, now=now)

    async def list_conversations(
        self,
        *,
        user: User,
        cursor: str | None,
        limit: int,
        include_archived: bool,
        now: datetime,
    ) -> ConversationListResponse:
        require_private_messaging_enabled(self._settings)
        self._authz.assert_active_account(user)
        page_size = min(max(limit, 1), self._settings.conversation_list_page_max)
        qfp = keyset_fingerprint(
            list=LIST_NAME, user_id=str(user.id), include_archived=include_archived
        )

        stmt = (
            select(Conversation, ConversationMember)
            .join(
                ConversationMember,
                and_(
                    ConversationMember.conversation_id == Conversation.id,
                    ConversationMember.user_id == user.id,
                ),
            )
            .order_by(
                Conversation.last_message_at.desc().nulls_last(),
                Conversation.id.desc(),
            )
            .limit(page_size + 1)
        )
        if not include_archived:
            stmt = stmt.where(ConversationMember.archived_at.is_(None))
        if cursor:
            payload = verify_keyset_cursor(
                cursor=cursor,
                expected_qfp=qfp,
                secret=self._settings.cursor_hmac_secret.get_secret_value(),
            )
            sort_raw = payload["sk"]
            if sort_raw in {"", "null"}:
                stmt = stmt.where(
                    Conversation.last_message_at.is_(None),
                    Conversation.id < UUID(str(payload["id"])),
                )
            else:
                stmt = stmt.where(
                    tuple_(Conversation.last_message_at, Conversation.id)
                    < tuple_(
                        literal(datetime.fromisoformat(str(sort_raw)), DateTime(timezone=True)),
                        literal(UUID(str(payload["id"])), PostgresUUID(as_uuid=True)),
                    )
                )

        rows = list((await self._session.execute(stmt)).all())
        page = rows[:page_size]
        items: list[ConversationSummary] = []
        for conversation, member in page:
            items.append(await self._summary(conversation, member=member, viewer=user, now=now))

        next_cursor: str | None = None
        if len(rows) > page_size and page:
            last_conv, _ = page[-1]
            sk = (
                last_conv.last_message_at.isoformat()
                if last_conv.last_message_at is not None
                else "null"
            )
            next_cursor = sign_keyset_cursor(
                sort_key=sk,
                item_id=str(last_conv.id),
                qfp=qfp,
                secret=self._settings.cursor_hmac_secret.get_secret_value(),
            )
        return ConversationListResponse(items=items, next_cursor=next_cursor)

    async def get_conversation(
        self, *, user: User, conversation_id: UUID, now: datetime
    ) -> ConversationDetail:
        require_private_messaging_enabled(self._settings)
        self._authz.assert_active_account(user)
        conversation = await self._load_visible_conversation(user.id, conversation_id)
        return await self._detail(conversation, viewer=user, now=now)

    async def list_messages(
        self,
        *,
        user: User,
        conversation_id: UUID,
        cursor: str | None,
        limit: int,
        now: datetime,
    ) -> MessageListResponse:
        require_private_messaging_enabled(self._settings)
        self._authz.assert_active_account(user)
        conversation = await self._load_visible_conversation(user.id, conversation_id)
        del conversation
        page_size = min(max(limit, 1), self._settings.message_list_page_max)
        qfp = keyset_fingerprint(
            list=MESSAGES_NAME, conversation_id=str(conversation_id), user_id=str(user.id)
        )

        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(page_size + 1)
        )
        if cursor:
            payload = verify_keyset_cursor(
                cursor=cursor,
                expected_qfp=qfp,
                secret=self._settings.cursor_hmac_secret.get_secret_value(),
            )
            stmt = stmt.where(
                tuple_(Message.created_at, Message.id)
                < tuple_(
                    literal(
                        datetime.fromisoformat(str(payload["sk"])),
                        DateTime(timezone=True),
                    ),
                    literal(UUID(str(payload["id"])), PostgresUUID(as_uuid=True)),
                )
            )

        rows = list((await self._session.execute(stmt)).scalars().all())
        page = rows[:page_size]
        items = [self._message_summary(m) for m in page]
        next_cursor: str | None = None
        if len(rows) > page_size and page:
            last = page[-1]
            next_cursor = sign_keyset_cursor(
                sort_key=last.created_at.isoformat(),
                item_id=str(last.id),
                qfp=qfp,
                secret=self._settings.cursor_hmac_secret.get_secret_value(),
            )
        return MessageListResponse(items=items, next_cursor=next_cursor)

    async def send_message(
        self,
        *,
        user: User,
        conversation_id: UUID,
        request: SendMessageRequest,
        now: datetime,
    ) -> MessageSummary:
        require_private_messaging_enabled(self._settings)
        self._authz.assert_active_account(user)

        existing = await self._load_by_client_message_id(user.id, request.client_message_id)
        if existing is not None:
            if existing.conversation_id != conversation_id:
                raise AppError(
                    "MESSAGE_IDEMPOTENCY_CONFLICT",
                    "client_message_id was already used in another conversation.",
                    status_code=409,
                )
            return self._message_summary(existing)

        body = request.body.strip()
        if not body:
            raise AppError(
                "MESSAGE_BODY_INVALID",
                "Message body cannot be empty.",
                status_code=422,
            )
        if len(body) > self._settings.message_body_max_length:
            raise AppError(
                "MESSAGE_BODY_TOO_LONG",
                "Message body exceeds the maximum length.",
                status_code=422,
                details={"max_length": self._settings.message_body_max_length},
            )

        conversation = await self._load_visible_conversation(user.id, conversation_id)
        other_id = await self._authz.other_user_id(conversation, user.id)
        await self._authz.assert_can_message_pair(actor=user, other_user_id=other_id, now=now)
        if conversation.revoked_at is not None:
            conversation.revoked_at = None
            conversation.revoked_reason = None

        await self._rates.check_send(user_id=user.id, now=now)

        message = Message(
            conversation_id=conversation.id,
            sender_user_id=user.id,
            client_message_id=request.client_message_id,
            body=body,
            status="sent",
            created_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(message)
                await self._session.flush()
        except IntegrityError:
            raced = await self._load_by_client_message_id(user.id, request.client_message_id)
            if raced is not None:
                return self._message_summary(raced)
            raise

        conversation.last_message_at = now
        conversation.updated_at = now

        other_member = await self._load_member(conversation.id, other_id)
        if other_member is not None:
            other_member.unread_count = int(other_member.unread_count or 0) + 1
            other_member.updated_at = now

        sender_member = await self._load_member(conversation.id, user.id)
        if sender_member is not None:
            sender_member.last_read_message_id = message.id
            sender_member.last_read_at = now
            sender_member.unread_count = 0
            sender_member.updated_at = now

        # Identifiers only — never put body in outbox / realtime / push.
        self._emit(
            aggregate_type="message",
            aggregate_id=message.id,
            event_type="message.created",
            occurred_at=now,
            recipient_user_ids=[user.id, other_id],
            payload={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "sender_user_id": str(user.id),
                "created_at": now.isoformat(),
            },
        )
        await self._session.commit()
        logger.info(
            "message_sent",
            conversation_id=str(conversation.id),
            message_id=str(message.id),
            sender_user_id=str(user.id),
        )
        return self._message_summary(message)

    async def mark_read(
        self,
        *,
        user: User,
        conversation_id: UUID,
        request: MarkReadRequest,
        now: datetime,
    ) -> MarkReadResponse:
        require_private_messaging_enabled(self._settings)
        self._authz.assert_active_account(user)
        conversation = await self._load_visible_conversation(user.id, conversation_id)
        member = await self._load_member(conversation.id, user.id)
        if member is None:
            raise AppError("CONVERSATION_NOT_FOUND", "Conversation not found.", status_code=404)

        target_id = request.last_read_message_id
        if target_id is None:
            latest = await self._session.scalar(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )
            if latest is None:
                return MarkReadResponse(
                    conversation_id=conversation.id,
                    last_read_message_id=member.last_read_message_id,
                    last_read_at=member.last_read_at,
                    unread_count=int(member.unread_count or 0),
                )
            target_id = latest.id

        target = await self._session.get(Message, target_id)
        if target is None or target.conversation_id != conversation.id:
            raise AppError(
                "MESSAGE_NOT_FOUND",
                "Message not found in this conversation.",
                status_code=404,
            )

        if member.last_read_message_id is not None:
            current = await self._session.get(Message, member.last_read_message_id)
            if current is not None and self._message_order_key(target) <= self._message_order_key(
                current
            ):
                return MarkReadResponse(
                    conversation_id=conversation.id,
                    last_read_message_id=member.last_read_message_id,
                    last_read_at=member.last_read_at,
                    unread_count=int(member.unread_count or 0),
                )

        member.last_read_message_id = target.id
        member.last_read_at = now
        member.unread_count = await self._count_unread_after(conversation.id, user.id, target)
        member.updated_at = now

        other_id = await self._authz.other_user_id(conversation, user.id)
        self._emit(
            aggregate_type="conversation",
            aggregate_id=conversation.id,
            event_type="message.read",
            occurred_at=now,
            recipient_user_ids=[user.id, other_id],
            payload={
                "conversation_id": str(conversation.id),
                "reader_user_id": str(user.id),
                "last_read_message_id": str(target.id),
                "read_at": now.isoformat(),
            },
        )
        await self._session.commit()
        return MarkReadResponse(
            conversation_id=conversation.id,
            last_read_message_id=member.last_read_message_id,
            last_read_at=member.last_read_at,
            unread_count=int(member.unread_count or 0),
        )

    async def archive(self, *, user: User, conversation_id: UUID, now: datetime) -> ArchiveResponse:
        require_private_messaging_enabled(self._settings)
        self._authz.assert_active_account(user)
        conversation = await self._load_visible_conversation(user.id, conversation_id)
        member = await self._load_member(conversation.id, user.id)
        if member is None:
            raise AppError("CONVERSATION_NOT_FOUND", "Conversation not found.", status_code=404)
        if member.archived_at is None:
            member.archived_at = now
            member.updated_at = now
            other_id = await self._authz.other_user_id(conversation, user.id)
            self._emit(
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="conversation.archived",
                occurred_at=now,
                recipient_user_ids=[user.id, other_id],
                payload={
                    "conversation_id": str(conversation.id),
                    "actor_user_id": str(user.id),
                },
            )
            await self._session.commit()
        return ArchiveResponse(conversation_id=conversation.id, archived_at=member.archived_at)

    async def unarchive(
        self, *, user: User, conversation_id: UUID, now: datetime
    ) -> ArchiveResponse:
        require_private_messaging_enabled(self._settings)
        self._authz.assert_active_account(user)
        conversation = await self._load_visible_conversation(user.id, conversation_id)
        member = await self._load_member(conversation.id, user.id)
        if member is None:
            raise AppError("CONVERSATION_NOT_FOUND", "Conversation not found.", status_code=404)
        if member.archived_at is not None:
            member.archived_at = None
            member.updated_at = now
            await self._session.commit()
        return ArchiveResponse(conversation_id=conversation.id, archived_at=None)

    async def emit_messaging_disabled_for_pair(
        self, a: UUID, b: UUID, *, now: datetime, reason: str
    ) -> None:
        low, high = canonical_pair(a, b)
        conversation = await self._load_conversation_for_pair(low, high)
        if conversation is None:
            return
        self._emit(
            aggregate_type="conversation",
            aggregate_id=conversation.id,
            event_type="conversation.messaging_disabled",
            occurred_at=now,
            recipient_user_ids=[low, high],
            payload={
                "conversation_id": str(conversation.id),
                "reason": reason,
            },
        )

    async def emit_messaging_enabled_for_pair(
        self, a: UUID, b: UUID, *, now: datetime, reason: str
    ) -> None:
        low, high = canonical_pair(a, b)
        conversation = await self._load_conversation_for_pair(low, high)
        if conversation is None:
            return
        if conversation.revoked_at is not None:
            conversation.revoked_at = None
            conversation.revoked_reason = None
            conversation.updated_at = now
        self._emit(
            aggregate_type="conversation",
            aggregate_id=conversation.id,
            event_type="conversation.messaging_enabled",
            occurred_at=now,
            recipient_user_ids=[low, high],
            payload={
                "conversation_id": str(conversation.id),
                "reason": reason,
            },
        )

    async def _count_unread_after(
        self, conversation_id: UUID, reader_id: UUID, watermark: Message
    ) -> int:
        result = await self._session.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.sender_user_id != reader_id,
                or_(
                    Message.created_at > watermark.created_at,
                    and_(
                        Message.created_at == watermark.created_at,
                        Message.id > watermark.id,
                    ),
                ),
            )
        )
        return int(result or 0)

    @staticmethod
    def _message_order_key(message: Message) -> tuple[datetime, UUID]:
        return (message.created_at, message.id)

    async def _load_by_client_message_id(
        self, sender_id: UUID, client_message_id: str
    ) -> Message | None:
        result = await self._session.execute(
            select(Message).where(
                Message.sender_user_id == sender_id,
                Message.client_message_id == client_message_id,
            )
        )
        return result.scalar_one_or_none()

    async def _load_conversation_for_pair(self, low: UUID, high: UUID) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.user_low_id == low,
                Conversation.user_high_id == high,
            )
        )
        return result.scalar_one_or_none()

    async def _load_visible_conversation(
        self, user_id: UUID, conversation_id: UUID
    ) -> Conversation:
        conversation = await self._session.get(Conversation, conversation_id)
        if conversation is None:
            raise AppError("CONVERSATION_NOT_FOUND", "Conversation not found.", status_code=404)
        await self._authz.assert_member(conversation, user_id)
        return conversation

    async def _load_member(self, conversation_id: UUID, user_id: UUID) -> ConversationMember | None:
        return await self._session.get(ConversationMember, (conversation_id, user_id))

    async def _summary(
        self,
        conversation: Conversation,
        *,
        member: ConversationMember,
        viewer: User,
        now: datetime,
    ) -> ConversationSummary:
        other_id = await self._authz.other_user_id(conversation, viewer.id)
        other = await self._session.get(User, other_id)
        allowed = await self._authz.messaging_allowed(actor=viewer, other_user_id=other_id, now=now)
        preview = await self._last_message_preview(conversation.id)
        return ConversationSummary(
            id=conversation.id,
            other_participant=self._participant(other, other_id),
            last_message_preview=preview,
            last_message_at=conversation.last_message_at,
            unread_count=int(member.unread_count or 0),
            archived_at=member.archived_at,
            messaging_allowed=allowed,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )

    async def _detail(
        self, conversation: Conversation, *, viewer: User, now: datetime
    ) -> ConversationDetail:
        member = await self._load_member(conversation.id, viewer.id)
        if member is None:
            raise AppError("CONVERSATION_NOT_FOUND", "Conversation not found.", status_code=404)
        other_id = await self._authz.other_user_id(conversation, viewer.id)
        other = await self._session.get(User, other_id)
        allowed = await self._authz.messaging_allowed(actor=viewer, other_user_id=other_id, now=now)
        return ConversationDetail(
            id=conversation.id,
            other_participant=self._participant(other, other_id),
            originating_connection_grant_id=conversation.originating_connection_grant_id,
            unread_count=int(member.unread_count or 0),
            archived_at=member.archived_at,
            messaging_allowed=allowed,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            last_message_at=conversation.last_message_at,
        )

    async def _last_message_preview(self, conversation_id: UUID) -> str | None:
        message = await self._session.scalar(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        if message is None:
            return None
        if message.status == "deleted":
            return None
        # Preview only for authenticated REST responses — never for outbox.
        text = message.body.strip()
        if len(text) > 120:
            return f"{text[:117]}..."
        return text

    @staticmethod
    def _participant(user: User | None, user_id: UUID) -> ParticipantSummary:
        if user is None:
            return ParticipantSummary(user_id=user_id)
        return ParticipantSummary(
            user_id=user_id,
            handle=user.handle,
            display_name=user.display_name,
        )

    @staticmethod
    def _message_summary(message: Message) -> MessageSummary:
        deleted = message.status == "deleted" or message.deleted_at is not None
        return MessageSummary(
            id=message.id,
            conversation_id=message.conversation_id,
            sender_user_id=message.sender_user_id,
            client_message_id=message.client_message_id,
            body=None if deleted else message.body,
            status="deleted" if deleted else "sent",
            created_at=message.created_at,
            edited_at=message.edited_at,
            deleted_at=message.deleted_at,
        )

    def _emit(
        self,
        *,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        occurred_at: datetime,
        recipient_user_ids: list[UUID],
        payload: dict[str, object],
    ) -> None:
        envelope = {
            **payload,
            "recipient_user_ids": [str(uid) for uid in recipient_user_ids],
        }
        self._session.add(
            OutboxEvent(
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                payload=envelope,
                occurred_at=occurred_at,
                available_at=occurred_at,
            )
        )


async def find_active_grant_for_users(
    session: AsyncSession, a: UUID, b: UUID
) -> ConnectionGrant | None:
    low, high = canonical_pair(a, b)
    result = await session.execute(
        select(ConnectionGrant).where(
            ConnectionGrant.user_a_id == low,
            ConnectionGrant.user_b_id == high,
            ConnectionGrant.revoked_at.is_(None),
        )
    )
    return result.scalar_one_or_none()
