"""Shared gates for onboarding / age / account status on social features."""

from __future__ import annotations

from app.core.errors import AppError
from app.db.models import User

INACTIVE_STATUSES = frozenset({"deletion_requested", "deleted", "suspended", "deactivated"})


def assert_socially_eligible(user: User, *, action: str = "this action") -> None:
    if user.account_status in INACTIVE_STATUSES or user.deleted_at is not None:
        raise AppError(
            "ACCOUNT_INACTIVE",
            "This account is not available.",
            status_code=403,
        )
    if user.onboarding_state == "age_ineligible":
        raise AppError(
            "AGE_INELIGIBLE",
            "This account does not meet the minimum age requirement.",
            status_code=403,
            details={"action": action},
        )
    if user.onboarding_state != "completed":
        raise AppError(
            "ONBOARDING_INCOMPLETE",
            "Finish onboarding before using social features.",
            status_code=403,
            details={"onboarding_state": user.onboarding_state, "action": action},
        )
