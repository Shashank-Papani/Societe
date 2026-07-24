from __future__ import annotations

import time
from typing import Any

import httpx
from jose import JWTError, jwt

from app.core.auth.protocol import AuthClaims
from app.core.config import Settings
from app.core.errors import AppError


class CognitoIdentityProvider:
    """Validates Cognito JWTs. Does not deploy Cognito resources."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks: dict[str, Any] | None = None
        self._jwks_fetched_at = 0.0

    @property
    def _issuer(self) -> str:
        region = self._settings.cognito_region
        pool_id = self._settings.cognito_user_pool_id
        return f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"

    @property
    def _jwks_url(self) -> str:
        return f"{self._issuer}/.well-known/jwks.json"

    async def _get_jwks(self) -> dict[str, Any]:
        now = time.time()
        if self._jwks is not None and now - self._jwks_fetched_at < 3600:
            return self._jwks
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(self._jwks_url)
            response.raise_for_status()
            self._jwks = response.json()
            self._jwks_fetched_at = now
            return self._jwks

    def _find_key(self, jwks: dict[str, Any], kid: str) -> dict[str, Any]:
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return dict(key)
        raise AppError("UNAUTHORIZED", "Unknown signing key.", status_code=401)

    async def verify_token(self, token: str) -> AuthClaims:
        if not self._settings.cognito_user_pool_id or not self._settings.cognito_app_client_id:
            raise AppError(
                "AUTH_MISCONFIGURED",
                "Cognito is not configured.",
                status_code=500,
            )
        try:
            headers = jwt.get_unverified_header(token)
            unverified = jwt.get_unverified_claims(token)
        except JWTError as exc:
            raise AppError("UNAUTHORIZED", "Invalid token.", status_code=401) from exc

        token_use = str(unverified.get("token_use", ""))
        if token_use == "refresh":
            raise AppError("UNAUTHORIZED", "Refresh tokens are not accepted.", status_code=401)
        if token_use not in {"access", "id"}:
            raise AppError("UNAUTHORIZED", "Unknown token type.", status_code=401)
        if token_use == "id" and not self._settings.cognito_accept_id_tokens:
            raise AppError("UNAUTHORIZED", "ID tokens are not accepted.", status_code=401)

        kid = headers.get("kid")
        alg = headers.get("alg")
        if alg not in self._settings.cognito_allowed_algorithms:
            raise AppError("UNAUTHORIZED", "Disallowed signing algorithm.", status_code=401)
        if not kid:
            raise AppError("UNAUTHORIZED", "Missing key id.", status_code=401)

        jwks = await self._get_jwks()
        key = self._find_key(jwks, str(kid))

        decode_kwargs: dict[str, Any] = {
            "algorithms": list(self._settings.cognito_allowed_algorithms),
            "issuer": self._issuer,
            "options": {"verify_aud": False},
        }
        try:
            payload = jwt.decode(token, key, **decode_kwargs)
        except JWTError as exc:
            raise AppError("UNAUTHORIZED", "Invalid or expired token.", status_code=401) from exc

        if str(payload.get("token_use")) != token_use:
            raise AppError("UNAUTHORIZED", "token_use mismatch.", status_code=401)

        client_id = self._settings.cognito_app_client_id
        if token_use == "access":
            if str(payload.get("client_id")) != client_id:
                raise AppError("UNAUTHORIZED", "Invalid client_id.", status_code=401)
        elif token_use == "id":
            aud = payload.get("aud")
            audiences = aud if isinstance(aud, list) else [aud]
            if client_id not in {str(a) for a in audiences}:
                raise AppError("UNAUTHORIZED", "Invalid audience.", status_code=401)

        subject = str(payload.get("sub", ""))
        if not subject:
            raise AppError("UNAUTHORIZED", "Token subject missing.", status_code=401)
        return AuthClaims(subject=subject, token_use=token_use, raw=dict(payload))
