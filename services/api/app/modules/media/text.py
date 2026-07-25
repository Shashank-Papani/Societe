"""Plain-text normalisation for captions and vibe tags.

Public clients must render captions as text, not HTML. Control characters and
markup are stripped at the boundary so a later renderer cannot accidentally
interpret user input.
"""

from __future__ import annotations

import re
import unicodedata

_CONTROL_OR_FORMAT = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"
    r"\ufeff"  # BOM
    r"]+"
)
_HTML_TAG = re.compile(r"<[^>]*>")
_WHITESPACE = re.compile(r"\s+")


def normalize_plain_text(value: str) -> str:
    """NFC-normalise, drop controls/HTML, collapse whitespace."""
    text = unicodedata.normalize("NFC", value)
    text = _CONTROL_OR_FORMAT.sub("", text)
    text = _HTML_TAG.sub("", text)
    text = _WHITESPACE.sub(" ", text)
    return text.strip()


def normalize_tag(value: str) -> str:
    return normalize_plain_text(value).lower()
