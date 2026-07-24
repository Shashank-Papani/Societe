"""Pure auth-status transitions used by mobile AuthProvider (documented for Phase 2).

These helpers keep login/logout/401 behavior free of reload workarounds and are
exercised by backend-adjacent documentation tests here for cold-start semantics.
"""

from __future__ import annotations

from typing import Literal

AuthStatus = Literal["initializing", "authenticated", "unauthenticated"]


def status_after_restore(token: str | None) -> AuthStatus:
    return "authenticated" if token else "unauthenticated"


def status_after_login() -> AuthStatus:
    return "authenticated"


def status_after_logout_or_401() -> AuthStatus:
    return "unauthenticated"


def protected_queries_enabled(status: AuthStatus) -> bool:
    return status == "authenticated"


def test_cold_start_without_token() -> None:
    assert status_after_restore(None) == "unauthenticated"
    assert not protected_queries_enabled("unauthenticated")
    assert not protected_queries_enabled("initializing")


def test_cold_start_with_token() -> None:
    assert status_after_restore("jwt") == "authenticated"
    assert protected_queries_enabled("authenticated")


def test_login_enables_protected_queries() -> None:
    assert status_after_login() == "authenticated"
    assert protected_queries_enabled(status_after_login())


def test_logout_and_401_disable_protected_queries() -> None:
    assert status_after_logout_or_401() == "unauthenticated"
    assert not protected_queries_enabled("unauthenticated")
