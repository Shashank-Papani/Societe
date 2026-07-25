"""Moderation provider seam and the deterministic local implementation.

Two rules shape this module:

* Moderation reads **sanitised derivatives**, not the raw original. The bytes a
  provider sees are the bytes a viewer would see, and the original never leaves
  quarantine for a third party.
* Anything other than a clear approval keeps the media unpublished. A provider
  exception, a timeout, or a low-confidence high-severity hit all resolve to
  manual review rather than a default publish.

The local provider is deterministic and marker-driven so a developer can
reproduce the reject and review branches on demand instead of waiting for a
probabilistic score to land.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from app.core.config import Settings

ModerationDecision = Literal["approved", "rejected", "manual_review"]

REJECT_CAPTION_MARKER = "[moderation:reject]"
REVIEW_CAPTION_MARKER = "[moderation:review]"
REJECT_TAG_MARKER = "moderation-reject"
REVIEW_TAG_MARKER = "moderation-review"


@dataclass(frozen=True)
class ModerationAsset:
    media_asset_id: UUID
    media_type: str
    caption: str | None
    vibe_tags: list[str]
    #: Sanitised derivative files, in evaluation order. Never the original.
    derivative_paths: list[Path] = field(default_factory=list)
    derivative_checksums: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModerationSignalResult:
    category: str
    # Absent when the signal is structural (a provider error carries no score).
    confidence: Decimal | None = None
    model_version: str | None = None
    raw_reference: str | None = None


@dataclass(frozen=True)
class ModerationResult:
    decision: ModerationDecision
    provider: str
    policy_version: str
    signals: list[ModerationSignalResult] = field(default_factory=list)

    @property
    def case_status(self) -> str:
        if self.decision == "approved":
            return "auto_approved"
        if self.decision == "rejected":
            return "auto_rejected"
        return "needs_review"


class ModerationProvider(Protocol):
    provider: str

    async def moderate(self, asset: ModerationAsset) -> ModerationResult: ...

    # Asynchronous video moderation belongs to the managed-provider phase. The
    # seam exists; calling it here would imply a job store that does not exist.
    async def start_video_moderation(self, asset: ModerationAsset) -> str: ...

    async def get_video_moderation(self, job_id: str) -> ModerationResult: ...


class DeterministicFakeModerationProvider:
    """Development/test provider. Same input always yields the same decision."""

    provider = "fake"

    def __init__(self, settings: Settings) -> None:
        self._policy_version = settings.media_moderation_policy_version

    async def moderate(self, asset: ModerationAsset) -> ModerationResult:
        caption = (asset.caption or "").lower()
        tags = {tag.lower() for tag in asset.vibe_tags}

        if REJECT_CAPTION_MARKER in caption or REJECT_TAG_MARKER in tags:
            return ModerationResult(
                decision="rejected",
                provider=self.provider,
                policy_version=self._policy_version,
                signals=[
                    ModerationSignalResult(
                        category="policy_marker_reject",
                        confidence=Decimal("99.00"),
                        model_version="deterministic-1",
                    )
                ],
            )
        if REVIEW_CAPTION_MARKER in caption or REVIEW_TAG_MARKER in tags:
            return ModerationResult(
                decision="manual_review",
                provider=self.provider,
                policy_version=self._policy_version,
                signals=[
                    ModerationSignalResult(
                        category="policy_marker_review",
                        confidence=Decimal("55.00"),
                        model_version="deterministic-1",
                    )
                ],
            )
        if not asset.derivative_paths:
            # Nothing sanitised to look at means nothing was approved.
            return ModerationResult(
                decision="manual_review",
                provider=self.provider,
                policy_version=self._policy_version,
                signals=[
                    ModerationSignalResult(
                        category="no_reviewable_derivative",
                        confidence=Decimal("100.00"),
                        model_version="deterministic-1",
                    )
                ],
            )
        return ModerationResult(
            decision="approved",
            provider=self.provider,
            policy_version=self._policy_version,
            signals=[
                ModerationSignalResult(
                    category="no_policy_violation",
                    confidence=Decimal("1.00"),
                    model_version="deterministic-1",
                )
            ],
        )

    async def start_video_moderation(self, asset: ModerationAsset) -> str:
        raise NotImplementedError(
            "Asynchronous video moderation arrives with the managed provider."
        )

    async def get_video_moderation(self, job_id: str) -> ModerationResult:
        raise NotImplementedError(
            "Asynchronous video moderation arrives with the managed provider."
        )


def build_moderation_provider(settings: Settings) -> ModerationProvider:
    if settings.media_moderation_provider == "fake":
        if settings.app_env not in {"development", "test"}:
            msg = (
                "MEDIA_MODERATION_PROVIDER=fake is not permitted when APP_ENV is "
                f"{settings.app_env!r}."
            )
            raise RuntimeError(msg)
        return DeterministicFakeModerationProvider(settings)
    msg = (
        f"Moderation provider {settings.media_moderation_provider!r} is not implemented "
        "in this phase. Media would never be publishable."
    )
    raise RuntimeError(msg)
