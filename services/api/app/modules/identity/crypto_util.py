from __future__ import annotations

import hashlib
import hmac
import secrets
import unicodedata

from app.core.config import Settings


def normalize_email(email: str) -> str:
    cleaned = unicodedata.normalize("NFKC", email).strip().lower()
    return cleaned


def hash_secret(value: str, settings: Settings) -> str:
    key = settings.jwt_secret.get_secret_value().encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_optional(value: str | None, settings: Settings) -> str | None:
    if value is None or value == "":
        return None
    return hash_secret(value, settings)


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)
