"""Development-only persona allowlist for dual-simulator local auth.

Never trust client-supplied subjects/handles — only these keys are accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

DevPersonaKey = Literal["alpha", "beta"]


@dataclass(frozen=True)
class DevPersona:
    key: DevPersonaKey
    subject: str
    handle: str
    display_name: str


DEV_PERSONAS: Final[dict[str, DevPersona]] = {
    "alpha": DevPersona(
        key="alpha",
        subject="dev-user-alpha",
        handle="devalpha",
        display_name="Dev Alpha",
    ),
    "beta": DevPersona(
        key="beta",
        subject="dev-user-beta",
        handle="devbeta",
        display_name="Dev Beta",
    ),
}

# Server-controlled claim-review fixture subjects (auth_subject, never handle).
# Dev Beta and arbitrary local users are intentionally excluded.
DEV_VENUE_CLAIM_ADMIN_SUBJECTS: Final[frozenset[str]] = frozenset({DEV_PERSONAS["alpha"].subject})


def resolve_dev_persona(persona: str) -> DevPersona:
    resolved = DEV_PERSONAS.get(persona)
    if resolved is None:
        from app.core.errors import AppError

        raise AppError(
            "UNKNOWN_DEV_PERSONA",
            "Unknown development persona.",
            status_code=400,
            details={"allowed": sorted(DEV_PERSONAS.keys())},
        )
    return resolved
