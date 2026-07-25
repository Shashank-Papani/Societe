from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user, get_db
from app.core.config import Settings, get_settings
from app.db.session import get_redis
from app.modules.identity.otp_service import OtpService
from app.modules.identity.service import IdentityService, serialize_user
from app.modules.identity.session_service import SessionService
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class OtpRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)


class OtpVerifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    code: str = Field(min_length=4, max_length=12)
    platform: Literal["ios", "android"]
    installation_id: uuid.UUID
    app_version: str | None = None
    os_version: str | None = None


class RefreshBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=20)


class LogoutBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str | None = None


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _redis(settings: Settings) -> Redis[str]:
    return get_redis(settings)


@router.post("/otp/request")
async def request_otp(
    request: Request,
    body: OtpRequestBody,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    service = OtpService(session, _redis(settings), settings)
    data = await service.request_otp(email=body.email, client_ip=_client_ip(request))
    await session.commit()
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.post("/otp/verify")
async def verify_otp(
    request: Request,
    body: OtpVerifyBody,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    service = OtpService(session, _redis(settings), settings)
    result = await service.verify_otp(
        email=body.email,
        code=body.code,
        platform=body.platform,
        installation_id=body.installation_id,
        app_version=body.app_version,
        os_version=body.os_version,
        client_ip=_client_ip(request),
    )
    await session.commit()
    assert result.user is not None
    identity = IdentityService(session, settings)
    user = await identity._repo.get_by_id(result.user.id)
    assert user is not None
    interests = await identity.interests_for(user.id)
    photo = await identity.approved_profile_photo_url(user)
    payload: dict[str, Any] = {
        "auth_status": result.auth_status,
        "is_new_user": result.is_new_user,
        "user": serialize_user(
            user,
            interests=interests,
            profile_photo_url=photo,
            settings=settings,
        ),
    }
    if result.tokens is not None and result.auth_status != "reactivation_required":
        payload["access_token"] = result.tokens.access_token
        payload["refresh_token"] = result.tokens.refresh_token
        payload["token_type"] = "bearer"
        payload["expires_in_minutes"] = result.tokens.expires_in_minutes
        payload["device_id"] = str(result.tokens.device_id)
        payload["session_id"] = str(result.tokens.session_id)
    elif result.tokens is not None and result.auth_status == "reactivation_required":
        payload["access_token"] = result.tokens.access_token
        payload["token_type"] = "bearer"
        payload["expires_in_minutes"] = result.tokens.expires_in_minutes
        payload["refresh_token"] = None
    return success_response(payload, meta=_meta(request)).model_dump(mode="json")


@router.post("/refresh")
async def refresh_tokens(
    request: Request,
    body: RefreshBody,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    sessions = SessionService(session, _redis(settings), settings)
    pair = await sessions.refresh(refresh_token=body.refresh_token)
    await session.commit()
    return success_response(
        {
            "access_token": pair.access_token,
            "refresh_token": pair.refresh_token,
            "token_type": "bearer",
            "expires_in_minutes": pair.expires_in_minutes,
            "device_id": str(pair.device_id),
            "session_id": str(pair.session_id),
        },
        meta=_meta(request),
    ).model_dump(mode="json")


@router.post("/logout")
async def logout(
    request: Request,
    body: LogoutBody,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    sessions = SessionService(session, _redis(settings), settings)
    if body.refresh_token:
        await sessions.revoke_session(refresh_token=body.refresh_token, reason="logout")
        await session.commit()
    return success_response({"revoked": True}, meta=_meta(request)).model_dump(mode="json")


@router.post("/logout-all")
async def logout_all(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[Any, Depends(get_current_user)],
) -> dict[str, Any]:
    sessions = SessionService(session, _redis(settings), settings)
    sid_raw = ctx.claims.get("sid")
    except_id = uuid.UUID(str(sid_raw)) if sid_raw else None
    count = await sessions.revoke_all_for_user(
        ctx.user.id, except_session_id=except_id, reason="logout_all"
    )
    await session.commit()
    return success_response({"revoked_sessions": count}, meta=_meta(request)).model_dump(
        mode="json"
    )
