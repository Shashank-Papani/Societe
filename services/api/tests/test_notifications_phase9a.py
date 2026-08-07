"""Phase 9A notification inbox, preferences, projection, push, and realtime."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from calling_cards_support import CallingCardWorld, build_calling_card_world
from messaging_support import accept_connection, messaging_service
from notifications_support import (
    deliveries_for,
    ensure_device,
    notification_service,
    notifications_for,
    project_pending,
)
from organization_support import auth_headers, me
from sqlalchemy import func, select, text

from app.core.errors import AppError
from app.db.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    OutboxEvent,
)
from app.modules.messaging.schemas import CreateConversationRequest, SendMessageRequest
from app.modules.notifications.constants import NOTIFICATION_CATEGORIES
from app.modules.notifications.push import (
    FakePushProvider,
    claim_deliveries,
    hash_push_token,
    process_delivery,
)
from app.modules.notifications.schemas import PreferencePatchItem, PreferencePatchRequest
from app.modules.notifications.tickets import (
    consume_realtime_ticket,
    create_realtime_ticket,
)
from app.modules.social.schemas import (
    BlockUserRequest,
    CreateCallingCardRequest,
    RespondCallingCardRequest,
)


@pytest.fixture
async def world(db_session, valkey, media_settings) -> CallingCardWorld:
    built = await build_calling_card_world(db_session, valkey, media_settings)
    try:
        yield built
    finally:
        await built.cleanup()


# --- migration ---
@pytest.mark.asyncio
async def test_migration_tables_exist(db_session) -> None:
    for table in (
        "notifications",
        "notification_preferences",
        "notification_deliveries",
        "notification_event_consumptions",
    ):
        exists = await db_session.scalar(
            text("SELECT to_regclass(:name)"), {"name": f"app.{table}"}
        )
        assert exists is not None


# --- inbox ---
@pytest.mark.asyncio
async def test_recipient_sees_own_notification_only(world: CallingCardWorld) -> None:
    await world.grant_both_verified()
    social = world.service()
    now = datetime.now(UTC)
    await social.create_calling_card(
        user=world.sender,
        request=CreateCallingCardRequest(
            recipient_user_id=world.recipient_id, reason_code="say_hello"
        ),
        idempotency_key=str(uuid4()),
        now=now,
    )
    await project_pending(world, event_types={"calling_card.created"})

    svc = notification_service(world)
    mine = await svc.list_notifications(
        user=world.recipient, cursor=None, limit=20, unread_only=False, category=None, now=now
    )
    assert len(mine.items) == 1
    assert mine.items[0].notification_type == "calling_card.received"

    other = await svc.list_notifications(
        user=world.sender, cursor=None, limit=20, unread_only=False, category=None, now=now
    )
    assert other.items == []


@pytest.mark.asyncio
async def test_inbox_filters_pagination_dismiss_read(world: CallingCardWorld) -> None:
    now = datetime.now(UTC)
    svc = notification_service(world)
    rows = []
    for i in range(3):
        row = Notification(
            recipient_user_id=world.recipient_id,
            notification_type="system.account_notice",
            title=f"Notice {i}",
            body=f"Body {i}",
            dedupe_key=f"system.account_notice:{world.recipient_id}:{i}",
            occurrence_count=1,
            priority="normal",
            latest_event_at=now + timedelta(seconds=i),
            created_at=now,
            updated_at=now,
        )
        world.session.add(row)
        rows.append(row)
    expired = Notification(
        recipient_user_id=world.recipient_id,
        notification_type="system.account_notice",
        title="Expired",
        body="Expired",
        dedupe_key=f"system.account_notice:{world.recipient_id}:expired",
        occurrence_count=1,
        priority="normal",
        expires_at=now - timedelta(minutes=1),
        latest_event_at=now + timedelta(seconds=10),
        created_at=now,
        updated_at=now,
    )
    world.session.add(expired)
    await world.session.commit()

    page1 = await svc.list_notifications(
        user=world.recipient, cursor=None, limit=2, unread_only=False, category=None, now=now
    )
    assert len(page1.items) == 2
    assert page1.next_cursor is not None
    page2 = await svc.list_notifications(
        user=world.recipient,
        cursor=page1.next_cursor,
        limit=2,
        unread_only=False,
        category=None,
        now=now,
    )
    assert len(page2.items) == 1
    assert all(i.title != "Expired" for i in page1.items + page2.items)

    cat = await svc.list_notifications(
        user=world.recipient,
        cursor=None,
        limit=20,
        unread_only=False,
        category="account",
        now=now,
    )
    assert len(cat.items) == 3

    target = rows[0]
    await world.session.refresh(target)
    await svc.mark_read(user=world.recipient, notification_id=target.id, now=now)
    again = await svc.mark_read(user=world.recipient, notification_id=target.id, now=now)
    assert again.read is True

    unread = await svc.list_notifications(
        user=world.recipient, cursor=None, limit=20, unread_only=True, category=None, now=now
    )
    assert all(not i.read for i in unread.items)
    assert target.id not in {i.notification_id for i in unread.items}

    read_all = await svc.mark_read_all(user=world.recipient, category="account", now=now)
    assert read_all.changed_count >= 1
    read_all2 = await svc.mark_read_all(user=world.recipient, category="account", now=now)
    assert read_all2.changed_count == 0

    dismissed = await svc.dismiss(user=world.recipient, notification_id=rows[1].id, now=now)
    assert dismissed.dismissed is True
    await svc.dismiss(user=world.recipient, notification_id=rows[1].id, now=now)
    inbox = await svc.list_notifications(
        user=world.recipient, cursor=None, limit=20, unread_only=False, category=None, now=now
    )
    assert rows[1].id not in {i.notification_id for i in inbox.items}


@pytest.mark.asyncio
async def test_cannot_read_other_users_notification(world: CallingCardWorld) -> None:
    now = datetime.now(UTC)
    row = Notification(
        recipient_user_id=world.recipient_id,
        notification_type="system.account_notice",
        title="Private",
        body="Private",
        dedupe_key=f"system.account_notice:{world.recipient_id}:private:{uuid4()}",
        occurrence_count=1,
        priority="normal",
        latest_event_at=now,
        created_at=now,
        updated_at=now,
    )
    world.session.add(row)
    await world.session.commit()
    svc = notification_service(world)
    with pytest.raises(AppError) as exc:
        await svc.mark_read(user=world.sender, notification_id=row.id, now=now)
    assert exc.value.code == "NOTIFICATION_NOT_FOUND"
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cannot_dismiss_other_users_notification(world: CallingCardWorld) -> None:
    now = datetime.now(UTC)
    row = Notification(
        recipient_user_id=world.recipient_id,
        notification_type="system.account_notice",
        title="Private dismiss",
        body="Private dismiss",
        dedupe_key=f"system.account_notice:{world.recipient_id}:dismiss:{uuid4()}",
        occurrence_count=1,
        priority="normal",
        latest_event_at=now,
        created_at=now,
        updated_at=now,
    )
    world.session.add(row)
    await world.session.commit()
    svc = notification_service(world)
    with pytest.raises(AppError) as exc:
        await svc.dismiss(user=world.sender, notification_id=row.id, now=now)
    assert exc.value.code == "NOTIFICATION_NOT_FOUND"
    assert exc.value.status_code == 404
    await world.session.refresh(row)
    assert row.dismissed_at is None


@pytest.mark.asyncio
async def test_http_cannot_read_or_dismiss_other_users_notification(
    world: CallingCardWorld, client
) -> None:
    from app.core.security import create_access_token

    now = datetime.now(UTC)
    row = Notification(
        recipient_user_id=world.recipient_id,
        notification_type="system.account_notice",
        title="HTTP private",
        body="HTTP private",
        dedupe_key=f"system.account_notice:{world.recipient_id}:http-iso:{uuid4()}",
        occurrence_count=1,
        priority="normal",
        latest_event_at=now,
        created_at=now,
        updated_at=now,
    )
    world.session.add(row)
    await world.session.commit()

    sender_token = create_access_token(
        subject=world.sender.auth_subject,
        handle=world.sender.handle,
        settings=world.settings,
    )
    headers = {"Authorization": f"Bearer {sender_token}"}
    read_resp = client.post(f"/v1/notifications/{row.id}/read", headers=headers)
    assert read_resp.status_code == 404
    assert read_resp.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"

    dismiss_resp = client.delete(f"/v1/notifications/{row.id}", headers=headers)
    assert dismiss_resp.status_code == 404
    assert dismiss_resp.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"


# --- preferences ---
@pytest.mark.asyncio
async def test_preferences_defaults_and_patch(world: CallingCardWorld) -> None:
    svc = notification_service(world)
    prefs = await svc.get_preferences(user=world.recipient)
    assert {i.category for i in prefs.items} == set(NOTIFICATION_CATEGORIES)

    with pytest.raises(AppError) as exc:
        await svc.patch_preferences(
            user=world.recipient,
            body=PreferencePatchRequest(
                items=[PreferencePatchItem(category="marketing", push_enabled=False)]
            ),
            now=datetime.now(UTC),
        )
    assert exc.value.code == "NOTIFICATION_CATEGORY_INVALID"

    updated = await svc.patch_preferences(
        user=world.recipient,
        body=PreferencePatchRequest(
            items=[
                PreferencePatchItem(category="messages", push_enabled=False, in_app_enabled=True)
            ]
        ),
        now=datetime.now(UTC),
    )
    messages = next(i for i in updated.items if i.category == "messages")
    assert messages.push_enabled is False
    assert messages.in_app_enabled is True

    with pytest.raises(AppError):
        await svc.patch_preferences(
            user=world.recipient,
            body=PreferencePatchRequest(
                items=[PreferencePatchItem(category="account", in_app_enabled=False)]
            ),
            now=datetime.now(UTC),
        )


# --- projection + coalescing ---
@pytest.mark.asyncio
async def test_calling_card_projection_idempotent_and_accept(world: CallingCardWorld) -> None:
    await world.grant_both_verified()
    social = world.service()
    now = datetime.now(UTC)
    created = await social.create_calling_card(
        user=world.sender,
        request=CreateCallingCardRequest(
            recipient_user_id=world.recipient_id, reason_code="say_hello"
        ),
        idempotency_key=str(uuid4()),
        now=now,
    )
    await project_pending(world, event_types={"calling_card.created"})
    first = await notifications_for(world.session, world.recipient_id)
    assert len(first) == 1

    # Replay same outbox event consumption path.
    event = (
        await world.session.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.event_type == "calling_card.created",
                OutboxEvent.aggregate_id == created.id,
            )
            .limit(1)
        )
    ).scalar_one()
    event.published_at = None
    await world.session.commit()
    await project_pending(world, event_types={"calling_card.created"})
    again = await notifications_for(world.session, world.recipient_id)
    assert len([n for n in again if n.notification_type == "calling_card.received"]) == 1

    await social.respond(
        user=world.recipient,
        calling_card_id=created.id,
        request=RespondCallingCardRequest(decision="accept", action="accept_only"),
        now=now + timedelta(seconds=1),
    )
    await project_pending(world, event_types={"calling_card.accepted"})
    sender_notes = await notifications_for(world.session, world.sender_id)
    assert any(n.notification_type == "calling_card.accepted" for n in sender_notes)


@pytest.mark.asyncio
async def test_message_coalesce_and_block(world: CallingCardWorld) -> None:
    await accept_connection(world)
    now = datetime.now(UTC)
    ms = messaging_service(world)
    conv = await ms.create_conversation(
        user=world.sender,
        request=CreateConversationRequest(other_user_id=world.recipient_id),
        now=now,
    )
    for i in range(3):
        await ms.send_message(
            user=world.sender,
            conversation_id=conv.id,
            request=SendMessageRequest(
                client_message_id=str(uuid4()), body=f"hello {i} secret body"
            ),
            now=now + timedelta(seconds=i),
        )
    await project_pending(world, event_types={"message.created"})
    notes = [
        n
        for n in await notifications_for(world.session, world.recipient_id)
        if n.notification_type == "message.received"
    ]
    assert len(notes) == 1
    assert notes[0].occurrence_count == 3
    assert "secret" not in notes[0].body
    assert "3 new messages" in notes[0].title

    # Sender never notified.
    sender_msg = [
        n
        for n in await notifications_for(world.session, world.sender_id)
        if n.notification_type == "message.received"
    ]
    assert sender_msg == []

    # Read then new message reopens unread.
    svc = notification_service(world)
    await svc.mark_read(user=world.recipient, notification_id=notes[0].id, now=now)
    await ms.send_message(
        user=world.sender,
        conversation_id=conv.id,
        request=SendMessageRequest(client_message_id=str(uuid4()), body="again"),
        now=now + timedelta(seconds=10),
    )
    await project_pending(world, event_types={"message.created"})
    await world.session.refresh(notes[0])
    assert notes[0].read_at is None
    assert notes[0].occurrence_count == 4

    # Block stops future notifications.
    await world.service().block_user(
        user=world.recipient,
        blocked_user_id=world.sender_id,
        request=BlockUserRequest(),
        now=now + timedelta(seconds=20),
    )
    before = notes[0].occurrence_count
    # Messaging should reject or projector should skip; either way count stays put.
    try:
        await ms.send_message(
            user=world.sender,
            conversation_id=conv.id,
            request=SendMessageRequest(client_message_id=str(uuid4()), body="blocked"),
            now=now + timedelta(seconds=30),
        )
    except AppError:
        pass
    await project_pending(world, event_types={"message.created"})
    await world.session.refresh(notes[0])
    assert notes[0].occurrence_count == before


@pytest.mark.asyncio
async def test_concurrent_message_coalesce_one_row(world: CallingCardWorld) -> None:
    await accept_connection(world)
    now = datetime.now(UTC)
    ms = messaging_service(world)
    conv = await ms.create_conversation(
        user=world.sender,
        request=CreateConversationRequest(other_user_id=world.recipient_id),
        now=now,
    )
    for i in range(2):
        await ms.send_message(
            user=world.sender,
            conversation_id=conv.id,
            request=SendMessageRequest(client_message_id=str(uuid4()), body=f"c{i}"),
            now=now + timedelta(milliseconds=i),
        )
    events = list(
        (
            await world.session.execute(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == "message.created",
                    OutboxEvent.payload["conversation_id"].as_string() == str(conv.id),
                )
            )
        ).scalars()
    )
    assert len(events) >= 2
    event_ids = [e.id for e in events]

    async def _one(event_id) -> None:
        from app.db.session import get_session_factory
        from app.modules.notifications.projector import project_outbox_event

        factory = get_session_factory(world.settings)
        async with factory() as session:
            event = await session.get(OutboxEvent, event_id)
            assert event is not None
            await project_outbox_event(
                session, event, redis=world.redis, settings=world.settings, now=now
            )
            await session.commit()

    await asyncio.gather(*[_one(eid) for eid in event_ids])
    world.session.expire_all()
    count = await world.session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.recipient_user_id == world.recipient_id,
            Notification.notification_type == "message.received",
            Notification.conversation_id == conv.id,
            Notification.dismissed_at.is_(None),
        )
    )
    assert int(count or 0) == 1
    note = (
        await world.session.execute(
            select(Notification).where(
                Notification.recipient_user_id == world.recipient_id,
                Notification.conversation_id == conv.id,
                Notification.notification_type == "message.received",
            )
        )
    ).scalar_one()
    assert note.occurrence_count == len(event_ids)


# --- push tokens + deliveries ---
@pytest.mark.asyncio
async def test_push_token_register_and_security(world: CallingCardWorld, client) -> None:
    # Resolve recipient auth via local persona is hard; use service-level device.
    device = await ensure_device(world.session, world.recipient_id)
    svc = notification_service(world)
    now = datetime.now(UTC)
    token = "ExponentPushToken[abcdefghijklmnopqrstuvwxyz]"
    result = await svc.register_push_token(
        user=world.recipient,
        device_id=device.id,
        body=__import__(
            "app.modules.notifications.schemas", fromlist=["PushTokenRegisterRequest"]
        ).PushTokenRegisterRequest(provider="expo", token=token),
        now=now,
    )
    assert result.registered is True
    assert "token" not in result.model_dump()
    await world.session.refresh(device)
    assert device.push_token_hash == hash_push_token(token)
    assert device.push_token_suffix == token[-8:]
    assert device.push_enabled is True

    # Idempotent re-register
    await svc.register_push_token(
        user=world.recipient,
        device_id=device.id,
        body=__import__(
            "app.modules.notifications.schemas", fromlist=["PushTokenRegisterRequest"]
        ).PushTokenRegisterRequest(provider="expo", token=token),
        now=now,
    )

    # Other user conflict
    other_device = await ensure_device(world.session, world.sender_id)
    with pytest.raises(AppError) as exc:
        await notification_service(world).register_push_token(
            user=world.sender,
            device_id=other_device.id,
            body=__import__(
                "app.modules.notifications.schemas", fromlist=["PushTokenRegisterRequest"]
            ).PushTokenRegisterRequest(provider="expo", token=token),
            now=now,
        )
    assert exc.value.code == "PUSH_TOKEN_CONFLICT"

    # Revoke disables push
    from app.modules.identity.service import IdentityService

    await IdentityService(world.session).revoke_device(world.recipient, device.id)
    await world.session.refresh(device)
    assert device.revoked_at is not None
    assert device.push_enabled is False


@pytest.mark.asyncio
async def test_push_delivery_success_retry_invalid(world: CallingCardWorld) -> None:
    now = datetime.now(UTC)
    device = await ensure_device(world.session, world.recipient_id)
    device.push_provider = "expo"
    device.push_token_hash = hash_push_token("ExponentPushToken[validtoken12345678]")
    device.push_token_suffix = "45678"
    device.push_enabled = True
    note = Notification(
        recipient_user_id=world.recipient_id,
        notification_type="system.account_notice",
        title="Hi",
        body="Hello",
        dedupe_key=f"system.account_notice:{world.recipient_id}:delivery",
        occurrence_count=1,
        priority="normal",
        latest_event_at=now,
        created_at=now,
        updated_at=now,
    )
    world.session.add(note)
    await world.session.flush()
    delivery = NotificationDelivery(
        notification_id=note.id,
        device_id=device.id,
        channel="push",
        status="pending",
        attempt_count=0,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    world.session.add(delivery)
    await world.session.commit()

    claimed = await claim_deliveries(world.session, limit=10, now=now, owner="test-worker")
    assert len(claimed) == 1
    provider = FakePushProvider()
    await process_delivery(world.session, claimed[0], provider=provider, now=now)
    await world.session.commit()
    await world.session.refresh(delivery)
    assert delivery.status == "delivered"
    assert note.id  # in-app survives

    # Retryable failure
    delivery2 = NotificationDelivery(
        notification_id=note.id,
        device_id=device.id,
        channel="push",
        status="pending",
        attempt_count=0,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    # unique constraint — use new notification
    note2 = Notification(
        recipient_user_id=world.recipient_id,
        notification_type="system.account_notice",
        title="Retry",
        body="Retry",
        dedupe_key=f"system.account_notice:{world.recipient_id}:retry",
        occurrence_count=1,
        priority="normal",
        latest_event_at=now,
        created_at=now,
        updated_at=now,
    )
    world.session.add(note2)
    await world.session.flush()
    delivery2.notification_id = note2.id
    world.session.add(delivery2)
    await world.session.commit()

    fail_provider = FakePushProvider()

    # force retryable via monkeypatch on send
    async def _retry(**kwargs):
        from app.modules.notifications.push import PushSendResult

        return PushSendResult(
            ok=False, permanent=False, provider_message_id=None, error_code="TRANSIENT"
        )

    fail_provider.send = _retry  # type: ignore[method-assign]
    claimed2 = await claim_deliveries(world.session, limit=10, now=now, owner="w2")
    await process_delivery(world.session, claimed2[0], provider=fail_provider, now=now)
    await world.session.commit()
    await world.session.refresh(delivery2)
    assert delivery2.status == "retryable"
    assert delivery2.next_attempt_at is not None

    # Invalid token
    note3 = Notification(
        recipient_user_id=world.recipient_id,
        notification_type="system.account_notice",
        title="Bad",
        body="Bad",
        dedupe_key=f"system.account_notice:{world.recipient_id}:bad",
        occurrence_count=1,
        priority="normal",
        latest_event_at=now,
        created_at=now,
        updated_at=now,
    )
    world.session.add(note3)
    await world.session.flush()
    delivery3 = NotificationDelivery(
        notification_id=note3.id,
        device_id=device.id,
        channel="push",
        status="pending",
        attempt_count=0,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    world.session.add(delivery3)
    await world.session.commit()
    bad = FakePushProvider(fail_tokens={device.push_token_hash})
    claimed3 = await claim_deliveries(world.session, limit=10, now=now, owner="w3")
    await process_delivery(world.session, claimed3[0], provider=bad, now=now)
    await world.session.commit()
    await world.session.refresh(delivery3)
    await world.session.refresh(device)
    assert delivery3.status == "permanently_failed"
    assert device.push_enabled is False
    await world.session.refresh(note3)
    assert note3.dismissed_at is None  # in-app survives


@pytest.mark.asyncio
async def test_disabled_push_creates_no_delivery(world: CallingCardWorld) -> None:
    now = datetime.now(UTC)
    device = await ensure_device(world.session, world.recipient_id)
    device.push_provider = "expo"
    device.push_token_hash = hash_push_token("ExponentPushToken[nopush1234567890]")
    device.push_enabled = True
    world.session.add(
        NotificationPreference(
            user_id=world.recipient_id,
            category="calling_cards",
            in_app_enabled=True,
            push_enabled=False,
            created_at=now,
            updated_at=now,
        )
    )
    await world.session.commit()
    await world.grant_both_verified()
    await world.service().create_calling_card(
        user=world.sender,
        request=CreateCallingCardRequest(
            recipient_user_id=world.recipient_id, reason_code="say_hello"
        ),
        idempotency_key=str(uuid4()),
        now=now,
    )
    notes = await project_pending(world, event_types={"calling_card.created"})
    assert len(notes) == 1
    dels = await deliveries_for(world.session, notes[0].id)
    assert dels == []


# --- realtime tickets ---
@pytest.mark.asyncio
async def test_realtime_ticket_hash_single_use_expiry(world: CallingCardWorld) -> None:
    ticket, ttl = await create_realtime_ticket(
        world.redis, user_id=world.recipient_id, settings=world.settings
    )
    assert ttl == world.settings.notification_realtime_ticket_ttl_seconds
    digest = hashlib.sha256(ticket.encode()).hexdigest()
    stored = await world.redis.get(f"realtime:ticket:{digest}")
    assert stored == str(world.recipient_id)
    # plaintext ticket must not be the redis key
    assert await world.redis.get(f"realtime:ticket:{ticket}") is None

    user_id = await consume_realtime_ticket(world.redis, ticket=ticket)
    assert user_id == world.recipient_id
    with pytest.raises(AppError) as exc:
        await consume_realtime_ticket(world.redis, ticket=ticket)
    assert exc.value.code in {"REALTIME_TICKET_EXPIRED", "REALTIME_TICKET_INVALID"}

    short_ticket, _ = await create_realtime_ticket(
        world.redis, user_id=world.recipient_id, settings=world.settings
    )
    digest2 = hashlib.sha256(short_ticket.encode()).hexdigest()
    await world.redis.expire(f"realtime:ticket:{digest2}", 0)
    with pytest.raises(AppError):
        await consume_realtime_ticket(world.redis, ticket=short_ticket)


@pytest.mark.asyncio
async def test_realtime_ticket_http(client) -> None:
    headers = auth_headers(client, persona="alpha")
    resp = client.post("/v1/realtime/tickets", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "ticket" in data
    assert data["expires_in_seconds"] == 60
    assert data["websocket_path"] == "/v1/realtime/notifications"
    assert "access_token" not in data
    assert "?" not in data["websocket_path"]
    assert "ticket=" not in data["websocket_path"]


def test_notifications_ws_rejects_ticket_in_url(client) -> None:
    from starlette.testclient import WebSocketDenialResponse
    from starlette.websockets import WebSocketDisconnect

    # Ticket must never be accepted via query string (proxy/access-log leak).
    with pytest.raises((WebSocketDenialResponse, WebSocketDisconnect, RuntimeError)):
        with client.websocket_connect(f"/v1/realtime/notifications?ticket={uuid4().hex}"):
            pass


def test_notifications_ws_rejects_access_token_query(client) -> None:
    from starlette.testclient import WebSocketDenialResponse
    from starlette.websockets import WebSocketDisconnect

    token = client.post("/v1/auth/local/token", json={"persona": "alpha"}).json()["data"][
        "access_token"
    ]
    with pytest.raises((WebSocketDenialResponse, WebSocketDisconnect, RuntimeError)):
        with client.websocket_connect(f"/v1/realtime/notifications?access_token={token}"):
            pass


@pytest.mark.asyncio
async def test_notifications_ws_first_message_auth_flow(
    world: CallingCardWorld, client, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    from starlette.testclient import WebSocketDenialResponse
    from starlette.websockets import WebSocketDisconnect

    now = datetime.now(UTC)
    world.session.add(
        Notification(
            recipient_user_id=world.recipient_id,
            notification_type="system.account_notice",
            title="WS seed",
            body="WS seed",
            dedupe_key=f"system.account_notice:{world.recipient_id}:ws:{uuid4()}",
            occurrence_count=1,
            priority="normal",
            latest_event_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    await world.session.commit()

    ticket, _ = await create_realtime_ticket(
        world.redis, user_id=world.recipient_id, settings=world.settings
    )
    assert "ticket=" not in "/v1/realtime/notifications"

    with caplog.at_level(logging.DEBUG):
        with client.websocket_connect("/v1/realtime/notifications") as ws:
            # No server payload before authenticate.
            ws.send_json({"type": "authenticate", "ticket": ticket})
            first = ws.receive_json()
            assert first["type"] == "unread_count.changed"
            assert first["payload"]["total"] >= 1

    # Plaintext ticket must not appear in application logs.
    joined = "\n".join(r.message for r in caplog.records)
    assert ticket not in joined

    # Reused ticket rejected.
    with pytest.raises((WebSocketDenialResponse, WebSocketDisconnect, RuntimeError)):
        with client.websocket_connect("/v1/realtime/notifications") as ws:
            ws.send_json({"type": "authenticate", "ticket": ticket})
            ws.receive_json()


@pytest.mark.asyncio
async def test_notifications_ws_invalid_and_arbitrary_pre_auth(
    world: CallingCardWorld, client
) -> None:
    from starlette.websockets import WebSocketDisconnect

    with client.websocket_connect("/v1/realtime/notifications") as ws:
        ws.send_json({"type": "authenticate", "ticket": "not-a-real-ticket-value!!"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401

    with client.websocket_connect("/v1/realtime/notifications") as ws:
        ws.send_json({"type": "ping"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


@pytest.mark.asyncio
async def test_notifications_ws_expired_ticket(world: CallingCardWorld, client) -> None:
    import hashlib

    from starlette.websockets import WebSocketDisconnect

    ticket, _ = await create_realtime_ticket(
        world.redis, user_id=world.recipient_id, settings=world.settings
    )
    digest = hashlib.sha256(ticket.encode()).hexdigest()
    await world.redis.expire(f"realtime:ticket:{digest}", 0)

    with client.websocket_connect("/v1/realtime/notifications") as ws:
        ws.send_json({"type": "authenticate", "ticket": ticket})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


@pytest.mark.asyncio
async def test_notifications_ws_binds_to_ticket_owner(world: CallingCardWorld, client) -> None:
    now = datetime.now(UTC)
    world.session.add(
        Notification(
            recipient_user_id=world.recipient_id,
            notification_type="system.account_notice",
            title="Owner only",
            body="Owner only",
            dedupe_key=f"system.account_notice:{world.recipient_id}:owner:{uuid4()}",
            occurrence_count=1,
            priority="normal",
            latest_event_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    await world.session.commit()
    ticket, _ = await create_realtime_ticket(
        world.redis, user_id=world.recipient_id, settings=world.settings
    )
    with client.websocket_connect("/v1/realtime/notifications") as ws:
        ws.send_json({"type": "authenticate", "ticket": ticket})
        first = ws.receive_json()
        assert first["type"] == "unread_count.changed"
        # Snapshot is for ticket owner (recipient), not an unauthenticated caller.
        assert isinstance(first["payload"]["total"], int)
        assert first["payload"]["total"] >= 1


@pytest.mark.asyncio
async def test_inbox_http_endpoints(client, world: CallingCardWorld) -> None:
    # Seed a notification for the authenticated local user if possible.
    headers = auth_headers(client, persona="alpha")
    profile = me(client, headers)
    user_id = profile["id"]
    now = datetime.now(UTC)
    world.session.add(
        Notification(
            recipient_user_id=user_id,
            notification_type="system.account_notice",
            title="HTTP",
            body="HTTP body",
            dedupe_key=f"system.account_notice:{user_id}:http:{uuid4()}",
            occurrence_count=1,
            priority="normal",
            latest_event_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    await world.session.commit()

    listed = client.get("/v1/notifications", headers=headers)
    assert listed.status_code == 200
    items = listed.json()["data"]["items"]
    assert any(i["title"] == "HTTP" for i in items)

    count = client.get("/v1/notifications/unread-count", headers=headers)
    assert count.status_code == 200
    assert count.json()["data"]["total"] >= 1

    prefs = client.get("/v1/me/notification-preferences", headers=headers)
    assert prefs.status_code == 200
    assert len(prefs.json()["data"]["items"]) == len(NOTIFICATION_CATEGORIES)

    bad = client.patch(
        "/v1/me/notification-preferences",
        headers=headers,
        json={"items": [{"category": "nope", "push_enabled": False}]},
    )
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_invitation_notification_omits_token(world: CallingCardWorld) -> None:
    from app.db.models import AuthIdentity
    from app.modules.notifications.projector import project_outbox_event

    now = datetime.now(UTC)
    world.session.add(
        AuthIdentity(
            user_id=world.recipient_id,
            provider="email",
            normalized_email="invitee@example.com",
            verified_at=now,
        )
    )
    invitation_id = uuid4()
    event = OutboxEvent(
        aggregate_type="organization_invitation",
        aggregate_id=invitation_id,
        event_type="organization.invitation.created",
        payload={
            "invitation_id": str(invitation_id),
            "organization_id": str(uuid4()),
            "email_normalized": "invitee@example.com",
            "role": "staff",
            "expires_at": (now + timedelta(days=7)).isoformat(),
            "token": "SHOULD_NEVER_APPEAR",
        },
        occurred_at=now,
        available_at=now,
    )
    world.session.add(event)
    await world.session.commit()
    note = await project_outbox_event(
        world.session, event, redis=world.redis, settings=world.settings, now=now
    )
    await world.session.commit()
    assert note is not None
    assert "SHOULD_NEVER_APPEAR" not in note.body
    assert "SHOULD_NEVER_APPEAR" not in (note.deep_link or "")
    assert "token" not in (note.deep_link or "").lower()


@pytest.mark.asyncio
async def test_story_rejected_omits_provider_payload(world: CallingCardWorld) -> None:
    from app.db.models import MediaAsset, Story
    from app.modules.notifications.projector import project_outbox_event

    now = datetime.now(UTC)
    device = await ensure_device(world.session, world.sender_id)
    asset = MediaAsset(
        owner_user_id=world.sender_id,
        venue_id=world.venue_id,
        purpose="user_story",
        organization_id=None,
        author_check_in_id=world.sender_check_in_id,
        device_id=device.id,
        media_type="image",
        lifecycle_status="rejected",
        moderation_status="rejected",
        attribution_mode="anonymous",
        quarantine_object_key=f"quarantine/u{world.sender_id}/{uuid4()}/original.jpg",
        declared_mime_type="image/jpeg",
        declared_byte_size=1000,
        intent_expires_at=now + timedelta(hours=1),
    )
    world.session.add(asset)
    await world.session.flush()
    story = Story(
        venue_id=world.venue_id,
        media_asset_id=asset.id,
        author_type="user",
        # Anonymous Stories still retain author_user_id for private author ops;
        # public attribution is gated by attribution_mode, not by nulling the FK.
        author_user_id=world.sender_id,
        created_by_user_id=world.sender_id,
        attribution_mode="anonymous",
        reply_policy="disabled",
        publication_status="rejected",
        moderation_status="rejected",
        created_at=now,
        updated_at=now,
    )
    world.session.add(story)
    await world.session.flush()

    event = OutboxEvent(
        aggregate_type="story",
        aggregate_id=story.id,
        event_type="story.rejected",
        payload={
            "story_id": str(story.id),
            "venue_id": str(world.venue_id),
            "media_asset_id": str(asset.id),
            "provider_raw": {
                "scores": [0.9],
                "secret": "moderation-provider-secret",
                "object_key": asset.quarantine_object_key,
                "signed_url": "https://cdn.example/signed?token=abc",
            },
        },
        occurred_at=now,
        available_at=now,
    )
    world.session.add(event)
    await world.session.commit()
    note = await project_outbox_event(
        world.session, event, redis=world.redis, settings=world.settings, now=now
    )
    await world.session.commit()
    assert note is not None
    assert note.recipient_user_id == world.sender_id
    assert note.notification_type == "story.rejected"
    assert note.actor_user_id is None
    blob = f"{note.title}\n{note.body}\n{note.deep_link or ''}"
    assert "provider_raw" not in blob
    assert "moderation-provider-secret" not in blob
    assert "quarantine/" not in blob
    assert "signed_url" not in blob
    assert "cdn.example" not in blob
    assert world.sender.handle not in blob
    assert world.sender.display_name not in blob

    # Tear down story/media before CallingCardWorld cleanup deletes check-ins.
    from sqlalchemy import delete

    from app.db.models import NotificationEventConsumption

    await world.session.execute(
        delete(NotificationEventConsumption).where(
            NotificationEventConsumption.event_id == event.id
        )
    )
    await world.session.execute(delete(OutboxEvent).where(OutboxEvent.id == event.id))
    if note is not None:
        await world.session.execute(delete(Notification).where(Notification.id == note.id))
    await world.session.execute(delete(Story).where(Story.id == story.id))
    await world.session.execute(delete(MediaAsset).where(MediaAsset.id == asset.id))
    await world.session.commit()
