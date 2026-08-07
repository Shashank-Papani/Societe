"""Phase 4 realtime hub, outbox dispatch, ack, and push fallback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from calling_cards_support import CallingCardWorld, build_calling_card_world
from event_dispatcher.worker import publish_event, run_dispatch_cycle
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.models import OutboxEvent
from app.db.session import get_redis
from app.modules.notifications.tickets import create_realtime_ticket
from app.modules.realtime.ack import has_event_ack, record_event_ack
from app.modules.realtime.factory import (
    build_push_publisher,
    build_realtime_publisher,
    reset_local_publishers,
)
from app.modules.realtime.local import LocalRealtimeHub
from app.modules.realtime.protocols import RealtimePublisher
from app.modules.social.schemas import CreateCallingCardRequest


@pytest.fixture
async def world(db_session, valkey, media_settings) -> CallingCardWorld:  # type: ignore[no-untyped-def]
    card_world = await build_calling_card_world(db_session, valkey, media_settings)
    try:
        yield card_world
    finally:
        await card_world.cleanup()


async def _create_card(world: CallingCardWorld):
    return await world.service().create_calling_card(
        user=world.sender,
        request=CreateCallingCardRequest(
            recipient_user_id=world.recipient_id,
            reason_code="love_the_dance_moves",
        ),
        idempotency_key=str(uuid4()),
        now=datetime.now(UTC),
    )


async def _load_outbox(world: CallingCardWorld, aggregate_id) -> OutboxEvent:
    result = await world.session.execute(
        select(OutboxEvent).where(OutboxEvent.aggregate_id == aggregate_id)
    )
    return result.scalar_one()


async def _drain_until_published(world: CallingCardWorld, aggregate_id) -> OutboxEvent:
    published: OutboxEvent | None = None
    for _ in range(50):
        await run_dispatch_cycle(world.settings)
        world.session.expire_all()
        event = await _load_outbox(world, aggregate_id)
        if event.published_at is not None:
            published = event
            break
    assert published is not None, "outbox row was not published"
    return published


async def test_hub_dedupes_duplicate_publish() -> None:
    hub = LocalRealtimeHub()
    payload = {"hello": "world"}
    await hub.publish("user:a", event_id="e1", event_type="calling_card.created", payload=payload)
    await hub.publish("user:a", event_id="e1", event_type="calling_card.created", payload=payload)
    await hub.publish("user:a", event_id="e2", event_type="calling_card.created", payload=payload)
    assert len(hub.events) == 2
    assert [e.event_id for e in hub.events] == ["e1", "e2"]


async def test_outbox_retry_then_published_at(world: CallingCardWorld) -> None:
    reset_local_publishers()
    created = await _create_card(world)
    event = await _load_outbox(world, created.id)
    redis = get_redis(world.settings)
    push = build_push_publisher(world.settings)

    class FlakyRealtime:
        def __init__(self) -> None:
            self.calls = 0

        async def publish(
            self,
            channel: str,
            *,
            event_id: str,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("realtime unavailable")

    flaky: RealtimePublisher = FlakyRealtime()
    with pytest.raises(RuntimeError, match="realtime unavailable"):
        await publish_event(
            event,
            realtime=flaky,
            push=push,
            redis=redis,
            ack_wait_seconds=0,
        )

    event.attempts = 1
    event.last_error = "realtime unavailable"
    event.available_at = datetime.now(UTC) + timedelta(seconds=30)
    await world.session.commit()
    assert any(c.event_id == str(event.id) for c in push.calls)  # type: ignore[attr-defined]

    reset_local_publishers()
    hub = build_realtime_publisher(world.settings)
    push = build_push_publisher(world.settings)
    await publish_event(
        event,
        realtime=hub,
        push=push,
        redis=redis,
        ack_wait_seconds=0.05,
    )
    event.published_at = datetime.now(UTC)
    event.last_error = None
    await world.session.commit()
    await world.session.refresh(event)
    assert event.published_at is not None
    assert event.last_error is None
    assert event.attempts == 1


async def test_push_fallback_when_no_ack(world: CallingCardWorld) -> None:
    reset_local_publishers()
    created = await _create_card(world)
    event = await _drain_until_published(world, created.id)

    push = build_push_publisher(world.settings)
    matching = [
        c
        for c in push.calls  # type: ignore[attr-defined]
        if c.event_id == str(event.id) and c.user_id == str(world.recipient_id)
    ]
    assert matching, "expected push fallback when realtime ack is missing"


async def test_no_push_when_ack_arrives_in_time(world: CallingCardWorld) -> None:
    reset_local_publishers()
    created = await _create_card(world)
    event = await _load_outbox(world, created.id)
    redis = get_redis(world.settings)
    inner = build_realtime_publisher(world.settings)
    push = build_push_publisher(world.settings)

    class AckingRealtime:
        async def publish(
            self,
            channel: str,
            *,
            event_id: str,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            await inner.publish(
                channel,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
            )
            await record_event_ack(
                redis,
                event_id=event_id,
                ttl_seconds=world.settings.realtime_ack_ttl_seconds,
            )

    await publish_event(
        event,
        realtime=AckingRealtime(),
        push=push,
        redis=redis,
        ack_wait_seconds=0.05,
    )
    assert await has_event_ack(redis, event_id=str(event.id))
    assert not any(c.event_id == str(event.id) for c in push.calls)  # type: ignore[attr-defined]


def test_ack_endpoint_and_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths["/v1/events/{event_id}/ack"]

    anonymous = client.post(f"/v1/events/{uuid4()}/ack")
    assert anonymous.status_code == 401

    token = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    event_id = uuid4()
    response = client.post(
        f"/v1/events/{event_id}/ack",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["event_id"] == str(event_id)
    assert body["acked"] is True


def test_websocket_requires_auth(client: TestClient) -> None:
    # Socket may accept, but no user-specific data without a valid ticket.
    with client.websocket_connect("/v1/realtime/ws") as ws:
        ws.send_json({"type": "authenticate", "ticket": "x" * 32})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_websocket_rejects_access_token_query(client: TestClient) -> None:
    from starlette.testclient import WebSocketDenialResponse

    token = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    with pytest.raises((WebSocketDenialResponse, WebSocketDisconnect, RuntimeError)):
        with client.websocket_connect(f"/v1/realtime/ws?access_token={token}"):
            pass


def test_websocket_rejects_ticket_query(client: TestClient) -> None:
    from starlette.testclient import WebSocketDenialResponse

    with pytest.raises((WebSocketDenialResponse, WebSocketDisconnect, RuntimeError)):
        with client.websocket_connect(f"/v1/realtime/ws?ticket={uuid4().hex}"):
            pass


def test_websocket_rejects_bearer_header_without_ticket(client: TestClient) -> None:
    token = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    # Bearer alone must not authenticate; ticket first-frame is required.
    with client.websocket_connect(
        "/v1/realtime/ws",
        headers={"Authorization": f"Bearer {token}"},
    ) as ws:
        ws.send_json({"type": "authenticate", "ticket": "x" * 32})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


@pytest.mark.asyncio
async def test_websocket_ticket_auth_flow(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    settings = get_settings()
    token = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"}).json()["data"]
    user_id = UUID(me["id"])
    redis = get_redis(settings)
    ticket, _ = await create_realtime_ticket(
        redis, user_id=user_id, settings=settings, purpose="calling_cards"
    )

    with caplog.at_level(logging.DEBUG):
        with client.websocket_connect("/v1/realtime/ws") as ws:
            ws.send_json({"type": "authenticate", "ticket": ticket})
            hello = ws.receive_json()
            assert hello["type"] == "subscribed"
            assert hello["channel"] == f"user:{user_id}"
            assert "deduplicate" in hello["note"].lower()

    assert ticket not in "\n".join(r.message for r in caplog.records)

    # Reused ticket rejected.
    with pytest.raises((WebSocketDenialResponse, WebSocketDisconnect, RuntimeError)):
        with client.websocket_connect("/v1/realtime/ws") as ws:
            ws.send_json({"type": "authenticate", "ticket": ticket})
            ws.receive_json()


@pytest.mark.asyncio
async def test_websocket_rejects_notifications_purpose_ticket(client: TestClient) -> None:
    settings = get_settings()
    token = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"}).json()["data"]
    user_id = UUID(me["id"])
    redis = get_redis(settings)
    ticket, _ = await create_realtime_ticket(
        redis, user_id=user_id, settings=settings, purpose="notifications"
    )
    with client.websocket_connect("/v1/realtime/ws") as ws:
        ws.send_json({"type": "authenticate", "ticket": ticket})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_websocket_subscribes_with_scoped_ticket(client: TestClient) -> None:
    """HTTP ticket endpoint + clean WS URL (no secrets in query)."""
    token = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    issued = client.post(
        "/v1/realtime/tickets",
        headers=headers,
        json={"purpose": "calling_cards"},
    )
    assert issued.status_code == 200
    data = issued.json()["data"]
    assert data["websocket_path"] == "/v1/realtime/ws"
    assert "access_token" not in data
    ticket = data["ticket"]

    with client.websocket_connect("/v1/realtime/ws") as ws:
        ws.send_json({"type": "authenticate", "ticket": ticket})
        hello = ws.receive_json()
        assert hello["type"] == "subscribed"
        assert hello["channel"].startswith("user:")
        assert "deduplicate" in hello["note"].lower()


async def test_calling_card_responses_omit_precise_coordinates(
    world: CallingCardWorld,
    client: TestClient,
) -> None:
    created = await _create_card(world)
    settings = get_settings()
    sender_token = create_access_token(
        subject=world.sender.auth_subject,
        handle=world.sender.handle,
        settings=settings,
    )
    recipient_token = create_access_token(
        subject=world.recipient.auth_subject,
        handle=world.recipient.handle,
        settings=settings,
    )

    forbidden = ("latitude", "longitude", "lat", "lon", "lng", "coords", "location")

    def _assert_no_coords(payload: Any) -> None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                assert key not in forbidden, f"unexpected coordinate key {key!r}"
                _assert_no_coords(value)
        elif isinstance(payload, list):
            for item in payload:
                _assert_no_coords(item)

    for path, token in (
        ("/v1/calling-cards/sent", sender_token),
        ("/v1/calling-cards/inbox", recipient_token),
        (f"/v1/calling-cards/{created.id}", sender_token),
        (f"/v1/calling-cards/{created.id}/status", sender_token),
        ("/v1/venues/me/discoverable-users", sender_token),
    ):
        response = client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text
        _assert_no_coords(response.json())
