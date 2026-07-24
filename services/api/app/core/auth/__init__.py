from __future__ import annotations

from app.core.auth.cognito_provider import CognitoIdentityProvider
from app.core.auth.local_provider import LocalIdentityProvider
from app.core.auth.protocol import IdentityProvider
from app.core.config import Settings, get_settings


def get_identity_provider(settings: Settings | None = None) -> IdentityProvider:
    cfg = settings or get_settings()
    if cfg.auth_provider == "cognito":
        return CognitoIdentityProvider(cfg)
    return LocalIdentityProvider(cfg)
