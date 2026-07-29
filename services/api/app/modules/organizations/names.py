"""Organization name normalization for duplicate detection."""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def normalize_organization_name(name: str) -> str:
    """Lowercase and collapse whitespace for active-name uniqueness checks."""
    return _WHITESPACE.sub(" ", name.strip()).lower()
