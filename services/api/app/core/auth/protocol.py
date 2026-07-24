from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AuthClaims:
    subject: str
    token_use: str
    raw: dict[str, object]


class IdentityProvider(Protocol):
    async def verify_token(self, token: str) -> AuthClaims: ...
