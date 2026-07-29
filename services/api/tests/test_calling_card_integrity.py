"""Calling Card uniqueness, custom messages, and block-list integrity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from calling_cards_support import CallingCardWorld, build_calling_card_world
from pydantic import ValidationError
from sqlalchemy import select, text
from test_calling_cards_authz import _create

from app.core.errors import AppError
from app.db.models import CallingCard, ConnectionGrant
from app.modules.social.message_validation import normalize_custom_message
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


@pytest.mark.asyncio
async def test_reverse_direction_pending_reconciles(world: CallingCardWorld) -> None:
    first = await _create(world)
    reverse = await world.service().create_calling_card(
        user=world.recipient,
        request=CreateCallingCardRequest(
            recipient_user_id=world.sender_id,
            reason_code="say_hello",
        ),
        idempotency_key=str(uuid4()),
        now=datetime.now(UTC),
    )
    assert reverse.id == first.id


@pytest.mark.asyncio
async def test_connected_pair_cannot_create_another_card(world: CallingCardWorld) -> None:
    created = await _create(world)
    await world.service().respond(
        user=world.recipient,
        calling_card_id=created.id,
        request=RespondCallingCardRequest(decision="accept", action="accept_only"),
        now=datetime.now(UTC),
    )
    await world.session.refresh(world.sender)
    await world.grant_both_verified()
    with pytest.raises(AppError) as exc:
        await _create(world)
    assert exc.value.code == "CALLING_CARD_ALREADY_CONNECTED"


@pytest.mark.asyncio
async def test_double_accept_returns_same_grant(world: CallingCardWorld) -> None:
    created = await _create(world)
    first = await world.service().respond(
        user=world.recipient,
        calling_card_id=created.id,
        request=RespondCallingCardRequest(decision="accept", action="accept_only"),
        now=datetime.now(UTC),
    )
    second = await world.service().respond(
        user=world.recipient,
        calling_card_id=created.id,
        request=RespondCallingCardRequest(decision="accept", action="accept_only"),
        now=datetime.now(UTC) + timedelta(seconds=1),
    )
    assert first.grant is not None
    assert second.grant is not None
    assert first.grant.id == second.grant.id
    result = await world.session.execute(
        select(ConnectionGrant).where(
            ConnectionGrant.calling_card_id == created.id,
            ConnectionGrant.revoked_at.is_(None),
        )
    )
    assert len(list(result.scalars().all())) == 1


@pytest.mark.asyncio
async def test_custom_message_only_and_preset_plus_message(world: CallingCardWorld) -> None:
    only_message = await world.service().create_calling_card(
        user=world.sender,
        request=CreateCallingCardRequest(
            recipient_user_id=world.recipient_id,
            custom_message="  Had fun near the booth  ",
        ),
        idempotency_key=str(uuid4()),
        now=datetime.now(UTC),
    )
    detail = await world.service().detail(
        user=world.sender, calling_card_id=only_message.id, now=datetime.now(UTC)
    )
    assert detail.card.custom_message == "Had fun near the booth"
    assert detail.card.reason_code is None

    # Clear for second card to a different recipient is hard; cancel and reuse after.
    await world.service().cancel(
        user=world.sender, calling_card_id=only_message.id, now=datetime.now(UTC)
    )
    await world.grant_both_verified()
    both = await world.service().create_calling_card(
        user=world.sender,
        request=CreateCallingCardRequest(
            recipient_user_id=world.recipient_id,
            reason_code="great_conversation",
            custom_message="Loved that set",
        ),
        idempotency_key=str(uuid4()),
        now=datetime.now(UTC),
    )
    detail2 = await world.service().detail(
        user=world.sender, calling_card_id=both.id, now=datetime.now(UTC)
    )
    assert detail2.card.reason_code == "great_conversation"
    assert detail2.card.custom_message == "Loved that set"


@pytest.mark.asyncio
async def test_empty_opener_and_overlong_message_rejected(world: CallingCardWorld) -> None:
    with pytest.raises(AppError) as empty:
        await world.service().create_calling_card(
            user=world.sender,
            request=CreateCallingCardRequest(recipient_user_id=world.recipient_id),
            idempotency_key=str(uuid4()),
            now=datetime.now(UTC),
        )
    assert empty.value.code == "VALIDATION_ERROR"

    with pytest.raises(ValidationError):
        CreateCallingCardRequest(
            recipient_user_id=world.recipient_id,
            custom_message="x" * 161,
        )
    with pytest.raises(AppError) as long:
        normalize_custom_message("x" * 161)
    assert long.value.code == "VALIDATION_ERROR"


def test_normalize_custom_message_strips_controls() -> None:
    assert normalize_custom_message("  hello\x00  ") == "hello"
    assert normalize_custom_message("   ") is None


@pytest.mark.asyncio
async def test_block_list_and_unblock(world: CallingCardWorld) -> None:
    await world.service().block_user(
        user=world.sender,
        blocked_user_id=world.recipient_id,
        request=BlockUserRequest(reason_code="harassment"),
        now=datetime.now(UTC),
    )
    listed = await world.service().list_blocked_users(user=world.sender)
    assert len(listed.blocked_users) == 1
    assert listed.blocked_users[0].user_id == world.recipient_id

    await world.service().unblock_user(
        user=world.sender,
        blocked_user_id=world.recipient_id,
        now=datetime.now(UTC),
    )
    listed_after = await world.service().list_blocked_users(user=world.sender)
    assert listed_after.blocked_users == []


@pytest.mark.asyncio
async def test_block_invalidates_pending_card(world: CallingCardWorld) -> None:
    created = await _create(world)
    await world.service().block_user(
        user=world.sender,
        blocked_user_id=world.recipient_id,
        request=BlockUserRequest(),
        now=datetime.now(UTC),
    )
    card = await world.session.get(CallingCard, created.id)
    assert card is not None
    assert card.status == "blocked"


@pytest.mark.asyncio
async def test_unblock_does_not_restore_prior_card_or_grant(world: CallingCardWorld) -> None:
    created = await _create(world)
    await world.service().respond(
        user=world.recipient,
        calling_card_id=created.id,
        request=RespondCallingCardRequest(decision="accept", action="accept_only"),
        now=datetime.now(UTC),
    )
    await world.service().block_user(
        user=world.sender,
        blocked_user_id=world.recipient_id,
        request=BlockUserRequest(),
        now=datetime.now(UTC),
    )
    await world.service().unblock_user(
        user=world.sender,
        blocked_user_id=world.recipient_id,
        now=datetime.now(UTC),
    )
    card = await world.session.get(CallingCard, created.id)
    assert card is not None
    # Accepted cards are not rewritten to blocked; grants are revoked instead.
    assert card.status == "accepted"
    grants = await world.session.execute(
        select(ConnectionGrant).where(
            ConnectionGrant.calling_card_id == created.id,
            ConnectionGrant.revoked_at.is_(None),
        )
    )
    assert list(grants.scalars().all()) == []
    inbox = await world.service().inbox(user=world.recipient, now=datetime.now(UTC))
    accepted = next(item for item in inbox.items if item.id == created.id)
    assert accepted.has_active_grant is False
    sent = await world.service().sent(user=world.sender, now=datetime.now(UTC))
    sent_accepted = next(item for item in sent.items if item.id == created.id)
    assert sent_accepted.has_active_grant is False
    await world.grant_both_verified()
    # Unblock must not auto-reconnect; a new card may be sent under normal rules.
    fresh = await _create(world)
    assert fresh.id != created.id
    assert fresh.status == "pending"


@pytest.mark.asyncio
async def test_concurrent_accepts_one_grant(world: CallingCardWorld) -> None:
    created = await _create(world)

    async def _accept() -> None:
        # Use a nested session path via the shared world service carefully.
        await world.service().respond(
            user=world.recipient,
            calling_card_id=created.id,
            request=RespondCallingCardRequest(decision="accept", action="accept_only"),
            now=datetime.now(UTC),
        )

    await _accept()
    await _accept()
    result = await world.session.execute(
        text(
            """
            SELECT COUNT(*) FROM app.connection_grants
            WHERE revoked_at IS NULL
              AND LEAST(user_a_id, user_b_id) = LEAST(CAST(:a AS uuid), CAST(:b AS uuid))
              AND GREATEST(user_a_id, user_b_id) = GREATEST(CAST(:a AS uuid), CAST(:b AS uuid))
            """
        ),
        {"a": str(world.sender_id), "b": str(world.recipient_id)},
    )
    assert int(result.scalar_one()) == 1
