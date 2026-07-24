from __future__ import annotations

from app.core.middleware import redact_query_string
from app.shared.logging_redaction import LOCATION_QUERY_FIELDS, redact_mapping


def test_redact_mapping_by_field_name() -> None:
    payload = {
        "latitude": 34.0955,
        "longitude": -118.344,
        "venue_name": "Neon House",
        "nested": {"lat": 1.23, "ok": True},
        "centroid_lat_not_a_field": 34.0955,
    }
    redacted = redact_mapping(payload)
    assert redacted["latitude"] == "[REDACTED]"
    assert redacted["longitude"] == "[REDACTED]"
    assert redacted["nested"]["lat"] == "[REDACTED]"
    assert redacted["venue_name"] == "Neon House"
    # Numeric coincidence with a venue centroid is allowed when field is not location-named.
    assert redacted["centroid_lat_not_a_field"] == 34.0955


def test_redact_query_string() -> None:
    query = "latitude=34.1&longitude=-118.3&radius_m=3000&music_tags=house"
    redacted = redact_query_string(query)
    assert "34.1" not in redacted
    assert "-118.3" not in redacted
    assert "radius_m=3000" in redacted
    assert "music_tags=house" in redacted
    assert "latitude=%5BREDACTED%5D" in redacted or "latitude=[REDACTED]" in redacted


def test_location_field_names_cover_common_aliases() -> None:
    for name in ("latitude", "longitude", "lat", "lng", "lon", "location", "coords"):
        assert name in LOCATION_QUERY_FIELDS


def test_cache_keys_do_not_embed_coordinates() -> None:
    from app.modules.venues.cache import VenueStaticCache

    class _Dummy:
        async def mget(self, keys: list[str]) -> list[None]:
            return [None] * len(keys)

        def pipeline(self) -> object:
            return self

        def set(self, *args: object, **kwargs: object) -> None:
            return None

        async def execute(self) -> list[object]:
            return []

    cache = VenueStaticCache(_Dummy(), ttl_seconds=60)  # type: ignore[arg-type]
    key = cache._key("11111111-1111-1111-1111-111111111111")
    assert key == "venue:static:v1:11111111-1111-1111-1111-111111111111"
    assert "34." not in key
    assert "-118" not in key
