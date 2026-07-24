from __future__ import annotations

import time

import pytest

from app.core.errors import AppError
from app.shared.cursors import query_fingerprint, sign_cursor, verify_cursor

SECRET = "test-cursor-hmac-secret-0123456789abcdef01234567"


def test_cursor_round_trip() -> None:
    qfp = query_fingerprint(
        latitude=34.1,
        longitude=-118.3,
        radius_m=3000,
        filters={"music_tags": ["house"]},
    )
    cursor = sign_cursor(
        distance_m=120.5,
        venue_id="00000000-0000-0000-0000-000000000001",
        qfp=qfp,
        secret=SECRET,
        ttl_seconds=60,
    )
    payload = verify_cursor(cursor=cursor, expected_qfp=qfp, secret=SECRET)
    assert payload["distance_m"] == 120.5
    assert payload["venue_id"] == "00000000-0000-0000-0000-000000000001"


def test_cursor_tamper_rejected() -> None:
    qfp = query_fingerprint(latitude=34.1, longitude=-118.3, radius_m=3000, filters={})
    cursor = sign_cursor(
        distance_m=10,
        venue_id="00000000-0000-0000-0000-000000000001",
        qfp=qfp,
        secret=SECRET,
    )
    bad = cursor[:-4] + "dead"
    with pytest.raises(AppError) as exc:
        verify_cursor(cursor=bad, expected_qfp=qfp, secret=SECRET)
    assert exc.value.code == "CURSOR_INVALID"


def test_cursor_expired() -> None:
    qfp = query_fingerprint(latitude=34.1, longitude=-118.3, radius_m=3000, filters={})
    cursor = sign_cursor(
        distance_m=10,
        venue_id="00000000-0000-0000-0000-000000000001",
        qfp=qfp,
        secret=SECRET,
        ttl_seconds=-1,
    )
    # Ensure clock moved past exp
    time.sleep(0.01)
    with pytest.raises(AppError) as exc:
        verify_cursor(cursor=cursor, expected_qfp=qfp, secret=SECRET)
    assert exc.value.code == "CURSOR_EXPIRED"
