"""Integration tests for presence heartbeat retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.core.config import get_settings
from app.db.models import CheckIn, User, UserDevice, Venue
from app.db.session import get_redis, get_session_factory
from app.main import create_app
from app.modules.presence.heartbeat import PresenceHeartbeatService
from app.modules.presence.leases import LeaseWrite, PresenceLeaseStore
from app.modules.presence.schemas import (
    EvidenceLocation,
    HeartbeatRequest,
    PlatformSignals,
)


async def _neon_venue(session) -> Venue | None:  # type: ignore[no-untyped-def]
    result = await session.execute(select(Venue).where(Venue.slug == "societe-neon-house"))
    return result.scalar_one_or_none()


async def _reset_user_presence(session, redis, user_id: UUID) -> None:  # type: ignore[no-untyped-def]
    await session.execute(
        text(
            "UPDATE app.check_ins SET state='exited', exited_at=now(), "
            "exit_reason='test_reset' WHERE user_id=:uid AND state IN "
            "('provisional','verified','rechecking','degraded')"
        ),
        {"uid": str(user_id)},
    )
    await session.commit()
    await PresenceLeaseStore(redis).clear(user_id)


async def _seed_active_presence(
    session,
    redis,
    *,
    user: User,
    venue: Venue,
    device: UserDevice,
    now: datetime,
    state: str = "verified",
    outside_count: int = 0,
    first_outside: datetime | None = None,
) -> CheckIn:
    check_in = CheckIn(
        id=uuid4(),
        user_id=user.id,
        venue_id=venue.id,
        state=state,
        verification_level="standard",
        confidence_score=90,
        entry_method="fused_location",
        ghost_mode_snapshot=False,
        discoverable_snapshot=True,
        entered_at=now - timedelta(minutes=5),
        verified_at=now - timedelta(minutes=5),
        last_verified_at=now - timedelta(minutes=1),
        verified_until=now + timedelta(minutes=25),
        grace_until=now + timedelta(minutes=40),
        lease_expires_at=now + timedelta(minutes=40),
        last_valid_evidence_at=now - timedelta(minutes=1),
        outside_confirmation_count=outside_count,
        first_outside_observed_at=first_outside,
        last_outside_observed_at=first_outside,
        geofence_version=venue.geofence_version,
        risk_reasons=[],
        created_at=now,
        updated_at=now,
    )
    session.add(check_in)
    await session.commit()
    store = PresenceLeaseStore(redis)
    await store.update(
        LeaseWrite(
            user_id=user.id,
            venue_id=venue.id,
            check_in_id=check_in.id,
            state="verified",
            confidence=90,
            verification_level="standard",
            ghost_mode=False,
            discoverable=True,
            verified_until=check_in.verified_until,
            grace_until=check_in.grace_until,
            lease_version=venue.geofence_version,
        )
    )
    return check_in


def _hb(
    *,
    device_id: UUID,
    venue_id: UUID,
    lat: float,
    lng: float,
    now: datetime,
    accuracy: float = 8.0,
) -> HeartbeatRequest:
    return HeartbeatRequest(
        evidence_id=uuid4(),
        observed_at=now,
        location=EvidenceLocation(
            latitude=lat,
            longitude=lng,
            horizontal_accuracy_m=accuracy,
            provider="simulated",
        ),
        platform_signals=PlatformSignals(
            is_mock=False,
            is_simulated=True,
            app_state="foreground",
        ),
        venue_id=venue_id,
        client_sequence=1,
        device_id=device_id,
    )


async def _local_world(session, redis):  # type: ignore[no-untyped-def]
    venue = await _neon_venue(session)
    if venue is None:
        pytest.skip("Neon House not seeded")
    user = (
        await session.execute(select(User).where(User.handle == "localdev"))
    ).scalar_one_or_none()
    if user is None:
        pytest.skip("localdev user missing")
    device = UserDevice(user_id=user.id, platform="ios", installation_id=uuid4())
    session.add(device)
    await session.flush()
    await _reset_user_presence(session, redis, user.id)
    return venue, user, device


@pytest.mark.asyncio
async def test_heartbeat_renews_inside_retention_radius() -> None:
    settings = get_settings()
    factory = get_session_factory(settings)
    redis = get_redis(settings)
    async with factory() as session:
        venue, user, device = await _local_world(session, redis)
        now = datetime.now(UTC)
        check_in = await _seed_active_presence(
            session, redis, user=user, venue=venue, device=device, now=now
        )
        service = PresenceHeartbeatService(session, redis, settings)
        try:
            result = await service.heartbeat(
                user=user,
                request=_hb(
                    device_id=device.id,
                    venue_id=venue.id,
                    lat=34.093703,
                    lng=-118.3440,
                    now=now,
                ),
                received_at=now,
                allow_simulated=True,
            )
            assert result.state == "verified"
            assert result.decision == "renewed"
            assert result.distance_meters is not None
            assert result.distance_meters > 160.9344
            assert result.distance_meters <= 241.4016
            assert result.lease_expires_at is not None
            assert result.lease_expires_at >= now + timedelta(seconds=1790)
            await session.refresh(check_in)
            assert check_in.outside_confirmation_count == 0
        finally:
            await _reset_user_presence(session, redis, user.id)


@pytest.mark.asyncio
async def test_first_outside_enters_rechecking_second_revokes() -> None:
    settings = get_settings()
    factory = get_session_factory(settings)
    redis = get_redis(settings)
    async with factory() as session:
        venue, user, device = await _local_world(session, redis)
        now = datetime.now(UTC)
        check_in = await _seed_active_presence(
            session, redis, user=user, venue=venue, device=device, now=now
        )
        service = PresenceHeartbeatService(session, redis, settings)
        try:
            first = await service.heartbeat(
                user=user,
                request=_hb(
                    device_id=device.id,
                    venue_id=venue.id,
                    lat=34.092804,
                    lng=-118.3440,
                    now=now,
                ),
                received_at=now,
                allow_simulated=True,
            )
            assert first.state == "rechecking"
            assert first.outside_confirmation_pending is True

            early = await service.heartbeat(
                user=user,
                request=_hb(
                    device_id=device.id,
                    venue_id=venue.id,
                    lat=34.092804,
                    lng=-118.3440,
                    now=now + timedelta(seconds=30),
                ),
                received_at=now + timedelta(seconds=30),
                allow_simulated=True,
            )
            assert early.state == "rechecking"
            assert "too_early" in early.reasons[0] or early.outside_confirmation_pending

            second = await service.heartbeat(
                user=user,
                request=_hb(
                    device_id=device.id,
                    venue_id=venue.id,
                    lat=34.092804,
                    lng=-118.3440,
                    now=now + timedelta(seconds=91),
                ),
                received_at=now + timedelta(seconds=91),
                allow_simulated=True,
            )
            assert second.state == "exited"
            assert second.decision == "revoked"
            assert "left_retention_radius" in second.reasons
            await session.refresh(check_in)
            assert check_in.state == "revoked"
            assert user.account_status == "active"
        finally:
            await _reset_user_presence(session, redis, user.id)


@pytest.mark.asyncio
async def test_inside_during_recheck_resets_outside_count() -> None:
    settings = get_settings()
    factory = get_session_factory(settings)
    redis = get_redis(settings)
    async with factory() as session:
        venue, user, device = await _local_world(session, redis)
        now = datetime.now(UTC)
        check_in = await _seed_active_presence(
            session,
            redis,
            user=user,
            venue=venue,
            device=device,
            now=now,
            state="rechecking",
            outside_count=1,
            first_outside=now - timedelta(seconds=40),
        )
        service = PresenceHeartbeatService(session, redis, settings)
        try:
            result = await service.heartbeat(
                user=user,
                request=_hb(
                    device_id=device.id,
                    venue_id=venue.id,
                    lat=34.093703,
                    lng=-118.3440,
                    now=now,
                ),
                received_at=now,
                allow_simulated=True,
            )
            assert result.state == "verified"
            await session.refresh(check_in)
            assert check_in.outside_confirmation_count == 0
            assert check_in.first_outside_observed_at is None
        finally:
            await _reset_user_presence(session, redis, user.id)


@pytest.mark.asyncio
async def test_poor_accuracy_outside_does_not_confirm() -> None:
    settings = get_settings()
    factory = get_session_factory(settings)
    redis = get_redis(settings)
    async with factory() as session:
        venue, user, device = await _local_world(session, redis)
        now = datetime.now(UTC)
        check_in = await _seed_active_presence(
            session, redis, user=user, venue=venue, device=device, now=now
        )
        service = PresenceHeartbeatService(session, redis, settings)
        try:
            result = await service.heartbeat(
                user=user,
                request=_hb(
                    device_id=device.id,
                    venue_id=venue.id,
                    lat=34.092804,
                    lng=-118.3440,
                    now=now,
                    accuracy=500.0,
                ),
                received_at=now,
                allow_simulated=True,
            )
            assert result.state == "verified"
            assert "accuracy" in result.reasons[0]
            await session.refresh(check_in)
            assert check_in.outside_confirmation_count == 0
        finally:
            await _reset_user_presence(session, redis, user.id)


@pytest.mark.asyncio
async def test_heartbeat_after_revoke_does_not_revive() -> None:
    settings = get_settings()
    factory = get_session_factory(settings)
    redis = get_redis(settings)
    async with factory() as session:
        venue, user, device = await _local_world(session, redis)
        now = datetime.now(UTC)
        service = PresenceHeartbeatService(session, redis, settings)
        try:
            result = await service.heartbeat(
                user=user,
                request=_hb(
                    device_id=device.id,
                    venue_id=venue.id,
                    lat=34.0955,
                    lng=-118.3440,
                    now=now,
                ),
                received_at=now,
                allow_simulated=True,
            )
            assert result.state == "outside"
            assert result.decision == "no_active_presence"
        finally:
            await _reset_user_presence(session, redis, user.id)


@pytest.mark.asyncio
async def test_openapi_heartbeat_via_async_client() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        paths = (await client.get("/openapi.json")).json()["paths"]
        assert "/v1/presence/heartbeat" in paths
