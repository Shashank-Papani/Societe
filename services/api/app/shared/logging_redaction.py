from __future__ import annotations

import hashlib
import json
from typing import Any

LOCATION_QUERY_FIELDS = frozenset(
    {
        "latitude",
        "longitude",
        "lat",
        "lng",
        "lon",
        "coords",
        "coordinate",
        "coordinates",
        "location",
        "geolocation",
    }
)


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Redact known location field names from a mapping (logs/traces/errors)."""
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in LOCATION_QUERY_FIELDS:
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)
        elif isinstance(value, list):
            redacted[key] = [
                redact_mapping(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            redacted[key] = value
    return redacted


def stable_json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
