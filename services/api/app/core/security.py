from __future__ import annotations

from typing import Any, cast

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(
    *,
    subject: str,
    handle: str,
    settings: Settings,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    from datetime import UTC, datetime, timedelta

    if settings.auth_provider != "local":
        raise RuntimeError("create_access_token is only available for AUTH_PROVIDER=local")
    if settings.app_env not in {"development", "test"}:
        raise RuntimeError("Local token minting is only allowed in development/test")

    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "handle": handle,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_access_token_minutes)).timestamp()),
        "iss": "societe-local",
        "aud": "societe-api",
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return cast(str, token)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience="societe-api",
            issuer="societe-local",
        )
        return cast(dict[str, Any], payload)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid or expired token."},
        ) from exc


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Bearer token required."},
        )
    return decode_access_token(credentials.credentials, settings)
