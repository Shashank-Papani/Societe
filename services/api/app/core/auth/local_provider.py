from __future__ import annotations

from jose import JWTError, jwt

from app.core.auth.protocol import AuthClaims
from app.core.config import Settings
from app.core.errors import AppError


class LocalIdentityProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def verify_token(self, token: str) -> AuthClaims:
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret.get_secret_value(),
                algorithms=[self._settings.jwt_algorithm],
                audience="societe-api",
                issuer="societe-local",
            )
        except JWTError as exc:
            raise AppError(
                "UNAUTHORIZED",
                "Invalid or expired token.",
                status_code=401,
            ) from exc
        subject = str(payload.get("sub", ""))
        if not subject:
            raise AppError("UNAUTHORIZED", "Token subject missing.", status_code=401)
        return AuthClaims(subject=subject, token_use="access", raw=dict(payload))
