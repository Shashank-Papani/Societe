"""Phase 5 private messaging authorization and persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from calling_cards_support import CallingCardWorld, build_calling_card_world
from messaging_support import accept_connection, messaging_service, outbox_of_type
from sqlalchemy import func, select

from app.core.errors import AppError
from app.db.models import ConversationMember, Message, OutboxEvent
from app.modules.messaging.schemas import (
    CreateConversationRequest,
    MarkReadRequest,
    SendMessageRequest,
)
from app.modules.social.schemas import BlockUserRequest


@pytest.fixture
async def world(db_session, valkey, media_settings) -> CallingCardWorld:
    built = await build_calling_card_world(db_session, valkey, media_settings)
    try:
        yield built
    finally:
        await built.cleanup()


@pytest.mark.asyncio
async def test_accepted_grant_is_durable_and_survives_exit(world: CallingCardWorld) -> None:
    await accept_connection(world)
    await world.clear_leases()
    now = datetime.now(UTC)
    service = messaging_service(world)
    detail = await service.create_conversation(
        user=world.sender,
        request=CreateConversationRequest(other_user_id=world.recipient_id),
        now=now,
    )
    assert detail.messaging_allowed is True
    members = await world.session.scalars(
        select(ConversationMember).where(ConversationMember.conversation_id == detail.id)
    )
    assert len(list(members)) == 2


@pytest.mark.asyncio
async def test_duplicate_conversation_returns_same_id(world: CallingCardWorld) -> None:
    await accept_connection(world)
    now = datetime.now(UTC)
    service = messaging_service(world)
    first = await service.create_conversation(
        user=world.sender,
        request=CreateConversationRequest(other_user_id=world.recipient_id),
        now=now,
    )
    second = await service.create_conversation(
        user=world.recipient,
        request=CreateConversationRequest(other_user_id=world.sender_id),
        now=now + timedelta(seconds=1),
    )
    assert first.id == second.id


@pytest.mark.asyncio
async def test_self_conversation_rejected(world: CallingCardWorld) -> None:
    await accept_connection(world)
    service = messaging_service(world)
    with pytest.raises(AppError) as exc:
        await service.create_conversation(
            user=world.sender,
            request=CreateConversationRequest(other_user_id=world.sender_id),
            now=datetime.now(UTC),
        )
    assert exc.value.code == "CONVERSATION_SELF"


@pytest.mark.asyncio
async def test_non_connected_cannot_create(world: CallingCardWorld) -> None:
    service = messaging_service(world)
    with pytest.raises(AppError) as exc:
        await service.create_conversation(
            user=world.sender,
            request=CreateConversationRequest(other_user_id=world.recipient_id),
            now=datetime.now(UTC),
        )
    assert exc.value.code == "CONNECTION_REQUIRED"


@pytest.mark.asyncio
async def test_message_idempotency_and_no_body_in_outbox(world: CallingCardWorld) -> None:
    await accept_connection(world)
    now = datetime.now(UTC)
    service = messaging_service(world)
    conversation = await service.create_conversation(
        user=world.sender,
        request=CreateConversationRequest(other_user_id=world.recipient_id),
        now=now,
    )
    client_id = str(uuid4())
    body = "secret nightlife plan"
    first = await service.send_message(
        user=world.sender,
        conversation_id=conversation.id,
        request=SendMessageRequest(body=body, client_message_id=client_id),
        now=now,
    )
    second = await service.send_message(
        user=world.sender,
        conversation_id=conversation.id,
        request=SendMessageRequest(body=body, client_message_id=client_id),
        now=now + timedelta(seconds=1),
    )
    assert first.id == second.id
    count = await world.session.scalar(
        select(func.count()).select_from(Message).where(Message.conversation_id == conversation.id)
    )
    assert count == 1
    events = await outbox_of_type(world, "message.created")
    assert events
    for event in events:
        assert "body" not in event.payload
        assert body not in str(event.payload)


@pytest.mark.asyncio
async def test_whitespace_message_rejected(world: CallingCardWorld) -> None:
    await accept_connection(world)
    now = datetime.now(UTC)
    service = messaging_service(world)
    conversation = await service.create_conversation(
        user=world.sender,
        request=CreateConversationRequest(other_user_id=world.recipient_id),
        now=now,
    )
    with pytest.raises(AppError) as exc:
        await service.send_message(
            user=world.sender,
            conversation_id=conversation.id,
            request=SendMessageRequest(body="   \n\t  ", client_message_id=str(uuid4())),
            now=now,
        )
    assert exc.value.code == "MESSAGE_BODY_INVALID"


@pytest.mark.asyncio
async def test_block_disables_send_unblock_does_not_restore_grant(
    world: CallingCardWorld,
) -> None:
    await accept_connection(world)
    now = datetime.now(UTC)
    service = messaging_service(world)
    conversation = await service.create_conversation(
        user=world.sender,
        request=CreateConversationRequest(other_user_id=world.recipient_id),
        now=now,
    )
    await world.service().block_user(
        user=world.sender,
        blocked_user_id=world.recipient_id,
        request=BlockUserRequest(),
        now=now,
    )
    disabled = await outbox_of_type(world, "conversation.messaging_disabled")
    assert disabled
    with pytest.raises(AppError) as exc:
        await service.send_message(
            user=world.sender,
            conversation_id=conversation.id,
            request=SendMessageRequest(body="should fail", client_message_id=str(uuid4())),
            now=now + timedelta(seconds=1),
        )
    assert exc.value.code == "MESSAGING_BLOCKED"

    await world.service().unblock_user(
        user=world.sender, blocked_user_id=world.recipient_id, now=now + timedelta(seconds=2)
    )
    # Unblock must not restore prior grants — messaging stays closed until a new connection.
    with pytest.raises(AppError) as after:
        await service.send_message(
            user=world.sender,
            conversation_id=conversation.id,
            request=SendMessageRequest(body="still closed", client_message_id=str(uuid4())),
            now=now + timedelta(seconds=3),
        )
    assert after.value.code in {
        "MESSAGING_BLOCKED",
        "MESSAGING_DISABLED",
        "MESSAGING_NOT_ALLOWED",
        "CONNECTION_REVOKED",
        "CONNECTION_REQUIRED",
    }


@pytest.mark.asyncio
async def test_read_state_monotonic_and_unread(world: CallingCardWorld) -> None:
    await accept_connection(world)
    now = datetime.now(UTC)
    service = messaging_service(world)
    conversation = await service.create_conversation(
        user=world.sender,
        request=CreateConversationRequest(other_user_id=world.recipient_id),
        now=now,
    )
    m1 = await service.send_message(
        user=world.sender,
        conversation_id=conversation.id,
        request=SendMessageRequest(body="one", client_message_id=str(uuid4())),
        now=now,
    )
    m2 = await service.send_message(
        user=world.sender,
        conversation_id=conversation.id,
        request=SendMessageRequest(body="two", client_message_id=str(uuid4())),
        now=now + timedelta(seconds=1),
    )
    listed = await service.list_conversations(
        user=world.recipient,
        cursor=None,
        limit=10,
        include_archived=False,
        now=now + timedelta(seconds=2),
    )
    assert listed.items[0].unread_count == 2

    forward = await service.mark_read(
        user=world.recipient,
        conversation_id=conversation.id,
        request=MarkReadRequest(last_read_message_id=m2.id),
        now=now + timedelta(seconds=3),
    )
    assert forward.unread_count == 0
    assert forward.last_read_message_id == m2.id

    backward = await service.mark_read(
        user=world.recipient,
        conversation_id=conversation.id,
        request=MarkReadRequest(last_read_message_id=m1.id),
        now=now + timedelta(seconds=4),
    )
    assert backward.last_read_message_id == m2.id


@pytest.mark.asyncio
async def test_archive_is_per_user(world: CallingCardWorld) -> None:
    await accept_connection(world)
    now = datetime.now(UTC)
    service = messaging_service(world)
    conversation = await service.create_conversation(
        user=world.sender,
        request=CreateConversationRequest(other_user_id=world.recipient_id),
        now=now,
    )
    await service.archive(user=world.sender, conversation_id=conversation.id, now=now)
    sender_list = await service.list_conversations(
        user=world.sender, cursor=None, limit=10, include_archived=False, now=now
    )
    recipient_list = await service.list_conversations(
        user=world.recipient, cursor=None, limit=10, include_archived=False, now=now
    )
    assert sender_list.items == []
    assert len(recipient_list.items) == 1


@pytest.mark.asyncio
async def test_non_participant_cannot_read_messages(world: CallingCardWorld) -> None:
    from app.db.models import User

    await accept_connection(world)
    now = datetime.now(UTC)
    service = messaging_service(world)
    conversation = await service.create_conversation(
        user=world.sender,
        request=CreateConversationRequest(other_user_id=world.recipient_id),
        now=now,
    )
    stranger = User(
        auth_subject=f"stranger-{uuid4().hex[:8]}",
        handle=f"stranger_{uuid4().hex[:8]}",
        display_name="Stranger",
        account_status="active",
        age_verified=True,
        onboarding_state="completed",
    )
    world.session.add(stranger)
    await world.session.commit()
    with pytest.raises(AppError) as exc:
        await service.list_messages(
            user=stranger,
            conversation_id=conversation.id,
            cursor=None,
            limit=10,
            now=now,
        )
    assert exc.value.code == "CONVERSATION_NOT_FOUND"
    await world.session.delete(stranger)
    await world.session.commit()


@pytest.mark.asyncio
async def test_message_and_outbox_atomicity_identifiers_only(world: CallingCardWorld) -> None:
    await accept_connection(world)
    now = datetime.now(UTC)
    service = messaging_service(world)
    conversation = await service.create_conversation(
        user=world.sender,
        request=CreateConversationRequest(other_user_id=world.recipient_id),
        now=now,
    )
    await service.send_message(
        user=world.sender,
        conversation_id=conversation.id,
        request=SendMessageRequest(body="hello", client_message_id=str(uuid4())),
        now=now,
    )
    events = await world.session.scalars(
        select(OutboxEvent).where(OutboxEvent.event_type == "message.created")
    )
    matching = [
        event for event in events if event.payload.get("conversation_id") == str(conversation.id)
    ]
    assert matching, "expected message.created outbox for this conversation"
    event = matching[-1]
    assert event.payload["conversation_id"] == str(conversation.id)
    assert "message_id" in event.payload
    assert "preview" not in event.payload
    assert "body" not in event.payload
