from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.core.errors import AppError

CURSOR_VERSION = 1
DEFAULT_CURSOR_TTL_SECONDS = 30 * 60


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def query_fingerprint(
    *,
    latitude: float,
    longitude: float,
    radius_m: int,
    filters: dict[str, Any],
) -> str:
    normalized = {
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "radius_m": radius_m,
        "filters": filters,
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def keyset_fingerprint(**parts: Any) -> str:
    """Bind a cursor to the query that produced it (feed pagination)."""
    encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sign_keyset_cursor(
    *,
    sort_key: str,
    item_id: str,
    qfp: str,
    secret: str,
    ttl_seconds: int = DEFAULT_CURSOR_TTL_SECONDS,
) -> str:
    """Signed `(sort_key, id)` position for a keyset-paginated list.

    Signed for the same reason map cursors are: an opaque-looking base64 blob a
    client can edit is an offset parameter with extra steps, and this one is used
    to seek into another user's feed page.
    """
    payload = {
        "v": CURSOR_VERSION,
        "sk": sort_key,
        "id": item_id,
        "qfp": qfp,
        "exp": int(time.time()) + ttl_seconds,
    }
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url_encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def verify_keyset_cursor(*, cursor: str, expected_qfp: str, secret: str) -> dict[str, Any]:
    payload = _decode_verified(cursor=cursor, expected_qfp=expected_qfp, secret=secret)
    if "sk" not in payload or "id" not in payload:
        raise AppError("CURSOR_INVALID", "Cursor is incomplete.", status_code=400)
    return payload


def sign_cursor(
    *,
    distance_m: float,
    venue_id: str,
    qfp: str,
    secret: str,
    ttl_seconds: int = DEFAULT_CURSOR_TTL_SECONDS,
) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "distance_m": float(distance_m),
        "venue_id": venue_id,
        "qfp": qfp,
        "exp": int(time.time()) + ttl_seconds,
    }
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url_encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def _decode_verified(*, cursor: str, expected_qfp: str, secret: str) -> dict[str, Any]:
    try:
        body, sig = cursor.split(".", 1)
    except ValueError as exc:
        raise AppError("CURSOR_INVALID", "Cursor is malformed.", status_code=400) from exc

    expected_sig = _b64url_encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig, expected_sig):
        raise AppError("CURSOR_INVALID", "Cursor signature is invalid.", status_code=400)

    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise AppError("CURSOR_INVALID", "Cursor payload is invalid.", status_code=400) from exc

    if payload.get("v") != CURSOR_VERSION:
        raise AppError("CURSOR_INVALID", "Unsupported cursor version.", status_code=400)
    if int(payload.get("exp", 0)) < int(time.time()):
        raise AppError("CURSOR_EXPIRED", "Cursor has expired.", status_code=400)
    if payload.get("qfp") != expected_qfp:
        raise AppError(
            "CURSOR_QUERY_MISMATCH",
            "Cursor does not match the current query.",
            status_code=400,
        )
    return dict(payload)


def verify_cursor(
    *,
    cursor: str,
    expected_qfp: str,
    secret: str,
) -> dict[str, Any]:
    payload = _decode_verified(cursor=cursor, expected_qfp=expected_qfp, secret=secret)
    if "distance_m" not in payload or "venue_id" not in payload:
        raise AppError("CURSOR_INVALID", "Cursor is incomplete.", status_code=400)
    return payload
