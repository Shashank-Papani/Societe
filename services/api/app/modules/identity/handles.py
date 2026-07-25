from __future__ import annotations

import re
import unicodedata

from app.core.errors import AppError

HANDLE_RE = re.compile(r"^[a-z0-9_]{3,32}$")

RESERVED_HANDLES = frozenset(
    {
        "admin",
        "administrator",
        "support",
        "help",
        "societe",
        "official",
        "moderator",
        "mod",
        "staff",
        "system",
        "root",
        "null",
        "undefined",
        "api",
        "security",
        "devalpha",
        "devbeta",
        "localdev",
    }
)

# Best-effort confusable / unsafe fragments.
UNSAFE_FRAGMENTS = frozenset(
    {
        "fuck",
        "shit",
        "nazi",
        "Hitler",
    }
)


def normalize_handle(raw: str) -> str:
    value = unicodedata.normalize("NFKC", raw).strip().lower()
    return value


def validate_handle(raw: str) -> str:
    handle = normalize_handle(raw)
    if not HANDLE_RE.fullmatch(handle):
        raise AppError(
            "INVALID_HANDLE",
            "Username must be 3-32 characters: lowercase letters, numbers, underscore.",
            status_code=400,
        )
    if handle in RESERVED_HANDLES:
        raise AppError(
            "HANDLE_RESERVED",
            "That username is reserved.",
            status_code=400,
        )
    for fragment in UNSAFE_FRAGMENTS:
        if fragment.lower() in handle:
            raise AppError(
                "HANDLE_NOT_ALLOWED",
                "That username is not allowed.",
                status_code=400,
            )
    return handle
