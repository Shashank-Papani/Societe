from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.security import create_access_token, get_current_principal
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["identity"])


class LocalDevTokenRequest(BaseModel):
    """Development-only token request. Subject/handle are fixed from server config."""

    note: str | None = Field(
        default=None,
        description="Optional note; ignored. Tokens always use configured LOCAL_DEV_* values.",
    )


class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    subject: str
    handle: str


class MeData(BaseModel):
    subject: str
    handle: str
    auth_provider: str


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


@router.post("/auth/local/token")
async def issue_local_dev_token(
    request: Request,
    _body: LocalDevTokenRequest | None = None,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Mint a local JWT for development/test only.

    Does not accept arbitrary credentials. Subject and handle come from server config.
    Disabled unless AUTH_PROVIDER=local and APP_ENV is development or test.
    """
    if settings.auth_provider != "local":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Local auth is disabled."},
        )
    if settings.app_env not in {"development", "test"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "LOCAL_AUTH_FORBIDDEN",
                "message": "Local auth is only available in development/test.",
            },
        )

    token = create_access_token(
        subject=settings.local_dev_subject,
        handle=settings.local_dev_handle,
        settings=settings,
    )
    data = TokenData(
        access_token=token,
        expires_in_minutes=settings.jwt_access_token_minutes,
        subject=settings.local_dev_subject,
        handle=settings.local_dev_handle,
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.get("/me")
async def get_me(
    request: Request,
    principal: dict[str, Any] = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    data = MeData(
        subject=str(principal.get("sub", "")),
        handle=str(principal.get("handle", "")),
        auth_provider=settings.auth_provider,
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")
