"""Calling Card authorization and lifecycle against real Postgres + Valkey."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from calling_cards_support import CallingCardWorld, build_calling_card_world
from event_dispatcher.worker import run_dispatch_cycle
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import CallingCard, OutboxEvent
from app.modules.realtime.factory import reset_local_publishers
from app.modules.social.schemas import (
    BlockUserRequest,
    CreateCallingCardRequest,
    RespondCallingCardRequest,
)


@pytest.fixture
async def world(db_session, valkey, media_settings) -> CallingCardWorld:  # type: ignore[no-untyped-def]
    card_world = await build_calling_card_world(db_session, valkey, media_settings)
    try:
        yield card_world
    finally:
        await card_world.cleanup()


async def _create(
    world: CallingCardWorld,
    *,
    key: str | None = None,
    recipient_id=None,  # type: ignore[no-untyped-def]
    now: datetime | None = None,
):
    return await world.service().create_calling_card(
        user=world.sender,
        request=CreateCallingCardRequest(
            recipient_user_id=recipient_id or world.recipient_id,
            reason_code="love_the_dance_moves",
        ),
        idempotency_key=key or str(uuid4()),
        now=now or datetime.now(UTC),
    )


async def test_same_venue_success(world: CallingCardWorld) -> None:
    created = await _create(world)
    assert created.status == "pending"
    assert created.venue_id == world.venue_id

    result = await world.session.execute(
        select(OutboxEvent).where(
            OutboxEvent.aggregate_id == created.id,
            OutboxEvent.event_type == "calling_card.created",
        )
    )
    assert result.scalar_one_or_none() is not None


async def test_outbox_inserted_with_card(world: CallingCardWorld) -> None:
    created = await _create(world)
    result = await world.session.execute(
        select(OutboxEvent).where(OutboxEvent.aggregate_id == created.id)
    )
    event = result.scalar_one()
    assert event.event_type == "calling_card.created"
    assert event.payload["calling_card_id"] == str(created.id)
    assert "recipient_user_ids" in event.payload


async def test_cross_venue_reject(world: CallingCardWorld) -> None:
    await world.move_sender_to_other_venue()
    await world.session.refresh(world.sender)
    with pytest.raises(AppError) as exc:
        await _create(world)
    assert exc.value.code == "CALLING_CARD_VENUE_MISMATCH"


async def test_provisional_reject(world: CallingCardWorld) -> None:
    await world.grant_lease(
        world.sender_id,
        world.sender_check_in_id,
        state="provisional",
    )
    with pytest.raises(AppError) as exc:
        await _create(world)
    assert exc.value.code == "CALLING_CARD_NOT_AUTHORIZED"
    assert exc.value.details["reason"] == "presence_provisional"


async def test_ghost_reject(world: CallingCardWorld) -> None:
    await world.set_privacy(world.sender, ghost_mode=True, discoverable_in_venue=True)
    await world.grant_lease(
        world.sender_id,
        world.sender_check_in_id,
        ghost_mode=True,
        discoverable=False,
    )
    with pytest.raises(AppError) as exc:
        await _create(world)
    assert exc.value.code == "CALLING_CARD_NOT_AUTHORIZED"
    assert exc.value.details["reason"] == "ghost_mode"


async def test_discoverability_reject(world: CallingCardWorld) -> None:
    await world.set_privacy(world.recipient, discoverable_in_venue=False)
    with pytest.raises(AppError) as exc:
        await _create(world)
    assert exc.value.code == "CALLING_CARD_NOT_AUTHORIZED"
    assert exc.value.details["reason"] == "not_discoverable"


async def test_calling_cards_disabled(
    world: CallingCardWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FF_CALLING_CARDS", "false")
    get_settings.cache_clear()
    world.settings = get_settings()
    try:
        with pytest.raises(AppError) as exc:
            await _create(world)
        assert exc.value.code == "CALLING_CARDS_DISABLED"
        assert exc.value.status_code == 404
    finally:
        monkeypatch.setenv("FF_CALLING_CARDS", "true")
        get_settings.cache_clear()


async def test_blocked_pair(world: CallingCardWorld) -> None:
    await world.service().block_user(
        user=world.recipient,
        blocked_user_id=world.sender_id,
        request=BlockUserRequest(reason_code="harassment"),
        now=datetime.now(UTC),
    )
    # Re-attach sender after commit.
    await world.session.refresh(world.sender)
    with pytest.raises(AppError) as exc:
        await _create(world)
    assert exc.value.code == "CALLING_CARD_BLOCKED"


async def test_self_send(world: CallingCardWorld) -> None:
    with pytest.raises(AppError) as exc:
        await _create(world, recipient_id=world.sender_id)
    assert exc.value.code == "CALLING_CARD_SELF"


async def test_idempotency_duplicate(world: CallingCardWorld) -> None:
    key = str(uuid4())
    first = await _create(world, key=key)
    second = await _create(world, key=key)
    assert first.id == second.id


async def test_one_pending_per_pair(world: CallingCardWorld) -> None:
    first = await _create(world)
    # A second create with a different idempotency key must reconcile to the
    # same active pending card rather than inserting a duplicate.
    second = await _create(world)
    assert first.id == second.id
    assert second.status == "pending"


async def test_decline_cooldown(world: CallingCardWorld) -> None:
    created = await _create(world)
    await world.service().respond(
        user=world.recipient,
        calling_card_id=created.id,
        request=RespondCallingCardRequest(decision="decline"),
        now=datetime.now(UTC),
    )
    await world.session.refresh(world.sender)
    await world.grant_both_verified()
    with pytest.raises(AppError) as exc:
        await _create(world)
    assert exc.value.code == "CALLING_CARD_DECLINE_COOLDOWN"


async def test_rate_limits(world: CallingCardWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy import text

    from app.db.models import CheckIn, User, UserPrivacySettings

    monkeypatch.setenv("CALLING_CARD_RATE_LIMIT_PER_USER_PER_10_MINUTES", "1")
    get_settings.cache_clear()
    world.settings = get_settings()
    third_id = None
    third_ci_id = None
    try:
        await _create(world)
        # First send consumed the per-10m bucket. A different recipient still
        # hits the rate limit (pending-pair and cooldown do not apply).
        suffix = uuid4().hex[:8]
        third = User(
            auth_subject=f"cc-third-{suffix}",
            handle=f"third_{suffix}",
            display_name="Third",
            account_status="active",
            age_verified=True,
            onboarding_state="completed",
        )
        world.session.add(third)
        await world.session.flush()
        third_id = third.id
        world.session.add(
            UserPrivacySettings(
                user_id=third.id,
                ghost_mode=False,
                discoverable_in_venue=True,
                allow_calling_cards=True,
                allow_messages_from_connections=True,
            )
        )
        entered = datetime.now(UTC) - timedelta(minutes=5)
        ci = CheckIn(
            user_id=third.id,
            venue_id=world.venue_id,
            state="verified",
            verification_level="standard",
            confidence_score=90,
            entry_method="fused_location",
            ghost_mode_snapshot=False,
            discoverable_snapshot=True,
            entered_at=entered,
            verified_at=entered,
            last_verified_at=entered,
            verified_until=datetime.now(UTC) + timedelta(minutes=5),
            grace_until=datetime.now(UTC) + timedelta(minutes=10),
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=10),
            geofence_version=1,
        )
        world.session.add(ci)
        await world.session.commit()
        third_ci_id = ci.id
        await world.grant_lease(third.id, ci.id)
        await world.grant_both_verified()
        await world.session.refresh(world.sender)
        with pytest.raises(AppError) as exc:
            await _create(world, recipient_id=third.id)
        assert exc.value.code == "CALLING_CARD_RATE_LIMITED"
    finally:
        if third_ci_id is not None:
            await world.session.execute(
                text("DELETE FROM app.check_ins WHERE id = CAST(:id AS uuid)"),
                {"id": str(third_ci_id)},
            )
        if third_id is not None:
            await world.session.execute(
                text("DELETE FROM app.users WHERE id = CAST(:id AS uuid)"),
                {"id": str(third_id)},
            )
            await world.session.commit()
        monkeypatch.setenv("CALLING_CARD_RATE_LIMIT_PER_USER_PER_10_MINUTES", "3")
        get_settings.cache_clear()


async def test_accept_after_exit_fails(world: CallingCardWorld) -> None:
    created = await _create(world)
    await world.clear_leases()
    with pytest.raises(AppError) as exc:
        await world.service().respond(
            user=world.recipient,
            calling_card_id=created.id,
            request=RespondCallingCardRequest(decision="accept", action="accept_only"),
            now=datetime.now(UTC),
        )
    assert exc.value.code == "PRESENCE_NO_LONGER_VALID"
    result = await world.session.execute(select(CallingCard).where(CallingCard.id == created.id))
    card = result.scalar_one()
    assert card.status == "expired"


async def test_block_cancels_pending(world: CallingCardWorld) -> None:
    created = await _create(world)
    await world.service().block_user(
        user=world.sender,
        blocked_user_id=world.recipient_id,
        request=BlockUserRequest(),
        now=datetime.now(UTC),
    )
    result = await world.session.execute(select(CallingCard).where(CallingCard.id == created.id))
    card = result.scalar_one()
    assert card.status == "blocked"


async def test_dispatcher_publishes_to_user_channel(world: CallingCardWorld) -> None:
    from app.modules.realtime.factory import build_realtime_publisher

    reset_local_publishers()
    created = await _create(world)
    # Local DBs may carry an unpublished presence backlog; drain until our row.
    published = False
    for _ in range(50):
        await run_dispatch_cycle(world.settings)
        world.session.expire_all()
        result = await world.session.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == created.id)
        )
        event = result.scalar_one()
        if event.published_at is not None:
            published = True
            break
    assert published, "calling_card.created outbox row was not published"

    hub = build_realtime_publisher(world.settings)
    matching = [
        e
        for e in hub.events  # type: ignore[attr-defined]
        if e.event_type == "calling_card.created" and e.channel == f"user:{world.recipient_id}"
    ]
    assert matching
