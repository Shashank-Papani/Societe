"""Opaque signed Story group keys.

Clients receive opaque tokens; they must not be able to enumerate authors or
venues by forging ``user:{id}`` / ``venue:{id}`` strings.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Literal
from uuid import UUID

from app.core.errors import AppError

GROUP_KEY_VERSION = 1
DEFAULT_GROUP_KEY_TTL_SECONDS = 24 * 60 * 60

GroupType = Literal["venue", "user", "anon"]


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def logical_group_id(
    *,
    author_type: str,
    attribution_mode: str,
    venue_id: UUID,
    author_user_id: UUID | None,
    story_id: UUID,
) -> str:
    """Stable logical grouping id used inside the signed payload."""
    if author_type == "venue" or attribution_mode == "official":
        return f"venue:{venue_id}"
    if attribution_mode == "anonymous":
        # One anonymous Story per group — never merge across authors.
        return f"anon:{venue_id}:{story_id}"
    if author_user_id is None:
        return f"anon:{venue_id}:{story_id}"
    return f"user:{author_user_id}:venue:{venue_id}"


def group_type_for_logical(logical_id: str) -> GroupType:
    if logical_id.startswith("venue:"):
        return "venue"
    if logical_id.startswith("user:"):
        return "user"
    return "anon"


def sign_group_key(
    *,
    logical_id: str,
    secret: str,
    ttl_seconds: int = DEFAULT_GROUP_KEY_TTL_SECONDS,
) -> str:
    payload = {
        "v": GROUP_KEY_VERSION,
        "g": logical_id,
        "exp": int(time.time()) + ttl_seconds,
    }
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url_encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def verify_group_key(*, group_key: str, secret: str) -> dict[str, Any]:
    try:
        body, sig = group_key.split(".", 1)
    except ValueError as exc:
        raise AppError(
            "STORY_GROUP_KEY_INVALID",
            "Story group key is malformed.",
            status_code=400,
        ) from exc

    expected_sig = _b64url_encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig, expected_sig):
        raise AppError(
            "STORY_GROUP_KEY_INVALID",
            "Story group key signature is invalid.",
            status_code=400,
        )

    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise AppError(
            "STORY_GROUP_KEY_INVALID",
            "Story group key payload is invalid.",
            status_code=400,
        ) from exc

    if payload.get("v") != GROUP_KEY_VERSION:
        raise AppError(
            "STORY_GROUP_KEY_INVALID",
            "Unsupported story group key version.",
            status_code=400,
        )
    if int(payload.get("exp", 0)) < int(time.time()):
        raise AppError("STORY_GROUP_KEY_EXPIRED", "Story group key has expired.", status_code=400)
    logical_id = payload.get("g")
    if not isinstance(logical_id, str) or not logical_id:
        raise AppError(
            "STORY_GROUP_KEY_INVALID",
            "Story group key is incomplete.",
            status_code=400,
        )
    return {"logical_id": logical_id, "group_type": group_type_for_logical(logical_id)}
