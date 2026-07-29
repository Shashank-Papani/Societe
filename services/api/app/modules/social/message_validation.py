"""Server-side Calling Card custom message normalization."""

from __future__ import annotations

import re

from app.core.errors import AppError

CUSTOM_MESSAGE_MAX = 160
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_custom_message(value: str | None) -> str | None:
    """Trim, strip control chars, enforce max length. Empty → None."""
    if value is None:
        return None
    cleaned = _CONTROL_RE.sub("", value)
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    # Collapse internal runs of whitespace (including newlines) to single spaces
    # for storage safety while keeping readable prose.
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > CUSTOM_MESSAGE_MAX:
        raise AppError(
            "VALIDATION_ERROR",
            f"Custom message must be at most {CUSTOM_MESSAGE_MAX} characters.",
            status_code=422,
            details={"field": "custom_message", "max_length": CUSTOM_MESSAGE_MAX},
        )
    return cleaned


def require_opener(*, reason_code: str | None, custom_message: str | None) -> None:
    code = reason_code.strip() if isinstance(reason_code, str) else None
    if code == "":
        code = None
    if code is None and custom_message is None:
        raise AppError(
            "VALIDATION_ERROR",
            "Choose a reason or write a message.",
            status_code=422,
            details={"field": "reason_code"},
        )
