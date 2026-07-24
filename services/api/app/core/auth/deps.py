from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_identity_provider
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.models import User
from app.db.session import get_db_session, get_redis
from app.modules.identity.service import IdentityService
from app.shared.idempotency import IdempotencyService

bearer_scheme = HTTPBearer(auto_error=False)

# Single session dependency per request — do not wrap get_db_session in another
# generator or FastAPI will open a second session and commits will miss writes.
get_db = get_db_session


@dataclass
class CurrentUserContext:
    user: User
    auth_subject: str


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUserContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError("UNAUTHORIZED", "Bearer token required.", status_code=401)
    provider = get_identity_provider(settings)
    claims = await provider.verify_token(credentials.credentials)
    service = IdentityService(session)
    user = await service.resolve_or_provision(claims.subject)
    service.assert_active(user)
    return CurrentUserContext(user=user, auth_subject=claims.subject)


async def get_current_user_allow_inactive(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUserContext:
    """Load user without denying deletion_requested (for deletion idempotency replay)."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError("UNAUTHORIZED", "Bearer token required.", status_code=401)
    provider = get_identity_provider(settings)
    claims = await provider.verify_token(credentials.credentials)
    service = IdentityService(session)
    user = await service.resolve_or_provision(claims.subject)
    return CurrentUserContext(user=user, auth_subject=claims.subject)


async def get_idempotency_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> IdempotencyService:
    return IdempotencyService(
        get_redis(settings),
        ttl_seconds=settings.idempotency_ttl_seconds,
    )


def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if not idempotency_key:
        raise AppError(
            "IDEMPOTENCY_KEY_REQUIRED",
            "Idempotency-Key header is required.",
            status_code=400,
        )
    return idempotency_key


def optional_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    return idempotency_key
