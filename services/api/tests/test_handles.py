from __future__ import annotations

from app.modules.identity.repository import generate_temporary_handle


def test_temporary_handles_are_random_guest_prefix() -> None:
    handles = {generate_temporary_handle() for _ in range(20)}
    assert len(handles) == 20
    for handle in handles:
        assert handle.startswith("guest_")
        assert len(handle) == len("guest_") + 8
        # Must not look like email/phone/subject-derived.
        assert "@" not in handle
        assert not handle.startswith("+")
        assert "cognito" not in handle.lower()
