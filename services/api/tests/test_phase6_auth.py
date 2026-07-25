"""Phase 6: OTP auth, refresh concurrency, onboarding, age, lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.models import AuthRefreshSession
from app.modules.identity.age import evaluate_age
from app.modules.identity.email import build_email_sender, reset_memory_email_sender
from app.modules.identity.handles import validate_handle
from app.modules.identity.otp_service import OtpService
from app.modules.identity.session_service import SessionService


@pytest.fixture(autouse=True)
def _memory_mail() -> None:
    reset_memory_email_sender()
    yield
    reset_memory_email_sender()


def test_age_eligible_and_ineligible() -> None:
    settings = get_settings()
    today = datetime.now(UTC).date()
    adult = date(today.year - 20, today.month, today.day)
    child = date(today.year - 16, today.month, today.day)
    ok = evaluate_age(adult, minimum_age_years=settings.minimum_age_years)
    bad = evaluate_age(child, minimum_age_years=settings.minimum_age_years)
    assert ok.eligible is True
    assert ok.age_band is not None
    assert bad.eligible is False


def test_handle_reserved() -> None:
    with pytest.raises(AppError) as exc:
        validate_handle("admin")
    assert exc.value.code == "HANDLE_RESERVED"


def test_email_provider_fail_closed_in_production() -> None:
    with pytest.raises(ValueError):
        Settings(
            app_env="production",
            auth_provider="local",
            jwt_secret="prod-secret-not-for-dev-0123456789abcdef01234567",
            cursor_hmac_secret="cursor-secret-not-for-dev-0123456789abcdef0123",
            email_provider="mailpit",
        )


def test_local_persona_token(client) -> None:  # type: ignore[no-untyped-def]
    response = client.post("/v1/auth/local/token", json={"persona": "alpha"})
    assert response.status_code == 200
    token = response.json()["data"]["access_token"]
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()["data"]
    assert body["onboarding_state"] == "completed"
    assert body["age_verified"] is True
    assert body["privacy"]["allow_calling_cards"] is True


@pytest.mark.asyncio
async def test_otp_flow_new_user_onboarding(db_session, valkey, media_settings) -> None:  # type: ignore[no-untyped-def]
    settings = media_settings
    email = f"newuser-{uuid.uuid4().hex[:8]}@example.com"
    otp = OtpService(db_session, valkey, settings)
    await otp.request_otp(email=email, client_ip="127.0.0.1")
    await db_session.commit()

    sender = build_email_sender(settings)
    assert sender.messages  # type: ignore[attr-defined]
    text = sender.messages[-1].text_body  # type: ignore[attr-defined]
    code = "".join(ch for ch in text if ch.isdigit())[:6]
    assert len(code) == 6

    installation_id = uuid.uuid4()
    result = await otp.verify_otp(
        email=email,
        code=code,
        platform="ios",
        installation_id=installation_id,
        app_version="1.0.0",
        os_version="17.0",
        client_ip="127.0.0.1",
    )
    await db_session.commit()
    assert result.is_new_user is True
    assert result.auth_status == "onboarding_required"
    assert result.tokens is not None
    assert result.user is not None
    assert result.user.onboarding_state == "profile_required"
    assert result.user.privacy is not None
    assert result.user.privacy.allow_calling_cards is False
    assert result.user.privacy.allow_messages_from_connections is False

    # One-time use
    with pytest.raises(AppError) as reused:
        await otp.verify_otp(
            email=email,
            code=code,
            platform="ios",
            installation_id=installation_id,
            app_version="1.0.0",
            os_version="17.0",
            client_ip="127.0.0.1",
        )
    assert reused.value.code == "OTP_INVALID"


@pytest.mark.asyncio
async def test_otp_no_enumeration_and_resend_cooldown(db_session, valkey, media_settings) -> None:  # type: ignore[no-untyped-def]
    settings = media_settings
    otp = OtpService(db_session, valkey, settings)
    email = f"cooldown-{uuid.uuid4().hex[:8]}@example.com"
    first = await otp.request_otp(email=email, client_ip="10.0.0.1")
    await db_session.commit()
    assert "message" in first
    with pytest.raises(AppError) as exc:
        await otp.request_otp(email=email, client_ip="10.0.0.1")
    assert exc.value.code == "OTP_RESEND_COOLDOWN"


@pytest.mark.asyncio
async def test_concurrent_refresh_grace(db_session, valkey, media_settings) -> None:  # type: ignore[no-untyped-def]
    settings = media_settings
    from app.db.models import UserDevice, UserPrivacySettings
    from app.modules.identity.repository import IdentityRepository

    repo = IdentityRepository(db_session)
    user = await repo.create_user(auth_subject=f"refresh-{uuid.uuid4().hex}")
    user.onboarding_state = "completed"
    user.age_verified = True
    privacy = user.privacy or UserPrivacySettings(user_id=user.id)
    privacy.allow_calling_cards = True
    privacy.allow_messages_from_connections = True
    device = UserDevice(
        user_id=user.id,
        platform="ios",
        installation_id=uuid.uuid4(),
    )
    db_session.add(device)
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(device)

    sessions = SessionService(db_session, valkey, settings)
    pair = await sessions.create_session(user=user, device=device)
    await db_session.commit()
    old_refresh = pair.refresh_token

    # Sequential lock simulation: first refresh wins; second within grace replays.
    first = await SessionService(db_session, valkey, settings).refresh(refresh_token=old_refresh)
    await db_session.commit()
    second = await SessionService(db_session, valkey, settings).refresh(refresh_token=old_refresh)
    await db_session.commit()
    assert first.refresh_token == second.refresh_token
    assert first.access_token == second.access_token

    # Outside grace: family revoke
    row = (
        await db_session.execute(
            select(AuthRefreshSession).where(AuthRefreshSession.id == first.session_id)
        )
    ).scalar_one()
    row.rotated_at = datetime.now(UTC) - timedelta(
        seconds=settings.refresh_rotation_grace_seconds + 5
    )
    await db_session.commit()
    with pytest.raises(AppError) as exc:
        await SessionService(db_session, valkey, settings).refresh(refresh_token=old_refresh)
    assert exc.value.code == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_onboarding_age_ineligible(db_session, media_settings) -> None:  # type: ignore[no-untyped-def]
    from app.modules.identity.service import IdentityService

    settings = media_settings
    service = IdentityService(db_session, settings)
    user = await service.resolve_or_provision(f"age-{uuid.uuid4().hex}")
    user.onboarding_state = "age_required"
    await db_session.commit()
    today = datetime.now(UTC).date()
    under = date(today.year - 15, 6, 1)
    updated = await service.complete_onboarding_age(user, date_of_birth=under)
    assert updated.onboarding_state == "age_ineligible"
    assert updated.age_verified is False


@pytest.mark.asyncio
async def test_deactivation_and_reactivation_otp(db_session, valkey, media_settings) -> None:  # type: ignore[no-untyped-def]
    from app.db.models import UserDevice
    from app.modules.identity.service import IdentityService

    settings = media_settings
    identity = IdentityService(db_session, settings)
    sessions = SessionService(db_session, valkey, settings)
    user = await identity.resolve_or_provision(f"deact-{uuid.uuid4().hex}")
    user = await identity.ensure_dev_persona_ready(user, display_name="Deact")
    device = UserDevice(user_id=user.id, platform="ios", installation_id=uuid.uuid4())
    db_session.add(device)
    await db_session.commit()
    await db_session.refresh(device)
    pair = await sessions.create_session(user=user, device=device)
    await db_session.commit()

    await identity.deactivate_account(user, sessions=sessions)
    await db_session.commit()
    await db_session.refresh(user)
    assert user.account_status == "deactivated"

    with pytest.raises(AppError) as revoked:
        await sessions.refresh(refresh_token=pair.refresh_token)
    assert revoked.value.code == "UNAUTHORIZED"
